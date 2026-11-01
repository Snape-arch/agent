"""Synthetic fixture mechanism checks and real SQLite/API teaching closure."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from memoryos.memory_store import MemoryStore
from services.academy_materials import AcademyMaterials
from services.academy_learning_lab import AcademyLearningLab
from services.vision_api import vision_router
from services.vision_teaching import VisionTeaching, Conflict, digest
from services import vision_teaching_engine as engine


def request(template='rag',value=True,key='test-request-001'):
    return dict(request_id=key,template=template,value=value,seed=42,
                hypothesis='Synthetic prediction: compare the fixed arms and record limitations.',binding=None)


class MechanismTests(unittest.TestCase):
    def test_rag_retains_failures_and_locatable_current_passages(self):
        r=engine.execute('rag',True,42)
        self.assertEqual([a['metric'] for a in r['arms']],[4,5])
        self.assertTrue(any(not row['evaluation']['passed'] for row in r['arms'][1]['evidence']['rows']))
        docs={d['id']:d['text'] for d in engine.rag.DOCUMENTS}
        for row in r['arms'][1]['evidence']['rows']:
            for chunk in row['chunks']:
                self.assertTrue(chunk['current'])
                self.assertEqual(chunk['text'],docs[chunk['document_id']][chunk['start']:chunk['end']])
        self.assertFalse(r['paper_reproduction_verified']);self.assertFalse(r['learning_effect_verified'])

    def test_adapter_predictions_reconstruct_independent_test_loss(self):
        r=engine.execute('peft',2,42);a=r['arms'][1];e=a['evidence']
        self.assertFalse({tuple(x) for x in e['training_fixture']} & {tuple(x) for x in e['test_fixture']})
        squared=[]
        for x in e['test_fixture']:
            for o in range(6):
                prediction=sum(e['adapter_b'][o][k]*sum(e['adapter_a'][k][j]*x[j] for j in range(6)) for k in range(2))
                squared.append((prediction-[1.8,1.2,.6,0,0,0][o]*x[o])**2)
        self.assertAlmostEqual(sum(squared)/len(squared),a['metric'])
        self.assertEqual(a['metrics']['trainable_parameters'],24)
        self.assertLess(a['curve'][-1]['train'],a['curve'][0]['train'])
        self.assertEqual(r,engine.execute('peft',2,42))

    def test_probability_flow_numerical_convergence_and_cost(self):
        a,b,c=[engine.diffusion(n) for n in (8,32,64)]
        self.assertGreater(a['metric'],b['metric']);self.assertGreater(b['metric'],c['metric'])
        self.assertAlmostEqual(c['metrics']['mean'],2,delta=.03)
        self.assertAlmostEqual(c['metrics']['variance'],.25,delta=.04)
        self.assertEqual(c['metrics']['score_evaluations'],64*128)
        self.assertEqual(c['curve'][-1]['time'],0)

    def test_configs_reject_types_unbounded_work_and_unknown_fields(self):
        for k,v,s in [('rag',1,42),('peft',True,42),('diffusion',100000,42),('missing',1,42),('peft',2,True),('peft',2,-1)]:
            with self.assertRaises(ValueError):engine.execute(k,v,s)


class TeachingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.path=self.root/'teaching.sqlite';self.service=VisionTeaching(self.path)

    def test_immutable_hash_export_restart_and_no_mastery_claim(self):
        r=self.service.create('local-user',request());rid=r['report']['id']
        self.assertEqual(digest(r['report']),r['hash'])
        restored=VisionTeaching(self.path).get('local-user',rid)
        self.assertEqual(restored,r);self.assertFalse(r['learning_record']['mastery_updated'])
        self.assertIn('4',self.service.markdown(r));self.assertEqual(len(r['report']['source_hashes']),3)

    def test_idempotence_and_different_payload_conflict(self):
        data=request();r=self.service.create('local-user',data)
        self.assertEqual(self.service.create('local-user',data),r)
        data['hypothesis']+=' changed'
        with self.assertRaises(Conflict):self.service.create('local-user',data)
        self.assertEqual(self.service.history('local-user')['total'],1)

    def test_cross_instance_concurrent_same_request_has_one_result(self):
        other=VisionTeaching(self.path)
        with ThreadPoolExecutor(2) as pool:
            rows=list(pool.map(lambda s:s.create('local-user',request()),[self.service,other]))
        self.assertEqual(rows[0]['report']['id'],rows[1]['report']['id'])
        self.assertEqual(self.service.history('local-user')['total'],1)

    def test_actor_cannot_read_reflect_or_export_another_record(self):
        r=self.service.create('owner-a',request());rid=r['report']['id']
        with self.assertRaises(LookupError):self.service.get('other',rid)
        self.assertEqual(self.service.history('other')['total'],0)
        with self.assertRaises(LookupError):self.service.reflect('other',rid,self.reflection(r))

    @staticmethod
    def reflection(r):
        return dict(version=r['reflection_version'],report_hash=r['hash'],observation='Synthetic observation from the fixed paired run.',
                    explanation='Synthetic explanation with no teacher verification.',limitation='Synthetic fixtures do not establish open-domain results.')

    def test_append_only_reflections_cas_and_original_evidence(self):
        r=self.service.create('local-user',request());data=self.reflection(r);rid=r['report']['id']
        first=self.service.reflect('local-user',rid,data)
        with self.assertRaises(Conflict):self.service.reflect('local-user',rid,data)
        second=self.service.reflect('local-user',rid,self.reflection(first))
        self.assertEqual(second['reflection_version'],2)
        self.assertEqual(second['reflections'][0],first['reflections'][0])
        self.assertEqual(second['hash'],r['hash']);self.assertEqual(second['report'],r['report'])
        self.assertFalse(second['reflections'][0]['teacher_verified'])
        self.assertFalse(second['learning_record']['mastery_updated'])

    def test_cross_instance_reflection_race_only_one_saves(self):
        r=self.service.create('local-user',request());other=VisionTeaching(self.path)
        def write(s):
            try:s.reflect('local-user',r['report']['id'],self.reflection(r));return 'saved'
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(2) as pool:self.assertCountEqual(list(pool.map(write,[self.service,other])),['saved','conflict'])

    def test_report_and_reflection_corruption_rejected(self):
        r=self.service.create('local-user',request());rid=r['report']['id']
        self.service.reflect('local-user',rid,self.reflection(r))
        with self.service.connect() as c:c.execute('UPDATE teaching_reflections SET hash=?',('corrupted',))
        with self.assertRaises(ValueError):self.service.get('local-user',rid)
        with self.service.connect() as c:c.execute('UPDATE teaching_reports SET hash=?',('corrupted',))
        with self.assertRaises(ValueError):self.service.history('local-user')

    def test_history_pages_no_duplicates_and_template_filter(self):
        for i in range(21):self.service.create('local-user',request(key=f'fixture-request-{i}'))
        self.service.create('local-user',request('diffusion',16,'diffusion-request'))
        a=self.service.history('local-user');b=self.service.history('local-user',2)
        self.assertEqual(len(a['items']),20);self.assertTrue(a['has_more']);self.assertEqual(len(b['items']),2)
        self.assertFalse({r['id'] for r in a['items']} & {r['id'] for r in b['items']})
        self.assertEqual(self.service.history('local-user',template='diffusion')['total'],1)

    def test_unknown_fields_and_empty_prediction_are_not_persisted(self):
        for changes in ({'hypothesis':'short'},{'arbitrary_path':'outside'},{'seed':math.nan},{'request_id':'../bad'}):
            data=request();data.update(changes)
            with self.assertRaises(ValueError):self.service.create('local-user',data)
        self.assertEqual(self.service.history('local-user')['total'],0)

    def test_replay_recomputes_instead_of_trusting_an_exported_metric(self):
        from scripts.vision_teaching_replay import replay
        r=self.service.create('local-user',request('peft',2))
        self.assertTrue(replay(r)['passed'])
        altered=copy.deepcopy(r);altered['report']['result']['arms'][1]['metric']=0
        with self.assertRaises(ValueError):replay(altered)
        altered['hash']=digest(altered['report'])
        self.assertFalse(replay(altered)['passed'])

    def test_replay_rejects_other_implementation_identity(self):
        from scripts.vision_teaching_replay import replay
        r=self.service.create('local-user',request());r['report']['source_hashes']['vision_teaching_engine.py']='different'
        r['hash']=digest(r['report'])
        with self.assertRaises(ValueError):replay(r)


class BindingTests(unittest.TestCase):
    def setUp(self):
        TeachingTests.setUp(self)
        self.materials=AcademyMaterials(MemoryStore(str(self.root/'materials.db')),self.root/'materials')
        self.mid=self.materials.upload('book.md',b'# Evidence\nEvidence supports conclusions.')['document']['id']
        self.lab=AcademyLearningLab(self.materials)
        self.service=VisionTeaching(self.path,lab=lambda:self.lab)
        g=self.lab.graph.state(self.mid,'local-user');p=self.materials.document(self.mid)['payload']['passages'][0]
        self.graph=dict(nodes=[dict(id='evidence',title='Evidence',chapter=g['index']['chapters'][0]['id'],explanation='Evidence supports conclusions.',source=dict(citation=p['id'],quote='Evidence supports conclusions.'))],edges=[],covered_chapters=[g['index']['chapters'][0]['id']])
        self.lab.graph.save(self.mid,'local-user',self.graph,0,g['revision'])
        self.binding=dict(material_id=self.mid,node_id='evidence',revision=g['revision'],graph_version=1)

    def test_binding_freezes_source_and_rejects_stale_version(self):
        d=request();d['binding']=self.binding
        r=self.service.create('local-user',d)
        self.assertEqual(r['report']['binding']['node']['source']['quote'],'Evidence supports conclusions.')
        self.lab.graph.save(self.mid,'local-user',self.graph,1,self.binding['revision'])
        d['request_id']='stale-request'
        with self.assertRaises(Conflict):self.service.create('local-user',d)
        self.assertEqual(self.service.get('local-user',r['report']['id']),r)

    def test_source_changed_during_compute_does_not_save_success(self):
        d=request();d['binding']=self.binding;original=engine.execute
        def changed(*args):
            self.lab.graph.save(self.mid,'local-user',self.graph,1,self.binding['revision'])
            return original(*args)
        with patch('services.vision_teaching.engine.execute',changed):
            with self.assertRaises(Conflict):self.service.create('local-user',d)
        self.assertEqual(self.service.history('local-user')['total'],0)

    def test_unknown_node_or_unauthorized_book_not_accepted(self):
        d=request();d['binding']=dict(self.binding,node_id='invented')
        with self.assertRaises(ValueError):self.service.create('local-user',d)
        from fastapi import HTTPException
        d['binding']=self.binding
        with self.assertRaises(HTTPException):self.service.create('unknown-identity',d)


class TeachingApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);root=Path(self.tmp.name)
        self.service=VisionTeaching(root/'teaching.sqlite')
        class Identity:
            def identity(self,request):return dict(id='local-user')
        app=FastAPI();app.include_router(vision_router(lambda:None,Identity,root,teaching=lambda:self.service))
        self.client=TestClient(app,client=('127.0.0.1',50000));self.addCleanup(self.client.close)

    def test_owner_api_full_roundtrip_export_and_conflict_status(self):
        self.assertEqual(len(self.client.get('/api/vision/teaching/catalog').json()['templates']),3)
        r=self.client.post('/api/vision/teaching/reports',json=request());self.assertEqual(r.status_code,200)
        value=r.json();rid=value['report']['id']
        res=self.client.post('/api/vision/teaching/reports/'+rid+'/reflections',json=TeachingTests.reflection(value))
        self.assertEqual(res.status_code,200)
        self.assertEqual(self.client.post('/api/vision/teaching/reports/'+rid+'/reflections',json=TeachingTests.reflection(value)).status_code,409)
        export=self.client.get('/api/vision/teaching/reports/'+rid+'/export?format=md')
        self.assertIn('attachment',export.headers['content-disposition']);self.assertIn('本人记录',export.text)
        self.assertEqual(self.client.get('/api/vision/teaching/reports/'+rid+'/export').json()['report'],value['report'])

    def test_guest_bearer_foreign_origin_and_forwarded_denied(self):
        for headers in ({'Origin':'https://foreign.invalid'},{'Authorization':'Bearer test'},{'X-Forwarded-For':'127.0.0.1'}):
            self.assertEqual(self.client.get('/api/vision/teaching/catalog',headers=headers).status_code,403)
            self.assertEqual(self.client.post('/api/vision/teaching/reports',json=request(),headers=headers).status_code,403)

    def test_invalid_json_unknown_template_and_request_limit(self):
        self.assertEqual(self.client.post('/api/vision/teaching/reports',content='{').status_code,400)
        self.assertEqual(self.client.post('/api/vision/teaching/reports',content=' '*17000).status_code,413)
        self.assertEqual(self.client.post('/api/vision/teaching/reports',json=request('unknown',2)).status_code,400)


if __name__=='__main__':unittest.main()
