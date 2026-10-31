"""Scoped PostgreSQL/MinIO outage recovery with persistent Run/object evidence."""
from __future__ import annotations

import argparse
import time
from acceptance_support import authenticate, request, write_report
from disposable_compose import DisposableCompose


def health(url: str, expect_ok: bool, timeout: float = 90) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try: ok = bool(request(url, '/api/health', timeout=3).get('ok'))
        except (OSError, ValueError): ok = False
        if ok is expect_ok: return True
        time.sleep(min(2, max(0, deadline-time.monotonic())))
    return False


def exercise(stack: DisposableCompose, url: str, token: str) -> dict:
    if not health(url, True, 30): raise RuntimeError('healthy starting stack required')
    run = request(url, '/api/runs', {'name': 'fault-proof', 'params': {}}, token)['data']
    artifact = request(url, f"/api/runs/{run['id']}/artifacts", {'name': 'fault-object', 'type': 'json', 'content': {'proof': [1, 2, 3]}}, token)['data']
    evidence = []
    for index, service in enumerate(('postgres', 'minio'), 1):
        started = time.perf_counter(); observed = recovered = correct = False; error_type = None
        try:
            try:
                stack.run('stop', service)
                observed = health(url, False, 45)
            finally:
                # Even a failed outage assertion or stop invocation must attempt recovery.
                stack.run('start', service)
            recovered = health(url, True, 120)
            if recovered:
                request(url, f"/api/runs/{run['id']}/metrics", {'step': index, 'accuracy': .75}, token)
                stored = request(url, f"/api/runs/{run['id']}", token=token)['data']
                correct = [point['step'] for point in stored['metrics']] == list(range(1, index+1)) and any(
                    item['id'] == artifact['id'] and item['content'] == {'proof': [1, 2, 3]} for item in stored['artifacts'])
        except Exception as error: error_type = type(error).__name__
        evidence.append({'service': service, 'outageObserved': observed, 'recovered': recovered,
                         'dataVerified': correct, 'durationSeconds': round(time.perf_counter()-started, 3), 'errorType': error_type})
        if not recovered: break
    passed = len(evidence) == 2 and all(item['outageObserved'] and item['recovered'] and item['dataVerified'] and not item['errorType'] for item in evidence)
    return {'schemaVersion': 2, 'project': stack.project, 'evidence': evidence, 'passed': passed}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--project', required=True)
    parser.add_argument('--compose-file', action='append'); parser.add_argument('--url', default='http://127.0.0.1:8080')
    parser.add_argument('--token'); parser.add_argument('--output'); args = parser.parse_args()
    stack = DisposableCompose(args.project, args.compose_file)
    report = exercise(stack, args.url, authenticate(args.url, args.token))
    write_report(report, args.output)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__': main()
