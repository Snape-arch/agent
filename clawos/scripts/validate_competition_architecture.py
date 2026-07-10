#!/usr/bin/env python3
"""Offline architecture gate for the ClawOS competition profile."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def _check(name: str, passed: bool, weight: int, detail: str, *, required: bool = True) -> dict:
    return {
        "name": name,
        "passed": bool(passed),
        "weight": int(weight),
        "earned": int(weight) if passed else 0,
        "required": bool(required),
        "detail": detail,
    }


def validate() -> dict:
    import clawos_server as server
    from mtclaw.bridge_runner import NO_WRITE_ARGUMENTS, SAFE_ACTIONS, SAFE_TOOLS
    from mtclaw.prepare_runtime import prepare
    import tool_runner

    functions = [
        json.loads(line)
        for line in (ROOT / "functions.jsonl").read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    function_names = {item["name"] for item in functions}
    handler_names = set(tool_runner.handlers)
    provenance = (REPO_ROOT / "MTClaw-框架代码" / "UPSTREAM.md").read_text(encoding="utf-8")
    license_ok = (REPO_ROOT / "MTClaw-框架代码" / "LICENSE").is_file() and "MIT License" in (
        REPO_ROOT / "MTClaw-框架代码" / "LICENSE"
    ).read_text(encoding="utf-8")
    exact_upstream_recorded = "exact upstream GitHub URL and upstream commit SHA cannot be reconstructed" not in provenance
    competition = json.loads((ROOT / "config.competition.json").read_text(encoding="utf-8"))
    strategy = server.build_routing_strategy("请精读论文并校验引用")
    vertical = {
        "knowledge_search",
        "meeting_action_items",
        "paper_deep_read",
        "exam_practice_builder",
        "research_pdf",
        "paper_intelligence",
        "learning_workspace",
    }
    with tempfile.TemporaryDirectory() as td:
        runtime = prepare(Path(td))
        runtime_functions = [
            json.loads(line)
            for line in Path(runtime["functions"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    runtime_by_name = {item["name"]: item for item in runtime_functions}
    research_actions = set(
        runtime_by_name["research_pdf"]["parameters"]["properties"]["action"].get("enum") or []
    )
    learning_actions = set(
        runtime_by_name["learning_workspace"]["parameters"]["properties"]["action"].get("enum") or []
    )
    paper_actions = set(
        runtime_by_name["paper_intelligence"]["parameters"]["properties"]["action"].get("enum") or []
    )
    schemas_remove_write_args = all(
        not (set((runtime_by_name[name].get("parameters") or {}).get("properties") or {}) & denied)
        for name, denied in NO_WRITE_ARGUMENTS.items()
        if name in runtime_by_name
    )
    server_source = (ROOT / "clawos_server.py").read_text(encoding="utf-8")
    checks = [
        _check("vendored_license", license_ok, 5, "MIT license is retained with vendored MTClaw source"),
        _check("upstream_identity", exact_upstream_recorded, 5, "exact upstream URL/SHA recorded" if exact_upstream_recorded else "original upstream URL/SHA still needs owner confirmation"),
        _check("function_handler_parity", function_names == handler_names, 15, f"functions={len(function_names)} handlers={len(handler_names)}"),
        _check("vertical_mtclaw_surface", vertical <= SAFE_TOOLS, 15, f"vertical_safe_tools={len(vertical & SAFE_TOOLS)}/{len(vertical)}"),
        _check("action_level_guard", set(SAFE_ACTIONS["research_pdf"]) == research_actions and set(SAFE_ACTIONS["learning_workspace"]) == learning_actions and set(SAFE_ACTIONS["paper_intelligence"]) == paper_actions, 15, f"research={sorted(research_actions)} paper={sorted(paper_actions)} learning={sorted(learning_actions)}"),
        _check("least_privilege_schemas", schemas_remove_write_args, 10, "write-capable arguments are absent from generated MTClaw schemas"),
        _check("strict_competition_profile", competition["mtclaw"]["enabled"] is True and competition["mtclaw"]["fallback_on_error"] is False and competition.get("model_fallbacks") == [], 15, "MTClaw required, fallback disabled, no cloud model fallback"),
        _check("enforced_scenario_routing", strategy["mode"] == "enforced_scenario_routing" and strategy["scenario"] == "research" and "paper_deep_read" in strategy["allowed_tools"], 15, json.dumps(strategy, ensure_ascii=False)),
        _check("stream_mtclaw_route", "if g_mtclaw_adapter and g_mtclaw_adapter.enabled:" in server_source and "return sse_from_text(text, task_id=task_id, extra=raw[\"clawos\"])" in server_source, 5, "streaming requests use MTClaw then ClawOS SSE conversion"),
    ]
    score = sum(item["earned"] for item in checks)
    required_failures = [item["name"] for item in checks if item["required"] and not item["passed"]]
    return {
        "schema": "clawos.competition.architecture-gate.v1",
        "score": score,
        "max_score": sum(item["weight"] for item in checks),
        "competition_architecture_ready": score >= 90 and not [name for name in required_failures if name != "upstream_identity"],
        "enterprise_release_ready": not required_failures,
        "checks": checks,
        "blockers": required_failures,
        "external_acceptance_required": [
            "MTT AIBOOK Qwen/vLLM-MUSA latency, throughput, resource and offline evidence",
            "real model quality and tool-routing benchmark",
            "real audio ASR/meeting extraction benchmark",
            "paper claim-to-citation gold-set evaluation",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = validate()
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    return 1 if args.strict and not result["enterprise_release_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
