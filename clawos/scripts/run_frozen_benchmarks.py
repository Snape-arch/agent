#!/usr/bin/env python3
"""Run file-backed frozen ClawOS acceptance benchmarks."""

from __future__ import annotations

import argparse
import contextlib
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


def _run_tool(tool_name: str, args: dict) -> dict:
    from scripts import tool_runner

    started = time.perf_counter()
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
        os.chdir(REPO_ROOT)
        tool_runner.input_data = args or {}
        with contextlib.redirect_stdout(output):
            tool_runner.handlers[tool_name]()
        raw = output.getvalue().strip()
        data = json.loads(raw) if raw else {}
        ok = not (isinstance(data, dict) and data.get("error"))
        return {
            "ok": ok,
            "status": "success" if ok else "error",
            "tool": tool_name,
            "arguments": args,
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
    args = parser.parse_args()

    suite = load_suite_file(args.suite)
    db_path = args.db
    temp_dir = None
    if not db_path:
        temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(temp_dir.name) / "benchmark.db")

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
            _run_tool,
            thresholds=suite.get("thresholds") or {},
            created_by="frozen-runner",
        )
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    if args.json:
        print(json.dumps(run, ensure_ascii=False, indent=2))
    else:
        metrics = run["metrics"]
        print(
            f"Frozen benchmark: passed={bool(run['passed'])} "
            f"cases={metrics['passed_count']}/{metrics['case_count']} "
            f"pass_rate={metrics['pass_rate']} "
            f"p95_ms={metrics['p95_latency_ms']}"
        )
        for case in run["case_results"]:
            status = "PASS" if case["passed"] else "FAIL"
            print(f"- {status} {case['scenario']}::{case['name']} {case['latency_ms']}ms")

    return 0 if run["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
