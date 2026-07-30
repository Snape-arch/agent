#!/usr/bin/env python3
"""Run file-backed frozen ClawOS acceptance benchmarks."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from scenario_benchmarks import DEFAULT_SUITE_FILE, FrozenScenarioBenchmark, load_suite_file


def _materialize(value, variables: dict[str, str]):
    if isinstance(value, str):
        result = value
        for key, replacement in variables.items():
            result = result.replace("${" + key + "}", replacement)
        return result
    if isinstance(value, list):
        return [_materialize(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: _materialize(item, variables) for key, item in value.items()}
    return value


def _write_fixtures(fixtures: list[dict], variables: dict[str, str]) -> None:
    for fixture in fixtures or []:
        path = Path(_materialize(fixture.get("path", ""), variables))
        path.parent.mkdir(parents=True, exist_ok=True)
        if "bytes_hex" in fixture:
            path.write_bytes(bytes.fromhex(str(fixture["bytes_hex"])))
        else:
            path.write_text(str(fixture.get("content", "")), encoding="utf-8")


def _run_tool(
    tool_name: str,
    args: dict,
    variables: dict[str, str] | None = None,
    target_type: str = "",
    policy: dict | None = None,
) -> dict:
    from scripts import tool_runner

    variables = variables or {}
    started = time.perf_counter()
    policy = dict(policy or {})
    if target_type == "tool_routing_policy":
        allowed = {str(item) for item in policy.get("allowed_tools") or []}
        denied = {str(item) for item in policy.get("deny_tools") or []}
        if tool_name in denied or (allowed and tool_name not in allowed):
            return {
                "ok": False,
                "status": "blocked_by_candidate_policy",
                "tool": tool_name,
                "arguments": args,
                "data": None,
                "error": f"tool blocked by evaluated policy: {tool_name}",
                "duration_ms": 0,
            }
    if tool_name not in tool_runner.handlers:
        return {
            "ok": False,
            "status": "error",
            "tool": tool_name,
            "arguments": args,
            "data": None,
            "error": f"unknown tool: {tool_name}",
            "duration_ms": 0,
        }

    old_input = tool_runner.input_data
    old_cwd = Path.cwd()
    output = io.StringIO()
    try:
        raw_args = dict(args or {})
        fixtures = raw_args.pop("_benchmark_fixtures", [])
        _write_fixtures(fixtures, variables)
        materialized_args = _materialize(raw_args, variables)
        os.chdir(REPO_ROOT)
        tool_runner.input_data = materialized_args
        with contextlib.redirect_stdout(output):
            tool_runner.handlers[tool_name]()
        raw = output.getvalue().strip()
        data = json.loads(raw) if raw else {}
        ok = not (isinstance(data, dict) and data.get("error"))
        return {
            "ok": ok,
            "status": "success" if ok else "error",
            "tool": tool_name,
            "arguments": materialized_args,
            "data": data,
            "error": "" if ok else str(data.get("error", "tool error")),
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "tool": tool_name,
            "arguments": args,
            "data": None,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    finally:
        tool_runner.input_data = old_input
        os.chdir(old_cwd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default=str(DEFAULT_SUITE_FILE))
    parser.add_argument("--db", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--target-type", default="")
    parser.add_argument("--policy-json", default="{}")
    args = parser.parse_args()
    try:
        policy = json.loads(args.policy_json)
    except json.JSONDecodeError as exc:
        parser.error(f"--policy-json must contain valid JSON: {exc}")
    if not isinstance(policy, dict):
        parser.error("--policy-json must contain a JSON object")

    suite = load_suite_file(args.suite)
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    db_path = args.db or str(temp_path / "benchmark.db")
    variables = {
        "tmpdir": str(temp_path),
        "repo_root": str(REPO_ROOT),
        "clawos_root": str(ROOT),
    }
    old_memory_db = os.environ.get("CLAWOS_MEMORY_DB")
    os.environ["CLAWOS_MEMORY_DB"] = db_path

    try:
        benchmark = FrozenScenarioBenchmark(MemoryStore(db_path))
        created = next(
            (item for item in benchmark.list_suites() if item["name"] == suite["name"]),
            None,
        )
        if created is None:
            created = benchmark.create_suite(
                suite["name"],
                suite["cases"],
                description=suite["description"],
                created_by="frozen-runner",
            )
        run = benchmark.run_suite(
            created["id"],
            lambda tool, tool_args: _run_tool(
                tool,
                tool_args,
                variables,
                target_type=args.target_type,
                policy=policy,
            ),
            thresholds=suite.get("thresholds") or {},
            created_by="frozen-runner",
        )
        policy_trace = {
            "target_type": args.target_type,
            "policy_digest": hashlib.sha256(
                json.dumps(policy, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "materialized": bool(args.target_type),
            "routing_enforced": args.target_type == "tool_routing_policy",
            "case_count": len(run.get("case_results") or []),
        }
        policy_trace["trace_digest"] = hashlib.sha256(
            json.dumps(policy_trace, sort_keys=True).encode("utf-8")
        ).hexdigest()
        run["policy_execution"] = policy_trace
    finally:
        if old_memory_db is None:
            os.environ.pop("CLAWOS_MEMORY_DB", None)
        else:
            os.environ["CLAWOS_MEMORY_DB"] = old_memory_db
        temp_dir.cleanup()

    if args.json:
        print(json.dumps(run, ensure_ascii=False, indent=2))
    else:
        metrics = run["metrics"]
        failed_count = metrics["case_count"] - metrics["passed_count"]
        print(
            f"Frozen benchmark: passed={bool(run['passed'])} "
            f"passed_count={metrics['passed_count']} "
            f"failed_count={failed_count} "
            f"cases={metrics['passed_count']}/{metrics['case_count']} "
            f"pass_rate={metrics['pass_rate']} "
            f"p95_ms={metrics['p95_latency_ms']}"
        )
        for case in run["case_results"]:
            status = "PASS" if case["passed"] else "FAIL"
            reasons = ", ".join(case.get("reasons") or [])
            reason_text = f" reason={reasons}" if reasons else ""
            print(f"- {status} {case['scenario']}::{case['name']} {case['latency_ms']}ms{reason_text}")

    return 0 if run["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
