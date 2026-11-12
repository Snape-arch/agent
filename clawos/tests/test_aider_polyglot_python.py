"""Verify scorer evidence distinguishes test failures from blocked imports."""

from pathlib import Path
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
