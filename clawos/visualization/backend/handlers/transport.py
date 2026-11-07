"""Transport adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse
import base64
import json
import os
import re
import time
import uuid


class TransportHandler:
    runtime: HandlerRuntime

    def handle_one_request(self) -> None:
        started = time.perf_counter()
        try:
            super().handle_one_request()
        except self.runtime.ApplicationError as error:
            self._json({"error": error.message, "code": error.code, "detail": error.detail}, error.status)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error), "code": "validation_error"}, HTTPStatus.BAD_REQUEST)
        finally:
            method=getattr(self,"command","UNKNOWN");path=urlparse(getattr(self,"path","/")).path;status=str(getattr(self,"response_status",0) or 0)
            duration=time.perf_counter()-started
            self.runtime.inc("clawvision_http_requests_total",method=method,path=self._metric_path(path),status=status)
            self.runtime.observe("clawvision_http_request_duration_seconds",duration,method=method,path=self._metric_path(path))
            trace_id=getattr(self,"trace_id","");span_id=getattr(self,"span_id","")
            if trace_id and span_id:
                self.runtime.record_span("http.request",trace_id,span_id,duration,parent_span_id=getattr(self,"parent_span_id",""),status="error" if status.startswith("5") else "ok",method=method,path=self._metric_path(path),httpStatus=status)


    def parse_request(self) -> bool:
        parsed=super().parse_request()
        if parsed:
            context=self.runtime.adopt_traceparent(self.headers.get("traceparent"));self.trace_id=context["traceId"];self.span_id=context["spanId"];self.parent_span_id=context["parentSpanId"]
        return parsed


    @staticmethod
    def _metric_path(path: str) -> str:
        return re.sub(r"/(run|data|dsv|vexp|asset|agent|text3d|modelscene|meshjob|geometry|task|usr|tok|evalset|eval|scenario|synth)_[^/]+", r"/\1_:id", path)


    def _owned(self, table: str, item_id: str) -> bool:
        allowed = {"runs","jobs","datasets","visualization_specs","model_assets","studio_generations","parameter_snapshots","agent_runs","text3d_jobs","model_scenes","model_operation_jobs","asset_projects","scene_agent_runs","geometry_jobs","training_jobs","durable_tasks"}
        if table not in allowed: raise ValueError("unsupported tenant resource")
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            return bool(db.execute(f"SELECT 1 FROM {table} WHERE id=? AND tenant_id=?", (item_id, self.principal.tenant_id)).fetchone())


    def _guard_owned(self, table: str, item_id: str) -> bool:
        if self._owned(table, item_id): return True
        self._json({"error": "resource not found"}, HTTPStatus.NOT_FOUND); return False


    def _guard_write_path(self, path: str, body: dict) -> bool:
        # Publishing requires the same role/scope ceiling as approval, including
        # alternative catalog write paths that can move an asset to release.
        patch = body.get("patch") if isinstance(body.get("patch"), dict) else body
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        publishing = (bool(re.fullmatch(r"/api/model-assets/[^/]+/releases", path)) and body.get("status") in {"approved", "rejected"}) or (
            path.startswith("/api/model-assets") and (str(patch.get("stage", "")).strip() == "release" or str(metadata.get("assetStage", "")).strip() == "release"))
        if publishing and (not self.principal.permits("admin") or not self.principal.permits_scope("admin")):
            self.runtime.audit(self.principal, self.command, path, "denied", {"requiredRole": "admin", "requiredScope": "admin"})
            self._json({"error": "admin role and scope required for asset release"}, HTTPStatus.FORBIDDEN)
            return False
        patterns = (
            (r"/api/runs/([^/]+)(?:/.*)?", "runs"),
            (r"/api/model-assets/([^/]+)(?:/.*)?", "model_assets"),
            (r"/api/model-scenes/([^/]+)(?:/.*)?", "model_scenes"),
            (r"/api/model-operation-jobs/([^/]+)(?:/.*)?", "model_operation_jobs"),
            (r"/api/geometry-jobs/([^/]+)(?:/.*)?", "geometry_jobs"),
            (r"/api/training-jobs/([^/]+)(?:/.*)?", "training_jobs"),
            (r"/api/scene-agent-runs/([^/]+)(?:/.*)?", "scene_agent_runs"),
            (r"/api/studio/agent-runs/([^/]+)(?:/.*)?", "agent_runs"),
            (r"/api/studio/text-to-3d/([^/]+)(?:/.*)?", "text3d_jobs"),
        )
        collection_ids = {"batch", "garbage-collect", "providers"}
        for pattern, table in patterns:
            match = re.fullmatch(pattern, path)
            if match and match.group(1) not in collection_ids and not self._guard_owned(table, match.group(1)): return False
        if re.fullmatch(r"/api/runs/[^/]+/assets", path):
            asset_id = str(body.get("assetId") or "")
            if asset_id and not self._guard_owned("model_assets", asset_id): return False
        return True


    def _authorize(self, path: str, write: bool = False, admin: bool = False) -> bool:
        self.request_id=getattr(self,"request_id",None) or self.headers.get("X-Request-ID") or "req_"+uuid.uuid4().hex[:12]
        self.principal = self.runtime.authenticate(self.headers.get("Authorization"))
        if self.principal is None:
            self._json({"error": "authentication required"}, HTTPStatus.UNAUTHORIZED); return False
        role = "admin" if admin else "researcher" if write else "viewer"
        if not self.principal.permits(role):
            self.runtime.audit(self.principal, self.command, path, "denied", {"requiredRole": role}); self._json({"error": f"{role} role required"}, HTTPStatus.FORBIDDEN); return False
        scope = "admin" if admin else "write" if write else "read"
        if not self.principal.permits_scope(scope):
            self.runtime.audit(self.principal,self.command,path,"denied",{"requiredScope":scope});self._json({"error":f"{scope} scope required"},HTTPStatus.FORBIDDEN);return False
        if write: self.runtime.audit(self.principal, self.command, path, "requested")
        return True


    def log_message(self, pattern: str, *args) -> None:
        print(json.dumps({"time":self.runtime.now_iso(),"requestId":getattr(self,"request_id",None),"traceId":getattr(self,"trace_id",None),"spanId":getattr(self,"span_id",None),"remote":self.client_address[0],"message":pattern % args},ensure_ascii=False),flush=True)


    def send_response(self, code, message=None) -> None:
        self.response_status=int(code);super().send_response(code,message)


    def end_headers(self) -> None:
        trace_id=getattr(self,"trace_id","");span_id=getattr(self,"span_id","")
        if trace_id and span_id:
            self.send_header("traceparent",f"00-{trace_id}-{span_id}-01");self.send_header("X-Trace-ID",trace_id)
        super().end_headers()


    def _headers(self, status=HTTPStatus.OK, content_type="application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Range")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()


    def _json(self, value, status=HTTPStatus.OK) -> None:
        status_code = int(status)
        if isinstance(value, dict) and "error" in value and "status" not in value:
            value = self.runtime.problem_details(str(value["error"]), status_code, getattr(self, "request_id", "") or "", code=str(value.get("code") or "request_error"), detail=value.get("detail"))
        if getattr(self,"principal",None) is not None and self.command in {"POST","PATCH","DELETE"}:
            self.runtime.audit(self.principal,self.command,urlparse(self.path).path,"completed" if status_code<400 else "failed",{"status":status_code,"requestId":getattr(self,"request_id",None)})
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ("application/problem+json" if status_code >= 400 else "application/json") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Request-ID",getattr(self,"request_id","") or "")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


    def _binary(self, payload: bytes, mime: str, filename: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if filename: self.send_header("Content-Disposition", 'attachment; filename="'+filename+'"')
        self.end_headers()
        self.wfile.write(payload)


    def _stream_model_asset(self, asset_id: str, manifest_only: bool = False) -> None:
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            row = db.execute("SELECT * FROM model_assets WHERE id=? AND tenant_id=? AND deleted_at IS NULL", (asset_id, self.principal.tenant_id)).fetchone()
        if not row:
            return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        stored = self.runtime.OBJECT_STORE.get_json(row["object_key"])
        binary_key = stored.get("binaryKey")
        if binary_key:
            size = self.runtime.OBJECT_STORE.byte_size(binary_key)
        else:
            payload = base64.b64decode(stored["base64"], validate=True)
            size = len(payload)
        if manifest_only:
            return self._json({"data": {"assetId": asset_id, "name": row["name"], "format": row["format"], "byteSize": size,
                                         "contentUrl": f"/api/model-assets/{asset_id}/content", "acceptRanges": True,
                                         "resources": [{"name": item.get("name"), "mimeType": item.get("mimeType"), "byteSize": len(base64.b64decode(item.get("base64", ""))) if item.get("base64") else 0} for item in stored.get("resources", [])],
                                         "metadata": self.runtime.json_value(row["metadata"], {})}})
        start, end, status = 0, max(0, size - 1), HTTPStatus.OK
        range_header = self.headers.get("Range", "").strip()
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not match or (not match.group(1) and not match.group(2)):
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
            if not match.group(1):
                length = int(match.group(2)); start = max(0, size - length)
            else:
                start = int(match.group(1))
            if match.group(2) and match.group(1): end = min(size - 1, int(match.group(2)))
            if start >= size or end < start:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
            status = HTTPStatus.PARTIAL_CONTENT
        payload = self.runtime.OBJECT_STORE.get_range(binary_key, start, end) if binary_key else payload[start:end + 1]
        mime = {"glb": "model/gltf-binary", "gltf": "model/gltf+json", "obj": "text/plain", "stl": "model/stl"}.get(row["format"], "application/octet-stream")
        self.send_response(status); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(payload))); self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges"); self.send_header("Cache-Control", "private, max-age=3600"); self.end_headers(); self.wfile.write(payload)


    def _page_values(self, values: list, query: dict, *, default: int = 100) -> dict:
        pagination = self.runtime.parse_pagination(query, default=default)
        start = pagination.offset
        return {"data": values[start:start + pagination.page_size], "pagination": self.runtime.page_meta(pagination, len(values))}


    def _page_table(self, table: str, query: dict, *, default: int = 100, where: str = "tenant_id=?", values: tuple | list | None = None, order_by: str = "created_at DESC", select: str = "*", mapper=dict) -> dict:
        pagination = self.runtime.parse_pagination(query, default=default)
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            page = self.runtime.CollectionService.list(db, table, pagination, where=where, values=values or (self.principal.tenant_id,), order_by=order_by, select=select, mapper=mapper)
        return {"data": page.rows, "pagination": page.pagination}


    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        limit=max(1,min(512,int(os.environ.get("CLAWVISION_MAX_BODY_MB","384"))))
        if length > limit * 1024 * 1024:
            raise ValueError(f"request body exceeds {limit} MB")
        raw = self.rfile.read(length) if length else b"{}"
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value


    def do_OPTIONS(self) -> None:  # noqa: N802
        self._headers(HTTPStatus.NO_CONTENT)
