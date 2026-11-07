"""Fail closed on p95 regressions or incomparable/incorrect benchmark evidence."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from acceptance_support import write_report


def compare(baseline: dict, candidate: dict, maximum_regression: float = .35) -> dict:
    reasons = []; checks = {}
    if not math.isfinite(maximum_regression) or not 0 <= maximum_regression <= 1:
        raise ValueError('maximum regression must be between zero and one')
    for name, report in (('baseline', baseline), ('candidate', candidate)):
        if report.get('schemaVersion') != 2 or report.get('passed') is not True: reasons.append(f'{name}: missing or failed correctness evidence')
        samples = report.get('samples', 0)
        if not isinstance(samples, int) or samples < 20: reasons.append(f'{name}: at least 20 measured samples required')
        workload = report.get('workload', {})
        expected = workload.get('runs', 0) * workload.get('rounds', 0)
        if samples != expected or report.get('verifiedRuns') != expected or report.get('metricPoints') != expected * workload.get('steps', 0) or report.get('spooledRuns') != 0 or report.get('failures') != []:
            reasons.append(f'{name}: incomplete persisted-data evidence')
        for key in ('apiSourceDigest', 'sdkDriverDigest'):
            value = report.get('environment', {}).get(key)
            if not isinstance(value, str) or len(value) != 64: reasons.append(f'{name}: missing source provenance ({key})')
    fingerprint = baseline.get('environment', {}).get('fingerprint')
    if not fingerprint or fingerprint != candidate.get('environment', {}).get('fingerprint'): reasons.append('environment fingerprints differ')
    sdk = baseline.get('environment', {}).get('sdkDriverDigest')
    if sdk != candidate.get('environment', {}).get('sdkDriverDigest'): reasons.append('SDK measurement drivers differ')
    if not baseline.get('workload') or baseline.get('workload') != candidate.get('workload'): reasons.append('workloads differ')
    for metric in ('p95RunMs', 'p95DetailMs'):
        before, after = baseline.get(metric), candidate.get(metric)
        valid = all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 for value in (before, after))
        if not valid: reasons.append(f'{metric}: finite positive values required'); continue
        checks[metric] = {'baselineMs': before, 'candidateMs': after, 'ratio': round(after / before, 4),
                          'limitMs': round(before * (1 + maximum_regression), 3)}
        if after > before * (1 + maximum_regression): reasons.append(f'{metric}: regression exceeds {maximum_regression:.0%}')
    return {'schemaVersion': 1, 'maximumRegression': maximum_regression, 'checks': checks, 'reasons': reasons, 'passed': not reasons}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path); parser.add_argument('--max-regression', type=float, default=.35)
    parser.add_argument('--output'); args = parser.parse_args()
    report = compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()), args.max_regression)
    write_report(report, args.output)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__': main()
