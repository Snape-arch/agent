"""Real authenticated HTTP/SSE soak against an owned, isolated, model-free preview.

Writes only synthetic documents. A wall-clock run is never replaced by simulated
time. Progress is atomic JSON, without invites, cookies or credentials.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import httpx
from document_soak_evidence import Coverage, execution_request, source_fingerprints

ROOT=Path(__file__).resolve().parents[1]


async def verify_revocation(owner, guest, nid, identity, final):
    """Revoke a real authenticated, already-open SSE stream as well as HTTP access."""
    path=f'/api/academy/learning/documents/{nid}'
    async with guest.stream('GET',path+'/events') as response:
        response.raise_for_status()
        lines=response.aiter_lines()
        await asyncio.wait_for(anext(lines),10)  # Must be connected before revoke.
        revoked=await owner.post(f'/api/collaboration/documents/{nid}/revoke',json=dict(user_id=identity['id']))
        revoked.raise_for_status()
        async def denied_and_closed():
            denied=False
            async for line in lines:
                if line=='event: denied':denied=True
                elif denied and line.startswith('event:'):return False
            return denied
        stream_pass=await asyncio.wait_for(denied_and_closed(),10)
    responses=[await guest.get(path),await guest.put(path,json=final),
               await guest.post(f'/api/collaboration/documents/{nid}/presence',json=dict(block_id='writer-0'))]
    return dict(stream_denied_and_closed=stream_pass,read_denied=responses[0].status_code==403,
                write_denied=responses[1].status_code==403,presence_denied=responses[2].status_code==403)


async def run(args,report,write):
    url=f'http://127.0.0.1:{args.port}'
    timeout=httpx.Timeout(30,read=90)
    async with httpx.AsyncClient(base_url=url,timeout=timeout,trust_env=False) as owner:
        for attempt in range(90):
            try:
                env=(await owner.get('/api/qa/environment')).json()
                if env.get('isolated') is not True or env.get('models_enabled') is not False or env.get('session')!=args.session:
                    raise RuntimeError('Refusing writes outside the owned model-free preview')
                break
            except (httpx.ConnectError,httpx.ReadError):await asyncio.sleep(.5)
        else:raise RuntimeError('Owned preview did not start')
        blocks=[dict(id=f'writer-{i}',type='paragraph',text=f'writer {i}: 0',inline=[dict(text=f'writer {i}: 0',marks=[])]) for i in range(args.workers)]
        response=await owner.post('/api/academy/learning/documents',json=dict(title='Authenticated collaboration soak — synthetic',blocks=blocks));response.raise_for_status();doc=response.json();nid=doc['id']
        started=time.monotonic()
        expected=[0]*args.workers;pending=[None]*args.workers;latencies=[];stop=asyncio.Event();streams_stop=asyncio.Event();clients=[]
        def error(where,kind):
            report['errors_count']+=1
            if len(report['errors'])<100:report['errors'].append(dict(where=where,kind=str(kind)[:120],elapsed_seconds=round(time.monotonic()-started,2)))
        async def request(client,method,path,**kwargs):
            start=time.monotonic();response=await client.request(method,path,**kwargs);latencies.append((time.monotonic()-start)*1000)
            if len(latencies)>5000:del latencies[:1000]
            response.raise_for_status();return response.json()
        for i in range(args.workers):
            invite=await request(owner,'POST',f'/api/collaboration/documents/{nid}/invite',json=dict(role='editor'))
            client=httpx.AsyncClient(base_url=url,timeout=timeout,trust_env=False);clients.append(client)
            await request(client,'POST','/api/collaboration/join',json=dict(code=invite['code'],name=f'Soak editor {i+1}'))
        coverage=Coverage(args.workers,args.interval)
        started=coverage.started;deadline=started+args.hours*3600
        report.update(document_id=nid,status='running',started_at=datetime.now(timezone.utc).isoformat(),target_seconds=args.hours*3600)
        write()
        async def pause(seconds):
            try:await asyncio.wait_for(stop.wait(),max(.01,min(seconds,deadline-time.monotonic())))
            except asyncio.TimeoutError:pass
        async def writer(i):
            client=clients[i];await pause(i*.08)
            while time.monotonic()<deadline and not stop.is_set():
                try:
                    base=await request(client,'GET',f'/api/academy/learning/documents/{nid}');edit=deepcopy(base);edit['merge']=True
                    number=expected[i]+1;pending[i]=number;row=edit['blocks'][i];row['text']=f'writer {i}: {number}';row['inline']=[dict(text=row['text'],marks=[dict(type='bold')] if number%2 else [])]
                    saved=await request(client,'PUT',f'/api/academy/learning/documents/{nid}',json=edit)
                    if saved['blocks'][i]['inline'][0]['text']!=row['text']:raise RuntimeError('transaction_snapshot_mismatch')
                    expected[i]=number;pending[i]=None;report['writes']+=1
                    coverage.write(i)
                    await request(client,'POST',f'/api/collaboration/documents/{nid}/presence',json=dict(block_id=row['id'],cursor=dict(version=saved['version'],anchor=0,focus=min(3,len(row['text'])))))
                except Exception as exc:error(f'writer-{i}',type(exc).__name__+': '+str(exc) if not isinstance(exc,httpx.HTTPStatusError) else 'HTTP '+str(exc.response.status_code));stop.set();break
                await pause(args.interval)
        async def stream(i):
            last=0
            while time.monotonic()<deadline+10 and not streams_stop.is_set():
                async def consume():
                    nonlocal last
                    async with clients[i].stream('GET',f'/api/academy/learning/documents/{nid}/events',headers={'Last-Event-ID':str(last)}) as response:
                        response.raise_for_status();name='';data=''
                        async for line in response.aiter_lines():
                            if time.monotonic()>=deadline+10 or streams_stop.is_set():break
                            coverage.packet(i,'heartbeat')
                            if line.startswith('event:'):name=line[6:].strip()
                            elif line.startswith('data:'):data+=line[5:].strip()
                            elif not line and data:
                                value=json.loads(data)
                                if name=='document':
                                    if value['version']<=last:raise RuntimeError('non_monotonic_event')
                                    last=value['version'];report['document_events']+=1
                                elif name=='cursors':report['cursor_events']+=1
                                elif name=='denied':raise RuntimeError('unexpected_access_denial')
                                coverage.packet(i,name,value.get('version') if name=='document' else None)
                                name='';data=''
                try:await asyncio.wait_for(consume(),min(args.reconnect_seconds,max(.01,deadline+10-time.monotonic())))
                except asyncio.TimeoutError:report['controlled_reconnects']+=1;coverage.clients[i]['reconnects']+=1
                except asyncio.CancelledError:raise
                except Exception as exc:error(f'stream-{i}',type(exc).__name__);stop.set();streams_stop.set();break
        tasks=[asyncio.create_task(writer(i)) for i in range(args.workers)]+[asyncio.create_task(stream(i)) for i in range(args.workers)]
        try:
            while time.monotonic()<deadline and not stop.is_set():
                await pause(min(10,args.interval))
                before_counts=expected[:]
                current=await request(owner,'GET',f'/api/academy/learning/documents/{nid}')
                for failure in coverage.check():
                    error('continuous_coverage',failure);stop.set()
                for i,b in enumerate(current['blocks']):
                    observed=int(b['inline'][0]['text'].rsplit(': ',1)[1])
                    if not before_counts[i]<=observed<=max(expected[i],pending[i] or 0):error('integrity','independent_write_lost');stop.set()
                report['integrity_checks']+=1;report['elapsed_seconds']=round(time.monotonic()-started,2);report['version']=current['version'];report['per_editor_writes']=expected[:]
                report.update(coverage.summary())
                if source_fingerprints(ROOT)!=report['source_sha256']:
                    error('source_integrity','source_changed');stop.set()
                ordered=sorted(latencies);report['http_p95_ms']=round(ordered[int((len(ordered)-1)*.95)],2) if ordered else None
                db=ROOT/'output'/'learning-preview'/args.session/'learning.db';report['database_bytes']=db.stat().st_size if db.exists() else None
                write()
            stop.set();await asyncio.gather(*tasks[:args.workers],return_exceptions=True)
            final=await request(owner,'GET',f'/api/academy/learning/documents/{nid}')
            report['final_integrity_pass']=True
            for i,b in enumerate(final['blocks']):
                if b['inline'][0]['text']!=f'writer {i}: {expected[i]}':
                    error('final_integrity','independent_write_lost');report['final_integrity_pass']=False
            report['final_version']=final['version']
            report['final_version_pass']=final['version']==1+report['writes']
            if not report['final_version_pass']:error('final_integrity','version_write_count_mismatch')
            catchup_deadline=time.monotonic()+10
            while any(c['version']!=final['version'] for c in coverage.clients) and time.monotonic()<catchup_deadline and not streams_stop.is_set():
                await asyncio.sleep(.1)
            report['final_stream_convergence_pass']=all(c['version']==final['version'] for c in coverage.clients)
            if not report['final_stream_convergence_pass']:error('final_integrity','stream_not_converged')
            streams_stop.set()
            report['per_client']=coverage.summary()['per_client']
            # Actual revocation must also deny a previously authenticated connection.
            probe=await request(owner,'POST',f'/api/collaboration/documents/{nid}/invite',json=dict(role='editor'))
            async with httpx.AsyncClient(base_url=url,timeout=timeout,trust_env=False) as guest:
                identity=await request(guest,'POST','/api/collaboration/join',json=dict(code=probe['code'],name='Revocation probe'))
                report['revocation']=await verify_revocation(owner,guest,nid,identity,final)
                report['revocation_pass']=all(report['revocation'].values())
                if not report['revocation_pass']:error('revoke','access_not_denied')
            report['elapsed_seconds']=round(time.monotonic()-started,2);report['per_editor_writes']=expected[:]
            # Final HTTP/revocation cleanup time never counts toward load duration.
            report['source_unchanged']=source_fingerprints(ROOT)==report['source_sha256']
            report['per_client_pass']=coverage.clients_pass()
            if not report['per_client_pass']:error('client_coverage','missing_client_activity')
            if not report['source_unchanged']:error('source_integrity','source_changed')
            report['status']='passed' if not report['errors_count'] and report['covered_seconds']>=args.hours*3600 and report['per_client_pass'] and report['source_unchanged'] else 'failed'
            report['finished_at']=datetime.now(timezone.utc).isoformat();write()
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            for client in clients:await client.aclose()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--hours',type=float,default=48);parser.add_argument('--workers',type=int,default=12);parser.add_argument('--interval',type=float,default=30);parser.add_argument('--reconnect-seconds',type=float,default=300);parser.add_argument('--port',type=int,default=18915);parser.add_argument('--session',default='document-soak-'+uuid.uuid4().hex);parser.add_argument('--out');args=parser.parse_args()
    if not .001<=args.hours<=168 or not 2<=args.workers<=24 or not .2<=args.interval<=30 or not 1<=args.reconnect_seconds<=3600 or not 1024<=args.port<=65535 or not re.fullmatch(r'[a-z0-9-]{1,64}',args.session):parser.error('Invalid bounded soak options')
    out=Path(args.out or ROOT/'output'/args.session).resolve()
    if not out.is_relative_to((ROOT/'output').resolve()):parser.error('Reports must stay in ignored clawos/output')
    if out.exists() or (ROOT/'output'/'learning-preview'/args.session).exists():parser.error('Use a fresh output directory and session; previous evidence must not be overwritten')
    out.mkdir(parents=True);report=dict(status='starting',pid=os.getpid(),created_at=datetime.now(timezone.utc).isoformat(),session=args.session,port=args.port,python=sys.executable,workers=args.workers,target_seconds=args.hours*3600,errors_count=0,errors=[],writes=0,document_events=0,cursor_events=0,controlled_reconnects=0,integrity_checks=0,elapsed_seconds=0)
    report['source_sha256']=source_fingerprints(ROOT)
    def write():
        report['updated_at']=datetime.now(timezone.utc).isoformat()
        temporary=out/'progress.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,out/'progress.json')
    write()
    with (out/'preview.log').open('a',encoding='utf-8') as log:
        server=subprocess.Popen([sys.executable,str(ROOT/'scripts/learning_preview.py'),'--port',str(args.port),'--session',args.session],cwd=ROOT.parent,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        report['preview_pid']=server.pid;write()
        try:
            with execution_request() as active:
                report['windows_idle_sleep_request']=active;write()
                asyncio.run(run(args,report,write))
        except BaseException as exc:report.update(status='failed',fatal=type(exc).__name__,finished_at=datetime.now(timezone.utc).isoformat());write();raise
        finally:
            server.terminate()
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:server.kill();server.wait()
            report['preview_stopped']=server.poll() is not None;write()
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':sys.exit(main())
