"""Real owned Git/test commands, deterministic provider fixtures and gate denials."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from reflection.self_evolution import SelfEvolutionManager
from services.coding_comparison_service import digest
from services.coding_rollout_service import CodingRolloutService, candidate_family, coding_gate, paired_statistics
from services.coding_strategy_service import CodingStrategyService
import test_coding_comparison_service as comparison
import test_coding_strategy_service as previous
import test_self_evolution


def observations(count, *, same=False, failed=False, expensive=False):
    rows=[]
    for n in range(count):
        for variant in ('baseline','candidate'):
            rows.append(dict(task_group='same' if same else str(n),variant=variant,usable=True,
                accepted=not failed,tokens=5000 if expensive and variant=='candidate' else 100,
                calls=1,seconds=1,limits={'max_tokens':5000,'max_wall_seconds':100,'max_model_calls':10}))
    return rows


class StatisticsTests(unittest.TestCase):
    def test_minimum_independent_support_and_repeat_dedup(self):
        self.assertTrue(paired_statistics(observations(30))['passed'])
        self.assertFalse(paired_statistics(observations(29))['passed'])
        result=paired_statistics(observations(100,same=True))
        self.assertEqual(result['independent_groups'],1);self.assertFalse(result['passed'])

    def test_identical_failures_and_high_cost_never_validate(self):
        self.assertFalse(paired_statistics(observations(30,failed=True))['passed'])
        self.assertFalse(paired_statistics(observations(30,expensive=True))['passed'])

    def test_bad_arm_and_incomplete_pair_are_not_censored(self):
        rows=observations(31);rows[0]['usable']=False
        result=paired_statistics(rows)
        self.assertEqual(result['usable_groups'],30);self.assertFalse(result['passed'])
        self.assertFalse(result['all_pairs_usable'])
        self.assertFalse(paired_statistics(observations(31)[1:])['passed'])


class RolloutTests(unittest.IsolatedAsyncioTestCase):
    setUp=previous.StrategyTests.setUp
    case=previous.StrategyTests.case

    def candidate(self):
        return SelfEvolutionManager(self.store).create_run('prompt_policy','coding.proposal',{}, {'system':'ROLLOUT_CANDIDATE_MARKER'})

    def factory(self,role):return comparison.Provider(role)

    async def run_rollout(self,run=None,**kwargs):
        run=run or self.candidate()
        result=await CodingRolloutService(self.store,self.service.root).run(run['id'],[self.case()],self.factory,confirmed=True,**kwargs)
        return run,result

    async def test_actual_prompt_binding_both_variants_native_replay_no_publication(self):
        seen=[]
        def factory(role):return comparison.Provider(role,hook=lambda messages:seen.append(copy.deepcopy(messages)))
        run=self.candidate();rollout=CodingRolloutService(self.store,self.service.root)
        result=await rollout.run(run['id'],[self.case()],factory,confirmed=True)
        report=result['report'];self.assertTrue(report['complete'])
        self.assertEqual([r['variant'] for r in report['observations']],['baseline','candidate'])
        self.assertTrue(all(r['accepted'] for r in report['observations']),result)
        self.assertEqual(['ROLLOUT_CANDIDATE_MARKER' in m[0]['content'] for m in seen],[False,True])
        self.assertEqual(rollout.verified(run['id'])['statistics']['independent_groups'],1)
        self.assertFalse(coding_gate(self.store,run['id'])['passed'])
        self.assertFalse(self.store.get_runtime_policy('prompt_policy','coding.proposal'))
        self.assertEqual(self.store.list_self_evolution_quality_signals(run['id']),[])
        self.assertFalse(list(self.root.rglob('MODEL_COMMAND_EXECUTED')))
        self.assertIn('return a - b',(self.repo/'a.py').read_text())
        self.assertEqual(self.service.preview(self.case(),self.factory)['benefit']['independent_groups'],0)

    async def test_success_and_failure_are_observed_not_overwritten(self):
        class Conditional(comparison.Provider):
            async def complete(self,messages,options):
                self.wrong='ROLLOUT_CANDIDATE_MARKER' not in messages[0]['content']
                return await super().complete(messages,options)
        run=self.candidate();service=CodingRolloutService(self.store,self.service.root)
        result=await service.run(run['id'],[self.case()],lambda role:Conditional(role),confirmed=True,limits={'max_attempts':1})
        rows=result['report']['observations']
        self.assertEqual([r['accepted'] for r in rows],[False,True])
        self.assertGreater(result['report']['statistics']['mean_utility_delta'],.9)
        self.assertFalse(result['report']['statistics']['passed'])

    async def test_counterbalanced_repetitions_do_not_add_independent_tasks(self):
        run,result=await self.run_rollout(repetitions=2)
        rows=result['report']['observations']
        self.assertEqual([r['variant'] for r in rows],['baseline','candidate','candidate','baseline'])
        self.assertEqual(result['report']['statistics']['independent_groups'],1)

    async def test_caller_forged_pass_metrics_and_cached_gate_cannot_release(self):
        run,_=await self.run_rollout()
        manager=SelfEvolutionManager(self.store)
        generic=test_self_evolution.SelfEvolutionTests()._benchmarks()
        generic['coding_execution']={'passed':True,'case_count':999}
        evaluated=manager.evaluate(run['id'],generic)
        self.assertFalse(evaluated['gate_result']['passed'])
        self.assertEqual(evaluated['gate_result']['coding_execution']['statistics']['independent_groups'],1)
        self.store.update_self_evolution_run(run['id'],status='validated',gate_result={'passed':True})
        with self.assertRaisesRegex(ValueError,'coding regression'):manager.start_shadow(run['id'])

    async def test_tampered_child_answer_and_parent_report_fail_closed(self):
        run,result=await self.run_rollout();parent=self.service.root/result['folder']
        report_file=parent/'report.json';report=json.loads(report_file.read_text());report['complete']=False
        report_file.write_text(json.dumps(report))
        self.assertFalse(coding_gate(self.store,run['id'])['passed'])
        report['complete']=True;report_file.write_text(json.dumps(report))
        first=self.service.root/report['observations'][0]['child_folder']
        answer=next(first.glob('arm-*/answer-1.json'));data=json.loads(answer.read_text());data['content']='tampered'
        answer.write_text(json.dumps(data))
        gate=coding_gate(self.store,run['id']);self.assertFalse(gate['passed']);self.assertIn('receipt',gate['reason'])

    async def test_stale_executor_and_changed_candidate_are_rejected(self):
        run,_=await self.run_rollout()
        import services.coding_strategy_service as strategy
        with patch.dict(strategy.LOADED_WITNESS,{str(ROOT/'reflection/self_evolution.py'):'0'*64}):
            gate=coding_gate(self.store,run['id']);self.assertFalse(gate['passed']);self.assertIn('stale',gate['reason'])
        self.store.set_runtime_policy('prompt_policy','coding.proposal',{'system':'changed baseline'})
        self.assertFalse(coding_gate(self.store,run['id'])['passed'])

    async def test_unknown_usage_or_transport_remains_an_unusable_pair(self):
        class Unknown(comparison.Provider):
            async def complete(self,messages,options):
                result=await super().complete(messages,options);result['usage']={};return result
        run=self.candidate();result=await CodingRolloutService(self.store,self.service.root).run(run['id'],[self.case()],lambda role:Unknown(role),confirmed=True)
        self.assertTrue(result['report']['complete']);self.assertFalse(result['report']['statistics']['all_pairs_usable'])
        self.assertFalse(coding_gate(self.store,run['id'])['passed'])

    async def test_policy_mutation_mid_run_keeps_no_complete_rollout_receipt(self):
        run=self.candidate()
        def hook(messages):self.store.set_runtime_policy('prompt_policy','coding.proposal',{'system':'changed baseline'})
        with self.assertRaises((RuntimeError,ValueError)):
            await CodingRolloutService(self.store,self.service.root).run(run['id'],[self.case()],lambda role:comparison.Provider(role,hook=hook),confirmed=True)
        with self.store._conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM coding_rollouts').fetchone()[0],0)

    async def test_routing_candidate_executes_actual_modes_in_matching_namespace(self):
        preview=self.service.preview(self.case(),self.factory)
        run=SelfEvolutionManager(self.store).create_run('routing_policy',preview['target_key'],{},
            {'coding_mode':'multi','namespace':preview['namespace']})
        result=await CodingRolloutService(self.store,self.service.root).run(run['id'],[self.case()],self.factory,confirmed=True)
        self.assertEqual([r['mode'] for r in result['report']['observations']],['single','multi'])
        self.assertTrue(all(r['accepted'] for r in result['report']['observations']))
        self.assertEqual([r['calls'] for r in result['report']['observations']],[1,4])
        self.assertFalse(self.store.get_runtime_policy('routing_policy',preview['target_key']))

    async def test_confirmation_duplicate_ids_and_unsupported_payload_denied(self):
        run=self.candidate();service=CodingRolloutService(self.store,self.service.root)
        with self.assertRaises(PermissionError):await service.run(run['id'],[self.case()],self.factory)
        with self.assertRaisesRegex(ValueError,'duplicate'):await service.run(run['id'],[self.case(),self.case()],self.factory,confirmed=True)
        wrong=SelfEvolutionManager(self.store).create_run('prompt_policy','coding.proposal',{}, {'system':'x','shell_command':'bad'})
        with self.assertRaisesRegex(ValueError,'unsupported'):await service.run(wrong['id'],[self.case()],self.factory,confirmed=True)

    def test_multiple_candidates_in_same_baseline_correct_the_confidence_family(self):
        run=self.candidate()
        self.candidate()  # Same payload does not inflate multiplicity.
        self.assertEqual(candidate_family(self.store,run),1)
        SelfEvolutionManager(self.store).create_run('prompt_policy','coding.proposal',{}, {'system':'OTHER_CANDIDATE'})
        self.assertEqual(candidate_family(self.store,run),2)
        rows=observations(30)
        for row in rows[:20]:
            if row['variant']=='candidate':row['tokens']=1500
        self.assertLessEqual(paired_statistics(rows,family_size=2)['utility_lower_bound'],paired_statistics(rows)['utility_lower_bound'])

    async def test_concurrent_candidate_is_denied_then_lock_releases_for_retry(self):
        gate=asyncio.Event();started=asyncio.Event()
        class Waiting(comparison.Provider):
            async def complete(self,messages,options):
                started.set();await gate.wait();return await super().complete(messages,options)
        factory=lambda role:Waiting(role)
        run=self.candidate();service=CodingRolloutService(self.store,self.service.root)
        task=asyncio.create_task(service.run(run['id'],[self.case()],factory,confirmed=True))
        try:
            await asyncio.wait_for(started.wait(),30)
            with self.assertRaises(TimeoutError):await service.run(run['id'],[self.case()],factory,confirmed=True)
        finally:
            gate.set();await task
        await service.run(run['id'],[self.case()],factory,confirmed=True)
        result=service.verified(run['id'])
        self.assertEqual(result['records'],2);self.assertEqual(result['statistics']['independent_groups'],1)

    async def test_candidate_payload_mutation_mid_execution_blocks_complete_receipt(self):
        run=self.candidate()
        def hook(messages):
            with self.store._conn() as c:
                c.execute('UPDATE self_evolution_runs SET candidate_payload=? WHERE id=?',(json.dumps({'system':'replaced'}),run['id']))
        with self.assertRaisesRegex(ValueError,'candidate changed'):
            await CodingRolloutService(self.store,self.service.root).run(run['id'],[self.case()],lambda role:comparison.Provider(role,hook=hook),confirmed=True)
        with self.store._conn() as c:self.assertEqual(c.execute('SELECT count(*) FROM coding_rollouts').fetchone()[0],0)


class ApiTests(unittest.TestCase):
    def test_rollout_offline_inspection_and_execution_authorization(self):
        import tempfile
        import clawos_server as server
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from memoryos.memory_store import MemoryStore
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);store=MemoryStore(str(root/'test.db'));app=FastAPI()
            for route in server.app.routes:
                if route.path=='/api/workspace/coding/strategy':app.router.routes.append(route)
            run=SelfEvolutionManager(store).create_run('prompt_policy','coding.proposal',{}, {'system':'marker'})
            with patch.object(server,'g_memory_store',store),patch.object(server,'OUTPUT_ROOT',root/'out'),patch.object(server,'g_upstream_provider',None),TestClient(app) as client:
                response=client.post('/api/workspace/coding/strategy',json={'action':'rollout_evidence','run_id':run['id']})
                self.assertEqual(response.status_code,200);self.assertEqual(response.json()['statistics']['independent_groups'],0)
                self.assertEqual(client.post('/api/workspace/coding/strategy',json={'action':'rollout','run_id':run['id']}).status_code,503)
                with patch.object(server,'g_upstream_provider',comparison.Provider()):
                    self.assertEqual(client.post('/api/workspace/coding/strategy',json={'action':'rollout','run_id':run['id'],'confirmed':'true'}).status_code,409)


if __name__=='__main__':unittest.main()
