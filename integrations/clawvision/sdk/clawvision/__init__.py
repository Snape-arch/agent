"""ClawVision Python SDK with batching and durable offline replay."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ClawVisionError(RuntimeError):
    pass


def _request(base_url: str, path: str, payload: dict[str, Any] | None = None, method: str = "POST", api_token: str | None = None) -> dict[str, Any]:
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8") if method != "GET" else None
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", data=data, method=method,
        headers={"Content-Type": "application/json", "User-Agent": "clawvision-python/0.22", **({"Authorization": f"Bearer {api_token or os.environ.get('CLAWVISION_API_TOKEN')}"} if api_token or os.environ.get("CLAWVISION_API_TOKEN") else {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise ClawVisionError(f"ClawVision request failed: {error}") from error


def _spool_root() -> Path:
    root = Path(os.environ.get("CLAWVISION_SPOOL_DIR", Path.cwd() / ".clawvision-spool"))
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class Run:
    id: str
    base_url: str
    buffer_size: int = 10
    api_token: str | None = None
    _pending: dict[str, Any] = field(default_factory=lambda: {"params": {}, "metrics": [], "events": [], "artifacts": []})

    @property
    def spool_path(self) -> Path:
        return _spool_root() / f"{self.id}.jsonl"

    def _spool(self, path: str, payload: dict[str, Any]) -> None:
        with self.spool_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"baseUrl": self.base_url, "path": path, "payload": payload}, ensure_ascii=False) + "\n")

    def _pending_count(self) -> int:
        return len(self._pending["metrics"]) + len(self._pending["events"]) + len(self._pending["artifacts"]) + len(self._pending["params"])

    def flush(self) -> "Run":
        if not self._pending_count():
            return self
        payload = self._pending
        self._pending = {"params": {}, "metrics": [], "events": [], "artifacts": []}
        path = f"/api/runs/{self.id}/batch"
        try:
            _request(self.base_url, path, payload, api_token=self.api_token)
        except ClawVisionError:
            self._spool(path, payload)
        return self

    def _flush_if_needed(self) -> None:
        if self._pending_count() >= self.buffer_size:
            self.flush()

    def log_param(self, name: str, value: Any) -> "Run":
        self._pending["params"][name] = value
        self._flush_if_needed()
        return self

    def log_metric(self, name: str, value: float, step: int, **metrics: float) -> "Run":
        aliases = {"loss": "trainLoss", "train_loss": "trainLoss", "val_loss": "valLoss", "val_accuracy": "accuracy", "lr": "learningRate"}
        point: dict[str, Any] = {"step": int(step), "eventId": f"metric_{uuid.uuid4().hex}", aliases.get(name, name): float(value)}
        point.update({aliases.get(key, key): float(item) for key, item in metrics.items()})
        self._pending["metrics"].append(point)
        self._flush_if_needed()
        return self

    def log_metrics(self, step: int, **metrics: float) -> "Run":
        aliases = {"loss": "trainLoss", "train_loss": "trainLoss", "val_loss": "valLoss", "val_accuracy": "accuracy", "lr": "learningRate"}
        self._pending["metrics"].append({"step": int(step), "eventId": f"metric_{uuid.uuid4().hex}", **{aliases.get(key, key): float(value) for key, value in metrics.items()}})
        self._flush_if_needed()
        return self

    def log_event(self, message: str, level: str = "info") -> "Run":
        self._pending["events"].append({"message": message, "level": level, "eventId": f"event_{uuid.uuid4().hex}"})
        self._flush_if_needed()
        return self

    def log_artifact(self, name: str, content: Any, artifact_type: str = "json", step: int | None = None, mime_type: str = "application/json") -> "Run":
        self._pending["artifacts"].append({"name": name, "content": content, "type": artifact_type, "step": step, "mimeType": mime_type, "eventId": f"artifact_{uuid.uuid4().hex}"})
        self._flush_if_needed()
        return self

    def log_embedding_frame(self, points: list[dict[str, Any]], step: int) -> "Run":
        """Append an embedding frame understood by the 3D evolution plugin."""
        return self.log_artifact(f"embedding-step-{step}", {"frames": [{"step": step, "points": points}]}, "embedding-evolution-3d", step)

    def log_point_cloud(self, points: list[list[float]], step: int, **metadata: Any) -> "Run":
        return self.log_artifact(f"point-cloud-{step}", {"points": points, **metadata}, "point-cloud-3d", step)

    def log_trajectory(self, trajectory: list[list[float]], step: int, **metadata: Any) -> "Run":
        return self.log_artifact(f"trajectory-{step}", {"trajectory": trajectory, **metadata}, "trajectory-3d", step)

    def log_vector_field(self, vectors: list[dict[str, Any]], step: int, **metadata: Any) -> "Run":
        return self.log_artifact(f"vector-field-{step}", {"vectors": vectors, **metadata}, "vector-field-3d", step)

    def log_simulation_frame(self, points: list[list[float]], step: int, *, trajectory: list[list[float]] | None = None, vectors: list[dict[str, Any]] | None = None) -> "Run":
        frame = {"step": step, "points": points, "trajectory": trajectory or [], "vectors": vectors or []}
        return self.log_artifact(f"simulation-step-{step}", {"frames": [frame]}, "simulation-replay-3d", step)

    def link_model_asset(self, asset_id: str, *, step: int | None = None, role: str = "checkpoint", scene_id: str | None = None, metadata: dict[str, Any] | None = None) -> "Run":
        self.flush(); path = f"/api/runs/{self.id}/assets"; payload = {"assetId": asset_id, "step": step, "role": role, "sceneId": scene_id, "metadata": metadata or {}}
        try:
            _request(self.base_url, path, payload, api_token=self.api_token)
        except ClawVisionError:
            self._spool(path, payload)
        return self

    def _status(self, action: str, payload: dict[str, Any]) -> None:
        self.flush()
        path = f"/api/runs/{self.id}/{action}"
        try:
            _request(self.base_url, path, payload, api_token=self.api_token)
        except ClawVisionError:
            self._spool(path, payload)

    def finish(self, message: str = "训练正常结束") -> "Run":
        self._status("finish", {"message": message})
        return self

    def fail(self, error: str) -> "Run":
        self._status("fail", {"error": error, "message": f"训练失败 · {error}"})
        return self

    def resume(self, checkpoint_key: str | None = None) -> "Run":
        path = f"/api/runs/{self.id}/resume"
        payload = {"checkpointKey": checkpoint_key}
        try:
            _request(self.base_url, path, payload, api_token=self.api_token)
        except ClawVisionError:
            self._spool(path, payload)
        return self

    def log_lineage(self, *, framework: str = "custom", code_ref: str | None = None,
                    dataset_ref: str | None = None, environment: dict[str, Any] | None = None,
                    parent_run_id: str | None = None, resume_checkpoint_key: str | None = None,
                    world_size: int = 1, rank_count: int = 1) -> "Run":
        payload = {"framework": framework, "codeRef": code_ref, "datasetRef": dataset_ref,
                   "environment": environment or {}, "parentRunId": parent_run_id,
                   "resumeCheckpointKey": resume_checkpoint_key, "worldSize": world_size, "rankCount": rank_count}
        try: _request(self.base_url, f"/api/runs/{self.id}/lineage", payload, api_token=self.api_token)
        except ClawVisionError: self._spool(f"/api/runs/{self.id}/lineage", payload)
        return self

    def log_checkpoint(self, path: str | Path, step: int, *, name: str | None = None) -> "Run":
        import base64
        source = Path(path)
        return self.log_artifact(name or source.name, {"base64": base64.b64encode(source.read_bytes()).decode("ascii"), "filename": source.name}, "checkpoint", step, "application/octet-stream")

    def __enter__(self) -> "Run":
        return self

    def __exit__(self, _exc_type, exc_value, _traceback) -> bool:
        self.finish() if exc_value is None else self.fail(str(exc_value))
        return False


def start_run(experiment: str, params: dict[str, Any] | None = None, *, name: str | None = None, base_url: str | None = None, buffer_size: int = 10, api_token: str | None = None, lineage: dict[str, Any] | None = None) -> Run:
    endpoint = base_url or os.environ.get("CLAWVISION_URL", "http://127.0.0.1:8787")
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    payload = {"id": run_id, "name": name or experiment, "params": params or {}, "source": "python-sdk"}
    run = Run(id=run_id, base_url=endpoint, buffer_size=max(1, buffer_size), api_token=api_token)
    try:
        _request(endpoint, "/api/runs", payload, api_token=api_token)
    except ClawVisionError:
        run._spool("/api/runs", payload)
    if lineage: run.log_lineage(**lineage)
    return run


def sync_offline(spool_dir: str | Path | None = None) -> dict[str, int]:
    root = Path(spool_dir) if spool_dir else _spool_root()
    result = {"sent": 0, "remaining": 0}
    for path in sorted(root.glob("*.jsonl")):
        remaining = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            try:
                _request(entry["baseUrl"], entry["path"], entry["payload"])
                result["sent"] += 1
            except ClawVisionError:
                remaining.append(line)
        if remaining:
            path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
            result["remaining"] += len(remaining)
        else:
            path.unlink(missing_ok=True)
    return result


__version__ = "0.22.0"

# Imported last to avoid a cycle while integrations subclasses the SDK Run type.
from .integrations import HuggingFaceCallback, KerasCallback, LightningCallback, TrainingCallback  # noqa: E402,F401
