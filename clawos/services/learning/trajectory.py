"""Trajectory for bounded agent learning."""
from __future__ import annotations
from typing import Any
from services.learning.common import SENSITIVE_KEYS, _clamp, _stable_digest, _task_latency_ms
from services.learning.calibration import RewardCalibrator


class TrajectoryLearningService:
    """Capture task-bound decisions, outcomes, preferences, and exportable evidence."""

    def __init__(self, store):
        self.store = store

    def ensure_task(
        self,
        task_id: int,
        *,
        scenario: str = "general",
        task_context: dict[str, Any] | None = None,
        user_context: dict[str, Any] | None = None,
        environment_state: dict[str, Any] | None = None,
        policy_version: str = "",
    ) -> dict[str, Any]:
        return self.store.ensure_agent_trajectory(
            task_id,
            scenario=scenario,
            task_context=task_context,
            user_context=self._sanitize(user_context or {}),
            environment_state=self._sanitize(environment_state or {}),
            policy_version=policy_version,
        )

    def record_decision(
        self,
        task_id: int,
        *,
        state: dict[str, Any],
        action_type: str,
        action_name: str,
        action_payload: dict[str, Any] | None = None,
        policy_selection_id: int | None = None,
        behavior_propensity: float = 1.0,
        safety_violation: bool = False,
        candidate_set: list[str] | None = None,
        candidate_scores: dict[str, float] | None = None,
        policy_version: str = "",
        exploration_source: str = "",
        random_seed: int | None = None,
        context_digest: str = "",
    ) -> dict[str, Any]:
        candidates = [str(item) for item in (candidate_set or [])]
        scores = {
            str(key): round(float(value), 8)
            for key, value in (candidate_scores or {}).items()
        }
        if candidates and action_name not in candidates:
            raise ValueError("selected action must be present in candidate_set")
        if scores and set(scores) != set(candidates):
            raise ValueError("candidate_scores must cover the complete candidate_set")
        payload = self._sanitize(action_payload or {})
        payload["_policy_trace"] = {
            "schema": "clawos.counterfactual-decision.v1",
            "candidate_set": candidates,
            "candidate_scores": scores,
            "selected_action": action_name,
            "selected_probability": round(
                max(0.0, min(float(behavior_propensity), 1.0)), 8
            ),
            "policy_version": str(policy_version or ""),
            "exploration_source": str(exploration_source or ""),
            "random_seed": random_seed,
            "context_digest": str(context_digest or _stable_digest(state or {})),
            "complete": bool(
                candidates
                and scores
                and 0 < float(behavior_propensity or 0) <= 1
                and policy_version
            ),
        }
        return self.store.append_agent_trajectory_step(
            task_id,
            state=self._sanitize(state or {}),
            action_type=action_type,
            action_name=action_name,
            action_payload=payload,
            policy_selection_id=policy_selection_id,
            behavior_propensity=behavior_propensity,
            safety_violation=safety_violation,
        )

    def complete_task(self, task_id: int) -> dict[str, Any] | None:
        detail = self.store.get_task(task_id) or {}
        task = detail.get("task") or {}
        if not task:
            raise ValueError("task not found")
        status = str(task.get("status") or "")
        if status not in {
            "succeeded", "failed", "canceled", "cancelled", "interrupted"
        }:
            return None
        self.ensure_task(
            task_id,
            scenario=str((task.get("metadata") or {}).get("scenario") or "general"),
        )
        components, total = self.reward_from_task(task)
        return self.store.complete_agent_trajectory(
            task_id,
            outcome={
                "status": status,
                "error": str(task.get("error") or "")[:500],
                "result_present": bool((task.get("metadata") or {}).get("response_payload")),
            },
            reward_components=components,
            total_reward=total,
        )

    def reward_from_task(self, task: dict[str, Any]) -> tuple[dict[str, float], float]:
        metadata = task.get("metadata") or {}
        status = str(task.get("status") or "")
        success = 1.0 if status == "succeeded" else 0.0
        feedback_present = (
            "user_satisfaction" in metadata
            and metadata.get("user_satisfaction") is not None
        )
        satisfaction = (
            _clamp(metadata.get("user_satisfaction"))
            if feedback_present else None
        )
        latency_ms = _task_latency_ms(task)
        latency_budget = max(1.0, float(metadata.get("latency_budget_ms") or 3000))
        latency_cost = _clamp(latency_ms / latency_budget)
        resource_cost = _clamp(
            metadata.get("resource_cost")
            or metadata.get("token_cost_normalized")
            or 0
        )
        retry_cost = _clamp(max(0, int(task.get("attempt") or 1) - 1) / 3.0)
        safety_violation = 1.0 if metadata.get("safety_violation") else 0.0
        components = {
            "success": round(success, 6),
            "explicit_feedback": (
                round(satisfaction, 6) if satisfaction is not None else None
            ),
            "feedback_missing": 0.0 if feedback_present else 1.0,
            "evidence_correctness": (
                round(_clamp(metadata.get("evidence_correctness")), 6)
                if metadata.get("evidence_correctness") is not None else None
            ),
            "citation_validity": (
                round(_clamp(metadata.get("citation_validity")), 6)
                if metadata.get("citation_validity") is not None else None
            ),
            "latency_cost": round(latency_cost, 6),
            "resource_cost": round(resource_cost, 6),
            "retry_cost": round(retry_cost, 6),
            "safety_violation": round(safety_violation, 6),
        }
        total = RewardCalibrator.compose_reward(self.store, components)
        return components, total

    def record_preference(
        self,
        *,
        task_context: dict[str, Any],
        chosen: dict[str, Any],
        rejected: dict[str, Any],
        owner_id: str = "default",
        chosen_trajectory_id: int | None = None,
        rejected_trajectory_id: int | None = None,
        source: str = "explicit_user",
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not chosen or not rejected:
            raise ValueError("chosen and rejected examples are required")
        return self.store.create_agent_preference_pair(
            self._sanitize(task_context),
            self._sanitize(chosen),
            self._sanitize(rejected),
            owner_id=owner_id,
            chosen_trajectory_id=chosen_trajectory_id,
            rejected_trajectory_id=rejected_trajectory_id,
            source=source,
            confidence=confidence,
            metadata=self._sanitize(metadata or {}),
        )

    def export_dataset(
        self, *, group_name: str = "", limit: int = 5000
    ) -> dict[str, Any]:
        trajectories = self.store.list_agent_trajectories(
            status="completed", limit=limit
        )
        examples = self.store.list_agent_learning_examples(
            group_name=group_name, limit=limit
        )
        preferences = self.store.list_agent_preference_pairs(limit=limit)
        feedback = self.store.list_agent_feedback(limit=limit)
        sanitized = {
            "schema": "clawos.agent-learning.v1",
            "group_name": group_name,
            "trajectories": [self._sanitize(item) for item in trajectories],
            "decision_examples": [self._sanitize(item) for item in examples],
            "preference_pairs": [self._sanitize(item) for item in preferences],
            "explicit_feedback": [self._sanitize(item) for item in feedback],
        }
        sanitized["manifest"] = {
            "trajectory_count": len(trajectories),
            "decision_count": len(examples),
            "preference_count": len(preferences),
            "feedback_count": len(feedback),
            "digest": _stable_digest(sanitized),
        }
        return sanitized

    @classmethod
    def _sanitize(cls, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[truncated]"
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if any(sensitive in lowered for sensitive in SENSITIVE_KEYS):
                    result[str(key)] = "[redacted]"
                else:
                    result[str(key)] = cls._sanitize(item, depth + 1)
            return result
        if isinstance(value, list):
            return [cls._sanitize(item, depth + 1) for item in value[:200]]
        if isinstance(value, str):
            return value[:2000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:2000]
