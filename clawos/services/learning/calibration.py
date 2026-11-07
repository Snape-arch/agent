"""Calibration for bounded agent learning."""
from __future__ import annotations
import hashlib
import math
from typing import Any
from services.learning.common import _clamp, _stable_digest


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
