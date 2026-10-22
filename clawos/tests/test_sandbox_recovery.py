import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from services import sandbox_recovery as recovery
from services.appcontainer_process import GitControlSeal, dacl_policy


class RecoveryGuards(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.workspace=self.root/'workspace';self.runtime=self.root/'runtime'
        self.workspace.mkdir();self.runtime.mkdir()
        self.command='a'*32;self.folder=self.root/'sandbox/commands'/self.command;self.folder.mkdir(parents=True)
        self.env=patch.dict(os.environ,{'CLAWOS_OUTPUT_DIR':str(self.root)})
        self.env.start();self.addCleanup(self.env.stop)
        self.request=dict(schema='clawos.sandbox-command.v2',command_profile='ClawOS.Exec.'+self.command,
                          workspace=str(self.workspace),runtime=str(self.runtime),owner_pid=100,owner_creation=10)
        (self.folder/'request.json').write_text(json.dumps(self.request),encoding='utf-8')
        info=self.workspace.stat();other=self.runtime.stat()
        self.state=dict(self.request,schema='clawos.sandbox-recovery.v1',profile=self.request['command_profile'],
                        request_digest=hashlib.sha256((self.folder/'request.json').read_bytes()).hexdigest(),
                        supervisor_pid=200,supervisor_creation=20,profile_absent_verified=True,job_assigned_at_creation=True,
                        workspace_identity=[info.st_dev,info.st_ino],runtime_identity=[other.st_dev,other.st_ino],git_control={'exists':False})
        self.write_state()

    def write_state(self):
        (self.folder/'state.json').write_text(json.dumps(self.state),encoding='utf-8')

    def test_intent_is_bound_to_request_and_fresh_profile(self):
        recovery.load_plan(self.folder)
        for key,value in [('request_digest','wrong'),('profile','ClawOS.Runtime.other'),('workspace_identity',[0,0]),('job_assigned_at_creation',False),('owner_creation',11)]:
            with self.subTest(key=key):
                old=self.state[key];self.state[key]=value;self.write_state()
                with self.assertRaises(ValueError):recovery.load_plan(self.folder)
                self.state[key]=old
        self.write_state()

    def test_legacy_or_missing_snapshots_stay_quarantined(self):
        self.state.pop('git_control');self.write_state()
        with self.assertRaisesRegex(ValueError,'snapshot'):recovery.load_plan(self.folder)
        (self.folder/'request.json').write_text(json.dumps(dict(self.request,schema='clawos.sandbox-command.v1')))
        with self.assertRaisesRegex(ValueError,'legacy'):recovery.load_plan(self.folder)

    def test_dead_identity_never_treats_access_denied_as_exit(self):
        with patch.object(recovery,'ProcessIdentity',side_effect=OSError(5,'denied')):
            with self.assertRaises(OSError):recovery.dead(1,1)
        for error in (OSError(87,'gone'),ValueError('PID reused')):
            with patch.object(recovery,'ProcessIdentity',side_effect=error):self.assertTrue(recovery.dead(1,1))
        for pid in (True,0,-1,'1'):
            with self.assertRaises(ValueError):recovery.dead(pid,1)

    def test_host_lock_cannot_live_inside_leased_workspace(self):
        from services.sandbox_supervisor import host_lock
        for path in (self.root,self.root/'sandbox/locks',self.root/'sandbox/locks/nested'):
            with self.assertRaisesRegex(ValueError,'outside'):host_lock(path/'.clawos-supervisor')

    def test_recovery_rejects_guest_runtime_overlapping_host_locks(self):
        locks=self.root/'sandbox/locks';locks.mkdir()
        self.request['runtime']=str(locks)
        (self.folder/'request.json').write_text(json.dumps(self.request),encoding='utf-8')
        info=locks.stat();self.state.update(runtime=str(locks),runtime_identity=[info.st_dev,info.st_ino],request_digest=hashlib.sha256((self.folder/'request.json').read_bytes()).hexdigest())
        self.write_state()
        with self.assertRaisesRegex(ValueError,'locks overlap'):recovery.load_plan(self.folder)

    @unittest.skipUnless(os.name=='nt','Windows recovery')
    def test_live_owner_or_child_cannot_trigger_mutation(self):
        for key in ('owner','supervisor','child'):
            self.state.update(child_pid=300,child_creation=30);self.write_state()
            pid=self.state[key+'_pid']
            with patch.object(recovery,'dead',side_effect=lambda candidate,creation:candidate!=pid),patch.object(recovery.subprocess,'run') as mutate:
                with self.assertRaisesRegex(RuntimeError,'alive'):recovery.recover_command(self.command,confirmed=True)
                mutate.assert_not_called()
                self.assertFalse((self.folder/'result.json').exists())

    @unittest.skipUnless(os.name=='nt','Windows recovery')
    def test_cleanup_failure_stays_unknown_and_retry_is_idempotent(self):
        from services.windows_appcontainer_boundary import WindowsAppContainerBoundary
        boundary=MagicMock();boundary.status.return_value={'installed':False,'sid':'S-1-15-2-123'}
        with patch.object(recovery,'dead',return_value=True),patch('services.windows_appcontainer_boundary.WindowsAppContainerBoundary',return_value=boundary),patch.object(recovery.subprocess,'run',return_value=MagicMock(returncode=1)):
            with self.assertRaisesRegex(RuntimeError,'revocation'):recovery.recover_command(self.command,confirmed=True)
        self.assertFalse((self.folder/'result.json').exists())
        with patch.object(recovery,'dead',return_value=True),patch('services.windows_appcontainer_boundary.WindowsAppContainerBoundary',return_value=boundary),patch.object(recovery.subprocess,'run',return_value=MagicMock(returncode=0)) as mutate:
            self.assertTrue(recovery.recover_command(self.command,confirmed=True)['cleanup_verified'])
            self.assertTrue(recovery.recover_command(self.command,confirmed=True)['already_clean'])
            self.assertEqual(mutate.call_count,2)
        receipt=json.loads((self.folder/'result.json').read_text())
        self.assertFalse(receipt['execution_replayed']);self.assertNotIn('result',receipt)

    @unittest.skipUnless(os.name=='nt','Native DACL snapshot')
    def test_git_pointer_changed_bytes_refuses_saved_dacl_restore(self):
        pointer=self.workspace/'.git';pointer.write_text('gitdir: owned')
        with GitControlSeal(pointer) as sealed:saved=sealed.snapshot(pointer)
        GitControlSeal.restore_snapshot(pointer,saved)
        with GitControlSeal(pointer) as sealed:
            self.assertEqual(dacl_policy(saved['sddl']),dacl_policy(sealed.snapshot(pointer)['sddl']))
        pointer.write_text('gitdir: changed')
        with self.assertRaisesRegex(ValueError,'identity or bytes'):GitControlSeal.restore_snapshot(pointer,saved)

    def test_startup_does_not_release_invalid_intent(self):
        self.state['request_digest']='wrong';self.write_state()
        result=recovery.recover_pending()
        self.assertEqual(len(result['blocked']),1);self.assertEqual(result['recovered'],[])
        self.assertFalse((self.folder/'result.json').exists())

    def test_native_probe_selects_exact_caller_not_an_old_replay(self):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/'scripts/probe_sandbox_restart.py'
        spec=importlib.util.spec_from_file_location('restart_probe',path);probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
        self.state.update(child_pid=301,cleaned=True);self.write_state()
        other=self.folder.parent/('b'*32);other.mkdir();(other/'request.json').write_text('{}')
        (other/'state.json').write_text(json.dumps(dict(self.state,owner_pid=900,cleaned=False)))
        found=probe.find_command(self.folder.parent,900,self.workspace)
        self.assertEqual(found[0],other/'request.json')
        self.assertIsNone(probe.find_command(self.folder.parent,901,self.workspace))

    @unittest.skipUnless(os.name=='nt','Native Git pointer guard')
    def test_changed_git_pointer_is_rejected_before_grant_cleanup(self):
        pointer=self.workspace/'.git';pointer.write_text('gitdir: original')
        with GitControlSeal(pointer) as sealed:self.state['git_control']=sealed.snapshot(pointer)
        self.write_state();pointer.write_text('gitdir: substituted')
        boundary=MagicMock();boundary.status.return_value={'installed':True,'sid':'S-1-15-2-123'}
        with patch.object(recovery,'dead',return_value=True),patch('services.windows_appcontainer_boundary.WindowsAppContainerBoundary',return_value=boundary),patch.object(recovery.subprocess,'run') as mutate:
            with self.assertRaisesRegex(ValueError,'pointer changed'):recovery.recover_command(self.command,confirmed=True)
            mutate.assert_not_called();boundary.uninstall.assert_not_called()
        self.assertFalse((self.folder/'result.json').exists())
