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
        min_examples: int = 30,
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
        required = max(30, int(min_examples))
        if len(examples) < required:
            raise ValueError(
                f"at least {required} completed trajectory decisions are required"
            )
        ordered = sorted(examples, key=lambda item: int(item["id"]))
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in ordered:
            groups.setdefault(self._split_group(item), []).append(item)
        group_names = sorted(groups)
        if len(group_names) < 5:
            raise ValueError(
                "at least 5 independent repository/task/session groups are "
                "required for group-disjoint training"
            )
        holdout_groups = {
            name for index, name in enumerate(group_names) if index % 5 == 4
        }
        holdout_ids = {
            int(item["id"]) for name in holdout_groups for item in groups[name]
        }
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
            "baseline_active_model_id": (self.store.get_agent_policy_model(group_name=group_name, status="active") or {}).get("id", 0),
            "heads": weights,
            "arm_names": sorted(arm_map),
            "training_example_ids": [
                int(item["id"]) for item in training
            ],
            "holdout_example_ids": [
                int(item["id"]) for item in holdout
            ],
            "split_groups": {
                "training": sorted(set(groups) - holdout_groups),
                "holdout": sorted(holdout_groups),
            },
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
            "group_count": len(group_names),
            "arm_sample_counts": counts,
            "train_mae": round(train_mae, 6),
            "holdout_mae": round(holdout_mae, 6),
            "algorithm": "hashed_linear_contextual_q_v0",
            "group_disjoint_holdout": True,
        }
        return self.store.create_agent_policy_model(
            group_name,
            self.encoder.dimension,
            payload,
            metrics,
            _stable_digest(data_manifest),
            trained_by=trained_by,
        )

    @staticmethod
    def _split_group(item: dict[str, Any]) -> str:
        task_id = str(item.get("task_id") or "").strip()
        session_id = str(item.get("session_id") or "").strip()
        repository = str(
            (item.get("environment_state") or {}).get("repository_id")
            or (item.get("selection_context") or {}).get("repository_id")
            or ""
        ).strip()
        return f"repo:{repository}" if repository else f"task:{task_id}|session:{session_id}"

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
        min_samples: int = 30,
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
        payload = model.get("weights") or {}
        holdout_ids = {
            int(item) for item in payload.get("holdout_example_ids") or []
        }
        training_ids = {
            int(item) for item in payload.get("training_example_ids") or []
        }
        if (
            not holdout_ids or not training_ids
            or not holdout_ids.isdisjoint(training_ids)
        ):
            raise ValueError(
                "candidate model lacks a valid group-disjoint evaluation split"
            )
        holdout = [
            item for item in ordered if int(item["id"]) in holdout_ids
        ]
        training = [
            item for item in ordered if int(item["id"]) in training_ids
        ]
        if (len(holdout) != len(holdout_ids) or len(training) != len(training_ids)
                or {network._split_group(item) for item in training}
                   & {network._split_group(item) for item in holdout}):
            raise ValueError("training/holdout evidence missing or group leakage detected; retrain")
        reward_means: dict[str, float] = {}
        for name in arm_map:
            values = [
                float(item["observed_reward"]) for item in training
                if item.get("action_name") == name
            ]
            reward_means[name] = self._mean(values)
        from services.advanced_policy_learning import RobustOffPolicyEvaluator

        decisions = []
        safety_violations = sum(bool(item.get("safety_violation")) for item in holdout)
        def candidate_policy(item, candidates):
            context = {
                **(item.get("task_context") or {}),
                **(item.get("selection_context") or {}),
                "scenario": item.get("scenario") or "general",
                "user": item.get("user_context") or {},
                "environment": item.get("environment_state") or {},
                "state": item.get("state") or {},
            }
            eligible = [arm_map[name] for name in candidates if name in arm_map]
            scores = network.score_model(model, context, eligible)
            if set(scores) != set(candidates):
                return {}
            chosen = max(scores, key=lambda name: (scores[name], name))
            matched = chosen == item["action_name"]
            decisions.append({"example_id": int(item["id"]), "candidate_action": chosen,
                              "logged_action": item["action_name"], "matched": matched})
            return {name: float(name == chosen) for name in candidates}

        report = RobustOffPolicyEvaluator().evaluate(
            holdout, candidate_policy, minimum_samples=max(30, int(min_samples)),
            reward_model=lambda record, name: reward_means.get(name, 0.0),
        )
        passed = bool(report["passed"] and safety_violations == 0)
        metrics = {
            "schema": "clawos.router-promotion.v2", "evidence_type": "offline_robust_ope",
            "sample_count": report["sample_count"],
            "baseline_mean_reward": report["baseline_mean"],
            "candidate_estimated_reward": report["doubly_robust"],
            "estimated_lift": report["doubly_robust"] - report["baseline_mean"],
            "confidence_lower_95": report["bootstrap"]["dr_lower_95"],
            "effective_sample_size": report["effective_sample_size"],
            "safety_violation_count": safety_violations, "passed": passed,
            "regression_tolerance": 0.02,  # Caller cannot loosen the common gate.
            "decision_digest": _stable_digest(decisions),
            "model_digest": _stable_digest(model["weights"]),
            "holdout_digest": _stable_digest(holdout),
            "arm_digest": _stable_digest(arms),
            "group_disjoint_holdout": True,
            "independent_reward_model": "training_arm_mean_v1",
            "training_sample_count": len(training), "robust_ope": report,
            "scope": "offline pure-network argmax; live hybrid-router lift is not established",
        }
        return self.store.evaluate_agent_policy_model(model_id, metrics, passed)

    def activate(
        self, model_id: int, *, confirmed: bool = False
    ) -> dict[str, Any]:
        with self.store.transaction():
            return self._activate_locked(model_id, confirmed=confirmed)

    def _activate_locked(self, model_id: int, *, confirmed: bool = False) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("explicit confirmed=true is required for activation")
        model = self.store.get_agent_policy_model(model_id)
        if not model or model.get("status") != "shadow":
            raise ValueError("only a shadow-evaluated model can be activated")
        metrics = model.get("evaluation_metrics") or {}
        if not metrics.get("passed") or metrics.get("schema") != "clawos.router-promotion.v2":
            raise ValueError("common robust offline trajectory gate did not pass; reevaluate this model")
        current = self.store.get_agent_policy_model(group_name=model['group_name'], status='active')
        if (model.get('weights') or {}).get('baseline_active_model_id', -1) != (current or {}).get('id', 0):
            raise ValueError("active router changed; retrain and evaluate against its new baseline")
        # Replay the immutable split against current logged outcomes/arms before
        # activation, so changed rewards or arm payloads cannot reuse stale proof.
        evaluated = self.evaluate(model_id)
        fresh = evaluated.get("evaluation_metrics") or {}
        if (not fresh.get("passed") or any(fresh.get(key) != metrics.get(key)
                for key in ("model_digest", "holdout_digest", "arm_digest"))):
            raise ValueError("evaluation evidence changed; review the fresh gate before activation")
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


