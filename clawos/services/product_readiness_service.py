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
        sandbox_artifact: dict[str, Any] | None = None,
        restricted_token_artifact: dict[str, Any] | None = None,
        egress_proxy_artifact: dict[str, Any] | None = None,
        recovery_artifact: dict[str, Any] | None = None,
        recovery_soak_artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        learning = dict(learning or {})
        evaluator = dict(evaluator or {})
        outcome_benchmark = dict(outcome_benchmark or {})
        hardware = dict(hardware or {})
        ide_artifact = dict(ide_artifact or {})
        sandbox_artifact = dict(sandbox_artifact or {})
        restricted_token_artifact = dict(restricted_token_artifact or {})
        egress_proxy_artifact = dict(egress_proxy_artifact or {})
        recovery_artifact = dict(recovery_artifact or {})
        recovery_soak_artifact = dict(recovery_soak_artifact or {})
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
                and ide_artifact.get("trusted_publisher")
            ),
            "os_sandbox_backend_probe": bool(
                sandbox_artifact.get("passed")
                and sandbox_artifact.get("os_enforced")
            ),
            "production_os_sandbox": bool(
                sandbox_artifact.get("production_sandbox_ready")
                and (
                    restricted_token_artifact.get("appcontainer") or {}
                ).get("enabled")
                and restricted_token_artifact.get("filesystem_read_isolated")
                and egress_proxy_artifact.get("host_enforced")
            ),
            "restricted_token_filesystem_probe": bool(
                restricted_token_artifact.get("passed")
                and restricted_token_artifact.get("restricted_token")
                and restricted_token_artifact.get("filesystem_write_isolated")
            ),
            "authenticated_default_deny_egress_proxy": bool(
                egress_proxy_artifact.get("passed")
                and egress_proxy_artifact.get("default_deny")
                and egress_proxy_artifact.get("proxy_authentication")
                and egress_proxy_artifact.get("dns_resolution_checked")
            ),
            "process_restart_recovery": bool(recovery_artifact.get("passed")),
            "multi_worker_recovery_soak": bool(
                recovery_soak_artifact.get("multi_worker_passed")
            ),
            "multi_hour_recovery_soak": bool(
                recovery_soak_artifact.get("multi_hour_passed")
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
        agent_router = self.root / "clawos" / "api" / "agent_product.py"
        agent_kernel = (
            self.root / "clawos" / "services" / "agent_product_kernel.py"
        )
        agent_sdk = self.root / "clawos" / "services" / "agent_sdk.py"
        learning_product = (
            self.root / "clawos" / "services" / "learning_product_service.py"
        )
        academy_js = (
            self.root / "clawos" / "static" / "assets" / "academy.js"
        )
        workflow_text = self._read(workflow)
        extension_text = self._read(extension)
        agent_router_text = self._read(agent_router)
        agent_kernel_text = self._read(agent_kernel)
        agent_sdk_text = self._read(agent_sdk)
        learning_product_text = self._read(learning_product)
        academy_text = self._read(academy_js)
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
            "unified_task_run_protocol": bool(
                "clawos.task-run.v2" in agent_kernel_text
                and "/api/agent-product/task-runs" in agent_router_text
                and "transition_task" in agent_router_text
            ),
            "event_hook_v2": bool(
                "clawos.agent-hooks.v2" in self._read(
                    self.root / "clawos" / "services"
                    / "execution_governance.py"
                )
                and "checkpoint_created" in self._read(
                    self.root / "clawos" / "services"
                    / "execution_governance.py"
                )
            ),
            "capability_aware_sdk": bool(
                "clawos.agent-sdk.v1" in agent_sdk_text
                and "granted_capabilities" in agent_sdk_text
            ),
            "sandbox_plan_truth_boundary": bool(
                "os_enforced" in agent_kernel_text
                and "remains unclaimed" in agent_kernel_text
            ),
            "context_memory_explainability": bool(
                "/api/agent-product/context/explain" in agent_router_text
                and "/explain" in agent_router_text
                and "confirmed=true is required" in agent_router_text
            ),
            "ide_native_change_rewind": bool(
                "git.openChange" in extension_text
                and "clawos.rewindLastTask" in extension_text
                and "checkpoint_restored" in extension_text
            ),
            "education_evidence_truth_source": bool(
                "clawos.learning-dashboard.v1" in learning_product_text
                and "bkt-fsrs-lite.v1" in learning_product_text
                and "/api/academy/learning/dashboard" in academy_text
                and "clawos_academy_completed" not in academy_text
            ),
            "context_review_evidence_ledger": bool(
                "/task-runs/{task_id}/ledger" in agent_router_text
                and "/task-runs/{task_id}/reviews" in agent_router_text
                and "run.review" in agent_kernel_text
            ),
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
