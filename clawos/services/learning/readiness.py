"""Readiness for bounded agent learning."""
from __future__ import annotations
from typing import Any


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
