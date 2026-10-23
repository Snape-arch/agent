#!/usr/bin/env python3
"""Evaluate model responses against frozen ClawOS acceptance tasks."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from providers import create_model_provider
from scenario_benchmarks import DEFAULT_SUITE_FILE, FrozenScenarioBenchmark, load_suite_file
from scripts.run_frozen_benchmarks import _run_tool


def _provider_config(args: argparse.Namespace) -> dict[str, Any]:
    provider = args.provider or os.environ.get("MODEL_PROVIDER") or "mock"
    provider_key = str(provider or "").lower()
    if provider_key == "qwen":
        model = args.model or os.environ.get("QWEN_MODEL") or ""
        base_url = args.base_url or os.environ.get("QWEN_BASE_URL") or ""
        api_key = ""
    else:
        model = args.model or os.environ.get("MODEL_NAME") or ("mock-evaluator" if provider_key == "mock" else "")
        base_url = args.base_url or os.environ.get("MODEL_BASE_URL") or ""
        api_key = os.environ.get(args.api_key_env or "MODEL_API_KEY", "")
    cfg = {
        "provider": provider,
        "timeout_s": args.timeout_s,
    }
    if model:
        cfg["model"] = model
    if base_url:
        cfg["base_url"] = base_url
    if api_key:
        cfg["api_key"] = api_key
    if provider_key == "qwen":
        cfg["requires_api_key"] = False
    if provider_key == "mock":
        cfg["mock_response"] = args.mock_response or (
            "PASS: meeting research learning git template tool acceptance case "
            "reviewed with sufficient tool evidence."
        )
    return cfg


def _case_prompt(case: dict[str, Any], result: dict[str, Any]) -> list[dict[str, Any]]:
    expected = case.get("expected") or {}
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    compact = {
        "case": case.get("name"),
        "scenario": case.get("scenario"),
        "tool": case.get("tool"),
        "passed": bool(result.get("passed", result.get("ok"))),
        "expected_tool": expected.get("tool"),
        "expected_paths": expected.get("data_paths") or [],
        "data_keys": sorted(data.keys())[:20],
        "error": result.get("error") or "",
    }
    return [
        {
            "role": "system",
            "content": (
                "You are a ClawOS acceptance evaluator. Treat the supplied JSON as the authoritative "
                "frozen benchmark result. If passed is true and error is empty, return PASS and state "
                "that the tool evidence is sufficient; otherwise return FAIL and name the error. "
                "Include the exact case, scenario, and tool values in the concise verdict. Do not invent facts."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(compact, ensure_ascii=False),
        },
    ]


def _score_case(case_result: dict[str, Any], model_result: dict[str, Any]) -> dict[str, Any]:
    content = str(model_result.get("content") or "")
    score = 0
    reasons = []
    if case_result.get("passed"):
        score += 2
        reasons.append("tool_case_passed")
    if model_result.get("ok"):
        score += 1
        reasons.append("provider_ok")
    if content.strip():
        score += 1
        reasons.append("non_empty_answer")
    tool = str(case_result.get("tool") or "")
    scenario = str(case_result.get("scenario") or "")
    if tool and tool in content or scenario and scenario in content:
        score += 1
        reasons.append("mentions_context")
    return {
        "score": score,
        "max_score": 5,
        "reasons": reasons,
    }


async def _evaluate_cases(provider: Any, case_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evaluated = []
    for case_result in case_results:
        model_result = await provider.complete(_case_prompt(case_result, case_result), {"temperature": 0.0})
        score = _score_case(case_result, model_result)
        evaluated.append({
            "name": case_result.get("name"),
            "scenario": case_result.get("scenario"),
            "tool": case_result.get("tool"),
            "benchmark_passed": bool(case_result.get("passed")),
            "model_result": {
                "ok": bool(model_result.get("ok")),
                "provider": model_result.get("provider"),
                "model": model_result.get("model"),
                "content": model_result.get("content", ""),
                "usage": model_result.get("usage") or {},
                "duration_ms": model_result.get("duration_ms", 0),
                "error": model_result.get("error", ""),
            },
            "score": score,
        })
    return evaluated


def _run_suite(suite_path: str, limit: int = 0) -> dict[str, Any]:
    suite = load_suite_file(suite_path)
    if limit > 0:
        suite = {**suite, "cases": suite["cases"][:limit]}
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    variables = {
        "tmpdir": str(temp_path),
        "repo_root": str(REPO_ROOT),
        "clawos_root": str(ROOT),
    }
    old_memory_db = os.environ.get("CLAWOS_MEMORY_DB")
    os.environ["CLAWOS_MEMORY_DB"] = str(temp_path / "model_acceptance.db")
    try:
        benchmark = FrozenScenarioBenchmark(MemoryStore(os.environ["CLAWOS_MEMORY_DB"]))
        created = None
        if limit <= 0:
            created = next((item for item in benchmark.list_suites() if item["name"] == suite["name"]), None)
        if created is None:
            suite_name = suite["name"] if limit <= 0 else f"{suite['name']}-model-acceptance-{limit}"
            created = benchmark.create_suite(
                suite_name,
                suite["cases"],
                description=suite.get("description", ""),
                created_by="model-acceptance",
            )
        return benchmark.run_suite(
            created["id"],
            lambda tool, tool_args: _run_tool(tool, tool_args, variables),
            thresholds=suite.get("thresholds") or {},
            created_by="model-acceptance",
        )
    finally:
        if old_memory_db is None:
            os.environ.pop("CLAWOS_MEMORY_DB", None)
        else:
            os.environ["CLAWOS_MEMORY_DB"] = old_memory_db
        temp_dir.cleanup()


async def _main_async(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    run = _run_suite(args.suite, args.limit)
    provider = create_model_provider(_provider_config(args))
    case_evaluations = await _evaluate_cases(provider, run["case_results"])
    total_score = sum(item["score"]["score"] for item in case_evaluations)
    max_score = sum(item["score"]["max_score"] for item in case_evaluations) or 1
    provider_errors = {}
    for item in case_evaluations:
        error = item["model_result"].get("error") or ""
        if error:
            provider_errors[error] = provider_errors.get(error, 0) + 1
    return {
        "ok": bool(run["passed"]) and total_score == max_score,
        "provider": getattr(provider, "name", ""),
        "model": getattr(provider, "model", ""),
        "configured": bool(provider.is_configured()) if hasattr(provider, "is_configured") else True,
        "benchmark": run["metrics"],
        "benchmark_cases": [{key: item.get(key) for key in
            ("name", "scenario", "tool", "passed", "latency_ms", "reasons")}
            for item in run["case_results"]],
        "evaluation": {
            "cases": len(case_evaluations),
            "total_score": total_score,
            "max_score": max_score,
            "score_rate": round(total_score / max_score, 4),
            "provider_errors": provider_errors,
        },
        "case_evaluations": case_evaluations,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default=str(DEFAULT_SUITE_FILE))
    parser.add_argument("--provider", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key-env", default="MODEL_API_KEY")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--mock-response", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(_main_async(args))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        evaluation = result["evaluation"]
        benchmark = result["benchmark"]
        failed_count = benchmark["case_count"] - benchmark["passed_count"]
        print(
            f"Model acceptance: ok={result['ok']} provider={result['provider']} "
            f"model={result['model']} configured={result['configured']} "
            f"passed_count={benchmark['passed_count']} failed_count={failed_count} "
            f"score={evaluation['total_score']}/{evaluation['max_score']} "
            f"rate={evaluation['score_rate']}"
        )
        if evaluation["provider_errors"]:
            print(f"Provider errors: {json.dumps(evaluation['provider_errors'], ensure_ascii=False)}")
        for case in result['benchmark_cases']:
            if not case['passed']:
                print(f"- FAIL {case['scenario']}::{case['name']} tool={case['tool']} "
                      f"latency_ms={case['latency_ms']} reasons={json.dumps(case['reasons'], ensure_ascii=True)}")

    return 0 if result['ok'] else 1


if __name__ == "__main__":
    raise SystemExit(main())
