"""Native execution, artifact denial, paired clustering and candidate gates."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from memoryos.memory_store import MemoryStore
from reflection.self_evolution import SelfEvolutionManager
from services.coding_comparison_service import digest
from services.coding_strategy_service import CodingStrategyService, paired_benefit
from services.coding_workflow_service import CodingWorkflowService
import test_coding_comparison_service as comparison


def observations(count, *, same=False, imported=False, multi_success=True, censored=False):
    bundles=[]
    for n in range(count):
        rows=[]
        for mode in ('single','multi'):
            rows.append(dict(namespace='n',task_group='same' if same else str(n),mode=mode,
                accepted=(mode=='multi')==multi_success,usable=not(censored and mode=='single'),
                tokens=100,seconds=1,calls=1,limits={'max_tokens':5000,'max_wall_seconds':100,'max_model_calls':10}))
        bundles.append(dict(id=str(n),kind='imported' if imported else 'native-paired',paired=True,rows=rows))
    return bundles


class BenefitTests(unittest.TestCase):
    def test_repeats_are_one_cluster_not_thirty_samples(self):
        result=paired_benefit(observations(100,same=True),'n')
        self.assertEqual(result['independent_groups'],1);self.assertIsNone(result['recommendation'])

    def test_imported_selected_and_censored_pairs_do_not_train(self):
        self.assertEqual(paired_benefit(observations(50,imported=True),'n')['independent_groups'],0)
        self.assertEqual(paired_benefit(observations(50,censored=True),'n')['independent_groups'],0)
        selected=observations(50)
        for b in selected:b['paired']=False
        self.assertEqual(paired_benefit(selected,'n')['independent_groups'],0)

    def test_sample_and_family_corrected_bounds_for_both_modes(self):
        self.assertIsNone(paired_benefit(observations(29),'n')['recommendation'])
        for success,expected in ((True,'multi'),(False,'single')):
            value=paired_benefit(observations(30,multi_success=success),'n')
            self.assertEqual(value['recommendation'],expected)
            self.assertGreater(value['lower_bounds'][expected],.02)
            self.assertFalse(value['runtime_promotion_evidence'])

    def test_cost_penalty_and_namespace_separation(self):
        rows=observations(30)
        for b in rows:
            b['rows'][0]['accepted']=True
            b['rows'][1].update(tokens=5000,seconds=100,calls=10)
        self.assertEqual(paired_benefit(rows,'n')['recommendation'],'single')
        self.assertEqual(paired_benefit(rows,'other')['independent_groups'],0)

    def test_mixed_task_clusters_have_no_overconfident_recommendation(self):
        rows=observations(30)
        for b in rows[:15]:
            for r in b['rows']:r['accepted']=not r['accepted']
        value=paired_benefit(rows,'n')
        self.assertEqual(value['mean_multi_minus_single'],0);self.assertIsNone(value['recommendation'])


class StrategyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.repo=comparison.fixtures.fixture(self.root)
        (self.repo/'post.py').write_text('from a import add\nfrom b import mul\nassert add(-3,2)==-1\nassert mul(-3,2)==-6\n')
        comparison.fixtures.git(self.repo,'add','.')
        comparison.fixtures.git(self.repo,'-c','user.name=Fixture','-c','user.email=fixture@local','commit','-m','post')
        self.store=MemoryStore(str(self.root/'test.db'))
        self.service=CodingStrategyService(self.store,self.root/'out')
        runner=patch.object(CodingWorkflowService,'_run_command',side_effect=comparison.native)
        runner.start();self.addCleanup(runner.stop)

    def case(self):return comparison.PipelineTests.case(self)
    def factory(self,role):return comparison.Provider(role)
    async def run_case(self,**kwargs):
        return await self.service.run(self.case(),self.factory,confirmed=True,**kwargs)

    async def test_native_pair_and_reingest_preserve_origin_no_source_apply(self):
        result=await self.run_case(paired=True)
        self.assertTrue(all(r['accepted'] for r in result['report']['arms']),result)
        self.assertEqual(result['evidence']['kind'],'native-paired')
        self.assertEqual(self.service.evidence.ingest(result['folder']),result['evidence'])
        decision=self.service.preview(self.case(),self.factory)
        self.assertEqual(decision['benefit']['independent_groups'],1)
        self.assertEqual(decision['selected_mode'],'single');self.assertFalse(decision['strategy_recommendation_applied'])
        self.assertIn('return a - b',(self.repo/'a.py').read_text())
        self.assertFalse(list(self.root.rglob('MODEL_COMMAND_EXECUTED')))
        with self.assertRaisesRegex(ValueError,'insufficient'):self.service.nominate_routing(decision['id'])

    async def test_failure_card_candidate_is_idempotent_sanitized_and_unpublished(self):
        class Bad(comparison.Provider):
            async def complete(self,messages,options):
                return dict(ok=True,provider='fixture',model='fixture',content='{"changes":[ SECRET_UNTRUSTED_RULE',
                    usage={'total_tokens':60},raw={'choices':[{'finish_reason':'stop'}]})
        result=await self.service.run(self.case(),lambda role:Bad(role),confirmed=True)
        self.assertFalse(result['report']['arms'][0]['accepted'])
        failures=self.service.evidence.failures();self.assertEqual(failures['eligible'],1)
        self.assertEqual(failures['observations'][0]['category'],'format')
        first=self.service.evidence.nominate_failures();second=self.service.evidence.nominate_failures()
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['status'],'candidate')
        self.assertNotIn('SECRET_UNTRUSTED_RULE',json.dumps(first))
        self.assertEqual(first['candidate_payload']['coding_failure_evidence']['independent_groups'],1)
        self.assertFalse(self.store.get_runtime_policy('prompt_policy','coding.proposal'))
        with self.assertRaisesRegex(ValueError,'canary'):SelfEvolutionManager(self.store).activate(first['id'])
        with self.store._conn() as c:
            cards=c.execute("SELECT * FROM reflection_cards WHERE trigger_type='coding_evidence'").fetchall()
        self.assertEqual(len(cards),1);self.assertNotIn('SECRET_UNTRUSTED_RULE',str([dict(r) for r in cards]))

    async def test_transport_unknown_usage_is_quarantined(self):
        class Unknown(comparison.Provider):
            async def complete(self,messages,options):
                return dict(ok=False,provider='fixture',model='fixture',content='',usage={},error='network fixture')
        result=await self.service.run(self.case(),lambda role:Unknown(role),confirmed=True)
        row=result['evidence']['rows'][0]
        self.assertFalse(row['usable']);self.assertEqual(row['category'],'transport_unverified')
        with self.assertRaisesRegex(ValueError,'no verified'):self.service.evidence.nominate_failures()

    async def test_governed_mode_executes_and_prompt_is_accounted_before_capture(self):
        self.store.set_runtime_policy('prompt_policy','coding.proposal',{'system':'BOUND_PROMPT_MARKER'})
        seen=[]
        def factory(role):return comparison.Provider(role,hook=lambda messages:seen.append(copy.deepcopy(messages)))
        first=self.service.preview(self.case(),factory)
        self.store.set_runtime_policy('routing_policy',first['target_key'],{'coding_mode':'multi','namespace':first['namespace']})
        result=await self.service.run(self.case(),factory,confirmed=True)
        self.assertEqual(result['decision']['selected_mode'],'multi')
        self.assertEqual(result['decision']['selection_source'],'governed_runtime_policy')
        self.assertEqual([r['mode'] for r in result['report']['arms']],['multi'])
        self.assertTrue(all('BOUND_PROMPT_MARKER' in m[0]['content'] for m in seen))
        arm=result['report']['arms'][0]
        inputs={digest(m) for m in seen}
        self.assertTrue(all(r['input_digest'] in inputs for r in arm['ledger']['reservations']))
        self.assertEqual(self.service.preview(self.case(),factory)['benefit']['independent_groups'],0)

    async def test_policy_drift_denies_evidence_admission(self):
        def hook(messages):self.store.set_runtime_policy('prompt_policy','coding.proposal',{'system':'changed'})
        with self.assertRaisesRegex(RuntimeError,'policy changed'):
            await self.service.run(self.case(),lambda role:comparison.Provider(role,hook=hook),confirmed=True)
        with self.store._conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM coding_evidence').fetchone()[0],0)

    async def test_tampered_normalized_receipt_is_rejected_after_ingestion(self):
        result=await self.run_case()
        answer=next((self.service.root/result['folder']).glob('arm-*/answer-1.json'))
        value=json.loads(answer.read_text());value['content']='tampered';answer.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'receipt'):self.service.evidence.bundles()

    async def test_native_context_mutation_is_rejected(self):
        result=await self.run_case(baseline_mode='multi')
        file=next((self.service.root/result['folder']).glob('arm-*/c/*/contexts/*.json'))
        value=json.loads(file.read_text());value['objective']='changed';file.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.service.evidence.bundles()

    async def test_patch_and_command_tamper_are_rejected_even_rehashed(self):
        result=await self.run_case();folder=self.service.root/result['folder']
        report_path=folder/'report.json';report=json.loads(report_path.read_text());row=report['arms'][0]
        arm_path=folder/row['artifact'];arm=json.loads(arm_path.read_text())
        arm['validation']['tests'][0]['command']=[sys.executable,'-c','pass']
        arm_path.write_text(json.dumps(arm));report['arms'][0]=arm|{'artifact':row['artifact'],'report_digest':digest(arm)}
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError,'commands changed'):self.service.evidence.verify(folder)
        arm['validation']['tests'][0]['command']=self.case()['test_commands'][0]
        arm_path.write_text(json.dumps(arm));report['arms'][0]=arm|{'artifact':row['artifact'],'report_digest':digest(arm)}
        report_path.write_text(json.dumps(report));(arm_path.parent/'changes.patch').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'patch digest'):self.service.evidence.verify(folder)

    async def test_imported_pair_never_becomes_native_training(self):
        result=await self.run_case(paired=True)
        other=CodingStrategyService(MemoryStore(str(self.root/'other.db')),self.service.root)
        imported=other.evidence.ingest(result['folder']);self.assertEqual(imported['kind'],'imported')
        self.assertEqual(other.preview(self.case(),self.factory)['benefit']['independent_groups'],0)

    async def test_confirmation_invalid_mode_and_foreign_path_denied(self):
        with self.assertRaises(PermissionError):await self.service.run(self.case(),self.factory)
        with self.assertRaises(ValueError):self.service.preview(self.case(),self.factory,baseline_mode='auto')
        with self.assertRaises(ValueError):self.service.evidence.ingest(self.repo)
        with self.assertRaises(ValueError):self.service.evidence.nominate_failures('infrastructure')

    def test_invalid_governed_namespace_cannot_choose_mode(self):
        preview=self.service.preview(self.case(),self.factory)
        self.store.set_runtime_policy('routing_policy',preview['target_key'],{'coding_mode':'multi','namespace':'wrong'})
        with self.assertRaisesRegex(ValueError,'namespace'):self.service.preview(self.case(),self.factory)

    def test_routing_nomination_is_pending_and_rejects_stale_corpus(self):
        preview=self.service.preview(self.case(),self.factory)
        synthetic=observations(30)
        for b in synthetic:
            for row in b['rows']:row['namespace']=preview['namespace']
        with patch.object(self.service.evidence,'bundles',return_value=synthetic):
            decision=self.service.preview(self.case(),self.factory)
            first=self.service.nominate_routing(decision['id']);second=self.service.nominate_routing(decision['id'])
        self.assertEqual(first['id'],second['id']);self.assertEqual(first['status'],'candidate')
        self.assertEqual(first['candidate_payload']['coding_mode'],'multi')
        self.assertFalse(self.store.get_runtime_policy('routing_policy',decision['target_key']))
        with self.assertRaisesRegex(ValueError,'canary'):SelfEvolutionManager(self.store).activate(first['id'])
        with patch.object(self.service.evidence,'bundles',return_value=synthetic[:-1]):
            with self.assertRaisesRegex(ValueError,'changed'):self.service.nominate_routing(decision['id'])

    def test_generic_config_benchmark_cannot_validate_coding_behavior(self):
        import test_self_evolution
        manager=SelfEvolutionManager(self.store)
        run=manager.create_run('prompt_policy','coding.proposal',{}, {'system':'candidate'})
        evidence=test_self_evolution.SelfEvolutionTests()._benchmarks()
        self.assertTrue(manager._evaluate_gate(manager._normalize_benchmarks(evidence))['passed'])
        evaluated=manager.evaluate(run['id'],evidence)
        self.assertFalse(evaluated['gate_result']['passed'])
        self.assertIn('coding_execution',evaluated['gate_result']['missing_benchmarks'])
        with self.assertRaisesRegex(ValueError,'regression'):manager.start_shadow(run['id'])

    def test_same_failure_task_in_two_namespaces_is_one_independent_group(self):
        failures={'observations':[dict(task_group='one',namespace=n,category='format',usable=True) for n in ('model-a','model-b')]}
        with patch.object(self.service.evidence,'failures',return_value=failures):
            candidate=self.service.evidence.nominate_failures()
        self.assertEqual(candidate['candidate_payload']['coding_failure_evidence']['independent_groups'],1)

    async def test_invalid_accounting_is_rejected_even_with_rehashed_reports(self):
        result=await self.run_case();folder=self.service.root/result['folder']
        report_path=folder/'report.json';original=json.loads(report_path.read_text());row=original['arms'][0]
        arm_path=folder/row['artifact'];original_arm=json.loads(arm_path.read_text())
        for bad in (-1,float('nan'),True,501):
            report=copy.deepcopy(original);arm=copy.deepcopy(original_arm);arm['ledger']['charged_tokens']=bad
            arm_path.write_text(json.dumps(arm));report['arms'][0]=arm|{'artifact':row['artifact'],'report_digest':digest(arm)}
            report_path.write_text(json.dumps(report))
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'accounting'):self.service.evidence.verify(folder)


class ApiTests(unittest.TestCase):
    def test_offline_diagnostics_and_provider_and_confirmation_boundaries(self):
        import clawos_server as server
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);store=MemoryStore(str(root/'test.db'));app=FastAPI()
            for route in server.app.routes:
                if route.path=='/api/workspace/coding/strategy':app.router.routes.append(route)
            with patch.object(server,'g_memory_store',store),patch.object(server,'OUTPUT_ROOT',root/'out'),patch.object(server,'g_upstream_provider',None),TestClient(app) as client:
                response=client.post('/api/workspace/coding/strategy',json={'action':'failures'})
                self.assertEqual(response.status_code,200);self.assertEqual(response.json()['eligible'],0)
                self.assertEqual(client.post('/api/workspace/coding/strategy',json=[]).status_code,400)
                self.assertEqual(client.post('/api/workspace/coding/strategy',json={'action':'preview'}).status_code,503)
                self.assertEqual(client.post('/api/workspace/coding/strategy',json={'action':'ingest','folder':str(root)}).status_code,400)
                self.assertEqual(client.post('/api/workspace/coding/strategy',json={'action':'nominate_failure'}).status_code,400)
                with patch.object(server,'g_upstream_provider',comparison.Provider()):
                    self.assertEqual(client.post('/api/workspace/coding/strategy',json={'action':'run','confirmed':'true'}).status_code,409)


if __name__=='__main__':unittest.main()
