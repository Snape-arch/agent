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
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pathlib import Path
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from visualization.backend.api_contract import openapi_document, page_meta, parse_pagination
from visualization.backend.ai_studio import TEMPLATES, interpret, validate_plan
from visualization.backend.asset_scene import apply_asset_operations, canonicalize_mesh_asset, interpret_asset_command, pack_glb, parse_asset, quality_report, scene_manifest
from visualization.backend.agent_pipeline import cancel_agent_run, create_agent_run, execute_agent_pipeline, recover_agent_runs, serialize_agent_run
from visualization.backend.credentials import resolve_provider_key
from visualization.backend.database import connect, database_label, init_database, is_integrity_error, is_postgres
from visualization.backend.mesh_generator import compile_gltf, compile_obj
from visualization.backend.scene_operations import apply_operations, interpret_scene_command
from visualization.backend.object_store import create_object_store
from visualization.backend.text3d_service import cancel_text3d_job, create_text3d_job, execute_text3d_job, get_text3d_job, list_text3d_providers, recover_text3d_jobs, shutdown_text3d_workers
from visualization.backend.geometry_worker import provider_catalog as geometry_provider_catalog, run_provider as run_geometry_provider
from visualization.backend.scene_agent import assess_operations, record_decision, serialize_scene_agent_run, understand_scene
from visualization.backend.training_runner import cancel as cancel_training_process, provider_catalog as training_provider_catalog, run as run_training_provider
from visualization.backend.security import (audit, authenticate, bootstrap, check_run_quota, check_task_quota, create_member,
                      issue_token, list_members, list_tokens, login, quota_status,
                      reserve_storage, revoke_token, save_credential)
from visualization.backend.durable_queue import (enqueue as enqueue_task, serialize as serialize_task, queue_metrics, cancel as cancel_task,
                           reap_expired, lease as lease_task, heartbeat as heartbeat_task,
                           finish as finish_task, fail as fail_task)
from visualization.backend.domain_services import CollectionService, DatasetService
from visualization.backend.run_service import RunService
from visualization.backend.evaluation_service import EvaluationService
from visualization.backend.scenario_service import ScenarioService
from visualization.backend.synthesis_service import SynthesisService, execute_synthesis_job
from visualization.backend.vision_dataset_service import VisionDatasetService
from visualization.backend.vision_experiment_service import VisionExperimentService, execute_vision_experiment
from visualization.backend.analytics_service import AnalysisQueryService, DatasetCatalog, schema_diff
from visualization.backend.errors import ApplicationError, ConflictError, NotFoundError, ValidationError, problem_details
from visualization.backend.columnar_engine import parquet_row_count, parquet_to_rows, rows_to_parquet
from visualization.backend.observability import adopt_traceparent, gauge, inc, observe, record_span, render_prometheus
from visualization.backend.worker_health import statuses as worker_statuses

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


from visualization.backend.handlers.transport import TransportHandler
from visualization.backend.handlers.queries import QueriesHandler
from visualization.backend.handlers.mutations import MutationsHandler
from visualization.backend.handlers.studio import StudioHandler
from visualization.backend.handlers.datasets import DatasetsHandler
from visualization.backend.handlers.scenes import ScenesHandler
from visualization.backend.handlers.scene_agents import SceneAgentsHandler
from visualization.backend.handlers.geometry import GeometryHandler
from visualization.backend.handlers.assets import AssetsHandler
from visualization.backend.handlers.runs import RunsHandler


class Handler(
    TransportHandler,
    QueriesHandler,
    MutationsHandler,
    StudioHandler,
    DatasetsHandler,
    ScenesHandler,
    SceneAgentsHandler,
    GeometryHandler,
    AssetsHandler,
    RunsHandler,
    BaseHTTPRequestHandler,
):
    """Assemble domain handlers using this process runtime."""
    runtime = sys.modules[__name__]
    server_version = "ClawVision/0.22"




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
