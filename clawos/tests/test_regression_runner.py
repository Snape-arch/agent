import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1]/'scripts/run_regression.py'
spec = importlib.util.spec_from_file_location('regression_runner', SCRIPT)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RegressionRunnerTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt', 'Windows path aliases')
    def test_short_path_aliases_share_ownership_and_locks(self):
        import ctypes
        from ctypes import wintypes
        from services.file_transactions import _file_lock
        from services.reliable_collaboration import ReliableCollaborationService
        with tempfile.TemporaryDirectory(prefix='clawos-alias-regression-') as folder:
            root=Path(folder).resolve()
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.GetShortPathNameW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,wintypes.DWORD]
            kernel.GetShortPathNameW.restype=wintypes.DWORD
            buffer=ctypes.create_unicode_buffer(32768)
            count=kernel.GetShortPathNameW(str(root),buffer,len(buffer))
            self.assertGreater(count,0)
            alias=Path(buffer.value)
            if os.path.normcase(str(alias))==os.path.normcase(str(root)):
                self.skipTest('This volume does not expose 8.3 aliases')
            service=ReliableCollaborationService(lambda spec:None,root=alias/'new-run-store')
            self.assertEqual(service.root,root/'new-run-store')
            service.root=alias/'reassigned-store'
            self.assertEqual(service.root,root/'reassigned-store')
            with _file_lock(root/'coordinator',timeout=0):
                with self.assertRaises(TimeoutError):
                    with _file_lock(alias/'coordinator',timeout=0): pass

    def test_module_shards_are_complete_disjoint_and_stable(self):
        cases = []
        for module in range(35):
            case = type('Case', (unittest.TestCase,), {'__module__': 'fixture_'+str(module), 'runTest': lambda self: None})
            cases.extend([case(), case()])
        suite = unittest.TestSuite([unittest.TestSuite(cases[:10]), unittest.TestSuite(cases[10:])])
        flat = list(runner.flatten(suite))
        groups = [[test for test in flat if runner.shard_for(test, 4)==index] for index in range(4)]
        self.assertEqual(sum(map(len, groups)), len(cases))
        self.assertEqual({id(test) for group in groups for test in group}, {id(test) for test in cases})
        self.assertTrue(all(groups))
        for first, second in zip(cases[::2], cases[1::2]):
            self.assertEqual(runner.shard_for(first, 4), runner.shard_for(second, 4))
        self.assertEqual([runner.shard_for(test, 4) for test in reversed(cases)],
                         list(reversed([runner.shard_for(test, 4) for test in cases])))

    def execute(self, suite):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder)/'summary.json'
            output = io.StringIO()
            with patch.dict(os.environ, {'CLAWOS_REGRESSION_REPORT': str(report), 'GITHUB_ACTIONS': 'true'}), \
                 patch.object(unittest.defaultTestLoader, 'discover', return_value=suite), \
                 redirect_stdout(output), redirect_stderr(output):
                code = runner.run_worker(Path(folder), argparse.Namespace(pattern='test*.py', shard_count=1, shard_index=0, verbose=False))
            return code, json.loads(report.read_text()), output.getvalue()

    def test_failures_errors_and_subtests_cannot_produce_green(self):
        def failure(self): self.fail('failure marker%\nnext line')
        def error(self): raise RuntimeError('error marker')
        def subtest(self):
            with self.subTest(value=1): self.assertEqual(1, 2)
        case = type('Fixture', (unittest.TestCase,), {'test_failure': failure, 'test_error': error, 'test_subtest': subtest})
        code, report, output = self.execute(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        self.assertEqual(code, 1)
        self.assertFalse(report['successful'])
        self.assertEqual((report['tests_run'], report['errors'], report['failures']), (3, 1, 2))
        self.assertEqual(output.count('::error title='), 3)
        self.assertIn('failure marker%25%0Anext line', output)

    def test_empty_selection_fails_instead_of_passing(self):
        code, report, _ = self.execute(unittest.TestSuite())
        self.assertEqual(code, 2)
        self.assertFalse(report['successful'])

    def test_invalid_shard_rejected_before_creating_workspace(self):
        for count, index in ((0, 0), (4, -1), (4, 4)):
            with self.subTest(count=count, index=index):
                result = subprocess.run([sys.executable, str(SCRIPT), '--shard-count', str(count), '--shard-index', str(index)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('Isolated regression workspace:', result.stdout)
