"""Database-backed task leases shared by API and standalone workers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from database import connect
from observability import current_traceparent, gauge, inc


TERMINAL = {"completed", "failed", "cancelled", "dead-letter"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue(tenant_id: str, kind: str, resource_id: str, payload: dict,
            idempotency_key: str, *, priority: int = 50, max_attempts: int = 3) -> dict:
    payload = dict(payload)
    if current_traceparent(): payload.setdefault("_traceparent", current_traceparent())
    task_id = "task_" + uuid.uuid4().hex[:16]; timestamp = now()
    with connect() as db:
        existing = db.execute(
            "SELECT * FROM durable_tasks WHERE tenant_id=? AND idempotency_key=?",
            (tenant_id, idempotency_key),
        ).fetchone()
        if existing:
            return serialize(existing)
        db.execute(
            """INSERT INTO durable_tasks(id,tenant_id,kind,resource_id,payload,status,priority,
               attempts,max_attempts,idempotency_key,created_at,updated_at)
               VALUES(?,?,?,?,?,'queued',?,0,?,?,?,?)""",
            (task_id, tenant_id, kind, resource_id, json.dumps(payload, ensure_ascii=False),
             max(0, min(100, priority)), max(1, max_attempts), idempotency_key, timestamp, timestamp),
        )
        row = db.execute("SELECT * FROM durable_tasks WHERE id=?", (task_id,)).fetchone()
        _event(db, task_id, "queued", {"kind": kind})
    inc("clawvision_tasks_enqueued_total", kind=kind)
    return serialize(row)


def claim(worker_id: str, *, kinds: list[str] | None = None, lease_seconds: int = 30) -> dict | None:
    timestamp = now(); expires = (datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))).isoformat()
    with connect() as db:
        values: list = [timestamp]
        clause = "status='queued' OR (status='leased' AND lease_expires_at<?)"
        if kinds:
            clause = f"({clause}) AND kind IN ({','.join('?' for _ in kinds)})"; values.extend(kinds)
        row = db.execute(f"SELECT * FROM durable_tasks WHERE {clause} ORDER BY priority DESC,created_at LIMIT 1", values).fetchone()
        if not row:
            return None
        updated = db.execute(
            """UPDATE durable_tasks SET status='leased',lease_owner=?,lease_expires_at=?,
               heartbeat_at=?,attempts=attempts+1,updated_at=?
               WHERE id=? AND (status='queued' OR lease_expires_at<?)""",
            (worker_id, expires, timestamp, timestamp, row["id"], timestamp),
        )
        if getattr(updated, "rowcount", 1) == 0:
            return None
        claimed = db.execute("SELECT * FROM durable_tasks WHERE id=?", (row["id"],)).fetchone()
        _event(db, row["id"], "leased", {"worker": worker_id, "attempt": claimed["attempts"]})
    inc("clawvision_task_leases_total", kind=claimed["kind"])
    return serialize(claimed)


def lease(task_id: str, worker_id: str, lease_seconds: int = 30) -> bool:
    timestamp = now(); expires = (datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))).isoformat()
    with connect() as db:
        cursor = db.execute("UPDATE durable_tasks SET status='leased',lease_owner=?,lease_expires_at=?,heartbeat_at=?,attempts=attempts+1,updated_at=? WHERE id=? AND (status='queued' OR (status='leased' AND lease_expires_at<?))", (worker_id, expires, timestamp, timestamp, task_id, timestamp))
        ok = getattr(cursor, "rowcount", 1) > 0
        if ok: _event(db, task_id, "leased", {"worker": worker_id})
        return ok


def heartbeat(task_id: str, worker_id: str, lease_seconds: int = 30) -> bool:
    timestamp = now(); expires = (datetime.now(timezone.utc) + timedelta(seconds=max(5, lease_seconds))).isoformat()
    with connect() as db:
        cursor = db.execute("UPDATE durable_tasks SET heartbeat_at=?,lease_expires_at=?,updated_at=? WHERE id=? AND lease_owner=? AND status='leased'", (timestamp, expires, timestamp, task_id, worker_id))
        return getattr(cursor, "rowcount", 1) > 0


def finish(task_id: str, worker_id: str, result: dict | None = None) -> bool:
    timestamp = now()
    with connect() as db:
        cursor = db.execute("UPDATE durable_tasks SET status='completed',result=?,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=? AND lease_owner=?", (json.dumps(result or {}, ensure_ascii=False), timestamp, task_id, worker_id))
        ok = getattr(cursor, "rowcount", 1) > 0
        if ok: _event(db, task_id, "completed", result or {})
        if ok: inc("clawvision_tasks_completed_total")
        return ok


def fail(task_id: str, worker_id: str, error: str, *, retry: bool = True) -> str:
    timestamp = now()
    with connect() as db:
        row = db.execute("SELECT attempts,max_attempts FROM durable_tasks WHERE id=? AND lease_owner=?", (task_id, worker_id)).fetchone()
        if not row: return "missing"
        status = "queued" if retry and int(row["attempts"]) < int(row["max_attempts"]) else "dead-letter"
        db.execute("UPDATE durable_tasks SET status=?,error=?,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?", (status, error[:4000], timestamp, task_id))
        _event(db, task_id, status, {"error": error[:1000]})
        inc("clawvision_task_failures_total", status=status)
        if status == "dead-letter": inc("clawvision_task_dead_letters_total")
        return status


def cancel(task_id: str, tenant_id: str) -> bool:
    timestamp = now()
    with connect() as db:
        cursor = db.execute("UPDATE durable_tasks SET status='cancelled',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=? AND tenant_id=? AND status NOT IN ('completed','failed','dead-letter')", (timestamp, task_id, tenant_id))
        ok = getattr(cursor, "rowcount", 1) > 0
        if ok: _event(db, task_id, "cancelled", {})
        return ok


def reap_expired(*, kind: str | None = None) -> int:
    timestamp = now()
    reaped = 0
    with connect() as db:
        clause = " AND kind=?" if kind else ""
        values = (timestamp, kind) if kind else (timestamp,)
        rows = db.execute("SELECT id,attempts,max_attempts FROM durable_tasks WHERE status='leased' AND lease_expires_at<?" + clause, values).fetchall()
        for row in rows:
            status = "queued" if row["attempts"] < row["max_attempts"] else "dead-letter"
            updated = db.execute("UPDATE durable_tasks SET status=?,lease_owner=NULL,lease_expires_at=NULL,error='worker lease expired',updated_at=? WHERE id=? AND status='leased' AND lease_expires_at<?", (status, timestamp, row["id"], timestamp))
            if updated.rowcount == 0: continue
            reaped += 1
            _event(db, row["id"], "lease-expired", {"nextStatus": status})
            inc("clawvision_task_lease_expirations_total", next_status=status)
        return reaped


def queue_metrics() -> dict[str, object]:
    """Return global queue state for operational metrics and worker probes."""
    with connect() as db:
        rows = db.execute("SELECT status,COUNT(*) AS count FROM durable_tasks GROUP BY status").fetchall()
        oldest = db.execute("SELECT MIN(created_at) AS created_at FROM durable_tasks WHERE status='queued'").fetchone()
    counts = {row["status"]: int(row["count"]) for row in rows}
    age = 0.0
    if oldest and oldest["created_at"]:
        age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(oldest["created_at"])).total_seconds())
    for status in ("queued", "leased", "completed", "failed", "cancelled", "dead-letter"):
        gauge("clawvision_queue_tasks", counts.get(status, 0), status=status)
    gauge("clawvision_queue_oldest_queued_seconds", age)
    return {"counts": counts, "oldestQueuedSeconds": age}


def list_tasks(tenant_id: str, limit: int = 100) -> list[dict]:
    with connect() as db:
        rows = db.execute("SELECT * FROM durable_tasks WHERE tenant_id=? ORDER BY created_at DESC LIMIT ?", (tenant_id, max(1, min(limit, 500)))).fetchall()
    return [serialize(row) for row in rows]


def _event(db, task_id: str, event: str, detail: dict) -> None:
    db.execute("INSERT INTO durable_task_events(id,task_id,event,detail,created_at) VALUES(?,?,?,?,?)", ("tevt_" + uuid.uuid4().hex[:16], task_id, event, json.dumps(detail, ensure_ascii=False), now()))


def serialize(row) -> dict:
    return {"id": row["id"], "tenantId": row["tenant_id"], "kind": row["kind"], "resourceId": row["resource_id"],
            "payload": json.loads(row["payload"] or "{}"), "status": row["status"], "priority": row["priority"],
            "attempts": row["attempts"], "maxAttempts": row["max_attempts"], "leaseOwner": row["lease_owner"],
            "leaseExpiresAt": row["lease_expires_at"], "heartbeatAt": row["heartbeat_at"],
            "result": json.loads(row["result"] or "{}"), "error": row["error"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}
