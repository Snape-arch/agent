"""Durable task-bound coding trajectories with integrity digests."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CodingTraceService:
    STEP_TYPES = {
        "context", "model", "tool", "edit", "test", "review", "failure",
    }

    def __init__(self, path: str | Path = "output/traces/coding.json"):
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()

    def start(
        self, *, objective: str, repo_path: str | Path, task_id: str = "",
        session_id: str = "", actor_id: str = "local-user",
    ) -> dict[str, Any]:
        run = {
            "id": f"ctr-{uuid.uuid4().hex}",
            "schema": "clawos.coding-trajectory.v1",
            "objective_digest": self._digest(str(objective)),
            "repository_id": self._digest(str(Path(repo_path).resolve())),
            "task_id": str(task_id),
            "session_id": str(session_id),
            "actor_id": str(actor_id),
            "status": "running",
            "started_at": self._now(),
            "steps": [],
        }
        self._append(run)
        return run

    def step(
        self, run_id: str, step_type: str, *, status: str,
        input_value: Any = None, output_value: Any = None,
        behavior_propensity: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if step_type not in self.STEP_TYPES:
            raise ValueError(f"unsupported coding trace step: {step_type}")
        value = self._read()
        run = next((item for item in value["records"] if item["id"] == run_id), None)
        if run is None:
            raise KeyError("coding trajectory not found")
        item = {
            "sequence": len(run["steps"]) + 1,
            "type": step_type,
            "status": str(status),
            "input_digest": self._digest(input_value),
            "output_digest": self._digest(output_value),
            "behavior_propensity": (
                None if behavior_propensity is None else float(behavior_propensity)
            ),
            "metadata": dict(metadata or {}),
            "observed_at": self._now(),
        }
        item["step_digest"] = self._digest(item)
        run["steps"].append(item)
        self._write(value)
        return item

    def finish(self, run_id: str, status: str) -> dict[str, Any]:
        value = self._read()
        run = next((item for item in value["records"] if item["id"] == run_id), None)
        if run is None:
            raise KeyError("coding trajectory not found")
        run["status"] = str(status)
        run["completed_at"] = self._now()
        run["trajectory_digest"] = self._digest({
            key: item for key, item in run.items() if key != "trajectory_digest"
        })
        self._write(value)
        return run

    def get(self, run_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self._read()["records"] if item["id"] == run_id),
            None,
        )

    def _append(self, run: dict[str, Any]) -> None:
        value = self._read()
        value["records"].append(run)
        self._write(value)

    def _read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.is_file():
                return {"schema": "clawos.coding-trajectories.v1", "records": []}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"schema": "clawos.coding-trajectories.v1", "records": []}
            return value if isinstance(value, dict) else {
                "schema": "clawos.coding-trajectories.v1", "records": []
            }

    def _write(self, value: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp",
                dir=str(self.path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(value, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

    @staticmethod
    def _digest(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
