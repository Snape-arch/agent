from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from providers.base import model_result
from services.agentic_coding_loop_service import AgenticCodingLoopService
from services.coding_diagnostics_service import CodingDiagnosticsService, CodingEvidenceGate
from services.coding_trace_service import CodingTraceService
from services.coding_workflow_service import CodingWorkflowService
from services.execution_governance import GovernedExecutionContext


def make_repo(root: Path) -> Path:
    repo = root / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    return repo


class ReassessingProvider:
    def __init__(self):
        self.index = 0
        self.actions = [
            {"action": "read", "path": "calc.py", "start_line": 1, "end_line": 30},
            {
                "action": "propose_patch",
                "changes": [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a * b"}],
                "test_commands": [[sys.executable, "-m", "unittest", "test_calc.py"]],
                "hypothesis": {"claim": "multiplication implements add", "evidence_paths": ["calc.py"], "predicted_outcome": "test passes"},
                "acceptance_criteria": [{"id": "unit", "type": "tests_pass"}],
            },
            {"action": "read", "path": "test_calc.py", "start_line": 1, "end_line": 30},
            {
                "action": "propose_patch",
                "changes": [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a + b"}],
                "test_commands": [[sys.executable, "-m", "unittest", "test_calc.py"]],
                "hypothesis": {"claim": "addition operator satisfies the assertion", "evidence_paths": ["calc.py", "test_calc.py"], "predicted_outcome": "unit test passes"},
                "acceptance_criteria": [{"id": "unit", "type": "tests_pass"}],
            },
            {"action": "finish", "summary": "verified"},
        ]

    async def complete(self, messages, options=None, **kwargs):
        action = self.actions[min(self.index, len(self.actions) - 1)]
        self.index += 1
        return model_result(ok=True, provider="scripted", model="test", content=json.dumps(action), usage={"total_tokens": 10})


class CodingDiagnosticLoopTests(unittest.TestCase):
    def test_parses_test_trace_and_links_nearest_symbol(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            output = 'Traceback (most recent call last):\n  File "' + str(repo / "calc.py") + '", line 2, in add\n    return missing\nNameError: missing\n'
            result = CodingDiagnosticsService().analyze(repo, [{"command": ["python"], "exit_code": 1, "stdout": "", "stderr": output}])
        self.assertEqual(result["failure_category"], "implementation_failure")
        self.assertEqual(result["diagnostics"][0]["path"], "calc.py")
        self.assertEqual(result["diagnostics"][0]["related_symbol"]["name"], "add")

    def test_distinguishes_environment_test_and_requirement_failures(self):
        service = CodingDiagnosticsService()
        self.assertEqual(service.classify("command not found", nonzero=True, timed_out=False)[0], "environment_failure")
        self.assertEqual(service.classify("AssertionError: expected 5", nonzero=True, timed_out=False)[0], "test_failure")
        self.assertEqual(service.classify("acceptance criteria missing", nonzero=True, timed_out=False)[0], "requirements_failure")

    def test_evidence_gate_stops_repeated_or_excess_retrieval(self):
        gate = CodingEvidenceGate({"code_evidence": [{"path": "calc.py"}]})
        first = gate.register({"action": "read", "path": "calc.py"}, {"type": "read", "path": "calc.py"})
        second = gate.register({"action": "read", "path": "calc.py"}, {"type": "read", "path": "calc.py"})
        self.assertTrue(first["sufficient"])
        self.assertFalse(first["continue_retrieval"])
        self.assertTrue(second["duplicate"])

    def test_loop_reassesses_failed_hypothesis_and_enforces_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = make_repo(root)
            result = asyncio.run(AgenticCodingLoopService(
                ReassessingProvider(),
                workflow=CodingWorkflowService(artifact_root=root / "runs"),
                trace=CodingTraceService(root / "trace.json"),
            ).run(repo, "fix add", confirmed=True, task_id="t1", session_id="s1", max_turns=8))
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual([item["status"] for item in result["hypothesis_history"]], ["invalidated", "confirmed"])
        self.assertEqual(result["hypothesis_history"][0]["failure_category"], "test_failure")
        self.assertTrue(result["acceptance"]["passed"])
        reads = [item for item in result["observations"] if item["type"] == "read"]
        self.assertEqual([item["path"] for item in reads], ["calc.py", "test_calc.py"])
        self.assertFalse(reads[-1]["evidence_gate"]["continue_retrieval"])

    def test_unknown_acceptance_criterion_blocks_completion_and_restores(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = make_repo(root)
            result = CodingWorkflowService(artifact_root=root / "runs").execute(
                repo, "fix add",
                [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a + b"}],
                [[sys.executable, "-m", "unittest", "test_calc.py"]],
                confirmed=True, acceptance_criteria=[{"id": "manual-product-review", "type": "manual_review"}],
            )
            text = (repo / "calc.py").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["acceptance"]["passed"])
        self.assertIn("return a - b", text)

    def test_frozen_baseline_batches_retrieval_and_keeps_caller_test(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_repo(root)
            for index in range(15):
                (source / f'a{index:02}.py').write_text('value = 0\n', encoding='utf-8')
            target = source / 'zz_runtime.py'
            target.write_text('class Other:\n    def calculate(self):\n        return 0\n\n'
                              'def calculate():\n    return -42\n', encoding='utf-8')
            (source / 'test_calc.py').write_text("assert __import__('zz_runtime').calculate() == 42\n", encoding='utf-8')
            subprocess.run(['git', 'add', '.'], cwd=source, check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'repository discovery fixture'], cwd=source, check=True, capture_output=True)
            provider = ReassessingProvider()
            provider.actions = [
                {'action': 'inspect', 'actions': [
                    {'action': 'search', 'query': 'return -42', 'glob': '*.py'},
                    {'action': 'read', 'path': 'zz_runtime.py', 'symbol': 'calculate'},
                    {'action': 'read', 'path': 'zz_runtime.py', 'start_line': 5, 'end_line': 6},
                    {'action': 'read', 'path': 'zz_runtime.py', 'symbol': 'Other.calculate'},
                ]},
                {'action': 'propose_patch', 'changes': [dict(path='zz_runtime.py', operation='replace',
                    old_text='return -42', new_text='return 42')], 'test_commands': [['python', '-c', 'pass']],
                    'acceptance_criteria': ['the tests pass']},
            ]
            runs = []

            def run(repo, command, timeout, *, require_strict):
                self.assertTrue(require_strict)
                process = subprocess.run(command, cwd=repo, timeout=timeout, capture_output=True, text=True)
                runs.append((repo, command, process.returncode))
                return dict(command=command, exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr,
                            timed_out=False, sandbox={'strict_boundary_verified': True})

            command = [sys.executable, '-B', 'test_calc.py']
            governance = GovernedExecutionContext.local()
            tool_gates = []

            def observe_tool(payload):
                tool_gates.append(payload['tool'])

            governance.hooks.register('before_tool', 'record-retrieval', observe_tool)
            with patch.object(CodingWorkflowService, '_run_command', staticmethod(run)):
                result = asyncio.run(AgenticCodingLoopService(provider,
                    workflow=CodingWorkflowService(artifact_root=root/'runs'),
                    trace=CodingTraceService(root/'trace.json')).run(source, 'Repair the observed regression',
                        confirmed=True, task_id='discover', session_id='test', test_commands=[command], max_turns=2,
                        governance=governance))
            self.assertEqual(result['status'], 'passed', result.get('error'))
            self.assertEqual(provider.index, 2)
            self.assertEqual(tool_gates, ['baseline_tests', 'inspect', 'search', 'read', 'read', 'read'])
            self.assertEqual(governance.budget.tool_calls, 7)
            lookup = next(row for row in result['observations'] if row['type'] == 'inspect')
            search, ambiguous, top, qualified = lookup['results']
            self.assertEqual(search['matches'][0]['path'], 'zz_runtime.py')
            self.assertEqual([row['name'] for row in ambiguous['matches']], ['Other.calculate', 'calculate'])
            self.assertEqual(top['content'], 'def calculate():\n    return -42')
            self.assertEqual(qualified['content'], '    def calculate(self):\n        return 0')
            self.assertIn('zz_runtime.py', lookup['writable_paths'])
            self.assertEqual([row['type'] for row in result['acceptance']['criteria']],
                             ['tests_pass', 'scoped_diff', 'syntax_pass', 'diff_check'])
            self.assertNotIn('zz_runtime.py', result['observations'][0]['execution_context']['scope']['write_paths'])
            self.assertEqual([row[1:] for row in runs], [(command, 1), (command, 0)])
            self.assertTrue(all(row[0] != source for row in runs))
            self.assertIn('return -42', target.read_text(encoding='utf-8'))

    def test_inspect_rejects_excess_nested_and_write_actions(self):
        read = {'action': 'read', 'path': 'calc.py'}
        batch = lambda actions: json.dumps({'action': 'inspect', 'actions': actions})
        self.assertEqual(AgenticCodingLoopService._parse_action(batch([read]), batch_allowed=True)['actions'], [read])
        with self.assertRaises(ValueError):
            AgenticCodingLoopService._parse_action(batch([read]))
        for actions in ([], [read] * 5, [{'action': 'inspect'}], [{'action': 'propose_patch'}]):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                AgenticCodingLoopService._parse_action(batch(actions), batch_allowed=True)

    def test_agent_retries_an_inexact_anchor_before_running_candidate_tests(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = make_repo(root)
            command = [sys.executable, '-B', '-m', 'unittest', 'test_calc.py']
            tests = []

            def run(workspace, argv, timeout, *, require_strict):
                self.assertTrue(require_strict)
                result = subprocess.run(argv, cwd=workspace, timeout=timeout, capture_output=True, text=True)
                tests.append(result.returncode)
                return dict(command=argv, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                            timed_out=False, sandbox={'strict_boundary_verified': True})

            class RepairProvider:
                async def complete(_, messages, options):
                    old = 'return a-b'
                    if len(messages) > 2:
                        feedback = json.loads(messages[-1]['content'].split('\n', 1)[0])['observation']
                        self.assertEqual(feedback['anchor_diagnostics']['match_count'], 0)
                        old = feedback['anchor_diagnostics']['excerpts'][0]['content'].splitlines()[1].strip()
                        self.assertEqual(old, 'return a - b')
                        self.assertEqual(tests, [1])
                    return model_result(ok=True, provider='scripted', model='test', content=json.dumps({
                        'action': 'propose_patch', 'changes': [dict(path='calc.py', operation='replace',
                            old_text=old, new_text='return a + b')],
                    }), usage={'total_tokens': 10})

            with patch.object(CodingWorkflowService, '_run_command', staticmethod(run)):
                result = asyncio.run(AgenticCodingLoopService(RepairProvider(),
                    workflow=CodingWorkflowService(artifact_root=root/'runs'),
                    trace=CodingTraceService(root/'trace.json')).run(repo, 'Fix addition', confirmed=True,
                        task_id='anchor-retry', session_id='test', test_commands=[command], max_turns=2))
            self.assertEqual(result['status'], 'passed', result.get('error'))
            self.assertEqual(tests, [1, 0])
            self.assertIn('return a - b', (repo/'calc.py').read_text(encoding='utf-8'))

    def test_frozen_baseline_workspace_mutation_stops_before_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = make_repo(root)
            provider = ReassessingProvider()

            def mutate(repo, command, timeout, *, require_strict):
                self.assertTrue(require_strict)
                (repo / 'calc.py').write_text('modified by test', encoding='utf-8')
                return dict(exit_code=0, timed_out=False, sandbox={'strict_boundary_verified': True})

            with patch.object(CodingWorkflowService, '_run_command', staticmethod(mutate)):
                result = asyncio.run(AgenticCodingLoopService(provider,
                    workflow=CodingWorkflowService(artifact_root=root/'runs'),
                    trace=CodingTraceService(root/'trace.json')).run(source, 'fix add', confirmed=True,
                        task_id='mutating-test', session_id='test', test_commands=[[sys.executable, 'test_calc.py']]))
            self.assertEqual(result['status'], 'failed')
            self.assertFalse(result['observations'][0]['available'])
            self.assertEqual(provider.index, 0)
            self.assertIn('return a - b', (source/'calc.py').read_text(encoding='utf-8'))

    def test_caller_probe_imports_prioritize_source_without_target_paths(self):
        from services.coding_context_service import CodingContextService
        from services.coding_execution_context import CodingExecutionContext

        with tempfile.TemporaryDirectory() as td:
            source = make_repo(Path(td))
            for index in range(15):
                (source / f'a{index:02}.py').write_text('value = 0\n', encoding='utf-8')
            anchor = 'def calculate():\n    return -42'
            (source / 'zz_runtime.py').write_text(anchor + '\n', encoding='utf-8')
            (source / 'test_calc.py').write_text('from zz_runtime import calculate\nassert calculate() == 42\n', encoding='utf-8')
            subprocess.run(['git', 'add', '.'], cwd=source, check=True, capture_output=True)
            command = ['python', r'.\test_calc.py']
            objective = 'Repair the observed regression'
            self.assertNotIn('zz_runtime.py', CodingExecutionContext.targets(source, objective, None))
            evidence = CodingExecutionContext.test_evidence_paths(source, [command], [])
            self.assertEqual(evidence, ['zz_runtime.py'])
            manifest = CodingContextService().build_execution(source, objective, test_evidence_paths=evidence)
            self.assertEqual(manifest['code_evidence'][0]['path'], 'zz_runtime.py')
            self.assertIn(anchor, manifest['code_evidence'][0]['content'])
            self.assertNotIn('test_calc.py', manifest['scope']['write_paths'])
            reproduction = CodingExecutionContext.reproduction_evidence(source, [command], manifest, evidence, objective)
            self.assertEqual(reproduction['source_anchors'], [
                {'path': 'zz_runtime.py', 'start_line': 1, 'end_line': 2, 'content': anchor},
            ])
            self.assertEqual(reproduction['public_tests'][0]['path'], 'test_calc.py')
            restricted = CodingContextService().build_execution(source, objective, focus_paths=['calc.py'])
            restricted_evidence = CodingExecutionContext.reproduction_evidence(
                source, [command], restricted, evidence, objective)
            self.assertEqual(restricted_evidence['source_anchors'], [])

    def test_frozen_candidate_rejects_workspace_changes_or_missing_attestation(self):
        for mutation in (True, False):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                repo = make_repo(root)
                workflow = CodingWorkflowService(artifact_root=root/'runs')
                calls = []

                def run(candidate, command, timeout, *, require_strict):
                    calls.append(command)
                    self.assertTrue(require_strict)
                    if mutation:
                        (candidate/'test_calc.py').write_text('# modified by test\n', encoding='utf-8')
                    return dict(command=command, exit_code=0, timed_out=False,
                                sandbox={'strict_boundary_verified': mutation})

                command = ['python', '-B', 'test_calc.py']
                with patch.object(CodingWorkflowService, '_run_command', staticmethod(run)):
                    result = workflow.execute(repo, 'fix addition',
                        [dict(path='calc.py', operation='replace', old_text='return a - b', new_text='return a + b')],
                        [command, command], confirmed=True, require_strict=True)
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['acceptance']['passed'])
                self.assertEqual(calls, [command])
                self.assertEqual(result['rounds'][0]['tests'][0]['exit_code'], 0)
                self.assertIn('changed the task workspace' if mutation else 'strict sandbox', result['test_boundary_failure'])
                self.assertIn('return a - b', (repo/'calc.py').read_text(encoding='utf-8'))


if __name__ == "__main__":
    unittest.main()
