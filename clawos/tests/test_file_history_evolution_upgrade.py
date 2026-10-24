"""Executed regressions for files, archived history and policy ownership."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from memoryos.memory_store import MemoryStore
from services.file_transactions import write_text
from services.conversation_history import export_history
from services.grounded_paper_report import GroundedPaperReport
from services.coding_workflow_service import CodingWorkflowService
from reflection.evolution_runtime import RuntimePolicyController
from reflection.self_evolution import SelfEvolutionManager


class FileHistoryEvolutionUpgradeTests(unittest.TestCase):
    def test_preview_and_create_only_never_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td)/'nested'/'paper.md'
            planned = write_text(file, '论文', preview=True)
            self.assertFalse(file.parent.exists())
            self.assertFalse(planned['written'])
            saved = write_text(file, '论文', create_only=True)
            self.assertEqual(saved['sha256'], planned['sha256'])
            with self.assertRaisesRegex(ValueError, 'already exists'):
                write_text(file, 'overwrite', create_only=True)
            self.assertEqual(file.read_text(encoding='utf-8'), '论文')

    def test_concurrent_append_preserves_all_writes(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td)/'notes.txt'
            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(lambda i: write_text(file, f'{i}\n', append=True), range(60)))
            self.assertEqual(sorted(map(int,file.read_text().splitlines())), list(range(60)))

    def test_empty_lock_contention_waits_instead_of_writing_locked_byte(self):
        from services.file_transactions import _file_lock
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'new-file.md'
            with patch('services.file_transactions.tempfile.gettempdir', return_value=td):
                with _file_lock(target):
                    def contender():
                        with _file_lock(target, timeout=.05):
                            return 'unexpectedly acquired'
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with self.assertRaisesRegex(TimeoutError, 'file is busy'):
                            pool.submit(contender).result()
                self.assertEqual(next((Path(td)/'clawos-file-locks').glob('*.lock')).stat().st_size, 0)
                self.assertTrue(write_text(target, 'after release')['written'])

    def test_cross_process_cas_has_one_winner(self):
        code = '''import sys,time,pathlib,json
from services.file_transactions import write_text
file,digest,gate,ready = sys.argv[1:]
pathlib.Path(ready).touch()
deadline=time.monotonic()+15
while not pathlib.Path(gate).exists():
 if time.monotonic()>deadline: raise TimeoutError('test gate')
 time.sleep(.01)
try:
 print(json.dumps(write_text(file, ready, expected_sha256=digest)))
except ValueError as exc:
 print(json.dumps({'conflict':str(exc)}))
'''
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); target=root/'report.md'; gate=root/'go'
            digest=write_text(target,'baseline')['sha256']
            env=dict(os.environ,PYTHONPATH=str(ROOT))
            jobs=[]
            try:
                for i in range(6):
                    jobs.append(subprocess.Popen([sys.executable,'-c',code,str(target),digest,str(gate),str(root/f'ready{i}')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True))
                deadline=time.monotonic()+15
                while len(list(root.glob('ready*'))) != 6:
                    if time.monotonic()>deadline: self.fail('processes did not reach the test barrier')
                    time.sleep(.01)
                gate.touch()
                results=[]
                for job in jobs:
                    out,err=job.communicate(timeout=20)
                    self.assertEqual(job.returncode,0,err)
                    results.append(json.loads(out))
                self.assertEqual(sum(r.get('written',False) for r in results),1)
                self.assertEqual(sum('conflict' in r for r in results),5)
                self.assertFalse(list(root.glob('.*.tmp')))
            finally:
                for job in jobs:
                    if job.poll() is None: job.kill();job.wait()

    def test_replace_retries_transient_windows_permission(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'retry.md'
            real_replace = os.replace
            calls = {'count': 0}
            def flaky_replace(source, destination):
                calls['count'] += 1
                if calls['count'] < 3:
                    raise PermissionError(5, 'fixture lock')
                return real_replace(source, destination)
            with patch('services.file_transactions.os.replace', side_effect=flaky_replace):
                result = write_text(target, 'retry')
            self.assertTrue(result['written'])
            self.assertEqual(3, calls['count'])
            self.assertEqual('retry', target.read_text(encoding='utf-8'))

    def test_large_append_rejected_without_changing_file(self):
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'data.txt';write_text(file,'1234')
            with self.assertRaises(ValueError): write_text(file,'56789',append=True,max_bytes=8)
            self.assertEqual(file.read_text(),'1234')

    def test_concurrent_artifact_registration_preserves_every_download(self):
        from services.artifact_delivery_service import ArtifactDeliveryService
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);registry=root/'artifacts.json'
            files=[root/f'report-{i}.md' for i in range(40)]
            for file in files:file.write_text(file.name)
            def register(file):
                return ArtifactDeliveryService(registry,[root]).register(file)
            with ThreadPoolExecutor(max_workers=12) as pool:
                artifacts=list(pool.map(register,files))
            service=ArtifactDeliveryService(registry,[root])
            for item in artifacts:self.assertEqual(service.resolve(item['id'])[1].name,item['name'])
            self.assertEqual(len(json.loads(registry.read_text())),40)

    def test_paper_section_heading_is_not_a_finding(self):
        from services.paper_intelligence_service import PaperIntelligenceService
        service=PaperIntelligenceService(None)
        result=service._claims([dict(id=1,content='Experiments and Results\nWe find accuracy is 85 percent on 200 claims.',citation='doc:1#page=1&chunk=1')],
                               [dict(chunk_id=1,section='experiments',heading='Experiments and Results')])
        self.assertEqual(len(result),1)
        self.assertTrue(result[0]['claim'].startswith('We find'))

    def test_preview_is_not_delivered_as_an_overwritten_artifact(self):
        from services.artifact_delivery_service import ArtifactDeliveryService
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);file=root/'existing.md';write_text(file,'original')
            result=write_text(file,'planned',preview=True)
            service=ArtifactDeliveryService(root/'index.json',[root])
            self.assertEqual(service.collect([dict(name='file_write',result=dict(data=result))]),[])
            self.assertFalse(service.registry_path.exists())

    def test_malformed_artifact_registry_is_preserved(self):
        from services.artifact_delivery_service import ArtifactDeliveryService
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);file=root/'paper.md';file.write_text('paper')
            index=root/'index.json';index.write_text('{broken')
            service=ArtifactDeliveryService(index,[root])
            with self.assertRaisesRegex(ValueError,'unreadable'): service.register(file)
            self.assertEqual(index.read_text(),'{broken')

    def test_archived_history_full_text_paging_search_and_export(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            for i in range(112):
                store.add_message('paper-session','user' if i%2==0 else 'assistant',
                                  ('archive-needle '+('长'*3000)) if i==0 else f'message-{i}')
            store.add_message('paper-session','tool','SECRET_INTERNAL_TOOL_PAYLOAD')
            newest=store.conversation_history('paper-session',17)
            self.assertTrue(newest['has_more'])
            exported=export_history(store,'paper-session')
            self.assertEqual(exported['count'],112)
            self.assertEqual(len(exported['messages'][0]['content']),3015)
            self.assertEqual(exported['messages'][-1]['content'],'message-111')
            self.assertTrue(exported['messages'][0]['archived'])
            self.assertNotIn('SECRET_INTERNAL',json.dumps(exported))
            ids=[m['id'] for m in exported['messages']]
            self.assertEqual(ids,sorted(set(ids)))
            sessions=store.list_sessions('archive-needle')
            self.assertEqual([s['session_id'] for s in sessions],['paper-session'])
            self.assertEqual(sessions[0]['last_message'],'message-111')

    def test_archive_only_session_remains_discoverable(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            store.add_message('archived','user','old question')
            store.archive_session_messages('archived',[store.get_session_messages('archived')[0]['id']])
            self.assertEqual(store.list_sessions()[0]['session_id'],'archived')
            self.assertEqual(store.conversation_history('archived')['count'],1)

    def test_history_api_does_not_truncate_or_leak_tool_messages(self):
        import clawos_server as server
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            store.add_message('s','user','文'*5000)
            store.add_message('s','tool','private')
            with patch.object(server,'g_memory_store',store):
                result=json.loads(asyncio.run(server.get_history('s',1)).body)
                self.assertEqual(len(result['messages'][0]['content']),5000)
                self.assertEqual(result['total'],1)

    def test_report_keeps_conditions_source_index_and_unknown_citation_boundary(self):
        citation='doc:7#page=3&chunk=1'
        bundle=dict(document=dict(id=7,title='Evidence paper'),quality={},allowed_citations={citation:'200 blinded claims; accuracy 85%.'})
        report=GroundedPaperReport.normalize(dict(findings=[dict(text='Accuracy 85%',citations=citation,conditions=['200 claims','blinded'])]),bundle,mode='model_assisted')
        markdown=GroundedPaperReport.render_markdown(report)
        self.assertIn('200 claims；blinded',markdown)
        self.assertIn('document=7&page=3',markdown)
        self.assertEqual(report['source_index'][0]['citation'],citation)
        self.assertFalse(report['citation_audit']['semantic_entailment_verified'])
        foreign=GroundedPaperReport.build_evidence_bundle(dict(document=dict(id=7),sections=dict(abstract=[dict(citation='doc:8#page=1&chunk=1',excerpt='foreign source')]),claims=[]))
        self.assertEqual(foreign['allowed_citations'],{})

    def test_stale_candidate_cannot_route_or_publish(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            store.set_runtime_policy('prompt_policy','default',{'system':'v1'})
            manager=SelfEvolutionManager(store,benchmark_runner=object())
            run=manager.create_run('prompt_policy','default',{'system':'v1'},{'system':'candidate'})
            store.update_self_evolution_run(run['id'],status='canary',publish_decision='canary',traffic_percent=100)
            store.set_runtime_policy('prompt_policy','default',{'system':'v2'})
            selected=RuntimePolicyController(store).resolve('prompt_policy','default','s')
            self.assertEqual(selected['payload'],{'system':'v2'})
            self.assertIsNone(selected['run_id'])
            with self.assertRaisesRegex(ValueError,'policy changed'): store.publish_self_evolution_run(run['id'])
            with self.assertRaisesRegex(ValueError,'policy changed'): manager.promote_canary(run['id'])

    def test_rollback_restores_owned_policy_and_rejects_newer_version(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            store.set_runtime_policy('prompt_policy','default',{'system':'base'})
            def publish():
                run=store.create_self_evolution_run('test','prompt_policy','default',{'system':'base'},{'system':'candidate'})
                store.update_self_evolution_run(run['id'],status='canary',publish_decision='canary')
                return store.publish_self_evolution_run(run['id'])
            first=publish()
            store.rollback_self_evolution_run(first['id'])
            self.assertEqual(store.get_runtime_policy('prompt_policy','default')['payload'],{'system':'base'})
            second=publish()
            store.set_runtime_policy('prompt_policy','default',{'system':'newer'})
            with self.assertRaisesRegex(ValueError,'newer policy'): store.rollback_self_evolution_run(second['id'])
            self.assertEqual(store.get_runtime_policy('prompt_policy','default')['payload'],{'system':'newer'})

    def test_mismatched_baseline_creation_rolls_back(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            store.set_runtime_policy('prompt_policy','default',{'system':'real'})
            with self.assertRaisesRegex(ValueError,'baseline payload'):
                store.create_self_evolution_run('bad','prompt_policy','default',{'system':'fake'},{'system':'new'})
            self.assertEqual(store.list_self_evolution_runs(),[])

    def test_independent_policy_writers_increment_versions_without_reuse(self):
        with tempfile.TemporaryDirectory() as td:
            stores=[MemoryStore(str(Path(td)/'memory.db')) for _ in range(6)]
            def write(i):
                return stores[i%6].set_runtime_policy('prompt_policy','default',{'system':str(i)})['version']
            with ThreadPoolExecutor(max_workers=6) as pool:
                versions=list(pool.map(write,range(24)))
            self.assertEqual(sorted(versions),list(range(1,25)))
            self.assertEqual(stores[0].get_runtime_policy('prompt_policy','default')['version'],24)

    def test_evolution_board_counts_only_owned_active_policy(self):
        import clawos_server as server
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(str(Path(td)/'memory.db'))
            run=store.create_self_evolution_run('candidate','prompt_policy','default',{}, {'system':'candidate'})
            store.update_self_evolution_run(run['id'],status='canary',publish_decision='canary')
            store.publish_self_evolution_run(run['id'])
            with patch.object(server,'g_memory_store',store):
                before=json.loads(asyncio.run(server.api_self_evolution_board()).body)
                store.set_runtime_policy('prompt_policy','default',{'system':'newer'})
                after=json.loads(asyncio.run(server.api_self_evolution_board()).body)
            self.assertEqual(before['active_count'],1)
            self.assertEqual(after['active_count'],0)
            self.assertEqual(after['stage_counts'],{'superseded':1})
            self.assertFalse(before['enterprise_ready'])

    def test_strict_sandbox_blocks_unisolated_execution(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,CLAWOS_REQUIRE_OS_SANDBOX='true'):
            sentinel=Path(td)/'executed'
            with patch('services.coding_workflow_service.subprocess.run') as run:
                result=CodingWorkflowService._run_command(Path(td),[sys.executable,'-c',f"open({str(sentinel)!r},'w').close()"],10)
                run.assert_not_called()
            self.assertEqual(result['exit_code'],126)
            self.assertFalse(sentinel.exists())
            self.assertTrue(result['sandbox']['downgrade_blocked'])

    @unittest.skipUnless(os.name=='nt','Windows sandbox orchestrator')
    def test_strict_sandbox_blocks_missing_appcontainer_in_task_workspace(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ,CLAWOS_REQUIRE_OS_SANDBOX='1'):
            root=Path(td);repo=root/'workspace';repo.mkdir()
            (root/'workspace.json').write_text(json.dumps(dict(schema='clawos.task-workspace.v1',workspace=str(repo),isolated=True)))
            with patch('services.coding_workflow_service.WindowsAppContainerBoundary.status',return_value={'installed':False}), patch('services.coding_workflow_service.WindowsJobSandbox.run') as fallback:
                result=CodingWorkflowService._run_command(repo,[sys.executable,'-c','print(1)'],10)
                fallback.assert_not_called()
            self.assertEqual(result['exit_code'],126)
            self.assertTrue(result['sandbox']['launch_failed_closed'])


if __name__=='__main__': unittest.main()
