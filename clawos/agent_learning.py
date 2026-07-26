"""Offline-first trajectory learning and hierarchical policy routing for ClawOS."""

from __future__ import annotations

import hashlib
import json
import math
import re
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
    ) -> dict[str, Any]:
        return self.store.append_agent_trajectory_step(
            task_id,
            state=self._sanitize(state or {}),
            action_type=action_type,
            action_name=action_name,
            action_payload=self._sanitize(action_payload or {}),
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
        satisfaction = _clamp(metadata.get("user_satisfaction", 0.5))
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
        total = (
            0.45 * success
            + 0.25 * satisfaction
            - 0.12 * latency_cost
            - 0.08 * resource_cost
            - 0.10 * retry_cost
        )
        if safety_violation:
            total = -1.0
        components = {
            "success": round(success, 6),
            "satisfaction": round(satisfaction, 6),
            "latency_cost": round(latency_cost, 6),
            "resource_cost": round(resource_cost, 6),
            "retry_cost": round(retry_cost, 6),
            "safety_violation": round(safety_violation, 6),
        }
        return components, round(max(-1.0, min(total, 1.0)), 6)

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
        sanitized = {
            "schema": "clawos.agent-learning.v1",
            "group_name": group_name,
            "trajectories": [self._sanitize(item) for item in trajectories],
            "decision_examples": [self._sanitize(item) for item in examples],
            "preference_pairs": [self._sanitize(item) for item in preferences],
        }
        sanitized["manifest"] = {
            "trajectory_count": len(trajectories),
            "decision_count": len(examples),
            "preference_count": len(preferences),
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


class HashedFeatureEncoder:
    """Deterministic bounded feature encoder without a model-runtime dependency."""

    def __init__(self, dimension: int = 128):
        self.dimension = max(32, min(int(dimension), 2048))

    def encode(
        self,
        context: dict[str, Any],
        arm: dict[str, Any],
    ) -> list[float]:
        vector = [0.0] * self.dimension
        self._add(vector, "bias", 1.0)
        flattened: list[tuple[str, Any]] = []
        self._flatten("context", context or {}, flattened)
        self._flatten("arm", {
            "name": arm.get("name") or arm.get("arm_name") or "",
            "type": arm.get("arm_type") or "",
            "payload": arm.get("payload") or arm.get("action_payload") or {},
        }, flattened)
        for key, value in flattened[:400]:
            if isinstance(value, bool):
                self._add(vector, f"{key}={str(value).lower()}", 1.0)
            elif isinstance(value, (int, float)):
                self._add(vector, key, max(-10.0, min(float(value), 10.0)) / 10.0)
            else:
                text = str(value).strip().lower()
                if not text:
                    continue
                self._add(vector, f"{key}={text[:80]}", 1.0)
                for token in re.findall(r"[\w\u4e00-\u9fff]+", text)[:24]:
                    self._add(vector, f"{key}:token={token}", 0.25)
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _add(self, vector: list[float], feature: str, value: float) -> None:
        digest = hashlib.sha256(feature.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % self.dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * float(value)

    def _flatten(
        self, prefix: str, value: Any, output: list[tuple[str, Any]], depth: int = 0
    ) -> None:
        if depth > 4:
            return
        if isinstance(value, dict):
            for key in sorted(value):
                if any(sensitive in str(key).lower() for sensitive in SENSITIVE_KEYS):
                    continue
                self._flatten(
                    f"{prefix}.{key}", value[key], output, depth + 1
                )
        elif isinstance(value, list):
            for item in value[:20]:
                self._flatten(prefix, item, output, depth + 1)
        else:
            output.append((prefix, value))


class AgentSkillPolicyNetwork:
    """Small persistent contextual Q-router trained from completed trajectories."""

    def __init__(
        self,
        store,
        feature_dim: int = 128,
        learning_rate: float = 0.08,
        epochs: int = 60,
    ):
        self.store = store
        self.encoder = HashedFeatureEncoder(feature_dim)
        self.learning_rate = float(learning_rate)
        self.epochs = max(1, min(int(epochs), 500))

    def train(
        self,
        group_name: str,
        *,
        min_examples: int = 8,
        trained_by: str = "system",
    ) -> dict[str, Any]:
        arms, group = self.store.list_policy_arms(group_name)
        if not group or not arms:
            raise ValueError("policy group has no active arms")
        arm_map = {arm["name"]: arm for arm in arms}
        examples = [
            item for item in self.store.list_agent_learning_examples(group_name)
            if item.get("action_name") in arm_map
        ]
        required = max(4, int(min_examples))
        if len(examples) < required:
            raise ValueError(
                f"at least {required} completed trajectory decisions are required"
            )
        ordered = sorted(examples, key=lambda item: int(item["id"]))
        holdout_ids = {
            int(item["id"]) for index, item in enumerate(ordered)
            if index % 5 == 4
        }
        if not holdout_ids:
            holdout_ids.add(int(ordered[-1]["id"]))
        training = [
            item for item in ordered if int(item["id"]) not in holdout_ids
        ]
        holdout = [
            item for item in ordered if int(item["id"]) in holdout_ids
        ]
        weights = {
            name: [0.0] * self.encoder.dimension for name in arm_map
        }
        counts = {name: 0 for name in arm_map}
        for item in training:
            counts[item["action_name"]] += 1
        for epoch in range(self.epochs):
            rate = self.learning_rate / math.sqrt(epoch + 1)
            for item in training:
                arm_name = item["action_name"]
                vector = self._example_vector(item, arm_map[arm_name])
                prediction = self._dot(weights[arm_name], vector)
                target = max(-1.0, min(float(item["observed_reward"]), 1.0))
                error = target - prediction
                for index, value in enumerate(vector):
                    if value:
                        weights[arm_name][index] += rate * (
                            error * value - 0.0005 * weights[arm_name][index]
                        )
        train_mae = self._mae(training, arm_map, weights)
        holdout_mae = self._mae(holdout, arm_map, weights)
        payload = {
            "schema": "clawos.agent-skill-policy.v1",
            "heads": weights,
            "arm_names": sorted(arm_map),
        }
        data_manifest = [
            {
                "id": int(item["id"]),
                "arm": item["action_name"],
                "reward": round(float(item["observed_reward"]), 6),
            }
            for item in ordered
        ]
        metrics = {
            "sample_count": len(ordered),
            "training_count": len(training),
            "holdout_count": len(holdout),
            "arm_sample_counts": counts,
            "train_mae": round(train_mae, 6),
            "holdout_mae": round(holdout_mae, 6),
            "algorithm": "hashed_linear_contextual_q_v0",
        }
        return self.store.create_agent_policy_model(
            group_name,
            self.encoder.dimension,
            payload,
            metrics,
            _stable_digest(data_manifest),
            trained_by=trained_by,
        )

    def active_scores(
        self,
        group_name: str,
        context: dict[str, Any],
        arms: list[dict[str, Any]],
    ) -> dict[str, Any]:
        model = self.store.get_agent_policy_model(
            group_name=group_name, status="active"
        )
        if not model:
            return {"model": None, "scores": {}}
        return {
            "model": {
                "id": model["id"],
                "version": model["version"],
                "data_digest": model["data_digest"],
            },
            "scores": self.score_model(model, context, arms),
        }

    def score_model(
        self,
        model: dict[str, Any],
        context: dict[str, Any],
        arms: list[dict[str, Any]],
    ) -> dict[str, float]:
        encoder = HashedFeatureEncoder(int(model.get("feature_dim") or 128))
        heads = (model.get("weights") or {}).get("heads") or {}
        scores = {}
        for arm in arms:
            name = arm.get("name") or arm.get("arm_name")
            weights = heads.get(name)
            if not isinstance(weights, list) or len(weights) != encoder.dimension:
                continue
            vector = encoder.encode(context, arm)
            scores[str(name)] = round(
                max(-1.0, min(self._dot(weights, vector), 1.0)), 8
            )
        return scores

    def _example_vector(
        self, example: dict[str, Any], arm: dict[str, Any]
    ) -> list[float]:
        context = {
            **(example.get("task_context") or {}),
            **(example.get("selection_context") or {}),
            "scenario": example.get("scenario") or "general",
            "user": example.get("user_context") or {},
            "environment": example.get("environment_state") or {},
            "state": example.get("state") or {},
        }
        return self.encoder.encode(context, arm)

    def _mae(
        self,
        examples: list[dict[str, Any]],
        arms: dict[str, dict[str, Any]],
        weights: dict[str, list[float]],
    ) -> float:
        if not examples:
            return 0.0
        errors = []
        for item in examples:
            name = item["action_name"]
            vector = self._example_vector(item, arms[name])
            prediction = self._dot(weights[name], vector)
            errors.append(abs(float(item["observed_reward"]) - prediction))
        return sum(errors) / len(errors)

    @staticmethod
    def _dot(weights: list[float], vector: list[float]) -> float:
        return sum(weight * value for weight, value in zip(weights, vector))


class TrajectoryCritic:
    """Offline doubly-robust evaluator for candidate Agent Skill policies."""

    def __init__(self, store):
        self.store = store

    def evaluate(
        self,
        model_id: int,
        *,
        min_samples: int = 5,
        regression_tolerance: float = 0.02,
    ) -> dict[str, Any]:
        model = self.store.get_agent_policy_model(model_id)
        if not model:
            raise ValueError("agent policy model not found")
        if model["status"] not in {"candidate", "shadow"}:
            raise ValueError("only candidate or shadow models can be evaluated")
        network = AgentSkillPolicyNetwork(
            self.store, feature_dim=int(model["feature_dim"])
        )
        arms, group = self.store.list_policy_arms(model["group_name"])
        if not group or not arms:
            raise ValueError("policy group has no active arms")
        arm_map = {arm["name"]: arm for arm in arms}
        examples = [
            item for item in self.store.list_agent_learning_examples(
                model["group_name"]
            )
            if item.get("action_name") in arm_map
        ]
        ordered = sorted(examples, key=lambda item: int(item["id"]))
        holdout = [
            item for index, item in enumerate(ordered) if index % 5 == 4
        ]
        if len(holdout) < max(1, int(min_samples)):
            holdout = ordered[-max(1, int(min_samples)):]
        estimates = []
        observed_rewards = []
        importance_weights = []
        safety_violations = 0
        decisions = []
        for item in holdout:
            context = {
                **(item.get("task_context") or {}),
                **(item.get("selection_context") or {}),
                "scenario": item.get("scenario") or "general",
                "user": item.get("user_context") or {},
                "environment": item.get("environment_state") or {},
                "state": item.get("state") or {},
            }
            scores = network.score_model(model, context, arms)
            if not scores:
                continue
            chosen = max(scores, key=lambda name: (scores[name], name))
            logged = item["action_name"]
            behavior_q = float(scores.get(logged, 0))
            candidate_q = float(scores[chosen])
            observed = float(item["observed_reward"])
            propensity = max(
                0.000001, min(float(item.get("behavior_propensity") or 1), 1.0)
            )
            matched = chosen == logged
            weight = min(20.0, (1.0 / propensity) if matched else 0.0)
            doubly_robust = candidate_q + weight * (observed - behavior_q)
            estimates.append(max(-1.0, min(doubly_robust, 1.0)))
            observed_rewards.append(observed)
            importance_weights.append(weight)
            safety_violations += int(
                bool(item.get("safety_violation")) and matched
            )
            decisions.append({
                "example_id": int(item["id"]),
                "logged_action": logged,
                "candidate_action": chosen,
                "matched": matched,
                "behavior_propensity": round(propensity, 8),
            })
        candidate_mean = self._mean(estimates)
        baseline_mean = self._mean(observed_rewards)
        standard_error = self._standard_error(estimates)
        lower_95 = candidate_mean - 1.96 * standard_error
        weight_sum = sum(importance_weights)
        effective_sample_size = (
            (weight_sum * weight_sum) /
            max(sum(weight * weight for weight in importance_weights), 0.000001)
        )
        required = max(2, int(min_samples))
        passed = bool(
            len(estimates) >= required
            and safety_violations == 0
            and candidate_mean >= baseline_mean - float(regression_tolerance)
            and lower_95 >= baseline_mean - max(0.25, float(regression_tolerance))
        )
        metrics = {
            "evidence_type": "offline_doubly_robust",
            "sample_count": len(estimates),
            "baseline_mean_reward": round(baseline_mean, 6),
            "candidate_estimated_reward": round(candidate_mean, 6),
            "estimated_lift": round(candidate_mean - baseline_mean, 6),
            "standard_error": round(standard_error, 6),
            "confidence_lower_95": round(lower_95, 6),
            "effective_sample_size": round(effective_sample_size, 6),
            "safety_violation_count": safety_violations,
            "regression_tolerance": float(regression_tolerance),
            "passed": passed,
            "decision_digest": _stable_digest(decisions),
        }
        return self.store.evaluate_agent_policy_model(model_id, metrics, passed)

    def activate(
        self, model_id: int, *, confirmed: bool = False
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("explicit confirmed=true is required for activation")
        model = self.store.get_agent_policy_model(model_id)
        if not model or model.get("status") != "shadow":
            raise ValueError("only a shadow-evaluated model can be activated")
        if not (model.get("evaluation_metrics") or {}).get("passed"):
            raise ValueError("offline trajectory gate did not pass")
        return self.store.activate_agent_policy_model(model_id)

    def rollback(
        self, model_id: int, *, confirmed: bool = False
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("explicit confirmed=true is required for rollback")
        return self.store.rollback_agent_policy_model(model_id)

    @staticmethod
    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    @classmethod
    def _standard_error(cls, values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = cls._mean(values)
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        return math.sqrt(max(variance, 0.0) / len(values))
