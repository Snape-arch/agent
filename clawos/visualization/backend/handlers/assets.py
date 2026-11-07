"""Assets adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from datetime import datetime, timezone
from http import HTTPStatus
import base64
import json
import time
import uuid


class AssetsHandler:
    runtime: HandlerRuntime

    def _run_timeline(self, run_id: str) -> None:
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            run = db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run: return self._json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
            metrics = db.execute("SELECT step,train_loss,val_loss,accuracy,learning_rate,gpu,created_at FROM metrics WHERE run_id=? ORDER BY step", (run_id,)).fetchall()
            artifacts = db.execute("SELECT id,name,type,mime_type,step,created_at FROM artifacts WHERE run_id=? ORDER BY COALESCE(step,0),created_at", (run_id,)).fetchall()
            links = db.execute("SELECT a.*,l.id AS link_id,l.role AS link_role,l.scene_id AS link_scene_id,l.step AS link_step,l.metadata AS link_metadata,l.created_at AS link_created_at FROM run_asset_links l JOIN model_assets a ON a.id=l.asset_id WHERE l.run_id=? ORDER BY COALESCE(l.step,0),l.created_at", (run_id,)).fetchall()
        frames: dict[int, dict] = {}
        for metric in metrics:
            step = int(metric["step"]); frames.setdefault(step, {"step": step, "metrics": {}, "artifacts": [], "assets": []})["metrics"] = {"trainLoss": metric["train_loss"], "valLoss": metric["val_loss"], "accuracy": metric["accuracy"], "learningRate": metric["learning_rate"], "gpu": metric["gpu"]}
        for artifact in artifacts:
            step = int(artifact["step"] or 0); frames.setdefault(step, {"step": step, "metrics": {}, "artifacts": [], "assets": []})["artifacts"].append({"id": artifact["id"], "name": artifact["name"], "type": artifact["type"], "mimeType": artifact["mime_type"], "createdAt": artifact["created_at"]})
        for link in links:
            step = int(link["link_step"] or 0); frames.setdefault(step, {"step": step, "metrics": {}, "artifacts": [], "assets": []})["assets"].append({"linkId": link["link_id"], "role": link["link_role"], "sceneId": link["link_scene_id"], "metadata": self.runtime.json_value(link["link_metadata"], {}), "asset": self.runtime.serialize_model_asset(link)})
        return self._json({"data": {"runId": run_id, "frames": [frames[key] for key in sorted(frames)], "maxStep": max(frames.keys(), default=0)}})


    def _create_asset_project(self, body: dict) -> None:
        name = str(body.get("name") or "").strip()
        if not name or len(name) > 120: raise ValueError("project name must contain 1 to 120 characters")
        project_id = f"project_{uuid.uuid4().hex[:12]}"; created = self.runtime.now_iso()
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            db.execute("INSERT INTO asset_projects(id,name,description,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?)", (project_id, name, str(body.get("description") or "")[:1000], created, created,self.principal.tenant_id))
        self._json({"data": {"id": project_id, "name": name, "description": str(body.get("description") or "")[:1000], "assetCount": 0, "createdAt": created, "updatedAt": created}}, HTTPStatus.CREATED)


    def _link_run_asset(self, run_id: str, body: dict) -> None:
        asset_id = str(body.get("assetId") or ""); role = str(body.get("role") or "checkpoint")
        if role not in {"input", "checkpoint", "output", "baseline", "overlay", "simulation"}: raise ValueError("unsupported asset role")
        link_id = f"link_{uuid.uuid4().hex[:12]}"; created = self.runtime.now_iso(); step = body.get("step")
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            if not db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone(): return self._json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
            if not db.execute("SELECT id FROM model_assets WHERE id=? AND deleted_at IS NULL", (asset_id,)).fetchone(): return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
            db.execute("INSERT INTO run_asset_links(id,run_id,asset_id,scene_id,role,step,metadata,created_at) VALUES(?,?,?,?,?,?,?,?)", (link_id, run_id, asset_id, body.get("sceneId"), role, int(step) if step is not None else None, json.dumps(body.get("metadata") if isinstance(body.get("metadata"), dict) else {}, ensure_ascii=False), created))
        self.runtime.bump(run_id); self._json({"data": {"id": link_id, "runId": run_id, "assetId": asset_id, "role": role, "step": step, "createdAt": created}}, HTTPStatus.CREATED)


    def _update_model_asset(self, asset_id: str, body: dict) -> None:
        allowed = {"name", "projectId", "folder", "stage", "tags", "thumbnailBase64"}
        if not any(key in body for key in allowed): raise ValueError("no supported asset fields supplied")
        updates: list[str] = []; values: list = []
        mapping = {"name": "name", "projectId": "project_id", "folder": "folder", "stage": "stage"}
        for key, column in mapping.items():
            if key in body:
                value = body[key]
                if key in {"name", "folder", "stage"} and not str(value).strip(): raise ValueError(f"{key} cannot be empty")
                updates.append(f"{column}=?"); values.append(str(value).strip() if value is not None else None)
        if "tags" in body:
            if not isinstance(body["tags"], list): raise ValueError("tags must be an array")
            updates.append("tags=?"); values.append(json.dumps(sorted({str(tag).strip() for tag in body["tags"] if str(tag).strip()})[:30], ensure_ascii=False))
        if "thumbnailBase64" in body:
            thumbnail={"base64":str(body["thumbnailBase64"])};self.runtime.reserve_storage(self.principal.tenant_id,len(json.dumps(thumbnail).encode()));key = self.runtime.OBJECT_STORE.put_json(f"tenants/{self.principal.tenant_id}/models/{asset_id}.thumbnail.json",thumbnail)
            updates.append("thumbnail_key=?"); values.append(key)
        updates.append("updated_at=?"); values.append(self.runtime.now_iso()); values.append(asset_id)
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            db.execute(f"UPDATE model_assets SET {','.join(updates)} WHERE id=? AND deleted_at IS NULL", values)
            row = db.execute("SELECT * FROM model_assets WHERE id=?", (asset_id,)).fetchone()
        if not row: return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        self._json({"data": self.runtime.serialize_model_asset(row, False, True)})


    def _batch_update_assets(self, body: dict) -> None:
        ids = [str(item) for item in body.get("ids", []) if item]; patch = body.get("patch") if isinstance(body.get("patch"), dict) else {}
        if not ids or len(ids) > 200: raise ValueError("ids must contain 1 to 200 assets")
        updated = []
        for asset_id in ids:
            if not self._owned("model_assets",asset_id): continue
            fields = {key: value for key, value in patch.items() if key in {"projectId", "folder", "stage", "tags"}}
            if body.get("renamePrefix"):
                with self.runtime.DB_LOCK, self.runtime.connect() as db: row = db.execute("SELECT name FROM model_assets WHERE id=?", (asset_id,)).fetchone()
                if row: fields["name"] = f"{str(body['renamePrefix'])}{row['name']}"
            if fields:
                mapping = {"name": "name", "projectId": "project_id", "folder": "folder", "stage": "stage", "tags": "tags"}; assignments=[]; values=[]
                for key, value in fields.items(): assignments.append(f"{mapping[key]}=?"); values.append(json.dumps(value, ensure_ascii=False) if key == "tags" else value)
                assignments.append("updated_at=?"); values.extend([self.runtime.now_iso(), asset_id])
                with self.runtime.DB_LOCK, self.runtime.connect() as db: db.execute(f"UPDATE model_assets SET {','.join(assignments)} WHERE id=? AND deleted_at IS NULL", values)
                updated.append(asset_id)
        self._json({"data": {"updated": updated, "count": len(updated)}})


    def _set_asset_archive(self, asset_id: str, archive: bool) -> None:
        timestamp = self.runtime.now_iso()
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            db.execute("UPDATE model_assets SET archived_at=?,updated_at=? WHERE id=? AND deleted_at IS NULL", (timestamp if archive else None, timestamp, asset_id)); row = db.execute("SELECT * FROM model_assets WHERE id=?", (asset_id,)).fetchone()
        return self._json({"data": self.runtime.serialize_model_asset(row) if row else None}, HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)


    def _delete_model_asset(self, asset_id: str, purge: bool) -> None:
        with self.runtime.DB_LOCK:
            return self._delete_model_asset_locked(asset_id, purge)


    def _delete_model_asset_locked(self, asset_id: str, purge: bool) -> None:
        references = self.runtime.model_asset_references(asset_id)
        if references: return self._json({"error": "asset is still referenced", "references": references}, HTTPStatus.CONFLICT)
        with self.runtime.DB_LOCK, self.runtime.connect() as db: row = db.execute("SELECT * FROM model_assets WHERE id=?", (asset_id,)).fetchone()
        if not row: return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        if not purge:
            timestamp = self.runtime.now_iso()
            with self.runtime.DB_LOCK, self.runtime.connect() as db: db.execute("UPDATE model_assets SET deleted_at=?,updated_at=? WHERE id=?", (timestamp, timestamp, asset_id))
            return self._json({"data": {"id": asset_id, "deletedAt": timestamp}})
        self.runtime.OBJECT_STORE.delete(row["object_key"])
        with self.runtime.DB_LOCK, self.runtime.connect() as db: db.execute("DELETE FROM model_assets WHERE id=?", (asset_id,))
        return self._json({"data": {"id": asset_id, "purged": True}})


    def _garbage_collect_assets(self, body: dict) -> None:
        with self.runtime.DB_LOCK:
            return self._garbage_collect_assets_locked(body)


    def _garbage_collect_assets_locked(self, body: dict) -> None:
        grace_hours = max(0, int(body.get("graceHours", 168))); cutoff = time.time() - grace_hours * 3600; purged=[]; protected=[]
        with self.runtime.DB_LOCK, self.runtime.connect() as db: rows = db.execute("SELECT * FROM model_assets WHERE deleted_at IS NOT NULL AND tenant_id=?",(self.principal.tenant_id,)).fetchall()
        for row in rows:
            try: deleted = datetime.fromisoformat(row["deleted_at"].replace("Z", "+00:00")).timestamp()
            except ValueError: deleted = 0
            refs = self.runtime.model_asset_references(row["id"])
            if refs or deleted > cutoff: protected.append(row["id"]); continue
            self.runtime.OBJECT_STORE.delete(row["object_key"])
            with self.runtime.DB_LOCK, self.runtime.connect() as db: db.execute("DELETE FROM model_assets WHERE id=?", (row["id"],))
            purged.append(row["id"])
        self._json({"data": {"purged": purged, "protected": protected, "graceHours": grace_hours}})


    def _create_asset_component(self, asset_id: str, body: dict) -> None:
        kind = str(body.get("type") or "")
        if kind not in {"mesh", "material", "texture"}: raise ValueError("component type must be mesh, material or texture")
        content = body.get("content"); component_id = f"component_{uuid.uuid4().hex[:12]}"; created = self.runtime.now_iso()
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            if not db.execute("SELECT id FROM model_assets WHERE id=?", (asset_id,)).fetchone(): return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
            latest = db.execute("SELECT MAX(version) AS version FROM asset_components WHERE asset_id=? AND component_type=?", (asset_id, kind)).fetchone(); version = int(latest["version"] or 0) + 1
        self.runtime.reserve_storage(self.principal.tenant_id,len(json.dumps(content,ensure_ascii=False).encode()));key = self.runtime.OBJECT_STORE.put_json(f"tenants/{self.principal.tenant_id}/models/{asset_id}/components/{component_id}.json", content)
        with self.runtime.DB_LOCK, self.runtime.connect() as db: db.execute("INSERT INTO asset_components(id,asset_id,component_type,version,object_key,metadata,created_at) VALUES(?,?,?,?,?,?,?)", (component_id, asset_id, kind, version, key, json.dumps(body.get("metadata") if isinstance(body.get("metadata"), dict) else {}, ensure_ascii=False), created))
        self._json({"data": {"id": component_id, "assetId": asset_id, "type": kind, "version": version, "createdAt": created}}, HTTPStatus.CREATED)


    def _create_asset_release(self, asset_id: str, body: dict) -> None:
        status = str(body.get("status") or "pending")
        if status not in {"pending", "approved", "rejected"}: raise ValueError("invalid release status")
        release_id = f"release_{uuid.uuid4().hex[:12]}"; created = self.runtime.now_iso()
        reviewer = self.principal.user_id if status != "pending" else ""
        note = str(body.get("note") or "")[:1000]
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            if not db.execute("SELECT id FROM model_assets WHERE id=? AND tenant_id=? AND deleted_at IS NULL", (asset_id, self.principal.tenant_id)).fetchone(): return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
            db.execute("INSERT INTO asset_releases(id,asset_id,status,reviewer,note,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (release_id, asset_id, status, reviewer, note, created, created))
            if status == "approved": db.execute("UPDATE model_assets SET stage='release',updated_at=? WHERE id=?", (created, asset_id))
        self._json({"data": {"id": release_id, "assetId": asset_id, "status": status, "reviewer": reviewer, "note": note, "createdAt": created, "updatedAt": created}}, HTTPStatus.CREATED)


    def _create_model_asset(self, body: dict) -> None:
        asset_format = str(body.get("format") or "").lower()
        if asset_format not in {"glb", "gltf", "obj", "stl", "ply", "step", "iges", "brep"}:
            raise ValueError("format must be glb, gltf, obj, stl, ply, step, iges or brep")
        content = body.get("content")
        resources = body.get("resources") if isinstance(body.get("resources"), list) else []
        if not isinstance(content, str) or not content:
            raise ValueError("content must be a base64 string")
        if len(resources) > 64 or any(not isinstance(item, dict) or not item.get("name") or not item.get("base64") for item in resources):
            raise ValueError("resources must contain at most 64 named base64 files")
        asset=self.runtime.store_model_asset(str(body.get("name") or f"model.{asset_format}"),asset_format,base64.b64decode(content,validate=True),body.get("metadata") if isinstance(body.get("metadata"),dict) else {},resources,self.principal.tenant_id)
        self._json({"data":asset},HTTPStatus.CREATED)
