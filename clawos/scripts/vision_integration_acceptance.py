"""Real loopback gateway/worker acceptance in new stores; simulator is explicitly synthetic."""
import argparse
import base64
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import httpx
import uvicorn
from services.vision_runtime import VisionRuntime
from services.vision_api import vision_router
from services.collaboration import direct_owner


def app_for(runtime):
    class Identity:
        def identity(self,request):
            if not direct_owner(request):raise HTTPException(403,'local preview only')
            return dict(id='local-user')
    app=FastAPI();static=Path(__file__).resolve().parents[1]/'static'
    app.include_router(vision_router(lambda:runtime,Identity,static/'vision'))
    @app.get('/academy')
    def academy():return FileResponse(static/'academy.html')
    @app.get('/academy/research')
    def research():return FileResponse(static/'academy-research.html')
    @app.get('/api/research/watch/domains')
    def domains():
        from services.research_domains import catalog
        return catalog()
    @app.get('/api/research/watch/domains/{did}')
    def domain(did:str):
        from services.research_domains import get
        return get(did)
    app.mount('/assets',StaticFiles(directory=static/'assets'))
    return app


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--port',type=int,default=18935);ap.add_argument('--preview',action='store_true')
    a=ap.parse_args()
    if a.output.exists():raise SystemExit('Use a new output directory')
    a.output.mkdir(parents=True);runtime=VisionRuntime(a.output/'runtime');app=app_for(runtime)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=a.port,access_log=False,log_level='warning'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    checks={};base=f'http://127.0.0.1:{a.port}'
    try:
        with httpx.Client(base_url=base,trust_env=False,timeout=30) as c:
            deadline=time.monotonic()+10
            while not server.started:
                if time.monotonic()>deadline:raise TimeoutError('preview start timeout')
                time.sleep(.05)
            assert not c.get('/api/vision/runtime').json()['running'];checks['lazy_start']=True
            assert c.post('/api/vision/start',json={},headers={'Origin':'https://untrusted.invalid'}).status_code==403
            assert c.get('/api/vision/runtime',headers={'Authorization':'Bearer fabricated-test'}).status_code==403
            assert c.get('/api/vision/runtime',headers={'X-Forwarded-For':'127.0.0.1'}).status_code==403;checks['origin_identity_and_forwarded_rejected']=True
            assert c.post('/api/vision/start',json={}).json()['running'];worker=runtime.process
            assert c.post('/api/vision/start',json={}).json()['running'] and runtime.process is worker;checks['idempotent_start']=True
            endpoint,_=runtime.endpoint()
            assert httpx.get(endpoint+'/api/health',trust_env=False).status_code==403;checks['worker_direct_access_denied']=True
            assert c.get('/api/vision/service/auth/me').json()['data']['userId']=='local-user'
            assert c.post('/api/vision/service/auth/bootstrap',json={}).status_code==403;checks['no_secondary_bootstrap']=True
            params=dict(learningRate=.001,batchSize=16,dropout=.2,optimizer='AdamW',epochs=3,seed=42,weightDecay=.01,mixedPrecision=False,modelDepth='base')
            response=c.post('/api/vision/service/jobs',json=dict(name='整合验收 · 明确模拟实验',kind='single',configs=[params],concurrency=1,trainingProvider='simulator'))
            assert response.status_code==201,response.status_code
            job=response.json()['data'];rid=job['runIds'][0]
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                run=c.get('/api/vision/service/runs/'+rid).json()['data']
                if run['status'] in ('completed','failed'):break
                time.sleep(.1)
            assert run['status']=='completed' and len(run['metrics'])==3 and run['params']['_execution']['synthetic'] is True;checks['simulator_job_metrics_completion']=True
            content=dict(schema='clawos.reading-context.v1',domain='rag',readingPackVersion='domain-reading.v1',sourcePage='/academy/research#domain-heading',kind='user_selected_reading_reference',paperReproductionVerified=False)
            r=c.post('/api/vision/service/runs/'+rid+'/artifacts',json=dict(name='clawos-reading-context.json',type='json',mimeType='application/json',content=content))
            assert r.status_code==201,r.status_code;checks['reading_context_artifact_saved']=True
            with c.stream('GET','/api/vision/service/runs/'+rid+'/stream?incremental=1&after=0') as response:
                assert response.status_code==200
                frames='\n'.join(response.iter_lines());assert 'event: run-delta' in frames and rid in frames
                assert 'access-control-allow-origin' not in response.headers;checks['real_sse_final_frame_and_cors_stripped']=True
            dataset=c.post('/api/vision/service/datasets',json=dict(name='整合验收数据',format='csv',content='step,value\n1,0.3\n2,0.5\n3,0.7\n'))
            assert dataset.status_code==201,dataset.status_code
            did=dataset.json()['data']['id'];assert dataset.json()['data']['rowCount']==3;checks['csv_dataset_ingestion']=True
            mesh=b'o integration_triangle\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'
            asset=c.post('/api/vision/service/model-assets',json=dict(name='integration-triangle.obj',format='obj',content=base64.b64encode(mesh).decode()))
            assert asset.status_code==201,asset.status_code
            aid=asset.json()['data']['id']
            part=c.get('/api/vision/service/model-assets/'+aid+'/content',headers={'Range':'bytes=0-15'})
            assert part.status_code==206 and len(part.content)==16 and part.headers.get('content-range','').startswith('bytes 0-15/');checks['real_asset_range_stream']=True
            assert c.post('/api/vision/stop',json={}).json()['running'] is False and worker.poll() is not None;checks['owned_stop']=True
            assert c.post('/api/vision/start',json={}).json()['running'];assert runtime.process.pid!=worker.pid
            restored=c.get('/api/vision/service/runs/'+rid).json()['data'];assert restored['status']=='completed' and any(x['name']=='clawos-reading-context.json' for x in restored['artifacts'])
            assert c.get('/api/vision/service/datasets/'+did).status_code==200;checks['restart_persistence']=True
            assert c.get('/academy/vision/').status_code==200;checks['built_frontend_served']=True
            report=dict(passed=True,checks=checks,run_id=rid,dataset_id=did,metrics=3,model_calls=0,real_training=False,
                boundary='New isolated stores, actual loopback HTTP/SSE and worker process restart. Metrics are from the explicit simulator, not real model training, scientific reproduction, multi-user or long-duration acceptance.')
            (a.output/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)
        if a.preview:
            while thread.is_alive():thread.join(timeout=1)
    finally:
        runtime.close();server.should_exit=True;thread.join(timeout=5)


if __name__=='__main__':main()
