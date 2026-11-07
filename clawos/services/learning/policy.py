"""Policy for bounded agent learning."""
from __future__ import annotations
import hashlib
import math
import re
from typing import Any
from services.learning.common import SENSITIVE_KEYS, _stable_digest


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
