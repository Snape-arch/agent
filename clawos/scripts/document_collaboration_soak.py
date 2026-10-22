"""Real authenticated HTTP/SSE soak against an owned, isolated, model-free preview.

Writes only synthetic documents. A wall-clock run is never replaced by simulated
time. Progress is atomic JSON, without invites, cookies or credentials.
"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]


async def run(args,report,write):
    url=f'http://127.0.0.1:{args.port}'
    timeout=httpx.Timeout(30,read=90)
    async with httpx.AsyncClient(base_url=url,timeout=timeout) as owner:
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
        report.update(document_id=nid,status='running',started_at=datetime.now(timezone.utc).isoformat(),target_seconds=args.hours*3600)
        started=time.monotonic();deadline=started+args.hours*3600
        expected=[0]*args.workers;pending=[None]*args.workers;latencies=[];stop=asyncio.Event();clients=[]
        def error(where,kind):
            report['errors_count']+=1
            if len(report['errors'])<100:report['errors'].append(dict(where=where,kind=str(kind)[:120],elapsed_seconds=round(time.monotonic()-started,2)))
        async def request(client,method,path,**kwargs):
            start=time.monotonic();response=await client.request(method,path,**kwargs);latencies.append((time.monotonic()-start)*1000)
            if len(latencies)>5000:del latencies[:1000]
            response.raise_for_status();return response.json()
        for i in range(args.workers):
            invite=await request(owner,'POST',f'/api/collaboration/documents/{nid}/invite',json=dict(role='editor'))
            client=httpx.AsyncClient(base_url=url,timeout=timeout);clients.append(client)
            await request(client,'POST','/api/collaboration/join',json=dict(code=invite['code'],name=f'Soak editor {i+1}'))
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
                    await request(client,'POST',f'/api/collaboration/documents/{nid}/presence',json=dict(block_id=row['id'],cursor=dict(version=saved['version'],anchor=0,focus=min(3,len(row['text'])))))
                except Exception as exc:error(f'writer-{i}',type(exc).__name__+': '+str(exc) if not isinstance(exc,httpx.HTTPStatusError) else 'HTTP '+str(exc.response.status_code));stop.set();break
                await pause(args.interval)
        async def stream(i):
            last=0
            while time.monotonic()<deadline and not stop.is_set():
                async def consume():
                    nonlocal last
                    async with clients[i].stream('GET',f'/api/academy/learning/documents/{nid}/events',headers={'Last-Event-ID':str(last)}) as response:
                        response.raise_for_status();name='';data=''
                        async for line in response.aiter_lines():
                            if time.monotonic()>=deadline or stop.is_set():break
                            if line.startswith('event:'):name=line[6:].strip()
                            elif line.startswith('data:'):data+=line[5:].strip()
                            elif not line and data:
                                value=json.loads(data)
                                if name=='document':
                                    if value['version']<=last:raise RuntimeError('non_monotonic_event')
                                    last=value['version'];report['document_events']+=1
                                elif name=='cursors':report['cursor_events']+=1
                                elif name=='denied':raise RuntimeError('unexpected_access_denial')
                                name='';data=''
                try:await asyncio.wait_for(consume(),min(args.reconnect_seconds,max(.01,deadline-time.monotonic())))
                except asyncio.TimeoutError:report['controlled_reconnects']+=1
                except asyncio.CancelledError:raise
                except Exception as exc:error(f'stream-{i}',type(exc).__name__);stop.set();break
        tasks=[asyncio.create_task(writer(i)) for i in range(args.workers)]+[asyncio.create_task(stream(i)) for i in range(args.workers)]
        last_check=time.monotonic()
        try:
            while time.monotonic()<deadline and not stop.is_set():
                await pause(min(10,args.interval))
                before_counts=expected[:]
                current=await request(owner,'GET',f'/api/academy/learning/documents/{nid}')
                now=time.monotonic();gap=now-last_check;last_check=now
                report['max_check_gap_seconds']=round(max(report.get('max_check_gap_seconds',0),gap),2)
                if gap>max(60,args.interval*3):
                    error('continuous_coverage',f'monitor_gap_{gap:.1f}s');stop.set()
                for i,b in enumerate(current['blocks']):
                    observed=int(b['inline'][0]['text'].rsplit(': ',1)[1])
                    if not before_counts[i]<=observed<=max(expected[i],pending[i] or 0):error('integrity','independent_write_lost');stop.set()
                report['integrity_checks']+=1;report['elapsed_seconds']=round(time.monotonic()-started,2);report['version']=current['version'];report['per_editor_writes']=expected[:]
                ordered=sorted(latencies);report['http_p95_ms']=round(ordered[int((len(ordered)-1)*.95)],2) if ordered else None
                db=ROOT/'output'/'learning-preview'/args.session/'learning.db';report['database_bytes']=db.stat().st_size if db.exists() else None
                write()
            stop.set();await asyncio.gather(*tasks[:args.workers],return_exceptions=True)
            final=await request(owner,'GET',f'/api/academy/learning/documents/{nid}')
            for i,b in enumerate(final['blocks']):
                if b['inline'][0]['text']!=f'writer {i}: {expected[i]}':error('final_integrity','independent_write_lost')
            # Actual revocation must also deny a previously authenticated connection.
            probe=await request(owner,'POST',f'/api/collaboration/documents/{nid}/invite',json=dict(role='editor'))
            async with httpx.AsyncClient(base_url=url,timeout=timeout) as guest:
                identity=await request(guest,'POST','/api/collaboration/join',json=dict(code=probe['code'],name='Revocation probe'))
                await request(owner,'POST',f'/api/collaboration/documents/{nid}/revoke',json=dict(user_id=identity['id']))
                result=await guest.get(f'/api/academy/learning/documents/{nid}')
                report['revocation_pass']=result.status_code==403
                if not report['revocation_pass']:error('revoke','access_not_denied')
            report['elapsed_seconds']=round(time.monotonic()-started,2);report['per_editor_writes']=expected[:]
            report['status']='passed' if not report['errors_count'] and report['elapsed_seconds']>=args.hours*3600 and report['writes']>=args.workers and report['document_events'] and report['cursor_events'] else 'failed'
            report['finished_at']=datetime.now(timezone.utc).isoformat();write()
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            for client in clients:await client.aclose()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--hours',type=float,default=48);parser.add_argument('--workers',type=int,default=12);parser.add_argument('--interval',type=float,default=30);parser.add_argument('--reconnect-seconds',type=float,default=300);parser.add_argument('--port',type=int,default=18915);parser.add_argument('--session',default='document-soak-20261003');parser.add_argument('--out',default=str(ROOT/'output'/'document-soak-20261003'));args=parser.parse_args()
    if not .001<=args.hours<=168 or not 2<=args.workers<=24 or not .2<=args.interval<=30 or not 1<=args.reconnect_seconds<=3600 or not 1024<=args.port<=65535 or not re.fullmatch(r'[a-z0-9-]{1,80}',args.session):parser.error('Invalid bounded soak options')
    out=Path(args.out).resolve()
    if not out.is_relative_to((ROOT/'output').resolve()):parser.error('Reports must stay in ignored clawos/output')
    out.mkdir(parents=True,exist_ok=True);report=dict(status='starting',pid=os.getpid(),workers=args.workers,errors_count=0,errors=[],writes=0,document_events=0,cursor_events=0,controlled_reconnects=0,integrity_checks=0,elapsed_seconds=0)
    report['source_sha256']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('services/academy_documents.py','services/document_events.py','services/document_cursor.py','services/document_merge.py','services/collaboration.py')}
    def write():
        temporary=out/'progress.tmp';temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,out/'progress.json')
    write()
    with (out/'preview.log').open('a',encoding='utf-8') as log:
        server=subprocess.Popen([sys.executable,str(ROOT/'scripts/learning_preview.py'),'--port',str(args.port),'--session',args.session],cwd=ROOT.parent,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        report['preview_pid']=server.pid;write()
        try:asyncio.run(run(args,report,write))
        except BaseException as exc:report.update(status='failed',fatal=type(exc).__name__,finished_at=datetime.now(timezone.utc).isoformat());write();raise
        finally:
            server.terminate()
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:server.kill();server.wait()
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':sys.exit(main())
