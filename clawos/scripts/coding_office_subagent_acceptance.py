#!/usr/bin/env python3
"""Deterministic and optional real-model acceptance for coding, office and subagents."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.qwen import QwenProvider
from services.autonomous_subagent_service import AutonomousSubagentService, SubagentRoleSpec
from services.coding_workflow_service import CodingWorkflowService
from services.office_productivity_service import OfficeProductivityService


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True)


class DeterministicProvider:
    async def complete(self, messages, options=None, **_kwargs):
        content = json.dumps({
            "summary": "Evidence reviewed; bounded workflow is ready for human release approval.",
            "claims": ["The role completed its isolated assignment."],
            "evidence": ["checkpoint and trace hashes"],
            "artifacts": [],
            "proposed_actions": [],
            "confidence": 0.93,
            "open_risks": [],
            "hard_gate_failures": [],
            "requires_human_approval": False,
        })
        return {"ok": True, "provider": "deterministic", "model": "acceptance-fixture", "content": content, "raw": {"choices": [{"message": {"content": content}}]}, "usage": {"total_tokens": 32}}


async def _subagent_acceptance(root: Path, live_model: bool) -> dict:
    factory = (lambda _spec: QwenProvider({"timeout_s": 240})) if live_model else (lambda _spec: DeterministicProvider())
    service = AutonomousSubagentService(factory, checkpoint_root=root / "subagents", max_concurrency=2)
    roles = [
        SubagentRoleSpec("planner", "Produce an evidence-based release plan.", "Check scope and rollback", max_tokens=700, timeout_seconds=240),
        SubagentRoleSpec("reviewer", "Act as an independent enterprise release gate.", "Review the planner output; return strict JSON", depends_on=["planner"], hard_gate=True, max_tokens=700, timeout_seconds=240),
    ]
    result = await service.run("Accept coding and office workflow for a human-approved release", roles, run_budget={"max_model_calls": 4, "max_tool_calls": 0, "max_tokens": 6000, "max_wall_ms": 480000})
    traces = [trace for item in result["results"].values() for trace in item["trace"] if trace["type"] == "model"]
    return {
        "passed": result["status"] == "passed",
        "execution_completed": len(result["results"]) == len(roles) and len(traces) >= len(roles),
        "status": result["status"],
        "execution_mode": result["execution_mode"],
        "roles_completed": len(result["results"]),
        "providers": sorted({item.get("provider") for item in traces}),
        "models": sorted({item.get("model") for item in traces}),
        "model_calls": result["budget"]["model_calls"],
        "checkpoint_exists": Path(result["checkpoint"]).is_file(),
        "average_confidence": result["arbitration"]["average_confidence"],
        "arbitration": result["arbitration"],
        "role_summaries": {key: (value.get("output") or {}).get("summary", "") for key, value in result["results"].items()},
        "duration_ms": result["duration_ms"],
    }


def accept(live_model: bool = False) -> dict:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="clawos-accept-") as td:
        root = Path(td)
        repo = root / "repo"
        repo.mkdir()
        _run("git", "init", cwd=repo)
        _run("git", "config", "user.email", "acceptance@example.invalid", cwd=repo)
        _run("git", "config", "user.name", "ClawOS Acceptance", cwd=repo)
        (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_calc.py").write_text("import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")
        _run("git", "add", ".", cwd=repo)
        _run("git", "commit", "-m", "acceptance base", cwd=repo)
        coding = CodingWorkflowService(artifact_root=root / "coding").execute(
            repo,
            "Repair arithmetic with a bounded retry",
            [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return 0"}],
            [[sys.executable, "-m", "unittest", "test_calc.py"]],
            confirmed=True,
            repair_rounds=[[{"path": "calc.py", "operation": "replace", "old_text": "return 0", "new_text": "return a + b"}]],
            max_rounds=2,
        )
        coding_ok = coding["status"] == "passed" and len(coding["rounds"]) == 2 and Path(coding["diff_path"]).is_file()

        office_root = root / "office"
        office = OfficeProductivityService(allowed_roots=[office_root])
        package = office.meeting_package({
            "title": "Enterprise Acceptance",
            "summary": "Coding and office gates were exercised.",
            "decisions": ["Keep external sends human-confirmed"],
            "risks": ["Live tenant credentials are an external gate"],
            "actions": [{"owner": "Reviewer", "description": "Approve release", "due_date": "2026-07-12", "evidence": "acceptance-run"}],
        }, office_root / "package", recipients=["reviewer@example.invalid"], confirmed=True)
        office_formats = sorted({item["format"] for item in package["artifacts"]})
        office_ok = package["quality_gate"] == "pass" and set(["docx", "pdf", "xlsx", "md", "eml", "ics"]) <= set(office_formats)
        subagents = asyncio.run(_subagent_acceptance(root, live_model))

        checks = {
            "coding_retry_test_review_checkpoint": coding_ok,
            "office_six_format_reopen_gate": office_ok,
            "autonomous_isolated_dag_checkpoint": subagents["execution_completed"] and subagents["checkpoint_exists"],
        }
        return {
            "schema": "clawos.coding-office-subagent-acceptance.v1",
            "live_model": live_model,
            "ok": all(checks.values()),
            "checks": checks,
            "coding": {"status": coding["status"], "rounds": len(coding["rounds"]), "restored_on_failure": coding["restored_on_failure"], "human_review_required": coding["human_review_required"]},
            "office": {"quality_gate": package["quality_gate"], "formats": office_formats, "artifact_count": len(package["artifacts"])},
            "subagents": subagents,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-model", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    result = accept(args.live_model)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
