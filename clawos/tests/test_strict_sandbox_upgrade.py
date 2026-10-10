import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE));sys.path.insert(0, str(BASE/'scripts'))
from services.appcontainer_process import GitControlSeal, safe_tree, validate_python_command
from services.windows_appcontainer_boundary import WindowsAppContainerBoundary
from services.coding_workflow_service import CodingWorkflowService
from services.coding_comparison_service import CodingComparisonService, CORE_FILES
from benchmarks.coding_taskbank_v1 import TASKS, SOURCE_REVISION
from run_coding_taskbank import seed, reference_source, public_only_source


class BoundaryGuards(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows file security control')
    def test_git_pointer_restored_after_successful_acl_mutation_and_exception(self):
        import ctypes as c
        with tempfile.TemporaryDirectory() as td:
            pointer = Path(td) / '.git'
            original = 'gitdir: synthetic-control\n'
            pointer.write_text(original, encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'synthetic launcher failure'):
                with GitControlSeal(pointer) as seal:
                    # Positive control: the DACL actually changes, unlike the
                    # guest probe whose mutation is rejected by Windows.
                    self.assertTrue(seal.dacl.value)
                    self.assertEqual(seal.advapi.SetSecurityInfo(
                        seal.handle, 1, 4 | 0x80000000, None, None, None, None), 0)
                    dacl, descriptor = c.c_void_p(), c.c_void_p()
                    try:
                        self.assertEqual(seal.advapi.GetSecurityInfo(
                            seal.handle, 1, 4, None, None, c.byref(dacl), None,
                            c.byref(descriptor)), 0)
                        self.assertFalse(dacl.value)
                    finally:
                        if descriptor: seal.kernel.LocalFree(descriptor)
                    with self.assertRaises(OSError): pointer.write_text('changed')
                    with self.assertRaises(OSError): pointer.rename(Path(td) / 'moved')
                    raise RuntimeError('synthetic launcher failure')
            self.assertEqual(pointer.read_text(encoding='utf-8'), original)
            # A second snapshot proves restoration and closure of the first
            # seal; the pointer remains usable after ordinary exception exit.
            with GitControlSeal(pointer) as restored:
                self.assertTrue(restored.dacl.value)
            pointer.write_text(original + 'restored', encoding='utf-8')

    def test_installed_profile_does_not_claim_acceptance(self):
        boundary=WindowsAppContainerBoundary()
        with patch.object(boundary,'available',return_value=True), patch.object(boundary,'_derive_sid',return_value=('test-sid',None)), patch.object(boundary,'_free_sid'),patch.object(boundary,'_profile_exists',return_value=True):
            result=boundary.status()
        self.assertTrue(result['installed']);self.assertFalse(result['production_ready'])
        self.assertFalse(result['direct_network_denied'])

    def test_hard_link_rejected_before_acl_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); outside=root/'outside';outside.write_text('secret-canary')
            workspace=root/'workspace';workspace.mkdir();os.link(outside,workspace/'link')
            boundary=WindowsAppContainerBoundary()
            with patch('services.windows_appcontainer_boundary.subprocess.run') as run:
                with self.assertRaises(ValueError):boundary.grant_workspace(workspace,confirmed=True)
                run.assert_not_called()
            self.assertEqual(outside.read_text(),'secret-canary')

    @unittest.skipUnless(os.name=='nt','Windows junction test')
    def test_junction_rejected_without_following_target(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);outside=root/'outside';outside.mkdir();workspace=root/'workspace';workspace.mkdir()
            link=workspace/'junction'
            subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],capture_output=True,check=True)
            try:
                with self.assertRaises(ValueError):safe_tree(workspace)
            finally:link.rmdir()
            self.assertTrue(outside.is_dir())

    def test_unsupported_commands_do_not_grant_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            boundary=WindowsAppContainerBoundary(runtime_dir=td)
            with patch.object(boundary,'grant_workspace') as grant:
                for cmd in (['node','test.js'],['python','-I','test.py'],['python','bad\0arg'],[]):
                    with self.subTest(cmd=cmd),self.assertRaises(ValueError):
                        boundary.run_command(cmd,td,confirmed_acl=True)
                grant.assert_not_called()

    def test_workspace_runtime_overlap_rejected_before_acl(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);runtime=root/'runtime';runtime.mkdir()
            boundary=WindowsAppContainerBoundary(runtime_dir=runtime)
            with patch.object(boundary,'grant_workspace') as grant:
                with self.assertRaises(ValueError):boundary.run_command(['python','a.py'],root,confirmed_acl=True)
                grant.assert_not_called()

    def test_writable_git_database_rejected_before_acl(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);runtime=root/'runtime';runtime.mkdir();workspace=root/'workspace';workspace.mkdir()
            (workspace/'.git').mkdir()
            boundary=WindowsAppContainerBoundary(runtime_dir=runtime)
            with patch.object(boundary,'grant_workspace') as grant, patch.object(boundary,'install') as install:
                with self.assertRaises(ValueError):boundary.run_command(['python','test.py'],workspace,confirmed_acl=True)
                grant.assert_not_called();install.assert_not_called()

    def test_confirmation_gate_and_missing_private_runtime(self):
        boundary=WindowsAppContainerBoundary()
        with self.assertRaises(PermissionError):boundary.run_command(['python'],'.')
        with self.assertRaises(PermissionError):boundary.grant_runtime()
        with patch.dict(os.environ,{},clear=True):
            other=WindowsAppContainerBoundary()
            with self.assertRaises(ValueError):other.run_command(['python'],'.',confirmed_acl=True)

    @unittest.skipUnless(os.name=='nt','Windows workflow')
    def test_installed_profile_without_private_runtime_fails_closed(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);workspace=root/'repo';workspace.mkdir()
            (root/'workspace.json').write_text(json.dumps(dict(schema='clawos.task-workspace.v1',workspace=str(workspace),isolated=True)))
            with patch.dict(os.environ,{'CLAWOS_REQUIRE_OS_SANDBOX':'1','CLAWOS_APPCONTAINER_RUNTIME':''}), patch.object(WindowsAppContainerBoundary,'status',return_value={'installed':True}), patch('services.coding_workflow_service.WindowsJobSandbox.run') as fallback:
                result=CodingWorkflowService._run_command(workspace,['python','test.py'],1)
            self.assertEqual(result['exit_code'],126)
            self.assertIn('private copied Python runtime',result['stderr'])
            self.assertTrue(result['sandbox']['downgrade_blocked'])
            fallback.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows workflow')
    def test_child_report_cannot_assert_strict_boundary(self):
        import json
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);workspace=root/'repo';workspace.mkdir()
            (root/'workspace.json').write_text(json.dumps(dict(schema='clawos.task-workspace.v1',workspace=str(workspace),isolated=True)))
            fake=dict(exit_code=0,sandbox=dict(os_enforced=True,production_sandbox_ready=True))
            with patch.dict(os.environ,{'CLAWOS_REQUIRE_OS_SANDBOX':'1'}),patch.object(WindowsAppContainerBoundary,'status',return_value={'installed':True}),patch.object(WindowsAppContainerBoundary,'run_command',return_value=fake),patch('services.coding_workflow_service.WindowsJobSandbox.run') as fallback:
                result=CodingWorkflowService._run_command(workspace,['python','test.py'],1)
            self.assertEqual(result['exit_code'],126);self.assertTrue(result['sandbox']['downgrade_blocked'])
            fallback.assert_not_called()

    def test_native_launcher_is_bound_to_comparison_evidence(self):
        self.assertIn('appcontainer_process.py',CORE_FILES)
        self.assertIn('windows_appcontainer_boundary.py',CORE_FILES)
        self.assertIn('strict_sandbox_acceptance.py',CORE_FILES)


class TaskbankContracts(unittest.TestCase):
    def test_every_case_is_frozen_and_hidden_checks_absent_from_workspace(self):
        import ast
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); original=copy.deepcopy(TASKS)
            runner=CodingComparisonService(root/'comparison')
            digests=set()
            for task in TASKS:
                case,source,deps=seed(task,root/'seeds')
                frozen=runner.case(case);digests.add(frozen['task_group_digest'])
                ast.parse(reference_source(task,source));ast.parse(public_only_source(task,source))
                workspace=Path(case['repo'])
                self.assertFalse((workspace/'acceptance_holdout.py').exists())
                self.assertEqual((workspace/'acceptance_public.py').read_text(encoding='utf-8').count(task['public']),1)
                self.assertNotIn('reference_source', (workspace/case['paths'][0]).read_text(encoding='utf-8'))
            self.assertEqual(len(digests),6);self.assertEqual(TASKS,original)
            self.assertEqual(len(SOURCE_REVISION),40)


if __name__=='__main__':unittest.main()
