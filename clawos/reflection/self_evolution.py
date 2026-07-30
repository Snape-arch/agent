"""Regression-gated self-evolution for low-risk ClawOS configuration."""

from __future__ import annotations

from collections import Counter


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
        "policy": "policy_materialization",
        "policy_materialization": "policy_materialization",
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
    QUALITY_LIMITS = {
        "user_retry_rate": 0.20,
        "cancel_rate": 0.15,
        "long_task_failure_rate": 0.10,
    }
    from services.learning_governance import THRESHOLDS
    MIN_CANARY_SAMPLES = THRESHOLDS.canary_samples
    MIN_ACTIVATION_SAMPLES = THRESHOLDS.activation_samples

    def __init__(self, store, benchmark_runner=None):
        self._store = store
        if benchmark_runner is None:
            from reflection.evolution_runtime import ExecutedEvolutionBenchmarkRunner
            benchmark_runner = ExecutedEvolutionBenchmarkRunner()
        self._benchmark_runner = benchmark_runner

    def create_run(
        self, target_type, target_key, baseline_payload, candidate_payload,
        benchmarks=None, title="", conclusion="", created_by="system",
    ):
        self._assert_allowed_target(target_type)
        if not str(target_key or "").strip():
            raise ValueError("target_key is required")
        if not isinstance(baseline_payload, dict):
            raise ValueError("baseline_payload and candidate_payload must be objects")
        if not candidate_payload:
            candidate_payload = self.generate_candidate(target_type, baseline_payload)
        if not isinstance(candidate_payload, dict):
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
            publish_decision="shadow_required" if passed else "reject",
            status="validated" if passed else "rejected",
            release_stage="validated" if passed else "rejected",
        )

    def start_shadow(self, run_id):
        run = self._require(run_id)
        self._assert_allowed_target(run["target_type"])
        gate = run.get("gate_result") or {}
        if not gate.get("passed"):
            raise ValueError("self-evolution run has not passed the regression gate")
        if run.get("status") not in {"validated", "shadow"}:
            raise ValueError("self-evolution run must be validated before shadow release")
        return self._store.update_self_evolution_run(
            run_id,
            status="shadow",
            release_stage="shadow",
            traffic_percent=0,
            publish_decision="canary_pending",
            conclusion="Candidate is running in shadow mode; active runtime policy is unchanged.",
        )

    def promote_canary(self, run_id, traffic_percent=10):
        run = self._require(run_id)
        self._assert_allowed_target(run["target_type"])
        if run.get("status") not in {"shadow", "canary"}:
            raise ValueError("self-evolution run must be in shadow before canary")
        if self._paired_quality_sample_count(run["id"]) < self.MIN_CANARY_SAMPLES:
            raise ValueError(
                f"canary requires at least {self.MIN_CANARY_SAMPLES} runtime quality samples"
            )
        if not self._quality_gate_passed(run):
            raise ValueError("quality signals block canary promotion")
        traffic = max(1.0, min(float(traffic_percent or 10), 50.0))
        return self._store.update_self_evolution_run(
            run_id,
            status="canary",
            release_stage="canary",
            traffic_percent=traffic,
            publish_decision="canary",
            conclusion=f"Candidate is in canary at {traffic:g}% traffic.",
        )

    def activate(self, run_id, actor_id="system", reason=""):
        run = self._require(run_id)
        self._assert_allowed_target(run["target_type"])
        if run.get("status") != "canary":
            raise ValueError("self-evolution run must complete canary before activation")
        if self._paired_quality_sample_count(run["id"]) < self.MIN_ACTIVATION_SAMPLES:
            raise ValueError(
                f"activation requires at least {self.MIN_ACTIVATION_SAMPLES} runtime quality samples"
            )
        if not self._quality_gate_passed(run):
            raise ValueError("quality signals block activation")
        return self._store.publish_self_evolution_run(
            run_id,
            actor_id=actor_id,
            reason=reason or "Self-evolution activated after shadow/canary gates",
        )

    def publish(self, run_id, actor_id="system", reason=""):
        return self.activate(run_id, actor_id=actor_id, reason=reason)

    def record_quality_signal(self, run_id, signal_type, value, metadata=None, created_by="system"):
        run = self._store.record_self_evolution_quality_signal(
            run_id, signal_type, value, metadata=metadata, created_by=created_by
        )
        if run.get("status") == "canary" and not self._quality_gate_passed(run):
            run = self._store.update_self_evolution_run(
                run_id,
                status="rolled_back",
                release_stage="stopped",
                traffic_percent=0,
                publish_decision="reject",
                conclusion=f"Canary stopped automatically after unhealthy {signal_type} signal.",
            )
        return run

    def attach_runtime_quality_snapshot(self, run_id, created_by="system"):
        snapshot = self._store.runtime_quality_snapshot()
        run = self._require(run_id)
        for signal, value in snapshot.items():
            if signal.endswith("_rate") or signal in {"retrieval_hit_rate"}:
                self._store.record_self_evolution_quality_signal(
                    run_id,
                    signal,
                    value,
                    metadata={"source": "runtime_snapshot", "target": run["target_key"]},
                    created_by=created_by,
                )
        return self._store.get_self_evolution_run(run_id)

    def run_automatic_benchmarks(self, run_id):
        run = self._require(run_id)
        evidence = self._benchmark_runner.run(
            run["target_type"],
            run["baseline_payload"],
            run["candidate_payload"],
        )
        evaluated = self.evaluate(
            run_id,
            benchmarks=evidence,
            conclusion="Worker generated frozen, core E2E, and retrieval evidence automatically.",
        )
        if evaluated.get("gate_result", {}).get("passed"):
            return self.start_shadow(run_id)
        return evaluated

    def propose_from_recent_reflections(
        self,
        target_type,
        target_key,
        baseline_payload,
        limit=50,
        created_by="reflection-miner",
    ):
        cards = self._store.list_reflection_cards(limit=max(3, min(int(limit), 200)))
        failures = [
            card for card in cards
            if str(card.get("outcome") or "") in {"failure", "partial"}
        ]
        if len(failures) < 3:
            raise ValueError("at least three recent failure/partial reflections are required")
        candidate = self.generate_candidate_from_failures(
            target_type,
            baseline_payload,
            failures,
        )
        return self.create_run(
            target_type,
            target_key,
            baseline_payload,
            candidate,
            title=f"Evidence-clustered evolution: {target_type}/{target_key}",
            conclusion="Candidate mined from repeated recent reflection failures.",
            created_by=created_by,
        )

    @classmethod
    def generate_candidate(cls, target_type, baseline_payload, strategy="balanced"):
        target = str(target_type or "")
        base = dict(baseline_payload or {})
        if target in {"prompt", "prompt_policy"}:
            text = str(base.get("system") or base.get("prompt") or "")
            improved = (
                text.strip()
                + "\n\nGround every answer in cited context, state uncertainty, "
                "and finish with a concise quality check."
            ).strip()
            return {**base, "system": improved, "strategy": strategy}
        if target in {"retrieval_params", "retrieval_policy"}:
            top_k = int(base.get("top_k") or base.get("recall_top_k") or 10)
            rerank = int(base.get("rerank_top_k") or 3)
            return {
                **base,
                "top_k": max(top_k, 30),
                "rerank_top_k": max(rerank, 5),
                "citation_aware": True,
                "strategy": strategy,
            }
        if target in {"report_template", "template_policy"}:
            return {
                **base,
                "version": int(base.get("version") or 1) + 1,
                "typography": "journal",
                "sections": [
                    "abstract",
                    "method",
                    "evidence",
                    "limitations",
                    "next_actions",
                ],
                "quality_gate": "citation_coverage_and_layout",
                "strategy": strategy,
            }
        if target in {"tool_routing_policy", "tool_policy", "routing_policy"}:
            return {
                **base,
                "confirm_high_risk": True,
                "prefer_citation_tools": True,
                "fallback_order": base.get("fallback_order") or ["local", "api", "manual_review"],
                "strategy": strategy,
            }
        return base

    @classmethod
    def generate_candidate_from_failures(
        cls, target_type, baseline_payload, reflections, strategy="evidence_clustered",
    ):
        """Generate a low-risk candidate from repeated, evidence-backed failures."""

        rows = [item for item in (reflections or []) if isinstance(item, dict)]
        if not rows:
            raise ValueError("at least one reflection is required")
        categories = Counter(
            str(item.get("failure_category") or "unknown") for item in rows
        )
        patterns = Counter()
        for item in rows:
            for pattern in item.get("patterns") or []:
                normalized = " ".join(str(pattern).lower().split())[:160]
                if normalized:
                    patterns[normalized] += 1
        candidate = cls.generate_candidate(target_type, baseline_payload, strategy=strategy)
        candidate["evidence_summary"] = {
            "reflection_count": len(rows),
            "failure_categories": dict(categories.most_common()),
            "repeated_patterns": [
                {"pattern": key, "count": count}
                for key, count in patterns.most_common(5)
                if count >= 2
            ],
        }
        if categories.get("parameter", 0):
            candidate["validate_inputs"] = True
        if categories.get("permission", 0):
            candidate["confirm_high_risk"] = True
        if categories.get("environment", 0):
            candidate["fallback_order"] = ["local", "manual_review"]
        return candidate

    def _quality_gate_passed(self, run):
        signals = run.get("quality_signals") or {}
        for signal, limit in self.QUALITY_LIMITS.items():
            item = signals.get(signal) or {}
            if float(item.get("latest", item.get("average", 0)) or 0) > limit:
                return False
        retrieval = signals.get("retrieval_hit_rate") or {}
        if retrieval and float(retrieval.get("latest", retrieval.get("average", 1)) or 0) < 0.80:
            return False
        rows = self._store.list_self_evolution_quality_signals(
            run["id"], limit=500
        )
        grouped = {}
        for row in rows:
            variant = str((row.get("metadata") or {}).get("variant") or "")
            if variant not in {"control", "candidate"}:
                continue
            grouped.setdefault(
                (str(row.get("signal_type") or ""), variant), []
            ).append(float(row.get("value") or 0))
        for signal in {
            key[0] for key in grouped
            if (key[0], "control") in grouped
            and (key[0], "candidate") in grouped
        }:
            control = sum(grouped[(signal, "control")]) / len(
                grouped[(signal, "control")]
            )
            candidate = sum(grouped[(signal, "candidate")]) / len(
                grouped[(signal, "candidate")]
            )
            if signal in self.QUALITY_LIMITS and candidate > control + 0.02:
                return False
            if signal == "retrieval_hit_rate" and candidate < control - 0.02:
                return False
        return True

    def _quality_sample_count(self, run_id):
        from services.learning_governance import independent_evidence_ids

        rows = self._store.list_self_evolution_quality_signals(run_id, limit=500)
        return len(independent_evidence_ids(rows))

    def _paired_quality_sample_count(self, run_id):
        from services.learning_governance import independent_evidence_ids

        rows = self._store.list_self_evolution_quality_signals(
            run_id, limit=500
        )
        control = independent_evidence_ids(
            row for row in rows
            if (row.get("metadata") or {}).get("variant") == "control"
        )
        candidate = independent_evidence_ids(
            row for row in rows
            if (row.get("metadata") or {}).get("variant") == "candidate"
        )
        return len(control & candidate)

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
            if name in {*cls.REQUIRED_BENCHMARKS, "policy_materialization"} and isinstance(result, dict):
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
        causal_required = any(
            "baseline_materialized" in ((benchmarks.get(name) or {}).get("metadata") or {})
            for name in cls.REQUIRED_BENCHMARKS
        )
        for name in cls.REQUIRED_BENCHMARKS:
            item = benchmarks.get(name) or {}
            baseline = item.get("baseline") or {}
            candidate = item.get("candidate") or {}
            metadata = item.get("metadata") or {}
            executed = (
                metadata.get("evidence_type") == "executed"
                and bool(metadata.get("baseline_report_digest"))
                and bool(metadata.get("candidate_report_digest"))
                and int(metadata.get("case_count") or 0) > 0
            )
            if not baseline or not candidate or not executed:
                if name not in missing:
                    missing.append(name)
                continue
            checks.extend(cls._compare_suite(name, baseline, candidate))

        if causal_required:
            policy = benchmarks.get("policy_materialization") or {}
            metadata = policy.get("metadata") or {}
            materialized = bool(
                metadata.get("baseline_materialized")
                and metadata.get("candidate_materialized")
                and metadata.get("baseline_execution_digest")
                and metadata.get("candidate_execution_digest")
            )
            changed = bool(metadata.get("causal_effect_observed"))
            if not materialized:
                missing.append("policy_materialization")
            checks.append({
                "benchmark": "policy_materialization",
                "metric": "candidate_materialized",
                "direction": "required_true",
                "baseline": bool(metadata.get("baseline_materialized")),
                "candidate": bool(metadata.get("candidate_materialized")),
                "passed": materialized,
            })
            checks.append({
                "benchmark": "policy_materialization",
                "metric": "causal_effect_observed",
                "direction": "required_true",
                "baseline": metadata.get("baseline_execution_digest", ""),
                "candidate": metadata.get("candidate_execution_digest", ""),
                "passed": changed,
            })

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
            "limit": max(base * 1.50, base + 150.0),
            "passed": actual <= max(base * 1.50, base + 150.0),
        }

    @staticmethod
    def _default_conclusion(gate):
        if gate.get("passed"):
            return "Candidate passed frozen, core E2E, and retrieval regression gates."
        missing = gate.get("missing_benchmarks") or []
        if missing:
            return "Candidate rejected because required benchmark evidence is incomplete."
        return "Candidate rejected because at least one benchmark metric regressed."
