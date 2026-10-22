"""Reproducible, manually-labelled public OSS corpus evaluation."""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .coding_diagnostics_service import CodingDiagnosticsService


class CodingOSSCorpusBenchmark:
    """Evaluate only cases whose public source revision and labels are explicit."""

    SCHEMA = "clawos.coding-oss-corpus-evaluation.v1"
    LABELS = {"environment_failure", "test_failure", "implementation_failure", "requirements_failure"}

    def validate_manifest(self, manifest: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if manifest.get("schema") != "clawos.coding-oss-corpus.v1":
            errors.append("unsupported corpus schema")
        for index, case in enumerate(manifest.get("cases") or []):
            prefix = f"cases[{index}]"
            for key in ("id", "repository", "revision", "language", "path", "label", "command", "mutation", "repair"):
                if not case.get(key): errors.append(f"{prefix}.{key} is required")
            if case.get("label") not in self.LABELS: errors.append(f"{prefix}.label is invalid")
            if not str(case.get("repository") or "").startswith("https://"):
                errors.append(f"{prefix}.repository must be a public HTTPS URL")
            revision = str(case.get("revision") or "")
            if not (len(revision) == 40 and all(char in "0123456789abcdef" for char in revision.lower())):
                errors.append(f"{prefix}.revision must be a full 40-character commit SHA")
            for key in ("mutation", "repair"):
                value = case.get(key) or {}
                if not all(value.get(item) is not None for item in ("old_text", "new_text")):
                    errors.append(f"{prefix}.{key} requires old_text and new_text")
            review = case.get("human_review") or {}
            if review.get("status") != "approved" or not review.get("reviewer") or not review.get("reviewed_at"):
                errors.append(f"{prefix}.human_review approval evidence is required")
        return errors

    def evaluate(self, corpus_root: str | Path, manifest: dict[str, Any], *, bootstrap_samples: int = 2000) -> dict[str, Any]:
        errors = self.validate_manifest(manifest)
        if errors: raise ValueError("; ".join(errors))
        root = Path(corpus_root).expanduser().resolve()
        analyzer, rows = CodingDiagnosticsService(), []
        started = time.perf_counter()
        for case in manifest["cases"]:
            repo = root / str(case["id"]).split("::", 1)[0]
            if not (repo / ".git").exists():
                rows.append(self._skip(case, "repository checkout unavailable")); continue
            head = self._run(repo, ["git", "rev-parse", "HEAD"])
            if head["exit_code"] or head["stdout"].strip().lower() != str(case["revision"]).lower():
                rows.append(self._skip(case, "checkout revision does not match manifest")); continue
            path = repo / str(case["path"])
            if not path.is_file(): rows.append(self._skip(case, "mutation path unavailable")); continue
            original = path.read_text(encoding="utf-8")
            mutation = case["mutation"]
            if str(mutation["old_text"]) not in original:
                rows.append(self._skip(case, "reviewed mutation anchor does not match revision")); continue
            try:
                path.write_text(original.replace(str(mutation["old_text"]), str(mutation["new_text"]), 1), encoding="utf-8")
                failed = self._run(repo, list(map(str, case["command"])))
                analysis = analyzer.analyze(repo, [failed])
                repair = case["repair"]
                current = path.read_text(encoding="utf-8")
                if str(repair["old_text"]) not in current:
                    repaired = {"exit_code": 125, "stderr": "repair anchor missing", "stdout": "", "timed_out": False}
                else:
                    path.write_text(current.replace(str(repair["old_text"]), str(repair["new_text"]), 1), encoding="utf-8")
                    repaired = self._run(repo, list(map(str, case.get("repair_command") or case["command"])))
                rows.append({
                    "id": case["id"], "repository": case["repository"], "revision": case["revision"],
                    "language": case["language"], "expected": case["label"], "actual": analysis["failure_category"],
                    "classified_correctly": analysis["failure_category"] == case["label"],
                    "repair_success": repaired["exit_code"] == 0, "human_review": case["human_review"],
                    "failure_exit_code": failed["exit_code"], "repair_exit_code": repaired["exit_code"],
                })
            finally:
                path.write_text(original, encoding="utf-8")
        executed = [row for row in rows if not row.get("skipped")]
        class_values = [bool(row["classified_correctly"]) for row in executed]
        repair_values = [bool(row["repair_success"]) for row in executed]
        report = {
            "schema": self.SCHEMA, "manifest_digest": self._digest(manifest), "cases": rows,
            "metrics": {
                "total": len(rows), "executed": len(executed), "skipped": len(rows) - len(executed),
                "repositories": len({row["repository"] for row in executed}),
                "languages": sorted({row["language"] for row in executed}),
                "classification": self._metric(class_values, bootstrap_samples),
                "repair": self._metric(repair_values, bootstrap_samples),
                "leave_one_repository_out": self._loro(executed),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
            "truth_boundary": "Labels and mutations are human-reviewed; scores include only exact-revision public checkouts. LORO is held-repository observed performance, not a trained-model generalization claim.",
        }
        return report

    @classmethod
    def _metric(cls, values: list[bool], samples: int) -> dict[str, Any]:
        n, successes = len(values), sum(values)
        rate = successes / n if n else 0.0
        return {"successes": successes, "n": n, "rate": rate, "wilson_95": cls._wilson(successes, n), "bootstrap_95": cls._bootstrap(values, samples)}

    @staticmethod
    def _wilson(successes: int, n: int) -> list[float]:
        if not n: return [0.0, 0.0]
        z, p = 1.959963984540054, successes / n
        denominator = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denominator
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
        return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]

    @staticmethod
    def _bootstrap(values: list[bool], samples: int) -> list[float]:
        if not values: return [0.0, 0.0]
        rng, n = random.Random(20260812), len(values)
        rates = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(max(200, min(int(samples), 10000))))
        return [round(rates[int(.025 * (len(rates) - 1))], 6), round(rates[int(.975 * (len(rates) - 1))], 6)]

    @staticmethod
    def _loro(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for repository in sorted({row["repository"] for row in rows}):
            held = [row for row in rows if row["repository"] == repository]
            train = [row for row in rows if row["repository"] != repository]
            result.append({"held_out_repository": repository, "train_cases": len(train), "held_out_cases": len(held), "classification_accuracy": sum(row["classified_correctly"] for row in held) / len(held), "repair_success_rate": sum(row["repair_success"] for row in held) / len(held)})
        return result

    @staticmethod
    def _run(repo: Path, command: list[str]) -> dict[str, Any]:
        try:
            result = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            return {"exit_code": result.returncode, "stdout": result.stdout[-20000:], "stderr": result.stderr[-20000:], "timed_out": False}
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"exit_code": 127 if isinstance(exc, FileNotFoundError) else 124, "stdout": "", "stderr": str(exc), "timed_out": isinstance(exc, subprocess.TimeoutExpired)}

    @staticmethod
    def _skip(case: dict[str, Any], reason: str) -> dict[str, Any]:
        return {"id": case.get("id"), "repository": case.get("repository"), "language": case.get("language"), "skipped": True, "reason": reason}

    @staticmethod
    def _digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
