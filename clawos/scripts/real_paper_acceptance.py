"""Real public PDFs, full application lifecycle, explicit local model and frozen facts.

Reports selected-fact coverage and adversarial local normalization controls
separately. This is not independent held-out semantic evaluation or teaching proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import uuid

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
sys.path.insert(0,str(PROJECT/'scripts'))
from application_runtime import atomic_json,clean_environment,digest,verify
from p0_business_acceptance import local_model_endpoint
from services.grounded_paper_report import GroundedPaperReport,REPORT_SECTION_KEYS


def fact_coverage(report,chunks,facts):
    """Independent regex anchors, not the production numeric normalizer."""
    sources={row['citation']:row.get('content','') for row in chunks}
    rows=[row for key in REPORT_SECTION_KEYS for row in report.get(key,[]) if row.get('status')=='supported']
    results={}
    for fact in facts:
        matches=[]
        for row in rows:
            if not all(re.search(pattern,row.get('text',''),re.I) for pattern in fact['patterns']):continue
            evidence=' '.join(sources.get(c,'') for c in row.get('citations',[]))
            if all(re.search(pattern,evidence,re.I) for pattern in fact['source_patterns']):matches.append(row)
        results[fact['key']]=bool(matches)
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--python',required=True,type=Path)
    p.add_argument('--model-url',required=True,type=local_model_endpoint)
    p.add_argument('--embedding-model',required=True,type=Path)
    p.add_argument('--sources',required=True,type=Path)
    p.add_argument('--port',type=int,default=18942)
    args=p.parse_args()
    import httpx
    verify(args.python.resolve(strict=True))
    manifest_path=PROJECT/'benchmarks/real_paper_quality_v1.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for paper in manifest['papers']:
        if digest(args.sources/(paper['key']+'.pdf'))!=paper['sha256']:raise ValueError('Source fingerprint differs: '+paper['key'])
    with httpx.Client(trust_env=False,timeout=15) as client:
        response=client.get(args.model_url+'/models');response.raise_for_status();model=response.json()['data'][0]['id']
    root=PROJECT/'output'/'real-paper-quality'/uuid.uuid4().hex;root.mkdir(parents=True)
    protected={str(path):digest(path) for path in (PROJECT/'memoryos.db',PROJECT/'skills/skill_registry.jsonl')}
    config=dict(model_provider=dict(provider='qwen',base_url=args.model_url,model=model,api_key='',requires_api_key=False),mtclaw=dict(enabled=False),
                vector_store=dict(provider='chroma',chroma_dir=str(root/'vectors'),embedding_provider='qwen3',embedding_model_path=str(args.embedding_model.resolve(strict=True)),embedding_dim=1024))
    atomic_json(root/'config.json',config)
    env=clean_environment();env.update(CLAWOS_CONFIG_PATH=str(root/'config.json'),CLAWOS_DATA_DIR=str(root),CLAWOS_MEMORY_DB=str(root/'memory.db'),CLAWOS_OUTPUT_DIR=str(root/'output'),FEISHU_LIVE='false',CLAWOS_EMBEDDING_DEVICE='cpu')
    with socket.socket() as listener:listener.bind(('127.0.0.1',args.port))
    code="""import sys,threading,time,uvicorn
from pathlib import Path
import clawos_server
server=uvicorn.Server(uvicorn.Config(clawos_server.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='info'))
def stop():
    while not Path(sys.argv[2]).exists():time.sleep(.1)
    server.should_exit=True
