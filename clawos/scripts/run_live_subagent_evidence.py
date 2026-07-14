#!/usr/bin/env python3
"""Run one real local-model Planner -> Executor -> Reviewer rework cycle."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.qwen import QwenProvider
from services.autonomous_subagent_service import AutonomousSubagentService, SubagentRoleSpec
from services.competition_evidence_service import sha256_file


ISSUE_FILES = (
    "clawos/reflection/perception.py",
    "clawos/reflection/analyzer.py",
    "clawos/reflection/memory_writer.py",
)


def inspect_repository(_name: str, arguments: dict, _context: dict) -> dict:
    query = str(arguments.get("query") or "bare except JSON parsing")
    findings = []
    for relative in ISSUE_FILES:
        path = REPO_ROOT / relative
        lines = path.read_text(encoding="utf-8").splitlines()
        hits = [
            {"line": index, "text": line.strip()}
            for index, line in enumerate(lines, 1)
            if "except:" in line or "json.loads" in line
        ]
        findings.append({"path": relative, "sha256": sha256_file(path), "hits": hits})
    return {"query": query, "repository": str(REPO_ROOT), "findings": findings}


async def run(out: Path) -> dict:
    repository_evidence = inspect_repository("inspect_repository", {"query": "bare except JSON parsing"}, {})
    service = AutonomousSubagentService(
        lambda _spec: QwenProvider({"timeout_s": 360}),
        checkpoint_root=out.parent / "checkpoints",
        max_concurrency=1,
    )
    roles = [
        SubagentRoleSpec(
            "planner",
            "Plan a minimal, testable repository repair from the supplied repository evidence. Do not invent files or results.",
            "Plan a safe repair for repeated bare-except JSON parsing in the reflection modules.",
            max_model_calls=2,
            max_tokens=1100,
            timeout_seconds=360,
        ),
        SubagentRoleSpec(
            "executor",
            "Act as the implementation owner. Propose exact file-level edits and tests from supplied evidence. If reviewer feedback exists, address every request and explain the changed V2.",
            "Produce the bounded implementation proposal and verification plan.",
            depends_on=["planner"],
            max_model_calls=2,
            max_tokens=1400,
            timeout_seconds=360,
        ),
        SubagentRoleSpec(
            "reviewer",
            "You are independent. On the initial review, reject V1 if the evidence has no reviewer_rework_request: require one shared parser helper, narrow JSON exceptions, and tests proving BaseException is not swallowed. On a re-review with that request present, release only if the executor addresses all three. Express rejection in hard_gate_failures and requires_human_approval=false; express release with an empty hard_gate_failures list.",
            "Gate the executor result against maintainability, exception safety and test evidence.",
            depends_on=["planner", "executor"],
            hard_gate=True,
            max_model_calls=2,
            max_tokens=1200,
            timeout_seconds=360,
        ),
    ]
    result = await service.run(
        "Repair repeated bare-except JSON parsing in the real ClawOS repository with one documented reviewer disagreement and final release.",
        roles,
        shared_evidence=[{
            "type": "repository_issue",
            "repository": "https://github.com/Snape-arch/agent",
            "files": list(ISSUE_FILES),
            "requirement": "Never swallow cancellation or system-exit style BaseException subclasses.",
            "inspection": repository_evidence,
        }],
        run_budget={"max_model_calls": 12, "max_tool_calls": 0, "max_tokens": 16000, "max_wall_ms": 900000},
        review_cycle={"executor_role": "executor", "reviewer_role": "reviewer", "max_rounds": 2},
        actor="competition-campaign",
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT.parent / "output" / "real-evidence" / "subagents" / "live-run.json")
    args = parser.parse_args()
    result = asyncio.run(run(args.out.resolve()))
    print(json.dumps({
        "run_id": result["run_id"],
        "status": result["status"],
        "model_calls": result["budget"]["model_calls"],
        "tool_calls": result["budget"]["tool_calls"],
        "tokens": result["budget"]["tokens"],
        "tokens_estimated": result["budget"]["estimated_tokens"],
        "duration_ms": result["duration_ms"],
        "disagreements": len(result["review_cycle"]["disagreements"]),
        "release": result["review_cycle"]["release"],
        "checkpoint": result["checkpoint"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" and result["review_cycle"]["release"].get("status") == "released" else 1


if __name__ == "__main__":
    raise SystemExit(main())
