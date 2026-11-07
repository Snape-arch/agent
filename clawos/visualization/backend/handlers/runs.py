"""Runs adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
import json
import os
import threading
import time
import uuid


class RunsHandler:
    runtime: HandlerRuntime

    def _save_three_telemetry(self, body: dict) -> None:
        label = str(body.get("label") or "3d-view")[:100]
        session_id = str(body.get("sessionId") or "")[:100]
        if not session_id:
            raise ValueError("sessionId is required")
        asset_id = str(body.get("assetId") or "") or None
        if asset_id and not self._owned("model_assets", asset_id):
            return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        number = lambda name, default=0: float(body.get(name) if body.get(name) is not None else default)
        item_id = "three_" + uuid.uuid4().hex[:12]; created = self.runtime.now_iso(); enriched={**body,"nativeGpu":self.runtime.native_gpu_telemetry()}
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            db.execute("""INSERT INTO three_telemetry(id,tenant_id,asset_id,label,session_id,frames,average_frame_ms,max_frame_ms,gpu_frame_ms,gpu_vendor,gpu_renderer,webgl_version,geometries,textures,draw_calls,triangles,heap_bytes,transferred_bytes,context_losses,payload,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (item_id, self.principal.tenant_id, asset_id, label, session_id, int(number("frames")), number("averageFrameMs"), number("maxFrameMs"), number("gpuFrameMs") if body.get("gpuFrameMs") is not None else None,
               str(body.get("gpuVendor") or "")[:300], str(body.get("gpuRenderer") or "")[:300], str(body.get("webglVersion") or "")[:100], int(number("geometries")), int(number("textures")), int(number("drawCalls")), int(number("triangles")), int(number("heapBytes")), int(number("transferredBytes")), int(number("contextLosses")), json.dumps(enriched, ensure_ascii=False), created))
        self._json({"data": {"id": item_id, "nativeGpu":enriched["nativeGpu"], "createdAt": created}}, HTTPStatus.CREATED)


    def _create_run(self, body: dict) -> None:
        run = self.runtime.run_service().create(self.principal.tenant_id, body)
        self.runtime.bump(run["id"])
        self._json({"data": run}, HTTPStatus.CREATED)


    def _create_job(self, body: dict) -> None:
        self.runtime.check_run_quota(self.principal)
        configs = body.get("configs") if isinstance(body.get("configs"), list) else []
        if not configs or len(configs) > 100:
            return self._json({"error": "configs must contain 1 to 100 parameter sets"}, HTTPStatus.BAD_REQUEST)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        concurrency = max(1, min(int(body.get("concurrency") or 2), int(os.environ.get("CLAWVISION_MAX_CONCURRENCY", "3"))))
        estimate_seconds = float(body.get("estimateSeconds") or sum(float(config.get("epochs", 40)) * 0.045 for config in configs) / concurrency)
        estimated_cost = float(body.get("estimatedCost") or estimate_seconds / 3600 * 0.65)
        created_at = self.runtime.now_iso()
        baseline_run_id = body.get("baselineRunId")
        if baseline_run_id and not self._owned("runs", str(baseline_run_id)):
            raise PermissionError("baseline run is outside the current tenant")
        kind = str(body.get("kind") or "single")
        provider = str(body.get("trainingProvider") or "simulator")
        catalog = {item["id"]: item for item in self.runtime.training_provider_catalog()}
        if provider not in catalog or not catalog[provider]["configured"]:
            raise ValueError(f"training provider is unavailable: {provider}")
        timeout = max(30, min(86400, int(body.get("timeoutSeconds") or 900)))
        run_ids = []
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,kind,status,baseline_run_id,payload,total_runs,completed_runs,concurrency,estimate_seconds,estimated_cost,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, kind, "queued", baseline_run_id, json.dumps(body, ensure_ascii=False), len(configs), 0, concurrency, estimate_seconds, estimated_cost, created_at, created_at,self.principal.tenant_id),
            )
            for index, config in enumerate(configs):
                run_id = f"run_{uuid.uuid4().hex[:12]}"
                name = str(body.get("name") or f"{kind}-{job_id[-5:]}") + (f"-{index + 1:02d}" if len(configs) > 1 else "")
                params = {**config, "_jobId": job_id, "_baselineRunId": baseline_run_id,
                          "_execution": {"provider": provider, "synthetic": provider == "simulator"}}
                db.execute("INSERT INTO runs(id,name,status,source,params,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?)", (run_id, name, "queued", "parameter-lab", json.dumps(params), created_at, created_at,self.principal.tenant_id))
                db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", f"已进入队列 · job {job_id}", created_at))
                if provider != "simulator":
                    training_id = f"train_{uuid.uuid4().hex[:12]}"
                    db.execute("INSERT INTO training_jobs(id,run_id,parent_job_id,provider,status,stage,progress,cancel_requested,timeout_seconds,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (training_id, run_id, job_id, provider, "queued", "queued", 0, 0, timeout, created_at, created_at,self.principal.tenant_id))
                run_ids.append(run_id)
            db.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?", ("running", self.runtime.now_iso(), job_id))
        semaphore = threading.Semaphore(concurrency)
        for run_id, config in zip(run_ids, configs):
            if provider == "simulator":
                task=self.runtime.enqueue_task(self.principal.tenant_id,"training",run_id,{"runId":run_id,"provider":provider},f"training:{run_id}")
                self.runtime.submit_durable(task,self.runtime.execute_queued_run,run_id,config,job_id,semaphore)
            else:
                with self.runtime.DB_LOCK, self.runtime.connect() as db: training = db.execute("SELECT id FROM training_jobs WHERE run_id=?", (run_id,)).fetchone()
                task=self.runtime.enqueue_task(self.principal.tenant_id,"training",training["id"],{"runId":run_id,"provider":provider},f"training:{training['id']}")
                self.runtime.submit_durable(task,self.runtime.execute_real_training,training["id"],run_id,config,job_id,provider,semaphore,timeout)
        self._json({"data": {"id": job_id, "runIds": run_ids, "kind": kind, "status": "running", "provider": provider, "totalRuns": len(run_ids), "concurrency": concurrency, "estimateSeconds": estimate_seconds, "estimatedCost": estimated_cost}}, HTTPStatus.CREATED)


    def _save_training_lineage(self, run_id: str, body: dict) -> None:
        framework=str(body.get("framework") or "custom").lower()
        if framework not in {"custom","pytorch","lightning","transformers","keras","jax"}: raise ValueError("unsupported training framework")
        timestamp=self.runtime.now_iso(); environment=body.get("environment") if isinstance(body.get("environment"),dict) else {}
        with self.runtime.DB_LOCK,self.runtime.connect() as db:
            db.execute("""INSERT INTO training_lineage(run_id,tenant_id,framework,code_ref,dataset_ref,environment,parent_run_id,resume_checkpoint_key,world_size,rank_count,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET framework=excluded.framework,code_ref=excluded.code_ref,dataset_ref=excluded.dataset_ref,environment=excluded.environment,parent_run_id=excluded.parent_run_id,resume_checkpoint_key=excluded.resume_checkpoint_key,world_size=excluded.world_size,rank_count=excluded.rank_count,updated_at=excluded.updated_at""",
              (run_id,self.principal.tenant_id,framework,body.get("codeRef"),body.get("datasetRef"),json.dumps(environment,ensure_ascii=False),body.get("parentRunId"),body.get("resumeCheckpointKey"),max(1,int(body.get("worldSize") or 1)),max(1,int(body.get("rankCount") or 1)),timestamp,timestamp))
            row=db.execute("SELECT * FROM training_lineage WHERE run_id=? AND tenant_id=?",(run_id,self.principal.tenant_id)).fetchone()
        self._json({"data":{**dict(row),"environment":self.runtime.json_value(row["environment"],{})}},HTTPStatus.CREATED)


    def _log_metrics(self, run_id: str, body: dict) -> None:
        result = self.runtime.run_service().mutate(run_id, self.principal.tenant_id, "metrics", body)
        self.runtime.bump(run_id)
        self._json(result)


    def _log_params(self, run_id: str, body: dict) -> None:
        result = self.runtime.run_service().mutate(run_id, self.principal.tenant_id, "params", body)
        self.runtime.bump(run_id)
        self._json(result)


    def _log_event(self, run_id: str, body: dict) -> None:
        result = self.runtime.run_service().mutate(run_id, self.principal.tenant_id, "events", body)
        self.runtime.bump(run_id)
        self._json(result, HTTPStatus.CREATED)


    def _log_artifact(self, run_id: str, body: dict) -> None:
        result = self.runtime.run_service().mutate(run_id, self.principal.tenant_id, "artifacts", body)
        self.runtime.bump(run_id)
        self._json(result, HTTPStatus.CREATED)


    def _batch(self, run_id: str, body: dict) -> None:
        result = self.runtime.run_service().mutate(run_id, self.principal.tenant_id, "batch", body)
        self.runtime.bump(run_id)
        self._json(result)


    def _resume_run(self, run_id: str, body: dict) -> None:
        result = self.runtime.run_service().mutate(run_id, self.principal.tenant_id, "resume", body)
        self.runtime.bump(run_id)
        self._json(result)


    def _set_status(self, run_id: str, status: str, body: dict) -> None:
        operation = {"completed": "finish", "failed": "fail", "stopped": "stop"}[status]
        result = self.runtime.run_service().mutate(run_id, self.principal.tenant_id, operation, body)
        self.runtime.bump(run_id)
        self._json(result)


    def _stream(self, run_id: str, query: dict | None = None) -> None:
        query = query or {}
        incremental = (query.get("incremental") or [""])[0] == "1"
        cursor = int((query.get("after") or [self.headers.get("Last-Event-ID", "0")])[0])
        service = self.runtime.run_service()
        # Validate the cursor and ownership before sending streaming headers.
        pending = service.changes(run_id, self.principal.tenant_id, cursor)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        version = -1
        heartbeat = time.monotonic()
        try:
            for _ in range(90):
                if pending is None:
                    pending = service.changes(run_id, self.principal.tenant_id, cursor)
                current = pending["run"]["revision"]
                if current != version or (incremental and pending["cursor"] > cursor):
                    item = pending if incremental else service.get(run_id, self.principal.tenant_id)
                    payload = json.dumps(item, ensure_ascii=False)
                    event = "run-delta" if incremental else "run"
                    self.wfile.write(f"id: {item.get('cursor', current)}\nevent: {event}\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    version = current
                    cursor = item["cursor"]
                    heartbeat = time.monotonic()
                elif time.monotonic() - heartbeat >= 15:
                    # Keep idle connections alive and observe disconnected clients.
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    heartbeat = time.monotonic()
                if incremental and pending["hasMore"]:
                    pending = None
                    continue
                if pending["run"]["status"] in {"completed", "stopped", "failed"}:
                    break
                pending = None
                with self.runtime.RUN_CONDITION:
                    self.runtime.RUN_CONDITION.wait(timeout=1.0)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


    def _stream_agent_run(self, run_id: str) -> None:
        if not self.runtime.serialize_agent_run(run_id, self.runtime.OBJECT_STORE):
            return self._json({"error": "agent run not found"}, HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        previous = ""
        try:
            for _ in range(600):
                item = self.runtime.serialize_agent_run(run_id, self.runtime.OBJECT_STORE)
                encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if encoded != previous:
                    self.wfile.write(f"event: pipeline\ndata: {encoded}\n\n".encode("utf-8")); self.wfile.flush(); previous = encoded
                if item and item["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(.2)
        except (BrokenPipeError, ConnectionResetError):
            pass


    def _stream_text3d_job(self, job_id: str) -> None:
        if not self.runtime.get_text3d_job(job_id):
            return self._json({"error": "text-to-3d job not found"}, HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close"); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
        previous = ""
        try:
            for _ in range(900):
                item = self.runtime.get_text3d_job(job_id); encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if encoded != previous:
                    self.wfile.write(f"event: text3d\ndata: {encoded}\n\n".encode("utf-8")); self.wfile.flush(); previous = encoded
                if item and item["status"] in {"completed", "failed", "cancelled"}: break
                time.sleep(.2)
        except (BrokenPipeError, ConnectionResetError):
            pass


    def _stream_scene_agent(self, run_id: str) -> None:
        if not self._scene_agent_payload(run_id):return self._json({"error":"scene agent run not found"},HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK);self.send_header("Content-Type","text/event-stream");self.send_header("Cache-Control","no-cache");self.send_header("Connection","close");self.send_header("Access-Control-Allow-Origin","*");self.end_headers();previous=""
        try:
            for _ in range(1800):
                item=self._scene_agent_payload(run_id);encoded=json.dumps(item,ensure_ascii=False,sort_keys=True)
                if encoded!=previous:self.wfile.write(f"event: scene-agent\ndata: {encoded}\n\n".encode("utf-8"));self.wfile.flush();previous=encoded
                if item and item["status"] in {"ready","completed","rejected","failed","cancelled","stale","awaiting-confirmation"}:break
                time.sleep(.2)
        except (BrokenPipeError,ConnectionResetError):pass
