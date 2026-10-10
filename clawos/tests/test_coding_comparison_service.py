"""Paired native-command fixtures and negative budget/provenance gates."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.autonomous_coding_service import AutonomousCodingService
from services.coding_comparison_service import CodingComparisonService, ComparisonCapture, digest
from services.coding_contracts import CodingContracts
from services.coding_execution_context import CodingExecutionContext as View
from services.coding_workflow_service import CodingWorkflowService
from services.execution_governance import ExecutionBudget
from services.reliable_collaboration import ReliableCollaborationService
import test_reliable_collaboration as fixtures


def native(repo, argv, timeout):
    result=subprocess.run(argv,cwd=repo,capture_output=True,text=True,timeout=timeout)
    return dict(command=argv,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr,
        sandbox=dict(backend='native-owned-fixture',production_sandbox_ready=False))


def proposal(*, wrong=False):
    return dict(changes=[dict(path='a.py',operation='replace',old_text='return a - b',new_text='return a + b'),
        dict(path='b.py',operation='replace',old_text='return a + b',new_text='return a - b' if wrong else 'return a * b')],
        test_commands=[[sys.executable,'-c',"open('MODEL_COMMAND_EXECUTED','w').write('bad')"]],explanation='arithmetic')


class Provider:
    name='fixture';model='fixture';base_url='loopback-fixture'
    def __init__(self,role='single',*,wrong=False,hook=None):self.role,self.wrong,self.hook=role,wrong,hook
    async def complete(self,messages,options):
        if self.hook:self.hook(messages)
        output=proposal(wrong=self.wrong) if self.role=='comparison_identity' else fixtures.answer(self.role)
        return dict(ok=True,provider=self.name,model=self.model,content=json.dumps(output),
            usage={'total_tokens':50},raw={'choices':[{'finish_reason':'stop'}]})


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def capture(self,**overrides):
        limits=CodingComparisonService.limits(dict(max_tokens=5000,max_output_tokens=100,max_model_calls=2,**overrides))
        return ComparisonCapture(self.root,limits,{})

    async def test_all_message_utf8_bytes_reserved_unknown_usage_is_not_free(self):
        class Unknown(Provider):
            async def complete(self,messages,options):
                self.assert_options=options
                return dict(ok=False,provider='fixture',model='fixture',content='',usage={})
        raw=Unknown();capture=self.capture();wrapped=capture.wrap(raw)
        messages=[dict(role='system',content='系统规则😀'),dict(role='user',content='用户任务')]
        await wrapped.complete(messages,{'max_tokens':99999})
        reserved=len(json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode())+100
        self.assertEqual(capture.ledger['charged_tokens'],reserved);self.assertEqual(capture.ledger['provider_tokens'],0)
        self.assertEqual(capture.ledger['reserved_tokens'],0);self.assertEqual(raw.assert_options['max_tokens'],100)
        self.assertTrue(capture.verify())

    async def test_concurrent_admission_calls_timeout_and_receipt_integrity(self):
        gate=asyncio.Event()
        class Slow(Provider):
            async def complete(self,messages,options):
                await gate.wait();return await super().complete(messages,options)
        capture=self.capture();wrapped=capture.wrap(Slow('comparison_identity'))
        tasks=[asyncio.create_task(wrapped.complete([dict(role='user',content='task')],{})) for _ in range(2)]
        await asyncio.sleep(.02)
        with self.assertRaisesRegex(RuntimeError,'budget'):await wrapped.complete([], {})
        self.assertEqual(capture.ledger['calls'],2);self.assertGreater(capture.ledger['reserved_tokens'],0)
        gate.set();await asyncio.gather(*tasks);self.assertEqual(capture.ledger['reserved_tokens'],0)
        path=self.root/'answer-1.json';data=json.loads(path.read_text());data['content']='changed';path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'receipt'):capture.verify()

    async def test_provider_exception_identity_and_incomplete_answers_remain_charged(self):
        for kind in ('exception','identity','length'):
            capture=ComparisonCapture(self.root/kind,self.capture().limits,{})
            (self.root/kind).mkdir()
            class Bad(Provider):
                async def complete(self,messages,options):
                    if kind=='exception':raise TimeoutError('owned fixture timeout')
                    value=await super().complete(messages,options)
                    if kind=='identity':value['model']='different-model'
                    else:value['raw']['choices'][0]['finish_reason']='length'
                    return value
            with self.subTest(kind=kind),self.assertRaises((TimeoutError,RuntimeError)):
                await capture.wrap(Bad('comparison_identity')).complete([], {})
            self.assertEqual(capture.ledger['calls'],1);self.assertGreater(capture.ledger['charged_tokens'],0)
            self.assertEqual(capture.ledger['reserved_tokens'],0)

    async def test_deadline_and_implementation_drift_deny_before_actual_call(self):
        clock=[0.0];capture=ComparisonCapture(self.root,self.capture().limits,{},clock=lambda:clock[0])
        clock[0]=99999
        with self.assertRaisesRegex(RuntimeError,'budget'):await capture.wrap(Provider()).complete([], {})
        self.assertEqual(capture.ledger['calls'],0)
        source=self.root/'implementation.py';source.write_text('original')
        capture=ComparisonCapture(self.root,self.capture().limits,{str(source):hashlib.sha256(source.read_bytes()).hexdigest()})
        source.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'source changed'):await capture.wrap(Provider()).complete([], {})
        self.assertEqual(capture.ledger['calls'],0)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.repo=fixtures.fixture(self.root)
        (self.repo/'post.py').write_text('from a import add\nfrom b import mul\nassert add(-3,2)==-1\nassert mul(-3,2)==-6\n')
        fixtures.git(self.repo,'add','.');fixtures.git(self.repo,'commit','-m','post checks')
        self.patch=patch.object(CodingWorkflowService,'_run_command',side_effect=native);self.patch.start();self.addCleanup(self.patch.stop)

    def case(self):
        return dict(id='arithmetic',repo=str(self.repo),objective='Fix arithmetic',paths=['a.py','b.py'],
            test_commands=[[sys.executable,'-B','check.py']],post_commands=[[sys.executable,'-B','post.py']],
            requirements=[dict(id='addition',statement='Correct addition',paths=['a.py'],test_indexes=[0]),
                dict(id='multiplication',statement='Correct multiplication',paths=['b.py'],test_indexes=[0])])

    def model(self,runner,**kwargs):
        factory=lambda role:Provider(role,**kwargs)
        return dict(id='fixture',factory=factory,fingerprint=runner.svc.provider_signature(factory('comparison_identity')))

    async def test_same_frozen_case_caps_replay_and_no_model_commands(self):
        runner=CodingComparisonService(self.root/'paired');case=self.case()
        before=runner.svc.source_stamp(self.repo,case['paths'])
        report=await runner.run([case],[self.model(runner)],confirmed=True)
        self.assertTrue(report['complete']);self.assertTrue(report['protocol_valid']);self.assertTrue(report['all_tasks_resolved'],report)
        self.assertFalse(report['model_comparison_available']);self.assertEqual(len(report['arms']),2)
        single,multi=report['arms'];self.assertEqual(single['case_digest'],multi['case_digest'])
        self.assertEqual(single['limits'],multi['limits']);self.assertEqual(single['ledger']['calls'],1)
        self.assertEqual(multi['ledger']['calls'],4)
        for arm in report['arms']:
            self.assertEqual([t['command'] for t in arm['validation']['tests']],case['test_commands']+case['post_commands'])
            self.assertTrue(all(r['passed'] for r in arm['validation']['requirements']))
        self.assertFalse(list((self.root/'paired').rglob('MODEL_COMMAND_EXECUTED')))
        self.assertEqual(runner.svc.source_stamp(self.repo,case['paths']),before)

    async def test_failed_arm_is_retained_in_denominator_not_replaced_by_good_arm(self):
        runner=CodingComparisonService(self.root/'negative')
        report=await runner.run([self.case()],[self.model(runner,wrong=True)],confirmed=True,limits={'max_attempts':1})
        self.assertTrue(report['protocol_valid']);self.assertFalse(report['all_tasks_resolved'])
        self.assertEqual([(g['n'],g['accepted']) for g in report['groups']],[(1,0),(1,1)])
        self.assertEqual(report['arms'][0]['mode_status'],'failed');self.assertFalse(report['arms'][0]['task_tests_passed'])
        self.assertFalse(list((self.root/'negative').rglob('MODEL_COMMAND_EXECUTED')))

    async def test_input_mutation_cannot_weaken_commands_and_plan_tamper_stops_next_arm(self):
        case=self.case();runner=CodingComparisonService(self.root/'tamper')
        def hook(messages):
            case['objective']='caller later mutation';case['test_commands']=[[sys.executable,'-c','pass']]
            path=runner.root/'plan.json';data=json.loads(path.read_text());data['limits']['max_tokens']=99999;path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'plan changed'):
            await runner.run([case],[self.model(runner,hook=hook)],confirmed=True)
        row=json.loads(next(runner.root.glob('arm-*/report.json')).read_text())
        self.assertEqual(row['validation']['tests'][0]['command'],[sys.executable,'-B','check.py'])
        self.assertFalse((runner.root/'report.json').exists())

    async def test_single_format_repair_charged_and_frozen_commands_win(self):
        calls=[];budget=ExecutionBudget(max_model_calls=2,max_tokens=10000)
        class Formatting(Provider):
            async def complete(_,messages,options):
                calls.append(messages)
                return dict(ok=True,content='{"changes":[' if len(calls)==1 else json.dumps(proposal()),usage={'total_tokens':73},
                    raw={'choices':[{'finish_reason':'stop'}]})
        service=AutonomousCodingService(Formatting(),workflow=CodingWorkflowService(artifact_root=self.root/'proposal'))
        result=await service.propose(self.repo,'Fix arithmetic',focus_paths=['a.py','b.py'],budget=budget,
            test_commands=self.case()['test_commands'],requirements=self.case()['requirements'])
        self.assertEqual(budget.model_calls,2);self.assertEqual(budget.tokens,146)
        self.assertEqual(result['effective_test_commands'],self.case()['test_commands'])
        self.assertEqual([r['status'] for r in result['format_attempts']],['rejected','parsed'])
        self.assertEqual((self.repo/'a.py').read_text(),'def add(a, b):\n    return a - b\n')

    async def test_exact_anchor_rejection_is_bounded_charged_and_never_writes(self):
        for recovered in (True, False):
            calls=[]; budget=ExecutionBudget(max_model_calls=2,max_tokens=10000)
            before={path:(self.repo/path).read_bytes() for path in ('a.py','b.py')}
            class Anchors(Provider):
                async def complete(_,messages,options):
                    calls.append(copy.deepcopy(messages))
                    self.assertEqual({path:(self.repo/path).read_bytes() for path in before},before)
                    value=proposal()
                    if len(calls)==1 or not recovered:
                        value['changes'][0]['old_text']='return a-b'
                    return dict(ok=True,content=json.dumps(value),usage={'total_tokens':73},
                        raw={'choices':[{'finish_reason':'stop'}]})
            workflow=CodingWorkflowService(artifact_root=self.root/('anchors-'+str(recovered)))
            service=AutonomousCodingService(Anchors(),workflow=workflow)
            with patch.object(workflow,'execute') as execute:
                if recovered:
                    result=await service.propose(self.repo,'Fix arithmetic',focus_paths=['a.py','b.py'],budget=budget,
                        test_commands=self.case()['test_commands'],requirements=self.case()['requirements'])
                    self.assertEqual(result['effective_test_commands'],self.case()['test_commands'])
                    self.assertEqual([r['status'] for r in result['format_attempts']],['rejected','parsed'])
                    self.assertFalse(result['writes_performed'])
                else:
                    with self.assertRaisesRegex(ValueError,'bounded format repair'):
                        await service.propose(self.repo,'Fix arithmetic',focus_paths=['a.py','b.py'],budget=budget,
                            test_commands=self.case()['test_commands'],requirements=self.case()['requirements'])
                execute.assert_not_called()
            self.assertEqual(budget.model_calls,2); self.assertEqual(budget.tokens,146)
            self.assertIn('old_text must match exactly once',calls[1][-1]['content'])
            self.assertEqual({path:(self.repo/path).read_bytes() for path in before},before)

    def test_context_presentation_roundtrip_byte_integrity_and_grounded_diagnosis(self):
        text='def add(a, b):\n'+''.join(f'    # Evidence detail {i} '+ 'abcd '*14+'\n' for i in range(30))+'    return a - b\n'
        (self.repo/'a.py').write_text(text)
        from services.coding_context_service import CodingContextService
        view=CodingContextService().build_execution(self.repo,'Fix add',write_paths=['a.py'])
        presented=View.present(view,{'a.py':text})
        self.assertEqual(presented['schema'],'clawos.coding-context-presentation.v1')
        self.assertLess(len(json.dumps(presented)),len(json.dumps(view)))
        self.assertEqual(View.restore_presentation(presented,{'a.py':text}),view)
        with self.assertRaisesRegex(ValueError,'source text'):View.restore_presentation(presented,{'a.py':text+'tamper'})
        frames=[dict(path='check.py',symbol='test_mul',called_symbols=['mul'])]
        self.assertEqual(CodingContracts.diagnosis_targets(self.repo,frames,['a.py','b.py']),[dict(path='b.py',symbol='mul')])
        actual=View.failure_context(self.repo,[native(self.repo,[sys.executable,'-B','check.py'],30)])
        # This fixture still fails addition first; only that failing expression
        # is grounded, even though the displayed module also calls mul later.
        self.assertEqual(CodingContracts.diagnosis_targets(self.repo,actual,['a.py','b.py']),[dict(path='a.py',symbol='add')])

    async def test_unrelated_diagnosis_target_is_rejected_before_repair(self):
        roles=[]
        def handler(role,packet):
            roles.append(role)
            if role=='b':
                value=fixtures.answer('b');value['changes'][0]['new_text']='return a - b';return value
            if role=='diagnostician':
                self.assertEqual(packet['grounded_targets'],[dict(path='b.py',symbol='mul')])
                return dict(hypothesis='product broken',targets=[dict(path='a.py',symbol='add'),dict(path='b.py',symbol='mul')],
                    expected_test_effect='product assertion passes')
            return fixtures.answer(role)
        svc=ReliableCollaborationService(lambda spec:fixtures.Provider(spec.role_id,handler),root=self.root/'diagnosis')
        case=self.case()
        result=await svc.run(self.repo,case['objective'],allowed_paths=case['paths'],test_commands=case['test_commands'],
            requirements=case['requirements'],confirmed=True)
        self.assertEqual(result['status'],'test_failed');self.assertNotIn('repairer',roles)
        self.assertTrue(any(e['event']=='repair_diagnosis_rejected' for e in result['events']))

    async def test_counterbalanced_repeats_are_one_task_and_completed_report_tamper_is_rejected(self):
        runner=CodingComparisonService(self.root/'repeats')
        report=await runner.run([self.case()],[self.model(runner)],confirmed=True,repetitions=2)
        self.assertEqual([(r['mode'],r['repetition']) for r in report['arms']],
            [('single',1),('multi',1),('multi',2),('single',2)])
        self.assertEqual(report['unique_task_groups'],1)
        self.assertEqual([(g['n'],g['unique_tasks']) for g in report['groups']],[(2,1),(2,1)])
        row=report['arms'][0];path=runner.root/row['artifact'];value=json.loads(path.read_text());value['accepted']=False
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'report changed'):runner.verify_arm(row)

    def test_dirty_source_aliases_and_mechanical_rule_are_rejected(self):
        runner=CodingComparisonService(self.root/'invalid');case=self.case()
        alias=copy.deepcopy(case);alias['paths']=['a.py','A.py']
        with self.assertRaises(ValueError):runner.case(alias)
        case['requirements'][0]['rule']=dict(kind='python_exact_type',function='add',parameter='a',builtin_type='int')
        with self.assertRaisesRegex(ValueError,'mechanical'):runner.case(case)
        (self.repo/'a.py').write_text('modified')
        with self.assertRaisesRegex(ValueError,'clean'):runner.case(self.case())

    def test_digest_file_near_windows_path_limit_is_written_atomically(self):
        from services.file_transactions import write_text
        parent=self.root/('d'*60)/('e'*60)
        # Target fits MAX_PATH; the former target-derived temp name did not.
        target=parent/('f'*(250-len(str(parent))-1))
        self.assertEqual(len(str(target)),250)
        first=write_text(target,'原始证据',create_only=True)
        write_text(target,'更新证据',expected_sha256=first['sha256'])
        self.assertEqual(target.read_text(encoding='utf-8'),'更新证据')
        self.assertEqual(list(parent.glob('.claw-*.tmp')),[])

    async def test_zero_call_infrastructure_failure_cannot_claim_comparable_execution(self):
        runner=CodingComparisonService(self.root/'no-call')
        async def stopped(*args,**kwargs):
            return dict(status='failed',events=[dict(event='coordinator_failed',error='owned infrastructure failure')])
        with patch.object(ReliableCollaborationService,'run',side_effect=stopped):
            report=await runner.run([self.case()],[self.model(runner)],confirmed=True)
        self.assertTrue(report['complete']);self.assertTrue(report['protocol_valid'])
        self.assertFalse(report['execution_comparable'])
        self.assertEqual(report['arms'][1]['ledger']['calls'],0)
        self.assertFalse(report['arms'][1]['model_execution_observed'])


if __name__=='__main__':unittest.main()
