"""Concurrent SDK ingestion with persisted-data verification and comparable p95."""
from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sdk'))
from clawvision import start_run  # noqa: E402
from acceptance_support import authenticate, environment, local_api, percentile, request, write_report  # noqa: E402


def execute(index: int, steps: int, batch: int, url: str, token: str | None) -> dict:
    started = time.perf_counter()
    run = start_run('concurrent-ingestion', {'worker': index, 'steps': steps}, name=f'load-{index}', base_url=url, api_token=token, buffer_size=batch)
    for step in range(steps):
        run.log_metrics(step, loss=1 / (step + 1), accuracy=min(.999, step / max(1, steps)), samples_per_second=1200 + index)
    run.finish('concurrent benchmark complete')
    duration = (time.perf_counter() - started) * 1000
    detail_started = time.perf_counter()
    stored = request(url, f'/api/runs/{run.id}', token=token)['data']
    valid = stored['status'] == 'completed' and [point['step'] for point in stored['metrics']] == list(range(steps))
    valid = valid and all(math.isclose(point['trainLoss'], 1 / (point['step'] + 1)) and
                          math.isclose(point['accuracy'], min(.999, point['step'] / steps)) for point in stored['metrics'])
    return {'runId': run.id, 'durationMs': duration, 'detailMs': (time.perf_counter() - detail_started) * 1000,
            'spooled': run.spool_path.exists(), 'verified': valid, 'metricPoints': len(stored['metrics'])}


def benchmark(url: str, token: str, workers: int, runs: int, steps: int, batch: int, rounds: int, warmup: int, transport: str, repository: Path) -> dict:
    health = request(url, '/api/health')
    for index in range(warmup):
        result = execute(-index-1, steps, batch, url, token)
        if result['spooled'] or not result['verified']: raise RuntimeError('warmup did not persist correct data')
    started = time.perf_counter(); successes = []; failures = []; round_times = []
    for round_index in range(rounds):
        round_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(execute, round_index * runs + index, steps, batch, url, token) for index in range(runs)]
            for future in as_completed(futures):
                try: successes.append(future.result())
                except Exception as error: failures.append(type(error).__name__)
        round_times.append(round((time.perf_counter() - round_started) * 1000, 3))
    elapsed = time.perf_counter() - started
    durations = [item['durationMs'] for item in successes]
    return {'schemaVersion': 2, 'environment': environment(health, transport, repository),
            'workload': {'workers': workers, 'runs': runs, 'steps': steps, 'batch': batch, 'rounds': rounds, 'warmup': warmup},
            'samples': len(durations), 'metricPoints': sum(item['metricPoints'] for item in successes),
            'elapsedSeconds': round(elapsed, 3), 'roundDurationsMs': round_times,
            'runsPerSecond': round(len(successes) / max(elapsed, .001), 3),
            'medianRunMs': round(statistics.median(durations), 3) if durations else None,
            'p95RunMs': round(percentile(durations), 3) if durations else None,
            'p95DetailMs': round(percentile([item['detailMs'] for item in successes]), 3) if successes else None,
            'spooledRuns': sum(item['spooled'] for item in successes), 'verifiedRuns': sum(item['verified'] for item in successes),
            'failures': failures, 'passed': len(successes) == runs * rounds and not failures and all(item['verified'] and not item['spooled'] for item in successes)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Existing disposable stack; omitted starts an isolated uvicorn fixture')
    parser.add_argument('--token'); parser.add_argument('--fixture-repo', type=Path, default=ROOT)
    parser.add_argument('--transport', default='nginx-uvicorn', help='External transport label used in environment matching')
    parser.add_argument('--workers', type=int, default=4); parser.add_argument('--runs', type=int, default=32)
    parser.add_argument('--steps', type=int, default=40); parser.add_argument('--batch', type=int, default=20)
    parser.add_argument('--rounds', type=int, default=3); parser.add_argument('--warmup', type=int, default=4)
    parser.add_argument('--output'); args = parser.parse_args()
    if min(args.workers, args.runs, args.steps, args.batch, args.rounds) < 1 or args.warmup < 0: parser.error('workloads must be positive; warmup must be nonnegative')
    fixture = nullcontext((args.url, None)) if args.url else local_api(args.fixture_repo)
    with fixture as (url, _):
        report = benchmark(url, authenticate(url, args.token if args.url else None, use_environment=bool(args.url)), args.workers, args.runs, args.steps, args.batch, args.rounds, args.warmup,
                           args.transport if args.url else 'uvicorn', args.fixture_repo)
    write_report(report, args.output)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__': main()
