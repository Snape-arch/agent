"""ClawVision experiment service: REST, SSE, queue and pluggable persistence."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from api_contract import openapi_document, page_meta, parse_pagination
from ai_studio import TEMPLATES, interpret, validate_plan
from asset_scene import apply_asset_operations, canonicalize_mesh_asset, interpret_asset_command, pack_glb, parse_asset, quality_report, scene_manifest
from agent_pipeline import cancel_agent_run, create_agent_run, execute_agent_pipeline, recover_agent_runs, serialize_agent_run
from credentials import resolve_provider_key
from database import connect, database_label, init_database, is_integrity_error, is_postgres
from mesh_generator import compile_gltf, compile_obj
from scene_operations import apply_operations, interpret_scene_command
from object_store import create_object_store
from text3d_service import cancel_text3d_job, create_text3d_job, execute_text3d_job, get_text3d_job, list_text3d_providers, recover_text3d_jobs, shutdown_text3d_workers
from geometry_worker import provider_catalog as geometry_provider_catalog, run_provider as run_geometry_provider
from scene_agent import assess_operations, record_decision, serialize_scene_agent_run, understand_scene
from training_runner import cancel as cancel_training_process, provider_catalog as training_provider_catalog, run as run_training_provider
from security import (audit, authenticate, bootstrap, check_run_quota, check_task_quota, create_member,
                      issue_token, list_members, list_tokens, login, quota_status,
                      reserve_storage, revoke_token, save_credential)
from durable_queue import (enqueue as enqueue_task, serialize as serialize_task, queue_metrics, cancel as cancel_task,
                           reap_expired, lease as lease_task, heartbeat as heartbeat_task,
                           finish as finish_task, fail as fail_task)
from domain_services import CollectionService, DatasetService
from run_service import RunService
from evaluation_service import EvaluationService
from scenario_service import ScenarioService
from synthesis_service import SynthesisService, execute_synthesis_job
from vision_dataset_service import VisionDatasetService
from vision_experiment_service import VisionExperimentService, execute_vision_experiment
from analytics_service import AnalysisQueryService, DatasetCatalog, schema_diff
from errors import ApplicationError, ConflictError, NotFoundError, ValidationError, problem_details
from columnar_engine import parquet_row_count, parquet_to_rows, rows_to_parquet
from observability import adopt_traceparent, gauge, inc, observe, record_span, render_prometheus
from worker_health import statuses as worker_statuses

HOST = os.environ.get("CLAWVISION_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLAWVISION_PORT", "8787"))
STARTED_AT = time.time()
OBJECT_STORE = create_object_store()

DB_LOCK = threading.RLock()
RUN_CONDITION = threading.Condition()
RUN_VERSIONS: dict[str, int] = {}
EXECUTOR = ThreadPoolExecutor(max_workers=max(1, int(os.environ.get("CLAWVISION_MAX_CONCURRENCY", "3"))))
EMBEDDED_WORKERS = os.environ.get("CLAWVISION_EMBEDDED_WORKERS", "true").lower() in {"1","true","yes"}
SCENE_AGENT_LIMIT = threading.BoundedSemaphore(max(1, int(os.environ.get("SCENE_AGENT_MAX_CONCURRENCY", "2"))))
GEOMETRY_LIMIT = threading.BoundedSemaphore(max(1, int(os.environ.get("GEOMETRY_MAX_CONCURRENCY", "1"))))
_INITIALIZED = False
_ANALYSIS_SERVICE: AnalysisQueryService | None = None
_SYNTHESIS_STOP = threading.Event()
_SYNTHESIS_DISPATCHED: set[str] = set()
_SYNTHESIS_RECOVERY: threading.Thread | None = None


def run_service() -> RunService:
    return RunService(connect, OBJECT_STORE, DB_LOCK, reserve_storage)


def analysis_service() -> AnalysisQueryService:
    global _ANALYSIS_SERVICE
    if _ANALYSIS_SERVICE is None or _ANALYSIS_SERVICE.object_store is not OBJECT_STORE:
        _ANALYSIS_SERVICE = AnalysisQueryService(connect, OBJECT_STORE)
    return _ANALYSIS_SERVICE


def execute_durable(task_id: str, target, *args) -> None:
    """Execute a task under a renewable database lease.

    The same wrapper is usable by the API's embedded worker and by a future
    standalone worker process. Idempotency and lease expiry prevent double runs.
    """
    worker_id = f"worker-{os.getpid()}-{threading.get_ident()}"
    if not lease_task(task_id, worker_id, 30): return
    stopped = threading.Event()
    def renew():
        while not stopped.wait(10):
            if not heartbeat_task(task_id, worker_id, 30): return
    thread = threading.Thread(target=renew, daemon=True); thread.start()
    try:
        result = target(*args)
        with DB_LOCK,connect() as db:
            task_row=db.execute("SELECT kind,resource_id,payload FROM durable_tasks WHERE id=?",(task_id,)).fetchone();resource_status=None
            if task_row:
                kind=task_row["kind"];resource=task_row["resource_id"];payload=json_value(task_row["payload"],{})
                table={"agent-pipeline":"agent_runs","text-to-3d":"text3d_jobs","scene-agent":"scene_agent_runs","geometry":"geometry_jobs","model-operation":"model_operation_jobs","synthesis":"synthesis_jobs","vision-experiment":"vision_experiments"}.get(kind)
                if kind=="training": table="runs" if payload.get("provider")=="simulator" else "training_jobs"
                if table:
                    status_row=db.execute(f"SELECT status FROM {table} WHERE id=?",(resource,)).fetchone();resource_status=status_row["status"] if status_row else "missing"
        if resource_status in {"failed","dead-letter","missing"}:
            fail_task(task_id,worker_id,f"resource finished as {resource_status}",retry=False);return
        if resource_status in {"cancelled","stopped","rejected"}:
            with DB_LOCK,connect() as db: db.execute("UPDATE durable_tasks SET status='cancelled',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?",(now_iso(),task_id))
            return
        finish_task(task_id, worker_id, result if isinstance(result, dict) else {"ok": True})
    except Exception as error:
        fail_task(task_id, worker_id, str(error), retry=True)
        raise
    finally:
        stopped.set(); thread.join(timeout=.2)


def submit_durable(task: dict, target, *args) -> None:
    if EMBEDDED_WORKERS: EXECUTOR.submit(execute_durable,task["id"],target,*args)


def submit_synthesis(task: dict) -> None:
    if not EMBEDDED_WORKERS or _SYNTHESIS_STOP.is_set(): return
    with DB_LOCK:
        if task["id"] in _SYNTHESIS_DISPATCHED: return
        _SYNTHESIS_DISPATCHED.add(task["id"])
    def execute():
        try:
            target = execute_vision_experiment if task["kind"]=="vision-experiment" else execute_synthesis_job
            execute_durable(task["id"], target, task["resourceId"], task["tenantId"])
        except Exception:
            # execute_durable persists the error and retry count in the queue.
            pass
        finally:
            with DB_LOCK: _SYNTHESIS_DISPATCHED.discard(task["id"])
        with connect() as db:
            row = db.execute("SELECT * FROM durable_tasks WHERE id=? AND status='queued'", (task["id"],)).fetchone()
        if row: submit_synthesis(serialize_task(row))
    try:
        EXECUTOR.submit(execute)
    except RuntimeError:
        with DB_LOCK: _SYNTHESIS_DISPATCHED.discard(task["id"])


def recover_synthesis_once() -> int:
    if not EMBEDDED_WORKERS: return 0
    reap_expired(kind="synthesis")
    reap_expired(kind="vision-experiment")
    with connect() as db:
        rows = db.execute("SELECT * FROM durable_tasks WHERE kind IN ('synthesis','vision-experiment') AND status='queued' ORDER BY created_at LIMIT 50").fetchall()
    for row in rows: submit_synthesis(serialize_task(row))
    return len(rows)


def start_synthesis_recovery() -> None:
    global _SYNTHESIS_RECOVERY
    if not EMBEDDED_WORKERS or (_SYNTHESIS_RECOVERY and _SYNTHESIS_RECOVERY.is_alive()): return
    _SYNTHESIS_STOP.clear()
    def recover():
        while not _SYNTHESIS_STOP.is_set():
            try: recover_synthesis_once()
            except Exception: inc("clawvision_synthesis_recovery_failures_total")
            _SYNTHESIS_STOP.wait(2)
    _SYNTHESIS_RECOVERY = threading.Thread(target=recover, name="synthesis-recovery", daemon=True)
    _SYNTHESIS_RECOVERY.start()


def stop_synthesis_recovery() -> None:
    _SYNTHESIS_STOP.set()
    if _SYNTHESIS_RECOVERY: _SYNTHESIS_RECOVERY.join(timeout=2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def bump(run_id: str) -> None:
    with RUN_CONDITION:
        RUN_VERSIONS[run_id] = RUN_VERSIONS.get(run_id, 0) + 1
        RUN_CONDITION.notify_all()


def json_value(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def quality_accepts(candidate: dict, baseline: dict) -> bool:
    """Pass an absolute gate, or prove a legacy asset did not regress."""
    if candidate.get("passed"):
        return True
    if baseline.get("passed") or float(candidate.get("score") or 0) < float(baseline.get("score") or 0):
        return False
    current = candidate.get("metrics") if isinstance(candidate.get("metrics"), dict) else {}
    previous = baseline.get("metrics") if isinstance(baseline.get("metrics"), dict) else {}
    for metric in ("degenerateFaces", "boundaryEdges", "nonManifoldEdges", "components"):
        if int(current.get(metric) or 0) > int(previous.get(metric) or 0):
            return False
    return True


def native_gpu_telemetry() -> dict | None:
    """Capture host NVIDIA utilization for correlation with browser GPU timers."""
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        raw = subprocess.check_output(["nvidia-smi", "--query-gpu=name,uuid,driver_version,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw", "--format=csv,noheader,nounits", "-i", "0"], text=True, timeout=3, creationflags=flags).splitlines()[0]
        name, gpu_uuid, driver, utilization, memory_used, memory_total, temperature, power = [item.strip() for item in raw.split(",", 7)]
        return {"name":name,"uuid":gpu_uuid,"driverVersion":driver,"utilizationPercent":float(utilization),"memoryUsedMb":float(memory_used),"memoryTotalMb":float(memory_total),"temperatureC":float(temperature),"powerWatts":float(power)}
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def serialize_model_asset(row, include_content: bool = False, include_relations: bool = False) -> dict:
    metadata = json_value(row["metadata"], {})
    keys = set(row.keys())
    result = {
        "id": row["id"], "name": row["name"], "format": row["format"], "version": row["version"],
        "parentId": row["parent_id"], "projectId": row["project_id"] if "project_id" in keys else None,
        "folder": row["folder"] if "folder" in keys else "/", "stage": row["stage"] if "stage" in keys else metadata.get("assetStage", "raw"),
        "tags": json_value(row["tags"], []) if "tags" in keys else metadata.get("tags", []),
        "thumbnailKey": row["thumbnail_key"] if "thumbnail_key" in keys else None,
        "archivedAt": row["archived_at"] if "archived_at" in keys else None,
        "deletedAt": row["deleted_at"] if "deleted_at" in keys else None,
        "metadata": metadata, "createdAt": row["created_at"],
        "updatedAt": (row["updated_at"] if "updated_at" in keys else None) or row["created_at"],
    }
    if include_content:
        result["content"] = OBJECT_STORE.get_json(row["object_key"])
    if include_relations:
        with DB_LOCK, connect() as db:
            components = db.execute("SELECT * FROM asset_components WHERE asset_id=? ORDER BY component_type,version DESC", (row["id"],)).fetchall()
            releases = db.execute("SELECT * FROM asset_releases WHERE asset_id=? ORDER BY created_at DESC", (row["id"],)).fetchall()
        result["components"] = [{"id": item["id"], "type": item["component_type"], "version": item["version"], "metadata": json_value(item["metadata"], {}), "createdAt": item["created_at"]} for item in components]
        result["releases"] = [{"id": item["id"], "status": item["status"], "reviewer": item["reviewer"], "note": item["note"], "createdAt": item["created_at"], "updatedAt": item["updated_at"]} for item in releases]
        result["references"] = model_asset_references(row["id"])
    return result


def model_asset_references(asset_id: str) -> list[dict]:
    references: list[dict] = []
    with DB_LOCK, connect() as db:
        for item in db.execute("SELECT run_id,role,step FROM run_asset_links WHERE asset_id=?", (asset_id,)).fetchall():
            references.append({"kind": "run", "id": item["run_id"], "role": item["role"], "step": item["step"]})
        for item in db.execute("SELECT id FROM model_scenes WHERE source_asset_id=? OR current_asset_id=?", (asset_id, asset_id)).fetchall():
            references.append({"kind": "scene", "id": item["id"]})
        for item in db.execute("SELECT scene_id,version FROM model_scene_versions WHERE asset_id=?", (asset_id,)).fetchall():
            references.append({"kind": "scene-version", "id": item["scene_id"], "version": item["version"]})
        for item in db.execute("SELECT id FROM studio_generations WHERE asset_id=?", (asset_id,)).fetchall():
            references.append({"kind": "generation", "id": item["id"]})
        for item in db.execute("SELECT id,version FROM model_assets WHERE parent_id=? AND deleted_at IS NULL", (asset_id,)).fetchall():
            references.append({"kind": "asset-version", "id": item["id"], "version": item["version"]})
        for item in db.execute("SELECT id,version FROM evaluation_scenarios WHERE asset_id=?", (asset_id,)).fetchall():
            references.append({"kind": "evaluation-scenario", "id": item["id"], "version": item["version"]})
    return references


def store_model_asset(name: str, asset_format: str, content: bytes, metadata: dict, resources: list | None = None, tenant_id: str = "default") -> dict:
    if asset_format not in {"glb","gltf","obj","stl","ply","step","iges","brep"}: raise ValueError("format must be glb, gltf, obj, stl, ply, step, iges or brep")
    resources=resources or []; metadata={**metadata,"byteSize":len(content),"streaming":True}
    with DB_LOCK,connect() as db:
        latest=db.execute("SELECT id,version FROM model_assets WHERE name=? AND tenant_id=? ORDER BY version DESC LIMIT 1",(name,tenant_id)).fetchone(); version=int(latest["version"]+1) if latest else 1; parent_id=latest["id"] if latest else None
    asset_id=f"asset_{uuid.uuid4().hex[:12]}"; binary_key=f"tenants/{tenant_id}/models/{asset_id}.{asset_format}";stored={"base64":base64.b64encode(content).decode("ascii"),"resources":resources,"binaryKey":binary_key,"byteSize":len(content)};reserve_storage(tenant_id,len(json.dumps(stored).encode())+len(content));OBJECT_STORE.put_bytes(binary_key,content,{"glb":"model/gltf-binary","gltf":"model/gltf+json","obj":"text/plain","stl":"model/stl"}.get(asset_format,"application/octet-stream"));key=OBJECT_STORE.put_json(f"tenants/{tenant_id}/models/{asset_id}.json",stored); created=now_iso()
    project_id = metadata.get("projectId"); folder = str(metadata.get("folder") or "/"); stage = str(metadata.get("assetStage") or metadata.get("stage") or "raw"); tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
    with DB_LOCK,connect() as db:
        db.execute("INSERT INTO model_assets(id,name,format,version,parent_id,object_key,metadata,created_at,project_id,folder,stage,tags,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(asset_id,name,asset_format,version,parent_id,key,json.dumps(metadata,ensure_ascii=False),created,project_id,folder,stage,json.dumps(tags,ensure_ascii=False),created,tenant_id))
        row = db.execute("SELECT * FROM model_assets WHERE id=?", (asset_id,)).fetchone()
    result = serialize_model_asset(row); result["content"] = stored; return result


def serialize_model_scene(row, include_versions: bool = False) -> dict:
    result={"id":row["id"],"name":row["name"],"sourceAssetId":row["source_asset_id"],"currentAssetId":row["current_asset_id"],"version":row["version"],"operations":json_value(row["operations"],[]),"scene":json_value(row["scene_json"],{}),"quality":json_value(row["quality"],{}),"createdAt":row["created_at"],"updatedAt":row["updated_at"]}
    if include_versions:
        with DB_LOCK,connect() as db: versions=db.execute("SELECT * FROM model_scene_versions WHERE scene_id=? ORDER BY version DESC",(row["id"],)).fetchall()
        result["versions"]=[{"id":item["id"],"version":item["version"],"assetId":item["asset_id"],"operations":json_value(item["operations"],[]),"quality":json_value(item["quality"],{}),"createdAt":item["created_at"]} for item in versions]
        source_scene=json_value(versions[-1]["scene_json"],{}) if versions else {};current_scene=result["scene"]
        source_nodes=source_scene.get("nodes",[]);current_nodes=current_scene.get("nodes",[])
        result["diff"]={"operations":len(result["operations"]),"nodesAdded":max(0,len(current_nodes)-len(source_nodes)),"nodesRemoved":sum(1 for node in current_nodes if not node.get("visible",True)),"materialsAdded":max(0,int(current_scene.get("materialCount",0))-int(source_scene.get("materialCount",0))),"facesDelta":sum(int(node.get("faceCount",0)) for node in current_nodes)-sum(int(node.get("faceCount",0)) for node in source_nodes)}
    return result


def serialize_model_operation_job(row) -> dict | None:
    if not row:return None
    return {"id":row["id"],"sceneId":row["scene_id"],"status":row["status"],"progress":row["progress"],"stage":row["stage"],"operations":json_value(row["operations"],[]),"result":json_value(row["result"],None),"error":row["error"],"cancelRequested":bool(row["cancel_requested"]),"createdAt":row["created_at"],"updatedAt":row["updated_at"]}


def serialize_geometry_job(row) -> dict | None:
    if not row: return None
    return {"id":row["id"],"sceneId":row["scene_id"],"sourceAssetId":row["source_asset_id"],"provider":row["provider"],"operation":json_value(row["operation"],{}),"status":row["status"],"progress":row["progress"],"stage":row["stage"],"priority":row["priority"],"previewAssetId":row["preview_asset_id"],"resultAssetId":row["result_asset_id"],"checkpointKey":row["checkpoint_key"],"result":json_value(row["result"],None),"error":row["error"],"cancelRequested":bool(row["cancel_requested"]),"timeoutSeconds":row["timeout_seconds"],"createdAt":row["created_at"],"updatedAt":row["updated_at"]}


def recover_intelligent_geometry_jobs() -> dict:
    timestamp=now_iso()
    with DB_LOCK,connect() as db:
        agents=db.execute("SELECT id FROM scene_agent_runs WHERE status IN ('queued','understanding','planning','risk-analysis','previewing','quality-check','applying')").fetchall()
        geometry=db.execute("SELECT id FROM geometry_jobs WHERE status IN ('queued','running','previewing','provider-running','finalizing')").fetchall()
        for row in agents: db.execute("UPDATE scene_agent_runs SET status='failed',stage='recovered',error='service restarted before stage completion; source scene is unchanged',updated_at=? WHERE id=?",(timestamp,row["id"]))
        for row in geometry: db.execute("UPDATE geometry_jobs SET status='failed',stage='recovered',error='service restarted; resume from checkpoint by submitting a new job',updated_at=? WHERE id=?",(timestamp,row["id"]))
    return {"sceneAgents":len(agents),"geometryJobs":len(geometry)}


def infer_fields(rows: list[dict]) -> list[dict]:
    fields = []
    keys = list(dict.fromkeys(key for row in rows[:200] for key in row.keys()))
    for key in keys:
        values = [row.get(key) for row in rows[:500] if row.get(key) not in (None, "")]
        kind = "string"
        if values and all(isinstance(value, bool) or str(value).lower() in {"true", "false"} for value in values):
            kind = "boolean"
        elif values:
            try:
                [float(value) for value in values]
                kind = "number"
            except (TypeError, ValueError):
                try:
                    [datetime.fromisoformat(str(value).replace("Z", "+00:00")) for value in values]
                    kind = "datetime"
                except ValueError:
                    kind = "string"
        fields.append({"name": key, "type": kind, "nullable": len(values) < min(len(rows), 500)})
    return fields


def coerce_rows(rows: list[dict], fields: list[dict]) -> list[dict]:
    types = {field["name"]: field["type"] for field in fields}
    result = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if value in (None, ""):
                item[key] = None
            elif types.get(key) == "number":
                number = float(value)
                item[key] = int(number) if number.is_integer() else number
            elif types.get(key) == "boolean":
                item[key] = value if isinstance(value, bool) else str(value).lower() == "true"
            else:
                item[key] = value
        result.append(item)
    return result


def serialize_run(db, row) -> dict:
    return run_service().serialize(db, row)


def get_run(run_id: str) -> dict | None:
    try:
        return run_service().get(run_id)
    except NotFoundError:
        return None


def deterministic_noise(seed: int, step: int) -> float:
    value = math.sin((seed + step * 13) * 12.9898) * 43758.5453
    return (value - math.floor(value) - 0.5) * 0.075


def _execute_queued_run_legacy(run_id: str, params: dict, job_id: str, semaphore: threading.Semaphore) -> None:
    with semaphore:
        epochs = max(1, min(100, int(params.get("epochs", 40))))
        seed = int(params.get("seed", 42))
        learning_rate = float(params.get("learningRate", 0.001))
        batch_size = int(params.get("batchSize", 64))
        dropout = float(params.get("dropout", 0.2))
        optimizer = str(params.get("optimizer", "AdamW"))
        lr_quality = math.exp(-abs(math.log10(max(1e-8, learning_rate)) + 3) * 0.32)
        batch_quality = 1 - abs(batch_size - 64) / 380
        dropout_quality = 1 - abs(dropout - 0.2) * 0.8
        optimizer_quality = 1 if optimizer == "AdamW" else 0.965 if optimizer == "Adam" else 0.9
        quality = max(0.68, lr_quality * batch_quality * dropout_quality * optimizer_quality)
        with DB_LOCK, connect() as db:
            db.execute("UPDATE runs SET status=?,updated_at=? WHERE id=?", ("running", now_iso(), run_id))
            db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", "队列调度完成 · 后端执行器已启动", now_iso()))
        bump(run_id)
        for step in range(1, epochs + 1):
            progress = step / epochs
            noise = deterministic_noise(seed, step)
            train_loss = max(0.045, 2.15 * math.exp(-progress * (4.5 + quality * 2.2)) + 0.08 + noise)
            overfit = max(0, progress - 0.7) * max(0, 0.16 - dropout) * 1.8
            val_loss = max(0.07, train_loss * 1.14 + 0.06 + overfit + abs(noise) * 0.45)
            accuracy = min(0.992, max(0.42, 0.46 + 0.49 * quality * (1 - math.exp(-progress * 5.3)) - overfit * 0.45 + noise * 0.12))
            with DB_LOCK, connect() as db:
                db.execute(
                    """INSERT INTO metrics(run_id,step,train_loss,val_loss,accuracy,learning_rate,gpu,created_at)
                       VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id,step) DO UPDATE SET
                       train_loss=excluded.train_loss,val_loss=excluded.val_loss,accuracy=excluded.accuracy,
                       learning_rate=excluded.learning_rate,gpu=excluded.gpu""",
                    (run_id, step, train_loss, val_loss, accuracy, learning_rate * (1 - step / (epochs * 1.4)), min(99, 44 + batch_size * 0.43), now_iso()),
                )
                if step % 5 == 0 or step == epochs:
                    db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", f"epoch {step} · val_accuracy {accuracy:.1%}", now_iso()))
                db.execute("UPDATE runs SET updated_at=? WHERE id=?", (now_iso(), run_id))
            bump(run_id)
            time.sleep(0.045)
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        object_key = OBJECT_STORE.put_json(f"runs/{run_id}/{artifact_id}.json", {"jobId": job_id, "finalAccuracy": accuracy, "params": params})
        with DB_LOCK, connect() as db:
            db.execute("INSERT INTO artifacts(id,run_id,name,type,mime_type,step,content,object_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (artifact_id, run_id, "parameter-result", "parameter-result", "application/json", epochs, None, object_key, now_iso()))
            db.execute("UPDATE runs SET status=?,updated_at=? WHERE id=?", ("completed", now_iso(), run_id))
            db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", "参数实验执行完成", now_iso()))
            db.execute("UPDATE jobs SET completed_runs=completed_runs+1,updated_at=? WHERE id=?", (now_iso(), job_id))
            job = db.execute("SELECT total_runs,completed_runs FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job and job["completed_runs"] >= job["total_runs"]:
                db.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?", ("completed", now_iso(), job_id))
        bump(run_id)


def execute_queued_run(run_id: str, params: dict, job_id: str, semaphore: threading.Semaphore) -> None:
    """Persistent deterministic executor with stop checks and restart continuation."""
    with semaphore:
        epochs = max(1, min(100, int(params.get("epochs", 40))))
        seed = int(params.get("seed", 42))
        learning_rate = float(params.get("learningRate", 0.001))
        batch_size = int(params.get("batchSize", 64))
        dropout = float(params.get("dropout", 0.2))
        optimizer = str(params.get("optimizer", "AdamW"))
        lr_quality = math.exp(-abs(math.log10(max(1e-8, learning_rate)) + 3) * 0.32)
        quality = max(0.68, lr_quality * (1 - abs(batch_size - 64) / 380) * (1 - abs(dropout - 0.2) * 0.8) * (1 if optimizer == "AdamW" else 0.965 if optimizer == "Adam" else 0.9))
        with DB_LOCK, connect() as db:
            current = db.execute("SELECT status,tenant_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not current or current["status"] in {"completed", "stopped", "failed"}:
                return
            metric = db.execute("SELECT MAX(step) AS step FROM metrics WHERE run_id=?", (run_id,)).fetchone()
            start_step = int(metric["step"] or 0) + 1
            db.execute("UPDATE runs SET status=?,updated_at=? WHERE id=?", ("running", now_iso(), run_id))
            db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", "队列调度完成 · 可恢复执行器已启动", now_iso()))
        bump(run_id)
        accuracy = 0.5
        for step in range(start_step, epochs + 1):
            with DB_LOCK, connect() as db:
                state = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
                if not state or state["status"] == "stopped":
                    return
            progress = step / epochs
            noise = deterministic_noise(seed, step)
            train_loss = max(0.045, 2.15 * math.exp(-progress * (4.5 + quality * 2.2)) + 0.08 + noise)
            overfit = max(0, progress - 0.7) * max(0, 0.16 - dropout) * 1.8
            val_loss = max(0.07, train_loss * 1.14 + 0.06 + overfit + abs(noise) * 0.45)
            accuracy = min(0.992, max(0.42, 0.46 + 0.49 * quality * (1 - math.exp(-progress * 5.3)) - overfit * 0.45 + noise * 0.12))
            with DB_LOCK, connect() as db:
                db.execute("""INSERT INTO metrics(run_id,step,train_loss,val_loss,accuracy,learning_rate,gpu,created_at)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id,step) DO UPDATE SET
                    train_loss=excluded.train_loss,val_loss=excluded.val_loss,accuracy=excluded.accuracy,
                    learning_rate=excluded.learning_rate,gpu=excluded.gpu""",
                    (run_id, step, train_loss, val_loss, accuracy, learning_rate * (1 - step / (epochs * 1.4)), min(99, 44 + batch_size * 0.43), now_iso()))
                if step % 5 == 0 or step == epochs:
                    db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", f"epoch {step} · val_accuracy {accuracy:.1%}", now_iso()))
                db.execute("UPDATE runs SET updated_at=? WHERE id=?", (now_iso(), run_id))
            bump(run_id)
            time.sleep(0.045)
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        artifact_payload={"jobId":job_id,"finalAccuracy":accuracy,"params":params};reserve_storage(current["tenant_id"],len(json.dumps(artifact_payload).encode()));object_key = OBJECT_STORE.put_json(f"tenants/{current['tenant_id']}/runs/{run_id}/{artifact_id}.json",artifact_payload)
        with DB_LOCK, connect() as db:
            state = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not state or state["status"] == "stopped":
                return
            db.execute("INSERT INTO artifacts(id,run_id,name,type,mime_type,step,content,object_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (artifact_id, run_id, "parameter-result", "parameter-result", "application/json", epochs, None, object_key, now_iso()))
            db.execute("UPDATE runs SET status=?,updated_at=? WHERE id=?", ("completed", now_iso(), run_id))
            db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", "参数实验执行完成", now_iso()))
            db.execute("UPDATE jobs SET completed_runs=completed_runs+1,updated_at=? WHERE id=?", (now_iso(), job_id))
            job = db.execute("SELECT total_runs,completed_runs FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job and job["completed_runs"] >= job["total_runs"]:
                db.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?", ("completed", now_iso(), job_id))
        bump(run_id)


def execute_real_training(training_id: str, run_id: str, params: dict, job_id: str, provider: str, semaphore: threading.Semaphore, timeout: int) -> None:
    """Execute a controlled process provider and persist its streamed JSONL events."""
    with DB_LOCK,connect() as db:
        tenant_row=db.execute("SELECT tenant_id FROM training_jobs WHERE id=?",(training_id,)).fetchone(); tenant_id=tenant_row["tenant_id"] if tenant_row else "default"
    def on_event(item: dict) -> None:
        kind = str(item.get("type") or "log"); timestamp = now_iso()
        with DB_LOCK, connect() as db:
            state = db.execute("SELECT cancel_requested FROM training_jobs WHERE id=?", (training_id,)).fetchone()
            if state and state["cancel_requested"]:
                cancel_training_process(training_id); raise RuntimeError("training cancelled")
            if kind == "metric":
                db.execute("""INSERT INTO metrics(run_id,step,train_loss,val_loss,accuracy,learning_rate,gpu,created_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id,step) DO UPDATE SET train_loss=excluded.train_loss,val_loss=excluded.val_loss,accuracy=excluded.accuracy,learning_rate=excluded.learning_rate,gpu=excluded.gpu""", (run_id, int(item["step"]), item.get("trainLoss"), item.get("valLoss"), item.get("accuracy"), item.get("learningRate"), item.get("gpu"), timestamp))
                total = max(1, int(params.get("epochs", 8)))
                db.execute("UPDATE training_jobs SET progress=?,stage='training',updated_at=? WHERE id=?", (min(99, int(item["step"] / total * 100)), timestamp, training_id))
            elif kind == "artifact":
                artifact_id = "art_" + uuid.uuid4().hex[:12];content=item.get("content");reserve_storage(tenant_id,len(json.dumps(content,ensure_ascii=False).encode()));key = OBJECT_STORE.put_json(f"tenants/{tenant_id}/runs/{run_id}/{artifact_id}.json",content)
                db.execute("INSERT INTO artifacts(id,run_id,name,type,mime_type,step,content,object_key,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (artifact_id, run_id, str(item.get("name") or artifact_id), str(item.get("artifactType") or "json"), str(item.get("mimeType") or "application/json"), item.get("step"), None, key, timestamp))
            elif kind == "checkpoint":
                checkpoint_payload={"step":item.get("step"),"content":item.get("content")};reserve_storage(tenant_id,len(json.dumps(checkpoint_payload).encode()));key = OBJECT_STORE.put_json(f"tenants/{tenant_id}/runs/{run_id}/checkpoints/{training_id}.json",checkpoint_payload)
                db.execute("UPDATE training_jobs SET checkpoint_key=?,updated_at=? WHERE id=?", (key, timestamp, training_id))
            elif kind == "telemetry":
                db.execute("""INSERT INTO training_resource_metrics(run_id,step,gpu_utilization,gpu_memory_mb,gpu_temperature,samples_per_second,oom,created_at)
                  VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(run_id,step) DO UPDATE SET gpu_utilization=excluded.gpu_utilization,gpu_memory_mb=excluded.gpu_memory_mb,gpu_temperature=excluded.gpu_temperature,samples_per_second=excluded.samples_per_second,oom=excluded.oom""",
                  (run_id,int(item.get("step") or 0),item.get("gpuUtilization"),item.get("gpuMemoryMb"),item.get("gpuTemperature"),item.get("samplesPerSecond"),1 if item.get("oom") else 0,timestamp))
            elif kind == "log": db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, str(item.get("level") or "info"), str(item.get("message") or ""), timestamp))
        bump(run_id)
    with semaphore:
        with DB_LOCK, connect() as db:
            training = db.execute("SELECT status,cancel_requested,checkpoint_key FROM training_jobs WHERE id=? AND run_id=?", (training_id, run_id)).fetchone()
            if not training or training["status"] in {"completed", "cancelled"} or training["cancel_requested"]:
                return
            db.execute("UPDATE training_jobs SET status='running',stage='starting',error=NULL,updated_at=? WHERE id=?", (now_iso(), training_id)); db.execute("UPDATE runs SET status='running',error_message=NULL,updated_at=? WHERE id=?", (now_iso(), run_id))
        try:
            params = dict(params)
            if training["checkpoint_key"]:
                checkpoint = OBJECT_STORE.get_json(training["checkpoint_key"])
                if not isinstance(checkpoint, dict) or "content" not in checkpoint:
                    raise RuntimeError("saved training checkpoint is invalid")
                params["_checkpoint"] = checkpoint["content"]
                with DB_LOCK, connect() as db:
                    db.execute("INSERT INTO events(run_id,level,message,created_at) VALUES(?,?,?,?)", (run_id, "info", f"从 checkpoint step {checkpoint.get('step', '?')} 恢复训练", now_iso()))
                bump(run_id)
            result = run_training_provider(training_id, provider, params, on_event, timeout)
            with DB_LOCK, connect() as db:
                db.execute("UPDATE training_jobs SET status='completed',stage='completed',progress=100,result=?,updated_at=? WHERE id=?", (json.dumps(result), now_iso(), training_id)); db.execute("UPDATE runs SET status='completed',updated_at=? WHERE id=?", (now_iso(), run_id)); db.execute("UPDATE jobs SET completed_runs=completed_runs+1,updated_at=? WHERE id=?", (now_iso(), job_id))
                parent = db.execute("SELECT total_runs,completed_runs FROM jobs WHERE id=?", (job_id,)).fetchone()
                if parent and parent["completed_runs"] >= parent["total_runs"]: db.execute("UPDATE jobs SET status='completed',updated_at=? WHERE id=?", (now_iso(), job_id))
        except Exception as error:
            cancelled = "cancel" in str(error).lower(); status = "cancelled" if cancelled else "failed"
            with DB_LOCK, connect() as db:
                db.execute("UPDATE training_jobs SET status=?,stage=?,error=?,updated_at=? WHERE id=?", (status, status, str(error)[:2000], now_iso(), training_id)); db.execute("UPDATE runs SET status=?,error_message=?,updated_at=? WHERE id=?", ("stopped" if cancelled else "failed", str(error)[:2000], now_iso(), run_id))
        bump(run_id)


def resume_pending_jobs() -> int:
    reap_expired(); pending: list[tuple[str, dict, str, int, str, str | None, int, str]] = []
    with DB_LOCK, connect() as db:
        jobs = db.execute("SELECT id,concurrency,tenant_id FROM jobs WHERE status IN (?,?)", ("queued", "running")).fetchall()
        for job in jobs:
            rows = db.execute("SELECT id,params FROM runs WHERE source=? AND status IN (?,?) AND tenant_id=?", ("parameter-lab", "queued", "running", job["tenant_id"])).fetchall()
            for row in rows:
                params = json_value(row["params"], {})
                if params.get("_jobId") != job["id"]:
                    continue
                training = db.execute("SELECT id,provider,timeout_seconds FROM training_jobs WHERE run_id=? AND status IN ('queued','running')", (row["id"],)).fetchone()
                resource_id = training["id"] if training else row["id"]
                task = db.execute("SELECT status FROM durable_tasks WHERE resource_id=? AND tenant_id=? AND kind='training'", (resource_id, job["tenant_id"])).fetchone()
                # API restarts must not reset work owned by a live standalone lease.
                if task and task["status"] != "queued":
                    continue
                pending.append((row["id"], params, job["id"], int(job["concurrency"]), training["provider"] if training else "simulator", training["id"] if training else None, int(training["timeout_seconds"]) if training else 900,job["tenant_id"]))
                if EMBEDDED_WORKERS:
                    db.execute("UPDATE runs SET status=?,updated_at=? WHERE id=?", ("queued", now_iso(), row["id"]))
                    if training: db.execute("UPDATE training_jobs SET status='queued',stage='resuming',updated_at=? WHERE id=?", (now_iso(), training["id"]))
    semaphores: dict[str, threading.Semaphore] = {}
    for run_id, params, job_id, concurrency, provider, training_id, timeout,tenant_id in pending:
        semaphore = semaphores.setdefault(job_id, threading.Semaphore(concurrency))
        resource_id=training_id or run_id;task=enqueue_task(tenant_id,"training",resource_id,{"runId":run_id,"provider":provider},f"training:{resource_id}")
        if training_id: submit_durable(task,execute_real_training,training_id,run_id,params,job_id,provider,semaphore,timeout)
        else: submit_durable(task,execute_queued_run,run_id,params,job_id,semaphore)
    return len(pending)


def recover_model_operation_jobs() -> int:
    """Retire jobs interrupted by process shutdown; scene writes are atomic."""
    with DB_LOCK,connect() as db:
        rows=db.execute("SELECT id FROM model_operation_jobs WHERE status IN ('queued','running')").fetchall();timestamp=now_iso()
        for row in rows:db.execute("UPDATE model_operation_jobs SET status='failed',stage='interrupted',error='server restarted before operation completed; source scene is unchanged',updated_at=? WHERE id=?",(timestamp,row["id"]))
    return len(rows)


class Handler(BaseHTTPRequestHandler):
    server_version = "ClawVision/0.22"

    def handle_one_request(self) -> None:
        started = time.perf_counter()
        try:
            super().handle_one_request()
        except ApplicationError as error:
            self._json({"error": error.message, "code": error.code, "detail": error.detail}, error.status)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error), "code": "validation_error"}, HTTPStatus.BAD_REQUEST)
        finally:
            method=getattr(self,"command","UNKNOWN");path=urlparse(getattr(self,"path","/")).path;status=str(getattr(self,"response_status",0) or 0)
            duration=time.perf_counter()-started
            inc("clawvision_http_requests_total",method=method,path=self._metric_path(path),status=status)
            observe("clawvision_http_request_duration_seconds",duration,method=method,path=self._metric_path(path))
            trace_id=getattr(self,"trace_id","");span_id=getattr(self,"span_id","")
            if trace_id and span_id:
                record_span("http.request",trace_id,span_id,duration,parent_span_id=getattr(self,"parent_span_id",""),status="error" if status.startswith("5") else "ok",method=method,path=self._metric_path(path),httpStatus=status)

    def parse_request(self) -> bool:
        parsed=super().parse_request()
        if parsed:
            context=adopt_traceparent(self.headers.get("traceparent"));self.trace_id=context["traceId"];self.span_id=context["spanId"];self.parent_span_id=context["parentSpanId"]
        return parsed

    @staticmethod
    def _metric_path(path: str) -> str:
        return re.sub(r"/(run|data|dsv|vexp|asset|agent|text3d|modelscene|meshjob|geometry|task|usr|tok|evalset|eval|scenario|synth)_[^/]+", r"/\1_:id", path)

    def _owned(self, table: str, item_id: str) -> bool:
        allowed = {"runs","jobs","datasets","visualization_specs","model_assets","studio_generations","parameter_snapshots","agent_runs","text3d_jobs","model_scenes","model_operation_jobs","asset_projects","scene_agent_runs","geometry_jobs","training_jobs","durable_tasks"}
        if table not in allowed: raise ValueError("unsupported tenant resource")
        with DB_LOCK, connect() as db:
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
            audit(self.principal, self.command, path, "denied", {"requiredRole": "admin", "requiredScope": "admin"})
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
        self.principal = authenticate(self.headers.get("Authorization"))
        if self.principal is None:
            self._json({"error": "authentication required"}, HTTPStatus.UNAUTHORIZED); return False
        role = "admin" if admin else "researcher" if write else "viewer"
        if not self.principal.permits(role):
            audit(self.principal, self.command, path, "denied", {"requiredRole": role}); self._json({"error": f"{role} role required"}, HTTPStatus.FORBIDDEN); return False
        scope = "admin" if admin else "write" if write else "read"
        if not self.principal.permits_scope(scope):
            audit(self.principal,self.command,path,"denied",{"requiredScope":scope});self._json({"error":f"{scope} scope required"},HTTPStatus.FORBIDDEN);return False
        if write: audit(self.principal, self.command, path, "requested")
        return True

    def log_message(self, pattern: str, *args) -> None:
        print(json.dumps({"time":now_iso(),"requestId":getattr(self,"request_id",None),"traceId":getattr(self,"trace_id",None),"spanId":getattr(self,"span_id",None),"remote":self.client_address[0],"message":pattern % args},ensure_ascii=False),flush=True)

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
            value = problem_details(str(value["error"]), status_code, getattr(self, "request_id", "") or "", code=str(value.get("code") or "request_error"), detail=value.get("detail"))
        if getattr(self,"principal",None) is not None and self.command in {"POST","PATCH","DELETE"}:
            audit(self.principal,self.command,urlparse(self.path).path,"completed" if status_code<400 else "failed",{"status":status_code,"requestId":getattr(self,"request_id",None)})
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
        with DB_LOCK, connect() as db:
            row = db.execute("SELECT * FROM model_assets WHERE id=? AND tenant_id=? AND deleted_at IS NULL", (asset_id, self.principal.tenant_id)).fetchone()
        if not row:
            return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        stored = OBJECT_STORE.get_json(row["object_key"])
        binary_key = stored.get("binaryKey")
        if binary_key:
            size = OBJECT_STORE.byte_size(binary_key)
        else:
            payload = base64.b64decode(stored["base64"], validate=True)
            size = len(payload)
        if manifest_only:
            return self._json({"data": {"assetId": asset_id, "name": row["name"], "format": row["format"], "byteSize": size,
                                         "contentUrl": f"/api/model-assets/{asset_id}/content", "acceptRanges": True,
                                         "resources": [{"name": item.get("name"), "mimeType": item.get("mimeType"), "byteSize": len(base64.b64decode(item.get("base64", ""))) if item.get("base64") else 0} for item in stored.get("resources", [])],
                                         "metadata": json_value(row["metadata"], {})}})
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
        payload = OBJECT_STORE.get_range(binary_key, start, end) if binary_key else payload[start:end + 1]
        mime = {"glb": "model/gltf-binary", "gltf": "model/gltf+json", "obj": "text/plain", "stl": "model/stl"}.get(row["format"], "application/octet-stream")
        self.send_response(status); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(payload))); self.send_header("Accept-Ranges", "bytes")
        if status == HTTPStatus.PARTIAL_CONTENT: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Expose-Headers", "Content-Length, Content-Range, Accept-Ranges"); self.send_header("Cache-Control", "private, max-age=3600"); self.end_headers(); self.wfile.write(payload)

    def _page_values(self, values: list, query: dict, *, default: int = 100) -> dict:
        pagination = parse_pagination(query, default=default)
        start = pagination.offset
        return {"data": values[start:start + pagination.page_size], "pagination": page_meta(pagination, len(values))}

    def _page_table(self, table: str, query: dict, *, default: int = 100, where: str = "tenant_id=?", values: tuple | list | None = None, order_by: str = "created_at DESC", select: str = "*", mapper=dict) -> dict:
        pagination = parse_pagination(query, default=default)
        with DB_LOCK, connect() as db:
            page = CollectionService.list(db, table, pagination, where=where, values=values or (self.principal.tenant_id,), order_by=order_by, select=select, mapper=mapper)
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

    def do_GET(self) -> None:  # noqa: N802
        self.request_id=self.headers.get("X-Request-ID") or "req_"+uuid.uuid4().hex[:12]
        parsed_url = urlparse(self.path); path = parsed_url.path; query = parse_qs(parsed_url.query)
        if path == "/api/health":
            with DB_LOCK, connect() as db:
                database_ok = bool(db.execute("SELECT 1 AS ok").fetchone())
            storage = OBJECT_STORE.health_check()
            workers=worker_statuses()
            return self._json({"ok": database_ok and storage["ok"], "database": database_label(), "databaseKind": "postgresql" if is_postgres() else "sqlite", "objectStore": storage, "workers": workers, "queueRecovery": True, "time": now_iso()})
        if path == "/api/openapi.json":
            return self._json(openapi_document("0.22.0"))
        if path == "/api/metrics":
            if not self._authorize(path, admin=True): return
            queue_metrics()
            workers=worker_statuses();gauge("clawvision_workers_healthy",sum(1 for worker in workers if worker["healthy"]))
            for worker in workers:
                gauge("clawvision_worker_healthy",1 if worker["healthy"] else 0,worker=worker["workerId"])
                gauge("clawvision_worker_heartbeat_age_seconds",worker["ageSeconds"],worker=worker["workerId"])
                gauge("clawvision_worker_tasks_completed",worker["completed"],worker=worker["workerId"])
                gauge("clawvision_worker_tasks_failed",worker["failed"],worker=worker["workerId"])
            with DB_LOCK,connect() as db:runs=db.execute("SELECT status,COUNT(*) AS count FROM runs GROUP BY status").fetchall()
            for row in runs:gauge("clawvision_runs",int(row["count"]),status=row["status"])
            payload=render_prometheus().encode();self.send_response(200);self.send_header("Content-Type","text/plain; version=0.0.4");self.send_header("Content-Length",str(len(payload)));self.end_headers();self.wfile.write(payload);return
        if not self._authorize(path): return
        if path == "/api/auth/me": return self._json({"data": {"userId": self.principal.user_id, "tenantId": self.principal.tenant_id, "role": self.principal.role, "scopes": self.principal.scopes}})
        if path == "/api/auth/tokens": return self._json(self._page_values(list_tokens(self.principal), query))
        if path == "/api/auth/members": return self._json(self._page_values(list_members(self.principal), query))
        if path == "/api/quotas": return self._json({"data": quota_status(self.principal)})
        if path == "/api/tasks":
            return self._json(self._page_table("durable_tasks", query, order_by="created_at DESC,id DESC", mapper=serialize_task))
        if path == "/api/audit-logs":
            if not self.principal.permits("admin"): return self._json({"error": "admin role required"}, HTTPStatus.FORBIDDEN)
            return self._json(self._page_table("audit_logs", query, default=100))
        if path == "/api/studio/templates":
            return self._json({"data": TEMPLATES})
        if path == "/api/studio/text-to-3d/providers":
            return self._json({"data": list_text3d_providers()})
        if path == "/api/geometry/providers":
            return self._json({"data": geometry_provider_catalog()})
        if path == "/api/telemetry/3d":
            payload = self._page_table("three_telemetry", query, default=100, order_by="created_at DESC")
            payload["data"] = [{**dict(row), "payload": json_value(row["payload"], {})} for row in payload["data"]]
            return self._json(payload)
        if path == "/api/training/providers":
            return self._json({"data": training_provider_catalog()})
        training_match = re.fullmatch(r"/api/training-jobs/([^/]+)", path)
        if training_match:
            with DB_LOCK, connect() as db: row = db.execute("SELECT * FROM training_jobs WHERE id=? AND tenant_id=?", (training_match.group(1), self.principal.tenant_id)).fetchone()
            return self._json({"data": {**dict(row), "result": json_value(row["result"], {})} if row else None}, HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        if path == "/api/studio/generations":
            payload = self._page_table("studio_generations", query, order_by="updated_at DESC")
            payload["data"] = [{"id": row["id"], "name": row["name"], "prompt": row["prompt"], "provider": row["provider"], "plan": json_value(row["plan"], {}), "validation": json_value(row["validation"], {}), "assetId": row["asset_id"], "version": row["version"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]} for row in payload["data"]]
            return self._json(payload)
        scene_history_match = re.fullmatch(r"/api/studio/scenes/([^/]+)", path)
        if scene_history_match:
            payload = self._page_table("studio_scene_versions", query, where="generation_id=? AND tenant_id=?", values=(scene_history_match.group(1), self.principal.tenant_id), order_by="version DESC")
            payload["data"] = [{"id": row["id"], "generationId": row["generation_id"], "version": row["version"], "command": row["command"], "operations": json_value(row["operations"], []), "plan": json_value(row["plan"], {}), "createdAt": row["created_at"]} for row in payload["data"]]
            return self._json(payload)
        if path == "/api/studio/agent-runs":
            payload = self._page_table("agent_runs", query, default=50, select="id")
            payload["data"] = [serialize_agent_run(row["id"], OBJECT_STORE) for row in payload["data"]]
            return self._json(payload)
        agent_stream_match = re.fullmatch(r"/api/studio/agent-runs/([^/]+)/stream", path)
        if agent_stream_match:
            if not self._guard_owned("agent_runs", agent_stream_match.group(1)): return
            return self._stream_agent_run(agent_stream_match.group(1))
        agent_run_match = re.fullmatch(r"/api/studio/agent-runs/([^/]+)", path)
        if agent_run_match:
            if not self._guard_owned("agent_runs", agent_run_match.group(1)): return
            item = serialize_agent_run(agent_run_match.group(1), OBJECT_STORE)
            return self._json({"data": item}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        text3d_stream_match = re.fullmatch(r"/api/studio/text-to-3d/([^/]+)/stream", path)
        if text3d_stream_match:
            if not self._guard_owned("text3d_jobs", text3d_stream_match.group(1)): return
            return self._stream_text3d_job(text3d_stream_match.group(1))
        text3d_match = re.fullmatch(r"/api/studio/text-to-3d/([^/]+)", path)
        if text3d_match:
            if not self._guard_owned("text3d_jobs", text3d_match.group(1)): return
            item = get_text3d_job(text3d_match.group(1))
            return self._json({"data": item}, HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        model_job_match=re.fullmatch(r"/api/model-operation-jobs/([^/]+)",path)
        if model_job_match:
            with DB_LOCK,connect() as db:row=db.execute("SELECT * FROM model_operation_jobs WHERE id=? AND tenant_id=?",(model_job_match.group(1),self.principal.tenant_id)).fetchone()
            return self._json({"data":serialize_model_operation_job(row)},HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        geometry_job_match=re.fullmatch(r"/api/geometry-jobs/([^/]+)",path)
        if geometry_job_match:
            with DB_LOCK,connect() as db: row=db.execute("SELECT * FROM geometry_jobs WHERE id=? AND tenant_id=?",(geometry_job_match.group(1),self.principal.tenant_id)).fetchone()
            return self._json({"data":serialize_geometry_job(row)},HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        scene_agent_stream=re.fullmatch(r"/api/scene-agent-runs/([^/]+)/stream",path)
        if scene_agent_stream:
            if not self._guard_owned("scene_agent_runs",scene_agent_stream.group(1)): return
            return self._stream_scene_agent(scene_agent_stream.group(1))
        scene_agent_match=re.fullmatch(r"/api/scene-agent-runs/([^/]+)",path)
        if scene_agent_match:
            if not self._guard_owned("scene_agent_runs",scene_agent_match.group(1)): return
            item=self._scene_agent_payload(scene_agent_match.group(1));return self._json({"data":item},HTTPStatus.OK if item else HTTPStatus.NOT_FOUND)
        scene_agents_match=re.fullmatch(r"/api/model-scenes/([^/]+)/agent-runs",path)
        if scene_agents_match:
            if not self._guard_owned("model_scenes",scene_agents_match.group(1)): return
            payload = self._page_table("scene_agent_runs", query, default=50, where="scene_id=? AND tenant_id=?", values=(scene_agents_match.group(1), self.principal.tenant_id), select="id")
            payload["data"] = [self._scene_agent_payload(row["id"]) for row in payload["data"]]
            return self._json(payload)
        if path == "/api/parameter-snapshots":
            payload = self._page_table("parameter_snapshots", query)
            payload["data"] = [{"id": row["id"], "name": row["name"], "runId": row["run_id"], "params": json_value(row["params"], {}), "createdAt": row["created_at"]} for row in payload["data"]]
            return self._json(payload)
        if path == "/api/asset-projects":
            pagination = parse_pagination(query)
            with DB_LOCK, connect() as db:
                total = int(db.execute("SELECT COUNT(*) AS count FROM asset_projects WHERE tenant_id=?", (self.principal.tenant_id,)).fetchone()["count"])
                rows = db.execute("SELECT p.*,(SELECT COUNT(*) FROM model_assets a WHERE a.project_id=p.id AND a.tenant_id=p.tenant_id AND a.deleted_at IS NULL) AS asset_count FROM asset_projects p WHERE p.tenant_id=? ORDER BY p.name LIMIT ? OFFSET ?", (self.principal.tenant_id, pagination.page_size, pagination.offset)).fetchall()
            return self._json({"data": [{"id": row["id"], "name": row["name"], "description": row["description"], "assetCount": row["asset_count"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]} for row in rows], "pagination": page_meta(pagination, total)})
        if path == "/api/runs":
            pagination = parse_pagination(query)
            return self._json(run_service().list(self.principal.tenant_id, pagination, summary=(query.get("summary") or [""])[0] == "1", search=(query.get("q") or [""])[0]))
        if path == "/api/jobs":
            payload = self._page_table("jobs", query, default=50)
            payload["data"] = [{**row, "payload": json_value(row["payload"], {})} for row in payload["data"]]
            return self._json(payload)
        if path.startswith("/api/evaluation/"):
            service, tenant = EvaluationService(connect), self.principal.tenant_id
            pagination = parse_pagination(query, default=25, maximum=100)
            if path == "/api/evaluation/image-versions":
                return self._json(VisionDatasetService(connect,OBJECT_STORE,DB_LOCK).list(tenant,pagination))
            image_version = re.fullmatch(r"/api/evaluation/image-versions/([^/]+)(?:/images/(\d+))?",path)
            if image_version:
                images = VisionDatasetService(connect,OBJECT_STORE,DB_LOCK)
                if image_version.group(2) is not None: return self._binary(images.image(tenant,image_version.group(1),int(image_version.group(2))),"image/png")
                return self._json({"data":images.get(tenant,image_version.group(1))})
            if path == "/api/evaluation/experiments":
                return self._json(VisionExperimentService(connect,OBJECT_STORE,DB_LOCK).list(tenant,pagination))
            experiment = re.fullmatch(r"/api/evaluation/experiments/([^/]+)",path)
            if experiment: return self._json({"data":VisionExperimentService(connect,OBJECT_STORE,DB_LOCK).get(tenant,experiment.group(1))})
            synthesis_service = SynthesisService(connect, OBJECT_STORE, DB_LOCK)
            render_list = re.fullmatch(r"/api/evaluation/scenarios/([^/]+)/renders", path)
            if render_list:
                return self._json(synthesis_service.list(tenant, pagination, render_list.group(1)))
            render_match = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)(/(frames|manifest|export))?", path)
            if render_match:
                job_id, action = render_match.group(1), render_match.group(3)
                if action == "export":
                    return self._binary(synthesis_service.package(tenant, job_id), "application/zip", job_id+".zip")
                if action == "manifest": return self._json({"data": synthesis_service.manifest(tenant, job_id)})
                if action == "frames": return self._json(synthesis_service.frames(tenant, job_id, pagination))
                return self._json({"data": synthesis_service.get(tenant, job_id)})
            render_artifact = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)/frames/(\d+)/(image|mask|amodalMask)", path)
            if render_artifact:
                return self._binary(synthesis_service.artifact(tenant, render_artifact.group(1), int(render_artifact.group(2)), render_artifact.group(3)), "image/png")
            if path == "/api/evaluation/scenarios":
                return self._json(ScenarioService(connect, OBJECT_STORE, DB_LOCK).list(tenant, pagination, (query.get("reportId") or [None])[0]))
            scenario_match = re.fullmatch(r"/api/evaluation/scenarios/([^/]+)(/(export|asset))?", path)
            if scenario_match:
                scenario_service = ScenarioService(connect, OBJECT_STORE, DB_LOCK)
                method = scenario_service.preview_asset if scenario_match.group(3) == "asset" else scenario_service.get
                return self._json({"data": method(tenant, scenario_match.group(1))})
            if path == "/api/evaluation/test-sets":
                return self._json(service.list_test_sets(tenant, pagination))
            if path == "/api/evaluation/reports":
                return self._json(service.list_evaluations(tenant, pagination, (query.get("testSetId") or [None])[0]))
            if path == "/api/evaluation/compare":
                return self._json({"data": service.compare(tenant, (query.get("baselineId") or [""])[0], (query.get("candidateId") or [""])[0])})
            match = re.fullmatch(r"/api/evaluation/test-sets/([^/]+)(/export)?", path)
            if match:
                method = service.export_test_set if match.group(2) else service.get_test_set
                return self._json({"data": method(tenant, match.group(1))})
            match = re.fullmatch(r"/api/evaluation/reports/([^/]+)(/cases)?", path)
            if match:
                if not match.group(2):
                    return self._json({"data": service.get_evaluation(tenant, match.group(1))})
                failures_only = (query.get("failuresOnly") or ["true"])[0]
                if failures_only not in {"true", "false"}:
                    raise ValidationError("failuresOnly must be true or false")
                return self._json(service.cases(tenant, match.group(1), pagination, failures_only=failures_only == "true",
                                               dimension=(query.get("dimension") or [None])[0], value=(query.get("value") or [None])[0]))
        if path == "/api/datasets":
            pagination = parse_pagination(query, default=50)
            with DB_LOCK, connect() as db:
                page = CollectionService.list(db, "datasets", pagination, values=(self.principal.tenant_id,))
            return self._json({"data": [{"id": row["id"], "name": row["name"], "format": row["format"], "storageFormat": row.get("storage_format", "json"), "schema": json_value(row["schema_json"], []), "schemaVersion": row.get("schema_version", 1), "currentVersionId": row.get("current_version_id"), "partitionBy": json_value(row.get("partition_by"), []), "rowCount": row["row_count"], "createdAt": row["created_at"], "updatedAt": row.get("updated_at") or row["created_at"]} for row in page.rows], "pagination": page.pagination})
        dataset_versions_match = re.fullmatch(r"/api/datasets/([^/]+)/versions", path)
        if dataset_versions_match:
            versions = DatasetCatalog(connect, OBJECT_STORE).versions(dataset_versions_match.group(1), self.principal.tenant_id)
            return self._json(self._page_values(versions, query, default=50))
        dataset_lineage_match = re.fullmatch(r"/api/datasets/([^/]+)/lineage", path)
        if dataset_lineage_match:
            return self._json({"data": DatasetCatalog(connect, OBJECT_STORE).lineage(dataset_lineage_match.group(1), self.principal.tenant_id)})
        if path == "/api/analysis/queries":
            payload = self._page_table("analysis_queries", query, default=50, order_by="created_at DESC")
            payload["data"] = [analysis_service().get(row["id"], self.principal.tenant_id, include_result=False) for row in payload["data"]]
            return self._json(payload)
        analysis_query_match = re.fullmatch(r"/api/analysis/queries/([^/]+)", path)
        if analysis_query_match:
            return self._json({"data": analysis_service().get(analysis_query_match.group(1), self.principal.tenant_id)})
        dataset_match = re.fullmatch(r"/api/datasets/([^/]+)", path)
        if dataset_match:
            with DB_LOCK, connect() as db:
                row = db.execute("SELECT * FROM datasets WHERE id=? AND tenant_id=?", (dataset_match.group(1), self.principal.tenant_id)).fetchone()
                if not row:
                    return self._json({"error": "dataset not found"}, HTTPStatus.NOT_FOUND)
                keys = set(row.keys())
                return self._json({"data": {"id": row["id"], "name": row["name"], "format": row["format"], "storageFormat": row["storage_format"] if "storage_format" in keys else "json", "schema": json_value(row["schema_json"], []), "schemaVersion": row["schema_version"] if "schema_version" in keys else 1, "currentVersionId": row["current_version_id"] if "current_version_id" in keys else None, "partitionBy": json_value(row["partition_by"], []) if "partition_by" in keys else [], "rows": OBJECT_STORE.get_json(row["object_key"]), "rowCount": row["row_count"], "createdAt": row["created_at"], "updatedAt": row["updated_at"] if "updated_at" in keys else row["created_at"]}})
        if path == "/api/visualization-specs":
            payload = self._page_table("visualization_specs", query, order_by="updated_at DESC")
            payload["data"] = [{"id": row["id"], "name": row["name"], "datasetId": row["dataset_id"], "spec": json_value(row["spec"], {}), "shareToken": row["share_token"], "isPublic": bool(row["is_public"]), "version": row["version"], "updatedAt": row["updated_at"]} for row in payload["data"]]
            return self._json(payload)
        spec_match = re.fullmatch(r"/api/visualization-specs/([^/]+)", path)
        share_match = re.fullmatch(r"/api/shared/([^/]+)", path)
        if spec_match or share_match:
            with DB_LOCK, connect() as db:
                field, value = ("id", spec_match.group(1)) if spec_match else ("share_token", share_match.group(1))
                row = db.execute(f"SELECT * FROM visualization_specs WHERE {field}=? AND (tenant_id=? OR is_public=1)", (value, self.principal.tenant_id)).fetchone()
                if not row or (share_match and not row["is_public"]):
                    return self._json({"error": "visualization spec not found"}, HTTPStatus.NOT_FOUND)
                return self._json({"data": {"id": row["id"], "name": row["name"], "datasetId": row["dataset_id"], "spec": json_value(row["spec"], {}), "shareToken": row["share_token"], "isPublic": bool(row["is_public"]), "version": row["version"], "updatedAt": row["updated_at"]}})
        if path == "/api/model-assets":
            pagination = parse_pagination(query, default=100)
            clauses = ["tenant_id=?"]; values: list = [self.principal.tenant_id]
            if query.get("q"):
                clauses.append("LOWER(name) LIKE ?"); values.append(f"%{query['q'][0].lower()}%")
            for parameter, column in (("projectId", "project_id"), ("stage", "stage"), ("folder", "folder")):
                if query.get(parameter): clauses.append(f"{column}=?"); values.append(query[parameter][0])
            if query.get("tag"):
                clauses.append("LOWER(tags) LIKE ?"); values.append(f"%{query['tag'][0].lower()}%")
            if query.get("archived", ["false"])[0].lower() != "true": clauses.append("archived_at IS NULL")
            if query.get("deleted", ["false"])[0].lower() != "true": clauses.append("deleted_at IS NULL")
            with DB_LOCK, connect() as db:
                total = int(db.execute(f"SELECT COUNT(*) AS count FROM model_assets WHERE {' AND '.join(clauses)}", values).fetchone()["count"])
                rows = db.execute(f"SELECT * FROM model_assets WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC,created_at DESC LIMIT ? OFFSET ?", (*values, pagination.page_size, pagination.offset)).fetchall()
            return self._json({"data": [serialize_model_asset(row) for row in rows], "pagination": page_meta(pagination, total)})
        if path == "/api/model-scenes":
            payload = self._page_table("model_scenes", query, order_by="updated_at DESC")
            payload["data"] = [serialize_model_scene(row) for row in payload["data"]]
            return self._json(payload)
        scene_versions_match=re.fullmatch(r"/api/model-scenes/([^/]+)/versions",path)
        scene_match=re.fullmatch(r"/api/model-scenes/([^/]+)",path)
        if scene_versions_match or scene_match:
            scene_id=(scene_versions_match or scene_match).group(1)
            with DB_LOCK,connect() as db: row=db.execute("SELECT * FROM model_scenes WHERE id=? AND tenant_id=?",(scene_id,self.principal.tenant_id)).fetchone()
            if not row: return self._json({"error":"model scene not found"},HTTPStatus.NOT_FOUND)
            return self._json({"data":serialize_model_scene(row,include_versions=bool(scene_versions_match))})
        asset_stream_match = re.fullmatch(r"/api/model-assets/([^/]+)/(stream-manifest|content)", path)
        if asset_stream_match:
            return self._stream_model_asset(asset_stream_match.group(1), asset_stream_match.group(2) == "stream-manifest")
        asset_match = re.fullmatch(r"/api/model-assets/([^/]+)", path)
        if asset_match:
            with DB_LOCK, connect() as db:
                row = db.execute("SELECT * FROM model_assets WHERE id=? AND tenant_id=?", (asset_match.group(1), self.principal.tenant_id)).fetchone()
                if not row:
                    return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
                include_content=query.get("content",["true"])[0].lower() not in {"0","false","no"}
                return self._json({"data": serialize_model_asset(row, include_content, True)})
        artifact_match = re.fullmatch(r"/api/artifacts/([^/]+)/content", path)
        if artifact_match:
            with DB_LOCK, connect() as db:
                item = db.execute("SELECT a.* FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.id=? AND r.tenant_id=?", (artifact_match.group(1), self.principal.tenant_id)).fetchone()
                if not item:
                    return self._json({"error": "artifact not found"}, HTTPStatus.NOT_FOUND)
                object_key = item["object_key"] if "object_key" in item.keys() else None
                content = OBJECT_STORE.get_json(object_key) if object_key else json_value(item["content"], item["content"])
                return self._json({"data": content})
        stream_match = re.fullmatch(r"/api/runs/([^/]+)/stream", path)
        if stream_match:
            if not self._guard_owned("runs", stream_match.group(1)): return
            return self._stream(stream_match.group(1), query)
        changes_match = re.fullmatch(r"/api/runs/([^/]+)/changes", path)
        if changes_match:
            return self._json({"data": run_service().changes(changes_match.group(1), self.principal.tenant_id, int((query.get("after") or ["0"])[0]), int((query.get("limit") or ["100"])[0]))})
        timeline_match = re.fullmatch(r"/api/runs/([^/]+)/timeline", path)
        if timeline_match:
            if not self._guard_owned("runs", timeline_match.group(1)): return
            return self._run_timeline(timeline_match.group(1))
        lineage_match = re.fullmatch(r"/api/runs/([^/]+)/lineage", path)
        if lineage_match:
            if not self._guard_owned("runs", lineage_match.group(1)): return
            with DB_LOCK,connect() as db: row=db.execute("SELECT * FROM training_lineage WHERE run_id=? AND tenant_id=?",(lineage_match.group(1),self.principal.tenant_id)).fetchone()
            return self._json({"data": {**dict(row),"environment":json_value(row["environment"],{})} if row else None},HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)
        run_match = re.fullmatch(r"/api/runs/([^/]+)", path)
        if run_match:
            if not self._guard_owned("runs", run_match.group(1)): return
            run = run_service().get(run_match.group(1), self.principal.tenant_id)
            return self._json({"data": run}, HTTPStatus.OK if run else HTTPStatus.NOT_FOUND)
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/auth/bootstrap":
                principal, token = bootstrap(str(body.get("email") or ""), str(body.get("password") or ""), str(body.get("tenantName") or "ClawVision")); return self._json({"data": {"token": token, "userId": principal.user_id, "tenantId": principal.tenant_id, "role": principal.role}}, HTTPStatus.CREATED)
            if path == "/api/auth/login":
                principal, token = login(str(body.get("email") or ""), str(body.get("password") or "")); return self._json({"data": {"token": token, "userId": principal.user_id, "tenantId": principal.tenant_id, "role": principal.role}})
            if not self._authorize(path, write=True, admin=path in {"/api/auth/tokens", "/api/credential-refs"}): return
            if not self._guard_write_path(path, body): return
            if path == "/api/telemetry/3d":
                return self._save_three_telemetry(body)
            if path == "/api/auth/tokens": return self._json({"data": {"token": issue_token(self.principal, str(body.get("name") or "API token"), body.get("scopes") if isinstance(body.get("scopes"), list) else None, int(body.get("expiresHours") or 720))}}, HTTPStatus.CREATED)
            if path == "/api/auth/members": return self._json({"data": create_member(self.principal, str(body.get("email") or ""), str(body.get("password") or ""), str(body.get("role") or "viewer"))}, HTTPStatus.CREATED)
            if path == "/api/credential-refs":
                item_id = save_credential(self.principal, str(body.get("provider") or ""), str(body.get("name") or "credential"), str(body.get("secret") or ""))
                return self._json({"data": {"id": item_id, "provider": body.get("provider"), "name": body.get("name")}}, HTTPStatus.CREATED)
            if path == "/api/runs":
                return self._create_run(body)
            if path == "/api/evaluation/image-datasets":
                return self._json({"data":VisionDatasetService(connect,OBJECT_STORE,DB_LOCK).create_real(self.principal.tenant_id,body)},HTTPStatus.CREATED)
            register_synthetic = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)/dataset-version",path)
            if register_synthetic:
                return self._json({"data":VisionDatasetService(connect,OBJECT_STORE,DB_LOCK).from_synthesis(self.principal.tenant_id,register_synthetic.group(1),body)},HTTPStatus.CREATED)
            experiment_action = re.fullmatch(r"/api/evaluation/experiments/([^/]+)/(cancel|retry)",path)
            if path == "/api/evaluation/experiments" or experiment_action:
                service = VisionExperimentService(connect,OBJECT_STORE,DB_LOCK)
                result = service.action(self.principal.tenant_id,experiment_action.group(1),experiment_action.group(2)) if experiment_action else service.create(self.principal.tenant_id,body)
                if result["status"] == "queued":
                    with connect() as db: task = serialize_task(db.execute("SELECT * FROM durable_tasks WHERE id=?",(result["taskId"],)).fetchone())
                    submit_synthesis(task)
                return self._json({"data":result},HTTPStatus.ACCEPTED)
            synthesis_create = re.fullmatch(r"/api/evaluation/scenarios/([^/]+)/renders", path)
            synthesis_action = re.fullmatch(r"/api/evaluation/synthesis/([^/]+)/(cancel|retry)", path)
            if synthesis_create or synthesis_action:
                service = SynthesisService(connect, OBJECT_STORE, DB_LOCK)
                tenant = self.principal.tenant_id
                if synthesis_create:
                    result = service.create(tenant, synthesis_create.group(1), body)
                else:
                    result = service.action(tenant, synthesis_action.group(1), synthesis_action.group(2))
                if result["status"] == "queued":
                    with connect() as db: task = serialize_task(db.execute("SELECT * FROM durable_tasks WHERE id=?", (result["taskId"],)).fetchone())
                    submit_synthesis(task)
                return self._json({"data": result}, HTTPStatus.ACCEPTED)
            if path == "/api/evaluation/scenarios":
                return self._json({"data": ScenarioService(connect, OBJECT_STORE, DB_LOCK).create(self.principal.tenant_id, body)}, HTTPStatus.CREATED)
            if path == "/api/evaluation/test-sets":
                return self._json({"data": EvaluationService(connect).create_test_set(self.principal.tenant_id, body)}, HTTPStatus.CREATED)
            if path == "/api/evaluation/reports":
                return self._json({"data": EvaluationService(connect).create_evaluation(self.principal.tenant_id, body)}, HTTPStatus.CREATED)
            if path == "/api/jobs":
                return self._create_job(body)
            task_cancel = re.fullmatch(r"/api/tasks/([^/]+)/cancel", path)
            if task_cancel:
                return self._json({"ok": cancel_task(task_cancel.group(1), self.principal.tenant_id)}, HTTPStatus.ACCEPTED)
            training_cancel = re.fullmatch(r"/api/training-jobs/([^/]+)/cancel", path)
            if training_cancel:
                training_id = training_cancel.group(1)
                with DB_LOCK, connect() as db:
                    db.execute("UPDATE training_jobs SET cancel_requested=1,stage='cancelling',updated_at=? WHERE id=? AND tenant_id=?", (now_iso(), training_id,self.principal.tenant_id))
                    task_row=db.execute("SELECT id FROM durable_tasks WHERE resource_id=? AND tenant_id=? AND kind='training'",(training_id,self.principal.tenant_id)).fetchone()
                if task_row: cancel_task(task_row["id"],self.principal.tenant_id)
                cancel_training_process(training_id)
                return self._json({"data": {"id": training_id, "cancelRequested": True}}, HTTPStatus.ACCEPTED)
            if path == "/api/datasets":
                return self._create_dataset(body)
            dataset_version = re.fullmatch(r"/api/datasets/([^/]+)/versions", path)
            if dataset_version:
                return self._create_dataset(body, dataset_version.group(1))
            dataset_query = re.fullmatch(r"/api/datasets/([^/]+)/query", path)
            if dataset_query:
                return self._query_dataset(dataset_query.group(1), body)
            if path == "/api/analysis/query":
                return self._json({"data": analysis_service().execute(self.principal.tenant_id, body)})
            if path == "/api/analysis/queries":
                return self._json({"data": analysis_service().submit(self.principal.tenant_id, body)}, HTTPStatus.ACCEPTED)
            analysis_cancel = re.fullmatch(r"/api/analysis/queries/([^/]+)/cancel", path)
            if analysis_cancel:
                return self._json({"data": analysis_service().cancel(analysis_cancel.group(1), self.principal.tenant_id)}, HTTPStatus.ACCEPTED)
            if path == "/api/visualization-specs":
                return self._save_visualization_spec(body)
            if path == "/api/model-assets":
                return self._create_model_asset(body)
            if path == "/api/asset-projects":
                return self._create_asset_project(body)
            if path == "/api/model-assets/batch":
                return self._batch_update_assets(body)
            if path == "/api/model-assets/garbage-collect":
                return self._garbage_collect_assets(body)
            run_asset_link = re.fullmatch(r"/api/runs/([^/]+)/assets", path)
            if run_asset_link:
                return self._link_run_asset(run_asset_link.group(1), body)
            asset_catalog_action = re.fullmatch(r"/api/model-assets/([^/]+)/(archive|restore|components|releases)", path)
            if asset_catalog_action:
                asset_id, action = asset_catalog_action.groups()
                if action == "archive": return self._set_asset_archive(asset_id, True)
                if action == "restore": return self._set_asset_archive(asset_id, False)
                if action == "components": return self._create_asset_component(asset_id, body)
                return self._create_asset_release(asset_id, body)
            asset_geometry_job=re.fullmatch(r"/api/model-assets/([^/]+)/geometry-jobs",path)
            if asset_geometry_job:return self._create_geometry_job(None,asset_geometry_job.group(1),body)
            asset_scene_import=re.fullmatch(r"/api/model-assets/([^/]+)/scene",path)
            if asset_scene_import:
                return self._import_model_scene(asset_scene_import.group(1),body)
            scene_async=re.fullmatch(r"/api/model-scenes/([^/]+)/operations/async",path)
            if scene_async:return self._queue_model_operations(scene_async.group(1),body)
            model_job_cancel=re.fullmatch(r"/api/model-operation-jobs/([^/]+)/cancel",path)
            if model_job_cancel:return self._cancel_model_operation(model_job_cancel.group(1))
            geometry_cancel=re.fullmatch(r"/api/geometry-jobs/([^/]+)/cancel",path)
            if geometry_cancel:return self._cancel_geometry_job(geometry_cancel.group(1))
            scene_agent_create=re.fullmatch(r"/api/model-scenes/([^/]+)/agent-runs",path)
            if scene_agent_create:return self._create_scene_agent(scene_agent_create.group(1),body)
            scene_agent_action=re.fullmatch(r"/api/scene-agent-runs/([^/]+)/(confirm|apply|reject|cancel)",path)
            if scene_agent_action:
                agent_id,action=scene_agent_action.groups()
                if action=="confirm":return self._confirm_scene_agent(agent_id)
                if action=="apply":return self._apply_scene_agent(agent_id)
                return self._stop_scene_agent(agent_id,action)
            scene_geometry_job=re.fullmatch(r"/api/model-scenes/([^/]+)/geometry-jobs",path)
            if scene_geometry_job:return self._create_geometry_job(scene_geometry_job.group(1),None,body)
            scene_action=re.fullmatch(r"/api/model-scenes/([^/]+)/(command|preview|operations|restore|repair|export)",path)
            if scene_action:
                scene_id,action=scene_action.groups()
                if action=="command": return self._model_scene_command(scene_id,body)
                if action=="preview": return self._preview_model_scene(scene_id,body)
                if action=="operations": return self._apply_model_scene(scene_id,body)
                if action=="restore": return self._restore_model_scene(scene_id,body)
                if action=="repair": return self._repair_model_scene(scene_id,body)
                return self._export_model_scene(scene_id)
            if path == "/api/ai/interpret":
                return self._interpret_ai(body)
            if path == "/api/studio/generations":
                return self._save_studio_generation(body)
            if path == "/api/studio/scene-command":
                plan = body.get("plan")
                if not isinstance(plan, dict): raise ValueError("plan must be an object")
                return self._json({"data": interpret_scene_command(str(body.get("command") or ""), plan)}, HTTPStatus.CREATED)
            if path == "/api/studio/scenes/apply":
                return self._apply_scene_operations(body)
            if path == "/api/studio/agent-runs":
                return self._create_agent_pipeline(body)
            if path == "/api/studio/text-to-3d":
                return self._create_text3d_worker_job(body)
            agent_cancel = re.fullmatch(r"/api/studio/agent-runs/([^/]+)/cancel", path)
            if agent_cancel:
                item=cancel_agent_run(agent_cancel.group(1)); return self._json({"data":item},HTTPStatus.ACCEPTED if item else HTTPStatus.NOT_FOUND)
            text3d_cancel = re.fullmatch(r"/api/studio/text-to-3d/([^/]+)/cancel", path)
            if text3d_cancel:
                item=cancel_text3d_job(text3d_cancel.group(1)); return self._json({"data":item},HTTPStatus.ACCEPTED if item else HTTPStatus.NOT_FOUND)
            if path == "/api/studio/validate":
                return self._json({"data": validate_plan(body.get("plan") if isinstance(body.get("plan"), dict) else {})})
            if path == "/api/studio/mesh":
                return self._compile_studio_mesh(body)
            if path == "/api/studio/export":
                return self._export_studio_asset(body)
            if path == "/api/parameter-snapshots":
                return self._save_parameter_snapshot(body)
            feedback_match = re.fullmatch(r"/api/studio/generations/([^/]+)/feedback", path)
            if feedback_match:
                return self._save_studio_feedback(feedback_match.group(1), body)
            match = re.fullmatch(r"/api/runs/([^/]+)/(batch|params|metrics|events|artifacts|finish|fail|stop|resume)", path)
            lineage_match = re.fullmatch(r"/api/runs/([^/]+)/lineage", path)
            if lineage_match: return self._save_training_lineage(lineage_match.group(1), body)
            if not match:
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            run_id, action = match.groups()
            if action == "batch":
                return self._batch(run_id, body)
            if action == "params":
                return self._log_params(run_id, body)
            if action == "metrics":
                return self._log_metrics(run_id, body)
            if action == "events":
                return self._log_event(run_id, body)
            if action == "artifacts":
                return self._log_artifact(run_id, body)
            if action == "resume":
                return self._resume_run(run_id, body)
            status = "completed" if action == "finish" else "stopped" if action == "stop" else "failed"
            return self._set_status(run_id, status, body)
        except ApplicationError as error:
            self._json({"error": error.message, "code": error.code, "detail": error.detail}, error.status)
        except PermissionError as error:
            self._json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            if is_integrity_error(error):
                return self._json({"error": str(error)}, HTTPStatus.CONFLICT)
            self._json({"error": str(error)}, HTTPStatus.BAD_GATEWAY if path == "/api/ai/interpret" else HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if not self._authorize(path, write=True): return
            body = self._body()
            if not self._guard_write_path(path, body): return
            match = re.fullmatch(r"/api/model-assets/([^/]+)", path)
            if match: return self._update_model_asset(match.group(1), body)
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError) as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:
            self._json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed_url = urlparse(self.path); path = parsed_url.path; query = parse_qs(parsed_url.query)
        try:
            if not self._authorize(path, write=True, admin=query.get("purge", ["false"])[0].lower() == "true"): return
            token_match = re.fullmatch(r"/api/auth/tokens/([^/]+)", path)
            if token_match: return self._json({"ok": revoke_token(self.principal, token_match.group(1))})
            match = re.fullmatch(r"/api/model-assets/([^/]+)", path)
            if not match: return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return self._delete_model_asset(match.group(1), query.get("purge", ["false"])[0].lower() == "true")
        except Exception as error:
            if is_integrity_error(error): return self._json({"error": str(error)}, HTTPStatus.CONFLICT)
            self._json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _interpret_ai(self, body: dict) -> None:
        result = interpret(body)
        self._json({"data": result}, HTTPStatus.CREATED)

    def _create_agent_pipeline(self, body: dict) -> None:
        check_task_quota(self.principal)
        prompt = str(body.get("prompt") or "").strip()
        if not prompt or len(prompt) > 4000:
            raise ValueError("prompt must contain 1 to 4000 characters")
        provider = str(body.get("provider") or "local").lower()
        if provider not in {"local", "openai", "deepseek", "kimi", "qwen"}:
            raise ValueError("unsupported provider")
        if provider != "local" and not resolve_provider_key(provider, str(body.get("credentialRef") or "") or None):
            raise ValueError(f"server credential is not configured for {provider}")
        defaults = {"openai": "gpt-4.1-mini", "deepseek": "deepseek-v4-flash", "kimi": "moonshot-v1-8k", "qwen": "qwen-plus"}
        request = {**body, "prompt": prompt, "provider": provider, "model": str(body.get("model") or defaults.get(provider, "local"))}
        default_cycles = int(os.environ.get("AGENT_QUALITY_MAX_CYCLES", "2"))
        timeout=max(15,min(1800,int(body.get("timeoutSeconds") or 300)))
        run_id = create_agent_run(prompt, provider, request["model"], max(1, min(4, int(body.get("maxCycles") or default_cycles))),timeout,self.principal.tenant_id)
        task=enqueue_task(self.principal.tenant_id,"agent-pipeline",run_id,request,f"agent:{run_id}")
        submit_durable(task,execute_agent_pipeline,run_id,request,OBJECT_STORE)
        self._json({"data": serialize_agent_run(run_id, OBJECT_STORE)}, HTTPStatus.ACCEPTED)

    def _create_text3d_worker_job(self, body: dict) -> None:
        check_task_quota(self.principal)
        prompt = str(body.get("prompt") or "").strip()
        if not prompt or len(prompt) > 4000:
            raise ValueError("prompt must contain 1 to 4000 characters")
        resolution = max(24, min(56, int(body.get("resolution") or 38)))
        provider=str(body.get("provider") or "local-implicit").lower()
        image=str(body.get("imageBase64") or "") or None
        timeout=max(30,min(3600,int(body.get("timeoutSeconds") or 600)))
        memory=max(1024,min(65536,int(body.get("memoryBudgetMb") or 8192)))
        job_id = create_text3d_job(prompt,provider,image,timeout,memory,OBJECT_STORE,self.principal.tenant_id)
        task=enqueue_task(self.principal.tenant_id,"text-to-3d",job_id,{"provider":provider},f"text3d:{job_id}")
        submit_durable(task,execute_text3d_job,job_id,prompt,resolution,OBJECT_STORE,provider,image,timeout,memory)
        self._json({"data": get_text3d_job(job_id)}, HTTPStatus.ACCEPTED)

    def _save_studio_generation(self, body: dict) -> None:
        plan = body.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        generation_id = str(body.get("id") or f"gen_{uuid.uuid4().hex[:12]}")
        timestamp = now_iso()
        validation = validate_plan(plan)
        with DB_LOCK, connect() as db:
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
        self._json({"data": {"id": row["id"], "name": row["name"], "prompt": row["prompt"], "provider": row["provider"], "plan": json_value(row["plan"], {}), "validation": json_value(row["validation"], {}), "assetId": row["asset_id"], "version": row["version"], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}}, HTTPStatus.CREATED)

    def _apply_scene_operations(self, body: dict) -> None:
        plan=body.get("plan"); operations=body.get("operations")
        if not isinstance(plan,dict) or not isinstance(operations,list): raise ValueError("plan and operations are required")
        result=apply_operations(plan,operations); generation_id=str(body.get("generationId") or "draft")
        with DB_LOCK,connect() as db:
            row=db.execute("SELECT MAX(version) AS version FROM studio_scene_versions WHERE generation_id=? AND tenant_id=?",(generation_id,self.principal.tenant_id)).fetchone()
            version=int(row["version"] or 0)+1; item_id="scene_"+uuid.uuid4().hex[:12]
            db.execute("INSERT INTO studio_scene_versions(id,generation_id,version,command,operations,plan,created_at,tenant_id) VALUES(?,?,?,?,?,?,?,?)",
                       (item_id,generation_id,version,str(body.get("command") or "manual edit"),json.dumps(operations,ensure_ascii=False),json.dumps(result,ensure_ascii=False),now_iso(),self.principal.tenant_id))
        self._json({"data":{"id":item_id,"generationId":generation_id,"version":version,"plan":result,"operations":operations}},HTTPStatus.CREATED)

    def _save_studio_feedback(self, generation_id: str, body: dict) -> None:
        rating = max(1, min(5, int(body.get("rating") or 0)))
        with DB_LOCK, connect() as db:
            if not db.execute("SELECT 1 FROM studio_generations WHERE id=? AND tenant_id=?", (generation_id,self.principal.tenant_id)).fetchone():
                return self._json({"error": "generation not found"}, HTTPStatus.NOT_FOUND)
            db.execute("INSERT INTO studio_feedback(generation_id,rating,comment,created_at) VALUES(?,?,?,?)", (generation_id, rating, str(body.get("comment") or ""), now_iso()))
        self._json({"ok": True}, HTTPStatus.CREATED)

    def _compile_studio_mesh(self, body: dict) -> None:
        plan = body.get("plan")
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        quality = str(body.get("quality") or "high").lower()
        if quality not in {"standard", "high", "ultra"}:
            raise ValueError("quality must be standard, high or ultra")
        payload, stats = compile_obj(plan, quality)
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
        payload, stats = compile_obj(plan, quality) if asset_format == "obj" else compile_gltf(plan, quality, binary=asset_format == "glb")
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
        created_at = now_iso()
        with DB_LOCK, connect() as db:
            db.execute("INSERT INTO parameter_snapshots(id,name,run_id,params,created_at,tenant_id) VALUES(?,?,?,?,?,?)", (snapshot_id, str(body.get("name") or "Parameter snapshot"), run_id, json.dumps(params, ensure_ascii=False), created_at,self.principal.tenant_id))
        self._json({"data": {"id": snapshot_id, "name": str(body.get("name") or "Parameter snapshot"), "runId": run_id, "params": params, "createdAt": created_at}}, HTTPStatus.CREATED)

    def _create_dataset(self, body: dict, existing_dataset_id: str | None = None) -> None:
        raw_files = body.get("files")
        if raw_files is None:
            raw_files = [{"format": body.get("format", "json"), "content": body.get("content"), "partitions": body.get("partitions", {})}]
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("files must be a non-empty array")
        partition_by = body.get("partitionBy") or []
        if not isinstance(partition_by, list) or not all(isinstance(field, str) and field for field in partition_by):
            raise ValueError("partitionBy must be an array of field names")
        maximum_rows = max(1, int(os.environ.get("CLAWVISION_DATASET_MAX_ROWS", "25000000")))
        preview_limit = max(1, int(os.environ.get("CLAWVISION_DATASET_PREVIEW_ROWS", "10000")))
        decoded: list[dict] = []
        preview: list[dict] = []
        total_rows = 0
        per_file_preview = max(1, preview_limit // len(raw_files))
        for index, item in enumerate(raw_files):
            if not isinstance(item, dict):
                raise ValueError("each file must be an object")
            data_format = str(item.get("format") or body.get("format") or "json").lower()
            content = item.get("content")
            payload: bytes | None = None
            if data_format == "csv":
                rows = list(csv.DictReader(io.StringIO(str(content or ""))))
            elif data_format == "json":
                parsed = json.loads(content) if isinstance(content, str) else content
                rows = parsed if isinstance(parsed, list) else parsed.get("data", []) if isinstance(parsed, dict) else []
            elif data_format == "parquet":
                payload = base64.b64decode(str(content or ""), validate=True)
                count = parquet_row_count(payload)
                rows = parquet_to_rows(payload, limit=per_file_preview)
            else:
                raise ValueError("format must be csv, json or parquet")
            if not rows or not all(isinstance(row, dict) for row in rows):
                raise ValueError(f"file {index} must contain at least one object row")
            count = count if data_format == "parquet" else len(rows)
            total_rows += count
            if total_rows > maximum_rows:
                raise ValueError(f"dataset exceeds {maximum_rows} rows")
            partitions = item.get("partitions") or {}
            if not isinstance(partitions, dict) or any(field not in partitions for field in partition_by):
                raise ValueError("every file must declare values for all partitionBy fields")
            decoded.append({"format": data_format, "rows": rows, "payload": payload, "rowCount": count, "partitions": partitions})
            preview.extend(rows[:per_file_preview])
        fields = infer_fields(preview)
        dataset_id = existing_dataset_id or str(body.get("id") or f"data_{uuid.uuid4().hex[:12]}")
        name = str(body.get("name") or dataset_id)
        created_at = now_iso()
        if existing_dataset_id:
            with DB_LOCK, connect() as db:
                current = db.execute("SELECT * FROM datasets WHERE id=? AND tenant_id=?", (dataset_id, self.principal.tenant_id)).fetchone()
                parent = db.execute("SELECT schema_json FROM dataset_versions WHERE dataset_id=? AND tenant_id=? ORDER BY version DESC LIMIT 1", (dataset_id, self.principal.tenant_id)).fetchone()
            if not current:
                raise NotFoundError("dataset not found")
            name = str(body.get("name") or current["name"])
            changes = schema_diff(json_value(parent["schema_json"], []) if parent else json_value(current["schema_json"], []), fields)
            if not changes["compatible"] and not body.get("allowBreakingSchema"):
                raise ConflictError("schema evolution removes or changes existing fields", detail=changes)
        version_token = uuid.uuid4().hex[:12]
        manifest: list[dict] = []
        staged_files: list[tuple[str, bytes]] = []
        stored_bytes = 0
        for index, item in enumerate(decoded):
            payload = item["payload"]
            if payload is None:
                payload = rows_to_parquet(coerce_rows(item["rows"], fields))
            if payload is None:
                raise RuntimeError("Parquet support requires pyarrow")
            partition_path = "/".join(
                f"{re.sub(r'[^A-Za-z0-9_.-]+', '_', field)}={re.sub(r'[^A-Za-z0-9_.-]+', '_', str(item['partitions'][field]))}"
                for field in partition_by
            )
            key = f"tenants/{self.principal.tenant_id}/datasets/{dataset_id}/versions/{version_token}/"
            if partition_path:
                key += partition_path + "/"
            key += f"part-{index:05d}.parquet"
            staged_files.append((key, payload))
            stored_bytes += len(payload)
            manifest.append({"key": key, "format": "parquet", "rowCount": item["rowCount"], "byteSize": len(payload), "partitions": item["partitions"]})
        preview_rows = coerce_rows(preview, fields)
        preview_bytes = json.dumps(preview_rows, ensure_ascii=False).encode()
        reserve_storage(self.principal.tenant_id, stored_bytes + len(preview_bytes))
        for key, payload in staged_files:
            OBJECT_STORE.put_bytes(key, payload, "application/vnd.apache.parquet")
        object_key = OBJECT_STORE.put_json(
            f"tenants/{self.principal.tenant_id}/datasets/{dataset_id}/versions/{version_token}/preview.json",
            preview_rows,
        )
        if not existing_dataset_id:
            with DB_LOCK, connect() as db:
                db.execute(
                    "INSERT INTO datasets(id,name,format,schema_json,object_key,row_count,created_at,tenant_id,storage_format,columnar_key,byte_size,current_version_id,schema_version,partition_by,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (dataset_id, name, "multi" if len(raw_files) > 1 else decoded[0]["format"], "[]", object_key, 0, created_at, self.principal.tenant_id, "parquet", manifest[0]["key"], 0, None, 1, json.dumps(partition_by), created_at),
                )
        version = DatasetCatalog(connect, OBJECT_STORE).register_version(
            dataset_id,
            self.principal.tenant_id,
            fields,
            manifest,
            partition_by=partition_by,
            allow_breaking=bool(body.get("allowBreakingSchema")),
            lineage=body.get("lineage") if isinstance(body.get("lineage"), list) else None,
        )
        with DB_LOCK, connect() as db:
            db.execute("UPDATE datasets SET name=?,object_key=?,format=?,updated_at=? WHERE id=? AND tenant_id=?", (name, object_key, "multi" if len(raw_files) > 1 else decoded[0]["format"], created_at, dataset_id, self.principal.tenant_id))
        self._json({"data": {"id": dataset_id, "name": name, "format": "multi" if len(raw_files) > 1 else decoded[0]["format"], "storageFormat": "parquet", "schema": fields, "rows": preview_rows, "rowCount": total_rows, "partitionBy": partition_by, "version": version, "createdAt": created_at}}, HTTPStatus.CREATED)

    def _query_dataset(self, dataset_id: str, body: dict) -> None:
        result = analysis_service().execute(self.principal.tenant_id, body, dataset_id)
        self._json({"data": result})

    def _save_visualization_spec(self, body: dict) -> None:
        spec = body.get("spec")
        if not isinstance(spec, dict):
            raise ValueError("spec must be an object")
        spec_id = str(body.get("id") or f"viz_{uuid.uuid4().hex[:12]}")
        created_at = now_iso()
        with DB_LOCK, connect() as db:
            owner = db.execute("SELECT tenant_id FROM visualization_specs WHERE id=?", (spec_id,)).fetchone()
            if owner and owner["tenant_id"] != self.principal.tenant_id:
                raise PermissionError("visualization spec belongs to another tenant")
            current = db.execute("SELECT * FROM visualization_specs WHERE id=? AND tenant_id=?", (spec_id,self.principal.tenant_id)).fetchone()
            share_token = current["share_token"] if current else uuid.uuid4().hex[:16]
            db.execute("""INSERT INTO visualization_specs(id,name,dataset_id,spec,share_token,is_public,version,created_at,updated_at,tenant_id)
              VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,dataset_id=excluded.dataset_id,
              spec=excluded.spec,is_public=excluded.is_public,version=visualization_specs.version+1,updated_at=excluded.updated_at""",
              (spec_id, str(body.get("name") or "Untitled visualization"), body.get("datasetId"), json.dumps(spec, ensure_ascii=False), share_token, 1 if body.get("isPublic", True) else 0, 1, created_at, created_at,self.principal.tenant_id))
            row = db.execute("SELECT * FROM visualization_specs WHERE id=? AND tenant_id=?", (spec_id,self.principal.tenant_id)).fetchone()
        self._json({"data": {"id": row["id"], "name": row["name"], "datasetId": row["dataset_id"], "spec": json_value(row["spec"], {}), "shareToken": row["share_token"], "isPublic": bool(row["is_public"]), "version": row["version"], "updatedAt": row["updated_at"]}}, HTTPStatus.CREATED)

    def _scene_row(self,scene_id: str):
        with DB_LOCK,connect() as db: row=db.execute("SELECT * FROM model_scenes WHERE id=? AND tenant_id=?",(scene_id,self.principal.tenant_id)).fetchone()
        if not row: raise ValueError("model scene not found")
        return row

    def _render_model_scene(self,row,operations: list[dict]) -> dict:
        with DB_LOCK,connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(row["source_asset_id"],)).fetchone()
        if not asset: raise ValueError("source model asset not found")
        stored=OBJECT_STORE.get_json(asset["object_key"]); payload=base64.b64decode(stored["base64"],validate=True); document,binary=parse_asset(payload,asset["format"])
        if asset["format"]=="gltf" and not binary:
            uri=(document.get("buffers") or [{}])[0].get("uri")
            resource=next((item for item in stored.get("resources",[]) if item.get("name")==uri),None)
            if resource and resource.get("base64"): binary=base64.b64decode(resource["base64"],validate=True)
            if not binary and any(str(operation.get("type")) in {"modifier","csg","remesh","repair"} for operation in operations): raise ValueError("glTF mesh modifiers require an embedded buffer or an uploaded .bin resource")
        document,binary,modifier_stats=apply_asset_operations(document,binary,operations); manifest=scene_manifest(document)
        if asset["format"]=="glb":
            output=pack_glb(document,binary); quality=quality_report(output,manifest,max(50,min(100,int(os.environ.get("MODEL_SCENE_QUALITY_THRESHOLD","70")))))
        else:
            if binary:
                document.setdefault("buffers",[{"byteLength":len(binary)}]);document["buffers"][0]["byteLength"]=len(binary);document["buffers"][0]["uri"]="data:application/octet-stream;base64,"+base64.b64encode(binary).decode("ascii")
            output=json.dumps(document,separators=(",",":"),ensure_ascii=False).encode(); score=85 if manifest["meshCount"] else 20; quality={"format":"gltf","score":score,"threshold":70,"passed":score>=70,"issues":[] if score>=70 else ["no renderable meshes"],"issueNodeIds":[],"summary":{"nodes":manifest["nodeCount"],"meshes":manifest["meshCount"],"materials":manifest["materialCount"]}}
        return {"format":asset["format"],"name":asset["name"],"payload":output,"resources":stored.get("resources",[]),"manifest":manifest,"quality":quality,"modifierStats":modifier_stats}

    def _persist_model_scene_version(self,row,operations: list[dict],command: str,cancel_check=None) -> dict:
        rendered=self._render_model_scene(row,operations)
        if cancel_check and cancel_check():raise RuntimeError("model operation cancelled")
        version=int(row["version"])+1
        metadata={"source":"model-scene-release","sceneId":row["id"],"sourceAssetId":row["source_asset_id"],"operationCount":len(operations),"command":command[:500],"quality":rendered["quality"],"modifierStats":rendered["modifierStats"]}
        asset=store_model_asset(rendered["name"],rendered["format"],rendered["payload"],metadata,rendered["resources"],self.principal.tenant_id); created=now_iso(); version_id="msv_"+uuid.uuid4().hex[:12]
        with DB_LOCK,connect() as db:
            db.execute("UPDATE model_scenes SET current_asset_id=?,version=?,operations=?,scene_json=?,quality=?,updated_at=? WHERE id=?",(asset["id"],version,json.dumps(operations,ensure_ascii=False),json.dumps(rendered["manifest"],ensure_ascii=False),json.dumps(rendered["quality"],ensure_ascii=False),created,row["id"]))
            db.execute("INSERT INTO model_scene_versions(id,scene_id,version,asset_id,operations,scene_json,quality,created_at) VALUES(?,?,?,?,?,?,?,?)",(version_id,row["id"],version,asset["id"],json.dumps(operations,ensure_ascii=False),json.dumps(rendered["manifest"],ensure_ascii=False),json.dumps(rendered["quality"],ensure_ascii=False),created))
            updated=db.execute("SELECT * FROM model_scenes WHERE id=?",(row["id"],)).fetchone()
        return {**serialize_model_scene(updated,True),"asset":asset,"modifierStats":rendered["modifierStats"]}

    def _scene_agent_payload(self,run_id: str) -> dict | None:
        item=serialize_scene_agent_run(run_id)
        if item and isinstance(item.get("preview"),dict) and item["preview"].get("objectKey"):
            try:item["preview"]={**item["preview"],"asset":OBJECT_STORE.get_json(item["preview"]["objectKey"])}
            except (FileNotFoundError,KeyError):item["preview"]={**item["preview"],"unavailable":True}
        return item

    def _create_scene_agent(self,scene_id: str,body: dict) -> None:
        check_task_quota(self.principal)
        row=self._scene_row(scene_id);command=str(body.get("command") or "").strip()
        if not command or len(command)>2000:raise ValueError("command must contain 1 to 2000 characters")
        run_id="sceneagent_"+uuid.uuid4().hex[:12];created=now_iso();provider=str(body.get("provider") or "local-semantic");model=str(body.get("model") or "scene-graph-v1");max_cycles=max(1,min(4,int(body.get("maxCycles") or 2)))
        with DB_LOCK,connect() as db:db.execute("INSERT INTO scene_agent_runs(id,scene_id,command,provider,model,status,progress,stage,base_version,operations,analysis,preview,result,error,risk_level,estimated_cost,estimated_seconds,quality_cycles,max_cycles,cancel_requested,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(run_id,scene_id,command,provider,model,"queued",0,"queued",row["version"],"[]","{}",None,None,None,"low",0,0,0,max_cycles,0,created,created,self.principal.tenant_id))
        task=enqueue_task(self.principal.tenant_id,"scene-agent",run_id,{"sceneId":scene_id},f"scene-agent:{run_id}")
        submit_durable(task,self._execute_scene_agent,run_id,False);self._json({"data":self._scene_agent_payload(run_id)},HTTPStatus.ACCEPTED)

    def _scene_agent_cancelled(self,run_id: str) -> bool:
        with DB_LOCK,connect() as db:row=db.execute("SELECT cancel_requested FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
        return not row or bool(row["cancel_requested"])

    def _execute_scene_agent(self,run_id: str,confirmed: bool=False) -> None:
        acquired=SCENE_AGENT_LIMIT.acquire(timeout=10)
        if not acquired:
            with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='failed',error='scene agent concurrency timeout',updated_at=? WHERE id=?",(now_iso(),run_id))
            return
        try:
            with DB_LOCK,connect() as db:run=db.execute("SELECT * FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
            if not run or run["cancel_requested"]:return
            scene=self._scene_row(run["scene_id"]);manifest=json_value(scene["scene_json"],{})
            understanding=understand_scene(manifest);record_decision(run_id,"understanding","accept","scene graph roles and topology summarized",understanding)
            with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='understanding',progress=18,stage='structure-understanding',analysis=?,updated_at=? WHERE id=?",(json.dumps({"understanding":understanding},ensure_ascii=False),now_iso(),run_id))
            if self._scene_agent_cancelled(run_id):raise RuntimeError("cancelled")
            planned=interpret_asset_command(run["command"],manifest);operations=planned["operations"];record_decision(run_id,"planning","accept",planned.get("explanation","semantic operations planned"),{"operations":operations,"affectedNodeIds":planned.get("affectedNodeIds",[])})
            risk=assess_operations(operations,understanding,manifest);analysis={"understanding":understanding,"plan":{"explanation":planned.get("explanation"),"affectedNodeIds":planned.get("affectedNodeIds",[])},"risk":risk};record_decision(run_id,"risk","confirm-required" if risk["requiresConfirmation"] else "continue",f"risk {risk['level']} · score {risk['score']}",risk)
            status="awaiting-confirmation" if risk["requiresConfirmation"] and not confirmed else "planning"
            with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status=?,progress=?,stage=?,operations=?,analysis=?,risk_level=?,estimated_cost=?,estimated_seconds=?,updated_at=? WHERE id=?",(status,35,"risk-gate" if status=="awaiting-confirmation" else "previewing",json.dumps(operations,ensure_ascii=False),json.dumps(analysis,ensure_ascii=False),risk["level"],risk["estimatedCost"],risk["estimatedSeconds"],now_iso(),run_id))
            if status=="awaiting-confirmation":return
            cycles=0;targets=planned.get("affectedNodeIds",[]) or [node.get("id") for node in manifest.get("nodes",[]) if node.get("meshIndex") is not None]
            while cycles<int(run["max_cycles"]):
                if self._scene_agent_cancelled(run_id):raise RuntimeError("cancelled")
                cycles+=1
                with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='previewing',progress=?,stage=?,quality_cycles=?,updated_at=? WHERE id=?",(45+cycles*15,f"preview-cycle-{cycles}",cycles,now_iso(),run_id))
                rendered=self._render_model_scene(scene,operations);stored={"name":rendered["name"],"format":rendered["format"],"base64":base64.b64encode(rendered["payload"]).decode("ascii"),"resources":rendered["resources"]};key=OBJECT_STORE.put_json(f"studio/scene-agents/{run_id}/preview-{cycles}.json",stored)
                accepted=quality_accepts(rendered["quality"],json_value(scene["quality"],{}));preview={"objectKey":key,"quality":rendered["quality"],"scene":rendered["manifest"],"cycle":cycles,"modifierStats":rendered["modifierStats"]};record_decision(run_id,"quality","accept" if accepted else "return-to-repair",f"quality score {rendered['quality'].get('score')} · {'absolute or non-regression gate passed' if accepted else 'regression detected'}",{"cycle":cycles,"quality":rendered["quality"],"baseline":json_value(scene["quality"],{}),"artifactKey":key})
                with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET preview=?,progress=?,stage='quality-check',updated_at=? WHERE id=?",(json.dumps(preview,ensure_ascii=False),70+cycles*8,now_iso(),run_id))
                if accepted:
                    result={"operations":operations,"quality":rendered["quality"],"scene":rendered["manifest"],"affectedNodeIds":targets}
                    with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='ready',progress=100,stage='ready-to-apply',operations=?,result=?,updated_at=? WHERE id=?",(json.dumps(operations,ensure_ascii=False),json.dumps(result,ensure_ascii=False),now_iso(),run_id))
                    return
                repair={"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"normal-repair","fillHoles":True,"removeFragments":True},"enabled":True};operations=operations+[repair]
            with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='failed',stage='quality-rejected',error='Quality Agent rejected all repair cycles; source scene is unchanged',updated_at=? WHERE id=?",(now_iso(),run_id))
        except Exception as error:
            state="cancelled" if "cancelled" in str(error).lower() else "failed"
            with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",(state,state,str(error)[:2000],now_iso(),run_id))
        finally:SCENE_AGENT_LIMIT.release()

    def _confirm_scene_agent(self,run_id: str) -> None:
        with DB_LOCK,connect() as db:row=db.execute("SELECT status FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
        if not row:return self._json({"error":"scene agent run not found"},HTTPStatus.NOT_FOUND)
        if row["status"]!="awaiting-confirmation":raise ValueError("scene agent is not awaiting confirmation")
        with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='planning',progress=36,stage='confirmed-queued',updated_at=? WHERE id=?",(now_iso(),run_id))
        EXECUTOR.submit(self._execute_scene_agent,run_id,True);self._json({"data":self._scene_agent_payload(run_id)},HTTPStatus.ACCEPTED)

    def _apply_scene_agent(self,run_id: str) -> None:
        with DB_LOCK,connect() as db:run=db.execute("SELECT * FROM scene_agent_runs WHERE id=?",(run_id,)).fetchone()
        if not run:return self._json({"error":"scene agent run not found"},HTTPStatus.NOT_FOUND)
        if run["status"]!="ready":raise ValueError("scene agent must pass quality before apply")
        scene=self._scene_row(run["scene_id"])
        if int(scene["version"])!=int(run["base_version"]):
            with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='stale',stage='version-conflict',error='scene changed after Agent preview; re-run planning',updated_at=? WHERE id=?",(now_iso(),run_id))
            return self._json({"error":"scene changed after Agent preview; re-run planning"},HTTPStatus.CONFLICT)
        with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='applying',stage='atomic-apply',updated_at=? WHERE id=?",(now_iso(),run_id))
        operations=json_value(run["operations"],[]);result=self._persist_model_scene_version(scene,json_value(scene["operations"],[])+operations,run["command"])
        record_decision(run_id,"apply","commit","quality-approved operations committed atomically",{"sceneVersion":result["version"],"assetId":result["currentAssetId"]})
        with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status='completed',progress=100,stage='completed',result=?,updated_at=? WHERE id=?",(json.dumps(result,ensure_ascii=False),now_iso(),run_id))
        self._json({"data":self._scene_agent_payload(run_id)},HTTPStatus.CREATED)

    def _stop_scene_agent(self,run_id: str,action: str) -> None:
        status="rejected" if action=="reject" else "cancelled";created=now_iso()
        with DB_LOCK,connect() as db:db.execute("UPDATE scene_agent_runs SET status=?,stage=?,cancel_requested=1,updated_at=? WHERE id=?",(status,status,created,run_id))
        record_decision(run_id,"user",status,"user kept the source scene unchanged",{});self._json({"data":self._scene_agent_payload(run_id)})

    def _preview_professional_operation(self,operation: dict) -> dict | None:
        kind=str(operation.get("kind") or "");targets=operation.get("targetIds") if isinstance(operation.get("targetIds"),list) else []
        mapping={"exact-boolean":("boolean",{"operator":operation.get("operator","union"),"resolution":20}),"fillet":("bevel",{"amount":operation.get("radius",.01)}),"chamfer":("chamfer",{"amount":operation.get("amount",.01)}),"retopology":("remesh",{"targetFaces":operation.get("targetFaces",5000)}),"repair":("normal-repair",{}),"uv-unwrap":("normal-repair",{})}
        if kind not in mapping:return None
        modifier,payload=mapping[kind];return {"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":modifier,**payload},"enabled":True}

    def _create_geometry_job(self,scene_id: str|None,asset_id: str|None,body: dict) -> None:
        check_task_quota(self.principal)
        provider=str(body.get("provider") or "builtin-voxel");catalog={item["id"]:item for item in geometry_provider_catalog()}
        if provider not in catalog:raise ValueError("unsupported geometry provider")
        if provider!="builtin-voxel" and not catalog[provider]["configured"]:raise ValueError(f"geometry provider {provider} is not configured")
        scene=self._scene_row(scene_id) if scene_id else None;source_asset_id=str(asset_id or scene["current_asset_id"]);operation=body.get("operation") if isinstance(body.get("operation"),dict) else {"kind":"convert","outputFormat":body.get("outputFormat","glb")}
        job_id="geometry_"+uuid.uuid4().hex[:12];created=now_iso();priority=max(0,min(100,int(body.get("priority") or 50)));timeout=max(30,min(7200,int(body.get("timeoutSeconds") or 900)))
        with DB_LOCK,connect() as db:
            if not db.execute("SELECT id FROM model_assets WHERE id=?",(source_asset_id,)).fetchone():return self._json({"error":"source model asset not found"},HTTPStatus.NOT_FOUND)
            db.execute("INSERT INTO geometry_jobs(id,scene_id,source_asset_id,provider,operation,status,progress,stage,priority,preview_asset_id,result_asset_id,checkpoint_key,result,error,cancel_requested,timeout_seconds,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,scene_id,source_asset_id,provider,json.dumps(operation,ensure_ascii=False),"queued",0,"queued",priority,None,None,body.get("checkpointKey"),None,None,0,timeout,created,created,self.principal.tenant_id))
        task=enqueue_task(self.principal.tenant_id,"geometry",job_id,{"provider":provider},f"geometry:{job_id}",priority=priority)
        submit_durable(task,self._execute_geometry_job,job_id);self._json({"data":self._geometry_job(job_id)},HTTPStatus.ACCEPTED)

    def _geometry_job(self,job_id: str) -> dict|None:
        with DB_LOCK,connect() as db:row=db.execute("SELECT * FROM geometry_jobs WHERE id=?",(job_id,)).fetchone()
        return serialize_geometry_job(row)

    def _geometry_cancelled(self,job_id: str) -> bool:
        with DB_LOCK,connect() as db:row=db.execute("SELECT cancel_requested FROM geometry_jobs WHERE id=?",(job_id,)).fetchone()
        return not row or bool(row["cancel_requested"])

    def _execute_geometry_job(self,job_id: str) -> None:
        if not GEOMETRY_LIMIT.acquire(timeout=30):
            with DB_LOCK,connect() as db:db.execute("UPDATE geometry_jobs SET status='failed',error='geometry concurrency timeout',updated_at=? WHERE id=?",(now_iso(),job_id))
            return
        try:
            with DB_LOCK,connect() as db:
                job=db.execute("SELECT * FROM geometry_jobs WHERE id=?",(job_id,)).fetchone();asset=db.execute("SELECT * FROM model_assets WHERE id=?",(job["source_asset_id"],)).fetchone() if job else None
            if not job or not asset or job["cancel_requested"]:return
            operation=json_value(job["operation"],{});scene=self._scene_row(job["scene_id"]) if job["scene_id"] else None
            with DB_LOCK,connect() as db:db.execute("UPDATE geometry_jobs SET status='previewing',progress=5,stage='low-resolution-preview',updated_at=? WHERE id=?",(now_iso(),job_id))
            preview_operation=self._preview_professional_operation(operation)
            if scene and preview_operation:
                preview_rendered=self._render_model_scene(scene,json_value(scene["operations"],[])+[preview_operation]);preview_asset=store_model_asset("preview-"+preview_rendered["name"],preview_rendered["format"],preview_rendered["payload"],{"source":"geometry-low-resolution-preview","geometryJobId":job_id,"assetStage":"preview"},preview_rendered["resources"],self.principal.tenant_id)
                with DB_LOCK,connect() as db:db.execute("UPDATE geometry_jobs SET preview_asset_id=?,progress=20,updated_at=? WHERE id=?",(preview_asset["id"],now_iso(),job_id))
            if job["provider"]=="builtin-voxel":
                if not scene or not preview_operation:raise ValueError("builtin geometry provider requires an editable scene operation")
                result=self._persist_model_scene_version(scene,json_value(scene["operations"],[])+[preview_operation],f"geometry worker: {operation.get('kind')}",lambda:self._geometry_cancelled(job_id));asset_id=result["currentAssetId"]
                with DB_LOCK,connect() as db:db.execute("UPDATE geometry_jobs SET status='completed',progress=100,stage='completed',result_asset_id=?,result=?,updated_at=? WHERE id=?",(asset_id,json.dumps(result,ensure_ascii=False),now_iso(),job_id))
                return
            stored=OBJECT_STORE.get_json(asset["object_key"]);request={"jobId":job_id,"operation":operation,"source":{"name":asset["name"],"format":asset["format"],"content":stored["base64"],"resources":stored.get("resources",[])},"outputFormat":operation.get("outputFormat","glb"),"checkpointKey":job["checkpoint_key"]}
            def progress(value,stage,checkpoint=None):
                key=None
                if checkpoint:key=OBJECT_STORE.put_json(f"geometry/{job_id}/checkpoint-{max(0,min(100,value))}.json",checkpoint)
                with DB_LOCK,connect() as db:db.execute("UPDATE geometry_jobs SET status='provider-running',progress=?,stage=?,checkpoint_key=COALESCE(?,checkpoint_key),updated_at=? WHERE id=?",(max(20,min(94,value)),stage[:120],key,now_iso(),job_id))
            result=run_geometry_provider(job["provider"],request,int(job["timeout_seconds"]),progress,lambda:self._geometry_cancelled(job_id))
            if self._geometry_cancelled(job_id):raise RuntimeError("cancelled")
            output=result.content;output_format=result.format
            if scene and output_format in {"obj","stl","ply"}:
                document,binary=canonicalize_mesh_asset(output,output_format,asset["name"]);output=pack_glb(document,binary);output_format="glb"
            scene_result=None;manifest=None;quality=None
            if scene:
                document,binary=parse_asset(output,output_format);manifest=scene_manifest(document);quality=quality_report(output,manifest,70) if output_format=="glb" else {"format":output_format,"score":85,"threshold":70,"passed":True,"issues":[],"issueNodeIds":[],"summary":{"nodes":manifest["nodeCount"],"meshes":manifest["meshCount"],"materials":manifest["materialCount"]}}
                if not quality_accepts(quality,json_value(scene["quality"],{})):
                    raise RuntimeError(f"professional geometry quality gate rejected output: {quality.get('issues') or 'invalid mesh'}; source scene is unchanged")
            final=store_model_asset(re.sub(r"\.(step|stp|iges|igs|ply|obj|stl|gltf|glb)$",f".{output_format}",asset["name"],flags=re.I),output_format,output,{"source":"professional-geometry-worker","geometryJobId":job_id,"provider":job["provider"],"operation":operation,"stats":result.stats,"assetStage":"release"},tenant_id=self.principal.tenant_id)
            if scene:
                version=int(scene["version"])+1;operations=json_value(scene["operations"],[])+[{"id":"professional_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":operation.get("targetIds",[]),"payload":{**operation,"provider":job["provider"],"kernel":"professional"},"enabled":True}];created=now_iso()
                with DB_LOCK,connect() as db:
                    db.execute("UPDATE model_scenes SET current_asset_id=?,version=?,operations=?,scene_json=?,quality=?,updated_at=? WHERE id=?",(final["id"],version,json.dumps(operations,ensure_ascii=False),json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created,scene["id"]));db.execute("INSERT INTO model_scene_versions(id,scene_id,version,asset_id,operations,scene_json,quality,created_at) VALUES(?,?,?,?,?,?,?,?)",("msv_"+uuid.uuid4().hex[:12],scene["id"],version,final["id"],json.dumps(operations,ensure_ascii=False),json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created));updated=db.execute("SELECT * FROM model_scenes WHERE id=?",(scene["id"],)).fetchone()
                scene_result=serialize_model_scene(updated,True)
            payload={"asset":final,"scene":scene_result,"stats":result.stats}
            with DB_LOCK,connect() as db:db.execute("UPDATE geometry_jobs SET status='completed',progress=100,stage='high-quality-replaced',result_asset_id=?,result=?,updated_at=? WHERE id=?",(final["id"],json.dumps(payload,ensure_ascii=False),now_iso(),job_id))
        except Exception as error:
            state="cancelled" if "cancelled" in str(error).lower() else "failed"
            with DB_LOCK,connect() as db:db.execute("UPDATE geometry_jobs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",(state,state,str(error)[:2000],now_iso(),job_id))
        finally:GEOMETRY_LIMIT.release()

    def _cancel_geometry_job(self,job_id: str) -> None:
        with DB_LOCK,connect() as db:
            row=db.execute("SELECT status FROM geometry_jobs WHERE id=?",(job_id,)).fetchone()
            if not row:return self._json({"error":"geometry job not found"},HTTPStatus.NOT_FOUND)
            status="cancelled" if row["status"]=="queued" else row["status"];db.execute("UPDATE geometry_jobs SET cancel_requested=1,status=?,stage='cancel-requested',updated_at=? WHERE id=?",(status,now_iso(),job_id))
        self._json({"data":self._geometry_job(job_id)},HTTPStatus.ACCEPTED)

    def _queue_model_operations(self,scene_id: str,body: dict) -> None:
        check_task_quota(self.principal)
        row=self._scene_row(scene_id);additions=body.get("operations") if isinstance(body.get("operations"),list) else []
        if not additions or len(additions)>50:raise ValueError("operations must contain 1 to 50 items")
        operations=json_value(row["operations"],[])+additions
        if len(operations)>500:raise ValueError("scene operation stack exceeds 500 items")
        job_id="meshjob_"+uuid.uuid4().hex[:12];created=now_iso();payload={"operations":operations,"command":str(body.get("command") or "background mesh operation")}
        with DB_LOCK,connect() as db:db.execute("INSERT INTO model_operation_jobs(id,scene_id,status,progress,stage,operations,result,error,cancel_requested,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(job_id,scene_id,"queued",0,"queued",json.dumps(payload,ensure_ascii=False),None,None,0,created,created,self.principal.tenant_id))
        task=enqueue_task(self.principal.tenant_id,"model-operation",job_id,payload,f"model-operation:{job_id}")
        submit_durable(task,self._execute_model_operation,job_id);self._json({"data":{"id":job_id,"sceneId":scene_id,"status":"queued","progress":0,"stage":"queued","operations":additions,"cancelRequested":False,"createdAt":created,"updatedAt":created}},HTTPStatus.ACCEPTED)

    def _execute_model_operation(self,job_id: str) -> None:
        try:
            with DB_LOCK,connect() as db:
                job=db.execute("SELECT * FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
                if not job or job["cancel_requested"]:return
                db.execute("UPDATE model_operation_jobs SET status='running',progress=20,stage='voxelizing / topology',updated_at=? WHERE id=?",(now_iso(),job_id))
            payload=json_value(job["operations"],{});row=self._scene_row(job["scene_id"])
            def cancelled():
                with DB_LOCK,connect() as db:item=db.execute("SELECT cancel_requested FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
                return not item or bool(item["cancel_requested"])
            result=self._persist_model_scene_version(row,payload.get("operations",[]),str(payload.get("command") or "background mesh operation"),cancelled)
            with DB_LOCK,connect() as db:db.execute("UPDATE model_operation_jobs SET status='completed',progress=100,stage='completed',result=?,updated_at=? WHERE id=?",(json.dumps(result,ensure_ascii=False),now_iso(),job_id))
        except Exception as error:
            cancelled_state="cancelled" if "cancelled" in str(error).lower() else "failed"
            with DB_LOCK,connect() as db:db.execute("UPDATE model_operation_jobs SET status=?,stage=?,error=?,updated_at=? WHERE id=?",(cancelled_state,cancelled_state,str(error)[:1000],now_iso(),job_id))

    def _cancel_model_operation(self,job_id: str) -> None:
        with DB_LOCK,connect() as db:
            row=db.execute("SELECT * FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
            if not row:return self._json({"error":"model operation job not found"},HTTPStatus.NOT_FOUND)
            status="cancelled" if row["status"]=="queued" else row["status"];db.execute("UPDATE model_operation_jobs SET cancel_requested=1,status=?,stage=?,updated_at=? WHERE id=?",(status,"cancel requested" if status=="running" else status,now_iso(),job_id));updated=db.execute("SELECT * FROM model_operation_jobs WHERE id=?",(job_id,)).fetchone()
        self._json({"data":serialize_model_operation_job(updated)},HTTPStatus.ACCEPTED)

    def _import_model_scene(self,asset_id: str,body: dict) -> None:
        with DB_LOCK,connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(asset_id,)).fetchone()
        if not asset: return self._json({"error":"model asset not found"},HTTPStatus.NOT_FOUND)
        stored=OBJECT_STORE.get_json(asset["object_key"]); payload=base64.b64decode(stored["base64"],validate=True)
        if asset["format"] in {"obj","stl","ply"}:
            document,binary=canonicalize_mesh_asset(payload,asset["format"],asset["name"]);canonical_payload=pack_glb(document,binary);stem=re.sub(r"\.(obj|stl|ply)$","",asset["name"],flags=re.I)
            canonical=store_model_asset(f"{stem}.glb","glb",canonical_payload,{"source":"canonical-editable-import","originalAssetId":asset_id,"originalFormat":asset["format"],"assetStage":"raw-canonical"},tenant_id=self.principal.tenant_id);asset_id=canonical["id"]
            with DB_LOCK,connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(asset_id,)).fetchone()
            stored=OBJECT_STORE.get_json(asset["object_key"]);payload=canonical_payload
        elif asset["format"] in {"step","iges","brep"}:raise ValueError("STEP/IGES/B-Rep must be tessellated by a configured OpenCascade or external geometry provider before scene import")
        else:document,_=parse_asset(payload,asset["format"])
        manifest=scene_manifest(document)
        quality=quality_report(payload,manifest,70) if asset["format"]=="glb" else {"format":"gltf","score":85 if manifest["meshCount"] else 20,"threshold":70,"passed":bool(manifest["meshCount"]),"issues":[],"issueNodeIds":[],"summary":{"nodes":manifest["nodeCount"],"meshes":manifest["meshCount"],"materials":manifest["materialCount"]}}
        scene_id="modelscene_"+uuid.uuid4().hex[:12]; name=str(body.get("name") or asset["name"]); created=now_iso(); operations=[]; version_id="msv_"+uuid.uuid4().hex[:12]
        with DB_LOCK,connect() as db:
            db.execute("INSERT INTO model_scenes(id,name,source_asset_id,current_asset_id,version,operations,scene_json,quality,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(scene_id,name,asset_id,asset_id,1,"[]",json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created,created,self.principal.tenant_id))
            db.execute("INSERT INTO model_scene_versions(id,scene_id,version,asset_id,operations,scene_json,quality,created_at) VALUES(?,?,?,?,?,?,?,?)",(version_id,scene_id,1,asset_id,"[]",json.dumps(manifest,ensure_ascii=False),json.dumps(quality,ensure_ascii=False),created))
            row=db.execute("SELECT * FROM model_scenes WHERE id=?",(scene_id,)).fetchone()
        self._json({"data":serialize_model_scene(row,True)},HTTPStatus.CREATED)

    def _model_scene_command(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); manifest=json_value(row["scene_json"],{}); result=interpret_asset_command(str(body.get("command") or ""),manifest); self._json({"data":result},HTTPStatus.CREATED)

    def _preview_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); additions=body.get("operations") if isinstance(body.get("operations"),list) else []; operations=json_value(row["operations"],[])+additions
        rendered=self._render_model_scene(row,operations); self._json({"data":{"sceneId":scene_id,"operations":operations,"scene":rendered["manifest"],"quality":rendered["quality"],"modifierStats":rendered["modifierStats"],"asset":{"name":rendered["name"],"format":rendered["format"],"base64":base64.b64encode(rendered["payload"]).decode("ascii"),"resources":rendered["resources"]}}})

    def _apply_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); additions=body.get("operations") if isinstance(body.get("operations"),list) else []
        limit=500 if body.get("replace") else 50
        if (not additions and not body.get("replace")) or len(additions)>limit: raise ValueError(f"operations must contain {'0' if body.get('replace') else '1'} to {limit} items")
        existing=[] if body.get("replace") else json_value(row["operations"],[])
        if len(existing)+len(additions)>500: raise ValueError("scene operation stack exceeds 500 items")
        locked={node["id"] for node in json_value(row["scene_json"],{}).get("nodes",[]) if node.get("locked")}
        if any(locked.intersection(operation.get("targetIds",[])) and operation.get("type")!="lock" for operation in additions): raise ValueError("one or more target nodes are locked")
        result=self._persist_model_scene_version(row,existing+additions,str(body.get("command") or "manual edit")); self._json({"data":result},HTTPStatus.CREATED)

    def _restore_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); requested=int(body.get("version") or 0)
        with DB_LOCK,connect() as db: version=db.execute("SELECT operations FROM model_scene_versions WHERE scene_id=? AND version=?",(scene_id,requested)).fetchone()
        if not version: return self._json({"error":"model scene version not found"},HTTPStatus.NOT_FOUND)
        result=self._persist_model_scene_version(row,json_value(version["operations"],[]),f"restore version {requested}"); self._json({"data":result},HTTPStatus.CREATED)

    def _repair_model_scene(self,scene_id: str,body: dict) -> None:
        row=self._scene_row(scene_id); manifest=json_value(row["scene_json"],{}); targets=[node["id"] for node in manifest.get("nodes",[]) if node.get("meshIndex") is not None]
        operations=[{"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"normal-repair"},"enabled":True}]
        if body.get("decimate"):
            operations.append({"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"decimate","targetFaces":max(100,int(body.get("targetFaces") or 50000))},"enabled":True})
        base_operations=json_value(row["operations"],[])+operations; result=self._persist_model_scene_version(row,base_operations,"automatic mesh repair"); total_faces=sum(int(node.get("faceCount") or 0) for node in manifest.get("nodes",[]));lod_assets=[]
        for level,ratio in ((1,.5),(2,.25)):
            target=max(100,int(total_faces*ratio));lod_operation={"id":"op_"+uuid.uuid4().hex[:10],"type":"modifier","targetIds":targets,"payload":{"kind":"decimate","targetFaces":target},"enabled":True};rendered=self._render_model_scene(row,base_operations+[lod_operation]);stem=re.sub(r"\.(glb|gltf)$","",rendered["name"],flags=re.I);lod_assets.append(store_model_asset(f"{stem}.lod{level}.{rendered['format']}",rendered["format"],rendered["payload"],{"source":"model-scene-lod","sceneId":scene_id,"lod":level,"targetFaces":target,"quality":rendered["quality"]},rendered["resources"],self.principal.tenant_id))
        result["lodAssets"]=lod_assets;self._json({"data":result},HTTPStatus.CREATED)

    def _export_model_scene(self,scene_id: str) -> None:
        row=self._scene_row(scene_id)
        with DB_LOCK,connect() as db: asset=db.execute("SELECT * FROM model_assets WHERE id=?",(row["current_asset_id"],)).fetchone()
        stored=OBJECT_STORE.get_json(asset["object_key"]); self._json({"data":{"id":asset["id"],"name":asset["name"],"format":asset["format"],"version":asset["version"],"parentId":asset["parent_id"],"metadata":json_value(asset["metadata"],{}),"content":stored,"createdAt":asset["created_at"]}})

    def _run_timeline(self, run_id: str) -> None:
        with DB_LOCK, connect() as db:
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
            step = int(link["link_step"] or 0); frames.setdefault(step, {"step": step, "metrics": {}, "artifacts": [], "assets": []})["assets"].append({"linkId": link["link_id"], "role": link["link_role"], "sceneId": link["link_scene_id"], "metadata": json_value(link["link_metadata"], {}), "asset": serialize_model_asset(link)})
        return self._json({"data": {"runId": run_id, "frames": [frames[key] for key in sorted(frames)], "maxStep": max(frames.keys(), default=0)}})

    def _create_asset_project(self, body: dict) -> None:
        name = str(body.get("name") or "").strip()
        if not name or len(name) > 120: raise ValueError("project name must contain 1 to 120 characters")
        project_id = f"project_{uuid.uuid4().hex[:12]}"; created = now_iso()
        with DB_LOCK, connect() as db:
            db.execute("INSERT INTO asset_projects(id,name,description,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?)", (project_id, name, str(body.get("description") or "")[:1000], created, created,self.principal.tenant_id))
        self._json({"data": {"id": project_id, "name": name, "description": str(body.get("description") or "")[:1000], "assetCount": 0, "createdAt": created, "updatedAt": created}}, HTTPStatus.CREATED)

    def _link_run_asset(self, run_id: str, body: dict) -> None:
        asset_id = str(body.get("assetId") or ""); role = str(body.get("role") or "checkpoint")
        if role not in {"input", "checkpoint", "output", "baseline", "overlay", "simulation"}: raise ValueError("unsupported asset role")
        link_id = f"link_{uuid.uuid4().hex[:12]}"; created = now_iso(); step = body.get("step")
        with DB_LOCK, connect() as db:
            if not db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone(): return self._json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
            if not db.execute("SELECT id FROM model_assets WHERE id=? AND deleted_at IS NULL", (asset_id,)).fetchone(): return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
            db.execute("INSERT INTO run_asset_links(id,run_id,asset_id,scene_id,role,step,metadata,created_at) VALUES(?,?,?,?,?,?,?,?)", (link_id, run_id, asset_id, body.get("sceneId"), role, int(step) if step is not None else None, json.dumps(body.get("metadata") if isinstance(body.get("metadata"), dict) else {}, ensure_ascii=False), created))
        bump(run_id); self._json({"data": {"id": link_id, "runId": run_id, "assetId": asset_id, "role": role, "step": step, "createdAt": created}}, HTTPStatus.CREATED)

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
            thumbnail={"base64":str(body["thumbnailBase64"])};reserve_storage(self.principal.tenant_id,len(json.dumps(thumbnail).encode()));key = OBJECT_STORE.put_json(f"tenants/{self.principal.tenant_id}/models/{asset_id}.thumbnail.json",thumbnail)
            updates.append("thumbnail_key=?"); values.append(key)
        updates.append("updated_at=?"); values.append(now_iso()); values.append(asset_id)
        with DB_LOCK, connect() as db:
            db.execute(f"UPDATE model_assets SET {','.join(updates)} WHERE id=? AND deleted_at IS NULL", values)
            row = db.execute("SELECT * FROM model_assets WHERE id=?", (asset_id,)).fetchone()
        if not row: return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        self._json({"data": serialize_model_asset(row, False, True)})

    def _batch_update_assets(self, body: dict) -> None:
        ids = [str(item) for item in body.get("ids", []) if item]; patch = body.get("patch") if isinstance(body.get("patch"), dict) else {}
        if not ids or len(ids) > 200: raise ValueError("ids must contain 1 to 200 assets")
        updated = []
        for asset_id in ids:
            if not self._owned("model_assets",asset_id): continue
            fields = {key: value for key, value in patch.items() if key in {"projectId", "folder", "stage", "tags"}}
            if body.get("renamePrefix"):
                with DB_LOCK, connect() as db: row = db.execute("SELECT name FROM model_assets WHERE id=?", (asset_id,)).fetchone()
                if row: fields["name"] = f"{str(body['renamePrefix'])}{row['name']}"
            if fields:
                mapping = {"name": "name", "projectId": "project_id", "folder": "folder", "stage": "stage", "tags": "tags"}; assignments=[]; values=[]
                for key, value in fields.items(): assignments.append(f"{mapping[key]}=?"); values.append(json.dumps(value, ensure_ascii=False) if key == "tags" else value)
                assignments.append("updated_at=?"); values.extend([now_iso(), asset_id])
                with DB_LOCK, connect() as db: db.execute(f"UPDATE model_assets SET {','.join(assignments)} WHERE id=? AND deleted_at IS NULL", values)
                updated.append(asset_id)
        self._json({"data": {"updated": updated, "count": len(updated)}})

    def _set_asset_archive(self, asset_id: str, archive: bool) -> None:
        timestamp = now_iso()
        with DB_LOCK, connect() as db:
            db.execute("UPDATE model_assets SET archived_at=?,updated_at=? WHERE id=? AND deleted_at IS NULL", (timestamp if archive else None, timestamp, asset_id)); row = db.execute("SELECT * FROM model_assets WHERE id=?", (asset_id,)).fetchone()
        return self._json({"data": serialize_model_asset(row) if row else None}, HTTPStatus.OK if row else HTTPStatus.NOT_FOUND)

    def _delete_model_asset(self, asset_id: str, purge: bool) -> None:
        with DB_LOCK:
            return self._delete_model_asset_locked(asset_id, purge)

    def _delete_model_asset_locked(self, asset_id: str, purge: bool) -> None:
        references = model_asset_references(asset_id)
        if references: return self._json({"error": "asset is still referenced", "references": references}, HTTPStatus.CONFLICT)
        with DB_LOCK, connect() as db: row = db.execute("SELECT * FROM model_assets WHERE id=?", (asset_id,)).fetchone()
        if not row: return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        if not purge:
            timestamp = now_iso()
            with DB_LOCK, connect() as db: db.execute("UPDATE model_assets SET deleted_at=?,updated_at=? WHERE id=?", (timestamp, timestamp, asset_id))
            return self._json({"data": {"id": asset_id, "deletedAt": timestamp}})
        OBJECT_STORE.delete(row["object_key"])
        with DB_LOCK, connect() as db: db.execute("DELETE FROM model_assets WHERE id=?", (asset_id,))
        return self._json({"data": {"id": asset_id, "purged": True}})

    def _garbage_collect_assets(self, body: dict) -> None:
        with DB_LOCK:
            return self._garbage_collect_assets_locked(body)

    def _garbage_collect_assets_locked(self, body: dict) -> None:
        grace_hours = max(0, int(body.get("graceHours", 168))); cutoff = time.time() - grace_hours * 3600; purged=[]; protected=[]
        with DB_LOCK, connect() as db: rows = db.execute("SELECT * FROM model_assets WHERE deleted_at IS NOT NULL AND tenant_id=?",(self.principal.tenant_id,)).fetchall()
        for row in rows:
            try: deleted = datetime.fromisoformat(row["deleted_at"].replace("Z", "+00:00")).timestamp()
            except ValueError: deleted = 0
            refs = model_asset_references(row["id"])
            if refs or deleted > cutoff: protected.append(row["id"]); continue
            OBJECT_STORE.delete(row["object_key"])
            with DB_LOCK, connect() as db: db.execute("DELETE FROM model_assets WHERE id=?", (row["id"],))
            purged.append(row["id"])
        self._json({"data": {"purged": purged, "protected": protected, "graceHours": grace_hours}})

    def _create_asset_component(self, asset_id: str, body: dict) -> None:
        kind = str(body.get("type") or "")
        if kind not in {"mesh", "material", "texture"}: raise ValueError("component type must be mesh, material or texture")
        content = body.get("content"); component_id = f"component_{uuid.uuid4().hex[:12]}"; created = now_iso()
        with DB_LOCK, connect() as db:
            if not db.execute("SELECT id FROM model_assets WHERE id=?", (asset_id,)).fetchone(): return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
            latest = db.execute("SELECT MAX(version) AS version FROM asset_components WHERE asset_id=? AND component_type=?", (asset_id, kind)).fetchone(); version = int(latest["version"] or 0) + 1
        reserve_storage(self.principal.tenant_id,len(json.dumps(content,ensure_ascii=False).encode()));key = OBJECT_STORE.put_json(f"tenants/{self.principal.tenant_id}/models/{asset_id}/components/{component_id}.json", content)
        with DB_LOCK, connect() as db: db.execute("INSERT INTO asset_components(id,asset_id,component_type,version,object_key,metadata,created_at) VALUES(?,?,?,?,?,?,?)", (component_id, asset_id, kind, version, key, json.dumps(body.get("metadata") if isinstance(body.get("metadata"), dict) else {}, ensure_ascii=False), created))
        self._json({"data": {"id": component_id, "assetId": asset_id, "type": kind, "version": version, "createdAt": created}}, HTTPStatus.CREATED)

    def _create_asset_release(self, asset_id: str, body: dict) -> None:
        status = str(body.get("status") or "pending")
        if status not in {"pending", "approved", "rejected"}: raise ValueError("invalid release status")
        release_id = f"release_{uuid.uuid4().hex[:12]}"; created = now_iso()
        reviewer = self.principal.user_id if status != "pending" else ""
        note = str(body.get("note") or "")[:1000]
        with DB_LOCK, connect() as db:
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
        asset=store_model_asset(str(body.get("name") or f"model.{asset_format}"),asset_format,base64.b64decode(content,validate=True),body.get("metadata") if isinstance(body.get("metadata"),dict) else {},resources,self.principal.tenant_id)
        self._json({"data":asset},HTTPStatus.CREATED)

    def _save_three_telemetry(self, body: dict) -> None:
        label = str(body.get("label") or "3d-view")[:100]
        session_id = str(body.get("sessionId") or "")[:100]
        if not session_id:
            raise ValueError("sessionId is required")
        asset_id = str(body.get("assetId") or "") or None
        if asset_id and not self._owned("model_assets", asset_id):
            return self._json({"error": "model asset not found"}, HTTPStatus.NOT_FOUND)
        number = lambda name, default=0: float(body.get(name) if body.get(name) is not None else default)
        item_id = "three_" + uuid.uuid4().hex[:12]; created = now_iso(); enriched={**body,"nativeGpu":native_gpu_telemetry()}
        with DB_LOCK, connect() as db:
            db.execute("""INSERT INTO three_telemetry(id,tenant_id,asset_id,label,session_id,frames,average_frame_ms,max_frame_ms,gpu_frame_ms,gpu_vendor,gpu_renderer,webgl_version,geometries,textures,draw_calls,triangles,heap_bytes,transferred_bytes,context_losses,payload,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (item_id, self.principal.tenant_id, asset_id, label, session_id, int(number("frames")), number("averageFrameMs"), number("maxFrameMs"), number("gpuFrameMs") if body.get("gpuFrameMs") is not None else None,
               str(body.get("gpuVendor") or "")[:300], str(body.get("gpuRenderer") or "")[:300], str(body.get("webglVersion") or "")[:100], int(number("geometries")), int(number("textures")), int(number("drawCalls")), int(number("triangles")), int(number("heapBytes")), int(number("transferredBytes")), int(number("contextLosses")), json.dumps(enriched, ensure_ascii=False), created))
        self._json({"data": {"id": item_id, "nativeGpu":enriched["nativeGpu"], "createdAt": created}}, HTTPStatus.CREATED)

    def _create_run(self, body: dict) -> None:
        run = run_service().create(self.principal.tenant_id, body)
        bump(run["id"])
        self._json({"data": run}, HTTPStatus.CREATED)

    def _create_job(self, body: dict) -> None:
        check_run_quota(self.principal)
        configs = body.get("configs") if isinstance(body.get("configs"), list) else []
        if not configs or len(configs) > 100:
            return self._json({"error": "configs must contain 1 to 100 parameter sets"}, HTTPStatus.BAD_REQUEST)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        concurrency = max(1, min(int(body.get("concurrency") or 2), int(os.environ.get("CLAWVISION_MAX_CONCURRENCY", "3"))))
        estimate_seconds = float(body.get("estimateSeconds") or sum(float(config.get("epochs", 40)) * 0.045 for config in configs) / concurrency)
        estimated_cost = float(body.get("estimatedCost") or estimate_seconds / 3600 * 0.65)
        created_at = now_iso()
        baseline_run_id = body.get("baselineRunId")
        if baseline_run_id and not self._owned("runs", str(baseline_run_id)):
            raise PermissionError("baseline run is outside the current tenant")
        kind = str(body.get("kind") or "single")
        provider = str(body.get("trainingProvider") or "simulator")
        catalog = {item["id"]: item for item in training_provider_catalog()}
        if provider not in catalog or not catalog[provider]["configured"]:
            raise ValueError(f"training provider is unavailable: {provider}")
        timeout = max(30, min(86400, int(body.get("timeoutSeconds") or 900)))
        run_ids = []
        with DB_LOCK, connect() as db:
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
            db.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?", ("running", now_iso(), job_id))
        semaphore = threading.Semaphore(concurrency)
        for run_id, config in zip(run_ids, configs):
            if provider == "simulator":
                task=enqueue_task(self.principal.tenant_id,"training",run_id,{"runId":run_id,"provider":provider},f"training:{run_id}")
                submit_durable(task,execute_queued_run,run_id,config,job_id,semaphore)
            else:
                with DB_LOCK, connect() as db: training = db.execute("SELECT id FROM training_jobs WHERE run_id=?", (run_id,)).fetchone()
                task=enqueue_task(self.principal.tenant_id,"training",training["id"],{"runId":run_id,"provider":provider},f"training:{training['id']}")
                submit_durable(task,execute_real_training,training["id"],run_id,config,job_id,provider,semaphore,timeout)
        self._json({"data": {"id": job_id, "runIds": run_ids, "kind": kind, "status": "running", "provider": provider, "totalRuns": len(run_ids), "concurrency": concurrency, "estimateSeconds": estimate_seconds, "estimatedCost": estimated_cost}}, HTTPStatus.CREATED)

    def _save_training_lineage(self, run_id: str, body: dict) -> None:
        framework=str(body.get("framework") or "custom").lower()
        if framework not in {"custom","pytorch","lightning","transformers","keras","jax"}: raise ValueError("unsupported training framework")
        timestamp=now_iso(); environment=body.get("environment") if isinstance(body.get("environment"),dict) else {}
        with DB_LOCK,connect() as db:
            db.execute("""INSERT INTO training_lineage(run_id,tenant_id,framework,code_ref,dataset_ref,environment,parent_run_id,resume_checkpoint_key,world_size,rank_count,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET framework=excluded.framework,code_ref=excluded.code_ref,dataset_ref=excluded.dataset_ref,environment=excluded.environment,parent_run_id=excluded.parent_run_id,resume_checkpoint_key=excluded.resume_checkpoint_key,world_size=excluded.world_size,rank_count=excluded.rank_count,updated_at=excluded.updated_at""",
              (run_id,self.principal.tenant_id,framework,body.get("codeRef"),body.get("datasetRef"),json.dumps(environment,ensure_ascii=False),body.get("parentRunId"),body.get("resumeCheckpointKey"),max(1,int(body.get("worldSize") or 1)),max(1,int(body.get("rankCount") or 1)),timestamp,timestamp))
            row=db.execute("SELECT * FROM training_lineage WHERE run_id=? AND tenant_id=?",(run_id,self.principal.tenant_id)).fetchone()
        self._json({"data":{**dict(row),"environment":json_value(row["environment"],{})}},HTTPStatus.CREATED)

    def _log_metrics(self, run_id: str, body: dict) -> None:
        result = run_service().mutate(run_id, self.principal.tenant_id, "metrics", body)
        bump(run_id)
        self._json(result)

    def _log_params(self, run_id: str, body: dict) -> None:
        result = run_service().mutate(run_id, self.principal.tenant_id, "params", body)
        bump(run_id)
        self._json(result)

    def _log_event(self, run_id: str, body: dict) -> None:
        result = run_service().mutate(run_id, self.principal.tenant_id, "events", body)
        bump(run_id)
        self._json(result, HTTPStatus.CREATED)

    def _log_artifact(self, run_id: str, body: dict) -> None:
        result = run_service().mutate(run_id, self.principal.tenant_id, "artifacts", body)
        bump(run_id)
        self._json(result, HTTPStatus.CREATED)

    def _batch(self, run_id: str, body: dict) -> None:
        result = run_service().mutate(run_id, self.principal.tenant_id, "batch", body)
        bump(run_id)
        self._json(result)

    def _resume_run(self, run_id: str, body: dict) -> None:
        result = run_service().mutate(run_id, self.principal.tenant_id, "resume", body)
        bump(run_id)
        self._json(result)

    def _set_status(self, run_id: str, status: str, body: dict) -> None:
        operation = {"completed": "finish", "failed": "fail", "stopped": "stop"}[status]
        result = run_service().mutate(run_id, self.principal.tenant_id, operation, body)
        bump(run_id)
        self._json(result)

    def _stream(self, run_id: str, query: dict | None = None) -> None:
        query = query or {}
        incremental = (query.get("incremental") or [""])[0] == "1"
        cursor = int((query.get("after") or [self.headers.get("Last-Event-ID", "0")])[0])
        service = run_service()
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
                with RUN_CONDITION:
                    RUN_CONDITION.wait(timeout=1.0)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _stream_agent_run(self, run_id: str) -> None:
        if not serialize_agent_run(run_id, OBJECT_STORE):
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
                item = serialize_agent_run(run_id, OBJECT_STORE)
                encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if encoded != previous:
                    self.wfile.write(f"event: pipeline\ndata: {encoded}\n\n".encode("utf-8")); self.wfile.flush(); previous = encoded
                if item and item["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(.2)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _stream_text3d_job(self, job_id: str) -> None:
        if not get_text3d_job(job_id):
            return self._json({"error": "text-to-3d job not found"}, HTTPStatus.NOT_FOUND)
        self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close"); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers()
        previous = ""
        try:
            for _ in range(900):
                item = get_text3d_job(job_id); encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
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


def initialize() -> dict:
    """Initialize persistence and recover durable work once per process."""
    global _INITIALIZED
    if _INITIALIZED:
        start_synthesis_recovery()
        return {"alreadyInitialized": True}
    init_database()
    resumed = resume_pending_jobs()
    resumed_agents = recover_agent_runs(EXECUTOR, OBJECT_STORE)
    resumed_text3d = recover_text3d_jobs(EXECUTOR, OBJECT_STORE)
    retired_model_jobs = recover_model_operation_jobs()
    retired_intelligent_jobs = recover_intelligent_geometry_jobs()
    _INITIALIZED = True
    start_synthesis_recovery()
    return {"resumedRuns": resumed, "resumedAgents": resumed_agents, "resumedText3D": resumed_text3d, "retiredModelJobs": retired_model_jobs, "retiredGeometryJobs": retired_intelligent_jobs}


if __name__ == "__main__":
    recovery = initialize()
    print(f"ClawVision API listening on http://{HOST}:{PORT}")
    print(f"Database: {database_label()}")
    print(f"Object store: {OBJECT_STORE.kind}")
    print(f"Recovery: {json.dumps(recovery, ensure_ascii=False)}")
    service=ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        service.serve_forever()
    finally:
        stop_synthesis_recovery(); shutdown_text3d_workers(); EXECUTOR.shutdown(wait=False,cancel_futures=True); service.server_close()
