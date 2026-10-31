"""Persistent, retryable AI Studio agent pipeline with intermediate artifacts."""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from ai_studio import local_3d_plan, provider_plan, validate_plan
from database import connect
from credentials import resolve_provider_key
from security import reserve_storage

LOCK = threading.RLock()
AGENT_LIMIT = threading.BoundedSemaphore(max(1, int(os.environ.get("AGENT_MAX_CONCURRENCY", "2"))))
TERMINAL = {"completed", "failed", "cancelled"}
STAGE_LABELS = {
    "prompt": "Prompt Architect", "structure": "Structure Agent", "surface": "Surface Detail Agent",
    "material": "Material Agent", "quality": "Quality Agent",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(raw, fallback):
    try:
        return json.loads(raw) if raw else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def create_agent_run(prompt: str, provider: str, model: str, max_cycles: int, timeout_seconds: int = 300, tenant_id: str = "default") -> str:
    run_id = f"agent_{uuid.uuid4().hex[:12]}"
    timestamp = now_iso()
    with LOCK, connect() as db:
        db.execute("""INSERT INTO agent_runs(id,prompt,provider,model,status,cycle,max_cycles,total_tokens,total_cost,duration_ms,result,error,created_at,updated_at,timeout_seconds,cancel_requested,tenant_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (run_id, prompt, provider, model, "queued", 0, max_cycles, 0, 0, 0, None, None, timestamp, timestamp, max(15,min(1800,timeout_seconds)), 0,tenant_id))
    return run_id


def cancel_agent_run(run_id: str) -> dict | None:
    with LOCK, connect() as db:
        row=db.execute("SELECT status FROM agent_runs WHERE id=?",(run_id,)).fetchone()
        if not row: return None
        if row["status"] not in TERMINAL:
            db.execute("UPDATE agent_runs SET cancel_requested=1,status='cancelling',updated_at=? WHERE id=?",(now_iso(),run_id))
    return {"id":run_id,"status":"cancelling"}


def _check_cancelled(run_id: str) -> None:
    with LOCK, connect() as db:
        row=db.execute("SELECT cancel_requested,created_at,timeout_seconds FROM agent_runs WHERE id=?",(run_id,)).fetchone()
    if row and row["cancel_requested"]: raise RuntimeError("cancelled")
    if row and (datetime.now(timezone.utc)-datetime.fromisoformat(row["created_at"])).total_seconds()>row["timeout_seconds"]:
        raise RuntimeError(f"pipeline exceeded {row['timeout_seconds']}s timeout")


def recover_agent_runs(executor, object_store) -> int:
    with LOCK, connect() as db:
        rows = db.execute("SELECT * FROM agent_runs WHERE status NOT IN ('completed','failed','cancelled') ORDER BY created_at").fetchall()
    resumed = 0
    for row in rows:
        if row["provider"] != "local":
            with LOCK, connect() as db:
                db.execute("UPDATE agent_runs SET status=?,error=?,updated_at=? WHERE id=?",
                           ("failed", "Server restarted; online credentials were intentionally not persisted. Resubmit this pipeline.", now_iso(), row["id"]))
            continue
        request = {"prompt": row["prompt"], "provider": "local", "model": "local", "maxCycles": row["max_cycles"], "qualityThreshold": 92}
        executor.submit(execute_agent_pipeline, row["id"], request, object_store); resumed += 1
    return resumed


def serialize_agent_run(run_id: str, object_store) -> dict | None:
    with LOCK, connect() as db:
        run = db.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            return None
        stages = db.execute("SELECT * FROM agent_stages WHERE run_id=? ORDER BY created_at,id", (run_id,)).fetchall()
        artifacts = db.execute("SELECT * FROM agent_artifacts WHERE run_id=? ORDER BY created_at,id", (run_id,)).fetchall()
    artifact_items = []
    for item in artifacts:
        try:
            payload = object_store.get_json(item["object_key"])
        except (FileNotFoundError, KeyError, ValueError):
            payload = {"unavailable": True}
        artifact_items.append({"id": item["id"], "stage": item["stage"], "cycle": item["cycle"], "kind": item["kind"], "payload": payload, "createdAt": item["created_at"]})
    return {
        "id": run["id"], "prompt": run["prompt"], "provider": run["provider"], "model": run["model"],
        "status": run["status"], "cycle": run["cycle"], "maxCycles": run["max_cycles"],
        "totalTokens": run["total_tokens"], "totalCost": run["total_cost"], "durationMs": run["duration_ms"],
        "result": _json(run["result"], None), "error": run["error"], "timeoutSeconds": run["timeout_seconds"],
        "cancelRequested": bool(run["cancel_requested"]), "createdAt": run["created_at"], "updatedAt": run["updated_at"],
        "stages": [{
            "id": row["id"], "cycle": row["cycle"], "stage": row["stage"], "name": STAGE_LABELS.get(row["stage"], row["stage"]),
            "status": row["status"], "attempt": row["attempt"], "maxAttempts": row["max_attempts"],
            "inputArtifactId": row["input_artifact_id"], "outputArtifactId": row["output_artifact_id"],
            "tokens": row["tokens"], "cost": row["cost"], "durationMs": row["duration_ms"], "error": row["error"],
            "tokenSource": "provider" if run["provider"] != "local" and row["stage"] == "structure" and row["status"] == "completed" else "estimated-workload",
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        } for row in stages],
        "artifacts": artifact_items,
    }


def _save_artifact(run_id: str, stage: str, cycle: int, kind: str, payload: Any, object_store) -> str:
    artifact_id = f"ia_{uuid.uuid4().hex[:12]}"
    with LOCK,connect() as db: tenant_row=db.execute("SELECT tenant_id FROM agent_runs WHERE id=?",(run_id,)).fetchone()
    tenant_id=tenant_row["tenant_id"] if tenant_row else "default";reserve_storage(tenant_id,len(json.dumps(payload,ensure_ascii=False).encode()));key = object_store.put_json(f"tenants/{tenant_id}/studio/agent-runs/{run_id}/{artifact_id}.json", payload)
    with LOCK, connect() as db:
        db.execute("INSERT INTO agent_artifacts(id,run_id,stage,cycle,kind,object_key,created_at) VALUES(?,?,?,?,?,?,?)",
                   (artifact_id, run_id, stage, cycle, kind, key, now_iso()))
    return artifact_id


def _cost(provider: str, prompt_tokens: int, completion_tokens: int) -> float:
    if provider == "local":
        return 0.0
    input_rate = float(os.environ.get(f"{provider.upper()}_INPUT_COST_PER_M", os.environ.get("PROVIDER_INPUT_COST_PER_M", "0.20")))
    output_rate = float(os.environ.get(f"{provider.upper()}_OUTPUT_COST_PER_M", os.environ.get("PROVIDER_OUTPUT_COST_PER_M", "0.60")))
    return prompt_tokens / 1_000_000 * input_rate + completion_tokens / 1_000_000 * output_rate


def _run_stage(run_id: str, cycle: int, stage: str, input_artifact_id: str | None, action: Callable[[], tuple[Any, dict]], object_store, max_attempts: int = 3) -> tuple[Any, str]:
    _check_cancelled(run_id)
    max_attempts = max(1, min(5, int(os.environ.get("AGENT_STAGE_MAX_ATTEMPTS", max_attempts))))
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        stage_id = f"as_{uuid.uuid4().hex[:12]}"
        started_at = now_iso(); started = time.perf_counter()
        with LOCK, connect() as db:
            db.execute("""INSERT INTO agent_stages(id,run_id,cycle,stage,status,attempt,max_attempts,input_artifact_id,output_artifact_id,tokens,cost,duration_ms,error,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (stage_id, run_id, cycle, stage, "running", attempt, max_attempts, input_artifact_id, None, 0, 0, 0, None, started_at, started_at))
            db.execute("UPDATE agent_runs SET status=?,cycle=?,updated_at=? WHERE id=?", (stage, cycle, started_at, run_id))
        try:
            output, usage = action()
            prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
            output_id = _save_artifact(run_id, stage, cycle, f"{stage}-output", output, object_store)
            duration = max(1, round((time.perf_counter() - started) * 1000)); cost = _cost(usage.get("provider", "local"), prompt_tokens, completion_tokens) if usage.get("billable") else 0.0
            with LOCK, connect() as db:
                db.execute("UPDATE agent_stages SET status=?,output_artifact_id=?,tokens=?,cost=?,duration_ms=?,updated_at=? WHERE id=?",
                           ("completed", output_id, tokens, cost, duration, now_iso(), stage_id))
                db.execute("UPDATE agent_runs SET total_tokens=total_tokens+?,total_cost=total_cost+?,updated_at=? WHERE id=?", (tokens, cost, now_iso(), run_id))
            return output, output_id
        except Exception as error:
            last_error = error; duration = max(1, round((time.perf_counter() - started) * 1000))
            with LOCK, connect() as db:
                db.execute("UPDATE agent_stages SET status=?,duration_ms=?,error=?,updated_at=? WHERE id=?", ("failed", duration, str(error)[:1000], now_iso(), stage_id))
            if attempt < max_attempts:
                time.sleep(.12 * 2 ** (attempt - 1))
    raise RuntimeError(f"{STAGE_LABELS.get(stage, stage)} failed after {max_attempts} attempts: {last_error}")


def _usage(provider: str, input_value: Any, output_value: Any, actual: dict | None = None) -> dict:
    if actual:
        return {**actual, "provider": provider, "billable": True}
    # Local agents do not bill tokens; keep an estimated workload count for stage observability.
    estimated = max(1, (len(json.dumps(input_value, ensure_ascii=False)) + len(json.dumps(output_value, ensure_ascii=False))) // 4)
    return {"provider": provider, "total_tokens": estimated, "prompt_tokens": estimated // 2, "completion_tokens": estimated - estimated // 2, "billable": False}


def _refine_structure(plan: dict, cycle: int) -> dict:
    result = copy.deepcopy(plan)
    color = result.get("parameters", {}).get("color", "#86dfc4")
    material = result.get("parameters", {}).get("material", "metal")
    details = max(2, min(8, cycle * 2 + 2))
    for index in range(details):
        result["parts"].append({
            "shape": "roundedBox" if index % 2 == 0 else "cylinder", "name": f"Quality refinement {cycle}.{index + 1}",
            "size": [.18 + index * .02, .12, .08], "position": [(index - details / 2) * .24, .35 + cycle * .12, .52],
            "rotation": [0, 0, 0], "color": color, "material": material,
        })
    return result


def execute_agent_pipeline(run_id: str, request: dict, object_store) -> None:
    started = time.perf_counter()
    prompt = str(request.get("prompt") or "")
    provider = str(request.get("provider") or "local").lower()
    model = str(request.get("model") or "")
    api_key = resolve_provider_key(provider, str(request.get("credentialRef") or "") or None) if provider != "local" else ""
    max_cycles = max(1, min(4, int(request.get("maxCycles") or os.environ.get("AGENT_QUALITY_MAX_CYCLES", "2"))))
    threshold = max(70, min(100, int(request.get("qualityThreshold") or os.environ.get("AGENT_QUALITY_THRESHOLD", "92"))))
    acquired = AGENT_LIMIT.acquire(timeout=max(15, int(request.get("timeoutSeconds") or 300)))
    if not acquired:
        with LOCK, connect() as db: db.execute("UPDATE agent_runs SET status='failed',error='agent concurrency timeout',updated_at=? WHERE id=?",(now_iso(),run_id))
        return
    try:
        optimized, artifact_id = _run_stage(run_id, 0, "prompt", None, lambda: (
            {"prompt": prompt, "optimizedPrompt": f"{prompt}。要求结构分层、比例一致、可编辑部件、制造细节和清晰材质分区。"},
            _usage(provider, prompt, prompt + " optimized")), object_store)
        plan: dict | None = None
        for cycle in range(max_cycles):
            def structure_action():
                usage: dict = {}
                stage_prompt = optimized["optimizedPrompt"] + (f" 第 {cycle + 1} 轮质量返工：增加结构支撑和语义细节。" if cycle else "")
                generated = provider_plan(provider, api_key, model, stage_prompt, "model3d", usage_sink=usage) if provider != "local" else local_3d_plan(stage_prompt)
                if cycle and plan:
                    generated = _refine_structure(generated, cycle)
                return generated, _usage(provider, stage_prompt, generated, usage)
            plan, structure_id = _run_stage(run_id, cycle, "structure", artifact_id, structure_action, object_store)

            def surface_action():
                surfaced = copy.deepcopy(plan)
                curve = float(surfaced.get("parameters", {}).get("curveStrength", .5))
                for index, part in enumerate(surfaced.get("parts", [])):
                    part["bevel"] = round(.015 + curve * .065, 4)
                    part["booleanOperation"] = "union" if index else "base"
                    part["uv"] = {"repeatX": 1.0, "repeatY": 1.0, "strength": .72}
                return surfaced, _usage(provider, plan, surfaced)
            plan, surface_id = _run_stage(run_id, cycle, "surface", structure_id, surface_action, object_store)

            def material_action():
                materialized = copy.deepcopy(plan)
                for part in materialized.get("parts", []):
                    part.setdefault("material", materialized.get("parameters", {}).get("material", "metal"))
                    part.setdefault("color", materialized.get("parameters", {}).get("color", "#86dfc4"))
                return materialized, _usage(provider, plan, materialized)
            plan, material_id = _run_stage(run_id, cycle, "material", surface_id, material_action, object_store)

            def quality_action():
                validation = validate_plan(plan)
                parts = plan.get("parts", []); shapes = {part.get("shape") for part in parts if isinstance(part, dict)}
                uv_ready = all(isinstance(part.get("uv"), dict) for part in parts if isinstance(part, dict))
                score = min(validation["score"], min(100, 76 + min(16, len(parts)) + min(8, len(shapes) * 2) + cycle * 5 + (3 if uv_ready else 0)))
                report = {**validation, "score": score, "threshold": threshold, "passed": validation["valid"] and score >= threshold,
                          "decision": "accept" if validation["valid"] and score >= threshold else "return-to-structure-surface",
                          "cycle": cycle, "partCount": len(parts), "shapeDiversity": len(shapes), "uvReady": uv_ready}
                return report, _usage(provider, plan, report)
            report, artifact_id = _run_stage(run_id, cycle, "quality", material_id, quality_action, object_store)
            plan["validation"] = {key: report[key] for key in ("valid", "score", "warnings", "checks")}
            if report["passed"]:
                break
            if cycle == max_cycles - 1:
                raise RuntimeError(f"Quality Agent rejected the model after {max_cycles} cycles (score {report['score']}/{threshold})")

        with LOCK, connect() as db:
            stage_rows = db.execute("SELECT stage,status,attempt,tokens,cost,duration_ms,error FROM agent_stages WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        plan["agents"] = [{"id": f"{row['stage']}-{index}", "name": STAGE_LABELS.get(row["stage"], row["stage"]), "status": row["status"],
                           "message": f"cycle stage · attempt {row['attempt']} · {row['tokens']} tokens · ${row['cost']:.6f} · {row['duration_ms']}ms" + (f" · {row['error']}" if row["error"] else "")}
                          for index, row in enumerate(stage_rows)]
        duration = max(1, round((time.perf_counter() - started) * 1000))
        with LOCK, connect() as db:
            db.execute("UPDATE agent_runs SET status=?,result=?,duration_ms=?,updated_at=? WHERE id=?", ("completed", json.dumps(plan, ensure_ascii=False), duration, now_iso(), run_id))
    except Exception as error:
        duration = max(1, round((time.perf_counter() - started) * 1000))
        cancelled = str(error) == "cancelled"
        with LOCK, connect() as db:
            db.execute("UPDATE agent_runs SET status=?,error=?,duration_ms=?,updated_at=? WHERE id=?", ("cancelled" if cancelled else "failed", None if cancelled else str(error)[:2000], duration, now_iso(), run_id))
    finally:
        AGENT_LIMIT.release()
