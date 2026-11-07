"""Shared, pure helpers for learning records."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime
from typing import Any


SENSITIVE_KEYS = {
    "api_key", "authorization", "cookie", "credential", "password",
    "secret", "token",
}


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(float(value or 0), high))


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _task_latency_ms(task: dict[str, Any]) -> float:
    try:
        started = datetime.fromisoformat(
            str(task.get("started_at") or "").replace("Z", "+00:00")
        )
        completed = datetime.fromisoformat(
            str(task.get("completed_at") or "").replace("Z", "+00:00")
        )
        return max(0.0, (completed - started).total_seconds() * 1000.0)
    except (TypeError, ValueError):
        return float((task.get("metadata") or {}).get("duration_ms") or 0)
