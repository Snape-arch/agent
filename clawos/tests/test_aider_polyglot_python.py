"""Verify scorer evidence distinguishes test failures from blocked imports."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_aider_polyglot_python as benchmark


class AiderScoringTests(unittest.TestCase):
    def score(self, tests):
        def run(repo, command, timeout, *, require_strict):
            self.assertTrue(require_strict)
            process = subprocess.run([sys.executable, *command[1:]], cwd=repo, capture_output=True,
                                     encoding='utf-8', timeout=timeout, check=False)
            return dict(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr,
                        sandbox=dict.fromkeys(benchmark.BOUNDARY, True))

        with tempfile.TemporaryDirectory() as folder, patch.object(
            benchmark.CodingWorkflowService, '_run_command', side_effect=run,
        ):
            return benchmark.scorer(Path(folder), dict(test_module='exercise_test',
                                   tests={'exercise_test.py': tests.encode('utf-8')}), b'')

    def test_assertion_failure_carries_case_and_actual_assertion(self):
        result = self.score('import unittest\nclass Exercise(unittest.TestCase):\n'
                            '    def test_boundary(self):\n        self.assertEqual(3, 5)\n')
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['tests'], 1)
        self.assertFalse(result['sandbox_import_denied'])
        self.assertEqual(result['failures'], [{'case': 'exercise_test.Exercise.test_boundary',
                                             'detail': 'AssertionError: 3 != 5'}])

    def test_windows_standard_library_import_denial_is_visible_separately(self):
        result = self.score("raise PermissionError('[WinError 10013]'); import _overlapped\n")
        self.assertEqual(result['exit_code'], 1)
        self.assertTrue(result['load_failed'])
        self.assertTrue(result['sandbox_import_denied'])

    def test_multiline_failure_keeps_first_difference_and_only_records_executed_passes(self):
        result = self.score('import unittest\nclass Exercise(unittest.TestCase):\n'
                            '    def test_a(self):\n        self.assertEqual([1, 2], [1, 3])\n'
                            '    def test_b(self):\n        self.assertTrue(True)\n'
                            '    @unittest.skip("not executed")\n'
                            '    def test_c(self):\n        pass\n')
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['tests'], 3)
        self.assertEqual(len(result['passed_cases']), 1)
        self.assertEqual(result['unverified_cases'], 1)
        self.assertIn('AssertionError: Lists differ:', result['failures'][0]['detail'])
        self.assertIn('First differing element 1:\n2\n3', result['failures'][0]['detail'])


class CandidateRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_uses_scored_candidate_and_records_regressions(self):
        calls = []

        class Provider:
            name = 'fixture'
            model = 'fixture'

            async def complete(self, messages, options):
                calls.append(messages[-1]['content'])
                before, after = ('return 0', 'return n + 1') if len(calls) == 1 else ('return n + 1', repair)
                answer = dict(changes=[dict(path='exercise.py', operation='replace', old_text=before, new_text=after)],
                              test_commands=[['python', '-m', 'unittest']])
                return dict(ok=True, content=json.dumps(answer), usage={'total_tokens': 30}, provider=self.name,
                            model=self.model, raw={'choices': [{'finish_reason': 'stop'}]})

        def run(repo, command, timeout, **kwargs):
            result = subprocess.run([sys.executable, *command[1:]], cwd=repo, capture_output=True,
                                    encoding='utf-8', timeout=timeout, check=False)
            return dict(command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr, timed_out=False,
                        sandbox=dict.fromkeys(benchmark.BOUNDARY, True))

        case = dict(starter='exercise.py', body=b'def adjust(n):\n    return 0\n', test_module='exercise_test',
                    test_count=2, objective='Fix adjust to increment positives and leave zero unchanged.',
                    tests={'exercise_test.py': b'import unittest\nfrom exercise import adjust\n'
                           b'class Exercise(unittest.TestCase):\n'
                           b'    def test_positive(self):\n        self.assertEqual(adjust(2), 3)\n'
                           b'    def test_zero(self):\n        self.assertEqual(adjust(0), 0)\n'})
        variants = [('return n + 1 if n else 0', 'passed'), ('return -n', 'failed'), ('return 0', 'failed')]
        for repair, expected in variants:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder, patch.object(
                benchmark.CodingWorkflowService, '_run_command', staticmethod(run),
            ):
                calls.clear()
                row = await benchmark.exercise('exercise', case, Path(folder), Provider(), {},
                                               limits=benchmark.LIMITS, repair_reasoning=None, reuse_candidate=True)
                self.assertEqual(row['status'], expected, row['attempts'])
                first, repaired = row['attempts']
                self.assertEqual(len(first['score']['passed_cases']), 1)
                self.assertEqual(repaired['repaired_from'], first['patch_sha256'])
                if repair == 'return 0':
                    self.assertEqual(repaired['status'], 'matches_failing_starter')
                else:
                    self.assertTrue(repaired['regression_comparable'])
                    self.assertEqual(repaired['regressed_cases'], [] if expected == 'passed' else first['score']['passed_cases'])
                self.assertIn('The current source is the tested candidate.', calls[1])
