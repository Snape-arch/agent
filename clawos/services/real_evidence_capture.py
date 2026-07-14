from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .competition_evidence_service import EVIDENCE_CHAIN_SCHEMA, REQUIRED_STAGES, sha256_file


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceRunBuilder:
    """Capture competition evidence while a real task is executing.

    The builder deliberately has no API for manufacturing a completed stage. A
    caller supplies the concrete records produced by tools, reviewers and
    durable storage, and ``finish`` preserves them in execution order.
    """

    def __init__(
        self,
        *,
        scenario: str,
        title: str,
        actor: str,
        provider: str,
        model: str,
        input_origin: str,
        source_uri: str,
        source_path: str | Path = "",
        license_name: str = "",
        run_id: str = "",
    ) -> None:
        self.started_at = _now()
        self._started = time.perf_counter()
        self._stages: dict[str, dict[str, Any]] = {}
        self._artifacts: list[dict[str, Any]] = []
        self._failures: list[dict[str, Any]] = []
        source_sha256 = ""
        source_bytes = 0
        if source_path and Path(source_path).is_file():
            source = Path(source_path).resolve()
            source_sha256 = sha256_file(source)
            source_bytes = source.stat().st_size
        self.run: dict[str, Any] = {
            "schema": "clawos.run.v1",
            "evidence_schema": EVIDENCE_CHAIN_SCHEMA,
            "run_id": run_id or f"real-{scenario}-{int(time.time())}-{uuid.uuid4().hex[:8]}",
            "run_type": "real_task_evidence",
            "title": str(title),
            "status": "running",
            "actor": str(actor),
            "scenario": str(scenario),
            "started_at": self.started_at,
            "completed_at": "",
            "inputs": {"source_uri": str(source_uri), "source_sha256": source_sha256, "source_bytes": source_bytes},
            "outputs": {},
            "metrics": {},
            "workflow": {"schema": EVIDENCE_CHAIN_SCHEMA, "evidence_chain": []},
            "tags": ["real-task", "competition-evidence"],
            "provenance": {
                "provider": str(provider),
                "model": str(model),
                "execution_mode": "live",
                "input_origin": str(input_origin),
                "source_uri": str(source_uri),
                "source_sha256": source_sha256,
                "source_bytes": source_bytes,
                "license": str(license_name),
                "captured_at": self.started_at,
            },
            "verification": {},
            "artifacts": self._artifacts,
            "evidence": [],
            "failure_cases": self._failures,
        }

    def capture(self, stage_id: str, records: list[dict[str, Any]], *, status: str = "completed") -> dict[str, Any]:
        if stage_id not in REQUIRED_STAGES:
            raise ValueError(f"unknown evidence stage: {stage_id}")
        if not records:
            raise ValueError(f"stage records are required: {stage_id}")
        stage = {
            "id": stage_id,
            "status": status,
            "captured_at": _now(),
            "records": records,
            "evidence": [self._record_digest(item) for item in records],
        }
        self._stages[stage_id] = stage
        return stage

    def add_artifact(self, artifact_id: str, kind: str, title: str, path: str | Path, **metadata: Any) -> dict[str, Any]:
        artifact = Path(path).expanduser().resolve()
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        item = {
            "artifact_id": str(artifact_id),
            "kind": str(kind),
            "title": str(title),
            "uri": str(artifact),
            "created_at": _now(),
            "metadata": {"sha256": sha256_file(artifact), "bytes": artifact.stat().st_size, **metadata},
        }
        self._artifacts.append(item)
        return item

    def add_failure(
        self,
        *,
        failure_id: str,
        category: str,
        reason: str,
        remediation: str,
        severity: str = "medium",
        **metadata: Any,
    ) -> dict[str, Any]:
        item = {
            "failure_id": str(failure_id),
            "category": str(category),
            "reason": str(reason),
            "severity": str(severity),
            "remediation": str(remediation),
            "metadata": metadata,
            "created_at": _now(),
        }
        self._failures.append(item)
        return item

    def finish(self, *, outputs: dict[str, Any] | None = None, metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        missing = [stage for stage in REQUIRED_STAGES if stage not in self._stages]
        if missing:
            raise ValueError("missing evidence stages: " + ", ".join(missing))
        completed_at = _now()
        duration_ms = max(1, round((time.perf_counter() - self._started) * 1000, 2))
        delegation = self._stages.get("subagent_delegation") or {}
        subagent_duration_ms = max(
            (float(item.get("subagent_run_duration_ms") or 0) for item in delegation.get("records") or []),
            default=0,
        )
        measured = {"duration_ms": duration_ms}
        if subagent_duration_ms:
            measured.update({
                "subagent_duration_ms": round(subagent_duration_ms, 2),
                "end_to_end_duration_ms": round(subagent_duration_ms + duration_ms, 2),
            })
        self.run.update({
            "status": "passed",
            "completed_at": completed_at,
            "outputs": outputs or {},
            "metrics": {**measured, **(metrics or {})},
        })
        self.run["workflow"]["evidence_chain"] = [self._stages[item] for item in REQUIRED_STAGES]
        self.run["workflow"]["captured_live"] = True
        return self.run

    @staticmethod
    def _record_digest(record: dict[str, Any]) -> str:
        import json

        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
