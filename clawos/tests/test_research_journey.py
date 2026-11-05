"""Shared workflow tests; all paper text/model replies below are synthetic fixtures."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch,fingerprint
from services.research_learning import ResearchLearning,Conflict
from services.research_journey import ResearchJourney
from services.research_grounded import ResearchGrounded,bank,validate_answer
from services.research_ai import ResearchAI,ResearchAIWorker
from services.vision_api import vision_router
from test_research_learning import fake_source

RAW=b'%PDF-synthetic-protocol-fixture-not-a-scholarly-capture'
def source(spec,root):
    value=fake_source(spec,root);value['raw_sha256']=hashlib.sha256(RAW).hexdigest();value['abstract']+=' Synthetic question passage vectors similarity dot product retrieval.'
    folder=root/spec['version'];folder.mkdir(parents=True,exist_ok=True);(folder/'paper.pdf').write_bytes(RAW)
    return value

class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.clock=[1793860000.0]
        self.store=MemoryStore(str(self.root/'m.sqlite'));self.watch=ResearchWatch(self.store,clock=lambda:self.clock[0])
        self.learning=ResearchLearning(self.watch,self.root/'learning',source);self.course=self.learning.prepare('local-user',{'request_id':'synthetic-unified-01'})
        self.cid=self.course['case']['id'];self.h=self.course['hash'];self.journey=ResearchJourney(self.learning);self.qa=ResearchGrounded(self.learning)
    def payload(self,key='synthetic-model-01'):
        return dict(case_hash=self.h,request_id=key,question_id='fact-dpr',top_k=3,confirmed=True)
    def model_job(self,key='synthetic-model-01'):
        self.qa.enqueue('local-user',self.cid,self.payload(key));return self.qa.claim()
    async def model(self,messages,tools,**opts):
        self.assertEqual(tools,[]);self.assertEqual(opts['max_tokens'],1500);self.assertEqual(opts['temperature'],0)
        context=json.loads(messages[1]['content']);e=context['evidence'][0]
        value=dict(status='answered',reason='Synthetic protocol fixture with a bounded citation.',claims=[dict(text='合成协议夹具用于检查引用结构。',citations=[dict(id=e['id'],quote=e['quote'][:80])])])
        return dict(choices=[dict(finish_reason='stop',message=dict(content=json.dumps(value,ensure_ascii=False)))],clawos_model=dict(provider='synthetic-fixture',model='fixture-only',usage={'total_tokens':42},duration_ms=1))
    def completed(self,model=None,key='synthetic-model-01'):
        job=self.model_job(key);asyncio.run(self.qa.execute(job,model or self.model));return self.qa.get('local-user',job['id'])
    def test_one_case_shared_across_curriculum_overview_visuals_and_library(self):
        d=self.journey.dashboard('local-user',self.cid)
        self.assertEqual(len(d['papers']),10);self.assertEqual(len(d['units']),6);self.assertEqual(d['overview_id'],self.course['case']['overview_id'])
        for k in ('course','practice','mechanism'):self.assertIn(self.cid,d['links'][k])
        self.assertFalse(d['relationship']['learner_reflection_is_agent_reward']);self.assertFalse(d['relationship']['runtime_promotion_evidence'])
        self.assertNotIn('text',d['papers'][0]);self.assertNotIn('page_spans',d['papers'][0])
        with self.assertRaises(PermissionError):self.journey.dashboard('guest',self.cid)
    def test_notes_cas_retry_tags_owner_and_restart(self):
        data=dict(case_hash=self.h,version=0,status='reading',folder='检索学习',tags=[' RAG ','RAG'],note='Synthetic personal reading note.')
        value=self.journey.save_note('local-user',self.cid,'dpr',data);self.assertEqual(value['tags'],['RAG'])
        self.assertEqual(value,self.journey.save_note('local-user',self.cid,'dpr',data))
        with self.assertRaises(Conflict):self.journey.save_note('local-user',self.cid,'dpr',{**data,'note':'A competing stale draft.'})
        restored=ResearchJourney(ResearchLearning(ResearchWatch(MemoryStore(str(self.root/'m.sqlite'))),self.root/'learning')).dashboard('local-user',self.cid)
        self.assertEqual(next(p for p in restored['papers'] if p['id']=='dpr')['note'],value)
        for field,bad in [('version',True),('tags',['x']*9),('folder','x'*81),('status','mastered')]:
            with self.assertRaises(ValueError):self.journey.save_note('local-user',self.cid,'dpr',{**data,field:bad})
    def test_checkpoint_never_grades_or_changes_agent_state(self):
        data=dict(case_hash=self.h,version=0,explanation='这是本人对引用定位与语义支持不同的解释。')
        result=self.journey.checkpoint('local-user',self.cid,'evidence',data);self.assertFalse(result['mastery_updated']);self.assertFalse(result['teacher_verified'])
        self.assertEqual(result,self.journey.checkpoint('local-user',self.cid,'evidence',data))
        with self.assertRaises(Conflict):self.journey.checkpoint('local-user',self.cid,'evidence',{**data,'explanation':'另一份过期的个人解释，应该先核对。'})
        with self.store._conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM reflection_cards').fetchone()[0],0)
    def test_cached_pdf_exact_sha_missing_and_path_rejection(self):
        name,raw=self.journey.pdf('local-user',self.cid,'dpr');self.assertEqual(raw,RAW);self.assertEqual(name,'2004.04906v3.pdf')
        (self.learning.root/'sources'/'2004.04906v3'/'paper.pdf').write_bytes(RAW+b'changed')
        with self.assertRaises(ValueError):self.journey.pdf('local-user',self.cid,'dpr')
        with self.assertRaises(LookupError):self.journey.pdf('local-user',self.cid,'../dpr')
        (self.learning.root/'sources'/'2004.04906v3'/'paper.pdf').unlink()
        with self.assertRaises(LookupError):self.journey.pdf('local-user',self.cid,'dpr')
    def test_shared_import_confirmation_dedup_lease_and_partial_failure(self):
        calls=[]
        def importer(p,raw):calls.append(p['id']);return dict(document_id=8,material_id='material-fixture')
        self.journey.importer=importer;data=dict(case_hash=self.h,confirmed=True)
        with self.assertRaises(ValueError):self.journey.import_paper('local-user',self.cid,'dpr',{**data,'confirmed':False})
        a=self.journey.import_paper('local-user',self.cid,'dpr',data);b=self.journey.import_paper('local-user',self.cid,'realm',data)
        self.assertEqual(a,b);self.assertEqual(calls,['dpr']) # Same synthetic raw bytes dedup across plans/papers.
        with self.store._conn() as c:c.execute("UPDATE research_journey_imports SET status='importing',lease=?",(self.clock[0]+20,))
        with self.assertRaises(Conflict):self.journey.import_paper('local-user',self.cid,'dpr',data)
        self.clock[0]+=21
        def broken(p,raw):raise OSError('synthetic private failure message')
        self.journey.importer=broken
        with self.assertRaises(OSError):self.journey.import_paper('local-user',self.cid,'dpr',data)
        record=self.journey.dashboard('local-user',self.cid)['papers'][0]['import_record'];self.assertEqual(record['error_type'],'OSError');self.assertNotIn('message',record)
    def test_real_pdf_parser_connects_shared_knowledge_and_teaching_materials(self):
        import fitz
        from services.academy_materials import AcademyMaterials
        from services.research_journey_import import import_capture
        document=fitz.open();page=document.new_page();page.insert_text((40,60),'Synthetic paper fixture: retrieval evidence and source verification. '*3);raw=document.tobytes();document.close()
        paper=dict(self.course['case']['papers'][0],raw_sha256=hashlib.sha256(raw).hexdigest());materials=AcademyMaterials(self.store,self.root/'materials');calls=[]
        opts=dict(store=self.store,upload_dir=self.root/'uploads',materials=materials,staging=self.root/'stage',refresh=lambda:calls.append(True))
        a=import_capture(paper,raw,**opts);b=import_capture(paper,raw,**opts)
        self.assertEqual(a['document_id'],b['document_id']);self.assertEqual(a['material_id'],b['material_id']);self.assertGreater(a['knowledge_chunks'],0)
        self.assertEqual(materials.document(a['material_id'])['digest'],paper['raw_sha256']);self.assertFalse(a['teacher_verified']);self.assertEqual(list((self.root/'stage').iterdir()),[])
        self.assertEqual(len(list((self.root/'uploads').glob('*.pdf'))),1)
        from services.pdf_page_renderer import PdfPageRenderer
        renderer=PdfPageRenderer();rendered=renderer.render_bytes(raw,1)
        self.assertEqual(rendered,renderer.render_bytes(raw,1));self.assertEqual(rendered['pages'],1);self.assertTrue(rendered['image'].startswith('data:image/png;base64,'))
        self.assertTrue(any('Synthetic' in t['text'] for t in rendered['text']))
        with self.assertRaises(ValueError):renderer.render_bytes(raw,2)
        with self.assertRaises(ValueError):renderer.render_bytes(raw,True)
    def test_question_bank_is_three_balanced_unreviewed_sets(self):
        rows=bank();self.assertEqual(len(rows['questions']),30);self.assertFalse(rows['independent_gold']);self.assertFalse(rows['human_labels_verified'])
        for kind in ('fact','comparison','insufficiency'):self.assertEqual(sum(q['kind']==kind for q in rows['questions']),10)
    def test_enqueue_idempotence_budget_owner_topk_and_source(self):
        data=self.payload();a=self.qa.enqueue('local-user',self.cid,data);self.assertEqual(a,self.qa.enqueue('local-user',self.cid,data));self.assertEqual(a,self.qa.retry('local-user',self.cid,data))
        with self.assertRaises(Conflict):self.qa.retry('local-user',self.cid,{**data,'top_k':5})
        with self.assertRaises(PermissionError):self.qa.enqueue('guest',self.cid,data)
        with self.assertRaises(LookupError):self.qa.get('guest',a['id'])
        for k in (True,0,2):
            with self.assertRaises(ValueError):self.qa.enqueue('local-user',self.cid,{**data,'top_k':k,'request_id':'invalid-topk-01'})
        with patch('services.research_grounded.implementation',return_value={}):
            with self.assertRaises(Conflict):self.qa.enqueue('local-user',self.cid,self.payload('code-drift-01'))
    def test_model_pair_receipts_same_model_and_original_review_idempotence(self):
        value=self.completed();self.assertEqual(value['status'],'completed',value['result']);result=value['result']
        self.assertEqual([a['scope'] for a in result['arms']],['abstract','full_text']);self.assertEqual(result['model_calls'],2)
        legacy=ResearchAI(self.watch).get('local-user',result['review_job_id'])['result']
        self.assertIn('excluded',legacy);self.assertEqual(legacy['coverage']['corpus_papers'],10);self.assertGreaterEqual(legacy['coverage']['available_excerpts'],legacy['coverage']['selected_excerpts'])
        self.assertFalse(result['runtime_promotion_evidence']);self.assertFalse(result['learning_effect_verified'])
        review=self.qa.create_review('local-user',value['id']);again=self.qa.create_review('local-user',value['id']);self.assertEqual(review['id'],again['id']);self.assertEqual(review['kind'],'ai')
        self.assertEqual(review['summary']['double_reviewed'],0)
        exported=self.qa.export('local-user',value['id']);self.assertEqual(exported['case_hash'],self.h)
        with self.assertRaises(ValueError):self.qa.reflect('local-user',value['id'])
    def test_exact_contract_fault_enters_existing_reflection_without_improvement(self):
        async def broken(*args,**kwargs):
            value=await self.model(*args,**kwargs);content=json.loads(value['choices'][0]['message']['content']);content['claims'][0]['citations'][0]['id']='unknown-E99';value['choices'][0]['message']['content']=json.dumps(content);return value
        job=self.completed(broken);self.assertEqual(job['status'],'completed',job)
        a=self.qa.reflect('local-user',job['id']);b=self.qa.reflect('local-user',job['id']);self.assertTrue(a['created']);self.assertFalse(b['created'])
        card=self.store.get_reflection_card(a['card_id']);self.assertEqual(card['failure_category'],'citation_contract');self.assertFalse(card['outcome_detail']['runtime_promotion_evidence'])
        with self.store._conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM reflection_improvements').fetchone()[0],0)
        self.assertNotIn('Synthetic background',json.dumps(card));self.assertFalse(a['runtime_promotion_evidence'])
    def test_unreviewed_numeric_or_semantic_claim_is_not_agent_reward(self):
        async def invented(*a,**k):
            r=await self.model(*a,**k);value=json.loads(r['choices'][0]['message']['content']);value['claims'][0]['text']='The model achieves 99 percent accuracy on every future task.';r['choices'][0]['message']['content']=json.dumps(value);return r
        job=self.completed(invented);self.assertEqual(job['status'],'completed')
        self.assertTrue(all(a['answer']['withheld'][0]['reason']=='quantity_requires_review' for a in job['result']['arms']))
        with self.assertRaises(ValueError):self.qa.reflect('local-user',job['id'])
        with self.store._conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reflection_cards').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reflection_improvements').fetchone()[0],0)
    def test_export_preserves_original_question_bank_across_later_bank_edits(self):
        job=self.completed()
        with patch('services.research_grounded.bank',return_value={'version':'synthetic-later-bank'}):
            exported=self.qa.export('local-user',job['id'])
        self.assertEqual(fingerprint(exported['bank']),job['result']['bank_hash'])
        self.assertEqual(len(exported['bank']['questions']),30)
    def test_strict_reply_tool_request_and_truncated_json_are_withheld(self):
        for index,change in enumerate(['tool','truncated','duplicate']):
            async def bad(*a,**k):
                r=await self.model(*a,**k)
                if change=='tool':r['choices'][0]['message']['tool_calls']=[{'function':{'name':'must_not_run'}}]
                elif change=='truncated':r['choices'][0]['finish_reason']='length'
                else:r['choices'][0]['message']['content']='{"status":"answered","status":"insufficient"}'
                return r
            job=self.completed(bad,'synthetic-reject-'+str(index));self.assertEqual(job['status'],'completed');self.assertTrue(all(a['answer']['outcome']=='withheld' for a in job['result']['arms']))
    def test_transport_failure_and_provider_change_preserve_safe_partial_receipts(self):
        async def failing(*a,**k):raise OSError('private endpoint details must not be persisted')
        value=self.completed(failing);self.assertEqual(value['status'],'failed');self.assertEqual(value['result']['error_type'],'OSError');self.assertNotIn('private endpoint',json.dumps(value))
        count=[0]
        async def changed(*a,**k):
            count[0]+=1;r=await self.model(*a,**k);r['clawos_model']['model']='fixture-'+str(count[0]);return r
        value=self.completed(changed,'identity-change-01');self.assertEqual(value['status'],'failed');self.assertEqual(len(value['result']['calls']),2)
        with self.assertRaises(ValueError):self.qa.reflect('local-user',value['id'])
    def test_cross_queue_exclusion_and_cancelled_lease(self):
        old=ResearchAI(self.watch);queued=old.enqueue('local-user',self.course['case']['overview_id']);j=old.claim();self.assertIsNotNone(j)
        self.qa.enqueue('local-user',self.cid,self.payload());self.assertIsNone(self.qa.claim());old.finish(j,error='synthetic_stop')
        new=self.qa.claim();self.assertIsNotNone(new);old.enqueue('local-user',self.course['case']['overview_id']);self.assertIsNone(old.claim())
        self.qa.cancel('local-user',new['id']);self.assertIsNone(old.claim());self.qa.finish(new,{'cancelled':True},error='cancelled');self.assertIsNotNone(old.claim())
    def test_lease_expiry_prevents_late_publish(self):
        job=self.model_job();self.clock[0]+=241;self.assertFalse(self.qa.finish(job,{},error='late'));self.qa.claim();self.assertEqual(self.qa.get('local-user',job['id'])['status'],'failed')
    def test_cancellation_awaits_model_and_never_creates_review_envelope(self):
        async def run():
            started=asyncio.Event();cancelled=asyncio.Event();job=self.model_job()
            async def slow(*a,**k):
                started.set()
                try:await asyncio.Event().wait()
                finally:cancelled.set()
            task=asyncio.create_task(self.qa.execute(job,slow));await started.wait();self.qa.cancel('local-user',job['id'])
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(cancelled.is_set());self.assertEqual(self.qa.get('local-user',job['id'])['status'],'cancelled')
            with self.store._conn() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM research_ai_jobs WHERE id LIKE 'grounded-%'").fetchone()[0],0)
        asyncio.run(run())

    def test_owner_api_no_model_start_pdf_and_offline_retry(self):
        class Collaboration:
            def identity(self,r):return {'id':'local-user' if not r.headers.get('x-guest') else 'guest'}
        app=FastAPI();app.include_router(vision_router(lambda:None,Collaboration,self.root,journey=lambda:self.journey,grounded=lambda:self.qa,model_ready=lambda:dict(ready=False,reason='synthetic offline')))
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',40000)) as client:
            path='/api/vision/research/cases/'+self.cid
            self.assertEqual(client.get(path+'/journey',headers={'Origin':'http://evil.invalid'}).status_code,403)
            self.assertEqual(client.get(path+'/journey',headers={'x-guest':'1'}).status_code,403)
            r=client.get(path+'/papers/dpr/pdf?download=true');self.assertEqual(r.content,RAW);self.assertIn('attachment',r.headers['content-disposition']);self.assertEqual(r.headers['cache-control'],'no-store')
            self.assertEqual(client.post(path+'/answers',json=self.payload()).status_code,503)
            value=self.qa.enqueue('local-user',self.cid,self.payload());r=client.post(path+'/answers',json=self.payload());self.assertEqual(r.status_code,200);self.assertEqual(r.json()['id'],value['id'])
            self.assertEqual(client.post(path+'/answers',content='x'*160001).status_code,413)
            self.assertEqual(client.post(path+'/papers/dpr/note',json=[]).status_code,400)

if __name__=='__main__':unittest.main()
