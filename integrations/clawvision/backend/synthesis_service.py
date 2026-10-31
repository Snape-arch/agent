"""Durable, fenced scene rendering and immutable synthetic data exports."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone

from api_contract import page_meta
from errors import ConflictError, NotFoundError, ValidationError
from evaluation_service import canonical, digest
from observability import current_traceparent, inc
from scenario_service import ScenarioService, integer
from security import reserve_storage
import synthetic_renderer as renderer

MAX_OUTPUT = 64 * 1024 * 1024
TERMINAL = {"completed", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


class LeaseLost(Exception):
    pass


class SynthesisService:
    def __init__(self, connect, object_store, lock):
        self.connect, self.store, self.lock = connect, object_store, lock
        self.scenarios = ScenarioService(connect, object_store, lock)

    @staticmethod
    def _row(db, tenant, job_id):
        row = db.execute("SELECT j.*,t.status AS task_status,t.error AS task_error,t.attempts FROM synthesis_jobs j JOIN durable_tasks t ON t.id=j.task_id WHERE j.id=? AND j.tenant_id=?", (job_id, tenant)).fetchone()
        if not row:
            raise NotFoundError("synthesis job not found")
        return row

    @staticmethod
    def _json(row):
        status = row["status"]
        if row["task_status"] in {"cancelled", "dead-letter"} and status != "completed":
            status = "cancelled" if row["task_status"] == "cancelled" else "failed"
        elif row["task_status"] == "queued" and status != "completed":
            status = "queued"
        elif row["task_status"] == "leased" and status != "completed":
            status = "running"
        return {"id": row["id"], "scenarioId": row["scenario_id"], "taskId": row["task_id"], "status": status,
                "total": row["total"], "completed": row["completed"], "accepted": row["accepted"],
                "rejected": row["completed"] - row["accepted"], "attempts": row["attempts"],
                "digest": row["result_digest"], "config": json.loads(row["config_json"]),
                "error": None if status == "completed" else row["error"] or row["task_error"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}

    @staticmethod
    def _quota(db, tenant):
        if tenant == "default": return
        # Serialize budget reservations across PostgreSQL API replicas.
        suffix = " FOR UPDATE" if db.kind == "postgres" else ""
        quota = db.execute("SELECT max_concurrent_jobs FROM tenant_quotas WHERE tenant_id=?"+suffix, (tenant,)).fetchone()
        active = db.execute("SELECT COUNT(*) AS n FROM durable_tasks WHERE tenant_id=? AND status IN ('queued','leased')", (tenant,)).fetchone()["n"]
        if quota and active >= quota["max_concurrent_jobs"]: raise PermissionError("tenant concurrent task quota exceeded")

    def create(self, tenant, scenario_id, request):
        if not isinstance(request, dict) or set(request) - {"variantIndices", "minVisiblePixels", "minVisibleFraction", "rejectClipped"}:
            raise ValidationError("invalid synthesis request fields")
        renderer.numpy()  # Missing provider must fail before enqueueing.
        plan = self.scenarios.get(tenant, scenario_id)
        indices = request.get("variantIndices", list(range(plan["variantCount"])))
        if not isinstance(indices, list) or not 1 <= len(indices) <= 64:
            raise ValidationError("select 1 to 64 variant indices for each render job")
        indices = sorted(integer(v, "variant index", 0, plan["variantCount"]-1) for v in indices)
        if len(set(indices)) != len(indices):
            raise ValidationError("variant indices must be unique")
        pixels = integer(request.get("minVisiblePixels", 64), "minVisiblePixels", 1, 512*512)
        fraction = request.get("minVisibleFraction", .2)
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 <= fraction <= 1:
            raise ValidationError("minVisibleFraction must be a finite number between 0 and 1")
        reject = request.get("rejectClipped", True)
        if not isinstance(reject, bool):
            raise ValidationError("rejectClipped must be a boolean")
        config = {"scenarioDigest": plan["digest"], "renderer": renderer.RENDERER, "rendererSourceDigest": renderer.source_digest(),
                  "numpyVersion": renderer.numpy().__version__, "variantIndices": indices, "minVisiblePixels": pixels,
                  "minVisibleFraction": fraction, "rejectClipped": reject, "resolution": [512, 512],
                  "shading": "two-sided-opaque-Lambert-BlinnPhong-ACES-approx; no textures or shadows"}
        request_digest = digest({"scenarioId": scenario_id, "config": config})
        job_id = "synth_" + hashlib.sha256((tenant+":"+request_digest).encode()).hexdigest()[:32]
        task_id, timestamp = "task_" + job_id[6:], now()
        with self.lock, self.connect() as db:
            existing = db.execute("SELECT id FROM synthesis_jobs WHERE tenant_id=? AND request_digest=?", (tenant, request_digest)).fetchone()
            if existing:
                return self._json(self._row(db, tenant, existing["id"]))
            self._quota(db, tenant)
            payload = {"scenarioId": scenario_id}
            if current_traceparent(): payload["_traceparent"] = current_traceparent()
            # Queue and resource are committed together; no lost enqueue window.
            db.execute("INSERT INTO durable_tasks(id,tenant_id,kind,resource_id,payload,status,priority,attempts,max_attempts,idempotency_key,created_at,updated_at) VALUES(?,?,'synthesis',?,?,'queued',50,0,3,?,?,?)",
                       (task_id, tenant, job_id, canonical(payload), "synthesis:"+job_id, timestamp, timestamp))
            db.execute("INSERT INTO durable_task_events(id,task_id,event,detail,created_at) VALUES(?,?,'queued',?,?)",
                       ("tevt_"+uuid.uuid4().hex[:16], task_id, canonical({"kind": "synthesis"}), timestamp))
            db.execute("INSERT INTO synthesis_jobs(id,tenant_id,scenario_id,task_id,request_digest,config_json,status,total,created_at,updated_at) VALUES(?,?,?,?,?,?,'queued',?,?,?)",
                       (job_id, tenant, scenario_id, task_id, request_digest, canonical(config), len(indices), timestamp, timestamp))
            result = self._json(self._row(db, tenant, job_id))
        inc("clawvision_tasks_enqueued_total", kind="synthesis")
        return result

    def get(self, tenant, job_id):
        with self.connect() as db:
            return self._json(self._row(db, tenant, job_id))

    def list(self, tenant, pagination, scenario_id):
        with self.connect() as db:
            ScenarioService._row(db, tenant, scenario_id)
            where = "j.tenant_id=? AND j.scenario_id=?"
            total = db.execute(f"SELECT COUNT(*) AS n FROM synthesis_jobs j WHERE {where}", (tenant, scenario_id)).fetchone()["n"]
            rows = db.execute(f"SELECT j.*,t.status AS task_status,t.error AS task_error,t.attempts FROM synthesis_jobs j JOIN durable_tasks t ON t.id=j.task_id WHERE {where} ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?",
                              (tenant, scenario_id, pagination.page_size, pagination.offset)).fetchall()
        return {"data": [self._json(row) for row in rows], "pagination": page_meta(pagination, total)}

    @staticmethod
    def _frame(row):
        return {"variantIndex": row["variant_index"], "accepted": bool(row["accepted"]),
                "annotation": json.loads(row["annotation_json"]), "artifacts": json.loads(row["artifacts_json"])}

    def frames(self, tenant, job_id, pagination):
        with self.connect() as db:
            self._row(db, tenant, job_id)
            total = db.execute("SELECT COUNT(*) AS n FROM synthesis_frames WHERE job_id=?", (job_id,)).fetchone()["n"]
            rows = db.execute("SELECT * FROM synthesis_frames WHERE job_id=? ORDER BY variant_index LIMIT ? OFFSET ?", (job_id, pagination.page_size, pagination.offset)).fetchall()
        result = [self._frame(row) for row in rows]
        for frame in result:
            frame["artifacts"] = {kind: {key: value for key, value in info.items() if key != "key"} for kind, info in frame["artifacts"].items()}
        return {"data": result, "pagination": page_meta(pagination, total)}

    def _verified(self, info):
        try:
            if self.store.byte_size(info["key"]) != info["byteSize"]:
                raise ConflictError("synthetic artifact size changed")
            content = self.store.get_bytes(info["key"])
        except FileNotFoundError as error:
            raise ConflictError("synthetic artifact is missing") from error
        if hashlib.sha256(content).hexdigest() != info["sha256"]:
            raise ConflictError("synthetic artifact hash changed")
        return content

    def action(self, tenant, job_id, action):
        with self.lock, self.connect() as db:
            row = self._row(db, tenant, job_id)
            status = self._json(row)["status"]
            if status == "completed": raise ConflictError("completed synthetic datasets are immutable")
            timestamp = now()
            if action == "cancel":
                db.execute("UPDATE durable_tasks SET status='cancelled',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?", (timestamp, row["task_id"]))
                db.execute("UPDATE synthesis_jobs SET status='cancelled',updated_at=? WHERE id=?", (timestamp, job_id))
            elif action == "retry":
                if row["task_status"] not in {"cancelled", "dead-letter", "failed"}:
                    raise ConflictError("only terminal failed or cancelled jobs can be retried")
                self._quota(db, tenant)
                db.execute("UPDATE durable_tasks SET status='queued',attempts=0,error=NULL,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?", (timestamp, row["task_id"]))
                db.execute("UPDATE synthesis_jobs SET status='queued',error=NULL,updated_at=? WHERE id=?", (timestamp, job_id))
            else: raise ValidationError("unsupported synthesis action")
            db.execute("INSERT INTO durable_task_events(id,task_id,event,detail,created_at) VALUES(?,?,?,?,?)",
                       ("tevt_"+uuid.uuid4().hex[:16], row["task_id"], action, "{}", timestamp))
            return self._json(self._row(db, tenant, job_id))

    def artifact(self, tenant, job_id, index, kind):
        if kind not in {"image", "mask", "amodalMask"}:
            raise NotFoundError("synthetic artifact not found")
        with self.connect() as db:
            self._row(db, tenant, job_id)
            row = db.execute("SELECT artifacts_json FROM synthesis_frames WHERE job_id=? AND variant_index=?", (job_id, index)).fetchone()
            if not row: raise NotFoundError("synthetic frame not found")
        return self._verified(json.loads(row["artifacts_json"])[kind])

    @staticmethod
    def _fence(db, task_id, owner):
        # The conditional UPDATE below holds the lease row until transaction end.
        updated = db.execute("UPDATE durable_tasks SET heartbeat_at=heartbeat_at WHERE id=? AND lease_owner=? AND status='leased' AND lease_expires_at>?", (task_id, owner, now()))
        if updated.rowcount != 1: raise LeaseLost("render lease expired or was cancelled")

    def execute(self, tenant, job_id, owner):
        with self.connect() as db:
            row = self._row(db, tenant, job_id)
            if row["status"] == "completed": return {"jobId": job_id, "digest": row["result_digest"]}
            self._fence(db, row["task_id"], owner)
            db.execute("UPDATE synthesis_jobs SET status='running',error=NULL,updated_at=? WHERE id=?", (now(), job_id))
        task_id, config = row["task_id"], json.loads(row["config_json"])
        deadline = time.monotonic() + 180
        attempt = uuid.uuid4().hex
        last_check = 0
        def check():
            nonlocal last_check
            if time.monotonic() - last_check < .25: return
            with self.connect() as db:
                task = db.execute("SELECT status,lease_owner,lease_expires_at FROM durable_tasks WHERE id=?", (task_id,)).fetchone()
            if not task or task["status"] != "leased" or task["lease_owner"] != owner or task["lease_expires_at"] <= now():
                raise LeaseLost("render lease expired or was cancelled")
            last_check = time.monotonic()
        try:
            if config["rendererSourceDigest"] != renderer.source_digest() or config["numpyVersion"] != renderer.numpy().__version__:
                raise ConflictError("renderer environment changed; create a new render job")
            plan = self.scenarios.get(tenant, row["scenario_id"])
            if plan["digest"] != config["scenarioDigest"] or digest(plan["manifest"]) != plan["digest"]:
                raise ConflictError("saved scene manifest changed")
            verified = self.scenarios.preview_asset(tenant, plan["id"])
            mesh = renderer.load_mesh(base64.b64decode(verified["base64"]), verified["format"])
            if len(mesh[1]) * len(config["variantIndices"]) > 400000:
                raise ValidationError("render batch exceeds 400000 triangle-variants; select fewer variants")
            with self.connect() as db:
                previous = {item["variant_index"]: self._frame(item) for item in db.execute("SELECT * FROM synthesis_frames WHERE job_id=?", (job_id,)).fetchall()}
            byte_total = sum(info["byteSize"] for frame in previous.values() for info in frame["artifacts"].values())
            for index in config["variantIndices"]:
                check()
                if index in previous:
                    for info in previous[index]["artifacts"].values(): self._verified(info)
                    continue
                variant = plan["manifest"]["variants"][index]
                outputs, annotation = renderer.render(mesh, variant["parameters"], plan["manifest"]["config"], check=check, deadline=deadline)
                reasons = []
                if annotation["visiblePixels"] < config["minVisiblePixels"]: reasons.append("insufficient-visible-pixels")
                if annotation["visibleFraction"] < config["minVisibleFraction"]: reasons.append("excessive-occlusion")
                if config["rejectClipped"] and annotation["clipped"]: reasons.append("object-touches-image-border")
                annotation.update({"label": plan["source"]["label"], "labelSource": "user-associated-asset", "rejectionReasons": reasons,
                                   "parameters": variant["parameters"]})
                artifacts = {}
                byte_total += sum(len(content) for content in outputs.values())
                if byte_total > MAX_OUTPUT: raise ValidationError("synthetic artifact batch exceeds 64 MB")
                reserve_storage(tenant, sum(len(content) for content in outputs.values()))
                for kind, content in outputs.items():
                    key = f"tenants/{tenant}/synthesis/{job_id}/{attempt}/{index}-{kind}.png"
                    self.store.put_bytes(key, content, "image/png")
                    artifacts[kind] = {"key": key, "sha256": hashlib.sha256(content).hexdigest(), "byteSize": len(content),
                                       "url": f"/api/evaluation/synthesis/{job_id}/frames/{index}/{kind}"}
                with self.connect() as db:
                    self._fence(db, task_id, owner)
                    db.execute("INSERT INTO synthesis_frames(job_id,variant_index,accepted,annotation_json,artifacts_json) VALUES(?,?,?,?,?)",
                               (job_id, index, int(not reasons), canonical(annotation), canonical(artifacts)))
                    db.execute("UPDATE synthesis_jobs SET completed=completed+1,accepted=accepted+?,updated_at=? WHERE id=?", (int(not reasons), now(), job_id))
            with self.connect() as db:
                frames = [self._frame(item) for item in db.execute("SELECT * FROM synthesis_frames WHERE job_id=? ORDER BY variant_index", (job_id,)).fetchall()]
            manifest = {"schemaVersion": "clawvision.synthetic-dataset/1", "usage": "synthetic-training-only", "scenarioId": plan["id"],
                        "scenarioDigest": plan["digest"], "source": plan["source"], "asset": plan["asset"], "renderConfig": config,
                        "frames": frames, "coco": self._coco(frames, plan["source"]["label"])}
            manifest_bytes = canonical(manifest).encode()
            # Reserve headroom for duplicate COCO metadata and ZIP directory entries.
            if byte_total + 2*len(manifest_bytes) + 65536 > MAX_OUTPUT: raise ValidationError("synthetic manifest and artifacts exceed 64 MB")
            reserve_storage(tenant, len(manifest_bytes))
            manifest_key = f"tenants/{tenant}/synthesis/{job_id}/{attempt}/manifest.json"
            self.store.put_bytes(manifest_key, manifest_bytes, "application/json")
            result_digest = hashlib.sha256(manifest_bytes).hexdigest()
            with self.connect() as db:
                self._fence(db, task_id, owner)
                db.execute("UPDATE synthesis_jobs SET status='completed',result_digest=?,manifest_key=?,error=NULL,updated_at=? WHERE id=?",
                           (result_digest, manifest_key, now(), job_id))
            return {"jobId": job_id, "digest": result_digest}
        except Exception as error:
            try:
                with self.connect() as db:
                    self._fence(db, task_id, owner)
                    db.execute("UPDATE synthesis_jobs SET status='failed',error=?,updated_at=? WHERE id=?", (str(error)[:2000], now(), job_id))
            except LeaseLost:
                pass
            raise

    @staticmethod
    def _coco(frames, label):
        images, annotations = [], []
        for frame in frames:
            if not frame["accepted"]: continue
            index, annotation = frame["variantIndex"], frame["annotation"]
            images.append({"id": index+1, "file_name": f"accepted/images/{index:04d}.png", "width": 512, "height": 512})
            annotations.append({"id": index+1, "image_id": index+1, "category_id": 1, "bbox": annotation["bbox"],
                                "area": annotation["visiblePixels"], "iscrowd": 0, "segmentation": annotation["segmentation"]})
        return {"images": images, "annotations": annotations, "categories": [{"id": 1, "name": label}]}

    def manifest(self, tenant, job_id):
        with self.connect() as db:
            row = self._row(db, tenant, job_id)
        if row["status"] != "completed": raise ConflictError("synthetic dataset is not complete")
        try:
            if self.store.byte_size(row["manifest_key"]) > MAX_OUTPUT: raise ConflictError("synthetic manifest exceeds size limit")
            content = self.store.get_bytes(row["manifest_key"])
        except FileNotFoundError as error:
            raise ConflictError("synthetic manifest is missing") from error
        if len(content) > MAX_OUTPUT or hashlib.sha256(content).hexdigest() != row["result_digest"]:
            raise ConflictError("synthetic manifest hash changed")
        return {"id": job_id, "digest": row["result_digest"], "manifest": json.loads(content)}

    def package(self, tenant, job_id):
        result = self.manifest(tenant, job_id)
        manifest = result["manifest"]
        buffer, total = io.BytesIO(), 0
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            def write(name, value):
                nonlocal total
                total += len(value) + 2*len(name.encode()) + 128
                if total > MAX_OUTPUT: raise ValidationError("synthetic package exceeds 64 MB")
                # Fixed timestamp and permissions make repeat exports stable.
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.external_attr = 0o644 << 16
                archive.writestr(info, value)
            for frame in manifest["frames"]:
                prefix, index = "accepted" if frame["accepted"] else "rejected", frame["variantIndex"]
                for kind, folder in (("image", "images"), ("mask", "masks"), ("amodalMask", "amodal-masks")):
                    content = self._verified(frame["artifacts"][kind])
                    write(f"{prefix}/{folder}/{index:04d}.png", content)
            write("manifest.json", canonical(result).encode())
            write("annotations.json", canonical(manifest["coco"]).encode())
            # Flat labeled rows are also useful for the current classification workflow.
            write("classification.json", canonical([{"id": str(item["id"]), "label": manifest["source"]["label"], "image": item["file_name"]}
                                                    for item in manifest["coco"]["images"]]).encode())
        return buffer.getvalue()


def execute_synthesis_job(job_id, tenant, owner=None):
    from database import connect
    from server import DB_LOCK, OBJECT_STORE
    owner = owner or f"worker-{os.getpid()}-{threading.get_ident()}"
    return SynthesisService(connect, OBJECT_STORE, DB_LOCK).execute(tenant, job_id, owner)
