"""Behavioral benchmark and IDE/CI/review evidence contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class CodingOutcomeBenchmark:
    """Paired, blinded outcome gate for real patch-task reports."""

    def evaluate(
        self,
        cases: list[dict[str, Any]],
        *,
        minimum_cases: int = 30,
        bootstrap_samples: int = 1000,
        seed: int = 23,
    ) -> dict[str, Any]:
        valid = []
        failures: dict[str, int] = defaultdict(int)
        for case in cases:
            if case.get("origin") not in {"repository", "user_trajectory"}:
                failures["non_real_origin"] += 1
                continue
            if not case.get("blinded") or not case.get("hidden_test_digest"):
                failures["not_blinded"] += 1
                continue
            baseline = case.get("baseline") or {}
            candidate = case.get("candidate") or {}
            if not self._valid_run(baseline) or not self._valid_run(candidate):
                failures["invalid_run_evidence"] += 1
                continue
            valid.append({
                "id": str(case.get("id") or len(valid)),
                "baseline": self._score(baseline),
                "candidate": self._score(candidate),
                "repository": str(case.get("repository_id") or "unknown"),
            })
        required = max(30, int(minimum_cases or 30))
        deltas = [item["candidate"] - item["baseline"] for item in valid]
        interval = self._cluster_bootstrap(
            valid, max(200, min(int(bootstrap_samples), 10_000)), seed
        )
        passed = bool(
            len(valid) >= required
            and interval["lower_95"] >= 0
            and _mean(deltas) > 0
        )
        return {
            "schema": "clawos.coding-outcome-benchmark.v1",
            "evidence_type": "behavioral_ab",
            "blinded": True,
            "valid_case_count": len(valid),
            "required_case_count": required,
            "candidate_lift": round(_mean(deltas), 6),
            "bootstrap": interval,
            "failure_counts": dict(failures),
            "passed": passed,
            "activation_eligible": passed,
            "online_rl_claimed": False,
            "case_digest": _digest([item["id"] for item in valid]),
            "abort_reason": (
                "" if passed
                else "insufficient_real_blinded_cases" if len(valid) < required
                else "candidate_non_improvement"
            ),
        }

    @staticmethod
    def _valid_run(run: dict[str, Any]) -> bool:
        return bool(
            run.get("completed")
            and isinstance(run.get("hidden_tests_passed"), int)
            and isinstance(run.get("hidden_tests_total"), int)
            and run.get("hidden_tests_total", 0) > 0
            and run.get("patch_digest")
            and run.get("test_evidence_digest")
        )

    @staticmethod
    def _score(run: dict[str, Any]) -> float:
        correctness = run["hidden_tests_passed"] / run["hidden_tests_total"]
        return max(
            0.0,
            min(
                1.0,
                correctness
                - 0.05 * int(bool(run.get("safety_violation")))
                - min(0.10, float(run.get("normalized_cost") or 0) * 0.01),
            ),
        )

    @staticmethod
    def _cluster_bootstrap(
        rows: list[dict[str, Any]], samples: int, seed: int
    ) -> dict[str, Any]:
        if not rows:
            return {"samples": 0, "lower_95": 0.0, "upper_95": 0.0}
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in rows:
            grouped[item["repository"]].append(item)
        keys = list(grouped)
        generator = random.Random(seed)
        values = []
        for _ in range(samples):
            selected = []
            for _ in keys:
                selected.extend(grouped[keys[generator.randrange(len(keys))]])
            values.append(_mean([
                item["candidate"] - item["baseline"] for item in selected
            ]))
        values.sort()
        return {
            "samples": len(values),
            "cluster_count": len(keys),
            "lower_95": round(values[int(0.025 * (len(values) - 1))], 6),
            "upper_95": round(values[int(0.975 * (len(values) - 1))], 6),
        }


class CodingEvaluatorSummary:
    """Aggregate labelled evaluator samples without inflating real-user claims."""

    REAL_ORIGINS = {"repository", "user_trajectory"}

    @classmethod
    def summarize(
        cls, reports: list[dict[str, Any]], *, minimum_real_cases: int = 30
    ) -> dict[str, Any]:
        valid = [
            item for item in reports
            if item.get("model_execution_real") is True
            and item.get("evidence_digest")
            and item.get("evaluator_origin")
        ]
        real = [
            item for item in valid
            if item.get("repository_origin") in cls.REAL_ORIGINS
        ]
        controlled = [
            item for item in valid
            if item.get("repository_origin") == "controlled_repository_fixture"
        ]
        passed = sum(bool(item.get("sample_passed")) for item in valid)
        durations = [
            float(item.get("duration_ms") or 0) for item in valid
        ]
        evaluator_origins: dict[str, int] = defaultdict(int)
        for item in valid:
            evaluator_origins[str(item.get("evaluator_origin"))] += 1
        required = max(30, int(minimum_real_cases or 30))
        return {
            "schema": "clawos.coding-evaluator-summary.v1",
            "sample_count": len(valid),
            "passed_count": passed,
            "pass_rate": round(passed / len(valid), 6) if valid else 0.0,
            "mean_duration_ms": round(_mean(durations), 3),
            "controlled_fixture_count": len(controlled),
            "real_repository_case_count": len(real),
            "required_real_repository_cases": required,
            "evaluator_origin_counts": dict(evaluator_origins),
            "independent_human_user_count": len({
                str(item.get("evaluator_id"))
                for item in valid
                if item.get("evaluator_origin") == "human_user"
                and item.get("evaluator_id")
            }),
            "ope_eligible_count": sum(
                bool(item.get("eligible_for_ope")) for item in valid
            ),
            "real_benchmark_ready": len(real) >= required,
            "online_rl_claimed": False,
            "report_digest": _digest([
                str(item.get("evidence_digest")) for item in valid
            ]),
            "truth_boundary": (
                "Controlled fixtures and Codex evaluator feedback are real "
                "model executions but do not count as independent human users "
                "or real-repository benchmark cases."
            ),
        }


class IDEContextContract:
    """Normalize IDE state without treating editor text as system policy."""

    @staticmethod
    def normalize(repo_path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
        repo = Path(repo_path).expanduser().resolve()
        if not repo.is_dir():
            raise ValueError("repository does not exist")
        paths = []
        for raw in payload.get("open_files") or []:
            rel = str(raw).replace("\\", "/").strip("/")
            candidate = (repo / rel).resolve()
            try:
                candidate.relative_to(repo)
            except ValueError:
                continue
            if candidate.is_file():
                paths.append(rel)
        selection = dict(payload.get("selection") or {})
        return {
            "schema": "clawos.ide-context.v1",
            "repo_path": str(repo),
            "focus_paths": sorted(set(paths))[:50],
            "selection": {
                "path": str(selection.get("path") or ""),
                "start_line": max(1, int(selection.get("start_line") or 1)),
                "end_line": max(1, int(selection.get("end_line") or 1)),
                "text": str(selection.get("text") or "")[:20_000],
                "trust": "user_selected_repository_input",
            },
            "diagnostics": list(payload.get("diagnostics") or [])[:500],
            "editor": str(payload.get("editor") or "unknown"),
            "captured": True,
        }


class CodingReviewGate:
    """Require traceable CI plus independently attributable review findings."""

    @staticmethod
    def evaluate(
        changed_paths: list[str],
        ci_runs: list[dict[str, Any]],
        reviews: list[dict[str, Any]],
        *,
        verification_key: str = "",
    ) -> dict[str, Any]:
        scoped = {str(item).replace("\\", "/") for item in changed_paths}
        valid_ci = [
            item for item in ci_runs
            if item.get("command") and item.get("evidence_digest")
            and item.get("exit_code") == 0
            and CodingReviewGate._signature_valid(item, verification_key)
        ]
        valid_reviews = []
        for review in reviews:
            reviewer = str(review.get("reviewer_id") or "")
            findings = [
                item for item in review.get("findings") or []
                if str(item.get("path") or "").replace("\\", "/") in scoped
                and int(item.get("line") or 0) > 0
                and item.get("evidence")
            ]
            if reviewer and CodingReviewGate._signature_valid(review, verification_key):
                valid_reviews.append({
                    "reviewer_id": reviewer,
                    "decision": review.get("decision"),
                    "findings": findings,
                })
        blocking = [
            finding
            for review in valid_reviews
            for finding in review["findings"]
            if finding.get("severity") in {"critical", "high"}
        ]
        reviewer_count = len({item["reviewer_id"] for item in valid_reviews})
        passed = bool(valid_ci and reviewer_count >= 2 and not blocking)
        return {
            "schema": "clawos.coding-review-gate.v1",
            "passed": passed,
            "ci_evidence_count": len(valid_ci),
            "independent_reviewer_count": reviewer_count,
            "blocking_findings": blocking,
            "requires_human_review": True,
            "signed_provenance_required": bool(verification_key),
            "evidence_digest": _digest({
                "paths": sorted(scoped), "ci": valid_ci, "reviews": valid_reviews,
            }),
        }

    @staticmethod
    def sign(item: dict[str, Any], key: str) -> dict[str, Any]:
        if not key:
            raise ValueError("signing key is required")
        payload = {name: value for name, value in item.items() if name != "signature"}
        signature = hmac.new(
            key.encode("utf-8"),
            json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {**payload, "signature": signature}

    @staticmethod
    def _signature_valid(item: dict[str, Any], key: str) -> bool:
        if not key:
            return True
        signature = str(item.get("signature") or "")
        expected = CodingReviewGate.sign(item, key)["signature"]
        return bool(signature and hmac.compare_digest(signature, expected))
