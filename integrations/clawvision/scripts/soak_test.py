"""API/data/queue soak; 60 minutes by default, isolated uvicorn when URL is absent."""
from __future__ import annotations

import argparse
import math
import time
from contextlib import nullcontext
from acceptance_support import authenticate, environment, local_api, local_worker, percentile, request, write_report


def exercise(url: str, minutes: float, interval: float, token: str, queue_every: int = 20) -> dict:
    started = time.monotonic(); deadline = started + minutes * 60
    cycles = completed = 0; latencies = []; failures = []; queued_ids = []; task_ids = []
    while time.monotonic() < deadline:
        cycle_started = time.perf_counter()
        try:
            run = request(url, '/api/runs', {'name': f'soak-{cycles}', 'params': {'seed': cycles}, 'source': 'soak'}, token)['data']
            request(url, f"/api/runs/{run['id']}/batch", {'metrics': [{'step': 1, 'trainLoss': .5, 'accuracy': .8}], 'events': [{'level': 'info', 'message': 'soak'}]}, token)
            request(url, f"/api/runs/{run['id']}/finish", {'message': 'done'}, token)
            stored = request(url, f"/api/runs/{run['id']}", token=token)['data']
            if stored['status'] != 'completed' or len(stored['metrics']) != 1 or stored['metrics'][0]['accuracy'] != .8 or 'soak' not in stored['logs']:
                raise AssertionError('soak Run data mismatch')
            summaries = request(url, '/api/runs?summary=1&page=1&pageSize=20', token=token)['data']
            if len(summaries) > 20 or any('metrics' in item for item in summaries): raise AssertionError('summary read returned histories')
            if queue_every and cycles % queue_every == 0:
                job = request(url, '/api/jobs', {'name': 'soak-worker', 'kind': 'single', 'trainingProvider': 'simulator', 'configs': [{'epochs': 1}]}, token)['data']
                queued_ids.extend(job['runIds'])
            completed += 1
        except Exception as error:
            if len(failures) < 20: failures.append({'cycle': cycles, 'type': type(error).__name__})
        latencies.append((time.perf_counter() - cycle_started) * 1000)
        cycles += 1
        time.sleep(min(interval, max(0, deadline-time.monotonic())))
    measured = time.monotonic() - started
    # Drain only tasks created by this run, rather than accepting a truncated
    # global task page or including unrelated workloads in the result.
    queue_completed = 0
    drain_deadline = time.monotonic() + 45
    pending = set(queued_ids)
    while pending and time.monotonic() < drain_deadline:
        for run_id in list(pending):
            run = request(url, f'/api/runs/{run_id}', token=token)['data']
            if run['status'] == 'completed' and len(run['metrics']) == 1:
                queue_completed += 1; pending.remove(run_id)
            elif run['status'] in ('failed', 'stopped'):
                pending.remove(run_id); failures.append({'type': 'WorkerRunFailed'})
        if pending: time.sleep(.2)
    # Task endpoint is bounded; look up all pages and retain this run's resources.
    for page in range(1, 10000):
        response = request(url, f'/api/tasks?page={page}&pageSize=500', token=token)
        task_ids.extend(item for item in response['data'] if item['payload'].get('runId') in queued_ids)
        if not response.get('pagination', {}).get('hasNext', False): break
    incomplete = sum(item['status'] != 'completed' for item in task_ids)
    active = sum(item['status'] in ('queued', 'leased', 'running', 'retry') for item in task_ids)
    verified_tasks = len(task_ids) == len(queued_ids) and incomplete == 0
    return {'durationMinutes': minutes, 'measuredSeconds': round(measured, 3), 'cycles': cycles, 'completedRuns': completed,
            'failures': cycles-completed, 'failureEvidence': failures, 'queuedRuns': len(queued_ids), 'completedQueuedRuns': queue_completed,
            'activeTasks': active, 'nonSuccessfulTasks': incomplete, 'queueVerified': verified_tasks, 'samples': len(latencies),
            'p95CycleMs': round(percentile(latencies), 3) if latencies else None,
            'maxLatencyMs': round(max(latencies, default=0), 3),
            'passed': cycles > 0 and measured >= minutes*60 and not failures and completed == cycles and queue_completed == len(queued_ids) and verified_tasks}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument('--minutes', type=float, default=60)
    parser.add_argument('--interval', type=float, default=.25); parser.add_argument('--url'); parser.add_argument('--token')
    parser.add_argument('--queue-every', type=int, default=20, help='0 disables standalone Worker exercise')
    parser.add_argument('--output'); args = parser.parse_args()
    if not math.isfinite(args.minutes) or args.minutes <= 0 or not math.isfinite(args.interval) or args.interval < 0 or args.queue_every < 0:
        parser.error('minutes must be finite and positive; interval and queue frequency nonnegative')
    with (nullcontext((args.url, None)) if args.url else local_api()) as (url, root):
        with (local_worker(root) if root and args.queue_every else nullcontext()):
            token = authenticate(url, args.token if args.url else None, use_environment=bool(args.url))
            report = exercise(url, args.minutes, args.interval, token, args.queue_every)
            report['schemaVersion'] = 2
            report['environment'] = environment(request(url, '/api/health'), 'nginx-uvicorn' if args.url else 'uvicorn')
    write_report(report, args.output)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__': main()
