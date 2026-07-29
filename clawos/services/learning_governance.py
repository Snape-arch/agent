"""Shared, fail-closed learning promotion thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class LearningThresholds:
    shadow_samples: int = 30
    canary_samples: int = 30
    activation_samples: int = 30
    lightweight_router_samples: int = 30
    deep_router_trajectories: int = 500
    trajectory_rl_trajectories: int = 2000
    trajectory_rl_steps: int = 10_000
    preference_pairs: int = 100


THRESHOLDS = LearningThresholds()


def independent_evidence_ids(rows: Iterable[dict[str, Any]]) -> set[str]:
    """Return task/session/repository-bound evidence IDs.

    An aggregate snapshot or repeated observation without an independent
    identity deliberately contributes no promotion evidence.
    """

    identities: set[str] = set()
    for row in rows:
        metadata = dict(row.get("metadata") or {})
        evidence_id = str(metadata.get("evidence_id") or "").strip()
        task_id = str(metadata.get("task_id") or "").strip()
        session_id = str(metadata.get("session_id") or "").strip()
        repository_id = str(metadata.get("repository_id") or "").strip()
        identity = evidence_id or (
            f"task:{task_id}|session:{session_id}|repo:{repository_id}"
            if task_id and session_id
            else ""
        )
        if identity:
            identities.add(identity)
    return identities