class FeedbackLearningService:
    """Persist explicit user feedback and revise task-bound learning rewards."""

    ALLOWED_TYPES = {
        "binary", "rating", "score", "correction", "reason", "pairwise"
    }
    EVALUATOR_ORIGINS = {
        "human_user", "codex_evaluator", "automated_test",
    }

    def __init__(self, store):
        self.store = store

    def record(
        self,
        *,
        task_id: int,
        signal_type: str,
        value: Any = None,
        owner_id: str = "default",
        reason_category: str = "",
        correction: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        signal_type = str(signal_type or "").strip().lower()
        if signal_type not in self.ALLOWED_TYPES:
            raise ValueError(
                f"signal_type must be one of {sorted(self.ALLOWED_TYPES)}"
            )
        score = self._normalize_score(signal_type, value)
        normalized_metadata = TrajectoryLearningService._sanitize(
            metadata or {}
        )
        evaluator_origin = str(
            normalized_metadata.get("evaluator_origin") or "human_user"
        ).strip().lower()
        if evaluator_origin not in self.EVALUATOR_ORIGINS:
            raise ValueError(
                "evaluator_origin must be human_user, codex_evaluator, "
                "or automated_test"
            )
        if evaluator_origin == "codex_evaluator" and (
            not normalized_metadata.get("evidence_digest")
            or not normalized_metadata.get("evaluation_method")
        ):
            raise ValueError(
                "codex_evaluator feedback requires evidence_digest and "
                "evaluation_method"
            )
        normalized_metadata["evaluator_origin"] = evaluator_origin
        feedback = self.store.create_agent_feedback(
            task_id,
            signal_type,
            score=score,
            owner_id=owner_id,
            reason_category=reason_category,
            correction=TrajectoryLearningService._sanitize(correction or {}),
            metadata=normalized_metadata,
            explicit=True,
            idempotency_key=idempotency_key,
        )
        revised_rewards = []
        trajectory = self.store.get_agent_trajectory(task_id=task_id)
        if score is not None:
            self.store.update_task_metadata(
                task_id,
                {
                    "user_satisfaction": score,
                    "explicit_feedback_id": int(feedback["id"]),
                    "feedback_missing": False,
                },
                event_type="explicit_user_feedback",
            )
            revised_rewards = self.store.revise_policy_rewards_for_task(
                task_id, score, feedback["id"]
            )
            if trajectory and trajectory.get("status") == "completed":
                components = dict(trajectory.get("reward_components") or {})
                components["explicit_feedback"] = score
                components["feedback_missing"] = 0.0
                components["feedback_id"] = int(feedback["id"])
                total = RewardCalibrator.compose_reward(self.store, components)
                trajectory = self.store.complete_agent_trajectory(
                    task_id,
                    trajectory.get("outcome") or {},
                    components,
                    total,
                )
        return {
            "feedback": feedback,
            "trajectory": trajectory,
            "revised_policy_rewards": revised_rewards,
            "provenance": {
                "evaluator_origin": evaluator_origin,
                "counts_as_independent_human": evaluator_origin == "human_user",
                "counts_as_grounded_reward": evaluator_origin in {
                    "human_user", "codex_evaluator",
                },
            },
        }

    def quality_report(self) -> dict[str, Any]:
        quality = self.store.agent_learning_data_quality()
        quality["reward_calibration_ready"] = bool(
            quality["trajectory_count"] >= 50
            and quality["grounded_feedback_count"] >= 20
            and (
                not quality["arm_exposures"]
                or min(quality["arm_exposures"].values()) >= 10
            )
        )
        quality["preference_ranker_ready"] = PreferenceRanker.readiness(
            self.store
        )
        return quality

    @staticmethod
    def _normalize_score(signal_type: str, value: Any) -> float | None:
        if signal_type == "binary":
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"up", "like", "positive", "yes", "true"}:
                    return 1.0
                if normalized in {"down", "dislike", "negative", "no", "false"}:
                    return 0.0
                raise ValueError("binary feedback must be up/down or true/false")
            if isinstance(value, bool):
                return 1.0 if value else 0.0
            if value in {0, 1}:
                return float(value)
            raise ValueError("binary feedback must be 0 or 1")
        if signal_type == "rating":
            rating = float(value)
            if rating < 1 or rating > 5:
                raise ValueError("rating feedback must be between 1 and 5")
            return round((rating - 1.0) / 4.0, 6)
        if signal_type == "score":
            score = float(value)
            if score < 0 or score > 1:
                raise ValueError("score feedback must be between 0 and 1")
            return round(score, 6)
        if signal_type in {"correction", "reason", "pairwise"}:
            if value is None:
                return None
            score = float(value)
            if score < 0 or score > 1:
                raise ValueError("optional feedback score must be between 0 and 1")
            return round(score, 6)
        return None


