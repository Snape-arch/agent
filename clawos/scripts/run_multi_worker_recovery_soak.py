"""Concurrent durable-worker soak with crash injection and restart recovery."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from services.task_service import TaskService


def worker(database: Path, worker_id: str, deadline: float) -> int:
    store = MemoryStore(str(database))
    service = TaskService(store)
    while time.time() < deadline:
        result = asyncio.run(service.run_worker_once(
            worker_id=worker_id, max_attempts=1
        ))
        if not result.get("claimed"):
            time.sleep(0.05)
    return 0


def crash_worker(database: Path) -> None:
    store = MemoryStore(str(database))
    task = store.claim_next_task(worker_id="injected-crash")
    if not task:
        os._exit(75)
    store.add_task_event(
        task["id"], "worker_crash_injected",
        "Worker terminated after durable claim",
        data={"worker_id": "injected-crash"},
    )
    os._exit(74)


def enqueue(store: MemoryStore, sequence: int) -> dict:
    return store.start_task(
        "multi-worker-soak", f"Soak task {sequence}",
        source="multi-worker-soak", status="pending",
        idempotency_key=f"soak-{sequence}",
        metadata={
            "worker_action": "long_task", "duration_ms": 10,
            "soak_sequence": sequence,
        },
    )


def orchestrate(
    database: Path, report_path: Path, *,
    duration_seconds: float, workers: int, minimum_hours: float,
) -> int:
    duration = max(5.0, float(duration_seconds))
    worker_count = max(2, min(int(workers), 16))
    store = MemoryStore(str(database))
    started = time.time()
    deadline = started + duration
    sequence = 0
    sequence += 1
    enqueue(store, sequence)
    crashed = subprocess.run([
        sys.executable, str(Path(__file__).resolve()), "--phase", "crash",
        "--database", str(database),
    ], capture_output=True, text=True)
    recovery = store.recover_interrupted_tasks(
        actor_id="soak-supervisor", create_retries=True
    )
    for _ in range(worker_count * 3 - 1):
        sequence += 1
        enqueue(store, sequence)
    processes = [
        subprocess.Popen([
            sys.executable, str(Path(__file__).resolve()), "--phase", "worker",
            "--database", str(database), "--worker-id", f"soak-worker-{index}",
            "--deadline", str(deadline),
        ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        for index in range(worker_count)
    ]
    next_batch = time.time() + 0.5
    production_deadline = deadline - min(2.0, duration / 4)
    while time.time() < production_deadline:
        if time.time() >= next_batch:
            for _ in range(worker_count):
                sequence += 1
                enqueue(store, sequence)
            next_batch = time.time() + min(5.0, max(0.5, duration / 20))
        time.sleep(0.05)
    for process in processes:
        process.wait(timeout=max(5, int(deadline - time.time()) + 10))
    elapsed = time.time() - started
    tasks = store.list_tasks_for_soak(
        session_id="multi-worker-soak", limit=200000
    )
    by_root: dict[int, list[dict]] = {}
    for task in tasks:
        root_id = int(task.get("retry_of") or task["id"])
        by_root.setdefault(root_id, []).append(task)
    logical_success = sum(
        1 for rows in by_root.values()
        if any(row.get("status") == "succeeded" for row in rows)
    )
    duplicate_claims = 0
    for task in tasks:
        detail = store.get_task(task["id"])
        claims = sum(
            event.get("event_type") == "task_claimed"
            for event in detail.get("events") or []
        )
        if claims > 1:
            duplicate_claims += 1
    pending = [
        task for task in tasks
        if task.get("status") in {
            "pending", "pending_retry", "running", "cancel_requested",
        }
    ]
    checks = {
        "crash_injected": crashed.returncode == 74,
        "crash_recovered": bool(recovery.get("recovered")),
        "all_logical_tasks_succeeded": logical_success == len(by_root),
        "no_duplicate_claims": duplicate_claims == 0,
        "queue_drained": not pending,
        "all_workers_exited_cleanly": all(
            process.returncode == 0 for process in processes
        ),
    }
    multi_worker_passed = all(checks.values())
    report = {
        "schema": "clawos.multi-worker-recovery-soak.v1",
        "passed": multi_worker_passed,
        "multi_worker_passed": multi_worker_passed,
        "multi_hour_passed": bool(
            multi_worker_passed
            and elapsed >= max(1.0, minimum_hours) * 3600
        ),
        "requested_duration_seconds": duration,
        "observed_duration_seconds": round(elapsed, 3),
        "minimum_hours": max(1.0, minimum_hours),
        "worker_count": worker_count,
        "logical_task_count": len(by_root),
        "logical_success_count": logical_success,
        "physical_task_count": len(tasks),
        "duplicate_claim_task_count": duplicate_claims,
        "pending_task_count": len(pending),
        "crash_exit_code": crashed.returncode,
        "recovered_count": len(recovery.get("recovered") or []),
        "checks": checks,
        "throughput_tasks_per_second": round(
            logical_success / max(elapsed, 0.001), 3
        ),
        "truth_boundary": (
            "multi_hour_passed requires observed wall time at or above the "
            "configured minimum. Accelerated CI runs prove concurrency and "
            "recovery mechanics but cannot satisfy the multi-hour gate."
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if multi_worker_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["orchestrate", "worker", "crash"],
                        default="orchestrate")
    parser.add_argument("--database")
    parser.add_argument("--worker-id", default="soak-worker")
    parser.add_argument("--deadline", type=float, default=0)
    parser.add_argument("--duration-seconds", type=float, default=30)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--minimum-hours", type=float, default=2)
    parser.add_argument(
        "--report",
        default=str(ROOT.parent / "output" / "evidence"
                    / "multi-worker-recovery-soak.json"),
    )
    args = parser.parse_args()
    if args.phase == "worker":
        return worker(Path(args.database), args.worker_id, args.deadline)
    if args.phase == "crash":
        crash_worker(Path(args.database))
        return 74
    report = Path(args.report).expanduser().resolve()
    database = (
        Path(args.database).expanduser().resolve()
        if args.database else report.parent / (
            "multi-worker-recovery-soak-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + ".db"
        )
    )
    return orchestrate(
        database, report, duration_seconds=args.duration_seconds,
        workers=args.workers, minimum_hours=args.minimum_hours,
    )


if __name__ == "__main__":
    raise SystemExit(main())
