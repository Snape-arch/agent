"""Regression-gated self-evolution for low-risk ClawOS configuration."""

from __future__ import annotations


class SelfEvolutionManager:
    """Create, evaluate, and publish self-evolution runs without changing code."""

    REQUIRED_BENCHMARKS = ("frozen_benchmark", "core_e2e", "retrieval_benchmark")
    BENCHMARK_ALIASES = {
        "frozen": "frozen_benchmark",
        "frozen_benchmark": "frozen_benchmark",
        "competition_frozen": "frozen_benchmark",
        "core": "core_e2e",
        "core_e2e": "core_e2e",
        "core_e2e_benchmark": "core_e2e",
        "retrieval": "retrieval_benchmark",
        "retrieval_benchmark": "retrieval_benchmark",
    }
    ALLOWED_TARGET_TYPES = {
        "prompt",
        "prompt_policy",
        "retrieval_params",
        "retrieval_policy",
        "report_template",
        "template_policy",
        "tool_routing_policy",
        "tool_policy",
        "routing_policy",
    }
    BLOCKED_TARGET_HINTS = (
        "code", "source", "python", "script", "module", "binary", "migration",
    )
    HIGHER_IS_BETTER = (
        "pass_rate", "success_rate", "quality_score", "score", "hit_rate",
        "mrr", "precision", "passed_count",
    )
    LOWER_IS_BETTER = (
        "failed_count", "error_rate", "latency_ms", "p50_latency_ms",
        "p95_latency_ms", "latency_p50_ms", "latency_p95_ms",
    )

    def __init__(self, store):
        self._store = store

    def create_run(
        self, target_type, target_key, baseline_payload, candidate_payload,
        benchmarks=None, title="", conclusion="", created_by="system",
    ):
        self._assert_allowed_target(target_type)
        if not str(target_key or "").strip():
            raise ValueError("target_key is required")
        if not isinstance(baseline_payload, dict) or not isinstance(candidate_payload, dict):
            raise ValueError("baseline_payload and candidate_payload must be objects")
        return self._store.create_self_evolution_run(
            title=title or f"Self-evolution: {target_type}/{target_key}",
            target_type=target_type,
            target_key=target_key,
            baseline_payload=baseline_payload,
            candidate_payload=candidate_payload,
            benchmarks=self._normalize_benchmarks(benchmarks or {}),
            conclusion=conclusion,
            created_by=created_by,
        )

    def evaluate(self, run_id, benchmarks=None, conclusion=""):
        run = self._require(run_id)
        self._assert_allowed_target(run["target_type"])
        evidence = self._normalize_benchmarks(benchmarks or run.get("benchmarks") or {})
        gate = self._evaluate_gate(evidence)
        passed = bool(gate["passed"])
        return self._store.update_self_evolution_run(
            run_id,
            benchmarks=evidence,
            gate_result=gate,
            conclusion=conclusion or self._default_conclusion(gate),
            publish_decision="publish" if passed else "reject",
            status="validated" if passed else "rejected",
        )

    def publish(self, run_id, actor_id="system", reason=""):
        run = self._require(run_id)
        self._assert_allowed_target(run["target_type"])
        gate = run.get("gate_result") or {}
        if not gate.get("passed"):
            raise ValueError("self-evolution run has not passed the regression gate")
        if run.get("status") != "validated" or run.get("publish_decision") != "publish":
            raise ValueError("self-evolution run is not approved for publish")
        return self._store.publish_self_evolution_run(
            run_id,
            actor_id=actor_id,
            reason=reason,
        )

    def _require(self, run_id):
        run = self._store.get_self_evolution_run(run_id)
        if not run:
            raise ValueError("self-evolution run not found")
        return run

    @classmethod
    def _assert_allowed_target(cls, target_type):
        target = str(target_type or "").strip()
        lowered = target.lower()
        if target not in cls.ALLOWED_TARGET_TYPES:
            raise ValueError(
                "self-evolution can only publish low-risk config targets: "
                "prompt, retrieval_params, report_template, tool_routing_policy"
            )
        if any(hint in lowered for hint in cls.BLOCKED_TARGET_HINTS):
            raise ValueError("self-evolution is not allowed to change code or executable assets")

    @classmethod
    def _normalize_benchmarks(cls, benchmarks):
        normalized = {}
        for raw_name, result in (benchmarks or {}).items():
            name = cls.BENCHMARK_ALIASES.get(str(raw_name), str(raw_name))
            if name in cls.REQUIRED_BENCHMARKS and isinstance(result, dict):
                normalized[name] = {
                    "baseline": cls._extract_metrics(result.get("baseline", {})),
                    "candidate": cls._extract_metrics(result.get("candidate", {})),
                    "metadata": result.get("metadata", {}),
                }
        return normalized

    @classmethod
    def _evaluate_gate(cls, benchmarks):
        checks = []
        missing = [name for name in cls.REQUIRED_BENCHMARKS if name not in benchmarks]
        for name in cls.REQUIRED_BENCHMARKS:
            item = benchmarks.get(name) or {}
            baseline = item.get("baseline") or {}
            candidate = item.get("candidate") or {}
            if not baseline or not candidate:
                if name not in missing:
                    missing.append(name)
                continue
            checks.extend(cls._compare_suite(name, baseline, candidate))

        passed = not missing and bool(checks) and all(check["passed"] for check in checks)
        return {
            "passed": passed,
            "required_benchmarks": list(cls.REQUIRED_BENCHMARKS),
            "missing_benchmarks": missing,
            "checks": checks,
        }

    @classmethod
    def _compare_suite(cls, suite_name, baseline, candidate):
        checks = []
        if "passed" in candidate:
            checks.append({
                "benchmark": suite_name,
                "metric": "passed",
                "direction": "required_true",
                "baseline": bool(baseline.get("passed")),
                "candidate": bool(candidate.get("passed")),
                "passed": bool(candidate.get("passed")),
            })
        for metric in sorted(set(baseline) & set(candidate)):
            if metric == "passed":
                continue
            if metric.startswith("recall_at_") or metric.startswith("precision_at_"):
                checks.append(cls._higher_check(suite_name, metric, baseline, candidate))
            elif metric in cls.HIGHER_IS_BETTER:
                checks.append(cls._higher_check(suite_name, metric, baseline, candidate))
            elif metric in cls.LOWER_IS_BETTER:
                checks.append(cls._lower_check(suite_name, metric, baseline, candidate))
        return [check for check in checks if check]

    @staticmethod
    def _extract_metrics(value):
        if not isinstance(value, dict):
            return {}
        metrics = value.get("metrics") if isinstance(value.get("metrics"), dict) else {}
        extracted = {**metrics}
        for key, item in value.items():
            if key not in {"metrics", "cases", "case_results", "metadata"}:
                extracted[key] = item
        return extracted

    @staticmethod
    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _higher_check(cls, suite_name, metric, baseline, candidate):
        base = cls._number(baseline.get(metric))
        actual = cls._number(candidate.get(metric))
        if base is None or actual is None:
            return None
        return {
            "benchmark": suite_name,
            "metric": metric,
            "direction": "higher_or_equal",
            "baseline": base,
            "candidate": actual,
            "passed": actual >= base,
        }

    @classmethod
    def _lower_check(cls, suite_name, metric, baseline, candidate):
        base = cls._number(baseline.get(metric))
        actual = cls._number(candidate.get(metric))
        if base is None or actual is None:
            return None
        return {
            "benchmark": suite_name,
            "metric": metric,
            "direction": "lower_or_equal",
            "baseline": base,
            "candidate": actual,
            "passed": actual <= base,
        }

    @staticmethod
    def _default_conclusion(gate):
        if gate.get("passed"):
            return "Candidate passed frozen, core E2E, and retrieval regression gates."
        missing = gate.get("missing_benchmarks") or []
        if missing:
            return "Candidate rejected because required benchmark evidence is incomplete."
        return "Candidate rejected because at least one benchmark metric regressed."
