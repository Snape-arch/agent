#!/usr/bin/env python3
"""Isolated-process audit for a candidate Skill definition."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills import skill_registry


def _check_case(case, result):
    expected = case.get("expected") or {}
    reasons = []
    if "ok" in expected and bool(result.get("ok")) != bool(expected["ok"]):
        reasons.append("unexpected ok flag")
    expected_steps = expected.get("step_count")
    if expected_steps is not None and int(result.get("steps") or 0) != int(expected_steps):
        reasons.append("unexpected step count")
    actual_tools = [item.get("tool") for item in result.get("outputs") or []]
    if expected.get("tools") and actual_tools != list(expected["tools"]):
        reasons.append("unexpected tool sequence")
    return not reasons, reasons


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    definition = payload.get("definition") or {}
    cases = payload.get("cases") or []
    validation = skill_registry.validate_skill_steps(definition.get("steps"))
    results = []
    for case in cases:
        # Fresh-agent audit is deliberately plan-only: it proves that an
        # independent interpreter resolves the candidate without inheriting
        # author context, while avoiding external side effects.
        result = skill_registry.execute_skill_definition(
            definition,
            params=case.get("params") or {},
            plan_only=True,
        )
        passed, reasons = _check_case(case, result)
        results.append({
            "name": case.get("name", "case"),
            "passed": bool(passed and not validation["errors"]),
            "reasons": list(validation["errors"]) + reasons,
            "result": result,
            "silent_bypass": not bool(result.get("outputs")),
            "audit_mode": "isolated_plan",
        })
    output = {
        "ok": bool(results) and all(item["passed"] for item in results),
        "validation": validation,
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
