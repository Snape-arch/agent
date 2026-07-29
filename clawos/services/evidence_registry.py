"""Durable, fail-closed evidence and learning-artifact registries."""

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class _DurableJsonStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()

    def read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.is_file():
                return {"schema": "clawos.registry.v1", "records": []}
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"schema": "clawos.registry.v1", "records": []}
            return value if isinstance(value, dict) else {
                "schema": "clawos.registry.v1", "records": []
            }

    def write(self, value: dict[str, Any]) -> None:
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


class CapabilityEvidenceRegistry:
    """Append-only capability evidence with expiry and integrity checks.

    Missing, malformed, expired, or unverifiable evidence is never interpreted
    as success. Hardware and real-data evidence must be recorded explicitly.
    """

    ALLOWED_STATUS = {"verified", "failed", "unknown"}

    def __init__(self, path: str | Path = "output/evidence/capabilities.json"):
        self._store = _DurableJsonStore(path)

    def record(
        self,
        capability: str,
        *,
        status: str,
        evidence_type: str,
        source: str,
        metrics: dict[str, Any] | None = None,
        artifact_digest: str = "",
        commit: str = "",
        environment: str = "",
        expires_at: str = "",
        truth_scope: str = "software",
        test_ids: list[str] | None = None,
        worktree_clean: bool | None = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to record evidence")
        name = str(capability or "").strip()
        state = str(status or "").strip().lower()
        if not name or state not in self.ALLOWED_STATUS:
            raise ValueError("capability and a valid status are required")
        payload = {
            "id": f"ev-{uuid.uuid4().hex}",
            "capability": name,
            "status": state,
            "evidence_type": str(evidence_type or "unknown"),
            "source": str(source or ""),
            "metrics": dict(metrics or {}),
            "artifact_digest": str(artifact_digest or ""),
            "commit": str(commit or ""),
            "environment": str(environment or ""),
            "observed_at": _iso(),
            "expires_at": str(expires_at or ""),
            "truth_scope": str(truth_scope or "software"),
            "test_ids": sorted({
                str(item).strip() for item in (test_ids or []) if str(item).strip()
            }),
            "worktree_clean": worktree_clean,
        }
        payload["record_digest"] = _digest(payload)
        value = self._store.read()
        value.setdefault("records", []).append(payload)
        self._store.write(value)
        return payload

    @staticmethod
    def validate(
        record: dict[str, Any], *, at: datetime | None = None,
        expected_commit: str = "",
    ) -> dict[str, Any]:
        item = dict(record or {})
        digest = item.pop("record_digest", "")
        integrity = bool(digest and digest == _digest(item))
        expired = False
        if item.get("expires_at"):
            try:
                expiry = datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
                expired = expiry <= (at or _now())
            except ValueError:
                expired = True
        acceptance = item.get("evidence_type") == "automated_acceptance"
        reproducible = bool(
            not acceptance or (
                item.get("artifact_digest")
                and item.get("commit")
                and item.get("test_ids")
                and item.get("worktree_clean") is True
            )
        )
        commit_matches = bool(
            not expected_commit or item.get("commit") == expected_commit
        )
        verified = bool(
            integrity and not expired and item.get("status") == "verified"
            and item.get("source") and item.get("evidence_type")
            and reproducible and commit_matches
        )
        return {
            **record,
            "integrity_valid": integrity,
            "expired": expired,
            "verified": verified,
            "reproducible": reproducible,
            "commit_matches": commit_matches,
        }

    def latest(self, *, expected_commit: str = "") -> dict[str, dict[str, Any]]:
        rows: dict[str, dict[str, Any]] = {}
        for raw in self._store.read().get("records", []):
            item = self.validate(raw, expected_commit=expected_commit)
            name = str(item.get("capability") or "")
            previous = rows.get(name)
            if name and (
                previous is None
                or str(item.get("observed_at") or "") >= str(previous.get("observed_at") or "")
            ):
                rows[name] = item
        return rows

    def list(self) -> list[dict[str, Any]]:
        return [self.validate(item) for item in self._store.read().get("records", [])]


class LearningArtifactRegistry:
    """Versioned candidate -> evaluated -> shadow -> active state machine."""

    TRANSITIONS = {
        "candidate": {"evaluated", "rejected"},
        "evaluated": {"shadow", "rejected"},
        "shadow": {"active", "rejected"},
        "active": {"rolled_back"},
        "rejected": set(),
        "rolled_back": set(),
    }

    def __init__(self, path: str | Path = "output/evidence/learning_artifacts.json"):
        self._store = _DurableJsonStore(path)

    def create(
        self, kind: str, payload: dict[str, Any], *,
        source_data_digest: str, confirmed: bool = False
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to persist a candidate")
        if not source_data_digest:
            raise ValueError("source_data_digest is required")
        value = self._store.read()
        versions = [
            int(item.get("version") or 0) for item in value.get("records", [])
            if item.get("kind") == kind
        ]
        item = {
            "id": f"la-{uuid.uuid4().hex}",
            "kind": str(kind),
            "version": max(versions or [0]) + 1,
            "state": "candidate",
            "payload": dict(payload or {}),
            "payload_digest": _digest(payload or {}),
            "source_data_digest": source_data_digest,
            "created_at": _iso(),
            "history": [{"state": "candidate", "at": _iso(), "evidence": {}}],
        }
        value.setdefault("records", []).append(item)
        self._store.write(value)
        return item

    def transition(
        self, artifact_id: str, state: str, *,
        evidence: dict[str, Any] | None = None, confirmed: bool = False
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required for state transitions")
        value = self._store.read()
        target = next(
            (item for item in value.get("records", []) if item.get("id") == artifact_id),
            None,
        )
        if target is None:
            raise KeyError("learning artifact not found")
        current = str(target.get("state") or "")
        requested = str(state or "")
        if requested not in self.TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid transition: {current} -> {requested}")
        proof = dict(evidence or {})
        if requested in {"evaluated", "shadow", "active"} and not proof.get("passed"):
            raise ValueError(f"{requested} requires passed evidence")
        if requested == "active":
            from .learning_governance import THRESHOLDS
        if requested == "active" and (
            not proof.get("human_approved")
            or int(proof.get("sample_count") or 0) < THRESHOLDS.activation_samples
            or int(proof.get("independent_sample_count") or 0)
            < THRESHOLDS.activation_samples
        ):
            raise ValueError("activation requires human approval and at least 30 samples")
        target["state"] = requested
        target.setdefault("history", []).append(
            {"state": requested, "at": _iso(), "evidence": proof}
        )
        self._store.write(value)
        return target

    def list(self, kind: str = "") -> list[dict[str, Any]]:
        rows = self._store.read().get("records", [])
        return [item for item in rows if not kind or item.get("kind") == kind]
