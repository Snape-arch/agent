#!/usr/bin/env python3
"""Run the frozen real-repository coding-context benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.coding_context_service import CodingContextService


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * quantile))
    return ordered[index]


def run(suite_path: Path, limit: int = 0) -> dict:
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    cases = list(suite.get("cases") or [])
    if limit:
        cases = cases[:max(1, int(limit))]
    service = CodingContextService()
    results = []
    durations = []
    reciprocal_ranks = []
    for case in cases:
        started = time.perf_counter()
        pack = service.build(REPO, case["objective"], token_budget=3000)
        duration = (time.perf_counter() - started) * 1000
        ranked = [item["path"] for item in pack["code_evidence"]]
        expected = case["expected_path"]
        rank = ranked.index(expected) + 1 if expected in ranked else 0
        passed = bool(rank and rank <= 10)
        durations.append(duration)
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        results.append({
            "id": case["id"],
            "expected_path": expected,
            "rank": rank,
            "passed": passed,
            "duration_ms": round(duration, 3),
            "context_digest": pack["context_digest"],
        })
    count = len(results)
    metrics = {
        "case_count": count,
        "passed_count": sum(int(item["passed"]) for item in results),
        "pass_rate": round(
            sum(int(item["passed"]) for item in results) / count, 6
        ) if count else 0.0,
        "mrr": round(statistics.mean(reciprocal_ranks), 6)
        if reciprocal_ranks else 0.0,
        "p95_latency_ms": round(percentile(durations, 0.95), 3),
    }
    thresholds = suite.get("thresholds") or {}
    passed = bool(
        metrics["pass_rate"] >= float(thresholds.get("pass_rate", 0.9))
        and metrics["mrr"] >= float(thresholds.get("mrr", 0.7))
        and metrics["p95_latency_ms"] <= float(
            thresholds.get("p95_latency_ms", 5000)
        )
    )
    return {
        "schema": suite["schema"],
        "name": suite["name"],
        "truth_boundary": suite["truth_boundary"],
        "passed": passed,
        "metrics": metrics,
        "thresholds": thresholds,
        "case_results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--suite",
        default=str(ROOT / "benchmarks" / "coding_repository_v1.json"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run(Path(args.suite), args.limit)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Coding repository benchmark: passed={report['passed']} "
            f"cases={report['metrics']['passed_count']}/{report['metrics']['case_count']} "
            f"mrr={report['metrics']['mrr']} "
            f"p95_ms={report['metrics']['p95_latency_ms']}"
        )
        for item in report["case_results"]:
            print(
                f"- {'PASS' if item['passed'] else 'FAIL'} {item['id']} "
                f"rank={item['rank']} {item['duration_ms']}ms"
            )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
