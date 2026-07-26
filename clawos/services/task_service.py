from __future__ import annotations

import asyncio
import time
from typing import Any


class TaskService:
    """Runtime task boundary used by chat, queue, and task API routes."""

    def __init__(self, store: Any, action_handlers: dict[str, Any] | None = None):
        self.store = store
        self.action_handlers = action_handlers or {}

    def require_store(self):
        if not self.store:
            raise RuntimeError("MemoryOS not initialized")
        return self.store

    def create(self, session_id: str, title: str, source: str = "chat", metadata: dict[str, Any] | None = None):
        store = self.require_store()
        metadata = metadata or {}
        task = store.start_task(
            session_id,
            title,
            source=source,
            metadata=metadata,
            idempotency_key=str(metadata.get("idempotency_key", "") or ""),
            retry_of=metadata.get("retry_of"),
        )
        self._ensure_trajectory(task)
        return task

    def enqueue(self, session_id: str, title: str, source: str = "worker_job", metadata: dict[str, Any] | None = None):
        store = self.require_store()
        metadata = metadata or {}
        task = store.start_task(
            session_id,
            title,
            source=source,
            metadata=metadata,
            status="pending",
            idempotency_key=str(metadata.get("idempotency_key", "") or ""),
            retry_of=metadata.get("retry_of"),
        )
        self._ensure_trajectory(task)
        return task

    def list(self, session_id: str = "", status: str = "", limit: int = 50):
        return self.require_store().list_tasks(session_id=session_id, status=status, limit=limit)

    def queue(self, statuses: list[str] | None = None, limit: int = 50):
        return self.require_store().list_task_queue(statuses=statuses, limit=limit)

    def claim(self, worker_id: str = "worker", statuses: list[str] | None = None):
        return self.require_store().claim_next_task(worker_id=worker_id, statuses=statuses)

    def detail(self, task_id: int):
        return self.require_store().get_task(task_id)

    def finish(self, task_id: int | None, status: str, error: str = "", result_payload: dict[str, Any] | None = None):
        if not task_id:
            return {}
        store = self.require_store()
        task = store.finish_task(task_id, status, error=error, result_payload=result_payload)
        for selection in (task.get("metadata") or {}).get("policy_optimizer_selections") or []:
            try:
                from policy_optimizer import PolicyOptimizer

                PolicyOptimizer(store).reward_from_task(
                    int(selection["selection_id"]),
                    int(task_id),
                    satisfaction=(task.get("metadata") or {}).get(
                        "user_satisfaction"
                    ),
                )
            except (KeyError, TypeError, ValueError):
                # A selection may already have been rewarded explicitly.
                pass
        try:
            from agent_learning import TrajectoryLearningService

            TrajectoryLearningService(store).complete_task(int(task_id))
        except ValueError:
            pass
        try:
            from .runtime_records import run_from_task

            store.save_run_record(run_from_task({**task, "error": error}))
        except Exception:
            pass
        return task

    def cancel(self, task_id: int, reason: str = "", actor_id: str = "user"):
        return self.require_store().cancel_task(task_id, reason=reason, actor_id=actor_id)

    def retry(self, task_id: int, reason: str = "", actor_id: str = "user"):
        task = self.require_store().retry_task(task_id, actor_id=actor_id, reason=reason)
        self._ensure_trajectory(task)
        return task

    def recover(self, actor_id: str = "user", create_retries: bool = False):
        store = self.require_store()
        result = store.recover_interrupted_tasks(
            actor_id=actor_id, create_retries=create_retries
        )
        try:
            from agent_learning import TrajectoryLearningService

            learning = TrajectoryLearningService(store)
            for task_id in result.get("recovered") or []:
                learning.complete_task(int(task_id))
            for task in result.get("retry_tasks") or []:
                self._ensure_trajectory(task)
        except ValueError:
            pass
        return result

    def events(self, session_id: str = "", after_id: int = 0, limit: int = 100):
        return self.require_store().list_task_events(session_id=session_id, after_id=after_id, limit=limit)

    def prune_events(self, *, older_than_days=30, retain_latest_per_task=100, dry_run=False, actor_id="user"):
        return self.require_store().prune_task_events(
            older_than_days=older_than_days,
            retain_latest_per_task=retain_latest_per_task,
            dry_run=bool(dry_run),
            actor_id=str(actor_id or "user"),
        )

    def is_cancelled(self, task_id: int) -> bool:
        return self.require_store().is_task_cancelled(task_id)

    async def run_worker_once(
        self,
        *,
        worker_id: str = "background-worker",
        statuses: list[str] | None = None,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        store = self.require_store()
        task = store.claim_next_task(
            worker_id=worker_id,
            statuses=statuses or ["pending", "pending_retry"],
        )
        if not task:
            return {"ok": True, "claimed": False, "task": None}
        task_id = int(task["id"])
        metadata = dict(task.get("metadata") or {})
        action = str(metadata.get("worker_action") or "noop")
        try:
            if self.is_cancelled(task_id):
                item = self.finish(task_id, "canceled", error="canceled before worker execution")
                return {"ok": True, "claimed": True, "canceled": True, "task": item}
            handler = self.action_handlers.get(action)
            if handler:
                result = handler(task, metadata)
                if asyncio.iscoroutine(result):
                    result = await result
            else:
                result = await self._execute_worker_action(task, action)
            if self.is_cancelled(task_id):
                item = self.finish(task_id, "canceled", error="canceled during worker execution")
                return {"ok": True, "claimed": True, "canceled": True, "task": item}
            item = self.finish(task_id, "succeeded", result_payload=result)
            return {"ok": True, "claimed": True, "task": item, "result": result}
        except asyncio.CancelledError:
            store.finish_task(task_id, "interrupted", error="worker stopped")
            raise
        except Exception as exc:
            item = self.finish(task_id, "failed", error=str(exc))
            retry = {}
            if int(task.get("attempt") or 1) < int(max_attempts or 1):
                retry = store.retry_task(task_id, actor_id=worker_id, reason=str(exc))
            return {
                "ok": False,
                "claimed": True,
                "task": item,
                "error": str(exc),
                "retry_task": retry,
            }

    async def _execute_worker_action(self, task: dict[str, Any], action: str) -> dict[str, Any]:
        metadata = dict(task.get("metadata") or {})
        task_id = int(task["id"])
        if action == "fail":
            raise RuntimeError(str(metadata.get("error") or "worker action failed"))
        if action in {"sleep", "long_task"}:
            duration_ms = max(0, min(int(metadata.get("duration_ms") or 1000), 30000))
            deadline = time.monotonic() + duration_ms / 1000.0
            while time.monotonic() < deadline:
                if self.is_cancelled(task_id):
                    return {"action": action, "canceled": True}
                await asyncio.sleep(min(0.1, max(0, deadline - time.monotonic())))
            return {"action": action, "duration_ms": duration_ms}
        return {
            "action": action,
            "message": "Task consumed by minimal background worker.",
            "metadata_keys": sorted(metadata.keys()),
        }

    def _ensure_trajectory(self, task: dict[str, Any]) -> None:
        if not task or not task.get("id"):
            return
        metadata = task.get("metadata") or {}
        try:
            from agent_learning import TrajectoryLearningService

            TrajectoryLearningService(self.require_store()).ensure_task(
                int(task["id"]),
                scenario=str(metadata.get("scenario") or "general"),
                task_context={
                    "title": task.get("title") or "",
                    "source": task.get("source") or "",
                    "task_description": metadata.get("user_text") or task.get("title") or "",
                    "tags": metadata.get("tags") or [],
                },
                user_context=metadata.get("user_context") or {},
                environment_state=metadata.get("environment_state") or {},
                policy_version=str(metadata.get("policy_version") or ""),
            )
        except ValueError:
            pass
