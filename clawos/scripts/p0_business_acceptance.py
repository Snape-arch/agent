"""Full application HTTP workflows on disposable inputs and a real local index.

No provider calls, replaced services, daily databases or production restarts.
Synthetic inputs prove workflow mechanics, not research/teaching/model quality.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'scripts'))
from application_runtime import clean_environment,verify,digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',required=True)
    parser.add_argument('--port',type=int,default=18947)
    parser.add_argument('--embedding-model',required=True)
    parser.add_argument('--hold-preview',type=int,default=0)
    args=parser.parse_args()
    if not 1024<=args.port<=65535 or not 0<=args.hold_preview<=900:parser.error('Invalid QA port/hold duration')
    executable=Path(args.python).resolve(strict=True);receipt=verify(executable)
    embedding=Path(args.embedding_model).resolve(strict=True)
    root=PROJECT/'output'/'p0-business'/uuid.uuid4().hex;root.mkdir(parents=True)
    source_before={str(p):digest(p) for p in (PROJECT/'memoryos.db',PROJECT/'skills/skill_registry.jsonl') if p.is_file()}
    config=dict(model_provider=dict(provider='qwen',base_url='http://127.0.0.1:18949/v1',model='disabled-acceptance',api_key='',requires_api_key=False),
        mtclaw=dict(enabled=False),vector_store=dict(provider='chroma',chroma_dir=str(root/'vectors'),
        embedding_provider='qwen3',embedding_model_path=str(embedding),embedding_dim=1024))
    (root/'config.json').write_text(json.dumps(config),encoding='utf-8')
    env=clean_environment();env.update(CLAWOS_CONFIG_PATH=str(root/'config.json'),CLAWOS_DATA_DIR=str(root),
        CLAWOS_MEMORY_DB=str(root/'memory.db'),CLAWOS_OUTPUT_DIR=str(root/'output'),FEISHU_LIVE='false',
        CLAWOS_EMBEDDING_DEVICE='cpu',OMP_NUM_THREADS='2')
    import httpx
    from reportlab.pdfgen import canvas
    from application_runtime import atomic_json
    checks={};instances=[];processes=[];state={};error='';started=time.monotonic()
    def record(name,passed):
        checks[name]=bool(passed)
        atomic_json(root/'progress.json',dict(checks=checks,elapsed_seconds=time.monotonic()-started))
        if not passed:raise AssertionError(name)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',args.port))
    code="""import sys,threading,uvicorn,faulthandler,time
from pathlib import Path
faulthandler.enable()
faulthandler.dump_traceback_later(120,repeat=True)
import clawos_server
server=uvicorn.Server(uvicorn.Config(clawos_server.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='info'))
def stop():
    # A blocking CRT stdin read in another thread can interfere with lazy native
    # library initialization on Windows. This owned file avoids console I/O.
    while not Path(sys.argv[2]).is_file():time.sleep(.1)
    server.should_exit=True
