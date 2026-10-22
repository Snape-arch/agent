import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None

from memoryos.memory_store import MemoryStore
from services.evolution_experiments import EvolutionExperimentService, digest
from services.evolution_jobs import EvolutionJobStore, ExperimentLeaseLost
from services.evolution_review import EvolutionReviewService
from services.learning_governance import paired_quality_report, stratified_quality_report


def cases(count=200):
    return [{'id': f'case-{i}', 'group_id': f'group-{i}', 'query': f'Stage two independent question {i}',
             'reviewed_by': 'fixture-author', 'route': {'allowed_tools': ['file_read','file_write','shell_exec','web_fetch','web_search']},
             'required_tools': ['file_read'], 'forbidden_tools': ['file_write','shell_exec','web_fetch']}
            for i in range(count)]


class StageTwoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MemoryStore(str(Path(self.temp.name)/'isolated.db'))
        self.service = EvolutionExperimentService(self.store)
        self.jobs = EvolutionJobStore(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def freeze(self, data=None, key='default'):
        return self.service.freeze(target_type='tool_routing_policy', target_key=key,
                                   baseline_payload={}, cases=cases() if data is None else data, created_by='fixture-author')

    def expire(self, token):
        # Forced expiry exercises fencing without pretending to run 90 seconds.
        with self.store._conn() as conn:
            conn.execute('UPDATE evolution_attempts SET lease_until=0 WHERE token=?', (token,))

    def test_real_child_exit_reuses_saved_outcome_after_explicit_expiry(self):
        experiment = self.freeze()
        code = """
import sys,os
sys.path.insert(0,sys.argv[1])
from memoryos.memory_store import MemoryStore
from services.evolution_experiments import EvolutionExperimentService
from services.evolution_jobs import EvolutionJobStore
store=MemoryStore(sys.argv[2]); exp=store.claim_evolution_experiment(int(sys.argv[3]))
case=next(c for c in exp['definition']['cases'] if c['split']=='search')
outcome=EvolutionExperimentService._run_case(exp['definition'],case,{},None)
EvolutionJobStore(store).save(exp['id'],exp['attempt_token'],case['id'],'baseline',outcome)
os._exit(17)
"""
        result = subprocess.run([sys.executable,'-c',code,str(ROOT),self.store._db_path,str(experiment['id'])], timeout=30, capture_output=True, text=True)
        self.assertEqual(result.returncode,17,result.stderr)
        crashed = self.store.get_evolution_experiment(experiment['id'])
        self.assertEqual(crashed['job']['checkpoint_count'],1)
        token = crashed['job']['attempts'][0]['token']
        before = self.jobs.outcomes(experiment['id'])
        self.expire(token)
        completed = self.service.replay(experiment['id'])
        self.assertEqual([a['status'] for a in completed['job']['attempts']],['abandoned','completed'])
        self.assertTrue(completed['report']['eligible_for_regression_queue'])
        for key,value in before.items():
            self.assertEqual(self.jobs.outcomes(experiment['id'])[key],value)
        with self.assertRaises(ExperimentLeaseLost):
            self.jobs.finish(experiment['id'],token,{'forged':True})

    def test_pause_fences_worker_and_resume_uses_same_definition(self):
        exp = self.freeze(cases(20))
        first = self.jobs.claim(exp['id'])
        self.jobs.control(exp['id'],'pause')
        with self.assertRaises(ExperimentLeaseLost):
            self.jobs.save(exp['id'],first['attempt_token'],'case-0','baseline',{})
        resumed = self.jobs.claim(exp['id'])
        self.assertEqual(resumed['definition_digest'],exp['definition_digest'])
        self.assertNotEqual(first['attempt_token'],resumed['attempt_token'])
        with self.assertRaises(ExperimentLeaseLost):
            self.jobs.finish(exp['id'],first['attempt_token'],{},failed=True)
        self.assertEqual(self.store.get_evolution_experiment(exp['id'])['status'],'running')

    def test_live_lease_cannot_be_stolen_and_missing_token_cannot_finish(self):
        exp = self.freeze(cases(20)); self.jobs.claim(exp['id'])
        with self.assertRaisesRegex(ValueError,'live lease'):
            self.jobs.claim(exp['id'])
        with self.assertRaises(ExperimentLeaseLost):
            self.store.finish_evolution_experiment(exp['id'],{})

    def test_expired_worker_cannot_extend_lease(self):
        exp = self.jobs.claim(self.freeze(cases(20))['id'])
        self.expire(exp['attempt_token'])
        self.assertTrue(self.store.get_evolution_experiment(exp['id'])['job']['recoverable'])
        with self.assertRaises(ExperimentLeaseLost):
            self.jobs.heartbeat(exp['id'],exp['attempt_token'])

    def test_cancel_is_terminal_and_consumption_is_retained(self):
        exp = self.freeze(cases(20)); claimed=self.jobs.claim(exp['id'])
        cancelled=self.jobs.control(exp['id'],'cancel')
        self.assertEqual(cancelled['status'],'cancelled')
        with self.assertRaises(ValueError): self.jobs.claim(exp['id'])
        with self.assertRaises(ExperimentLeaseLost): self.jobs.finish(exp['id'],claimed['attempt_token'],{})
        with self.assertRaisesRegex(ValueError,'holdout exposure'):
            self.freeze(cases(20),'renamed-key')

    def test_case_checkpoint_corruption_fails_closed(self):
        exp=self.jobs.claim(self.freeze(cases(20))['id'])
        self.jobs.save(exp['id'],exp['attempt_token'],'case-0','baseline',{'output':'original'})
        with self.store._conn() as conn:
            conn.execute('UPDATE evolution_case_results SET outcome=?', ('{"output":"changed"}',))
        with self.assertRaisesRegex(ValueError,'digest mismatch'): self.jobs.outcomes(exp['id'])

    def test_normalized_duplicate_and_renamed_holdout_are_rejected(self):
        rows=cases(20); rows[1]['query']='  '+rows[0]['query'].upper()+'  '
        with self.assertRaisesRegex(ValueError,'duplicate task input'): self.freeze(rows)
        exp=self.freeze(cases(20)); self.jobs.claim(exp['id'])
        fresh=cases(20)
        for i,row in enumerate(fresh):
            row.update(id='renamed-'+str(i),group_id='changed-'+str(i),query='  '+row['query'].upper()+'  ')
        with self.assertRaisesRegex(ValueError,'holdout exposure'): self.freeze(fresh,'different-target')

    def test_two_frozen_experiments_cannot_claim_shared_holdout(self):
        first=self.freeze(cases(20)); second=self.freeze(cases(20),'second')
        self.jobs.claim(first['id'])
        with self.assertRaisesRegex(ValueError,'holdout exposure'): self.jobs.claim(second['id'])
        self.assertEqual(self.store.get_evolution_experiment(second['id'])['status'],'frozen')

    def test_completed_definition_stays_idempotent_and_old_attempts_backfill(self):
        exp=self.freeze(cases(20)); self.service.replay(exp['id'])
        self.assertEqual(self.freeze(cases(20))['id'],exp['id'])
        with self.store._conn() as conn: conn.execute('DELETE FROM evolution_exposures')
        with self.assertRaisesRegex(ValueError,'holdout exposure'): self.freeze(cases(20),'old-api')

    def test_real_fresh_inputs_can_form_next_campaign(self):
        exp=self.freeze(cases(20)); self.jobs.claim(exp['id'])
        fresh=cases(20)
        for row in fresh: row['query']='Different independent task: '+row['query']
        self.assertNotEqual(self.freeze(fresh)['id'],exp['id'])

    def test_actual_http_pause_resume_and_review_binding(self):
        import clawos_server as server
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        old=server.g_memory_store; server.g_memory_store=self.store
        try:
            app=FastAPI(); app.middleware('http')(server.workbench_access)
            for route in server.app.routes:
                if route.path.startswith('/api/self-evolution/'): app.router.routes.append(route)
            with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',45678)) as client:
                self.assertEqual(client.post('/api/self-evolution/experiments',json=[]).status_code,400)
                self.assertEqual(client.post('/api/self-evolution/experiments',content='broken').status_code,400)
                exp=self.freeze(cases(20)); base=f'/api/self-evolution/experiments/{exp["id"]}'
                response=client.post(base+'/control',json={'action':'pause'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['experiment']['status'],'paused')
                replay=client.post(base+'/replay'); self.assertEqual(replay.status_code,200,replay.text)
                detail=replay.json()['experiment']; report=detail['report']
                self.assertGreater(detail['job']['checkpoint_count'],0)
                self.assertEqual(client.post(base+'/control',json={'action':'cancel'}).status_code,409)
                output={'definition_digest':detail['definition_digest'],'report_digest':report['report_digest'],
                        'outputs':[{'case_id':pair['case_id'],'input_digest':pair['input_digest'],
                         'variants':{variant:{'text':'Synthetic external output','provider':'fixture','model':'fixture',
                                             'policy_digest':digest(policy)} for variant,policy in
                                             [('control',{}),('candidate',report['selected_payload'])]}}
                         for pair in report['holdout_pairs']]}
                packet=client.post(base+'/review-outputs',json=output)
                self.assertEqual(packet.status_code,200,packet.text)
                self.assertEqual(client.get(base+'/review/packet').json()['packet'],packet.json()['packet'])
                blocked=client.post(base+'/reviews',json={'reviewer':'test'},headers={'Origin':'https://untrusted.example'})
                self.assertEqual(blocked.status_code,403)
                self.assertFalse(client.get(base+'/review/summary').json()['summary']['runtime_promotion_evidence'])
        finally: server.g_memory_store=old


class SegmentTests(unittest.TestCase):
    def rows(self, count, segment, control, candidate):
        return [{'signal_type':'quality_score','value':score,'metadata':{'evidence_id':f'{segment}-{i}',
                'cluster_id':f'{segment}-{i}','input_digest':f'{segment}-{i}', 'segment':segment,'variant':variant}}
                for i in range(count) for variant,score in [('control',control),('candidate',candidate)]]

    def test_average_gain_cannot_hide_supported_segment_harm(self):
        rows=self.rows(60,'easy',.5,.8)+self.rows(30,'hard',.9,.75)
        self.assertTrue(paired_quality_report(rows)['passed'])
        report=stratified_quality_report(rows)
        self.assertFalse(report['passed']); self.assertFalse(report['segments']['hard']['passed'])

    def test_under_supported_declared_segment_blocks(self):
        rows=self.rows(30,'general',.7,.8)+self.rows(2,'rare',.7,.8)
        self.assertFalse(stratified_quality_report(rows)['passed'])

    def test_variant_cannot_change_its_segment(self):
        rows=self.rows(30,'same',.7,.8); rows[1]['metadata']['segment']='other'
        self.assertTrue(stratified_quality_report(rows)['identity_segment_conflict'])

    def test_live_run_gate_blocks_segment_harm_as_well_as_offline_gate(self):
        from reflection.self_evolution import SelfEvolutionManager
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'store.db')); manager=SelfEvolutionManager(store)
            run=manager.create_run('prompt','default',{'system':'old'},{'system':'new'})
            store.update_self_evolution_run(run['id'],status='shadow',release_stage='shadow')
            rows=self.rows(60,'easy',.5,.8)+self.rows(30,'hard',.9,.75)
            for row in rows:
                store.record_self_evolution_quality_signal(run['id'],row['signal_type'],row['value'],metadata=row['metadata'])
            report=manager.quality_evidence(run['id'])
            self.assertFalse(report['passed'])
            self.assertFalse(manager._quality_gate_passed(store.get_self_evolution_run(run['id']),require_support=False))


