from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.workspace_coding import WorkspaceCodingAPI
from providers.base import model_result
from services.coding_session_store import CodingSessionStore
from services.coding_workflow_service import CodingWorkflowService
from test_coding_diagnostic_loop import make_repo


class CodingSessionContinuityTests(unittest.TestCase):
    def test_http_pause_resume_and_project_memory_survive_recreating_the_service(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = make_repo(root)
            output = root / 'output'
            runs = []
            first = {'action': 'read', 'path': 'calc.py'}
            second = {'action': 'propose_patch', 'changes': [dict(path='calc.py', operation='replace',
                old_text='return a - b', new_text='return a + b')]}
            route = '/api/workspace/coding/autonomous'

            def client(answer, prompts):
                class Provider:
                    async def complete(self, messages, options):
                        prompts.append(messages)
                        return model_result(ok=True, provider='fixture', model='fixture',
                                            content=json.dumps(answer), usage={'total_tokens': 10})

                api = WorkspaceCodingAPI(get_coding_workflow_service=lambda: CodingWorkflowService(
                    artifact_root=output/'coding'), output_root_provider=lambda: output,
                    context_builder_provider=lambda: None, memory_store_provider=lambda: None,
                    security_policy_provider=lambda: None, upstream_provider_provider=Provider,
                    workspace_services_provider=lambda: None)
                app = FastAPI()
                app.include_router(api.router)
                return TestClient(app)

            def test_runner(workspace, argv, timeout, *, require_strict):
                self.assertTrue(require_strict)
                result = subprocess.run(argv, cwd=workspace, timeout=timeout, capture_output=True, text=True)
                runs.append((workspace, argv, result.returncode))
                return dict(command=argv, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                            timed_out=False, sandbox={'strict_boundary_verified': True})

            project_body = {'repo_path': str(repo)}
            start = project_body | dict(action='start', task_id='calc', session_id='old', confirmed=True,
                objective='Fix addition in calc', max_turns=2, pause_after=1,
                test_commands=[[sys.executable, '-B', '-m', 'unittest', 'test_calc.py']])
            with patch.object(CodingWorkflowService, '_run_command', staticmethod(test_runner)):
                with client(first, []) as api:
                    note = project_body | dict(action='memory_save', topic='Addition', note='Run the calc checks.',
                                               scope='calc.py')
                    self.assertEqual(api.post(route, json=note).status_code, 409)
                    saved = api.post(route, json=note | {'confirmed': True}).json()['note']
                    self.assertEqual(api.post(route, json=project_body | {'action': 'memory_list', 'query': 'calc'})
                                     .json()['notes'][0]['id'], saved['id'])
                    paused = api.post(route, json=start)
                    self.assertEqual(paused.status_code, 200, paused.text)
                    paused = paused.json()
                    self.assertEqual((paused['status'], paused['next_turn']), ('paused', 2))
                prompts = []
                with client(second, prompts) as api:
                    update = note | dict(note_id=saved['id'], note='Use the updated calc checks.', confirmed=True)
                    self.assertEqual(api.post(route, json=update).json()['note']['id'], saved['id'])
                    resume = project_body | dict(action='resume', session_id='new',
                                                 checkpoint_id=paused['checkpoint_id'])
                    self.assertEqual(api.post(route, json=resume).status_code, 409)
                    workspace = Path(paused['workspace']['workspace'])
                    target = workspace / 'calc.py'
                    before = target.read_bytes()
                    target.write_bytes(before + b'# drift\n')
                    self.assertEqual(api.post(route, json=resume | {'confirmed': True}).status_code, 400)
                    target.write_bytes(before)
                    result = api.post(route, json=resume | {'confirmed': True})
                    self.assertEqual(result.status_code, 200, result.text)
                    self.assertEqual(result.json()['status'], 'passed')
                    self.assertEqual(api.post(route, json=resume | {'confirmed': True}).status_code, 400)
                    history = api.post(route, json=project_body | {'action': 'history'}).json()['checkpoints']
                    self.assertEqual((history[0]['session_id'], history[0]['status']), ('new', 'completed'))
                    self.assertEqual(api.post(route, json=project_body | dict(action='memory_delete',
                        note_id=saved['id'], confirmed=True)).json(), {'deleted': True})

            self.assertEqual(len(prompts), 1)
            self.assertIn('Use the updated calc checks.', prompts[0][1]['content'])
            self.assertNotIn('Run the calc checks.', prompts[0][1]['content'])
            self.assertIn('return a - b', prompts[0][-1]['content'])
            self.assertEqual([row[2] for row in runs], [1, 0])
            self.assertEqual(runs[0][:2], runs[1][:2])
            self.assertIn('return a - b', (repo/'calc.py').read_text())
            store = CodingSessionStore(output/'coding'/'continuity')
            project = store.project(repo, 'local-user')
            state = store.load(project, paused['checkpoint_id'])
            self.assertEqual(state['budget']['model_calls'], 2)
            self.assertEqual(state['budget']['tokens'], 20)
            self.assertEqual(store.recall(project, repo, ['calc.py']), [])
            (repo/'calc.py').write_bytes((workspace/'calc.py').read_bytes())
            self.assertEqual(store.recall(project, repo, ['calc.py'])[0]['tests'], 1)
            self.assertEqual(store.recall(store.project(repo, 'another-user'), repo, ['calc.py']), [])
            self.assertEqual(store.notes(project), [])

    def test_checkpoint_integrity_and_exclusive_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CodingSessionStore(folder)
            project = store.project(folder, 'local-user')
            run_id = 'ctr-' + '1' * 32
            store.save(project, run_id, {'status': 'resumable'})
            with store.lock(project, run_id):
                with self.assertRaises(TimeoutError), CodingSessionStore(folder).lock(project, run_id):
                    self.fail('second resume acquired the lock')
            self.assertEqual(store.load(project, run_id), {'status': 'resumable'})
            with self.assertRaisesRegex(ValueError, 'not found'):
                store.load(store.project(folder, 'another-user'), run_id)
            path = next((Path(folder)/'sessions'/project).glob('*.json'))
            data = json.loads(path.read_bytes())
            data['state']['status'] = 'completed'
            path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                store.load(project, run_id)

    def test_project_memory_recalls_an_old_chinese_note_across_large_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store = CodingSessionStore(folder)
            project = store.project(folder, 'local-user')
            original = store.save_note(project, '解析器约定', '空输入必须保留分隔符语义')
            foreign = store.project(folder, 'other')
            store.save_note(foreign, '分隔符约定', '另一个项目的记录')
            for i in range(300):
                store.save_note(project, f'Build note {i}', 'Use the integration test suite')
            restored = CodingSessionStore(folder)
            result = restored.recall_notes(project, '修复空输入时的分隔符问题', ['calc.py'])
            self.assertEqual([row['note'] for row in result], [original['note']])
            self.assertEqual(len(restored.notes(project)), 50)
            self.assertEqual(restored.notes(project, query='解析器')[0]['id'], original['id'])
