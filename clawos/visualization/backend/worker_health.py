"""Shared-file Worker liveness state used by Compose probes and API metrics."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("CLAWVISION_WORKER_HEALTH_DIR", os.environ.get("CLAWVISION_DATA_DIR", "/data"))) / "worker-health"


def write(worker_id: str, *, state: str, task_id: str | None = None, kind: str | None = None, completed: int = 0, failed: int = 0) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    value = {"workerId": worker_id, "state": state, "taskId": task_id, "kind": kind,
             "completed": completed, "failed": failed, "updatedAt": datetime.now(timezone.utc).isoformat()}
    handle, temporary = tempfile.mkstemp(prefix=f".{worker_id}.", suffix=".tmp", dir=ROOT)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream: json.dump(value, stream)
        os.replace(temporary, ROOT / f"{worker_id}.json")
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def statuses(max_age_seconds: int = 45, *, purge_after_seconds: int = 300) -> list[dict]:
    if not ROOT.exists(): return []
    now = datetime.now(timezone.utc); values=[]
    for path in ROOT.glob("*.json"):
        try:
            item=json.loads(path.read_text(encoding="utf-8"));age=(now-datetime.fromisoformat(item["updatedAt"])).total_seconds()
            if age > purge_after_seconds:
                path.unlink(missing_ok=True);continue
            values.append({**item,"ageSeconds":max(0,age),"healthy":age <= max_age_seconds})
        except (OSError,ValueError,KeyError,json.JSONDecodeError): continue
    return values


def current_healthy(worker_id: str, max_age_seconds: int = 45) -> bool:
    return any(item["workerId"] == worker_id and item["healthy"] for item in statuses(max_age_seconds))


def remove(worker_id: str) -> None:
    (ROOT/f"{worker_id}.json").unlink(missing_ok=True)