class ReviewTests(unittest.TestCase):
    # Keep expensive replay once for this class; clone the isolated fixture DB
    # into a fresh store per test. Never touch the everyday database.
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory()
        cls.fixture_db=str(Path(cls.fixture.name)/'fixture.db')
        store=MemoryStore(cls.fixture_db)
        svc=EvolutionExperimentService(store)
        exp=svc.freeze(target_type='tool_routing_policy',target_key='default',baseline_payload={},cases=cases(),created_by='fixture-author')
        cls.completed=svc.replay(exp['id'])

    @classmethod
    def tearDownClass(cls): cls.fixture.cleanup()

    def setUp(self):
        import sqlite3
        self.temp=tempfile.TemporaryDirectory()
        self.store=MemoryStore(str(Path(self.temp.name)/'isolated.db'))
        with sqlite3.connect(self.fixture_db) as source, sqlite3.connect(self.store._db_path) as target: source.backup(target)
        self.review=EvolutionReviewService(self.store)
        exp=self.completed; report=exp['report']
        self.output={'definition_digest':exp['definition_digest'],'report_digest':report['report_digest'],
                     'outputs':[{'case_id':pair['case_id'],'input_digest':pair['input_digest'],
                                'variants':{variant:{'text':f'External fixture answer {variant} {pair["case_id"]}',
                                  'provider':'synthetic-test','model':'fixture-no-real-model','policy_digest':digest(policy)}
                                  for variant,policy in [('control',exp['definition']['baseline_payload']),('candidate',report['selected_payload'])]}}
                                for pair in report['holdout_pairs']]}

    def tearDown(self): self.temp.cleanup()

    def ratings(self, packet, name='reviewer-a', score=.8):
        return {'packet_digest':packet['packet_digest'],'reviewer':name,
                'ratings':[{'entry_id':row['entry_id'],'options':{label:{'text_digest':value['text_digest'],'score':score,
                    'rationale':'Synthetic fixture explanation; not real teacher review','critical_error':False}
                    for label,value in row['options'].items()}} for row in packet['entries']]}

    def test_blind_export_hides_variant_identity_and_outputs_are_immutable(self):
        packet=self.review.freeze_outputs(1,self.output,'fixture-author')
        self.assertEqual(self.review.freeze_outputs(1,self.output,'fixture-author'),packet)
        serialized=json.dumps(packet)
        self.assertNotIn('policy_digest',serialized); self.assertNotIn('mapping',serialized); self.assertNotIn('provider',serialized)
        # Text itself can reveal identity; export cannot guarantee human blinding.
        self.output['outputs'][0]['variants']['candidate']['text']='changed answer'
        with self.assertRaisesRegex(ValueError,'immutable'): self.review.freeze_outputs(1,self.output)

    def test_two_reviews_are_task_level_not_more_samples_or_runtime_signals(self):
        packet=self.review.freeze_outputs(1,self.output,'fixture-author')
        one=self.review.submit(1,self.ratings(packet))
        self.assertFalse(one['reported_review_passed'])
        two=self.review.submit(1,self.ratings(packet,'reviewer-b'))
        self.assertTrue(two['reported_review_passed'])
        self.assertFalse(two['provider_execution_verified']); self.assertFalse(two['reviewer_identity_verified'])
        self.assertFalse(two['runtime_promotion_evidence']); self.assertFalse(two['semantic_entailment_verified'])
        metric=two['reviewed_gate']['segments']['default']['metrics']['quality_score']
        self.assertEqual(metric['independent_clusters'],self.completed['report']['holdout_groups'])
        self.assertEqual(self.store.list_self_evolution_quality_signals(1),[])

    def test_review_digests_self_review_and_nonfinite_scores_rejected(self):
        packet=self.review.freeze_outputs(1,self.output,'fixture-author')
        rating=self.ratings(packet,'fixture-author')
        with self.assertRaisesRegex(ValueError,'different'): self.review.submit(1,rating)
        rating=self.ratings(packet); rating['ratings'][0]['options']['A']['score']=float('nan')
        with self.assertRaisesRegex(ValueError,'finite'): self.review.submit(1,rating)
        rating=self.ratings(packet); rating['ratings'][0]['options']['A']['text_digest']='wrong'
        with self.assertRaisesRegex(ValueError,'digest'): self.review.submit(1,rating)

    def test_judgment_is_idempotent_but_cannot_be_replaced(self):
        packet=self.review.freeze_outputs(1,self.output,'fixture-author'); rating=self.ratings(packet)
        self.review.submit(1,rating); self.review.submit(1,rating)
        self.assertEqual(self.review.summary(1)['reviewer_count'],1)
        rating['ratings'][0]['options']['A']['score']=.7
        with self.assertRaisesRegex(ValueError,'overwrite'): self.review.submit(1,rating)

    def test_disagreement_and_critical_error_require_followup(self):
        packet=self.review.freeze_outputs(1,self.output,'fixture-author')
        self.review.submit(1,self.ratings(packet,score=.5))
        self.review.submit(1,self.ratings(packet,'reviewer-b',score=.9))
        self.assertTrue(self.review.summary(1)['adjudication_required'])
        rating=self.ratings(packet,'reviewer-c'); rating['ratings'][0]['options']['B']['critical_error']=True
        report=self.review.submit(1,rating)
        self.assertFalse(report['reported_review_passed']); self.assertTrue(report['critical_errors'])

    def test_mismatched_source_and_partial_output_cannot_be_graded(self):
        self.output['outputs'][0]['input_digest']='unrelated'
        with self.assertRaisesRegex(ValueError,'mismatched'): self.review.freeze_outputs(1,self.output)
        self.output['outputs'].pop()
        with self.assertRaisesRegex(ValueError,'one paired'): self.review.freeze_outputs(1,self.output)


if __name__=='__main__': unittest.main()
