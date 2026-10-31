"""Durable lifecycle manager for preview and pluggable high-quality Text-to-3D workers."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path

from database import connect
from mesh_postprocess import postprocess_to_glb
from mesh_quality import assess_mesh
from text3d_providers import generate_reference_image, provider_catalog, run_provider
from security import reserve_storage

LOCK = threading.RLock()
WORKER = Path(__file__).with_name("text_to_3d_worker.py")
ACTIVE: dict[str, subprocess.Popen] = {}
CANCEL_EVENTS: dict[str, threading.Event] = {}
GPU_LIMIT = threading.BoundedSemaphore(max(1, int(os.environ.get("TEXT3D_GPU_CONCURRENCY", "1"))))
TERMINAL = {"completed", "failed", "cancelled"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_text3d_providers() -> list[dict]:
    return provider_catalog()


def shutdown_text3d_workers() -> int:
    """Terminate child processes owned by this API process during graceful shutdown."""
    stopped=0
    for job_id,process in list(ACTIVE.items()):
        CANCEL_EVENTS.setdefault(job_id,threading.Event()).set()
        if process.poll() is None:
            process.terminate(); stopped+=1
    return stopped


def create_text3d_job(prompt: str, provider: str = "local-implicit", image_base64: str | None = None,
                      timeout_seconds: int = 600, memory_budget_mb: int = 8192, object_store=None, tenant_id: str = "default") -> str:
    catalog = {item["id"] for item in provider_catalog()}
    if provider not in catalog:
        raise ValueError("unsupported Text-to-3D provider")
    job_id = f"text3d_{uuid.uuid4().hex[:12]}"; timestamp = now_iso(); image_key = None
    if image_base64:
        if len(image_base64) > 15_000_000:
            raise ValueError("reference image is too large")
        base64.b64decode(image_base64, validate=True)
        if object_store:
            image_payload={"base64":image_base64};reserve_storage(tenant_id,len(json.dumps(image_payload).encode()));image_key = object_store.put_json(f"tenants/{tenant_id}/studio/text3d/{job_id}/input-image.json",image_payload)
    with LOCK, connect() as db:
        db.execute("""INSERT INTO text3d_jobs(id,prompt,status,progress,stage,asset_id,stats,error,created_at,updated_at,provider,input_image_key,preview_asset_id,timeout_seconds,memory_budget_mb,checkpoint_key,cancel_requested,tenant_id)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (job_id, prompt, "queued", 0, "queued", None, None, None, timestamp, timestamp, provider, image_key, None,
                    max(30, min(3600, timeout_seconds)), max(1024, min(65536, memory_budget_mb)), None, 0,tenant_id))
    CANCEL_EVENTS[job_id] = threading.Event()
    return job_id


