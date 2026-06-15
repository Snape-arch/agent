"""Guarded Reflection improvement lifecycle."""

from __future__ import annotations


class ImprovementManager:
    """Approve, regression-test, publish, and roll back improvements."""

    TRANSITIONS = {
        "proposed": {"approved", "rejected"},
        "approved": {"testing", "rejected"},
        "testing": {"validated", "rejected"},
        "validated": {"published", "rejected"},
        "published": {"rolled_back"},
        "rejected": set(),
        "rolled_back": set(),
    }

    def __init__(self, store):
        self._store = store

    def transition(self, improvement_id, to_status, actor_id="system", reason=""):
        improvement = self._require(improvement_id)
        current = improvement["status"]
        if to_status not in self.TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid transition: {current} -> {to_status}")
        if to_status in {"published", "rolled_back"}:
            raise ValueError(f"use the dedicated {to_status} operation")
        return self._store.update_reflection_improvement(
            improvement_id,
            current,
            to_status,
            actor_id=actor_id,
            reason=reason,
        )

    def validate(self, improvement_id, baseline, candidate, thresholds=None, actor_id="system"):
        improvement = self._require(improvement_id)
        if improvement["status"] == "approved":
            improvement = self.transition(
                improvement_id, "testing", actor_id, "Regression validation started"
            )
        if improvement["status"] != "testing":
            raise ValueError("improvement must be approved or testing before validation")

        thresholds = thresholds or {}
        checks = []
        self._lower_is_better(
            checks, "latency_ms", baseline, candidate,
            float(thresholds.get("latency_regression_ratio", 0.20)),
        )
        self._lower_is_better(
            checks, "error_rate", baseline, candidate,
            float(thresholds.get("error_rate_regression_ratio", 0.0)),
        )
        self._higher_is_better(
            checks, "success_rate", baseline, candidate,
            float(thresholds.get("success_rate_regression", 0.0)),
        )
        self._higher_is_better(
            checks, "quality_score", baseline, candidate,
            float(thresholds.get("quality_regression", 0.0)),
        )
        passed = bool(checks) and all(check["passed"] for check in checks)
        result = {
            "passed": passed,
            "checks": checks,
            "thresholds": thresholds,
        }
        return self._store.update_reflection_improvement(
            improvement_id,
            "testing",
            "validated" if passed else "rejected",
            actor_id=actor_id,
            reason="Regression validation passed" if passed else "Regression validation failed",
            data=result,
            fields={
                "baseline_metrics": baseline,
                "candidate_metrics": candidate,
                "regression_result": result,
            },
        )

    def publish(self, improvement_id, actor_id="system", reason=""):
        return self._store.publish_reflection_improvement(
            improvement_id, actor_id=actor_id, reason=reason
        )

    def rollback(self, improvement_id, actor_id="system", reason=""):
        return self._store.rollback_reflection_improvement(
            improvement_id, actor_id=actor_id, reason=reason
        )

    def _require(self, improvement_id):
        improvement = self._store.get_reflection_improvement(improvement_id)
        if not improvement:
            raise ValueError("improvement not found")
        return improvement

    @staticmethod
    def _lower_is_better(checks, metric, baseline, candidate, tolerance):
        if metric not in baseline or metric not in candidate:
            return
        base = float(baseline[metric])
        actual = float(candidate[metric])
        limit = base * (1.0 + max(0.0, tolerance))
        checks.append({
            "metric": metric,
            "direction": "lower",
            "baseline": base,
            "candidate": actual,
            "limit": round(limit, 6),
            "passed": actual <= limit,
        })

    @staticmethod
    def _higher_is_better(checks, metric, baseline, candidate, tolerance):
        if metric not in baseline or metric not in candidate:
            return
        base = float(baseline[metric])
        actual = float(candidate[metric])
        limit = base - max(0.0, tolerance)
        checks.append({
            "metric": metric,
            "direction": "higher",
            "baseline": base,
            "candidate": actual,
            "limit": round(limit, 6),
            "passed": actual >= limit,
        })