threading.Thread(target=stop,daemon=True).start()
server.run()
"""
    with httpx.Client(base_url=f'http://127.0.0.1:{args.port}',trust_env=False,timeout=180) as client:
        def api(method,path,**kwargs):
            response=client.request(method,path,**kwargs)
            if response.status_code>=400:raise AssertionError(f'{method} {path}: {response.status_code} {response.text[:700]}')
            return response.json()
        try:
            for phase in range(2):
                with (root/f'app-{phase}.log').open('wb') as log:
                    stop_file=root/f'stop-{phase}.txt'
                    process=subprocess.Popen([str(executable),'-u','-c',code,str(args.port),str(stop_file)],cwd=PROJECT,
                        env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    processes.append(dict(pid=process.pid,started_utc=time.time(),executable=str(executable)))
                    atomic_json(root/'owned-processes.json',dict(processes=processes,port=args.port,workspace=str(root)))
                    try:
                        deadline=time.monotonic()+180
                        while True:
                            if process.poll() is not None:raise RuntimeError('Owned application failed during startup; inspect app log')
                            try:
                                response=client.get('/health',timeout=3)
                                health=response.json()
                                if response.is_success and health.get('core_ready'):break
                            except (httpx.HTTPError,ValueError):pass
                            if time.monotonic()>deadline:raise TimeoutError('Application startup exceeded 180 seconds')
                            time.sleep(.4)
                        instances.append(health['release'])
                        record(f'actual_chroma_qwen_ready_{phase}',health['vector']['provider']=='chroma' and health['vector']['embedding_provider']=='qwen3' and not health['vector']['fallback_reason'])
                        if phase==0:
                            # Capture -> searchable knowledge and actual embedding/index write.
                            item=api('POST','/api/knowledge',json=dict(title='P0 evidence fixture',content='Evidence supports conclusions under explicitly stated conditions.',source='synthetic:p0-business'))['item']
                            state['knowledge']=item['id']
                            rows=api('GET','/api/knowledge/search',params=dict(q='evidence'))['items']
                            record('knowledge_capture_and_search',any(r['id']==item['id'] for r in rows))
                            # Upload and read a real, explicitly synthetic multi-page PDF.
                            buf=io.BytesIO();pdf=canvas.Canvas(buf)
                            for heading,text in [('Abstract','This synthetic fixture evaluates evidence checks.'),('Methodology','We use 200 claims and three independent annotators.'),('Results','Citation accuracy is 85 percent on this synthetic dataset.'),('Limitations','This synthetic result does not establish performance for real users.')]:
                                pdf.setFont('Helvetica-Bold',16);pdf.drawString(50,770,heading)
                                pdf.setFont('Helvetica',11);pdf.drawString(50,730,text);pdf.showPage()
                            pdf.save();raw=buf.getvalue()
                            upload=api('POST','/api/documents/upload',files={'files':('synthetic-evidence.pdf',raw,'application/pdf')})
                            record('pdf_upload_and_parse',upload['count']==1 and not upload['errors'])
                            doc=upload['documents'][0];state['document']=doc['id']
                            downloaded=client.get(f'/api/documents/{doc["id"]}/source');downloaded.raise_for_status()
                            record('original_pdf_download_exact',hashlib.sha256(downloaded.content).digest()==hashlib.sha256(raw).digest())
                            chunks=api('GET',f'/api/documents/{doc["id"]}/chunks')['chunks']
                            record('reader_chunks_and_citations',bool(chunks) and all(c.get('citation') for c in chunks))
                            # Rich document save/reload/export and actual stale-write rejection.
                            blocks=[dict(id='p',type='paragraph',text='Synthetic source-bound annotation.'),dict(id='code',type='code',text='print(2 + 3)',language='python'),dict(id='table',type='table',cells=[['Claims','Accuracy'],['200','85%']]),dict(id='math',type='math',text=r'P(A\mid B)',caption='Conditional probability')]
                            note=api('POST','/api/academy/learning/documents',json=dict(title='P0 reading note',blocks=blocks,context=f'doc:{doc["id"]}'))
                            state['note']=note['id'];note_payload=dict(title=note['title'],blocks=note['blocks'],version=note['version'])
                            updated=api('PUT',f'/api/academy/learning/documents/{note["id"]}',json=note_payload)
                            conflict=client.put(f'/api/academy/learning/documents/{note["id"]}',json=note_payload)
                            record('rich_note_roundtrip_and_conflict',conflict.status_code==409 and len(updated['blocks'])==4)
                            exported=client.get(f'/api/academy/learning/documents/{note["id"]}/export');exported.raise_for_status()
                            record('rich_note_export',b'```python' in exported.content and b'Claims' in exported.content)
                            # Real report generation and registered immutable downloads, no model.
                            report=api('POST','/api/workspace/research/learning-analysis',json=dict(library_document_id=doc['id'],output_dir=str(root/'reports'),formats=['markdown','pdf','json'],model_assisted=False,depth=3,question_count=12))
                            state['artifacts']={a['download_url']:a['sha256'] for a in report['artifacts']}
                            record('report_three_formats',len(state['artifacts'])==3 and bool(report['analysis']['source_index']))
                            for path,expected in state['artifacts'].items():
                                result=client.get(path);result.raise_for_status()
                                record('download_'+expected[:12],hashlib.sha256(result.content).hexdigest()==expected)
                            # Enqueue/claim/execute through the actual durable task service.
                            task=api('POST','/api/tasks/jobs/report',json=dict(library_document_id=doc['id'],output_dir=str(root/'task-reports'),formats=['markdown','json'],question_count=12,depth=3))['task']
                            state['task']=task['id'];tick=api('POST','/api/tasks/worker/tick',json=dict(worker_id='owned-p0-acceptance',max_attempts=1))
                            detail=api('GET',f'/api/tasks/{task["id"]}')
                            record('durable_task_executed',detail['task']['status']=='succeeded')
                            # Reader checkpoint and exact-source retrieval.
                            checkpoint=api('POST','/api/academy/paper/checkpoint',json=dict(document_id=doc['id'],reading=dict(page=3)))
                            state['checkpoint']=checkpoint['run']['run_id']
                            found=api('GET','/api/documents/search',params=dict(q='annotators'))
                            record('source_search_with_citation',any(c['document_id']==doc['id'] and c.get('citation') for c in found['chunks']))
                            # Whole-book manual graph workflow with source-bound nodes.
                            textbook=b'# Evidence\nEvidence supports conclusions.\n# Conditions\nMissing evidence requires refusal.'
                            material=api('POST','/api/academy/learning/materials',files={'file':('textbook.md',textbook,'text/markdown')})['document'];state['material']=material['id']
                            base=f'/api/academy/learning/lab/books/{material["id"]}'
                            lab=api('GET',base);graph=lab['graph'];chapters=graph['index']['chapters'];passage=material['payload']['passages'][0]
                            nodes=[dict(id='evidence',title='Evidence',chapter=chapters[0]['id'],explanation='Source-based fixture.',source=dict(citation=passage['id'],quote='Evidence supports conclusions.')),dict(id='conditions',title='Conditions',chapter=chapters[1]['id'],explanation='Source-based fixture.',source=dict(citation=passage['id'],quote='Missing evidence requires refusal.'))]
                            graph_value=dict(nodes=nodes,edges=[],covered_chapters=[c['id'] for c in chapters])
                            api('POST',base+'/graph',json=dict(graph=graph_value,version=graph['version'],revision=graph['revision']))
                            route=api('GET',base+'/route',params=dict(goal='conditions'))
                            record('textbook_source_graph_and_route',[n['id'] for n in route['nodes']]==['conditions'])
                        else:
                            record('knowledge_survives_restart',any(r['id']==state['knowledge'] for r in api('GET','/api/knowledge')['items']))
                            record('rich_document_survives_restart',len(api('GET',f'/api/academy/learning/documents/{state["note"]}')['blocks'])==4)
                            record('task_completion_survives_restart',api('GET',f'/api/tasks/{state["task"]}')['task']['status']=='succeeded')
                            for path,expected in state['artifacts'].items():
                                response=client.get(path);response.raise_for_status()
                                record('persistent_download_'+expected[:12],hashlib.sha256(response.content).hexdigest()==expected)
                            record('textbook_graph_survives_restart',len(api('GET',f'/api/academy/learning/lab/books/{state["material"]}')['graph']['nodes'])==2)
                            checkpoint=api('GET',f'/api/academy/paper/checkpoints/{state["checkpoint"]}')
                            record('reading_checkpoint_survives_restart',checkpoint['checkpoint']['reading']['page']==3)
                            record('new_process_same_source',instances[0]['instance_id']!=instances[1]['instance_id'] and instances[0]['startup_source_digest']==instances[1]['startup_source_digest'])
                            marker=root/'RECOVERY_IN_PROGRESS.json'
                            atomic_json(marker,dict(phase='acceptance-only'))
                            try:record('health_rejects_incomplete_recovery',api('GET','/health')['core_ready'] is False)
                            finally:marker.unlink()
                            record('health_returns_ready_after_own_marker_removed',api('GET','/health')['core_ready'] is True)
                            atomic_json(root/'state.json',state)
                            if args.hold_preview:
                                print(json.dumps(dict(preview_ready=True,url=str(client.base_url),workspace=str(root))),flush=True)
                                end=time.monotonic()+args.hold_preview
                                while time.monotonic()<end and process.poll() is None:time.sleep(.5)
                    finally:
                        if process.poll() is None:
                            stop_file.write_text('Stop this owned preview.',encoding='utf-8')
                            try:process.wait(timeout=40)
                            except subprocess.TimeoutExpired:
                                # This exact Popen handle is exclusively owned by this probe.
                                # Preserve failure evidence instead of leaving a hidden QA server.
                                process.kill();process.wait(timeout=15)
                        record(f'clean_shutdown_{phase}',process.returncode==0)
            # Windows can time out instead of refusing a closed loopback port.
            # A timeout is not evidence of closure: require an actual exclusive bind.
            with socket.socket() as released:
                released.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                released.bind(('127.0.0.1',args.port))
            closed=True
            record('owned_port_closed',closed)
            blocked=root/'blocked-start';blocked.mkdir()
            (blocked/'RECOVERY_IN_PROGRESS.json').write_text('{"phase":"interrupted"}')
            blocked_env=dict(env,CLAWOS_DATA_DIR=str(blocked),CLAWOS_MEMORY_DB=str(blocked/'must-not-exist.db'))
            with (root/'blocked-start.log').open('wb') as log:
                refused=subprocess.run([str(executable),'-u',str(PROJECT/'clawos_server.py'),'--host','127.0.0.1','--port',str(args.port)],cwd=PROJECT,env=blocked_env,
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            record('incomplete_recovery_refused_before_database_open',refused.returncode!=0 and not (blocked/'must-not-exist.db').exists() and b'Workspace contains an incomplete' in (root/'blocked-start.log').read_bytes())
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)
        for path,before in source_before.items():record('unchanged_'+Path(path).name,digest(path)==before)
    result=dict(passed=not error and all(checks.values()),checks=checks,error=error,instances=instances,processes=processes,
        runtime_lock_sha256=receipt['lock_sha256'],elapsed_seconds=time.monotonic()-started,
        synthetic_inputs=True,full_application_lifespan=True,real_http=True,actual_chroma_qwen=True,
        model_generation_calls=0,browser_verified=False,model_quality_verified=False,production_restarted=False)
    atomic_json(root/'report.json',result)
    print(json.dumps(dict(passed=result['passed'],error=error,checks=checks,report=str(root/'report.json'))))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