class RewardCalibrator:
    """Fit and gate a constrained reward model against explicit user feedback."""

    FEATURE_NAMES = (
        "intercept", "success", "evidence_correctness", "citation_validity",
        "latency_cost", "resource_cost", "retry_cost",
    )
    DEFAULT_WEIGHTS = {
        "intercept": 0.0,
        "success": 0.55,
        "evidence_correctness": 0.15,
        "citation_validity": 0.10,
        "latency_cost": -0.10,
        "resource_cost": -0.05,
        "retry_cost": -0.05,
        "explicit_feedback_blend": 0.35,
    }

    def __init__(self, store):
        self.store = store

    @classmethod
    def compose_reward(
        cls, store, components: dict[str, Any]
    ) -> float:
        if float(components.get("safety_violation") or 0) > 0:
            return -1.0
        active = store.get_reward_calibration(status="active")
        weights = dict(cls.DEFAULT_WEIGHTS)
        if active:
            weights.update(active.get("weights") or {})
        vector = cls._component_vector(components)
        predicted = sum(
            float(weights.get(name, 0)) * value
            for name, value in zip(cls.FEATURE_NAMES, vector)
        )
        explicit = components.get("explicit_feedback")
        if explicit is not None and not float(
            components.get("feedback_missing") or 0
        ):
            blend = _clamp(weights.get("explicit_feedback_blend", 0.35))
            predicted = (1.0 - blend) * predicted + blend * _clamp(explicit)
        return round(max(-1.0, min(predicted, 1.0)), 6)

    def train(
        self,
        *,
        min_trajectories: int = 50,
        min_explicit_feedback: int = 20,
        min_arm_exposure: int = 10,
        trained_by: str = "system",
    ) -> dict[str, Any]:
        thresholds = {
            "min_trajectories": max(50, int(min_trajectories)),
            "min_explicit_feedback": max(20, int(min_explicit_feedback)),
            "min_arm_exposure": max(10, int(min_arm_exposure)),
        }
        quality = self.store.agent_learning_data_quality()
        failures = []
        if quality["trajectory_count"] < thresholds["min_trajectories"]:
            failures.append("trajectory_count")
        if quality["grounded_feedback_count"] < thresholds["min_explicit_feedback"]:
            failures.append("grounded_feedback_count")
        if quality["arm_exposures"] and min(
            quality["arm_exposures"].values()
        ) < thresholds["min_arm_exposure"]:
            failures.append("arm_exposure")
        if failures:
            raise ValueError(
                "reward calibration data gate not met: " + ", ".join(failures)
            )
        feedback = self.store.list_agent_feedback(
            explicit_only=True, limit=10000
        )
        latest_by_task = {}
        for item in feedback:
            if item.get("score") is not None:
                latest_by_task.setdefault(int(item["task_id"]), item)
        examples = []
        for task_id, item in sorted(latest_by_task.items()):
            trajectory = self.store.get_agent_trajectory(task_id=task_id)
            if not trajectory or trajectory.get("status") != "completed":
                continue
            examples.append({
                "task_id": task_id,
                "features": self._component_vector(
                    trajectory.get("reward_components") or {}
                ),
                "target": float(item["score"]),
            })
        if len(examples) < thresholds["min_explicit_feedback"]:
            raise ValueError("not enough task-distinct explicit feedback examples")
        training, holdout = self._split_by_task(examples)
        weights = [0.0, 0.4, 0.1, 0.1, -0.05, -0.05, -0.05]
        for epoch in range(300):
            rate = 0.08 / math.sqrt(epoch + 1)
            for item in training:
                prediction = sum(
                    weight * value
                    for weight, value in zip(weights, item["features"])
                )
                error = item["target"] - prediction
                for index, value in enumerate(item["features"]):
                    weights[index] += rate * (
                        error * value - 0.001 * weights[index]
                    )
                weights[1] = max(0.0, weights[1])
                weights[2] = max(0.0, weights[2])
                weights[3] = max(0.0, weights[3])
                weights[4] = min(0.0, weights[4])
                weights[5] = min(0.0, weights[5])
                weights[6] = min(0.0, weights[6])
        train_mae = self._mae(training, weights)
        holdout_mae = self._mae(holdout, weights)
        holdout_mean = (
            sum(item["target"] for item in training) / len(training)
            if training else 0.5
        )
        baseline_mae = (
            sum(abs(item["target"] - holdout_mean) for item in holdout)
            / len(holdout)
            if holdout else 1.0
        )
        weight_map = {
            name: round(value, 8)
            for name, value in zip(self.FEATURE_NAMES, weights)
        }
        weight_map["explicit_feedback_blend"] = 0.35
        manifest = [
            {"task_id": item["task_id"], "target": item["target"]}
            for item in examples
        ]
        metrics = {
            "algorithm": "constrained_linear_reward_calibration_v1",
            "sample_count": len(examples),
            "training_count": len(training),
            "holdout_count": len(holdout),
            "train_mae": round(train_mae, 6),
            "holdout_mae": round(holdout_mae, 6),
            "baseline_holdout_mae": round(baseline_mae, 6),
            "data_quality": quality,
        }
        return self.store.create_reward_calibration(
            weight_map, metrics, thresholds, _stable_digest(manifest),
            trained_by=trained_by,
        )

    def evaluate(self, calibration_id: int) -> dict[str, Any]:
        calibration = self.store.get_reward_calibration(calibration_id)
        if not calibration or calibration.get("status") != "candidate":
            raise ValueError("reward calibration candidate not found")
        training = calibration.get("training_metrics") or {}
        holdout_count = int(training.get("holdout_count") or 0)
        holdout_mae = float(training.get("holdout_mae") or 1)
        baseline_mae = float(training.get("baseline_holdout_mae") or 1)
        passed = bool(
            holdout_count >= 4
            and holdout_mae <= baseline_mae
            and holdout_mae <= 0.35
        )
        metrics = {
            "evidence_type": "task_disjoint_holdout",
            "holdout_count": holdout_count,
            "holdout_mae": holdout_mae,
            "baseline_holdout_mae": baseline_mae,
            "passed": passed,
        }
        return self.store.evaluate_reward_calibration(
            calibration_id, metrics, passed
        )

    def activate(
        self, calibration_id: int, *, confirmed: bool = False
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("explicit confirmed=true is required for activation")
        calibration = self.store.get_reward_calibration(calibration_id)
        if not calibration or calibration.get("status") != "shadow":
            raise ValueError("only a shadow reward calibration can be activated")
        if not (calibration.get("evaluation_metrics") or {}).get("passed"):
            raise ValueError("reward calibration gate did not pass")
        return self.store.activate_reward_calibration(calibration_id)

    @staticmethod
    def _component_vector(components: dict[str, Any]) -> list[float]:
        return [
            1.0,
            _clamp(components.get("success")),
            _clamp(components.get("evidence_correctness")),
            _clamp(components.get("citation_validity")),
            _clamp(components.get("latency_cost")),
            _clamp(components.get("resource_cost")),
            _clamp(components.get("retry_cost")),
        ]

    @staticmethod
    def _split_by_task(examples):
        training = []
        holdout = []
        for item in examples:
            bucket = int(
                hashlib.sha256(str(item["task_id"]).encode("utf-8")).hexdigest()[:8],
                16,
            ) % 5
            (holdout if bucket == 0 else training).append(item)
        if len(holdout) < 4:
            holdout = examples[-max(4, len(examples) // 5):]
            holdout_ids = {item["task_id"] for item in holdout}
            training = [
                item for item in examples if item["task_id"] not in holdout_ids
            ]
        return training, holdout

    @staticmethod
    def _mae(examples, weights):
        if not examples:
            return 0.0
        return sum(
            abs(
                item["target"]
                - sum(
                    weight * value
                    for weight, value in zip(weights, item["features"])
                )
            )
            for item in examples
        ) / len(examples)


class PreferenceRanker:
    """User-conditioned pairwise ranker with hard data and leakage gates."""

    CORE_SCENARIOS = ("learning", "research", "project", "office")

    def __init__(
        self, store, feature_dim: int = 128, epochs: int = 80
    ):
        self.store = store
        self.encoder = HashedFeatureEncoder(feature_dim)
        self.epochs = max(10, min(int(epochs), 500))

    @classmethod
    def readiness(cls, store) -> dict[str, Any]:
        pairs = store.list_agent_preference_pairs(limit=5000)
        scenario_counts = {scenario: 0 for scenario in cls.CORE_SCENARIOS}
        valid = 0
        for pair in pairs:
            if (
                pair.get("chosen") and pair.get("rejected")
                and float(pair.get("confidence") or 0) >= 0.5
            ):
                valid += 1
                scenario = str(
                    (pair.get("task_context") or {}).get("scenario") or ""
                ).lower()
                if scenario in scenario_counts:
                    scenario_counts[scenario] += 1
        ready = bool(
            valid >= 100
            and all(count >= 20 for count in scenario_counts.values())
        )
        return {
            "ready": ready,
            "valid_pair_count": valid,
            "required_pair_count": 100,
            "scenario_counts": scenario_counts,
            "required_per_scenario": 20,
        }

    def train(
        self, *, min_pairs: int = 100, min_per_scenario: int = 20,
        trained_by: str = "system",
    ) -> dict[str, Any]:
        required_pairs = max(100, int(min_pairs))
        required_scenario = max(20, int(min_per_scenario))
        pairs = [
            pair for pair in self.store.list_agent_preference_pairs(limit=5000)
            if pair.get("chosen") and pair.get("rejected")
            and float(pair.get("confidence") or 0) >= 0.5
        ]
        scenario_counts = {scenario: 0 for scenario in self.CORE_SCENARIOS}
        for pair in pairs:
            scenario = str(
                (pair.get("task_context") or {}).get("scenario") or ""
            ).lower()
            if scenario in scenario_counts:
                scenario_counts[scenario] += 1
        failures = []
        if len(pairs) < required_pairs:
            failures.append("preference_pair_count")
        if any(count < required_scenario for count in scenario_counts.values()):
            failures.append("scenario_coverage")
        contradiction_rate = self._contradiction_rate(pairs)
        if contradiction_rate >= 0.15:
            failures.append("contradiction_rate")
        if failures:
            raise ValueError(
                "preference ranker data gate not met: " + ", ".join(failures)
            )
        training, holdout = self._split_pairs(pairs)
        weights = [0.0] * self.encoder.dimension
        for epoch in range(self.epochs):
            rate = 0.12 / math.sqrt(epoch + 1)
            for pair in training:
                difference = self._difference(pair)
                self._logistic_update(weights, difference, 1.0, rate)
                self._logistic_update(
                    weights, [-value for value in difference], 0.0, rate
                )
        train_accuracy = self._accuracy(training, weights)
        holdout_accuracy = self._accuracy(holdout, weights)
        length_baseline = self._length_baseline_accuracy(holdout)
        manifest = [
            {
                "id": int(pair["id"]),
                "context": _stable_digest(pair.get("task_context") or {}),
            }
            for pair in pairs
        ]
        metrics = {
            "algorithm": "hashed_pairwise_logistic_ranker_v1",
            "sample_count": len(pairs),
            "training_count": len(training),
            "holdout_count": len(holdout),
            "scenario_counts": scenario_counts,
            "contradiction_rate": round(contradiction_rate, 6),
            "train_accuracy": round(train_accuracy, 6),
            "holdout_accuracy": round(holdout_accuracy, 6),
            "length_baseline_accuracy": round(length_baseline, 6),
            "task_disjoint_split": True,
        }
        return self.store.create_preference_ranker_model(
            self.encoder.dimension,
            [round(value, 10) for value in weights],
            metrics,
            _stable_digest(manifest),
            trained_by=trained_by,
        )

    def evaluate(self, model_id: int) -> dict[str, Any]:
        model = self.store.get_preference_ranker_model(model_id)
        if not model or model.get("status") != "candidate":
            raise ValueError("preference ranker candidate not found")
        metrics = model.get("training_metrics") or {}
        accuracy = float(metrics.get("holdout_accuracy") or 0)
        baseline = float(metrics.get("length_baseline_accuracy") or 0)
        holdout = int(metrics.get("holdout_count") or 0)
        passed = bool(
            holdout >= 20 and accuracy >= 0.55 and accuracy >= baseline + 0.02
        )
        evaluation = {
            "evidence_type": "task_disjoint_pairwise_holdout",
            "holdout_count": holdout,
            "accuracy": accuracy,
            "length_baseline_accuracy": baseline,
            "passed": passed,
        }
        return self.store.evaluate_preference_ranker_model(
            model_id, evaluation, passed
        )

    def activate(
        self, model_id: int, *, confirmed: bool = False
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("explicit confirmed=true is required for activation")
        model = self.store.get_preference_ranker_model(model_id)
        if not model or model.get("status") != "shadow":
            raise ValueError("only a shadow preference ranker can be activated")
        if not (model.get("evaluation_metrics") or {}).get("passed"):
            raise ValueError("preference ranker gate did not pass")
        return self.store.activate_preference_ranker_model(model_id)

    def rank(
        self,
        task_context: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if len(candidates) < 2:
            raise ValueError("at least two candidates are required")
        model = self.store.get_preference_ranker_model(status="active")
        if not model:
            raise ValueError("no active preference ranker")
        encoder = HashedFeatureEncoder(int(model["feature_dim"]))
        weights = model.get("weights") or []
        scored = []
        for index, candidate in enumerate(candidates):
            vector = encoder.encode(
                task_context or {},
                {"name": "response", "arm_type": "response", "payload": candidate},
            )
            score = sum(
                weight * value for weight, value in zip(weights, vector)
            )
            scored.append({
                "index": index,
                "score": round(score, 8),
                "candidate_digest": _stable_digest(candidate),
            })
        ranked = sorted(scored, key=lambda item: (-item["score"], item["index"]))
        confidence = (
            1.0 / (1.0 + math.exp(-(ranked[0]["score"] - ranked[1]["score"])))
        )
        return {
            "model_id": model["id"],
            "model_version": model["version"],
            "selected_index": ranked[0]["index"],
            "confidence": round(confidence, 6),
            "ranking": ranked,
        }

    def _difference(self, pair):
        context = {
            **(pair.get("task_context") or {}),
            "owner_id": pair.get("owner_id") or "default",
        }
        chosen = self.encoder.encode(
            context,
            {"name": "response", "arm_type": "response", "payload": pair["chosen"]},
        )
        rejected = self.encoder.encode(
            context,
            {"name": "response", "arm_type": "response", "payload": pair["rejected"]},
        )
        return [left - right for left, right in zip(chosen, rejected)]

    @staticmethod
    def _logistic_update(weights, vector, target, rate):
        raw = max(-20.0, min(sum(
            weight * value for weight, value in zip(weights, vector)
        ), 20.0))
        prediction = 1.0 / (1.0 + math.exp(-raw))
        error = target - prediction
        for index, value in enumerate(vector):
            if value:
                weights[index] += rate * (
                    error * value - 0.0005 * weights[index]
                )

    def _accuracy(self, pairs, weights):
        if not pairs:
            return 0.0
        return sum(
            int(sum(
                weight * value
                for weight, value in zip(weights, self._difference(pair))
            ) > 0)
            for pair in pairs
        ) / len(pairs)

    @staticmethod
    def _response_text(value):
        if isinstance(value, dict):
            for key in ("text", "content", "response", "output"):
                if value.get(key) is not None:
                    return str(value[key])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _length_baseline_accuracy(self, pairs):
        if not pairs:
            return 0.0
        return sum(
            int(
                len(self._response_text(pair["chosen"]))
                <= len(self._response_text(pair["rejected"]))
            )
            for pair in pairs
        ) / len(pairs)

    @staticmethod
    def _split_pairs(pairs):
        training = []
        holdout = []
        for pair in pairs:
            context = pair.get("task_context") or {}
            group_key = (
                context.get("task_id")
                or context.get("session_id")
                or _stable_digest(context)
            )
            bucket = int(
                hashlib.sha256(str(group_key).encode("utf-8")).hexdigest()[:8],
                16,
            ) % 5
            (holdout if bucket == 0 else training).append(pair)
        if len(holdout) < 20:
            holdout = pairs[-max(20, len(pairs) // 5):]
            holdout_ids = {int(pair["id"]) for pair in holdout}
            training = [
                pair for pair in pairs if int(pair["id"]) not in holdout_ids
            ]
        return training, holdout

    @staticmethod
    def _contradiction_rate(pairs):
        directions = {}
        contradictions = 0
        for pair in pairs:
            context = _stable_digest(pair.get("task_context") or {})
            chosen = _stable_digest(pair.get("chosen") or {})
            rejected = _stable_digest(pair.get("rejected") or {})
            canonical = (context, *sorted((chosen, rejected)))
            direction = chosen < rejected
            if canonical in directions and directions[canonical] != direction:
                contradictions += 1
            directions[canonical] = direction
        return contradictions / len(pairs) if pairs else 0.0


class AdvancedLearningReadiness:
    """Evidence-only gates for deeper Router, Trajectory RL, and behavior LoRA."""

    THRESHOLDS = {
        "deep_router": {
            "trajectory_count": 500,
            "preference_pair_count": 200,
            "explicit_feedback_count": 100,
            "min_arm_exposure": 50,
        },
        "trajectory_rl": {
            "trajectory_count": 2000,
            "decision_step_count": 10000,
            "feedback_coverage": 0.60,
            "valid_propensity_rate": 0.99,
        },
        "behavior_lora": {
            "trajectory_per_scenario": 500,
            "preference_per_scenario": 200,
        },
    }

    def __init__(self, store):
        self.store = store

    def report(self) -> dict[str, Any]:
        quality = self.store.agent_learning_data_quality()
        preferences = self.store.list_agent_preference_pairs(limit=5000)
        preference_scenarios = {}
        for pair in preferences:
            scenario = str(
                (pair.get("task_context") or {}).get("scenario") or "general"
            )
            preference_scenarios[scenario] = (
                preference_scenarios.get(scenario, 0) + 1
            )
        min_arm = (
            min(quality["arm_exposures"].values())
            if quality["arm_exposures"] else 0
        )
        deep = self.THRESHOLDS["deep_router"]
        deep_checks = {
            "trajectory_count": quality["trajectory_count"] >= deep["trajectory_count"],
            "preference_pair_count": quality["preference_pair_count"] >= deep["preference_pair_count"],
            "explicit_feedback_count": quality["grounded_feedback_count"] >= deep["explicit_feedback_count"],
            "min_arm_exposure": min_arm >= deep["min_arm_exposure"],
        }
        rl = self.THRESHOLDS["trajectory_rl"]
        rl_checks = {
            "trajectory_count": quality["trajectory_count"] >= rl["trajectory_count"],
            "decision_step_count": quality["decision_step_count"] >= rl["decision_step_count"],
            "feedback_coverage": quality["feedback_coverage"] >= rl["feedback_coverage"],
            "valid_propensity_rate": quality["valid_propensity_rate"] >= rl["valid_propensity_rate"],
            "conflicting_feedback": quality["conflicting_feedback_task_count"] == 0,
        }
        lora_threshold = self.THRESHOLDS["behavior_lora"]
        all_scenarios = sorted(set(
            quality["scenario_counts"]
        ) | set(preference_scenarios))
        lora_scenarios = {
            scenario: {
                "trajectory_count": quality["scenario_counts"].get(scenario, 0),
                "preference_pair_count": preference_scenarios.get(scenario, 0),
                "ready": bool(
                    quality["scenario_counts"].get(scenario, 0)
                    >= lora_threshold["trajectory_per_scenario"]
                    and preference_scenarios.get(scenario, 0)
                    >= lora_threshold["preference_per_scenario"]
                ),
            }
            for scenario in all_scenarios
        }
        return {
            "evidence_type": "observed_local_data_only",
            "online_rl_claimed": False,
            "quality": quality,
            "deep_router": {
                "ready": all(deep_checks.values()),
                "checks": deep_checks,
                "thresholds": deep,
            },
            "trajectory_rl": {
                "ready": all(rl_checks.values()),
                "checks": rl_checks,
                "thresholds": rl,
            },
            "behavior_lora": {
                "ready": bool(lora_scenarios)
                and all(item["ready"] for item in lora_scenarios.values()),
                "scenarios": lora_scenarios,
                "thresholds": lora_threshold,
            },
        }
