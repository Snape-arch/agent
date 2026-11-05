"""Actual isolated application acceptance for the pinned RAG literature lesson.

Saved captures must include captures.json, <paper-id>.pdf / <paper-id>.html,
exact pinned public URLs, UTC capture times and raw SHA256. No model is started.
All generated material stays in a new directory below clawos/output.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'clawos'),str(ROOT/'clawos/scripts')]
from application_runtime import clean_environment
from services.research_domains import get
from services.research_learning_engine import experiment

def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def seed_captures(pdf_root,metadata_root,target):
    """Validate originals and retain their timestamps; this is capture replay."""
    pdfs={r['id']:r for r in json.loads((pdf_root/'captures.json').read_text(encoding='utf-8'))['records']}
    metadata={r['id']:r for r in json.loads((metadata_root/'captures.json').read_text(encoding='utf-8'))['records']}
    pack=get('rag')['domain'];receipt=[]
    for spec in pack['papers']+pack['supplements']:
        sid=spec['id'];pdf=pdfs[sid];meta=metadata[sid]
        raw=(pdf_root/(sid+'.pdf')).read_bytes();html=(metadata_root/(sid+'.html')).read_bytes()
        for record,body,kind in [(pdf,raw,'pdf'),(meta,html,'abs')]:
            expected='https://arxiv.org/'+kind+'/'+spec['version']
            if record['url']!=expected or record.get('final_url',expected)!=expected or sha(body)!=record['raw_sha256']:
                raise ValueError('Capture identity/hash mismatch: '+sid)
            captured=datetime.fromisoformat(record['captured'])
            if captured.tzinfo is None or captured>datetime.now(timezone.utc):raise ValueError('Capture time invalid')
        folder=target/spec['version'];folder.mkdir(parents=True,exist_ok=False)
        (folder/'paper.pdf').write_bytes(raw);(folder/'metadata.html').write_bytes(html)
        capture=dict(version=spec['version'],pdf_sha256=sha(raw),metadata_sha256=sha(html),pdf_url=pdf['url'],metadata_url=meta['url'],
                     captured=pdf['captured'],pdf_captured=pdf['captured'],metadata_captured=meta['captured'],capture_mode='verified_capture_replay')
        save(folder/'capture.json',capture);receipt.append(dict(id=sid,**capture))
    return receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--pdf-captures',required=True,type=Path)
    parser.add_argument('--metadata-captures',required=True,type=Path)
    parser.add_argument('--port',type=int,default=18945)
    parser.add_argument('--preview',action='store_true',help='Keep the second owned app open until its stop flag is created')
    parser.add_argument('--journey',action='store_true',help='Also verify shared paper/material/course records; no model call')
    args=parser.parse_args();out=args.output.resolve()
    if not out.is_relative_to((ROOT/'clawos/output').resolve()) or out.exists():parser.error('Output must be a new directory below clawos/output')
    if not 1024<=args.port<=65535:parser.error('Use an unprivileged local port')
    with socket.socket() as s:s.bind(('127.0.0.1',args.port))
    out.mkdir(parents=True);receipt=seed_captures(args.pdf_captures.resolve(),args.metadata_captures.resolve(),out/'research-learning/sources')
    save(out/'capture-receipt.json',receipt)
    config=out/'config.json'
    disabled=dict(provider='qwen',base_url='http://127.0.0.1:18999/v1',model='disabled-acceptance',api_key='',requires_api_key=False)
    save(config,dict(routing=disabled,upstream=disabled,mtclaw=dict(enabled=False),vector_store=dict(provider='sqlite',embedding_provider='hash',embedding_dim=256)))
    env=clean_environment();env.update(CLAWOS_CONFIG_PATH=str(config),CLAWOS_DATA_DIR=str(out),CLAWOS_MEMORY_DB=str(out/'memory.sqlite'),
        CLAWOS_OUTPUT_DIR=str(out/'artifacts'),FEISHU_LIVE='false')
    code='''import uvicorn,clawos_server,sys,threading,time
from pathlib import Path
server=uvicorn.Server(uvicorn.Config(clawos_server.app,host='127.0.0.1',port=int(sys.argv[2]),log_level='warning'))
def stop():
 while not Path(sys.argv[1]).is_file():time.sleep(.1)
 server.should_exit=True
threading.Thread(target=stop,daemon=True).start();server.run()
'''
    import httpx
    started=time.monotonic();checks={};ids={};preview_seconds=0.;failure=None;run=None;case=None
    def check(name,value):
        checks[name]=bool(value);save(out/'progress.json',dict(checks=checks))
        if not value:raise AssertionError(name)
    def response(c,method,path,body=None,status=200):
        r=c.request(method,path,json=body) if body is not None else c.request(method,path)
        if r.status_code!=status:raise AssertionError(path+' status '+str(r.status_code))
        return r.json()
    try:
        for phase in range(2):
            stop=out/f'stop-{phase}.flag';log=(out/f'app-{phase}.log').open('wb')
            p=subprocess.Popen([sys.executable,'-u','-c',code,str(stop),str(args.port)],cwd=ROOT/'clawos',env=env,stdout=log,stderr=log,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            save(out/f'owned-{phase}.json',dict(launcher_pid=p.pid,port=args.port,stop=str(stop),started=datetime.now(timezone.utc).isoformat()))
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{args.port}',trust_env=False,timeout=90) as c:
                    deadline=time.monotonic()+120
                    while True:
                        if p.poll() is not None:raise RuntimeError('Owned application exited during readiness')
                        try:
                            health=c.get('/health').json()
                            save(out/f'readiness-{phase}.json',{key:health.get(key) for key in ('core_ready','release','database','vector')})
                            if health.get('core_ready'):break
                        except (httpx.HTTPError,ValueError):pass
                        if time.monotonic()>deadline:raise TimeoutError('Owned application readiness')
                        time.sleep(.3)
                    check('actual_application_'+str(phase),True)
                    b='/api/vision/research'
                    check('research_worker_'+str(phase),response(c,'GET','/api/research/watch')['worker']['running'])
                    check('vision_not_started_'+str(phase),response(c,'GET','/api/vision/runtime')['running'] is False)
                    check('workspace_page_'+str(phase),c.get('/academy/vision/').status_code==200)
                    if args.journey:
                        check('grounded_worker_'+str(phase),response(c,'GET','/api/vision/research/answer-status')['worker_running'])
                        bank=response(c,'GET','/api/vision/research/answer-bank')
                        check('thirty_unreviewed_questions_'+str(phase),len(bank['questions'])==30 and not bank['independent_gold'])
                    if phase==0:
                        case=response(c,'POST',b+'/prepare',dict(request_id='real-literature-acceptance-001'))
                        cid=case['case']['id'];ids.update(case=cid,overview=case['case']['overview_id'],subscription=case['case']['subscription_id'])
                        save(out/'case.json',case)
                        check('ten_real_full_text_sources',len(case['case']['papers'])==10 and case['overview_preview']['coverage']['full_text_bound']==10)
                        check('real_169_pages',sum(p['page_count'] for p in case['case']['papers'])==169)
                        repeated=response(c,'POST',b+'/prepare',dict(request_id='real-literature-acceptance-001'))
                        check('prepare_idempotent',case['hash']==repeated['hash'])
                        watch=response(c,'GET','/api/research/watch');sub=next(x for x in watch['subscriptions'] if x['id']==ids['subscription'])
                        check('subscription_explicitly_paused',not sub['enabled'])
                        feed=response(c,'GET','/api/research/watch/feed')
                        check('ten_discoveries',len(feed['items'])==10)
                        check('english_classification_candidates',all(p['classification'][0]['name']!='待归类' for p in feed['items']))
                        check('teacher_not_faked',case['case']['teaching_graph']['teacher_verified'] is False)
                        run=response(c,'POST',b+'/cases/'+cid+'/runs',dict(request_id='real-literature-experiment-001',case_hash=case['hash'],
                            hypothesis='I expect full text to reveal method details missing from abstracts, while increasing candidate text and retrieval noise.',top_k=3))
                        ids['run']=run['run']['id'];save(out/'run.json',run)
                        check('same_queries_two_scopes',[a['scope'] for a in run['run']['result']['arms']]==['abstract','full_text'])
                        check('no_model_or_learning_claim',run['run']['model_calls']==0 and not run['run']['learning_effect_verified'])
                        hit=run['run']['result']['arms'][1]['rows'][1]['hits'][0]
                        page=response(c,'GET',b+'/cases/'+cid+'/papers/'+hit['paper_id']+'/pages/'+str(hit['page']))
                        check('actual_page_source',page['text'] and page['case_hash']==case['hash'])
                        view=response(c,'POST',b+'/runs/'+ids['run']+'/views',dict(request_id='real-literature-observation-001',run_hash=run['hash'],state=dict(arm=1,question_id='dpr')))
                        ids['view']=view['id'];check('saved_observation',view['visibility']=='owner_only')
                        # This tests append/reload only. It is explicitly not a learner response or teacher review.
                        transfer=dict(version=0,run_hash=run['hash'],answers={q['id']:'AUTOMATED PERSISTENCE FIXTURE, NOT A LEARNER ANSWER: verify sources, controlled conditions, limits and uncertainty.' for q in run['transfer_questions']},
                                      reflection='AUTOMATED PERSISTENCE FIXTURE: phrase coverage does not establish answer correctness or learning benefit.')
                        run=response(c,'POST',b+'/runs/'+ids['run']+'/attempts',transfer)
                        check('transfer_waits_teacher',run['version']==1 and run['attempts'][0]['review_status']=='pending_teacher_review' and not run['attempts'][0]['mastery_updated'])
                        check('transfer_retry',response(c,'POST',b+'/runs/'+ids['run']+'/attempts',transfer)['version']==1)
                        conflict=c.post(b+'/runs/'+ids['run']+'/attempts',json={**transfer,'reflection':'Different stale automated fixture cannot overwrite saved answers.'})
                        check('transfer_conflict',conflict.status_code==409)
                        check('foreign_origin_denied',c.post(b+'/prepare',json={'request_id':'foreign-origin-fixture'},headers={'Origin':'https://foreign.invalid'}).status_code==403)
                        exported=response(c,'GET',b+'/runs/'+ids['run']+'/export');save(out/'export.json',exported)
                        check('same_process_replay',experiment(exported['case']['papers'],3)==exported['run']['result'])
                        replay_code="import json,sys;from services.research_learning_engine import experiment;p=json.load(open(sys.argv[1],encoding='utf-8'));assert experiment(p['case']['papers'],3)==p['run']['result']"
                        replay_env=clean_environment();replay_env.update(PYTHONPATH=str(ROOT/'clawos'),PYTHONHASHSEED='71')
                        completed=subprocess.run([sys.executable,'-c',replay_code,str(out/'export.json')],env=replay_env,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40)
                        (out/'replay.log').write_bytes(completed.stdout+completed.stderr);check('independent_process_exact_replay',completed.returncode==0)
                        if args.journey:
                            journey=response(c,'GET',b+'/cases/'+cid+'/journey');save(out/'journey.json',journey)
                            check('shared_plan_links',journey['overview_id']==ids['overview'] and all(cid in journey['links'][key] for key in ('course','practice','mechanism')))
                            check('six_pending_teacher_units',len(journey['units'])==6 and all(not u['teacher_verified'] for u in journey['units']))
                            paper=next(p for p in journey['papers'] if p['id']=='dpr');pdf=c.get(paper['pdf_url']+'?download=true')
                            check('exact_captured_pdf_download',pdf.status_code==200 and sha(pdf.content)==paper['raw_sha256'] and 'attachment' in pdf.headers['content-disposition'])
                            rendered=response(c,'GET',b+'/cases/'+cid+'/papers/dpr/pdf-page/1')
                            check('shared_renderer_actual_pdf_page',rendered['image'].startswith('data:image/png;base64,') and rendered['pages']==paper['page_count'] and rendered['raw_sha256']==paper['raw_sha256'] and len(rendered['text'])>0)
                            note=dict(case_hash=case['hash'],version=0,status='reading',folder='AUTOMATED ACCEPTANCE',tags=['fixture'],note='AUTOMATED PERSISTENCE FIXTURE, NOT A LEARNER READING NOTE.')
                            ids['note']=response(c,'POST',b+'/cases/'+cid+'/papers/dpr/note',note)
                            check('reading_note_cas',c.post(b+'/cases/'+cid+'/papers/dpr/note',json={**note,'note':'A stale conflicting automated fixture.'}).status_code==409)
                            checkpoint=dict(case_hash=case['hash'],version=0,explanation='AUTOMATED PERSISTENCE FIXTURE: locating a quote does not establish semantic support or learner mastery.')
                            ids['checkpoint']=response(c,'POST',b+'/cases/'+cid+'/units/evidence/checkpoint',checkpoint)
                            check('explanation_no_reward',not ids['checkpoint']['mastery_updated'] and not ids['checkpoint']['teacher_verified'])
                            imported=response(c,'POST',b+'/cases/'+cid+'/papers/dpr/import',dict(case_hash=case['hash'],confirmed=True));ids['imported']=imported
                            repeated=response(c,'POST',b+'/cases/'+cid+'/papers/dpr/import',dict(case_hash=case['hash'],confirmed=True))
                            check('same_pdf_shared_import_idempotent',imported==repeated and imported['knowledge_chunks']>0)
                            material=response(c,'GET','/api/academy/learning/materials/'+imported['material_id'])
                            check('material_source_and_teacher_boundary',material['document']['digest']==paper['raw_sha256'] and material['document']['status']=='ready' and material['calibration']['status']=='unlabelled')
                            check('original_reader_and_teacher_pages',all(c.get(imported[key]).status_code==200 for key in ('reader_url','material_url','teacher_url')))
                            check('no_model_job_implicitly_queued',response(c,'GET',b+'/cases/'+cid+'/answers')['items']==[])
                            check('foreign_origin_journey_denied',c.get(b+'/cases/'+cid+'/journey',headers={'Origin':'https://foreign.invalid'}).status_code==403)
                    else:
                        restored=response(c,'GET',b+'/cases/'+ids['case']);check('case_after_restart',restored['hash']==case['hash'])
                        restored_run=response(c,'GET',b+'/runs/'+ids['run']);check('answers_after_restart',restored_run==run)
                        restored_view=response(c,'GET',b+'/views/'+ids['view']);check('view_after_restart',restored_view['state']==dict(arm=1,question_id='dpr'))
                        check('course_history',response(c,'GET',b+'/history')['items'][0]['reflections']==1)
                        check('notification_restored',any(n['subscription_id']==ids['subscription'] for n in response(c,'GET','/api/research/watch')['notifications']))
                        if args.journey:
                            journey=response(c,'GET',b+'/cases/'+ids['case']+'/journey');dpr=next(p for p in journey['papers'] if p['id']=='dpr')
                            check('reading_note_restart',dpr['note']==ids['note'])
                            check('shared_import_restart',dpr['import_record']['material_id']==ids['imported']['material_id'])
                            unit=next(u for u in journey['units'] if u['id']=='evidence')
                            check('lesson_explanation_restart',unit['checkpoint']==ids['checkpoint'])
                            check('evolution_boundary_restart',not journey['relationship']['learner_reflection_is_agent_reward'] and not journey['relationship']['runtime_promotion_evidence'])
                            check('model_history_still_empty',response(c,'GET',b+'/cases/'+ids['case']+'/answers')['items']==[])
                        if args.preview:
                            save(out/'before-preview.json',dict(passed=True,checks=checks,ids=ids,active_seconds=time.monotonic()-started,model_calls=0))
                            print(json.dumps(dict(preview_port=args.port,ids=ids,checks=len(checks))),flush=True)
                            wait_started=time.monotonic()
                            while p.poll() is None:time.sleep(.5)
                            preview_seconds+=time.monotonic()-wait_started
            finally:
                stop.touch()
                try:p.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    # Only our explicitly-created child is terminated, never another preview.
                    p.terminate();p.wait(timeout=10)
                log.close();check('graceful_application_exit_'+str(phase),p.returncode==0)
    except Exception as exc:failure=type(exc).__name__;save(out/'failure.json',dict(type=failure,checks=checks))
    result=dict(passed=failure is None,checks=checks,ids=ids,error_type=failure,active_seconds=time.monotonic()-started-preview_seconds,preview_seconds=preview_seconds,
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),model_calls=0,
        source_files={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [*sorted((ROOT/'clawos/services').glob('research_learning*.py')),Path(__file__)]},
        actual_application=True,capture_mode='verified_capture_replay',boundary='Single-host short real-app acceptance; automated answer fixtures are not learner/teacher/model or sustained-load evidence.')
    save(out/'result.json',result);print(json.dumps(result),flush=True)
    return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
