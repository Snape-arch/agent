#!/usr/bin/env python3
"""Collect one truthfully labelled local-model coding evaluation sample."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path


CLAWOS = Path(__file__).resolve().parents[1]
ROOT = CLAWOS.parent
if str(CLAWOS) not in sys.path:
    sys.path.insert(0, str(CLAWOS))

from agent_learning import FeedbackLearningService
from memoryos.memory_store import MemoryStore
from providers.qwen import QwenProvider
from services.agentic_coding_loop_service import AgenticCodingLoopService
from services.coding_trace_service import CodingTraceService
from services.coding_workflow_service import CodingWorkflowService
from services.coding_quality_service import CodingEvaluatorSummary
from services.task_service import TaskService


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def _fixture(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "evaluator@clawos.local")
    _git(repo, "config", "user.name", "ClawOS Evaluator")
    (repo / "AGENTS.md").write_text(
        "Fix only the requested bug. Run the repository test before finishing.\n",
        encoding="utf-8",
    )
    (repo / "maths.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (repo / "test_maths.py").write_text(
        "import unittest\nfrom maths import add\n\n"
        "class MathsTest(unittest.TestCase):\n"
        "    def test_add(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "controlled evaluator fixture")
    return repo


def _hidden_test(repo: Path, command: list[str] | None = None) -> dict:
    command = command or [
        sys.executable, "-c",
        "from maths import add; assert add(4, 7) == 11; "
        "assert add(-2, 5) == 3",
    ]
    result = subprocess.run(
        command,
        cwd=repo, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30,
    )
    return {
        "command_digest": _digest(command),
        "exit_code": result.returncode,
        "stdout_digest": _digest(result.stdout),
        "stderr_digest": _digest(result.stderr),
    }


def _prepare_repository(args, output: Path) -> tuple[Path, str, str, list[str]]:
    if not args.repo:
        return (
            _fixture(output),
            "controlled_repository_fixture",
            (
                "Fix maths.add so it performs addition. Inspect the file, make "
                "the smallest patch, run test_maths, then finish."
            ),
            [],
        )
    source = Path(args.repo).expanduser().resolve()
    if not (source / ".git").exists():
        raise ValueError("--repo must point to a Git repository")
    if not args.repository_id or not args.objective or not args.hidden_test_json:
        raise ValueError(
            "--repository-id, --objective, and --hidden-test-json are "
            "required with --repo"
        )
    try:
        hidden_command = json.loads(args.hidden_test_json)
    except json.JSONDecodeError as exc:
        raise ValueError("--hidden-test-json must be a JSON argv array") from exc
    if (
        not isinstance(hidden_command, list)
        or not hidden_command
        or not all(isinstance(item, str) and item for item in hidden_command)
    ):
        raise ValueError("--hidden-test-json must be a non-empty JSON argv array")
    repo = output / "repo"
    cloned = subprocess.run(
        [
            "git", "clone", "--local", "--no-hardlinks", "--no-tags",
            str(source), str(repo),
        ],
        cwd=output,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if cloned.returncode:
        raise RuntimeError(cloned.stderr.strip() or "isolated clone failed")
    _git(repo, "checkout", "--detach", "HEAD")
    return repo, "repository", str(args.objective), hidden_command


def _write_summary(output_root: Path) -> dict:
    reports = []
    for path in sorted(output_root.glob("*/report.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(item, dict):
                reports.append(item)
        except (OSError, json.JSONDecodeError):
            continue
    summary = CodingEvaluatorSummary.summarize(reports)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


async def _run(args) -> dict:
    run_id = f"local-eval-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    output = Path(args.output_root).expanduser().resolve() / run_id
    output.mkdir(parents=True)
    repo, repository_origin, objective, hidden_command = _prepare_repository(
        args, output
    )
    repository_id = (
        str(args.repository_id)
        if repository_origin == "repository"
        else "controlled-add-fixture"
    )
    store = MemoryStore(str(Path(args.database).expanduser().resolve()))
    tasks = TaskService(store)
    task = tasks.create(
        run_id,
        objective,
        source="codex_evaluator",
        metadata={
            "scenario": "coding",
            "user_text": objective,
            "user_context": {
                "evaluator_origin": "codex_evaluator",
                "evaluator_id": "codex-single-evaluator",
            },
            "environment_state": {
                "repository_origin": repository_origin,
                "repository_id": repository_id,
                "model": args.model,
            },
            "latency_budget_ms": 120_000,
        },
    )
    provider = QwenProvider({
        "base_url": args.base_url,
        "model": args.model,
        "requires_api_key": False,
        "timeout_s": args.timeout_seconds,
    })
    trace = CodingTraceService(output / "coding-trace.json")
    service = AgenticCodingLoopService(
        provider,
        workflow=CodingWorkflowService(artifact_root=output / "workflow"),
        trace=trace,
        learning_store=store,
    )
    started = time.perf_counter()
    try:
        result = await service.run(
            repo,
            objective,
            confirmed=True,
            task_id=str(task["id"]),
            session_id=run_id,
            actor_id="codex-single-evaluator",
            max_turns=args.max_turns,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "online_rl_claimed": False,
        }
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    hidden = _hidden_test(repo, hidden_command or None)
    patch = _git(repo, "diff", "--binary")
    patch_digest = _digest(patch)
    passed = bool(result.get("status") == "passed" and hidden["exit_code"] == 0)
    tasks.finish(
        task["id"], "succeeded" if passed else "failed",
        error="" if passed else str(result.get("error") or "evaluation failed"),
        result_payload={
            "agent_status": result.get("status"),
            "hidden_test": hidden,
            "patch_digest": patch_digest,
            "duration_ms": duration_ms,
        },
    )
    evidence = {
        "run_id": run_id,
        "task_id": task["id"],
        "model": args.model,
        "agent_status": result.get("status"),
        "hidden_test": hidden,
        "patch_digest": patch_digest,
        "trajectory_id": result.get("trajectory_id"),
        "duration_ms": duration_ms,
    }
    evidence_digest = _digest(evidence)
    feedback = FeedbackLearningService(store).record(
        task_id=task["id"],
        signal_type="score",
        value=1.0 if passed else 0.0,
        owner_id="codex-single-evaluator",
        reason_category="hidden_test_and_patch_review",
        metadata={
            "evaluator_origin": "codex_evaluator",
            "evidence_digest": evidence_digest,
            "evaluation_method": "hidden_tests_and_patch_review",
            "repository_origin": repository_origin,
            "repository_id": repository_id,
            "model": args.model,
            "run_id": run_id,
        },
        idempotency_key=f"{run_id}:codex-evaluation",
    )
    report = {
        "schema": "clawos.local-coding-evaluator.v1",
        "run_id": run_id,
        "task_id": task["id"],
        "sample_passed": passed,
        "model_execution_real": True,
        "repository_origin": repository_origin,
        "repository_id": repository_id,
        "issue_digest": _digest(objective),
        "hidden_test_digest": hidden["command_digest"],
        "evaluator_origin": "codex_evaluator",
        "evaluator_id": "codex-single-evaluator",
        "independent_human_user_claimed": False,
        "behavior_propensity_known": False,
        "eligible_for_ope": False,
        "eligible_for_reward_calibration": True,
        "agent_result": result,
        "hidden_test": hidden,
        "patch_digest": patch_digest,
        "duration_ms": duration_ms,
        "feedback_id": feedback["feedback"]["id"],
        "evidence_digest": evidence_digest,
        "online_rl_claimed": False,
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = _write_summary(output.parent)
    report["collection_summary"] = summary
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database", default=str(CLAWOS / "memoryos.db")
    )
    parser.add_argument(
        "--output-root", default=str(ROOT / "output" / "coding-evaluator")
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:11434/v1"
    )
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument(
        "--repo",
        default="",
        help="Optional real Git repository; evaluated in an isolated detached clone.",
    )
    parser.add_argument("--repository-id", default="")
    parser.add_argument("--objective", default="")
    parser.add_argument(
        "--hidden-test-json",
        default="",
        help='Hidden test argv as JSON, for example ["python","-m","pytest","-q"].',
    )
    parser.add_argument("--max-turns", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    if args.summary_only:
        print(json.dumps(
            _write_summary(Path(args.output_root).expanduser().resolve()),
            ensure_ascii=False, indent=2,
        ))
        return 0
    report = asyncio.run(_run(args))
    print(json.dumps({
        key: report.get(key) for key in (
            "run_id", "task_id", "sample_passed", "model_execution_real",
            "eligible_for_ope", "duration_ms", "evidence_digest",
        )
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
