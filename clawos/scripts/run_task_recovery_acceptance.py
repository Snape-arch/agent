"""Crash one process and recover the same durable task in a fresh process."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from services.task_service import TaskService


def phase_start(database: Path, repository: Path, state_path: Path) -> None:
    store = MemoryStore(str(database))
    checkpoint = repository / "progress-checkpoint.json"
    checkpoint.write_text(json.dumps({
        "schema": "clawos.long-task-checkpoint.v1",
        "completed_units": 2, "total_units": 5,
    }), encoding="utf-8")
    task = store.start_task(
        "recovery-acceptance", "Long repository analysis",
        source="process-restart-acceptance", status="running",
        metadata={
            "worker_action": "long_task", "duration_ms": 50,
            "repo_path": str(repository), "checkpoint_path": str(checkpoint),
            "completed_units": 2, "total_units": 5,
        },
    )
    store.add_task_event(
        task["id"], "run.checkpoint", "Progress persisted before crash",
        data={"checkpoint": {"uri": str(checkpoint), "digest": "acceptance"}},
    )
    state_path.write_text(json.dumps({"task_id": task["id"]}), encoding="utf-8")
    os._exit(73)


def phase_resume(database: Path, state_path: Path, report_path: Path) -> int:
    store = MemoryStore(str(database))
    original_id = int(json.loads(state_path.read_text(encoding="utf-8"))["task_id"])
    recovery = store.recover_interrupted_tasks(
        actor_id="fresh-process", create_retries=True
    )
    worker = asyncio.run(TaskService(store).run_worker_once(
        worker_id="fresh-process-worker", max_attempts=1
    ))
    original = store.get_task(original_id)
    retry_id = int((recovery.get("retry_tasks") or [{}])[0].get("id") or 0)
    retry = store.get_task(retry_id) if retry_id else {}
    original_metadata = (original.get("task") or {}).get("metadata") or {}
    retry_metadata = (retry.get("task") or {}).get("metadata") or {}
    checks = {
        "fresh_process_recovered_original": original_id in recovery.get("recovered", []),
        "original_marked_interrupted": (
            (original.get("task") or {}).get("status") == "interrupted"
        ),
        "retry_created": retry_id > 0,
        "checkpoint_reference_preserved": (
            original_metadata.get("checkpoint_path")
            == retry_metadata.get("checkpoint_path")
            and Path(str(retry_metadata.get("checkpoint_path") or "")).is_file()
        ),
        "repository_identity_preserved": (
            original_metadata.get("repo_path") == retry_metadata.get("repo_path")
        ),
        "retry_completed": (
            worker.get("ok")
            and (retry.get("task") or {}).get("status") == "succeeded"
        ),
        "event_history_preserved": any(
            event.get("event_type") == "task_recovered"
            for event in original.get("events") or []
        ),
    }
    report = {
        "schema": "clawos.long-task-recovery-acceptance.v1",
        "passed": all(checks.values()), "checks": checks,
        "crash_exit_code": 73, "original_task_id": original_id,
        "retry_task_id": retry_id, "recovery": recovery, "worker": worker,
        "truth_boundary": (
            "Acceptance uses two independent Python processes and one durable "
            "SQLite database. It validates restart/replay semantics, not "
            "multi-day production load."
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


def orchestrate(report_path: Path, workspace_parent: Path | None = None) -> int:
    parent = workspace_parent or report_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    workspace = parent / f"recovery-{int(time.time() * 1000)}"
    workspace.mkdir()
    repository = workspace / "repository"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet"], cwd=repository,
        check=True, capture_output=True,
    )
    (repository / "work-item.txt").write_text(
        "durable long repository task\n", encoding="utf-8"
    )
    database, state = workspace / "memory.db", workspace / "state.json"
    crashed = subprocess.run([
        sys.executable, str(Path(__file__).resolve()),
        "--phase", "start", "--database", str(database),
        "--repository", str(repository), "--state", str(state),
    ], capture_output=True, text=True)
    if crashed.returncode != 73 or not state.is_file():
        raise RuntimeError(
            f"crash phase failed: exit={crashed.returncode} stderr={crashed.stderr}"
        )
    return phase_resume(database, state, report_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["orchestrate", "start", "resume"],
                        default="orchestrate")
    parser.add_argument("--database")
    parser.add_argument("--repository")
    parser.add_argument("--state")
    parser.add_argument(
        "--report",
        default=str(ROOT.parent / "output" / "evidence" / "task-recovery.json"),
    )
    parser.add_argument("--workspace-parent")
    args = parser.parse_args()
    if args.phase == "start":
        phase_start(Path(args.database), Path(args.repository), Path(args.state))
        return 73
    if args.phase == "resume":
        return phase_resume(
            Path(args.database), Path(args.state), Path(args.report)
        )
    return orchestrate(
        Path(args.report).expanduser().resolve(),
        Path(args.workspace_parent).expanduser().resolve()
        if args.workspace_parent else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
