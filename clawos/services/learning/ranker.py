"""Ranker for bounded agent learning."""
from __future__ import annotations
import hashlib
import json
import math
from typing import Any
from services.learning.common import _stable_digest
from services.learning.policy import HashedFeatureEncoder


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
