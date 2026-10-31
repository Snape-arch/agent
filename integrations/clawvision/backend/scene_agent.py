"""Semantic scene-edit Agent analysis, risk gating and durable decisions."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone

from database import connect


TERMINAL = {"ready", "completed", "rejected", "failed", "cancelled", "stale"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_value(raw, fallback):
    try: return json.loads(raw) if raw else fallback
    except (TypeError, json.JSONDecodeError): return fallback


def understand_scene(manifest: dict) -> dict:
    nodes = manifest.get("nodes", []); materials = manifest.get("materials", [])
    mesh_nodes = [node for node in nodes if node.get("meshIndex") is not None]
    total_faces = sum(int(node.get("faceCount") or 0) for node in mesh_nodes)
    total_vertices = sum(int(node.get("vertexCount") or 0) for node in mesh_nodes)
    roles = []
    for node in mesh_nodes:
        name = str(node.get("name") or "").lower(); role = "component"
        if any(token in name for token in ("base", "body", "frame", "chassis", "底", "主体")): role = "primary-structure"
        elif any(token in name for token in ("wheel", "arm", "leg", "wing", "轮", "臂", "翼")): role = "moving-part"
        elif any(token in name for token in ("screen", "lens", "sensor", "camera", "屏", "镜头", "传感")): role = "functional-surface"
        elif not node.get("parentId"): role = "root-component"
        roles.append({"nodeId": node.get("id"), "name": node.get("name"), "role": role, "faces": int(node.get("faceCount") or 0), "locked": bool(node.get("locked")), "materialIds": node.get("materialIds", [])})
    complexity = "high" if total_faces > 250000 or len(mesh_nodes) > 100 else "medium" if total_faces > 30000 or len(mesh_nodes) > 20 else "low"
    return {"nodeCount": len(nodes), "meshCount": len(mesh_nodes), "materialCount": len(materials), "totalFaces": total_faces, "totalVertices": total_vertices, "complexity": complexity, "roles": roles, "unknownStructure": not bool(mesh_nodes), "summary": f"{len(mesh_nodes)} editable mesh nodes, {total_faces} faces, {len(materials)} materials"}


def assess_operations(operations: list[dict], understanding: dict, manifest: dict) -> dict:
    weights = {"delete": 50, "csg": 40, "modifier": 25, "repair": 18, "remesh": 20, "duplicate": 12, "transform": 8, "material": 4, "rename": 2, "visibility": 2, "lock": 2, "group": 3}
    score = 0; warnings = []; affected = set(); heavy = False
    nodes = {str(node.get("id")): node for node in manifest.get("nodes", [])}
    for operation in operations:
        kind = str(operation.get("type") or ""); payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
        modifier = str(payload.get("kind") or ""); targets = [str(item) for item in operation.get("targetIds", [])]; affected.update(targets)
        score += weights.get(kind, 10)
        if kind == "modifier":
            score += {"boolean": 35, "decimate": 24, "remesh": 22, "bevel": 18, "chamfer": 18, "subdivision": 16}.get(modifier, 8)
            heavy = heavy or modifier in {"boolean", "decimate", "remesh", "bevel", "chamfer", "subdivision", "uv-unwrap", "fillet"}
        if any(nodes.get(target, {}).get("locked") for target in targets): warnings.append("selection contains locked nodes")
        if kind == "delete": warnings.append("deletion hides geometry and changes downstream selections")
        if kind == "modifier" and modifier == "boolean" and len(targets) != 2: warnings.append("boolean requires exactly two mesh nodes")
    face_factor = math.log10(max(10, int(understanding.get("totalFaces") or 0)))
    score += int(max(0, face_factor - 4) * 12); score = min(100, score)
    level = "critical" if score >= 75 else "high" if score >= 50 else "medium" if score >= 25 else "low"
    estimated_seconds = round(max(.2, .12 * len(operations) + (understanding.get("totalFaces", 0) / 180000 if heavy else 0)), 2)
    estimated_cost = round((understanding.get("totalFaces", 0) / 1_000_000) * (.08 if heavy else .01), 6)
    return {"score": score, "level": level, "warnings": list(dict.fromkeys(warnings)), "affectedNodeIds": sorted(affected), "operationCount": len(operations), "heavyGeometry": heavy, "estimatedSeconds": estimated_seconds, "estimatedCost": estimated_cost, "requiresConfirmation": level in {"high", "critical"}, "rollbackStrategy": "non-destructive preview; source version remains immutable until explicit apply"}


def record_decision(run_id: str, stage: str, decision: str, reason: str, payload: dict | None = None) -> str:
    decision_id = f"decision_{uuid.uuid4().hex[:12]}"; created = now_iso()
    with connect() as db:
        db.execute("INSERT INTO scene_agent_decisions(id,run_id,stage,decision,reason,payload,created_at) VALUES(?,?,?,?,?,?,?)", (decision_id, run_id, stage, decision, reason[:1000], json.dumps(payload or {}, ensure_ascii=False), created))
    return decision_id


def serialize_scene_agent_run(run_id: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM scene_agent_runs WHERE id=?", (run_id,)).fetchone()
        if not row: return None
        decisions = db.execute("SELECT * FROM scene_agent_decisions WHERE run_id=? ORDER BY created_at,id", (run_id,)).fetchall()
    return {"id": row["id"], "sceneId": row["scene_id"], "command": row["command"], "provider": row["provider"], "model": row["model"], "status": row["status"], "progress": row["progress"], "stage": row["stage"], "baseVersion": row["base_version"], "operations": json_value(row["operations"], []), "analysis": json_value(row["analysis"], {}), "preview": json_value(row["preview"], None), "result": json_value(row["result"], None), "error": row["error"], "riskLevel": row["risk_level"], "estimatedCost": row["estimated_cost"], "estimatedSeconds": row["estimated_seconds"], "qualityCycles": row["quality_cycles"], "maxCycles": row["max_cycles"], "cancelRequested": bool(row["cancel_requested"]), "decisions": [{"id": item["id"], "stage": item["stage"], "decision": item["decision"], "reason": item["reason"], "payload": json_value(item["payload"], {}), "createdAt": item["created_at"]} for item in decisions], "createdAt": row["created_at"], "updatedAt": row["updated_at"]}
