import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.autonomous_subagent_service import AutonomousSubagentService, SubagentRoleSpec
from services.agent_orchestration_service import AgentOrchestrationService
from services.workflow_engine import WorkflowEngine


class Provider:
    def __init__(self,role,calls,failed=False,tokens=10):
        self.role,self.calls,self.failed,self.tokens=role,calls,failed,tokens
    async def complete(self,messages,options):
        self.calls.append(self.role)
        return dict(ok=not self.failed,error='offline' if self.failed else '',usage=dict(total_tokens=self.tokens),
            content=json.dumps(dict(summary='Verified result',claims=[],evidence=[],artifacts=[],proposed_actions=[],
                confidence=.9,open_risks=[],hard_gate_failures=[],requires_human_approval=False)))


class AgentChainIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_non_gate_role_never_releases_or_invokes_descendants(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[];store=MemoryStore(str(Path(td)/'memory.db'))
            service=AutonomousSubagentService(lambda s:Provider(s.role_id,calls,failed=s.role_id=='source'),checkpoint_root=td,store=store)
            result=await service.run('Ground an answer',[
                SubagentRoleSpec('source','Find evidence','Retrieve source',max_model_calls=1),
                SubagentRoleSpec('writer','Write','Write answer',depends_on=['source']),
                SubagentRoleSpec('reviewer','Review','Review answer',depends_on=['writer'])])
            self.assertEqual(result['status'],'failed');self.assertEqual(calls,['source'])
            self.assertEqual(result['results']['writer']['status'],'blocked')
            self.assertEqual(store.get_run_record(result['run_id'])['status'],'failed')
            self.assertTrue(store.get_run_record(result['run_id'])['failure_cases'])

    async def test_provider_initialization_failure_preserves_checkpoint_and_independent_work(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[]
            def factory(spec):
                if spec.role_id=='bad':raise RuntimeError('provider unavailable')
                return Provider(spec.role_id,calls)
            service=AutonomousSubagentService(factory,checkpoint_root=td)
            result=await service.run('Inspect', [SubagentRoleSpec('bad','A','A'),SubagentRoleSpec('good','B','B')])
            self.assertEqual(result['status'],'failed');self.assertEqual(calls,['good'])
            self.assertTrue(Path(result['checkpoint']).is_file())

    async def test_cyclic_dag_rejected_before_any_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[];service=AutonomousSubagentService(lambda s:Provider(s.role_id,calls),checkpoint_root=td)
            with self.assertRaises(ValueError):
                await service.run('Cycle',[SubagentRoleSpec('a','A','A',depends_on=['b']),SubagentRoleSpec('b','B','B',depends_on=['a'])])
            self.assertEqual(calls,[]);self.assertEqual(list(Path(td).iterdir()),[])

    async def test_resume_retries_failed_branch_preserves_success_and_rejects_changed_policy(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[];failed=True
            roles=[SubagentRoleSpec('a','A','A',max_model_calls=1),SubagentRoleSpec('b','B','B'),SubagentRoleSpec('c','C','C',depends_on=['a'])]
            service=AutonomousSubagentService(lambda s:Provider(s.role_id,calls,failed=failed and s.role_id=='a'),checkpoint_root=td)
            first=await service.run('Resume',roles)
            with self.assertRaises(ValueError):await service.run('Other objective',roles,resume_checkpoint=first['checkpoint'])
            with self.assertRaises(ValueError):await service.run('Resume',roles,shared_evidence=[dict(citation='changed')],resume_checkpoint=first['checkpoint'])
            with self.assertRaises(ValueError):await service.run('Resume',[SubagentRoleSpec('a','changed','A')],resume_checkpoint=first['checkpoint'])
            failed=False;calls.clear()
            resumed=await service.run('Resume',roles,resume_checkpoint=first['checkpoint'])
            self.assertEqual(resumed['status'],'passed');self.assertEqual(calls,['a','c'])
            self.assertEqual(first['run_id'],resumed['run_id'])

    async def test_rework_rebuilds_intermediate_dependents_before_review_and_release(self):
        with tempfile.TemporaryDirectory() as td:
            calls={};packets={}
            class ReworkProvider:
                def __init__(self,role):self.role=role
                async def complete(self,messages,options):
                    calls[self.role]=calls.get(self.role,0)+1
                    packet=json.loads(messages[1]['content']);packets[self.role]=packet
                    summary=self.role+'-v'+str(calls[self.role])
                    if self.role=='bridge':summary=packet['dependencies']['executor']['output']['summary']
                    content=dict(summary=summary,claims=[],evidence=[],artifacts=[],proposed_actions=[],confidence=.9,
                        open_risks=[],hard_gate_failures=['missing evidence'] if self.role=='reviewer' and calls[self.role]==1 else [],requires_human_approval=False)
                    return dict(ok=True,usage=dict(total_tokens=10),content=json.dumps(content))
            roles=[SubagentRoleSpec('executor','Execute','Execute'),SubagentRoleSpec('bridge','Build','Build',depends_on=['executor']),
                   SubagentRoleSpec('reviewer','Review','Review',depends_on=['bridge'],hard_gate=True),
                   SubagentRoleSpec('release','Release','Release',depends_on=['reviewer'])]
            service=AutonomousSubagentService(lambda s:ReworkProvider(s.role_id),checkpoint_root=td)
            result=await service.run('Rework',roles,review_cycle=dict(executor_role='executor',reviewer_role='reviewer'))
            self.assertEqual(result['status'],'passed',result)
            self.assertEqual(calls,dict(executor=2,bridge=2,reviewer=2,release=1))
            self.assertEqual(packets['reviewer']['dependencies']['bridge']['output']['summary'],'executor-v2')

    async def test_hard_failure_keeps_all_already_executed_siblings_in_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[];service=AutonomousSubagentService(lambda s:Provider(s.role_id,calls,failed=s.role_id=='bad'),checkpoint_root=td)
            result=await service.run('Siblings',[SubagentRoleSpec('bad','A','A',max_model_calls=1,hard_gate=True),SubagentRoleSpec('good','B','B')])
            self.assertEqual(set(result['results']),{'bad','good'})
            checkpoint=json.loads(Path(result['checkpoint']).read_text())
            self.assertEqual(checkpoint['completed']['good']['status'],'passed')

    async def test_reported_token_overrun_cannot_be_persisted_as_pass(self):
        with tempfile.TemporaryDirectory() as td:
            service=AutonomousSubagentService(lambda s:Provider(s.role_id,[],tokens=20000),checkpoint_root=td)
            result=await service.run('Budget',[SubagentRoleSpec('a','A','A')],run_budget=dict(max_tokens=1000))
            self.assertEqual(result['status'],'budget_exhausted')

    async def test_same_score_reviews_are_distinct_and_rework_state_is_consistent(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'));service=AgentOrchestrationService(store=store)
            result=dict(project_name='Project',score=70,quality_gate=dict(status='revision_required',failures=['Missing evidence']),
                rework_loop=dict(final_quality_gate=dict(status='pass',failures=[]),
                    rounds=[dict(round=1,status='pass',final_score=90,quality_gate=dict(status='pass',failures=[]))]))
            first=service.normalize_committee_result(result);second=service.normalize_committee_result(result)
            self.assertNotEqual(first['run_id'],second['run_id'])
            self.assertEqual(first['status'],'passed')
            self.assertEqual(first['workflow']['state_machine']['state'],'passed')
            self.assertEqual(first['outputs']['quality_gate']['status'],'pass')
            self.assertEqual(store.get_run_record(first['run_id'])['status'],'passed')

    async def test_missing_gate_evidence_cannot_pass_workflow(self):
        result=WorkflowEngine().gate_rework_until_done(workflow_id='empty',name='review',gate_statuses=[])
        self.assertEqual(result['state'],'failed')


if __name__=='__main__':unittest.main()
