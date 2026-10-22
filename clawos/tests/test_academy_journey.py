import asyncio
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memoryos.memory_store import MemoryStore
from services.academy_materials import AcademyMaterials
from services.academy_material_api import materials_router
from services.academy_journey import utc_now
from services.maintenance_service import MaintenanceService
from services.learning_product_service import LearningProductService


class AcademyJourneyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=MemoryStore(str(self.root/'memory.db'))
        LearningProductService(self.store)
        self.s=AcademyMaterials(self.store,self.root/'materials')
        state=self.s.upload('lesson.md',b'# Evidence\nEvidence supports conclusions. Missing evidence requires refusal.\n# Practice\nCheck the source before answering.')
        self.mid=state['document']['id'];self.chapter=state['chapters'][0]
        self.questions=dict(questions=[dict(dimension=d,question='Explain why evidence supports conclusions.',
            quote='Evidence supports conclusions.',criterion='Explain the condition and its implication.') for d in ('concept','reasoning','transfer')])
        self.q=self.s.save_chapter_questions(self.mid,self.chapter['id'],'research',self.questions)
        self.answers=['Evidence must support the conclusion.']*3
        self.project=dict(question='What supports an answer?',method='Check the original source.',result='Evidence is required.',reflection='More tests are needed.',quote='Evidence supports conclusions.')
        self.response=self.s.chapter_response(self.mid,self.chapter['id'],self.answers,self.project,question_event_id=self.q['id'])
        self.judge=dict(dimensions={d:dict(score=2,reason='Explains the evidence condition.',student_quote='Evidence must support',
            source_quote='Evidence supports conclusions.',next_step='Try a case with no evidence.') for d in ('concept','reasoning','transfer')})
        self.review=self.s.save_chapter_review(self.mid,self.response['id'],[self.judge,self.judge])
        self.j=self.s.journey

    def test_planner_prioritizes_due_recall_and_respects_budget(self):
        state=self.s.state(self.mid)
        future=utc_now()+timedelta(days=2)
        plan=self.j.state(state['document'],state['chapters'],future)
        self.assertEqual(plan['tasks'][0]['kind'],'recall')
        self.assertLessEqual(plan['planned_minutes'],plan['minutes'])
        self.assertEqual(plan['due_count'],1)
        self.j.settings(self.mid,40)
        self.assertEqual(self.s.state(self.mid)['journey']['minutes'],40)
        for invalid in [True,25,'40']:
            with self.assertRaises(ValueError):self.j.settings(self.mid,invalid)

    def test_recall_requires_answers_before_rating_and_preserves_blind_response(self):
        a=self.j.start(self.mid,self.chapter['id'])
        self.assertEqual(a['id'],self.j.start(self.mid,self.chapter['id'])['id'])
        with self.assertRaises(ValueError):self.j.rate(self.mid,a['id'],'remembered')
        with self.assertRaises(ValueError):self.j.submit(self.mid,a['id'],['short']*3)
        self.j.submit(self.mid,a['id'],self.answers)
        with self.assertRaises(ValueError):self.j.submit(self.mid,a['id'],['A changed explanation of the source.']*3)
        rated=self.j.rate(self.mid,a['id'],'remembered')
        self.assertEqual(rated,self.j.rate(self.mid,a['id'],'remembered'))
        with self.assertRaises(ValueError):self.j.rate(self.mid,a['id'],'again')
        self.assertEqual(rated['stage'],1)
        self.assertEqual(self.s.state(self.mid)['journey']['due_count'],0)
        self.assertEqual(self.s.state(self.mid)['chapters'][0]['status'],'passed')
        with self.store._conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM learning_reviews').fetchone()[0],0)

    def test_intervals_progress_then_reset_and_survive_new_service(self):
        for stage,days in enumerate((1,3,7,14,30),1):
            a=self.j.start(self.mid,self.chapter['id']);self.j.submit(self.mid,a['id'],self.answers)
            r=self.j.rate(self.mid,a['id'],'remembered')
            self.assertEqual(r['stage'],stage)
            self.assertEqual((__import__('datetime').datetime.fromisoformat(r['due_at'])-__import__('datetime').datetime.fromisoformat(r['rated_at'])).days,days)
        a=self.j.start(self.mid,self.chapter['id']);self.j.submit(self.mid,a['id'],self.answers)
        r=self.j.rate(self.mid,a['id'],'again');self.assertEqual(r['stage'],0)
        fresh=AcademyMaterials(MemoryStore(str(self.root/'memory.db')),self.root/'materials')
        self.assertEqual(fresh.journey.attempt(self.mid,a['id'])['rating'],'again')

    def test_changed_question_or_review_rejects_stale_attempt(self):
        a=self.j.start(self.mid,self.chapter['id'])
        self.s.save_chapter_questions(self.mid,self.chapter['id'],'research',self.questions)
        with self.assertRaises(ValueError):self.j.submit(self.mid,a['id'],self.answers)
        self.assertEqual(self.s.state(self.mid)['journey']['review_queue'],[])

    def test_changed_source_revision_invalidates_prior_pass_and_recall(self):
        a=self.j.start(self.mid,self.chapter['id'])
        doc=self.s.document(self.mid);doc['payload']['revision']='new-source-version'
        with self.store._conn() as c:
            c.execute('UPDATE academy_materials SET payload=? WHERE id=?',(json.dumps(doc['payload']),self.mid))
        state=self.s.state(self.mid)
        self.assertEqual(state['chapters'][0]['status'],'not_started')
        self.assertEqual(state['journey']['review_queue'],[])
        with self.assertRaises(ValueError):self.j.attempt(self.mid,a['id'])

    def test_wrong_learner_material_and_unreviewed_chapter_are_rejected(self):
        a=self.j.start(self.mid,self.chapter['id'])
        with self.assertRaises(ValueError):self.j.attempt(self.mid,a['id'],'other')
        other=self.s.upload('other.txt',b'Another learning material.')['document']['id']
        with self.assertRaises(ValueError):self.j.attempt(other,a['id'])
        with self.assertRaises(ValueError):self.j.start(self.mid,self.s.state(self.mid)['chapters'][1]['id'])
        with self.assertRaises(ValueError):self.j.passport(self.mid,'other')

    def test_old_recall_and_passport_survive_activity_window(self):
        a=self.j.start(self.mid,self.chapter['id']);self.j.submit(self.mid,a['id'],self.answers)
        self.j.rate(self.mid,a['id'],'partial')
        self.s.upload('unrelated.txt',b'Private unrelated source.')
        for i in range(205):self.s.event(self.mid,'tutor',dict(citation='elsewhere',answer=str(i)))
        doc=self.j.passport(self.mid)
        self.assertEqual(len(doc['recall_attempts']),1)
        self.assertEqual(len(doc['evidence_events']),3)
        self.assertNotIn('Private unrelated',json.dumps(doc))
        self.assertEqual(self.s.state(self.mid)['journey']['review_queue'][0]['rating'],'partial')

    def client(self,model):
        app=FastAPI();app.include_router(materials_router(lambda:self.s,model))
        client=TestClient(app);self.addCleanup(client.close);return client

    def test_http_recall_roundtrip_export_and_scope(self):
        model=AsyncMock();client=self.client(model);base='/api/academy/learning/materials/'+self.mid
        a=client.post(base+'/recall-start',json=dict(chapter=self.chapter['id'])).json()
        self.assertEqual(client.post(base+'/recall-submit',json=dict(attempt_id=a['id'],answers=self.answers)).status_code,200)
        self.assertEqual(client.post(base+'/recall-rate',json=dict(attempt_id=a['id'],rating='remembered')).status_code,200)
        self.assertEqual(client.get(base+'/recalls/'+str(a['id'])).json()['rating'],'remembered')
        self.assertEqual(client.get(base+'/passport').json()['schema'],'clawos.learning-passport.v1')
        self.assertEqual(client.get(base+'/passport?learner_id=other').status_code,404)
        model.assert_not_called()

    def test_model_failure_and_invalid_evidence_persist_failed_trace(self):
        base='/api/academy/learning/materials/'+self.mid
        for model in [AsyncMock(side_effect=RuntimeError('offline')),
                      AsyncMock(return_value={'choices':[{'message':{'content':'{}'}}]})]:
            client=self.client(model)
            self.assertIn(client.post(base+'/guide',json=dict(citation=self.chapter['citation'])).status_code,(400,502))
            run_event=next(e for e in self.s.state(self.mid)['events'] if e['kind']=='model_run')
            self.assertEqual(run_event['data']['status'],'failed')
            run=self.store.get_run_record(run_event['data']['run_id'])
            self.assertEqual(run['status'],'failed');self.assertTrue(run['failure_cases'])

    def test_double_review_trace_matches_persisted_learning_outcome(self):
        model=AsyncMock(return_value={'choices':[{'message':{'content':json.dumps(self.judge)}}]})
        client=self.client(model)
        result=client.post('/api/academy/learning/materials/'+self.mid+'/chapter-review',json=dict(response_id=self.response['id']))
        self.assertEqual(result.status_code,200,result.text)
        run=self.store.get_run_record(result.json()['run_id'])
        self.assertEqual(run['status'],'passed');self.assertEqual(run['metrics']['model_calls'],2)
        self.assertEqual([s['role'] for s in run['workflow']['trace']],['teacher','reviewer'])
        self.assertEqual(run['outputs']['event_id'],result.json()['id'])

    def test_database_health_detects_application_orphans_without_foreign_keys(self):
        with self.store._conn() as c:
            c.execute("INSERT INTO academy_material_events(material_id,kind,payload) VALUES ('missing','draft','{}')")
        ops=MaintenanceService(store=self.store,db_path=self.root/'memory.db',base_dir=self.root,config={})
        health=ops.database_health()
        self.assertTrue(health['sqlite_ok']);self.assertFalse(health['ok'])
        self.assertEqual(health['logical_checks']['orphan_academy_material_events'],1)

    def test_database_health_exposes_failed_vector_projection(self):
        with self.store._conn() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS knowledge_vector_outbox_v2
                (id INTEGER PRIMARY KEY,processed_at TEXT,error TEXT)''')
            c.execute("INSERT INTO knowledge_vector_outbox_v2(processed_at,error) VALUES ('','embedding offline')")
        ops=MaintenanceService(store=self.store,db_path=self.root/'memory.db',base_dir=self.root,config={})
        health=ops.database_health()
        self.assertTrue(health['sqlite_ok']);self.assertEqual(health['status'],'degraded')
        self.assertEqual(health['vector_projection']['failed'],1)
        self.assertIn('vector_projection_failed',health['warnings'])


if __name__=='__main__':unittest.main()
