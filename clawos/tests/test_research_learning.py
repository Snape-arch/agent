"""Frozen real-paper lesson mechanics. Fixtures here are explicitly synthetic."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch,fingerprint
from services.research_learning import ResearchLearning,Conflict
from services.research_learning_engine import QUESTIONS,TRANSFER,experiment,chunks,normalized_pages,abstract_span
from services.research_learning_sources import check_url,paper_source
from services.research_updates import ResearchUpdates
from services.vision_api import vision_router

def fake_source(spec,_root):
    needle=next(q[3] for q in QUESTIONS if q[0]==spec['id'])
    abstract='We propose a synthetic retrieval fixture for protocol tests. These statements are not captured scholarly evidence.'
    text=abstract+' '+('Synthetic background context. '*40)+needle+' '+(' experiment evaluates fixture limitations. '*20)
    return dict(id=spec['id'],name='Synthetic '+spec['name'],title=spec['title'],version=spec['version'],url='https://arxiv.org/pdf/'+spec['version'],metadata_url=spec['url'],
        authors=['Synthetic fixture'],date=spec['date'],category=spec['category'],abstract=abstract,text=text,page_spans=[[0,len(text)]],page_count=1,
        raw_sha256='synthetic-pdf-fingerprint',metadata_sha256='synthetic-metadata-fingerprint',text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source_text_fingerprint=fingerprint(text),captured='2026-11-04T00:00:00+00:00',cache_used=False,capture_mode='synthetic_test_fixture')

class CourseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.clock=[1793764800.0];self.watch=ResearchWatch(MemoryStore(str(self.root/'memory.sqlite')),clock=lambda:self.clock[0])
        self.service=ResearchLearning(self.watch,self.root/'course',fake_source)
    def prepare(self,key='synthetic-course-001'):return self.service.prepare('local-user',dict(request_id=key))
    def run_experiment(self,course,key='synthetic-run-001'):
        return self.service.run('local-user',course['case']['id'],dict(request_id=key,case_hash=course['hash'],hypothesis='Synthetic prediction: method details may be absent from short abstracts.',top_k=3))
    def test_atomic_research_overview_case_and_idempotent_retry(self):
        course=self.prepare();again=self.prepare();self.assertEqual(course,again)
        self.assertEqual(len(course['case']['papers']),10);self.assertEqual(course['overview_preview']['coverage']['full_text_bound'],10)
        state=self.watch.state('local-user');self.assertEqual(len(state['subscriptions']),1)
        self.assertEqual(state['subscriptions'][0]['enabled'],False)
        self.assertEqual(len(self.watch.feed('local-user')['items']),10)
        self.assertTrue(all(p['classification'][0]['name']!='待归类' for p in self.watch.feed('local-user')['items']))
        self.assertTrue(all(len(term)<=80 for d in state['subscriptions'][0]['directions'] for term in d['terms']))
        self.assertFalse(course['case']['teaching_graph']['teacher_verified'])
        with self.assertRaises(LookupError):self.service.get_case('guest',course['case']['id'])
        with self.assertRaises(PermissionError):self.service.prepare('guest',dict(request_id='guest-forbidden'))
    def test_source_failure_never_publishes_partial_watch_or_overview(self):
        calls=[]
        def failing(spec,root):
            calls.append(spec['id'])
            if len(calls)==3:raise OSError('Synthetic source unavailable')
            return fake_source(spec,root)
        self.service.fetch=failing
        with self.assertRaises(OSError):self.prepare()
        self.assertEqual(self.service.catalog('local-user')['cases'],[]);self.assertEqual(self.watch.state('local-user')['subscriptions'],[])
        self.assertEqual(self.service.catalog('local-user')['preparation']['status'],'failed')
    def test_publish_failure_rolls_back_memberships_report_and_notification(self):
        with patch.object(self.service.synthesis,'compose',side_effect=ValueError('Synthetic publish failure')):
            with self.assertRaises(ValueError):self.prepare()
        self.assertEqual(self.watch.feed('local-user')['items'],[]);self.assertEqual(self.watch.state('local-user')['subscriptions'],[])
    def test_page_bounds_and_frozen_source_integrity(self):
        course=self.prepare();cid=course['case']['id'];p=self.service.page('local-user',cid,'dpr',1)
        self.assertTrue(p['text']);self.assertEqual(p['start'],0)
        with self.assertRaises(ValueError):self.service.page('local-user',cid,'dpr',2)
        with self.assertRaises(LookupError):self.service.page('guest',cid,'dpr',1)
        with self.watch.store._conn() as c:c.execute("UPDATE rag_learning_cases SET hash='damaged' WHERE id=?",(cid,))
        with self.assertRaises(ValueError):self.service.get_case('local-user',cid)
    def test_actual_pair_and_concurrent_idempotent_runs_are_immutable(self):
        course=self.prepare()
        with ThreadPoolExecutor(2) as pool:rows=list(pool.map(lambda _:self.run_experiment(course),range(2)))
        self.assertEqual(rows[0]['run']['id'],rows[1]['run']['id']);run=rows[0]
        self.assertEqual(run['run']['model_calls'],0);self.assertFalse(run['run']['learning_effect_verified'])
        self.assertEqual([a['scope'] for a in run['run']['result']['arms']],['abstract','full_text'])
        exported=self.service.export('local-user',run['run']['id']);self.assertEqual(exported['case_hash'],course['hash'])
        self.assertEqual(experiment(exported['case']['papers'],3),run['run']['result'])
    def test_run_contract_source_drift_and_owner_rejection(self):
        course=self.prepare();run=self.run_experiment(course);cid=course['case']['id']
        data=dict(request_id='synthetic-run-001',case_hash=course['hash'],hypothesis='Changed configuration is not the original experiment.',top_k=1)
        with self.assertRaises(Conflict):self.service.run('local-user',cid,data)
        with self.assertRaises(LookupError):self.service.get_run('guest',run['run']['id'])
        for k in (True,0,2,100,float('nan')):
            with self.assertRaises(ValueError):self.service.run('local-user',cid,{**data,'request_id':'invalid-topk-key','top_k':k})
        with patch('services.research_learning.implementation_hashes',return_value={'synthetic':'drift'}):
            with self.assertRaises(Conflict):self.service.run('local-user',cid,{**data,'request_id':'source-drift-key'})
    def test_transfer_append_retry_conflict_and_no_fake_grades(self):
        course=self.prepare();run=self.run_experiment(course);rid=run['run']['id']
        body=dict(version=0,run_hash=run['hash'],answers={q['id']:'Synthetic independent-scenario response for persistence testing.' for q in TRANSFER},reflection='Synthetic reflection: evidence coverage is not answer correctness.')
        first=self.service.submit('local-user',rid,body);self.assertEqual(first,self.service.submit('local-user',rid,body));self.assertEqual(first['version'],1)
        self.assertFalse(first['attempts'][0]['mastery_updated']);self.assertFalse(first['attempts'][0]['teacher_verified'])
        with self.assertRaises(Conflict):self.service.submit('local-user',rid,{**body,'reflection':'A different stale answer cannot overwrite the previous response.'})
        second=self.service.submit('local-user',rid,{**body,'version':1});self.assertEqual(second['version'],2)
        self.assertEqual(self.service.course_history('local-user')['items'][0]['reflections'],2)
    def test_observation_restore_validation_and_owner_isolation(self):
        run=self.run_experiment(self.prepare());rid=run['run']['id'];data=dict(request_id='synthetic-view-001',run_hash=run['hash'],state=dict(arm=1,question_id='dpr'))
        v=self.service.save_view('local-user',rid,data);self.assertEqual(v,self.service.save_view('local-user',rid,data))
        self.assertEqual(self.service.view('local-user',v['id'])['state'],data['state'])
        for state in [dict(arm=True,question_id='dpr'),dict(arm=1,question_id='invented'),dict(arm=1,question_id='dpr',script='not allowed')]:
            with self.assertRaises(ValueError):self.service.save_view('local-user',rid,{**data,'state':state})
        with self.assertRaises(LookupError):self.service.view('guest',v['id'])
    def test_restart_restores_records_and_expired_preparation_is_not_success(self):
        course=self.prepare();run=self.run_experiment(course);other=ResearchLearning(self.watch,self.root/'course',fake_source)
        self.assertEqual(other.get_case('local-user',course['case']['id']),self.service.get_case('local-user',course['case']['id']))
        self.assertEqual(other.get_run('local-user',run['run']['id']),run)
        with self.watch.store._conn() as c:c.execute("INSERT INTO rag_learning_jobs VALUES('stale','local-user','stale-request','preparing','old-token',?,0,'',NULL)",(self.clock[0]-1,))
        self.assertEqual(other.catalog('local-user')['preparation']['status'],'failed')
    def test_full_text_overview_cannot_be_silently_replaced_by_abstracts(self):
        course=self.prepare();updates=ResearchUpdates(self.watch);rid=course['case']['overview_id']
        with self.assertRaises(ValueError):updates.configure('local-user',rid,dict(enabled=True,interval_hours=6,version=0))
        with self.assertRaises(ValueError):updates.check('local-user',rid,dict(version=0))
        self.assertEqual(self.service.synthesis.get('local-user',rid)['hash'],course['case']['overview_hash'])

class SourceAndEngineTests(unittest.TestCase):
    def test_corrupted_or_missing_cached_originals_never_fall_back_to_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cache=root/'2004.04906v3';cache.mkdir()
            spec=dict(version='2004.04906v3',title='Synthetic')
            (cache/'capture.json').write_text('{}',encoding='utf-8')
            with patch('services.research_learning_sources.read_public',side_effect=AssertionError('No hidden source replacement')) as network:
                with self.assertRaises(FileNotFoundError):paper_source(spec,root)
                (cache/'paper.pdf').write_bytes(b'%PDF synthetic');(cache/'metadata.html').write_bytes(b'synthetic')
                (cache/'capture.json').write_text(json.dumps(dict(version=spec['version'],pdf_sha256='wrong',metadata_sha256='wrong')),encoding='utf-8')
                with self.assertRaises(ValueError):paper_source(spec,root)
                network.assert_not_called()
    def test_public_source_urls_are_explicit_versioned_and_credential_free(self):
        check_url('https://arxiv.org/pdf/2004.04906v3')
        for url in ['http://arxiv.org/pdf/2004.04906v3','https://arxiv.org/pdf/2004.04906','https://127.0.0.1/private','https://user:secret@arxiv.org/pdf/2004.04906v3','https://arxiv.org/pdf/2004.04906v3?token=not-real']:
            with self.assertRaises(ValueError):check_url(url)
    def test_canonical_extraction_keeps_explicit_representation_and_ranges(self):
        self.assertEqual(normalized_pages(['A ﬁle with docu-\nment.']),['A file with document.'])
        paper=dict(id='test',name='Synthetic',text='alpha '*200,abstract='alpha abstract',metadata_url='https://arxiv.org/abs/2004.04906v3',url='https://arxiv.org/pdf/2004.04906v3',page_spans=[[0,1200]],raw_sha256='synthetic',metadata_sha256='synthetic-meta')
        for scope,field in [('full_text','text'),('abstract','abstract')]:
            for p in chunks([paper],scope):self.assertEqual(p['text'],paper[field][p['start']:p['end']]);self.assertEqual(p['field'],scope)

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        watch=ResearchWatch(MemoryStore(str(root/'m.sqlite')));self.service=ResearchLearning(watch,root,fake_source)
        class Identity:
            def identity(self,request):return dict(id='local-user')
        app=FastAPI();app.include_router(vision_router(lambda:None,Identity,root,research=lambda:self.service))
        self.client=TestClient(app,client=('127.0.0.1',40000));self.addCleanup(self.client.close)

    def test_maximum_unicode_transfer_answers_fit_bounded_json_body(self):
        b='/api/vision/research';c=self.client
        course=c.post(b+'/prepare',json=dict(request_id='unicode-api-course')).json();cid=course['case']['id']
        run=c.post(b+'/cases/'+cid+'/runs',json=dict(request_id='unicode-api-run',case_hash=course['hash'],hypothesis='Synthetic Unicode transfer transport validation.',top_k=3)).json()
        data=dict(version=0,run_hash=run['hash'],answers={q['id']:'🌱'*3000 for q in TRANSFER},reflection='🌱'*3000)
        raw=json.dumps(data,ensure_ascii=True).encode('utf-8');self.assertGreater(len(raw),140000)
        response=c.post(b+'/runs/'+run['run']['id']+'/attempts',content=raw,headers={'Content-Type':'application/json'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['version'],1)
        self.assertEqual(response.json()['attempts'][0]['reflection'],data['reflection'])
        self.assertEqual(c.post(b+'/prepare',content=b' '*160001,headers={'Content-Type':'application/json'}).status_code,413)

    def test_real_router_prepare_run_source_view_and_foreign_origin_rejection(self):
        b='/api/vision/research';c=self.client
        self.assertEqual(c.post(b+'/prepare',json=dict(request_id='foreign-preparation'),headers={'Origin':'https://foreign.invalid'}).status_code,403)
        course=c.post(b+'/prepare',json=dict(request_id='synthetic-api-case')).json();cid=course['case']['id']
        response=c.post(b+'/cases/'+cid+'/runs',json=dict(request_id='synthetic-api-run',case_hash=course['hash'],hypothesis='Synthetic prediction for route-level protocol testing.',top_k=3))
        self.assertEqual(response.status_code,200);run=response.json();rid=run['run']['id']
        self.assertEqual(c.get(b+'/cases/'+cid+'/papers/dpr/pages/1').status_code,200)
        self.assertEqual(c.get(b+'/runs/'+rid+'/export').status_code,200)
        self.assertEqual(c.get(b+'/history').json()['items'][0]['id'],rid)
        self.assertEqual(c.get(b+'/catalog',headers={'Authorization':'Bearer synthetic-guest'}).status_code,403)

if __name__=='__main__':unittest.main()
