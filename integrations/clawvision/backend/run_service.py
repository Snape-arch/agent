"""Transport-independent Run queries, transactions and durable incremental reads."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from api_contract import Pagination, page_meta
from errors import NotFoundError, ValidationError


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def metric_value(row) -> dict:
    return {"step": row["step"], "trainLoss": row["train_loss"], "valLoss": row["val_loss"], "accuracy": row["accuracy"], "learningRate": row["learning_rate"], "gpu": row["gpu"]}


def run_value(row) -> dict:
    return {"id": row["id"], "name": row["name"], "status": row["status"], "source": row["source"], "params": json.loads(row["params"] or "{}"),
            "createdAt": row["created_at"], "updatedAt": row["updated_at"], "errorMessage": row["error_message"], "revision": int(row["revision"])}


class RunService:
    def __init__(self, connect, object_store, lock, reserve_storage=lambda tenant, size: None):
        self.connect, self.object_store, self.lock, self.reserve_storage = connect, object_store, lock, reserve_storage

    @contextmanager
    def transaction(self, *, write=False):
        with self.lock, self.connect() as db:
            # Snapshot and its cursor must describe the same committed state.
            if getattr(db, "kind", None) == "sqlite" or isinstance(db, sqlite3.Connection):
                db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            elif not write:
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            yield db

    @staticmethod
    def require(db, run_id, tenant_id=None):
        clause = "id=?" + (" AND tenant_id=?" if tenant_id is not None else "")
        values = (run_id, tenant_id) if tenant_id is not None else (run_id,)
        row = db.execute(f"SELECT * FROM runs WHERE {clause}", values).fetchone()
        if row is None:
            raise NotFoundError("run not found")
        return row

    def artifact_value(self, row) -> dict:
        object_key = row["object_key"]
        try:
            content = self.object_store.get_json(object_key) if object_key else json.loads(row["content"] or "null")
        except (FileNotFoundError, KeyError):
            content = {"unavailable": True, "objectKey": object_key}
        return {"id": row["id"], "name": row["name"], "type": row["type"], "mimeType": row["mime_type"], "step": row["step"],
                "content": content, "objectKey": object_key, "createdAt": row["created_at"]}

    def serialize(self, db, row) -> dict:
        metrics = db.execute("SELECT * FROM metrics WHERE run_id=? ORDER BY step", (row["id"],)).fetchall()
        events = db.execute("SELECT * FROM events WHERE run_id=? ORDER BY id", (row["id"],)).fetchall()
        artifacts = db.execute("SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at,id", (row["id"],)).fetchall()
        return {**run_value(row), "cursor": int(row["revision"]), "metrics": [metric_value(item) for item in metrics],
                "logs": [item["message"] for item in events], "events": [dict(item) for item in events],
                "artifacts": [self.artifact_value(item) for item in artifacts]}

    def get(self, run_id, tenant_id=None) -> dict:
        with self.transaction() as db:
            return self.serialize(db, self.require(db, run_id, tenant_id))

    def list(self, tenant_id, pagination: Pagination, *, summary=False, search="") -> dict:
        search = str(search).strip()[:200]
        where, values = "tenant_id=?", [tenant_id]
        if search:
            where += " AND LOWER(name) LIKE ? ESCAPE '!'"
            values.append("%" + search.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%")
        with self.transaction() as db:
            total = int(db.execute(f"SELECT COUNT(*) AS count FROM runs WHERE {where}", values).fetchone()["count"])
            counts = {item["status"]: int(item["count"]) for item in db.execute("SELECT status,COUNT(*) AS count FROM runs WHERE tenant_id=? GROUP BY status", (tenant_id,)).fetchall()}
            rows = db.execute(f"SELECT * FROM runs WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (*values, pagination.page_size, pagination.offset)).fetchall()
            if not summary:
                data = [self.serialize(db, row) for row in rows]
            else:
                # One latest metric per Run; no histories or object-store reads.
                data = []
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in ids)
                latest, metric_counts, artifact_counts = {}, {}, {}
                if ids:
                    latest = {item["run_id"]: item for item in db.execute(f"SELECT m.* FROM metrics m JOIN (SELECT run_id,MAX(step) AS step FROM metrics WHERE run_id IN ({placeholders}) GROUP BY run_id) last ON m.run_id=last.run_id AND m.step=last.step", ids).fetchall()}
                    metric_counts = {item["run_id"]: item["count"] for item in db.execute(f"SELECT run_id,COUNT(*) AS count FROM metrics WHERE run_id IN ({placeholders}) GROUP BY run_id", ids).fetchall()}
                    artifact_counts = {item["run_id"]: item["count"] for item in db.execute(f"SELECT run_id,COUNT(*) AS count FROM artifacts WHERE run_id IN ({placeholders}) GROUP BY run_id", ids).fetchall()}
                for row in rows:
                    last = latest.get(row["id"])
                    data.append({**run_value(row), "summary": True, "latestMetric": metric_value(last) if last else None,
                                 "metricCount": int(metric_counts.get(row["id"], 0)), "artifactCount": int(artifact_counts.get(row["id"], 0))})
            return {"data": data, "pagination": page_meta(pagination, total), "counts": counts}

    def changes(self, run_id, tenant_id, after: int, limit=100) -> dict:
        if after < 0 or not 1 <= limit <= 500:
            raise ValidationError("after must be non-negative and limit must be between 1 and 500")
        with self.transaction() as db:
            row = self.require(db, run_id, tenant_id)
            revision = int(row["revision"])
            if after > revision:
                raise ValidationError("cursor is ahead of this Run; reload its detail")
            changes = db.execute("SELECT revision,kind,item_key FROM run_changes WHERE run_id=? AND revision>? ORDER BY revision LIMIT ?", (run_id, after, limit)).fetchall()
            cursor = int(changes[-1]["revision"]) if changes else after
            result = {"id": run_id, "run": run_value(row), "cursor": cursor, "hasMore": cursor < revision,
                      "metrics": [], "events": [], "artifacts": [], "removedMetrics": [], "removedEvents": [], "removedArtifacts": []}
            latest = {(item["kind"].removesuffix("-delete"), item["item_key"]): item for item in changes}
            tables = {"metric": ("metrics", "step", "metrics", metric_value), "event": ("events", "id", "events", dict),
                      "artifact": ("artifacts", "id", "artifacts", self.artifact_value)}
            for (kind, key), change in latest.items():
                if kind == "run":
                    continue
                table, field, collection, serialize = tables[kind]
                item = db.execute(f"SELECT * FROM {table} WHERE run_id=? AND {field}=?", (run_id, int(key) if kind in {"metric", "event"} else key)).fetchone()
                if item is None:
                    result["removed" + collection.title()].append(int(key) if kind in {"metric", "event"} else key)
                else:
                    result[collection].append(serialize(item))
            return result

    @staticmethod
    def insert_metric(db, run_id, point):
        db.execute("""INSERT INTO metrics(run_id,step,train_loss,val_loss,accuracy,learning_rate,gpu,created_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id,step) DO UPDATE SET
            train_loss=COALESCE(excluded.train_loss,metrics.train_loss),val_loss=COALESCE(excluded.val_loss,metrics.val_loss),
            accuracy=COALESCE(excluded.accuracy,metrics.accuracy),learning_rate=COALESCE(excluded.learning_rate,metrics.learning_rate),
            gpu=COALESCE(excluded.gpu,metrics.gpu)""",
            (run_id, int(point["step"]), point.get("trainLoss"), point.get("valLoss"), point.get("accuracy"), point.get("learningRate"), point.get("gpu"), now()))

    @staticmethod
    def insert_event(db, run_id, event):
        db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, str(event.get("level") or "info"), str(event.get("message") or ""), now()))

    def create(self, tenant_id, body) -> dict:
        run_id = str(body.get("id") or "run_" + uuid.uuid4().hex[:12])
        timestamp = now()
        params = body.get("params") or {}
        if not isinstance(params, dict):
            raise ValidationError("params must be an object")
        with self.transaction(write=True) as db:
            db.execute("INSERT INTO runs(id,name,status,source,params,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?)",
                       (run_id, str(body.get("name") or run_id), "running", str(body.get("source") or "sdk"), json.dumps(params), timestamp, timestamp, tenant_id))
            self.insert_event(db, run_id, {"message": "Run 已创建"})
        return self.get(run_id, tenant_id)

    def mutate(self, run_id, tenant_id, operation, body) -> dict:
        self.get_owner(run_id, tenant_id)
        artifacts = body.get("artifacts", []) if operation == "batch" else [body] if operation == "artifacts" else []
        prepared = []
        for artifact in artifacts:
            event_id = str(artifact.get("eventId") or "") if operation == "batch" else ""
            artifact_id = "art_" + (hashlib.sha256(f"{run_id}:{event_id}".encode()).hexdigest()[:12] if event_id else uuid.uuid4().hex[:12])
            with self.transaction() as db:
                existing = db.execute("SELECT 1 FROM artifacts WHERE id=? AND run_id=?", (artifact_id, run_id)).fetchone()
            if existing:
                prepared.append((artifact_id, artifact, None))
                continue
            self.reserve_storage(tenant_id, len(json.dumps(artifact.get("content"), ensure_ascii=False).encode()))
            key = self.object_store.put_json(f"tenants/{tenant_id}/runs/{run_id}/{artifact_id}.json", artifact.get("content"))
            prepared.append((artifact_id, artifact, key))
        accepted_metrics = accepted_events = 0
        with self.transaction(write=True) as db:
            row = self.require(db, run_id, tenant_id)
            # Serialize concurrent writers for this Run, including in PostgreSQL.
            db.execute("UPDATE runs SET revision=revision WHERE id=? AND tenant_id=?", (run_id, tenant_id))
            if operation in {"metrics", "batch"}:
                points = body.get("metrics", []) if operation == "batch" else body.get("points") if isinstance(body.get("points"), list) else [body]
                for point in points:
                    if self.receipt(db, run_id, tenant_id, point, "metric", operation):
                        self.insert_metric(db, run_id, point)
                        accepted_metrics += 1
            if operation in {"events", "batch"}:
                events = body.get("events", []) if operation == "batch" else [body]
                for event in events:
                    if self.receipt(db, run_id, tenant_id, event, "event", operation):
                        self.insert_event(db, run_id, event)
                        accepted_events += 1
            if operation in {"params", "batch"}:
                update = body.get("params", {}) if operation == "batch" else body.get("params") if isinstance(body.get("params"), dict) else body
                if not isinstance(update, dict):
                    raise ValidationError("params must be an object")
                if update:
                    db.execute("UPDATE runs SET params=? WHERE id=?", (json.dumps({**json.loads(row["params"] or "{}"), **update}), run_id))
            for artifact_id, artifact, key in prepared:
                if key is not None:
                    db.execute("INSERT INTO artifacts(id,run_id,name,type,mime_type,step,content,object_key,created_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                               (artifact_id, run_id, str(artifact.get("name") or artifact_id), str(artifact.get("type") or "json"), str(artifact.get("mimeType") or "application/json"), artifact.get("step"), None, key, now()))
            if operation in {"finish", "fail", "stop", "resume"}:
                status = {"finish": "completed", "fail": "failed", "stop": "stopped", "resume": "running"}[operation]
                default_message = {"finish": "训练正常结束", "fail": "训练失败", "stop": "实验已停止", "resume": f"Run resumed from {body.get('checkpointKey') or 'latest checkpoint'}"}[operation]
                db.execute("UPDATE runs SET status=?,error_message=? WHERE id=?", (status, body.get("error") if status == "failed" else None, run_id))
                self.insert_event(db, run_id, {"level": "error" if status == "failed" else "info", "message": body.get("message") or default_message})
            db.execute("UPDATE runs SET updated_at=? WHERE id=?", (now(), run_id))
        if operation == "batch":
            return {"ok": True, "metrics": accepted_metrics, "events": accepted_events, "artifacts": [item[0] for item in prepared]}
        if operation == "events":
            return {"ok": True}
        if operation == "artifacts":
            return {"id": prepared[0][0]}
        return {"data": self.get(run_id, tenant_id)}

    def get_owner(self, run_id, tenant_id):
        with self.transaction() as db:
            self.require(db, run_id, tenant_id)

    @staticmethod
    def receipt(db, run_id, tenant_id, item, kind, operation):
        event_id = str(item.get("eventId") or "") if operation == "batch" else ""
        if not event_id:
            return True
        cursor = db.execute("INSERT INTO ml_ingestion_receipts(run_id,event_id,tenant_id,kind,created_at) VALUES(?,?,?,?,?) ON CONFLICT(run_id,event_id) DO NOTHING",
                            (run_id, event_id, tenant_id, kind, now()))
        return cursor.rowcount != 0