threading.Thread(target=stop,daemon=True).start()
server.run()
"""
    before={str(path.relative_to(PROJECT)):digest(path) for path in (Path(__file__),PROJECT/'services/grounded_paper_report.py',PROJECT/'services/paper_numeric_evidence.py',PROJECT/'services/document_index_worker.py',PROJECT/'memoryos/services/vector_store.py',PROJECT/'workspace_services.py',PROJECT/'clawos_server.py',manifest_path)}
    checks={};results=[];error='';indexing_final=None;start=time.monotonic();stop=root/'stop-app'
    with (root/'app.log').open('wb') as log:
        process=subprocess.Popen([str(args.python.resolve()),'-u','-c',code,str(args.port),str(stop)],cwd=PROJECT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        atomic_json(root/'owned-process.json',dict(pid=process.pid,started_utc=time.time(),port=args.port,python=str(args.python)))
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{args.port}',trust_env=False,timeout=180) as client:
                deadline=time.monotonic()+180
                while True:
                    if process.poll() is not None:raise RuntimeError('Owned application exited')
                    try:
                        health=client.get('/health',timeout=3).json()
                        if health.get('core_ready'):break
                    except (httpx.HTTPError,ValueError):pass
                    if time.monotonic()>deadline:raise TimeoutError('Startup budget exceeded')
                    time.sleep(.4)
                checks['actual_embeddings_no_fallback']=health['vector']['provider']=='chroma' and health['vector']['embedding_provider']=='qwen3' and not health['vector']['fallback_reason']
                for paper in manifest['papers']:
                    at=time.monotonic();raw=(args.sources/(paper['key']+'.pdf')).read_bytes()
                    upload_at=time.monotonic()
                    upload=client.post('/api/documents/upload',files={'files':(paper['key']+'.pdf',raw,'application/pdf')});upload.raise_for_status()
                    upload_seconds=round(time.monotonic()-upload_at,3)
                    document=upload.json()['documents'][0];mid=document['id']
                    chunks=[];offset=0
                    while True:
                        page=client.get(f'/api/documents/{mid}/chunks',params=dict(limit=100,offset=offset));page.raise_for_status();page=page.json()
                        chunks.extend(page['chunks'])
                        if not page.get('has_more'):break
                        if page['next_offset']<=offset:raise ValueError('Chunk pagination did not advance')
                        offset=page['next_offset']
                    response=client.post('/api/workspace/research/learning-analysis',json=dict(library_document_id=mid,output_dir=str(root/paper['key']),formats=['markdown','pdf','json'],model_assisted=True,depth=3,question_count=12))
                    try:response_payload=response.json()
                    except ValueError:response_payload=dict(http_status=response.status_code,non_json=True)
                    atomic_json(root/(paper['key']+'-response.json'),response_payload)
                    response.raise_for_status();payload=response.json();report=payload['analysis']
                    facts=fact_coverage(report,chunks,paper['facts'])
                    local=dict(model_no_fallback=report['mode']=='model_assisted' and payload['report']['metadata']['model']['ok'] is True,
                               original_source_exact=hashlib.sha256(client.get(f'/api/documents/{mid}/source').content).hexdigest()==paper['sha256'],
                               citations_bound=bool(report['source_index']) and all(c['citation'] in {row['citation'] for row in chunks} for c in report['source_index']),
                               selected_facts=all(facts.values()))
                    # One invented result with a legitimate citation is a negative control,
                    # never a model-generated outcome or an external blind test.
                    citation=next(iter(report['source_index']),{}).get('citation')
                    bundle=dict(document=dict(id=mid,title=paper['key']),allowed_citations={row['citation']:row.get('content','') for row in chunks})
                    forged=GroundedPaperReport.normalize(dict(findings=[dict(text='The result is 9999.12345 percent.',citations=[citation],status='supported')]),bundle,mode='model_assisted')
                    local['invented_number_not_supported']=bool(citation) and forged['findings'][0]['status']!='supported'
                    row=dict(key=paper['key'],document_id=mid,upload_seconds=upload_seconds,upload_http_status=upload.status_code,
                             indexing=upload.json().get('indexing'),seconds=round(time.monotonic()-at,3),checks=local,facts=facts,passed=all(local.values()))
                    results.append(row);atomic_json(root/'progress.json',dict(results=results));print(json.dumps(row),flush=True)
                index_response=client.get('/api/documents/indexing');index_response.raise_for_status()
                indexing_final=index_response.json()
        except Exception as exc:error=type(exc).__name__+': '+str(exc)
        finally:
            if process.poll() is None:
                stop.write_text('Stop this owned app.')
                try:process.wait(timeout=40)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=15)
    checks['owned_app_clean_shutdown']=process.returncode==0
    checks['protected_files_unchanged']=all(digest(path)==value for path,value in protected.items())
    checks['source_unchanged']=all(digest(PROJECT/path)==value for path,value in before.items())
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);listener.bind(('127.0.0.1',args.port));checks['owned_port_released']=True
    result=dict(passed=not error and len(results)==len(manifest['papers']) and all(row['passed'] for row in results) and all(checks.values()),error=error,checks=checks,results=results,
                source_fingerprints=before,manifest_sha256=digest(manifest_path),elapsed_seconds=round(time.monotonic()-start,3),synthetic_inputs=False,
                indexing_final=indexing_final,index_completion_verified=bool(indexing_final and indexing_final.get('state')=='ready' and indexing_final.get('pending')==0 and indexing_final.get('failed')==0),
                selected_public_papers=True,independent_heldout=False,semantic_entailment_verified=False,teacher_calibration_verified=False,browser_verified=False,production_restarted=False)
    atomic_json(root/'report.json',result);print(json.dumps(dict(passed=result['passed'],error=error,report=str(root/'report.json'))))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
