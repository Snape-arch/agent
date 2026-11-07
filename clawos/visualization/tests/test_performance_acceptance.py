"""Regression evidence must be comparable and verify persisted data."""
import copy
import io
import json
import math
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import acceptance_support
import concurrent_sdk_benchmark as benchmark
import performance_gate
import soak_test


def report():
    return {'schemaVersion': 2, 'passed': True, 'samples': 24, 'verifiedRuns': 24, 'metricPoints': 240, 'spooledRuns': 0, 'failures': [],
            'environment': {'fingerprint': 'same-host', 'apiSourceDigest': 'a'*64, 'sdkDriverDigest': 'b'*64}, 'workload': {'runs': 24, 'rounds': 1, 'steps': 10},
            'p95RunMs': 100, 'p95DetailMs': 10}


class PerformanceAcceptanceTests(unittest.TestCase):
    def test_nearest_rank_p95_does_not_use_the_maximum_for_twenty_samples(self):
        self.assertEqual(acceptance_support.percentile(list(range(1, 21))), 19)
        with self.assertRaises(ValueError): acceptance_support.percentile([])

    def test_authentication_falls_back_to_login_after_bootstrap_conflict(self):
        conflict = urllib.error.HTTPError('http://fixture', 409, 'exists', {}, io.BytesIO())
        with patch.object(acceptance_support, 'request', side_effect=[conflict, {'data': {'token': 'test-token'}}]) as request:
            self.assertEqual(acceptance_support.authenticate('http://fixture'), 'test-token')
        self.assertEqual(request.call_args_list[1].args[1], '/api/auth/login')

    def test_p95_gate_rejects_incompatible_or_incorrect_results(self):
        baseline = report()
        self.assertTrue(performance_gate.compare(baseline, copy.deepcopy(baseline))['passed'])
        changes = [('p95RunMs', 136), ('p95DetailMs', 14), ('samples', 0), ('passed', False), ('spooledRuns', 1),
                   ('verifiedRuns', 23), ('metricPoints', 239), ('failures', ['timeout']), ('p95RunMs', math.nan)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                candidate = report(); candidate[key] = value
                self.assertFalse(performance_gate.compare(baseline, candidate)['passed'])
        candidate = report(); candidate['environment']['fingerprint'] = 'another-host'
        self.assertFalse(performance_gate.compare(baseline, candidate)['passed'])
        candidate = report(); candidate['workload']['steps'] = 20
        self.assertFalse(performance_gate.compare(baseline, candidate)['passed'])
        candidate = report(); candidate['environment']['sdkDriverDigest'] = 'c'*64
        self.assertFalse(performance_gate.compare(baseline, candidate)['passed'])
        candidate = report(); candidate['environment'].pop('apiSourceDigest')
        self.assertFalse(performance_gate.compare(baseline, candidate)['passed'])

    def test_sdk_success_alone_does_not_prove_ingestion_correctness(self):
        run = SimpleNamespace(id='run', log_metrics=Mock(), finish=Mock(), spool_path=Path('missing-test-spool'))
        with patch.object(benchmark, 'start_run', return_value=run), patch.object(benchmark, 'request', return_value={'data': {'status': 'completed', 'metrics': []}}):
            result = benchmark.execute(0, 2, 2, 'http://fixture', 'token')
        self.assertFalse(result['verified'])
        self.assertEqual(result['metricPoints'], 0)

    def test_soak_checks_all_task_pages_and_uses_summary_reads(self):
        run = {'id': 'run', 'status': 'completed', 'metrics': [{'accuracy': .8}], 'logs': ['soak']}
        paths = []

        def request(_, path, body=None, token=None):
            paths.append(path)
            if path == '/api/jobs': return {'data': {'runIds': ['worker-run']}}
            if path.startswith('/api/tasks?page=1'):
                return {'data': [], 'pagination': {'hasNext': True}}
            if path.startswith('/api/tasks?page=2'):
                return {'data': [{'payload': {'runId': 'worker-run'}, 'status': 'completed'}], 'pagination': {'hasNext': False}}
            if 'summary=1' in path: return {'data': [{'id': 'run'}]}
            return {'data': run}

        # One cycle lasts past the deadline; measurements still report real elapsed time.
        with patch.object(soak_test, 'request', side_effect=request), patch.object(soak_test.time, 'monotonic', side_effect=[0, .001, .1, .1, .1, .1, .1]), patch.object(soak_test.time, 'sleep'):
            result = soak_test.exercise('http://fixture', .001, 0, 'token', 1)
        self.assertTrue(result['passed'])
        self.assertTrue(any('page=2' in path for path in paths))
        self.assertIn('/api/runs?summary=1&page=1&pageSize=20', paths)

    def test_environment_fingerprint_includes_storage_and_transport(self):
        with patch.object(acceptance_support.subprocess, 'run', return_value=SimpleNamespace(stdout='revision')):
            one = acceptance_support.environment({'databaseKind': 'sqlite', 'objectStore': {'kind': 'local'}}, 'uvicorn')
            two = acceptance_support.environment({'databaseKind': 'postgresql', 'objectStore': {'kind': 's3'}}, 'nginx-uvicorn')
        self.assertNotEqual(one['fingerprint'], two['fingerprint'])
        self.assertNotIn('token', json.dumps(one))


if __name__ == '__main__': unittest.main()
