"""Offline-only policy evaluation and trajectory preference components.

These components never activate a policy.  They produce evidence for the
existing shadow/canary governance path and deliberately reject weak support.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from typing import Any, Callable


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


class CounterfactualTraceAudit:
    """Validate whether logged decisions are suitable for off-policy use."""

    @staticmethod
    def audit(records: list[dict[str, Any]]) -> dict[str, Any]:
        failures = defaultdict(int)
        valid = []
        arm_exposure: dict[str, int] = defaultdict(int)
        for record in records:
            trace = (
                (record.get("action_payload") or {}).get("_policy_trace")
                or record.get("policy_trace")
                or {}
            )
            candidates = [str(item) for item in trace.get("candidate_set") or []]
            scores = trace.get("candidate_scores") or {}
            selected = str(
                trace.get("selected_action")
                or record.get("action_name")
                or ""
            )
            propensity = trace.get(
                "selected_probability", record.get("behavior_propensity")
            )
            if not candidates:
                failures["missing_candidate_set"] += 1
                continue
            if selected not in candidates:
                failures["selection_outside_candidate_set"] += 1
                continue
            if set(scores) != set(candidates):
                failures["incomplete_candidate_scores"] += 1
                continue
            try:
                propensity = float(propensity)
            except (TypeError, ValueError):
                propensity = 0.0
            if not 0 < propensity <= 1:
                failures["invalid_propensity"] += 1
                continue
            if not trace.get("policy_version"):
                failures["missing_policy_version"] += 1
                continue
            arm_exposure[selected] += 1
            valid.append(record)
        count = len(records)
        return {
            "schema": "clawos.counterfactual-audit.v1",
            "record_count": count,
            "valid_count": len(valid),
            "valid_rate": round(len(valid) / count, 6) if count else 0.0,
            "failure_counts": dict(failures),
            "arm_exposure": dict(arm_exposure),
            "minimum_arm_exposure": min(arm_exposure.values()) if arm_exposure else 0,
            "ready": bool(count and len(valid) / count >= 0.99),
            "valid_record_digest": _digest([
                int(item.get("id") or index) for index, item in enumerate(valid)
            ]),
        }


class RobustOffPolicyEvaluator:
    """IPS/SNIPS/DR evaluator with bootstrap, overlap, and agreement gates."""

    def evaluate(
        self,
        records: list[dict[str, Any]],
        candidate_policy: Callable[[dict[str, Any], list[str]], dict[str, float]],
        *,
        bootstrap_samples: int = 400,
        seed: int = 17,
        minimum_ess: float = 20.0,
        minimum_overlap: float = 0.20,
        reward_model: Callable[[dict[str, Any], str], float] | None = None,
    ) -> dict[str, Any]:
        audit = CounterfactualTraceAudit.audit(records)
        arm_rewards: dict[str, list[float]] = defaultdict(list)
        group_arm_rewards: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for record in records:
            trace = (
                (record.get("action_payload") or {}).get("_policy_trace")
                or record.get("policy_trace")
                or {}
            )
            arm = str(trace.get("selected_action") or record.get("action_name") or "")
            try:
                reward_value = float(
                    record.get("observed_reward", record.get("reward", 0.0))
                )
                arm_rewards[arm].append(reward_value)
                group_arm_rewards[self._group(record)][arm].append(reward_value)
            except (TypeError, ValueError):
                continue
        global_reward = _mean([
            value for values in arm_rewards.values() for value in values
        ])
        arm_values = {
            arm: _mean(values) for arm, values in arm_rewards.items()
        }
        rows = []
        for record in records:
            trace = (
                (record.get("action_payload") or {}).get("_policy_trace")
                or record.get("policy_trace")
                or {}
            )
            candidates = [str(item) for item in trace.get("candidate_set") or []]
            logged = str(trace.get("selected_action") or record.get("action_name") or "")
            if not candidates or logged not in candidates:
                continue
            try:
                behavior = float(
                    trace.get("selected_probability", record.get("behavior_propensity"))
                )
                reward = float(
                    record.get("observed_reward", record.get("reward", 0.0))
                )
            except (TypeError, ValueError):
                continue
            if not 0 < behavior <= 1:
                continue
            probabilities = candidate_policy(record, candidates)
            if set(probabilities) != set(candidates):
                continue
            total = sum(max(0.0, float(value)) for value in probabilities.values())
            if total <= 0:
                continue
            normalized = {
                arm: max(0.0, float(value)) / total
                for arm, value in probabilities.items()
            }
            target = normalized.get(logged, 0.0)
            weight = min(50.0, target / behavior)
            group = self._group(record)
            cross_fit_values = {
                arm: self._leave_group_out_mean(
                    arm_rewards.get(arm, []),
                    group_arm_rewards.get(group, {}).get(arm, []),
                    global_reward,
                )
                for arm in candidates
            }
            q_logged = (
                float(reward_model(record, logged))
                if reward_model else cross_fit_values.get(logged, global_reward)
            )
            q_target = sum(
                normalized[arm] * (
                    float(reward_model(record, arm))
                    if reward_model else cross_fit_values.get(arm, global_reward)
                )
                for arm in candidates
            )
            rows.append({
                "ips": weight * reward,
                "weight": weight,
                "dr": q_target + weight * (reward - q_logged),
                "reward": reward,
                "overlap": int(target > 0),
                "timestamp": str(record.get("created_at") or ""),
                "cluster": str(
                    record.get("task_id")
                    or record.get("session_id")
                    or record.get("id")
                    or len(rows)
                ),
                "segment": str(
                    record.get("scenario")
                    or (record.get("task_context") or {}).get("scenario")
                    or "general"
                ),
                "cross_fit_group": group,
            })
        weights = [row["weight"] for row in rows]
        ips = _mean([row["ips"] for row in rows])
        snips = (
            sum(row["ips"] for row in rows) / sum(weights)
            if sum(weights) > 0 else 0.0
        )
        dr = _mean([row["dr"] for row in rows])
        baseline = _mean([row["reward"] for row in rows])
        ess = (
            sum(weights) ** 2 / max(sum(value * value for value in weights), 1e-12)
            if weights else 0.0
        )
        overlap = _mean([row["overlap"] for row in rows])
        bootstrap = self._bootstrap(rows, bootstrap_samples, seed)
        estimates = [ips, snips, dr]
        agreement_span = max(estimates) - min(estimates) if estimates else 0.0
        support_passed = bool(
            audit["ready"]
            and ess >= minimum_ess
            and overlap >= minimum_overlap
        )
        agreement_passed = agreement_span <= 0.25
        lower = bootstrap["dr_lower_95"]
        passed = bool(
            support_passed
            and agreement_passed
            and lower >= baseline - 0.02
        )
        temporal = self._temporal_holdout(rows)
        return {
            "schema": "clawos.robust-ope.v1",
            "evidence_type": "offline_only",
            "online_rl_claimed": False,
            "sample_count": len(rows),
            "baseline_mean": round(baseline, 6),
            "ips": round(ips, 6),
            "snips": round(snips, 6),
            "doubly_robust": round(dr, 6),
            "effective_sample_size": round(ess, 6),
            "overlap_rate": round(overlap, 6),
            "agreement_span": round(agreement_span, 6),
            "bootstrap": bootstrap,
            "temporal_holdout": temporal,
            "segments": self._segments(rows),
            "counterfactual_audit": audit,
            "reward_model": {
                "type": (
                    "external" if reward_model
                    else "leave_repository_or_task_group_out_arm_mean"
                ),
                "cross_fitted": not bool(reward_model),
                "group_count": len(group_arm_rewards),
            },
            "gates": {
                "support": support_passed,
                "estimator_agreement": agreement_passed,
                "non_regression_lower_bound": lower >= baseline - 0.02,
            },
            "passed": passed,
            "abort_reason": (
                "" if passed
                else "insufficient_support" if not support_passed
                else "estimator_disagreement" if not agreement_passed
                else "confidence_lower_bound_regressed"
            ),
        }

    @staticmethod
    def _group(record: dict[str, Any]) -> str:
        context = record.get("task_context") or {}
        return str(
            record.get("repository_id")
            or context.get("repository_id")
            or record.get("task_id")
            or record.get("session_id")
            or record.get("id")
            or "ungrouped"
        )

    @staticmethod
    def _leave_group_out_mean(
        all_values: list[float], group_values: list[float], fallback: float
    ) -> float:
        remaining = len(all_values) - len(group_values)
        if remaining <= 0:
            return fallback
        return (sum(all_values) - sum(group_values)) / remaining

    @staticmethod
    def _bootstrap(
        rows: list[dict[str, float]], samples: int, seed: int
    ) -> dict[str, float]:
        if not rows:
            return {"samples": 0, "dr_lower_95": 0.0, "dr_upper_95": 0.0}
        generator = random.Random(seed)
        estimates = []
        clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            clusters[str(row.get("cluster") or "")].append(row)
        keys = list(clusters)
        count = len(keys)
        for _ in range(max(100, min(int(samples), 5000))):
            sample = []
            for _ in range(count):
                sample.extend(clusters[keys[generator.randrange(count)]])
            estimates.append(_mean([item["dr"] for item in sample]))
        estimates.sort()
        low = estimates[int(0.025 * (len(estimates) - 1))]
        high = estimates[int(0.975 * (len(estimates) - 1))]
        return {
            "samples": len(estimates),
            "dr_lower_95": round(low, 6),
            "dr_upper_95": round(high, 6),
        }

    @staticmethod
    def _temporal_holdout(rows: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = sorted(rows, key=lambda item: item.get("timestamp") or "")
        cut = max(1, int(len(ordered) * 0.8))
        train = ordered[:cut]
        holdout = ordered[cut:]
        return {
            "train_count": len(train),
            "holdout_count": len(holdout),
            "train_reward": round(_mean([item["reward"] for item in train]), 6),
            "holdout_reward": round(_mean([item["reward"] for item in holdout]), 6),
            "holdout_dr": round(_mean([item["dr"] for item in holdout]), 6),
        }

    @staticmethod
    def _segments(rows: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("segment") or "general")].append(row)
        return {
            name: {
                "sample_count": len(items),
                "baseline_mean": round(_mean([item["reward"] for item in items]), 6),
                "doubly_robust": round(_mean([item["dr"] for item in items]), 6),
                "overlap_rate": round(_mean([item["overlap"] for item in items]), 6),
            }
            for name, items in sorted(grouped.items())
        }


class TrajectoryPreferenceRanker:
    """Transparent trajectory scorer trained from chosen/rejected workflows."""

    FEATURES = (
        "success", "explicit_feedback", "evidence_correctness",
        "citation_validity", "latency_cost", "resource_cost", "retry_cost",
        "safety_violation", "step_count",
    )

    def train(
        self,
        pairs: list[dict[str, Any]],
        *,
        epochs: int = 200,
        learning_rate: float = 0.05,
        minimum_pairs: int = 100,
    ) -> dict[str, Any]:
        if len(pairs) < minimum_pairs:
            return {
                "status": "blocked",
                "pair_count": len(pairs),
                "required_pairs": minimum_pairs,
                "online_rl_claimed": False,
            }
        ordered = sorted(pairs, key=lambda item: str(item.get("created_at") or ""))
        cut = max(1, int(len(ordered) * 0.8))
        training, holdout = ordered[:cut], ordered[cut:]
        weights = {name: 0.0 for name in self.FEATURES}
        for epoch in range(max(1, min(epochs, 1000))):
            rate = learning_rate / math.sqrt(epoch + 1)
            for pair in training:
                diff = self._difference(pair)
                margin = sum(weights[name] * diff[name] for name in self.FEATURES)
                gradient = 1.0 / (1.0 + math.exp(max(-30.0, min(30.0, margin))))
                for name in self.FEATURES:
                    weights[name] += rate * gradient * diff[name]
        accuracy = _mean([
            int(sum(weights[name] * self._difference(pair)[name] for name in self.FEATURES) > 0)
            for pair in holdout
        ])
        passed = bool(len(holdout) >= 20 and accuracy >= 0.55)
        return {
            "schema": "clawos.trajectory-ranker.v1",
            "status": "shadow" if passed else "rejected",
            "pair_count": len(pairs),
            "train_count": len(training),
            "holdout_count": len(holdout),
            "holdout_accuracy": round(accuracy, 6),
            "weights": {key: round(value, 8) for key, value in weights.items()},
            "model_digest": _digest(weights),
            "online_rl_claimed": False,
            "activation_requires_confirmation": True,
        }

    def _difference(self, pair: dict[str, Any]) -> dict[str, float]:
        chosen = pair.get("chosen") or {}
        rejected = pair.get("rejected") or {}
        return {
            name: float(chosen.get(name) or 0) - float(rejected.get(name) or 0)
            for name in self.FEATURES
        }


class OfflinePolicySandbox:
    """Produce AWR-style sample weights without mutating a runtime policy."""

    @staticmethod
    def advantage_weights(
        trajectories: list[dict[str, Any]],
        *,
        temperature: float = 0.5,
        maximum_weight: float = 20.0,
        minimum_trajectories: int = 2000,
        minimum_steps: int = 10000,
    ) -> dict[str, Any]:
        steps = sum(len(item.get("steps") or []) for item in trajectories)
        if len(trajectories) < minimum_trajectories or steps < minimum_steps:
            return {
                "schema": "clawos.offline-policy-sandbox.v1",
                "status": "blocked",
                "trajectory_count": len(trajectories),
                "decision_step_count": steps,
                "thresholds": {
                    "trajectory_count": minimum_trajectories,
                    "decision_step_count": minimum_steps,
                },
                "online_rl_claimed": False,
                "runtime_policy_mutated": False,
            }
        rewards = [float(item.get("total_reward") or 0) for item in trajectories]
        baseline = _mean(rewards)
        temp = max(0.05, float(temperature))
        rows = []
        for item, reward in zip(trajectories, rewards):
            advantage = reward - baseline
            weight = min(maximum_weight, math.exp(max(-20.0, min(20.0, advantage / temp))))
            rows.append({
                "trajectory_id": item.get("id"),
                "advantage": round(advantage, 8),
                "weight": round(weight, 8),
            })
        return {
            "schema": "clawos.offline-policy-sandbox.v1",
            "status": "candidate_dataset",
            "algorithm": "advantage_weighted_regression",
            "baseline_reward": round(baseline, 8),
            "samples": rows,
            "dataset_digest": _digest(rows),
            "online_rl_claimed": False,
            "runtime_policy_mutated": False,
            "next_gate": "offline_ope_then_shadow",
        }


class AdaptationReadiness:
    """Truthful gate for router, trajectory, preference and behavior adapters."""

    THRESHOLDS = {
        "skill_router": {"trajectories": 500, "task_families": 8},
        "trajectory_rl": {"trajectories": 2000, "decision_steps": 10000},
        "preference_ranker": {"explicit_pairs": 100, "users": 10},
        "behavior_adapter": {
            "demonstrations": 1000, "task_families": 8,
            "prompt_policy_plateau_weeks": 4,
        },
    }

    @classmethod
    def report(cls, metrics: dict[str, Any]) -> dict[str, Any]:
        result = {}
        for name, thresholds in cls.THRESHOLDS.items():
            observed = dict(metrics.get(name) or {})
            checks = {
                key: float(observed.get(key) or 0) >= value
                for key, value in thresholds.items()
            }
            result[name] = {
                "ready": all(checks.values()),
                "checks": checks,
                "observed": observed,
                "thresholds": thresholds,
            }
        return {
            "schema": "clawos.adaptation-readiness.v1",
            "components": result,
            "deep_training_ready": all(
                item["ready"] for item in result.values()
            ),
            "recommended_next": next(
                (name for name, item in result.items() if not item["ready"]),
                "offline_candidate_evaluation",
            ),
            "online_rl_claimed": False,
            "adapter_training_claimed": False,
        }
