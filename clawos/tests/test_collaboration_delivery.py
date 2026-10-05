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
from services.collaboration_delivery import CollaborationDelivery
from services.reliable_collaboration import ReliableCollaborationService
from services.coding_workflow_service import CodingWorkflowService
from services.file_transactions import _file_lock
from test_reliable_collaboration import Provider, fixture, git, answer


def native_test(repo, command, timeout):
    result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=timeout)
    return dict(command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                sandbox={'backend':'native-fixture', 'production_sandbox_ready':False})


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.repo = fixture(self.folder)
        self.root = self.folder / 'runs'
        self.calls = []
        self.service = ReliableCollaborationService(lambda spec: Provider(spec.role_id, calls=self.calls), root=self.root)
        self.delivery = CollaborationDelivery(self.service)
        self.runner = patch.object(CodingWorkflowService, '_run_command', side_effect=native_test)
        self.runner.start()
        self.addCleanup(self.runner.stop)

    async def run_pass(self):
        result = await self.service.run(self.repo, 'Fix arithmetic', allowed_paths=['a.py','b.py'],
            test_commands=[[sys.executable,'check.py']], confirmed=True, actor='owner')
        self.assertEqual(result['status'], 'passed', result)
        return result['run_id']

    async def test_replay_packet_digest_confirmation_and_no_source_or_model_changes(self):
        run_id = await self.run_pass()
        calls = list(self.calls)
        source = self.service.source_stamp(self.repo, ['a.py','b.py'])
        with self.assertRaises(PermissionError):
            await self.delivery.prepare(run_id)
        packet = await self.delivery.prepare(run_id, confirmed=True)
        self.assertEqual(packet['status'], 'ready')
        self.assertEqual(packet['manifest']['changed_paths'], ['a.py','b.py'])
        self.assertEqual(packet['manifest']['tests'][0]['exit_code'], 0)
        self.assertEqual((await self.delivery.prepare(run_id, confirmed=True))['delivery_id'], packet['delivery_id'])
        for actor, digest, confirmed, error in [('other',packet['manifest_digest'],True,PermissionError),
                ('owner','wrong',True,ValueError),('owner',packet['manifest_digest'],False,PermissionError)]:
            with self.assertRaises(error):
                self.delivery.approve(run_id, actor=actor, manifest_digest=digest, confirmed=confirmed)
        approved = self.delivery.approve(run_id, actor='owner', manifest_digest=packet['manifest_digest'], confirmed=True)
        self.assertEqual(approved['status'], 'approved')
        self.assertFalse(approved['human_release_required'])
        self.assertTrue(approved['source_application_required'])
        self.assertEqual(self.delivery.inspect(run_id)['approval'], approved['approval'])
        self.assertEqual(self.delivery.approve(run_id, actor='owner', manifest_digest=packet['manifest_digest'], confirmed=True), approved)
        self.assertEqual(source, self.service.source_stamp(self.repo, ['a.py','b.py']))
        self.assertEqual(calls, self.calls)

    async def test_task_records_follow_ready_and_approved_packet(self):
        from memoryos.memory_store import MemoryStore
        self.service.store=MemoryStore(self.folder/'records.db')
        run_id=await self.run_pass()
        self.assertIsNone(self.service.store.get_run_record(run_id)['outputs']['collaboration']['delivery'])
        packet=await self.delivery.prepare(run_id,confirmed=True)
        self.assertEqual(self.service.store.get_run_record(run_id)['outputs']['collaboration']['delivery']['status'],'ready')
        self.delivery.approve(run_id,actor='owner',manifest_digest=packet['manifest_digest'],confirmed=True)
        self.assertEqual(self.service.store.get_run_record(run_id)['outputs']['collaboration']['delivery']['status'],'approved')
        self.assertEqual(len(self.service.store.list_run_records(run_type='autonomous_subagents')),1)

    async def test_dirty_caller_baseline_preserved_and_excluded_from_task_patch(self):
        (self.repo/'a.py').write_text('def add(a, b):\n    # caller draft\n    return a - b\n')
        git(self.repo, 'add', 'a.py')
        (self.repo/'draft.txt').write_text('caller untracked draft')
        source = self.service.source_stamp(self.repo, ['a.py','b.py'])
        run_id = await self.run_pass()
        packet = await self.delivery.prepare(run_id, confirmed=True)
        self.assertTrue(packet['manifest']['includes_caller_dirty_baseline'])
        diff = self.delivery.inspect(run_id)['diff']
        self.assertNotIn('diff --git a/draft.txt', diff)
        self.assertNotIn('+# caller draft', diff)
        self.assertEqual(source, self.service.source_stamp(self.repo, ['a.py','b.py']))

    async def test_failed_fresh_tests_retained_and_replay_attempts_bounded(self):
        run_id = await self.run_pass()
        with patch.object(CodingWorkflowService, '_run_command', return_value=dict(exit_code=1, stdout='', stderr='fresh failure')):
            for _ in range(3):
                with self.assertRaisesRegex(ValueError, 'fresh delivery tests failed'):
                    await self.delivery.prepare(run_id, confirmed=True)
            with self.assertRaisesRegex(ValueError, 'attempt budget'):
                await self.delivery.prepare(run_id, confirmed=True)
        state = self.service.load(run_id)
        self.assertEqual(state['status'], 'passed')
        self.assertEqual(len(state['delivery_attempts']), 3)
        self.assertTrue(all(a['status']=='failed' and a['tests'][0]['exit_code']==1 for a in state['delivery_attempts']))
        with self.assertRaises(ValueError):
            self.delivery.inspect(run_id)

    async def test_new_file_patch_replays_and_failed_delivery_can_retry(self):
        def handler(role, packet):
            if role=='planner':
                result=answer(role)
                result['nodes'].append(dict(id='helper',objective='create helper',write_paths=['helper.py'],depends_on=[]))
                return result
            if role=='helper':
                return dict(summary='helper',changes=[dict(path='helper.py',operation='create',content='VALUE = 42\n')])
            return answer(role)
        self.service.factory=lambda spec:Provider(spec.role_id,handler)
        result=await self.service.run(self.repo,'Fix and add helper',allowed_paths=['a.py','b.py','helper.py'],
            test_commands=[[sys.executable,'check.py']],confirmed=True,actor='owner')
        self.assertEqual(result['status'],'passed')
        run_id=result['run_id']
        with patch.object(CodingWorkflowService,'_run_command',return_value=dict(exit_code=1,stdout='',stderr='temporary failure')):
            with self.assertRaises(ValueError):await self.delivery.prepare(run_id,confirmed=True)
        packet=await self.delivery.prepare(run_id,confirmed=True)
        replay=Path(packet['manifest']['replay']['workspace']['workspace'])
        self.assertEqual((replay/'helper.py').read_text(),'VALUE = 42\n')
        self.assertEqual([a['status'] for a in self.service.load(run_id)['delivery_attempts']],['failed','ready'])
        self.assertFalse((self.repo/'helper.py').exists())

    async def test_approval_receipt_survives_checkpoint_write_interruption(self):
        import services.collaboration_delivery as module
        run_id=await self.run_pass()
        packet=await self.delivery.prepare(run_id,confirmed=True)
        original=module.write_text
        def crash_after_receipt(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if Path(path).name=='approval.json':raise SystemExit('simulated receipt/checkpoint interval')
            return result
        with patch.object(module,'write_text',side_effect=crash_after_receipt):
            with self.assertRaises(SystemExit):
                self.delivery.approve(run_id,actor='owner',manifest_digest=packet['manifest_digest'],confirmed=True)
        path=Path(packet['manifest_path']).parent/'approval.json'
        captured=path.read_bytes()
        self.assertEqual(self.service.load(run_id)['delivery']['status'],'ready')
        approved=self.delivery.approve(run_id,actor='owner',manifest_digest=packet['manifest_digest'],confirmed=True)
        self.assertEqual(path.read_bytes(),captured)
        self.assertEqual(approved['status'],'approved')

    async def test_cancellation_drains_owned_test_before_owner_is_released(self):
        import threading
        run_id=await self.run_pass()
        entered=threading.Event(); release=threading.Event()
        def blocked(repo,command,timeout):
            entered.set()
            if not release.wait(30):raise TimeoutError('fixture release missing')
            return native_test(repo,command,timeout)
        with patch.object(CodingWorkflowService,'_run_command',side_effect=blocked):
            task=asyncio.create_task(self.delivery.prepare(run_id,confirmed=True))
            await asyncio.wait_for(asyncio.to_thread(entered.wait,30),35)
            task.cancel()
            await asyncio.sleep(.05)
            self.assertFalse(task.done())
            task.cancel()
            await asyncio.sleep(.05)
            self.assertFalse(task.done())
            with self.assertRaises(TimeoutError):
                with _file_lock(self.root/run_id/'coordinator',timeout=0):pass
            release.set()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(self.service.load(run_id)['delivery']['status'],'interrupted')
        self.assertEqual((await self.delivery.prepare(run_id,confirmed=True))['status'],'ready')

    async def test_fresh_tests_mutating_replay_are_rejected(self):
        run_id = await self.run_pass()
        def dirty(repo, command, timeout):
            result = native_test(repo, command, timeout)
            (repo/'b.py').write_text('def mul(a,b):\n    return 0\n')
            return result
        with patch.object(CodingWorkflowService, '_run_command', side_effect=dirty):
            with self.assertRaisesRegex(ValueError, 'test mutated'):
                await self.delivery.prepare(run_id, confirmed=True)
        self.assertEqual(self.service.load(run_id)['delivery']['status'], 'failed')

    async def test_packet_patch_manifest_and_replay_corruption_reject_approval(self):
        run_id = await self.run_pass()
        packet = await self.delivery.prepare(run_id, confirmed=True)
        for path in [Path(packet['patch_path']), Path(packet['manifest_path']),
                     Path(packet['manifest']['replay']['workspace']['workspace'])/'a.py']:
            before = path.read_bytes()
            path.write_bytes(before+b'\ncorrupt')
            with self.assertRaises((ValueError, RuntimeError)):
                self.delivery.approve(run_id, actor='owner', manifest_digest=packet['manifest_digest'], confirmed=True)
            path.write_bytes(before)
        self.assertEqual(self.delivery.inspect(run_id)['status'], 'ready')

    async def test_source_drift_and_live_owner_reject_delivery(self):
        run_id = await self.run_pass()
        with _file_lock(self.root/run_id/'coordinator', timeout=0):
            with self.assertRaises(TimeoutError):
                await self.delivery.prepare(run_id, confirmed=True)
        packet = await self.delivery.prepare(run_id, confirmed=True)
        (self.repo/'a.py').write_text('external editor update')
        with self.assertRaisesRegex(ValueError, 'source checkout changed'):
            self.delivery.approve(run_id, actor='owner', manifest_digest=packet['manifest_digest'], confirmed=True)
        self.assertEqual((self.repo/'a.py').read_text(), 'external editor update')

    async def test_http_prepare_read_and_approval(self):
        import httpx
        from fastapi import FastAPI
        import clawos_server as server
        run_id = await self.run_pass()
        app=FastAPI()
        app.add_api_route('/delivery/{run_id}',server.api_collaboration_delivery,methods=['GET','POST'])
        app.add_api_route('/delivery/{run_id}/approve',server.api_collaboration_delivery_approve,methods=['POST'])
        with patch.object(server, 'get_reliable_collaboration_service', return_value=self.service):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                self.assertEqual((await client.post('/delivery/'+run_id,json={})).status_code,409)
                response=await client.post('/delivery/'+run_id,json={'confirmed':True})
                self.assertEqual(response.status_code,200,response.text)
                digest=response.json()['manifest_digest']
                self.assertIn('diff --git',(await client.get('/delivery/'+run_id)).json()['diff'])
                approved=await client.post('/delivery/'+run_id+'/approve',json={'confirmed':True,'actor':'owner','manifest_digest':digest})
                self.assertEqual(approved.json()['status'],'approved')

    async def test_delivery_available_without_model_provider_but_new_execution_requires_it(self):
        import clawos_server as server
        from fastapi import HTTPException
        self.root=self.folder/'collaboration-runs'
        self.service.root=self.root
        run_id=await self.run_pass()
        with patch.object(server,'OUTPUT_ROOT',self.folder), patch.object(server,'g_upstream_provider',None),\
             patch.object(server,'g_memory_store',None):
            with self.assertRaises(HTTPException) as denied:
                server.get_reliable_collaboration_service()
            self.assertEqual(denied.exception.status_code,503)
            offline=server.get_reliable_collaboration_service(require_model=False)
            self.assertIsNone(offline.factory(None))
            handoff=CollaborationDelivery(offline)
            packet=await handoff.prepare(run_id,confirmed=True)
            approved=handoff.approve(run_id,actor='owner',manifest_digest=packet['manifest_digest'],confirmed=True)
            self.assertEqual(approved['status'],'approved')
            self.assertEqual(handoff.inspect(run_id)['manifest_digest'],packet['manifest_digest'])
            import httpx
            from fastapi import FastAPI
            app=FastAPI()
            app.add_api_route('/api/subagents/run',server.api_autonomous_subagents,methods=['POST'])
            app.add_api_route('/delivery/{run_id}',server.api_collaboration_delivery,methods=['GET','POST'])
            app.add_api_route('/delivery/{run_id}/approve',server.api_collaboration_delivery_approve,methods=['POST'])
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                new=await client.post('/api/subagents/run',json={'team_profile':'reliable_coding','confirmed':True})
                self.assertEqual(new.status_code,503)
                self.assertEqual((await client.post('/delivery/'+run_id,json={'confirmed':True})).status_code,200)
                self.assertEqual((await client.get('/delivery/'+run_id)).json()['manifest_digest'],packet['manifest_digest'])
                replay=await client.post('/delivery/'+run_id+'/approve',json={'actor':'owner','confirmed':True,'manifest_digest':packet['manifest_digest']})
                self.assertEqual(replay.json()['status'],'approved')

    async def test_real_delivery_process_death_then_fresh_replay(self):
        run_id = await self.run_pass()
        child_code = '''import asyncio,os,sys
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(sys.argv[1])/'tests')]
from services.reliable_collaboration import ReliableCollaborationService
from services.collaboration_delivery import CollaborationDelivery
from services.coding_workflow_service import CodingWorkflowService
from test_collaboration_delivery import native_test
class CrashService(ReliableCollaborationService):
    def event(self,state,kind,**fields):
        super().event(state,kind,**fields)
        if kind=='delivery_test':os._exit(17)
CodingWorkflowService._run_command=staticmethod(native_test)
svc=CrashService(lambda spec:None,root=sys.argv[2])
asyncio.run(CollaborationDelivery(svc).prepare(sys.argv[3],confirmed=True))
'''
        proc = await asyncio.to_thread(subprocess.run,[sys.executable,'-c',child_code,str(ROOT),str(self.root),run_id],capture_output=True,text=True,timeout=120)
        self.assertEqual(proc.returncode,17,proc.stderr)
        previous=self.service.load(run_id)['delivery']['workspace']['workspace']
        self.assertTrue(self.service.inspect(run_id)['needs_recovery'])
        packet=await self.delivery.prepare(run_id,confirmed=True)
        self.assertNotEqual(previous,packet['manifest']['replay']['workspace']['workspace'])
        state=self.service.load(run_id)
        self.assertEqual([a['status'] for a in state['delivery_attempts']],['interrupted','ready'])
        self.assertIn('exit',state['delivery_attempts'][0]['error'])

    def test_windows_sensitive_aliases_and_devices_are_blocked(self):
        for path in ['Tools/weights.bin','.GIT/config','.ENV.local','src/NUL.py','src/trailing.','src/file ']:
            with self.assertRaises(ValueError):
                self.service.safe_path(path)


if __name__=='__main__':unittest.main()
