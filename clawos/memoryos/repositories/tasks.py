from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from memoryos.persistence import Repository


class TasksRepository(Repository):
    """Persistence operations for tasks."""

    def __init__(self, session, record_quality_signal):
        super().__init__(session)
        self._record_quality_signal = record_quality_signal

    def _task_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        item["attempt"] = int(item.get("attempt") or 1)
        item["cancellation_requested"] = bool(item.get("cancellation_requested"))
        return item


    def _step_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["input"] = self._json_loads(item.pop("input_data", "{}"), {})
        item["output"] = self._json_loads(item.pop("output_data", "{}"), {})
        return item


    def _event_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["data"] = self._json_loads(item.get("data"), {})
        return item


    def start_task(
        self, session_id, title, source="", metadata=None, status="running",
        idempotency_key="", retry_of=None,
    ):
        with self._conn() as c:
            key = str(idempotency_key or "").strip()
            if key:
                existing = c.execute(
                    "SELECT * FROM tasks WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                if existing:
                    item = self._task_row_to_dict(existing)
                    item["idempotent_replay"] = True
                    return item
            attempt = 1
            if retry_of:
                prior = c.execute(
                    "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM tasks WHERE id=? OR retry_of=?",
                    (int(retry_of), int(retry_of)),
                ).fetchone()
                attempt = int(prior["max_attempt"] or 0) + 1
            cursor = c.execute(
                """
                INSERT INTO tasks
                    (session_id, title, status, source, metadata, idempotency_key, retry_of, attempt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session_id or "default"),
                    str(title or "Untitled task")[:300],
                    status,
                    source,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    key,
                    int(retry_of) if retry_of else None,
                    attempt,
                ),
            )
            task_id = int(cursor.lastrowid)
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    task_id,
                    "task_started",
                    "Task started",
                    json.dumps({"idempotency_key": key, "retry_of": retry_of, "attempt": attempt}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return self._task_row_to_dict(row)


    def finish_task(self, task_id, status, error="", result_payload=None):
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            metadata = self._json_loads(row["metadata"], {}) if row else {}
            if result_payload is not None:
                metadata["response_payload"] = result_payload
            metadata["quality_outcome"] = {
                "success": str(status) == "succeeded",
                "failed": str(status) == "failed",
                "canceled": str(status) in {"canceled", "cancelled"},
                "has_response": result_payload is not None,
            }
            c.execute(
                "UPDATE tasks SET status=?, metadata=?, completed_at=datetime('now') WHERE id=?",
                (status, json.dumps(metadata, ensure_ascii=False), int(task_id)),
            )
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(task_id),
                    "task_finished",
                    status,
                    json.dumps({"error": error} if error else {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            result = self._task_row_to_dict(row) if row else {}
        self._record_task_policy_signals(result)
        return result


    def update_task_metadata(self, task_id, updates, event_type="task_metadata"):
        """Merge traceable runtime metadata into a task and emit an audit event."""

        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not row:
                return {}
            metadata = self._json_loads(row["metadata"], {})
            metadata.update(dict(updates or {}))
            c.execute(
                "UPDATE tasks SET metadata=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), int(task_id)),
            )
            c.execute(
                """
                INSERT INTO task_events (task_id, event_type, message, data)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(task_id),
                    str(event_type or "task_metadata"),
                    "Task runtime metadata updated",
                    json.dumps(updates or {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            return self._task_row_to_dict(row)


    def _record_task_policy_signals(self, task):
        metadata = (task or {}).get("metadata") or {}
        selections = metadata.get("runtime_policies") or []
        if isinstance(selections, dict):
            selections = list(selections.values())
        run_ids = {
            int(item.get("run_id"))
            for item in selections
            if isinstance(item, dict)
            and item.get("run_id")
            and item.get("exposure") == "candidate"
        }
        if not run_ids:
            return
        status = str((task or {}).get("status") or "")
        signals = {
            "user_retry_rate": float(
                int((task or {}).get("attempt") or 1) > 1 or bool((task or {}).get("retry_of"))
            ),
            "cancel_rate": float(status in {"canceled", "cancelled"}),
            "long_task_failure_rate": float(status == "failed"),
        }
        for run_id in run_ids:
            for signal_type, value in signals.items():
                self._record_quality_signal(
                    run_id,
                    signal_type,
                    value,
                    metadata={
                        "source": "task_outcome",
                        "task_id": int((task or {}).get("id") or 0),
                        "status": status,
                    },
                    created_by="runtime",
                )


    def cancel_task(self, task_id, reason="", actor_id="user"):
        with self._conn() as c:
            task = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not task:
                return {}
            terminal = str(task["status"]) in {"succeeded", "failed", "canceled", "cancelled"}
            status = str(task["status"]) if terminal else "cancel_requested"
            c.execute(
                "UPDATE tasks SET cancellation_requested=1, status=? WHERE id=?",
                (status, int(task_id)),
            )
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(task_id),
                    "task_cancel_requested",
                    reason or "Cancellation requested",
                    json.dumps({"actor_id": actor_id, "terminal": terminal}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            return self._task_row_to_dict(row)


    def is_task_cancelled(self, task_id):
        if not task_id:
            return False
        with self._conn() as c:
            row = c.execute(
                "SELECT cancellation_requested, status FROM tasks WHERE id=?",
                (int(task_id),),
            ).fetchone()
            return bool(row and (int(row["cancellation_requested"] or 0) or row["status"] in {"cancel_requested", "canceled"}))


    def retry_task(self, task_id, actor_id="user", reason=""):
        with self._conn() as c:
            task = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not task:
                return {}
            metadata = self._json_loads(task["metadata"], {})
            metadata["retry_reason"] = reason
            metadata["retry_actor"] = actor_id
            title = f"Retry: {task['title']}"[:300]
            previous_key = str(task["idempotency_key"] or "")
            retry_key = f"{previous_key}:retry:{int(time.time() * 1000)}" if previous_key else ""
            prior = c.execute(
                "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM tasks WHERE id=? OR retry_of=?",
                (int(task_id), int(task_id)),
            ).fetchone()
            attempt = int(prior["max_attempt"] or int(task["attempt"] or 1)) + 1
            cursor = c.execute(
                """
                INSERT INTO tasks
                    (session_id, title, status, source, metadata, idempotency_key, retry_of, attempt, resume_state)
                VALUES (?, ?, 'pending_retry', ?, ?, ?, ?, ?, 'ready_to_replay')
                """,
                (
                    task["session_id"], title, "retry",
                    json.dumps(metadata, ensure_ascii=False), retry_key,
                    int(task_id), attempt,
                ),
            )
            new_id = int(cursor.lastrowid)
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    new_id,
                    "task_retry_created",
                    reason or "Retry task created",
                    json.dumps({"retry_of": int(task_id), "actor_id": actor_id, "attempt": attempt}, ensure_ascii=False),
                ),
            )
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(task_id),
                    "task_retry_requested",
                    reason or "Retry requested",
                    json.dumps({"new_task_id": new_id, "actor_id": actor_id}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (new_id,)).fetchone()
            return self._task_row_to_dict(row)


    def recover_interrupted_tasks(self, actor_id="system", create_retries=False):
        recoverable = ("running", "pending", "cancel_requested", "waiting_confirmation")
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM tasks WHERE status IN ({','.join('?' for _ in recoverable)})",
                recoverable,
            ).fetchall()
            recovered = []
            retry_tasks = []
            for row in rows:
                status = "canceled" if row["status"] == "cancel_requested" else "interrupted"
                c.execute(
                    "UPDATE tasks SET status=?, resume_state='needs_retry', completed_at=datetime('now') WHERE id=?",
                    (status, int(row["id"])),
                )
                c.execute(
                    "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                    (
                        int(row["id"]),
                        "task_recovered",
                        "Recovered after process restart or manual recovery",
                        json.dumps({"actor_id": actor_id, "previous_status": row["status"]}, ensure_ascii=False),
                    ),
                )
                recovered.append(int(row["id"]))
                if create_retries and row["status"] in {"running", "pending"}:
                    metadata = self._json_loads(row["metadata"], {})
                    metadata["recovery_actor"] = actor_id
                    prior = c.execute(
                        "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM tasks WHERE id=? OR retry_of=?",
                        (int(row["id"]), int(row["id"])),
                    ).fetchone()
                    attempt = int(prior["max_attempt"] or int(row["attempt"] or 1)) + 1
                    cursor = c.execute(
                        """
                        INSERT INTO tasks
                            (session_id, title, status, source, metadata, idempotency_key, retry_of, attempt, resume_state)
                        VALUES (?, ?, 'pending_retry', 'recovery', ?, '', ?, ?, 'ready_to_replay')
                        """,
                        (
                            row["session_id"], f"Replay: {row['title']}"[:300],
                            json.dumps(metadata, ensure_ascii=False),
                            int(row["id"]), attempt,
                        ),
                    )
                    retry_id = int(cursor.lastrowid)
                    c.execute(
                        "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                        (
                            retry_id,
                            "task_retry_created",
                            "Replay retry created during recovery",
                            json.dumps({"retry_of": int(row["id"]), "actor_id": actor_id, "attempt": attempt}, ensure_ascii=False),
                        ),
                    )
                    retry_row = c.execute("SELECT * FROM tasks WHERE id=?", (retry_id,)).fetchone()
                    retry_tasks.append(self._task_row_to_dict(retry_row))
            return {
                "recovered": recovered,
                "count": len(recovered),
                "retry_tasks": retry_tasks,
                "created_retry_count": len(retry_tasks),
            }


    def list_task_events(self, session_id="", after_id=0, limit=100):
        with self._conn() as c:
            limit = max(1, min(int(limit or 100), 500))
            clauses = ["e.id>?"]
            params = [int(after_id or 0)]
            if session_id:
                clauses.append("t.session_id=?")
                params.append(session_id)
            rows = c.execute(
                f"""
                SELECT e.*, t.session_id, t.status AS task_status, t.title AS task_title
                FROM task_events e JOIN tasks t ON t.id=e.task_id
                WHERE {' AND '.join(clauses)}
                ORDER BY e.id ASC LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            return [self._event_row_to_dict(row) for row in rows]


    def prune_task_events(self, older_than_days=30, retain_latest_per_task=100, dry_run=False, actor_id="system"):
        lifecycle_events = {
            "task_started",
            "task_finished",
            "task_cancel_requested",
            "task_retry_created",
            "task_retry_requested",
            "task_recovered",
        }
        older_than_days = max(1, int(older_than_days or 30))
        retain_latest_per_task = max(0, min(int(retain_latest_per_task or 0), 1000))
        cutoff = f"-{older_than_days} days"
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM task_events
                WHERE created_at < datetime('now', ?)
                ORDER BY task_id ASC, id DESC
                """,
                (cutoff,),
            ).fetchall()
            detail_kept_by_task = {}
            delete_ids = []
            retained_lifecycle_count = 0
            retained_tail_count = 0
            for row in rows:
                if row["event_type"] in lifecycle_events:
                    retained_lifecycle_count += 1
                    continue
                task_id = int(row["task_id"])
                kept = detail_kept_by_task.get(task_id, 0)
                if kept < retain_latest_per_task:
                    detail_kept_by_task[task_id] = kept + 1
                    retained_tail_count += 1
                    continue
                delete_ids.append(int(row["id"]))
            if delete_ids and not dry_run:
                placeholders = ",".join("?" for _ in delete_ids)
                c.execute(f"DELETE FROM task_events WHERE id IN ({placeholders})", delete_ids)
        return {
            "older_than_days": older_than_days,
            "retain_latest_per_task": retain_latest_per_task,
            "dry_run": bool(dry_run),
            "actor_id": str(actor_id or "system"),
            "candidate_count": len(rows),
            "deleted_count": len(delete_ids),
            "retained_lifecycle_count": retained_lifecycle_count,
            "retained_tail_count": retained_tail_count,
        }


    def add_task_step(self, task_id, step_type, name, status="running", input_data=None):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO task_steps (task_id, step_type, name, status, input_data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(task_id),
                    str(step_type or "tool"),
                    str(name or "step"),
                    status,
                    json.dumps(input_data or {}, ensure_ascii=False),
                ),
            )
            step_id = int(cursor.lastrowid)
            c.execute(
                "INSERT INTO task_events (task_id, step_id, event_type, message, data) VALUES (?, ?, ?, ?, ?)",
                (int(task_id), step_id, "step_started", str(name or "step"), "{}"),
            )
            row = c.execute("SELECT * FROM task_steps WHERE id=?", (step_id,)).fetchone()
            return self._step_row_to_dict(row)


    def finish_task_step(self, step_id, status, output_data=None, error=""):
        with self._conn() as c:
            c.execute(
                """
                UPDATE task_steps
                SET status=?, output_data=?, error=?, completed_at=datetime('now')
                WHERE id=?
                """,
                (
                    status,
                    json.dumps(output_data or {}, ensure_ascii=False),
                    error,
                    int(step_id),
                ),
            )
            row = c.execute("SELECT * FROM task_steps WHERE id=?", (int(step_id),)).fetchone()
            if not row:
                return {}
            c.execute(
                "INSERT INTO task_events (task_id, step_id, event_type, message, data) VALUES (?, ?, ?, ?, ?)",
                (
                    int(row["task_id"]),
                    int(step_id),
                    "step_finished",
                    status,
                    json.dumps({"error": error} if error else {}, ensure_ascii=False),
                ),
            )
            return self._step_row_to_dict(row)


    def add_task_event(self, task_id, event_type, message="", step_id=None, data=None):
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO task_events (task_id, step_id, event_type, message, data) VALUES (?, ?, ?, ?, ?)",
                (
                    int(task_id),
                    int(step_id) if step_id else None,
                    str(event_type or "event"),
                    str(message or ""),
                    json.dumps(data or {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM task_events WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return self._event_row_to_dict(row)


    def transition_task(
        self, task_id, status, actor_id="system", reason="", checkpoint=None
    ):
        """Apply the canonical TaskRun state machine and persist one audit event."""

        from services.agent_product_kernel import TaskRunContract

        target = str(status or "").strip()
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM tasks WHERE id=?", (int(task_id),)
            ).fetchone()
            if not row:
                return {}
            current = str(row["status"] or "created")
            TaskRunContract.validate_transition(current, target)
            metadata = self._json_loads(row["metadata"], {})
            checkpoint = dict(checkpoint or {})
            if checkpoint:
                if not checkpoint.get("uri") or not checkpoint.get("digest"):
                    raise ValueError("checkpoint requires uri and digest")
                metadata["latest_checkpoint"] = checkpoint
            terminal = target in TaskRunContract.TERMINAL
            cancellation_requested = int(target == "cancel_requested")
            completed = "datetime('now')" if terminal else "completed_at"
            c.execute(
                f"""
                UPDATE tasks
                SET status=?, metadata=?, cancellation_requested=?,
                    completed_at={completed},
                    resume_state=?
                WHERE id=?
                """,
                (
                    target,
                    json.dumps(metadata, ensure_ascii=False),
                    cancellation_requested,
                    "checkpoint_available" if checkpoint else target,
                    int(task_id),
                ),
            )
            if checkpoint:
                c.execute(
                    """
                    INSERT INTO task_events (task_id, event_type, message, data)
                    VALUES (?, 'run.checkpoint', ?, ?)
                    """,
                    (
                        int(task_id), "Checkpoint attached to task run",
                        json.dumps({
                            "actor_id": str(actor_id or "system"),
                            "checkpoint": checkpoint,
                        }, ensure_ascii=False),
                    ),
                )
            event_type = "run.completed" if terminal else "run.transitioned"
            c.execute(
                """
                INSERT INTO task_events (task_id, event_type, message, data)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(task_id), event_type, reason or f"{current} -> {target}",
                    json.dumps({
                        "from": current, "to": target,
                        "actor_id": str(actor_id or "system"),
                        "checkpoint": checkpoint,
                    }, ensure_ascii=False),
                ),
            )
            updated = c.execute(
                "SELECT * FROM tasks WHERE id=?", (int(task_id),)
            ).fetchone()
            return self._task_row_to_dict(updated)


    def list_tasks(self, session_id="", status="", limit=50):
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            clauses = []
            params = []
            if session_id:
                clauses.append("session_id=?")
                params.append(session_id)
            if status:
                clauses.append("status=?")
                params.append(status)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM tasks{where} ORDER BY id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [self._task_row_to_dict(row) for row in rows]


    def list_tasks_for_soak(self, session_id, limit=200000):
        """Return the complete bounded task set used by offline soak validation."""
        with self._conn() as c:
            limit = max(1, min(int(limit or 200000), 200000))
            rows = c.execute(
                """
                SELECT * FROM tasks
                WHERE session_id=?
                ORDER BY id ASC
                LIMIT ?
                """,
                (str(session_id), limit),
            ).fetchall()
            return [self._task_row_to_dict(row) for row in rows]


    def list_task_queue(self, statuses=None, limit=50):
        statuses = statuses or ["pending_retry", "pending"]
        statuses = [str(status) for status in statuses if str(status or "").strip()]
        if not statuses:
            statuses = ["pending_retry", "pending"]
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            placeholders = ",".join("?" for _ in statuses)
            rows = c.execute(
                f"""
                SELECT *
                FROM tasks
                WHERE status IN ({placeholders}) AND cancellation_requested=0
                ORDER BY attempt ASC, id ASC
                LIMIT ?
                """,
                [*statuses, limit],
            ).fetchall()
            return [self._task_row_to_dict(row) for row in rows]


    def claim_next_task(self, worker_id="worker", statuses=None):
        statuses = statuses or ["pending_retry", "pending"]
        statuses = [str(status) for status in statuses if str(status or "").strip()]
        if not statuses:
            statuses = ["pending_retry", "pending"]
        with self._conn() as c:
            placeholders = ",".join("?" for _ in statuses)
            row = c.execute(
                f"""
                SELECT *
                FROM tasks
                WHERE status IN ({placeholders}) AND cancellation_requested=0
                ORDER BY attempt ASC, id ASC
                LIMIT 1
                """,
                statuses,
            ).fetchone()
            if not row:
                return {}
            metadata = self._json_loads(row["metadata"], {})
            metadata["claimed_by"] = str(worker_id or "worker")
            metadata["claimed_at"] = datetime.now(timezone.utc).isoformat()
            updated = c.execute(
                """
                UPDATE tasks
                SET status='running', resume_state='claimed', metadata=?
                WHERE id=? AND status=?
                """,
                (json.dumps(metadata, ensure_ascii=False), int(row["id"]), row["status"]),
            )
            if updated.rowcount != 1:
                return {}
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(row["id"]),
                    "task_claimed",
                    "Task claimed by queue worker",
                    json.dumps({"worker_id": str(worker_id or "worker")}, ensure_ascii=False),
                ),
            )
            claimed = c.execute("SELECT * FROM tasks WHERE id=?", (int(row["id"]),)).fetchone()
            return self._task_row_to_dict(claimed)


    def get_task(self, task_id):
        with self._conn() as c:
            task = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not task:
                return {}
            steps = c.execute("SELECT * FROM task_steps WHERE task_id=? ORDER BY id", (int(task_id),)).fetchall()
            events = c.execute("SELECT * FROM task_events WHERE task_id=? ORDER BY id", (int(task_id),)).fetchall()
            return {
                "task": self._task_row_to_dict(task),
                "steps": [self._step_row_to_dict(row) for row in steps],
                "events": [self._event_row_to_dict(row) for row in events],
            }
