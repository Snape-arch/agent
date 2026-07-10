#!/usr/bin/env python3
"""Run the offline MTClaw vertical routing contract benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[index]


def run(dataset: Path) -> dict:
    import clawos_server as server
    from mtclaw.bridge_runner import SAFE_TOOLS

    payload = json.loads(dataset.read_text(encoding="utf-8"))
    results = []
    latencies = []
    for case in payload.get("cases", []):
        started = time.perf_counter()
        strategy = server.build_routing_strategy(case["prompt"])
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        latencies.append(latency_ms)
        required_tool = case["required_tool"]
        checks = {
            "scenario": strategy["scenario"] == case["scenario"],
            "tool_allowed_by_scenario": required_tool in strategy["allowed_tools"],
            "tool_exposed_by_mtclaw": required_tool in SAFE_TOOLS,
            "enforced_mode": strategy["mode"] == "enforced_scenario_routing",
        }
        results.append({
            "id": case["id"],
            "passed": all(checks.values()),
            "checks": checks,
            "strategy": strategy,
            "latency_ms": latency_ms,
        })
    passed = sum(1 for item in results if item["passed"])
    return {
        "schema": payload.get("schema"),
        "passed": passed == len(results) and bool(results),
        "passed_count": passed,
        "failed_count": len(results) - passed,
        "case_count": len(results),
        "pass_rate": round(passed / max(1, len(results)), 4),
        "latency": {
            "mean_ms": round(statistics.mean(latencies), 3) if latencies else 0.0,
            "p95_ms": round(percentile(latencies, 0.95), 3),
        },
        "results": results,
        "scope": "offline contract evidence; real model/tool quality and MTT hardware remain external acceptance",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "benchmarks" / "mtclaw_vertical_acceptance_v1.json"))
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    result = run(Path(args.dataset))
    print(
        f"MTClaw vertical acceptance: passed={result['passed']} "
        f"cases={result['passed_count']}/{result['case_count']} "
        f"pass_rate={result['pass_rate']} p95_ms={result['latency']['p95_ms']}"
    )
    for item in result["results"]:
        print(f"- {'PASS' if item['passed'] else 'FAIL'} {item['id']} {item['latency_ms']}ms")
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
