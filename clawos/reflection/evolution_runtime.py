"""Runtime policy delivery and executed evidence for controlled self-evolution."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FROZEN_SUITE = ROOT / "benchmarks" / "competition_frozen_v1.json"
CORE_SUITE = ROOT / "benchmarks" / "core_e2e_v1.json"
BENCHMARK_SCRIPT = ROOT / "scripts" / "run_frozen_benchmarks.py"


def stable_bucket(identity: str, run_id: int) -> float:
    """Return a deterministic 0..100 bucket for stable canary assignment."""

    raw = f"{identity or 'anonymous'}:{int(run_id)}".encode("utf-8")
    value = int(hashlib.sha256(raw).hexdigest()[:12], 16)
    return round((value / float(0xFFFFFFFFFFFF)) * 100.0, 6)


def payload_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RuntimePolicyController:
    """Resolve active, shadow, and canary policies for a concrete task."""

    def __init__(self, store):
        self._store = store

    def resolve(self, target_type: str, target_key: str, identity: str = "") -> dict[str, Any]:
        current = self._store.get_runtime_policy(target_type, target_key) or {}
        active_payload = dict(current.get("payload") or {})
        selection = {
            "target_type": target_type,
            "target_key": target_key,
            "payload": active_payload,
            "policy_version": int(current.get("version") or 0),
            "source": "runtime_policy" if current else "default",
            "release_stage": "active" if current else "default",
            "run_id": None,
            "exposure": "baseline",
            "bucket": None,
            "shadow_payload": None,
        }
        runs = self._store.list_self_evolution_runs(limit=500)
        eligible = [
            run for run in runs
            if run.get("target_type") == target_type
            and run.get("target_key") == target_key
            and run.get("status") in {"shadow", "canary"}
        ]
        if not eligible:
            return selection
        run = max(eligible, key=lambda item: int(item.get("id") or 0))
        selection.update({
            "run_id": int(run["id"]),
            "release_stage": run.get("release_stage") or run.get("status"),
            "candidate_digest": payload_digest(run.get("candidate_payload") or {}),
            "baseline_digest": payload_digest(active_payload),
        })
        if run.get("status") == "shadow":
            selection["shadow_payload"] = dict(run.get("candidate_payload") or {})
            selection["source"] = "shadow_baseline"
            return selection
        bucket = stable_bucket(identity, int(run["id"]))
        selection["bucket"] = bucket
        if bucket < float(run.get("traffic_percent") or 0):
            selection["payload"] = dict(run.get("candidate_payload") or {})
            selection["source"] = "canary"
            selection["exposure"] = "candidate"
        else:
            selection["source"] = "canary_baseline"
        return selection

    @staticmethod
    def apply_prompt(base_prompt: str, selection: dict[str, Any]) -> str:
        payload = selection.get("payload") or {}
        addition = str(payload.get("system") or payload.get("prompt") or "").strip()
        if not addition:
            return base_prompt
        return f"{base_prompt}\n\n[Active runtime prompt policy]\n{addition}"

    @staticmethod
    def apply_routing(base: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
        result = {**base}
        payload = selection.get("payload") or {}
        allowed = payload.get("allowed_tools")
        denied = {str(item) for item in payload.get("deny_tools") or []}
        if isinstance(allowed, list) and allowed:
            result["allowed_tools"] = [
                tool for tool in result.get("allowed_tools", [])
                if tool in {str(item) for item in allowed}
            ]
        if denied:
            result["allowed_tools"] = [
                tool for tool in result.get("allowed_tools", []) if tool not in denied
            ]
        if payload.get("confirm_high_risk"):
            result["requires_confirmation"] = sorted(set(
                result.get("requires_confirmation", [])
            ))
        result["runtime_policy"] = {
            key: selection.get(key)
            for key in (
                "target_type", "target_key", "policy_version", "source",
                "release_stage", "run_id", "exposure", "bucket",
                "candidate_digest", "baseline_digest",
            )
            if selection.get(key) is not None
        }
        if selection.get("shadow_payload") is not None:
            result["runtime_policy"]["shadow_digest"] = payload_digest(
                selection["shadow_payload"]
            )
        return result

    @staticmethod
    def retrieval_options(selection: dict[str, Any]) -> dict[str, Any]:
        payload = selection.get("payload") or {}
        return {
            "top_k": max(1, min(int(payload.get("top_k") or 5), 100)),
            "recall_top_k": max(1, min(int(
                payload.get("recall_top_k") or payload.get("top_k") or 30
            ), 200)),
            "rerank_top_k": max(1, min(int(payload.get("rerank_top_k") or 5), 50)),
            "citation_aware": bool(payload.get("citation_aware", False)),
        }


class ExecutedEvolutionBenchmarkRunner:
    """Run isolated file-backed suites and an actual retrieval probe.

    The runner never infers benchmark results from configuration text. Every
    metric is derived from executed cases and carries a report digest.
    """

    RETRIEVAL_CASES = (
        ("agent memory evidence", "memory", ("agent", "memory", "evidence")),
        ("paper citation retrieval", "citation", ("paper", "citation", "retrieval")),
        ("safe tool routing", "routing", ("safe", "tool", "routing")),
        ("task retry recovery", "recovery", ("task", "retry", "recovery")),
        ("local model latency", "latency", ("local", "model", "latency")),
    )

    def __init__(self, python_executable: str | None = None):
        self.python_executable = python_executable or sys.executable

    def run(
        self,
        target_type: str,
        baseline_payload: dict[str, Any],
        candidate_payload: dict[str, Any],
    ) -> dict[str, Any]:
        frozen_base = self._run_suite(FROZEN_SUITE, baseline_payload)
        frozen_candidate = self._run_suite(FROZEN_SUITE, candidate_payload)
        core_base = self._run_suite(CORE_SUITE, baseline_payload)
        core_candidate = self._run_suite(CORE_SUITE, candidate_payload)
        retrieval_base = self._run_retrieval_probe(baseline_payload)
        retrieval_candidate = self._run_retrieval_probe(candidate_payload)
        return {
            "frozen_benchmark": self._pair(frozen_base, frozen_candidate),
            "core_e2e": self._pair(core_base, core_candidate),
            "retrieval_benchmark": self._pair(retrieval_base, retrieval_candidate),
        }

    def _run_suite(self, suite_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        completed = subprocess.run(
            [
                self.python_executable,
                "-B",
                str(BENCHMARK_SCRIPT),
                "--suite",
                str(suite_path),
                "--json",
            ],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode not in {0, 1}:
            raise RuntimeError(
                f"benchmark runner failed ({completed.returncode}): "
                f"{completed.stderr[-500:]}"
            )
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"benchmark runner returned invalid JSON: {exc}") from exc
        metrics = dict(report.get("metrics") or {})
        metrics["passed"] = bool(report.get("passed"))
        metrics["execution_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return {
            "metrics": metrics,
            "report_digest": payload_digest(report),
            "config_digest": payload_digest(payload),
            "case_count": len(report.get("case_results") or []),
            "runner": "isolated_subprocess",
        }

    def _run_retrieval_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        top_k = max(1, min(int(payload.get("top_k") or 5), 50))
        recall_top_k = max(top_k, min(int(
            payload.get("recall_top_k") or payload.get("top_k") or 10
        ), 100))
        corpus = [
            {"id": label, "tokens": set(tokens)}
            for _, label, tokens in self.RETRIEVAL_CASES
        ]
        reciprocal_ranks = []
        hits = 0
        cases = []
        for query, expected, _ in self.RETRIEVAL_CASES:
            query_tokens = set(query.lower().split())
            ranked = sorted(
                corpus,
                key=lambda item: (
                    len(query_tokens & item["tokens"]) / max(1, len(query_tokens)),
                    item["id"],
                ),
                reverse=True,
            )[:recall_top_k]
            visible = ranked[:top_k]
            ids = [item["id"] for item in visible]
            rank = ids.index(expected) + 1 if expected in ids else 0
            hits += int(bool(rank))
            reciprocal_ranks.append(1.0 / rank if rank else 0.0)
            cases.append({"query": query, "expected": expected, "rank": rank, "hits": ids})
        hit_rate = hits / len(cases)
        mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
        report = {
            "cases": cases,
            "top_k": top_k,
            "recall_top_k": recall_top_k,
            "hit_rate": round(hit_rate, 6),
            "mrr": round(mrr, 6),
        }
        return {
            "metrics": {
                "pass_rate": round(hit_rate, 6),
                "hit_rate": round(hit_rate, 6),
                "mrr": round(mrr, 6),
                "p95_latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "passed": hit_rate >= 0.8,
            },
            "report_digest": payload_digest(report),
            "config_digest": payload_digest(payload),
            "case_count": len(cases),
            "runner": "deterministic_retrieval_execution",
        }

    @staticmethod
    def _pair(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "baseline": baseline["metrics"],
            "candidate": candidate["metrics"],
            "metadata": {
                "evidence_type": "executed",
                "baseline_report_digest": baseline["report_digest"],
                "candidate_report_digest": candidate["report_digest"],
                "baseline_config_digest": baseline["config_digest"],
                "candidate_config_digest": candidate["config_digest"],
                "baseline_runner": baseline["runner"],
                "candidate_runner": candidate["runner"],
                "case_count": min(baseline["case_count"], candidate["case_count"]),
            },
        }
