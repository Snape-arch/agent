"""Feedback for bounded agent learning."""
from __future__ import annotations
from typing import Any
from services.learning.ranker import PreferenceRanker
from services.learning.calibration import RewardCalibrator
from services.learning.trajectory import TrajectoryLearningService


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
