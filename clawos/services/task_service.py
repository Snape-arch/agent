from __future__ import annotations

from typing import Any


class TaskService:
    """Runtime task boundary used by chat, queue, and task API routes."""

    def __init__(self, store: Any):
        self.store = store

    def require_store(self):
        if not self.store:
            raise RuntimeError("MemoryOS not initialized")
        return self.store

    def create(self, session_id: str, title: str, source: str = "chat", metadata: dict[str, Any] | None = None):
        store = self.require_store()
        metadata = metadata or {}
        return store.start_task(
            session_id,
            title,
            source=source,
            metadata=metadata,
            idempotency_key=str(metadata.get("idempotency_key", "") or ""),
            retry_of=metadata.get("retry_of"),
        )

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
        return self.require_store().finish_task(task_id, status, error=error, result_payload=result_payload)

    def cancel(self, task_id: int, reason: str = "", actor_id: str = "user"):
        return self.require_store().cancel_task(task_id, reason=reason, actor_id=actor_id)

    def retry(self, task_id: int, reason: str = "", actor_id: str = "user"):
        return self.require_store().retry_task(task_id, actor_id=actor_id, reason=reason)

    def recover(self, actor_id: str = "user", create_retries: bool = False):
        return self.require_store().recover_interrupted_tasks(actor_id=actor_id, create_retries=create_retries)

    def events(self, session_id: str = "", after_id: int = 0, limit: int = 100):
        return self.require_store().list_task_events(session_id=session_id, after_id=after_id, limit=limit)

    def prune_events(self, *, older_than_days=30, retain_latest_per_task=100, dry_run=False, actor_id="user"):
        return self.require_store().prune_task_events(
            older_than_days=older_than_days,
            retain_latest_per_task=retain_latest_per_task,
            dry_run=bool(dry_run),
            actor_id=str(actor_id or "user"),
        )
