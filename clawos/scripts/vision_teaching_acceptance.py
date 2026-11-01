"""Owned HTTP preview and teaching closure, using explicitly synthetic sources."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.responses import FileResponse
import httpx
import uvicorn
from memoryos.memory_store import MemoryStore
from services.academy_materials import AcademyMaterials
from services.academy_learning_lab import AcademyLearningLab
from services.academy_lab_api import lab_router
from services.vision_runtime import VisionRuntime
from services.vision_teaching import VisionTeaching, digest
from vision_integration_acceptance import app_for
from vision_teaching_replay import replay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--port',type=int,default=18937)
    parser.add_argument('--preview',action='store_true');a=parser.parse_args()
    if a.output.exists():raise SystemExit('Use a new evidence directory')
    a.output.mkdir(parents=True)
    m=AcademyMaterials(MemoryStore(str(a.output/'education.sqlite')),a.output/'materials')
    mid=m.upload('synthetic-teaching-book.md',b'# Evidence\nEvidence supports conclusions.\n# Conditions\nMissing evidence requires refusal.')['document']['id']
    lab=AcademyLearningLab(m);g=lab.graph.state(mid,'local-user');p=m.document(mid)['payload']['passages'][0]
    graph=dict(nodes=[dict(id='evidence',title='Evidence',chapter=g['index']['chapters'][0]['id'],explanation='Evidence supports conclusions.',source=dict(citation=p['id'],quote='Evidence supports conclusions.'))],edges=[],covered_chapters=[g['index']['chapters'][0]['id']])
    lab.graph.save(mid,'local-user',graph,0,g['revision'])
    service=VisionTeaching(a.output/'teaching.sqlite',lab=lambda:lab);runtime=VisionRuntime(a.output/'runtime')
    app=app_for(runtime,teaching=lambda:service)
    async def no_model(*args,**kwargs):raise RuntimeError('No model permitted in this acceptance')
    app.include_router(lab_router(lambda:lab,no_model))
    @app.get('/academy/lab')
    def education():return FileResponse(Path(__file__).resolve().parents[1]/'static/academy-lab.html')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=a.port,access_log=False,log_level='warning'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start();checks={};records=[]
    (a.output/'owned-preview.json').write_text(json.dumps(dict(pid=os.getpid(),port=a.port,script=str(Path(__file__).resolve()),
        output=str(a.output.resolve()),started=datetime.now(timezone.utc).isoformat(),experiment_worker_started=False),indent=2),encoding='utf-8')
    started=time.perf_counter()
    try:
        deadline=time.monotonic()+10
        while not server.started:
            if time.monotonic()>deadline:raise TimeoutError('Owned preview not ready')
            time.sleep(.05)
        with httpx.Client(base_url=f'http://127.0.0.1:{a.port}',trust_env=False,timeout=20) as c:
            base='/api/vision/teaching'
            assert len(c.get(base+'/catalog').json()['templates'])==3
            assert not c.get('/api/vision/runtime').json()['running'];checks['catalog_without_worker_or_model_start']=True
            for headers in ({'Origin':'https://foreign.invalid'},{'Authorization':'Bearer synthetic-test'},{'X-Forwarded-For':'127.0.0.1'}):
                assert c.get(base+'/reports',headers=headers).status_code==403
                assert c.post(base+'/reports',json={},headers=headers).status_code==403
            checks['same_owner_origin_and_forwarding_boundary']=True
            assert c.get(base+'/books').json()[0]['id']==mid
            nodes=c.get(base+'/books/'+mid+'/nodes').json();assert nodes['version']==1 and nodes['nodes'][0]['id']=='evidence'
            checks['education_node_catalog']=True
            for template,value in [('rag',True),('peft',2),('diffusion',32)]:
                data=dict(request_id='acceptance-'+template,template=template,value=value,seed=42,
                          hypothesis='Synthetic pre-run prediction: compare conditions and retain failures.',
                          binding=dict(material_id=mid,node_id='evidence',revision=g['revision'],graph_version=1) if template=='rag' else None)
                response=c.post(base+'/reports',json=data);assert response.status_code==200,response.status_code
                r=response.json();rid=r['report']['id'];records.append(rid)
                assert r['report']['result']['execution']=='real_cpu_synthetic_fixture'
                assert c.post(base+'/reports',json=data).json()['hash']==r['hash'];checks[template+'_http_and_idempotence']=True
                changed=dict(data,hypothesis=data['hypothesis']+' changed')
                assert c.post(base+'/reports',json=changed).status_code==409;checks[template+'_request_conflict']=True
                exported=c.get(base+'/reports/'+rid+'/export').json();assert exported==r and digest(exported['report'])==r['hash']
                proof=replay(exported);assert proof['passed'];checks[template+'_export_and_actual_replay']=True
                (a.output/(template+'-report.json')).write_text(json.dumps(exported,ensure_ascii=False,indent=2),encoding='utf-8')
                ref=dict(version=0,report_hash=r['hash'],observation='Synthetic observation: compare the recorded numerical differences.',explanation='Synthetic explanation: the paired arms changed one bounded control.',limitation='Synthetic fixture results are not real paper reproduction or learning effects.')
                first=c.post(base+'/reports/'+rid+'/reflections',json=ref);assert first.status_code==200
                assert first.json()['learning_record']['mastery_updated'] is False
                assert c.post(base+'/reports/'+rid+'/reflections',json=ref).status_code==409
                assert c.get(base+'/reports/'+rid+'/export?format=md').headers['content-disposition'].endswith('.md"')
            checks['reflection_append_conflicts_and_no_mastery_write']=True
            checks['private_markdown_export']=True
            lab.graph.save(mid,'local-user',graph,1,g['revision'])
            assert c.post(base+'/reports',json=dict(request_id='stale-acceptance',template='rag',value=True,seed=42,
                hypothesis='Synthetic stale source must be rejected before success.',binding=dict(material_id=mid,node_id='evidence',revision=g['revision'],graph_version=1))).status_code==409
            assert c.get(base+'/reports/'+records[0]).json()['report']['binding']['graph_version']==1
            checks['stale_graph_rejected_original_snapshot_preserved']=True
            assert c.get(base+'/reports?template=rag').json()['total']==1
            assert c.get(base+'/reports').json()['total']==3;checks['course_scoped_learning_history']=True
            restored=VisionTeaching(a.output/'teaching.sqlite',lab=lambda:lab)
            for rid in records:
                r=restored.get('local-user',rid);assert r['reflection_version']==1 and not r['learning_record']['learning_effect_verified']
            checks['new_service_instance_restores_evidence_and_reflections']=True
            assert runtime.process is None and not runtime.root.exists();checks['no_experiment_child_data_created']=True
            assert c.get('/academy/vision/').status_code==200 and c.get('/academy/lab?lesson=rag').status_code==200
            checks['compiled_workbench_and_course_entry']=True
            report=dict(passed=True,checks=checks,records=records,material_id=mid,elapsed_seconds=time.perf_counter()-started,
                        model_calls=0,experiment_worker_started=False,
                        boundary='Single-host short HTTP/SQLite/CPU exercise using synthetic teaching material; not real browser, teacher, learning-effect, paper reproduction, GPU, multi-device or sustained-load acceptance.')
            (a.output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
        if a.preview:
            while thread.is_alive():thread.join(timeout=1)
    finally:
        runtime.close();server.should_exit=True;thread.join(timeout=5)


if __name__=='__main__':main()
