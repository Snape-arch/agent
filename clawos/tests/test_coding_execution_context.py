"""Shared evidence parity, scope, source drift and persisted context receipts."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.coding_context_service import CodingContextService
from services.coding_execution_context import CodingExecutionContext as View
from services.autonomous_coding_service import AutonomousCodingService
from services.agentic_coding_loop_service import AgenticCodingLoopService
from services.coding_trace_service import CodingTraceService
from services.reliable_collaboration import ReliableCollaborationService
from services.collaboration_delivery import CollaborationDelivery
from services.coding_workflow_service import CodingWorkflowService
import test_reliable_collaboration as fixtures


def command(repo, argv, timeout):
    proc = subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=timeout)
    return dict(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
                sandbox=dict(backend='native-fixture', production_sandbox_ready=False))


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name);self.repo = fixtures.fixture(self.folder)
        (self.repo/'pkg').mkdir()
        for rel, text in {'pkg/use.py':'from .helper import total\ndef result():\n    return total()\n',
                          'pkg/helper.py':'from .constants import VALUE\ndef total():\n    return VALUE\n',
                          'pkg/constants.py':'VALUE = 4\n', 'pkg/__init__.py':'',
                          'AGENTS.md':'Root instruction', 'pkg/AGENTS.md':'Scoped instruction',
                          '.env':'never send secret', 'credentials.json':'{"never":"send credential"}',
                          'sealed_holdout.py':'secret heldout assertion'}.items():
            (self.repo/rel).write_text(text, encoding='utf-8')
        fixtures.git(self.repo, 'add', '.');fixtures.git(self.repo, 'commit', '-m', 'context fixture')
        self.context = CodingContextService()

    def view(self, **kwargs):
        return self.context.build_execution(self.repo, 'repair result', write_paths=['pkg/use.py'], **kwargs)

    def test_package_dependencies_instructions_and_same_snapshot_parity(self):
        view = self.view()
        self.assertEqual(view['scope']['write_paths'], ['pkg/use.py'])
        self.assertIn('pkg/constants.py', view['scope']['read_only_paths'])
        self.assertEqual([r['path'] for r in view['instruction_hierarchy']], ['AGENTS.md','pkg/AGENTS.md'])
        other = self.folder/'clone';fixtures.git(self.folder, 'clone', '--local', str(self.repo), str(other))
        same = self.context.build_execution(other, 'repair result', focus_paths=['pkg/use.py'])
        self.assertEqual(view, same)
        self.assertNotIn('sealed_holdout', json.dumps(view))
        self.assertNotIn('never send secret', json.dumps(view))
        View.verify(other, same)

    def test_invalid_paths_links_and_oversize_explicit_sources_fail_before_read(self):
        for rel in ('../a.py', 'tools/a.py', '.env', 'credentials.json', 'NUL.py', 'a.py:stream', '/a.py', 'output/a.py'):
            with self.subTest(path=rel), self.assertRaises(ValueError):
                self.context.build_execution(self.repo, 'repair', write_paths=[rel])
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda p: p == self.repo/'pkg' or original(p)), self.assertRaises(ValueError):
            self.view()
        (self.repo/'pkg/use.py').write_text('x'*129000)
        with self.assertRaises(ValueError):self.view()

    def test_budget_is_structured_and_source_drift_or_packet_tamper_rejected(self):
        view = self.view(max_chars=4000)
        self.assertLessEqual(len(json.dumps(view, ensure_ascii=False, separators=(',', ':'))), 4000)
        altered = json.loads(json.dumps(view));altered['scope']['write_paths'].append('pkg/helper.py')
        with self.assertRaises(ValueError):View.verify_packet(altered)
        (self.repo/'pkg/constants.py').write_text('VALUE = 9\n')
        with self.assertRaisesRegex(ValueError, 'source drift'):View.verify(self.repo, view)
        new = self.view();self.assertNotEqual(new['source_fingerprint'], view['source_fingerprint'])

    def test_missing_write_file_and_explicit_read_dependency_have_distinct_access(self):
        view = self.context.build_execution(self.repo, 'create future', write_paths=['future.py'], read_only_paths=['a.py'])
        self.assertEqual(view['code_evidence'][0]['state'], 'missing')
        View.assert_changes(view, [dict(path='future.py')])
        with self.assertRaises(ValueError):View.assert_changes(view, [dict(path='a.py')])
        (self.repo/'future.py').write_text('pass')
        with self.assertRaises(ValueError):View.verify(self.repo, view)

    def test_real_failed_frame_is_shared_and_out_of_range_frames_are_not_evidence(self):
        proc = command(self.repo, [sys.executable, '-B', 'check.py'], 30)
        proc['command'] = [sys.executable, '-B', 'check.py']
        frames = View.failure_context(self.repo, [proc]);self.assertTrue(frames)
        self.assertEqual(frames[0]['source'], 'actual_failure_frame')
        view = self.context.build_execution(self.repo, 'fix add', write_paths=['a.py'], failure_context=frames)
        self.assertIn('check.py', view['scope']['read_only_paths'])
        bogus = dict(exit_code=1, stderr=f'File "{self.repo / "check.py"}", line 99999')
        self.assertEqual(View.failure_context(self.repo, [bogus]), [])

    def test_search_and_read_use_selected_source_view(self):
        view = self.view()
        service = AgenticCodingLoopService(None, trace=CodingTraceService(self.folder/'trace.json'))
        result = service._observe(self.repo, view, dict(action='search', query='secret', glob='*'))
        self.assertEqual(result['matches'], [])
        with self.assertRaises(ValueError):service._observe(self.repo, view, dict(action='read', path='sealed_holdout.py'))
        read = service._observe(self.repo, view, dict(action='read', path='pkg/helper.py', start_line=1, end_line=999999))
        self.assertIn('return VALUE', read['content'])

    def test_target_function_beats_earlier_class_and_dependency_excerpt_is_partially_retained(self):
        text='class MergeConflict(Exception):\n    pass\n' + '# padding\n'*90 + 'def merge_document():\n    return 42\n'
        (self.repo/'pkg/use.py').write_text(text)
        view=self.context.build_execution(self.repo,'merge_document preserving MergeConflict',write_paths=['pkg/use.py'])
        self.assertIn('def merge_document',view['code_evidence'][0]['content'])
        self.assertGreater(view['code_evidence'][0]['start_line'],80)
        (self.repo/'pkg/use.py').write_text('from .helper import total\ndef result():\n    return total()\n')
        (self.repo/'pkg/helper.py').write_text('from .constants import VALUE\ndef total():\n    return VALUE\n' + ('# '+'evidence '*15+'\n')*60)
        objective='repair result '+ 'x'*1400
        complete=self.context.build_execution(self.repo,objective,write_paths=['pkg/use.py'],max_chars=8000)
        complete_size=len(json.dumps(complete,ensure_ascii=False,separators=(',',':')))
        self.assertGreater(complete_size,4500)
        limit=complete_size-500
        view=self.context.build_execution(self.repo,objective,write_paths=['pkg/use.py'],max_chars=limit)
        helper=next(r for r in view['code_evidence'] if r['path']=='pkg/helper.py')
        self.assertGreater(len(helper['content']),0);self.assertLess(len(helper['content']),1600)
        self.assertLessEqual(len(json.dumps(view,ensure_ascii=False,separators=(',',':'))),limit)

    def test_long_failed_function_keeps_the_actual_assertion_window(self):
        (self.repo/'check.py').write_text('from a import add\ndef check():\n'+ '    # padding\n'*200 + '    assert add(3,2)==5\ncheck()\n')
        frames=View.failure_context(self.repo,[command(self.repo,[sys.executable,'-B','check.py'],30)])
        frame=next(f for f in frames if f['symbol']=='check')
        self.assertIn('assert add(3,2)',frame['snippet']);self.assertGreater(frame['start_line'],100)


class RuntimeContextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name);self.repo=fixtures.fixture(self.folder);self.root=self.folder/'runs'
        self.runner=patch.object(CodingWorkflowService,'_run_command',side_effect=command)
        self.runner.start();self.addCleanup(self.runner.stop)

    def kwargs(self):
        return dict(allowed_paths=['a.py','b.py'],test_commands=[[sys.executable,'-B','check.py']],confirmed=True)

    async def test_single_and_worker_receive_equal_shared_view_and_delivery_freezes_it(self):
        captured = {}
        def handler(role, packet):
            if role=='a':captured['worker']=packet['execution_context']
            return fixtures.answer(role)
        svc=ReliableCollaborationService(lambda spec:fixtures.Provider(spec.role_id,handler),root=self.root)
        result=await svc.run(self.repo,'Fix arithmetic',**self.kwargs())
        self.assertEqual(result['status'],'passed',result)
        class Single:
            async def complete(_,messages,options):
                text=messages[-1]['content'];captured['single']=json.loads(text.split('instructions]\n',1)[1])
                return dict(ok=True,content=json.dumps(dict(changes=[dict(path='a.py',operation='replace',old_text='return a - b',new_text='return a + b')],
                    test_commands=[[sys.executable,'-B','check.py']],explanation='fix add',confidence=.9)),usage={'total_tokens':10})
        proposal=await AutonomousCodingService(Single(),workflow=svc.workflow).propose(self.repo,'Fix arithmetic',focus_paths=['a.py'])
        self.assertEqual(captured['worker'],captured['single'])
        self.assertEqual(proposal['context_digest'],captured['worker']['context_digest'])
        packet=await CollaborationDelivery(svc).prepare(result['run_id'],confirmed=True)
        self.assertEqual(packet['manifest']['contexts'],result['contexts'])
        for event in result['events']:
            if event['event']=='model_receipt':self.assertIn(event['context_digest'],result['contexts'])
        record=next(iter(result['contexts'].values()));path=self.root/result['run_id']/record['artifact']
        body=json.loads(path.read_text());body['objective']='changed'
        path.write_text(json.dumps(body))
        with self.assertRaises(ValueError):CollaborationDelivery(svc).inspect(result['run_id'])
        path.unlink()
        with self.assertRaisesRegex(ValueError,'context artifact missing'):svc.verify_receipts(svc.load(result['run_id']))

    async def test_single_rejects_dependency_write_and_generation_time_source_drift(self):
        (self.repo/'a.py').write_text('import b\ndef add(a, b):\n    return a - b\n')
        for scenario in ('readonly','drift'):
            class Single:
                async def complete(_,messages,options):
                    if scenario=='drift':(self.repo/'b.py').write_text('def multiply(a,b):\n    return a*b+1\n')
                    return dict(ok=True,content=json.dumps(dict(changes=[dict(path='b.py' if scenario=='readonly' else 'a.py',operation='replace',old_text='return a - b',new_text='return a + b')],
                        test_commands=[[sys.executable,'check.py']],explanation='bad',confidence=.5)))
            with self.subTest(scenario=scenario),self.assertRaises(ValueError):
                await AutonomousCodingService(Single(),workflow=CodingWorkflowService(artifact_root=self.root)).propose(self.repo,'Fix arithmetic',focus_paths=['a.py'])
        self.assertIn('return a - b',(self.repo/'a.py').read_text())

    async def test_new_run_policy_drift_blocks_recovery_before_model_calls(self):
        svc=ReliableCollaborationService(lambda spec:fixtures.Provider(spec.role_id,lambda role,packet:dict(wrong=True)),root=self.root)
        result=await svc.run(self.repo,'Fix arithmetic',**self.kwargs())
        self.assertEqual(result['status'],'failed')
        import services.reliable_collaboration as module
        with patch.object(module,'LOADED_POLICY',dict(schema='different')),self.assertRaisesRegex(ValueError,'context policy'):
            await svc.run(self.repo,'Fix arithmetic',resume_run=result['run_id'],**self.kwargs())

    async def test_single_preserves_the_full_original_objective_beyond_context_excerpt(self):
        objective='Fix addition. '+ 'detail '*400 + 'UNIQUE_FINAL_CONSTRAINT'
        class Single:
            async def complete(_,messages,options):
                self.assertIn(objective,messages[-1]['content'])
                return dict(ok=True,content=json.dumps(dict(changes=[dict(path='a.py',operation='replace',old_text='return a - b',new_text='return a + b')],
                    test_commands=[[sys.executable,'check.py']],explanation='fix',confidence=.9)))
        result=await AutonomousCodingService(Single(),workflow=CodingWorkflowService(artifact_root=self.root)).propose(self.repo,objective,focus_paths=['a.py'])
        self.assertLessEqual(len(result['execution_context']['objective']),2000)
        self.assertTrue(result['original_objective_digest'])


if __name__=='__main__':unittest.main()
