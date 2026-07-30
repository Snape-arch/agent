"""Fail-closed product readiness across empirical, engineering, and learning gates."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ProductReadinessService:
    """Separate software closure from evidence that requires real usage or hardware."""

    def __init__(self, repository_root: str | Path):
        self.root = Path(repository_root).expanduser().resolve()

    def report(
        self,
        *,
        learning: dict[str, Any] | None = None,
        evaluator: dict[str, Any] | None = None,
        outcome_benchmark: dict[str, Any] | None = None,
        hardware: dict[str, Any] | None = None,
        ide_artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        learning = dict(learning or {})
        evaluator = dict(evaluator or {})
        outcome_benchmark = dict(outcome_benchmark or {})
        hardware = dict(hardware or {})
        ide_artifact = dict(ide_artifact or {})
        quality = dict(learning.get("quality") or {})

        software = self._software_contracts()
        p0_checks = {
            "minimum_real_repository_cases": (
                int(evaluator.get("real_repository_case_count") or 0) >= 30
            ),
            "paired_benchmark_lift": bool(outcome_benchmark.get("passed")),
            "reward_calibration_data": bool(
                quality.get("reward_calibration_ready")
            ),
            "target_hardware_acceptance": bool(
                hardware.get("passed")
                and int(hardware.get("task_count") or 0) >= 30
            ),
        }
        p1_checks = {
            **software,
            "signed_packaged_ide": bool(
                ide_artifact.get("signed")
                and ide_artifact.get("artifact_digest")
                and ide_artifact.get("compatibility_passed")
            ),
        }
        p2_checks = {
            "preference_ranker": bool(quality.get("preference_ranker_ready")),
            "deep_router": bool(
                (learning.get("deep_router") or {}).get("ready")
            ),
            "trajectory_rl": bool(
                (learning.get("trajectory_rl") or {}).get("ready")
            ),
            "behavior_lora": bool(
                (learning.get("behavior_lora") or {}).get("ready")
            ),
        }
        blocked = [
            f"{phase}.{name}"
            for phase, checks in (
                ("p0", p0_checks), ("p1", p1_checks), ("p2", p2_checks)
            )
            for name, passed in checks.items()
            if not passed
        ]
        return {
            "schema": "clawos.product-readiness.v1",
            "phases": {
                "p0_empirical": {
                    "ready": all(p0_checks.values()),
                    "checks": p0_checks,
                },
                "p1_product_engineering": {
                    "ready": all(p1_checks.values()),
                    "software_closed": all(software.values()),
                    "checks": p1_checks,
                },
                "p2_advanced_learning": {
                    "ready": all(p2_checks.values()),
                    "checks": p2_checks,
                },
            },
            "software_contracts_closed": all(software.values()),
            "product_ready": not blocked,
            "blocked": blocked,
            "observed": {
                "real_repository_case_count": int(
                    evaluator.get("real_repository_case_count") or 0
                ),
                "controlled_fixture_count": int(
                    evaluator.get("controlled_fixture_count") or 0
                ),
                "trajectory_count": int(quality.get("trajectory_count") or 0),
                "grounded_feedback_count": int(
                    quality.get("grounded_feedback_count") or 0
                ),
                "independent_human_user_count": int(
                    evaluator.get("independent_human_user_count") or 0
                ),
            },
            "online_rl_claimed": False,
            "truth_boundary": (
                "Software contracts may be closed by reproducible tests. Real "
                "repository lift, target-hardware acceptance, signed IDE "
                "distribution, advanced Router, Trajectory RL, and behavior "
                "LoRA remain false until their own observed evidence passes."
            ),
        }

    def _software_contracts(self) -> dict[str, bool]:
        workflow = self.root / ".github" / "workflows" / "clawos-ci.yml"
        requirements = self.root / "clawos" / "requirements-test.txt"
        extension = self.root / "clawos" / "integrations" / "vscode" / "extension.js"
        package = self.root / "clawos" / "integrations" / "vscode" / "package.json"
        router = self.root / "clawos" / "api" / "product_readiness.py"
        workflow_text = self._read(workflow)
        extension_text = self._read(extension)
        package_value = self._json(package)
        return {
            "hosted_ci_contract": bool(
                "unittest discover" in workflow_text
                and "node --check" in workflow_text
                and "requirements-test.txt" in workflow_text
            ),
            "deterministic_ci_dependencies": self._requirements_pinned(
                requirements
            ),
            "ide_preview_confirmation": bool(
                "showWarningMessage" in extension_text
                and "confirmed: false" in extension_text
                and "confirmed: true" in extension_text
            ),
            "ide_cancellation": bool(
                "AbortController" in extension_text
                and "withProgress" in extension_text
                and "isCancellationRequested" in extension_text
            ),
            "ide_source_check": (
                ((package_value.get("scripts") or {}).get("check"))
                == "node --check extension.js"
            ),
            "modular_readiness_api": router.is_file(),
        }

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return ""

    @classmethod
    def _json(cls, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(cls._read(path))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _requirements_pinned(cls, path: Path) -> bool:
        lines = [
            line.strip()
            for line in cls._read(path).splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return bool(lines) and all(
            re.fullmatch(r"[A-Za-z0-9_.-]+==[^=\s]+", line)
            for line in lines
        )