def cancel_text3d_job(job_id: str) -> dict | None:
    with LOCK, connect() as db:
        row = db.execute("SELECT status FROM text3d_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        if row["status"] not in TERMINAL:
            db.execute("UPDATE text3d_jobs SET cancel_requested=1,stage=?,updated_at=? WHERE id=?", ("cancelling", now_iso(), job_id))
    CANCEL_EVENTS.setdefault(job_id, threading.Event()).set()
    process = ACTIVE.get(job_id)
    if process and process.poll() is None:
        process.terminate()
    return get_text3d_job(job_id)


def recover_text3d_jobs(executor, object_store) -> int:
    with LOCK, connect() as db:
        rows = db.execute("SELECT * FROM text3d_jobs WHERE status NOT IN ('completed','failed','cancelled') ORDER BY created_at").fetchall()
    resumed = 0
    for row in rows:
        if row["cancel_requested"]:
            with LOCK, connect() as db:
                db.execute("UPDATE text3d_jobs SET status='cancelled',stage='cancelled',updated_at=? WHERE id=?", (now_iso(), row["id"]))
            continue
        image = None
        if row["input_image_key"]:
            try: image = object_store.get_json(row["input_image_key"]).get("base64")
            except (FileNotFoundError, KeyError, ValueError): pass
        CANCEL_EVENTS[row["id"]] = threading.Event()
        executor.submit(execute_text3d_job, row["id"], row["prompt"], 38, object_store, row["provider"], image,
                        row["timeout_seconds"], row["memory_budget_mb"]); resumed += 1
    return resumed


def get_text3d_job(job_id: str) -> dict | None:
    with LOCK, connect() as db:
        row = db.execute("SELECT * FROM text3d_jobs WHERE id=?", (job_id,)).fetchone()
    if not row: return None
    try: stats = json.loads(row["stats"]) if row["stats"] else None
    except json.JSONDecodeError: stats = None
    return {"id":row["id"],"prompt":row["prompt"],"provider":row["provider"],"status":row["status"],"progress":row["progress"],"stage":row["stage"],
            "previewAssetId":row["preview_asset_id"],"assetId":row["asset_id"],"stats":stats,"error":row["error"],
            "timeoutSeconds":row["timeout_seconds"],"memoryBudgetMb":row["memory_budget_mb"],"cancelRequested":bool(row["cancel_requested"]),
            "createdAt":row["created_at"],"updatedAt":row["updated_at"]}


def _cancelled(job_id: str) -> bool:
    event = CANCEL_EVENTS.get(job_id)
    if event and event.is_set(): return True
    with LOCK, connect() as db:
        row = db.execute("SELECT cancel_requested FROM text3d_jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def _progress(job_id: str, progress: int, stage: str) -> None:
    with LOCK, connect() as db:
        db.execute("UPDATE text3d_jobs SET progress=?,stage=?,updated_at=? WHERE id=?", (progress, stage, now_iso(), job_id))


def _save_asset(object_store, name: str, asset_format: str, payload: bytes, metadata: dict, tenant_id: str) -> str:
    with LOCK, connect() as db:
        latest=db.execute("SELECT id,version FROM model_assets WHERE name=? AND tenant_id=? ORDER BY version DESC LIMIT 1",(name,tenant_id)).fetchone()
        version=int(latest["version"]+1) if latest else 1; parent=latest["id"] if latest else None
    asset_id=f"asset_{uuid.uuid4().hex[:12]}"; created=now_iso()
    stored={"base64":base64.b64encode(payload).decode(),"resources":[]};reserve_storage(tenant_id,len(json.dumps(stored).encode()));key=object_store.put_json(f"tenants/{tenant_id}/models/{asset_id}.json",stored)
    with LOCK, connect() as db:
        db.execute("INSERT INTO model_assets(id,name,format,version,parent_id,object_key,metadata,created_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?)",
                   (asset_id,name,asset_format,version,parent,key,json.dumps(metadata,ensure_ascii=False),created,tenant_id))
    return asset_id


def _local_preview(job_id: str, prompt: str, resolution: int, timeout: int) -> tuple[bytes, dict]:
    flags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0
    process=subprocess.Popen([sys.executable,str(WORKER)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,encoding="utf-8",creationflags=flags)
    ACTIVE[job_id]=process
    stdout,stderr=process.communicate(json.dumps({"prompt":prompt,"resolution":resolution},ensure_ascii=True),timeout=min(timeout,240))
    if _cancelled(job_id): raise RuntimeError("cancelled")
    final=None
    for line in stdout.splitlines():
        event=json.loads(line)
        if event.get("type")=="progress": _progress(job_id,min(40,int(event["progress"]*.4)),"preview-"+str(event["stage"]))
        elif event.get("type")=="result": final=event
    if process.returncode or not final: raise RuntimeError(stderr[-1000:] or "preview worker returned no mesh")
    return base64.b64decode(final["content"]),final["stats"]


def execute_text3d_job(job_id: str, prompt: str, resolution: int, object_store, provider: str = "local-implicit",
                       image_base64: str | None = None, timeout_seconds: int = 600, memory_budget_mb: int = 8192) -> None:
    try:
        with LOCK, connect() as db:
            job_row=db.execute("SELECT tenant_id FROM text3d_jobs WHERE id=?",(job_id,)).fetchone();tenant_id=job_row["tenant_id"] if job_row else "default"
            db.execute("UPDATE text3d_jobs SET status='running',stage='preview-start',error=NULL,updated_at=? WHERE id=?",(now_iso(),job_id))
        local_resolution=min(resolution,52 if provider=="local-semantic" else 38)
        preview,preview_stats=_local_preview(job_id,prompt,local_resolution,timeout_seconds)
        preview_id=_save_asset(object_store,"preview-"+uuid.uuid5(uuid.NAMESPACE_URL,prompt).hex[:10]+".obj","obj",preview,
                               {**preview_stats,"source":"text3d-preview","provider":"local-implicit"},tenant_id)
        checkpoint_payload={"previewAssetId":preview_id,"provider":provider};reserve_storage(tenant_id,len(json.dumps(checkpoint_payload).encode()));checkpoint=object_store.put_json(f"tenants/{tenant_id}/studio/text3d/{job_id}/checkpoint.json",checkpoint_payload)
        with LOCK, connect() as db:
            db.execute("UPDATE text3d_jobs SET preview_asset_id=?,checkpoint_key=?,progress=45,stage='preview-ready',updated_at=? WHERE id=?",(preview_id,checkpoint,now_iso(),job_id))
        if _cancelled(job_id): raise RuntimeError("cancelled")
        source,source_format,source_stats=preview,"obj",preview_stats
        if provider not in {"local-implicit","local-semantic"}:
            gpu_provider = provider in {"local-neural","trellis", "hunyuan3d", "triposr"}
            if gpu_provider and memory_budget_mb < 4096: raise RuntimeError("GPU provider requires at least 4096 MB memory budget")
            _progress(job_id,50,"waiting-gpu-slot" if gpu_provider else "waiting-managed-api")
            def invoke_provider():
                if provider in {"hunyuan3d","triposr"} and not image_base64:
                    _progress(job_id,52,"prompt-to-reference-image")
                    generated_image=generate_reference_image(prompt,min(timeout_seconds,120))
                else: generated_image=image_base64
                request={"prompt":prompt,"imageBase64":generated_image,"memoryBudgetMb":memory_budget_mb,"outputFormat":"glb","targetPolycount":80000}
                try:
                    return run_provider(provider,request,timeout_seconds,lambda p,s:_progress(job_id,50+int(p*.35),s),lambda:_cancelled(job_id))
                except Exception:
                    if provider != "meshy" or not os.environ.get("TEXT3D_TRIPO_API_KEY") or _cancelled(job_id): raise
                    _progress(job_id,52,"meshy-failed-fallback-tripo")
                    fallback=run_provider("tripo",request,timeout_seconds,lambda p,s:_progress(job_id,52+int(p*.33),"fallback-"+s),lambda:_cancelled(job_id))
                    fallback.stats={**fallback.stats,"fallbackFrom":"meshy"}; return fallback
            if gpu_provider:
                with GPU_LIMIT: result=invoke_provider()
            else: result=invoke_provider()
            source,source_format,source_stats=result.content,result.format,result.stats
        threshold=max(50,min(100,int(os.environ.get("TEXT3D_QUALITY_THRESHOLD","75"))))
        raw_quality=assess_mesh(source,source_format,threshold)
        raw_id=_save_asset(object_store,"raw-"+uuid.uuid5(uuid.NAMESPACE_URL,prompt+provider).hex[:10]+"."+source_format,source_format,source,
                           {**source_stats,"source":"text-to-3d-raw","provider":provider,"quality":raw_quality,"assetStage":"raw"},tenant_id)
        _progress(job_id,88,"mesh-postprocess")
        glb,post_stats=postprocess_to_glb(source,source_format,"Semantic "+uuid.uuid5(uuid.NAMESPACE_URL,prompt).hex[:8])
        release_quality=assess_mesh(glb,"glb",threshold)
        metadata={**source_stats,**post_stats,**release_quality["metrics"],"source":"text-to-3d-provider","provider":provider,"prompt":prompt[:1000],"imageConditioned":bool(image_base64),"nonParametric":True,
                  "assetStage":"release","assetStages":{"preview":preview_id,"raw":raw_id},"quality":{"raw":raw_quality,"release":release_quality}}
        if not release_quality["passed"]:
            raise RuntimeError("3D quality gate rejected release: "+"; ".join(release_quality["issues"]))
        asset_id=_save_asset(object_store,"semantic-"+uuid.uuid5(uuid.NAMESPACE_URL,prompt+provider).hex[:10]+".glb","glb",glb,metadata,tenant_id)
        metadata["assetStages"]["release"]=asset_id
        with LOCK, connect() as db:
            db.execute("UPDATE text3d_jobs SET status='completed',progress=100,stage='completed',asset_id=?,stats=?,updated_at=? WHERE id=?",
                       (asset_id,json.dumps(metadata,ensure_ascii=False),now_iso(),job_id))
    except subprocess.TimeoutExpired:
        process=ACTIVE.get(job_id)
        if process: process.kill()
        with LOCK, connect() as db:
            db.execute("UPDATE text3d_jobs SET status='failed',stage='timeout',error=?,updated_at=? WHERE id=?",(f"job exceeded {timeout_seconds}s",now_iso(),job_id))
    except Exception as error:
        cancelled=_cancelled(job_id) or str(error)=="cancelled"
        with LOCK, connect() as db:
            db.execute("UPDATE text3d_jobs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",
                       ("cancelled" if cancelled else "failed","cancelled" if cancelled else "failed",None if cancelled else str(error)[:2000],now_iso(),job_id))
    finally:
        ACTIVE.pop(job_id,None); CANCEL_EVENTS.pop(job_id,None)
