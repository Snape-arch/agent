import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import test_reliable_collaboration as fixtures
from services.coding_contracts import CodingContracts
from services.coding_workflow_service import CodingWorkflowService
from services.reliable_collaboration import ReliableCollaborationService
from services.collaboration_delivery import CollaborationDelivery


def requirements():
    return [dict(id='addition',statement='addition retains the caller contract',paths=['a.py'],test_indexes=[0]),
            dict(id='multiplication',statement='multiplication produces actual products',paths=['b.py'],test_indexes=[0])]


class ContractValidationTests(unittest.TestCase):
    def test_frozen_copy_and_binding_cannot_alias_caller_data(self):
        caller=requirements();frozen=CodingContracts.validate(caller,['a.py','b.py'],[['python','check.py']])
        caller[0]['paths'][0]='other.py';self.assertEqual(frozen[0]['paths'],['a.py'])
        selected=CodingContracts.select(frozen,['a.py']);selected[0]['statement']='weakened'
        self.assertNotEqual(selected[0]['statement'],frozen[0]['statement'])
        owners=CodingContracts.bind_plan(frozen,fixtures.plan()['nodes'])
        self.assertEqual(owners,dict(addition=['a'],multiplication=['b']))
        with self.assertRaises(ValueError):CodingContracts.bind_plan(frozen,fixtures.plan()['nodes'][:1])

    def test_invalid_contracts_rejected_before_execution(self):
        for change in ('bool_index','outside_index','outside_path','duplicate_id','missing_binding','unknown_rule'):
            value=requirements()
            if change=='bool_index':value[0]['test_indexes']=[True]
            if change=='outside_index':value[0]['test_indexes']=[1]
            if change=='outside_path':value[0]['paths']=['outside.py']
            if change=='duplicate_id':value[1]['id']='addition'
            if change=='missing_binding':value[0]['test_indexes']=[]
            if change=='unknown_rule':value[0]['rule']=dict(kind='python_exact_type',function='add',parameter='a',builtin_type=[])
            with self.subTest(change=change),self.assertRaises(ValueError):
                CodingContracts.validate(value,['a.py','b.py'],[['python','check.py']])

    def test_test_bindings_do_not_promote_failed_or_missing_evidence(self):
        value=requirements();digest=ReliableCollaborationService.digest
        for tests in ([],[dict(exit_code=1)]):
            self.assertTrue(all(not r['passed'] for r in CodingContracts.results(value,tests,digest)))
        self.assertTrue(all(r['passed'] for r in CodingContracts.results(value,[dict(exit_code=0)],digest)))


class ContractRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.repo=fixtures.fixture(self.folder);self.root=self.folder/'runs'
        def command(repo,argv,timeout):
            proc=subprocess.run(argv,cwd=repo,capture_output=True,text=True,timeout=timeout)
            return dict(exit_code=proc.returncode,stdout=proc.stdout,stderr=proc.stderr,sandbox={'backend':'fixture-native','os_enforced':False})
        self.runner=patch.object(CodingWorkflowService,'_run_command',side_effect=command)
        self.runner.start();self.addCleanup(self.runner.stop)

    def service(self,handler=None,calls=None):
        return ReliableCollaborationService(lambda spec:fixtures.Provider(spec.role_id,handler,calls),root=self.root)

    def kwargs(self,value=None):
        return dict(allowed_paths=['a.py','b.py'],test_commands=[[sys.executable,'-B','check.py']],
                    confirmed=True,requirements=value or requirements())

    async def test_requirement_receipts_replay_and_changed_resume_rejected(self):
        svc=self.service();value=requirements()
        result=await svc.run(self.repo,'Fix arithmetic',**self.kwargs(value))
        self.assertEqual(result['status'],'passed',result)
        self.assertTrue(all(r['passed'] for r in result['requirement_results']))
        self.assertEqual(result['requirement_owners'],dict(addition=['a'],multiplication=['b']))
        packet=await CollaborationDelivery(svc).prepare(result['run_id'],confirmed=True)
        self.assertEqual(packet['manifest']['requirements'],value)
        self.assertEqual(packet['manifest']['requirements_digest'],result['requirements_digest'])
        value[0]['statement']='different contract'
        with self.assertRaises(ValueError):await svc.run(self.repo,'Fix arithmetic',resume_run=result['run_id'],**self.kwargs(value))
        state=svc.load(result['run_id']);state['requirement_results'][0]['passed']=False;svc.save(state)
        with self.assertRaises(ValueError):CollaborationDelivery(svc).inspect(result['run_id'])

    async def test_exact_type_requires_declared_rule_actual_assertion_and_runtime_retest(self):
        (self.repo/'check.py').write_text('''import unittest
from a import add
from b import mul
class SubInt(int):pass
class Checks(unittest.TestCase):
    def test_contract(self):
        with self.assertRaises(ValueError):add(SubInt(3),2)
        self.assertEqual(add(3,2),5)
        self.assertEqual(mul(3,2),6)
unittest.main()
''',encoding='utf-8')
        fixtures.git(self.repo,'add','check.py');fixtures.git(self.repo,'-c','user.name=Fixture','-c','user.email=fixture@local','commit','-m','actual assertion')
        value=requirements();value[0]['rule']=dict(kind='python_exact_type',function='add',parameter='a',builtin_type='int')
        calls=[]
        def handler(role,packet):
            if role=='a':
                self.assertEqual(packet['requirements'][0]['rule'],value[0]['rule'])
                return dict(changes=[dict(path='a.py',operation='replace',old_text='return a - b',
                    new_text='if not isinstance(a, int):\n        raise ValueError("integer required")\n    return a + b')])
            return fixtures.answer(role)
        svc=self.service(handler,calls);result=await svc.run(self.repo,'Exact caller type and arithmetic',**self.kwargs(value))
        self.assertEqual(result['status'],'passed',result)
        repairs=[e for e in result['events'] if e['event']=='coordinator_contract_repair']
        self.assertEqual(len(repairs),1);self.assertFalse(repairs[0]['model_generated'])
        self.assertNotIn('repairer',calls);self.assertNotIn('diagnostician',calls)
        self.assertNotEqual(result['integration']['test_rounds'][0]['tests'][0]['exit_code'],0)
        self.assertEqual(result['integration']['test_rounds'][1]['tests'][0]['exit_code'],0)
        self.assertEqual((self.repo/'a.py').read_text(),'def add(a, b):\n    return a - b\n')
        frames=result['integration']['failure_contexts'][0]['frames']
        self.assertIn('add',frames[0]['called_symbols'])
        self.assertIsNone(CodingContracts.exact_type_repair(self.repo,value,[dict(exit_code=0)],frames,svc.read_files))
        self.assertIsNone(CodingContracts.exact_type_repair(self.repo,value,[dict(exit_code=1)],[],svc.read_files))

    async def test_diagnosis_reads_failing_assertion_and_limits_repair_scope(self):
        observed=[]
        def handler(role,packet):
            if role=='b':
                result=fixtures.answer('b');result['changes'][0]['new_text']='return a - b';return result
            if role=='diagnostician':
                self.assertIn('assert mul',packet['read_only_failure_context'][0]['snippet'])
                observed.append('diagnosis')
                return dict(hypothesis='mul subtracts rather than multiplying',targets=[dict(path='b.py',symbol='mul')],expected_test_effect='the product assertion passes')
            if role=='repairer':
                self.assertEqual(set(packet['files']),{'b.py'});self.assertIn('diagnosis',packet)
                observed.append('patch')
                return dict(changes=[dict(path='b.py',operation='replace',old_text='return a - b',new_text='return a * b')])
            return fixtures.answer(role)
        result=await self.service(handler).run(self.repo,'Fix arithmetic',**self.kwargs())
        self.assertEqual(result['status'],'passed',result);self.assertEqual(observed,['diagnosis','patch'])

    def test_traceback_paths_outside_repo_are_not_read(self):
        outside=self.folder/'outside.py';outside.write_text('sensitive fixture',encoding='utf-8')
        svc=self.service()
        frames=CodingContracts.failure_context(self.repo,[dict(exit_code=1,stderr=f'File "{outside}", line 1')],svc.safe_path,svc.git)
        self.assertEqual(frames,[])


if __name__=='__main__':unittest.main()
