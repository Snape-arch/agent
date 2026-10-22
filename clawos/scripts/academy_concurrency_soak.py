"""Isolated reproducible concurrency/rollback/backup/vector soak. Never opens a live DB."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.academy_documents import AcademyDocuments,DocumentConflict
from services.academy_materials import AcademyMaterials
from services.maintenance_service import MaintenanceService
from services.recovery_bundle import RecoveryBundle
from memoryos.services.vector_store import MemoryVectorStore

def percentile(rows,p):
    values=sorted(rows)
    return round(values[min(len(values)-1,math.ceil(len(values)*p)-1)],2) if values else 0

def crash(db):
    import os
    s=MemoryStore(db)
    with s.transaction() as c:
        c.execute("INSERT INTO profiles(category,key,value) VALUES ('soak','uncommitted-crash','must roll back')")
        os._exit(23)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seconds',type=int,default=900)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--crash-db',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.crash_db:crash(args.crash_db);return
    if not 10<=args.seconds<=86400 or not 2<=args.workers<=32:parser.error('seconds 10–86400, workers 2–32')
    root=Path(__file__).resolve().parents[1]/'output'/'concurrency-soak'/uuid.uuid4().hex
    root.mkdir(parents=True);db=root/'memory.db';store=MemoryStore(str(db))
    materials=AcademyMaterials(store,root/'output'/'academy-materials')
    material=materials.upload('soak.md',b'# Evidence\nEvidence supports conclusions.\n# Boundaries\nMissing evidence requires refusal.')
    mid=material['document']['id'];notes=AcademyDocuments(store)
    shared=notes.save(dict(title='shared',blocks=[dict(id='p',type='paragraph',text='shared fixture')]))
    ops=MaintenanceService(store=store,db_path=db,base_dir=root,config={})
    vectors=MemoryVectorStore(str(db),provider='lightweight',embedding_provider='hash')
    deadline=time.monotonic()+args.seconds;lock=threading.Lock();metrics=dict(writes=0,conflicts=0,crashes=0,vector_checks=0,backups=0,errors=[],latencies=[])
    def worker(number):
        local=MemoryStore(str(db));documents=AcademyDocuments(local)
        note=documents.save(dict(title='worker-'+str(number),blocks=[dict(id='p',type='code',language='python',text='# Fixture only')]))
        count=0
        while time.monotonic()<deadline:
            started=time.perf_counter()
            try:
                note=documents.save({**note,'blocks':[dict(id='p',type='code',language='python',text='worker='+str(number)+'\niteration='+str(count))]},note['id'])
                with local._conn() as c:
                    c.execute("INSERT INTO academy_material_events(material_id,kind,payload) VALUES (?,'soak_event',?)",(mid,json.dumps(dict(worker=number,iteration=count))))
                # Exercise independent MemoryStore instances racing on one expected version.
                current=documents.get(shared['id'])
                try:documents.save({**current,'title':'shared-'+str(number)+'-'+str(count)},shared['id'])
                except DocumentConflict:
                    with lock:metrics['conflicts']+=1
                if count%20==0:local.add_knowledge('soak-'+str(number)+'-'+str(count),'Evidence condition requires a source. iteration '+str(count),source='isolated-soak')
                count+=1
                with lock:
                    metrics['writes']+=1
                    if len(metrics['latencies'])<100000:metrics['latencies'].append((time.perf_counter()-started)*1000)
            except Exception as e:
                with lock:metrics['errors'].append(dict(worker=number,error=type(e).__name__+': '+str(e)))
            time.sleep(.02)
        return count
    counts=[];start=time.monotonic();next_crash=start+15;next_backup=start+30;next_vector=start+5;next_progress=start+30;latest_bundle=None
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(worker,n) for n in range(args.workers)]
        while time.monotonic()<deadline:
            now=time.monotonic()
            try:
                if now>=next_crash:
                    child=subprocess.run([sys.executable,__file__,'--crash-db',str(db)],capture_output=True,timeout=20)
                    if child.returncode!=23:raise RuntimeError('Fault child did not exit at the intended transaction boundary')
                    with store._conn() as c:
                        if c.execute("SELECT COUNT(*) FROM profiles WHERE key='uncommitted-crash'").fetchone()[0]:raise RuntimeError('Uncommitted crash transaction leaked')
                    metrics['crashes']+=1;next_crash=now+60
                if now>=next_vector:
                    stats=vectors.refresh()
                    metrics['vector_checks']+=1;next_vector=now+15
                if now>=next_backup:
                    latest_bundle=RecoveryBundle(ops).backup('concurrent-soak')
                    metrics['backups']+=1;next_backup=now+90
            except Exception as e:metrics['errors'].append(dict(worker='supervisor',error=type(e).__name__+': '+str(e)))
            if now>=next_progress:
                print(json.dumps(dict(elapsed=round(now-start),writes=metrics['writes'],conflicts=metrics['conflicts'],errors=len(metrics['errors']),crashes=metrics['crashes'],backups=metrics['backups'])),flush=True);next_progress=now+30
            time.sleep(.5)
        for f in futures:counts.append(f.result())
    elapsed=time.monotonic()-start
    vectors.rebuild();vector_stats=vectors.stats();vectors.close()
    final_bundle=RecoveryBundle(ops).backup('final-soak');recovery=RecoveryBundle(ops).restore_isolated(final_bundle['path'])
    with store._conn() as c:
        events=c.execute("SELECT COUNT(*) FROM academy_material_events WHERE material_id=? AND kind='soak_event'",(mid,)).fetchone()[0]
    latency=metrics.pop('latencies')
    result=dict(schema='clawos.concurrency-soak.v1',isolated=True,model_calls=0,elapsed_seconds=round(elapsed,2),workers=args.workers,
        worker_iterations=counts,**metrics,latency_ms=dict(p50=percentile(latency,.5),p95=percentile(latency,.95),p99=percentile(latency,.99)),
        learning_events=events,events_match_writes=events==metrics['writes'],health=ops.database_health(),
        vector=dict(consistent=vector_stats['consistent'],count=vector_stats['vector_count']),recovery=recovery,
        boundary='Local synthetic workload; duration is measured. Does not prove multi-day uptime, live model latency or a real embedding backend.')
    result['passed']=not result['errors'] and result['health']['ok'] and result['events_match_writes'] and result['vector']['consistent'] and recovery['ok']
    path=root/'report.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=result['passed'],elapsed_seconds=result['elapsed_seconds'],writes=result['writes'],p95_ms=result['latency_ms']['p95'],report=str(path)),ensure_ascii=False),flush=True)
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
