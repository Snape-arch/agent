"""Studio adapter for the private visualization HTTP transport."""
from __future__ import annotations

from visualization.backend.handlers.contract import HandlerRuntime
from http import HTTPStatus
import base64
import json
import os
import re
import uuid


class StudioHandler:
    runtime: HandlerRuntime

    def _interpret_ai(self, body: dict) -> None:
        result = self.runtime.interpret(body)
        self._json({"data": result}, HTTPStatus.CREATED)


    def _create_agent_pipeline(self, body: dict) -> None:
        self.runtime.check_task_quota(self.principal)
        prompt = str(body.get("prompt") or "").strip()
        if not prompt or len(prompt) > 4000:
            raise ValueError("prompt must contain 1 to 4000 characters")
        provider = str(body.get("provider") or "local").lower()
        if provider not in {"local", "openai", "deepseek", "kimi", "qwen"}:
            raise ValueError("unsupported provider")
        if provider != "local" and not self.runtime.resolve_provider_key(provider, str(body.get("credentialRef") or "") or None):
            raise ValueError(f"server credential is not configured for {provider}")
        defaults = {"openai": "gpt-4.1-mini", "deepseek": "deepseek-v4-flash", "kimi": "moonshot-v1-8k", "qwen": "qwen-plus"}
        request = {**body, "prompt": prompt, "provider": provider, "model": str(body.get("model") or defaults.get(provider, "local"))}
        default_cycles = int(os.environ.get("AGENT_QUALITY_MAX_CYCLES", "2"))
        timeout=max(15,min(1800,int(body.get("timeoutSeconds") or 300)))
        run_id = self.runtime.create_agent_run(prompt, provider, request["model"], max(1, min(4, int(body.get("maxCycles") or default_cycles))),timeout,self.principal.tenant_id)
        task=self.runtime.enqueue_task(self.principal.tenant_id,"agent-pipeline",run_id,request,f"agent:{run_id}")
        self.runtime.submit_durable(task,self.runtime.execute_agent_pipeline,run_id,request,self.runtime.OBJECT_STORE)
        self._json({"data": self.runtime.serialize_agent_run(run_id, self.runtime.OBJECT_STORE)}, HTTPStatus.ACCEPTED)


    def _create_text3d_worker_job(self, body: dict) -> None:
        self.runtime.check_task_quota(self.principal)
        prompt = str(body.get("prompt") or "").strip()
        if not prompt or len(prompt) > 4000:
            raise ValueError("prompt must contain 1 to 4000 characters")
        resolution = max(24, min(56, int(body.get("resolution") or 38)))
        provider=str(body.get("provider") or "local-implicit").lower()
        image=str(body.get("imageBase64") or "") or None
        timeout=max(30,min(3600,int(body.get("timeoutSeconds") or 600)))
        memory=max(1024,min(65536,int(body.get("memoryBudgetMb") or 8192)))
        job_id = self.runtime.create_text3d_job(prompt,provider,image,timeout,memory,self.runtime.OBJECT_STORE,self.principal.tenant_id)
        task=self.runtime.enqueue_task(self.principal.tenant_id,"text-to-3d",job_id,{"provider":provider},f"text3d:{job_id}")
        self.runtime.submit_durable(task,self.runtime.execute_text3d_job,job_id,prompt,resolution,self.runtime.OBJECT_STORE,provider,image,timeout,memory)
        self._json({"data": self.runtime.get_text3d_job(job_id)}, HTTPStatus.ACCEPTED)


    def _save_studio_generation(self, body: dict) -> None:
        plan = body.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        generation_id = str(body.get("id") or f"gen_{uuid.uuid4().hex[:12]}")
        timestamp = self.runtime.now_iso()
        validation = self.runtime.validate_plan(plan)
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            owner = db.execute("SELECT tenant_id FROM studio_generations WHERE id=?", (generation_id,)).fetchone()
            if owner and owner["tenant_id"] != self.principal.tenant_id:
                raise PermissionError("studio generation belongs to another tenant")
            current = db.execute("SELECT version,created_at FROM studio_generations WHERE id=? AND tenant_id=?", (generation_id,self.principal.tenant_id)).fetchone()
            version = int(current["version"] + 1) if current else 1
            created_at = current["created_at"] if current else timestamp
            db.execute("""INSERT INTO studio_generations(id,name,prompt,provider,plan,validation,asset_id,version,created_at,updated_at,tenant_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,prompt=excluded.prompt,
                provider=excluded.provider,plan=excluded.plan,validation=excluded.validation,asset_id=excluded.asset_id,
                version=studio_generations.version+1,updated_at=excluded.updated_at""",
                (generation_id, str(body.get("name") or plan.get("name") or "Untitled model"), str(body.get("prompt") or plan.get("prompt") or ""), str(body.get("provider") or plan.get("provider") or "local"), json.dumps(plan, ensure_ascii=False), json.dumps(validation, ensure_ascii=False), body.get("assetId"), version, created_at, timestamp,self.principal.tenant_id))
            row = db.execute("SELECT * FROM studio_generations WHERE id=? AND tenant_id=?", (generation_id,self.principal.tenant_id)).fetchone()
        self._json({"data": {"id": row["id"], "name": row["name"], "prompt": row["prompt"], "provider": row["provider"], "plan": self.runtime.json_value(row["plan"], {}), "validation": self.runtime.json_value(row["validation"], {}), "assetId": row["asset_id"], "version": row["version"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}}, HTTPStatus.CREATED)


    def _apply_scene_operations(self, body: dict) -> None:
        plan=body.get("plan"); operations=body.get("operations")
        if not isinstance(plan,dict) or not isinstance(operations,list): raise ValueError("plan and operations are required")
        result=self.runtime.apply_operations(plan,operations); generation_id=str(body.get("generationId") or "draft")
        with self.runtime.DB_LOCK,self.runtime.connect() as db:
            row=db.execute("SELECT MAX(version) AS version FROM studio_scene_versions WHERE generation_id=? AND tenant_id=?",(generation_id,self.principal.tenant_id)).fetchone()
            version=int(row["version"] or 0)+1; item_id="scene_"+uuid.uuid4().hex[:12]
            db.execute("INSERT INTO studio_scene_versions(id,generation_id,version,command,operations,plan,created_at,tenant_id) VALUES(?,?,?,?,?,?,?,?)",
                       (item_id,generation_id,version,str(body.get("command") or "manual edit"),json.dumps(operations,ensure_ascii=False),json.dumps(result,ensure_ascii=False),self.runtime.now_iso(),self.principal.tenant_id))
        self._json({"data":{"id":item_id,"generationId":generation_id,"version":version,"plan":result,"operations":operations}},HTTPStatus.CREATED)


    def _save_studio_feedback(self, generation_id: str, body: dict) -> None:
        rating = max(1, min(5, int(body.get("rating") or 0)))
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            if not db.execute("SELECT 1 FROM studio_generations WHERE id=? AND tenant_id=?", (generation_id,self.principal.tenant_id)).fetchone():
                return self._json({"error": "generation not found"}, HTTPStatus.NOT_FOUND)
            db.execute("INSERT INTO studio_feedback(generation_id,rating,comment,created_at) VALUES(?,?,?,?)", (generation_id, rating, str(body.get("comment") or ""), self.runtime.now_iso()))
        self._json({"ok": True}, HTTPStatus.CREATED)


    def _compile_studio_mesh(self, body: dict) -> None:
        plan = body.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        quality = str(body.get("quality") or "high").lower()
        if quality not in {"standard", "high", "ultra"}:
            raise ValueError("quality must be standard, high or ultra")
        payload, stats = self.runtime.compile_obj(plan, quality)
        safe_name = re.sub(r"[^\w\-.]+", "-", str(plan.get("name") or "ai-model"), flags=re.UNICODE).strip("-") or "ai-model"
        self._create_model_asset({
            "name": f"{safe_name}.obj",
            "format": "obj",
            "content": base64.b64encode(payload).decode("ascii"),
            "metadata": {**stats, "source": "ai-3d-studio", "prompt": str(plan.get("prompt") or "")[:1000]},
        })


    def _export_studio_asset(self, body: dict) -> None:
        plan = body.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        asset_format = str(body.get("format") or "glb").lower()
        quality = str(body.get("quality") or "high").lower()
        if asset_format not in {"obj", "gltf", "glb"}:
            raise ValueError("format must be obj, gltf or glb")
        if quality not in {"standard", "high", "ultra"}:
            raise ValueError("quality must be standard, high or ultra")
        payload, stats = self.runtime.compile_obj(plan, quality) if asset_format == "obj" else self.runtime.compile_gltf(plan, quality, binary=asset_format == "glb")
        safe_name = re.sub(r"[^\w\-.]+", "-", str(plan.get("name") or "ai-model"), flags=re.UNICODE).strip("-") or "ai-model"
        self._create_model_asset({"name": f"{safe_name}.{asset_format}", "format": asset_format,
                                  "content": base64.b64encode(payload).decode("ascii"),
                                  "metadata": {**stats, "source": "ai-3d-studio-export", "prompt": str(plan.get("prompt") or "")[:1000]}})


    def _save_parameter_snapshot(self, body: dict) -> None:
        params = body.get("params")
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        run_id = body.get("runId")
        if run_id and not self._owned("runs", str(run_id)):
            raise PermissionError("run is outside the current tenant")
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        created_at = self.runtime.now_iso()
        with self.runtime.DB_LOCK, self.runtime.connect() as db:
            db.execute("INSERT INTO parameter_snapshots(id,name,run_id,params,created_at,tenant_id) VALUES(?,?,?,?,?,?)", (snapshot_id, str(body.get("name") or "Parameter snapshot"), run_id, json.dumps(params, ensure_ascii=False), created_at,self.principal.tenant_id))
        self._json({"data": {"id": snapshot_id, "name": str(body.get("name") or "Parameter snapshot"), "runId": run_id, "params": params, "createdAt": created_at}}, HTTPStatus.CREATED)
