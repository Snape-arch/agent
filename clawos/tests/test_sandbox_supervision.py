import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.sandbox_runtime import SandboxRuntime, runtime_files
from services.sandbox_supervisor import ProcessIdentity, run_supervised, unresolved
from services.coding_workflow_service import CodingWorkflowService
from services.windows_appcontainer_boundary import WindowsAppContainerBoundary


class RuntimeIntegrity(unittest.TestCase):
    def deployment(self,root):
        runtime=root/'runtime-test';runtime.mkdir();(runtime/'python.exe').write_bytes(b'trusted-test-runtime')
        data=dict(schema='clawos.private-runtime.v1',directory=runtime.name,profile='ClawOS.Runtime.test',
                  sid='test-owned-sid',files=runtime_files(runtime))
        (root/'deployment.json').write_text(json.dumps(data))
        return SandboxRuntime(root),runtime

    def test_modified_missing_or_added_runtime_files_refuse_activation(self):
        for mutation in ('modified','missing','added'):
            with tempfile.TemporaryDirectory() as td:
                manager,runtime=self.deployment(Path(td))
                with patch.object(WindowsAppContainerBoundary,'status',return_value=dict(installed=True,sid='test-owned-sid')):
                    self.assertIsNotNone(manager.resolve())
                    if mutation=='modified':(runtime/'python.exe').write_bytes(b'changed')
                    elif mutation=='missing':(runtime/'python.exe').unlink()
                    else:(runtime/'extra.dll').write_bytes(b'extra')
                    self.assertFalse(manager.status()['configured'])
                    with self.assertRaisesRegex(ValueError,'integrity'):manager.resolve()

    def test_profile_identity_and_escaped_manifest_refuse_activation(self):
        with tempfile.TemporaryDirectory() as td:
            manager,runtime=self.deployment(Path(td))
            with patch.object(WindowsAppContainerBoundary,'status',return_value=dict(installed=True,sid='other')):
                with self.assertRaisesRegex(ValueError,'changed'):manager.resolve()
            value=json.loads(manager.config.read_text());value['directory']='../outside'
            manager.config.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'escaped'):manager.resolve()

    def test_setup_requires_explicit_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(PermissionError):SandboxRuntime(Path(td)/'absent').prepare()
            self.assertFalse((Path(td)/'absent').exists())

    def test_interrupted_setup_and_invalid_manifest_cannot_activate(self):
        with tempfile.TemporaryDirectory() as td:
            manager,runtime=self.deployment(Path(td))
            pending=Path(td)/'setup-state.json'
            pending.write_text(json.dumps(dict(phase='activating',cleanup_verified=False)))
            with self.assertRaisesRegex(ValueError,'interrupted'):manager.resolve()
            pending.write_text(json.dumps(dict(phase='complete',cleanup_verified=True)))
            manager.config.write_text(json.dumps(dict(schema='clawos.private-runtime.v1')))
            with self.assertRaisesRegex(ValueError,'fields'):manager.resolve()

    @unittest.skipUnless(os.name=='nt','Windows workflow')
    def test_default_workflow_uses_owned_deployment_without_environment(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);workspace=root/'repo';workspace.mkdir()
            (root/'workspace.json').write_text(json.dumps(dict(schema='clawos.task-workspace.v1',workspace=str(workspace),isolated=True)))
            boundary=WindowsAppContainerBoundary('ClawOS.Runtime.test',runtime_dir=root/'runtime')
            result=dict(exit_code=0,sandbox=dict(strict_boundary_verified=True,direct_socket_non_bypass_enforced=True))
            with patch.dict(os.environ,{'CLAWOS_APPCONTAINER_PROFILE':'','CLAWOS_APPCONTAINER_RUNTIME':''}),patch.object(SandboxRuntime,'resolve',return_value=boundary),patch.object(boundary,'status',return_value=dict(installed=True)),patch.object(boundary,'run_command',return_value=result) as run,patch('services.coding_workflow_service.WindowsJobSandbox.run') as fallback:
                actual=CodingWorkflowService._run_command(workspace,['python','a.py'],10)
            self.assertEqual(actual['exit_code'],0);run.assert_called_once();fallback.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows workflow')
    def test_corrupt_deployment_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);workspace=root/'repo';workspace.mkdir()
            (root/'workspace.json').write_text(json.dumps(dict(schema='clawos.task-workspace.v1',workspace=str(workspace),isolated=True)))
            with patch.dict(os.environ,{'CLAWOS_APPCONTAINER_PROFILE':'','CLAWOS_APPCONTAINER_RUNTIME':''}),patch.object(SandboxRuntime,'resolve',side_effect=ValueError('private runtime integrity changed')),patch('services.coding_workflow_service.WindowsJobSandbox.run') as fallback:
                actual=CodingWorkflowService._run_command(workspace,['python','a.py'],10)
            self.assertEqual(actual['exit_code'],126);fallback.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows strict gate')
    def test_strict_mode_never_accepts_legacy_host_downgrade(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);workspace=root/'repo';workspace.mkdir()
            (root/'workspace.json').write_text(json.dumps(dict(schema='clawos.task-workspace.v1',workspace=str(workspace),isolated=True)))
            with patch.dict(os.environ,{'CLAWOS_REQUIRE_OS_SANDBOX':'1'}), \
                 patch.object(WindowsAppContainerBoundary,'status',return_value=dict(installed=False)), \
                 patch('services.coding_workflow_service.WindowsJobSandbox.run') as job, \
                 patch('services.coding_workflow_service.WindowsRestrictedTokenSandbox.run_command') as legacy:
                result=CodingWorkflowService._run_command(workspace,['python','a.py'],10)
            self.assertEqual(result['exit_code'],126)
            self.assertTrue(result['sandbox']['launch_failed_closed'])
            job.assert_not_called();legacy.assert_not_called()


class SupervisorOwnership(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Native process handles')
    def test_creation_identity_mismatch_is_rejected(self):
        identity=ProcessIdentity(os.getpid())
        try:
            self.assertFalse(identity.exited())
            with self.assertRaisesRegex(ValueError,'identity'):ProcessIdentity(os.getpid(),identity.creation+1)
        finally:identity.close()

    def test_unknown_cleanup_receipt_blocks_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);workspace=root/'guest';workspace.mkdir();control=root/'host';control.mkdir()
            folder=control/'owned-command';folder.mkdir()
            (folder/'request.json').write_text(json.dumps(dict(workspace=str(workspace))))
            for result in (None,dict(cleanup_verified=False,error='failed cleanup')):
                if result is not None:(folder/'result.json').write_text(json.dumps(result))
                with self.assertRaisesRegex(RuntimeError,'quarantine'):unresolved(control,workspace)
            (folder/'result.json').write_text(json.dumps(dict(cleanup_verified=True,request_digest='wrong')))
            with self.assertRaisesRegex(RuntimeError,'quarantine'):unresolved(control,workspace)
            digest=hashlib.sha256((folder/'request.json').read_bytes()).hexdigest()
            (folder/'result.json').write_text(json.dumps(dict(cleanup_verified=True,request_digest=digest)))
            unresolved(control,workspace)
            (folder/'result.json').write_text('{broken')
            with self.assertRaisesRegex(RuntimeError,'invalid supervisor'):unresolved(control,workspace)


if __name__=='__main__':unittest.main()
