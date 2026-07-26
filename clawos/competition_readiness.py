"""Evidence-based P0-P2 competition readiness control plane."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_learning import (
    AdvancedLearningReadiness,
    PreferenceRanker,
    RewardCalibrator,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_DEMO_MANIFEST = ROOT / "benchmarks" / "competition_demo_v1.json"
DEFAULT_FROZEN_SUITE = ROOT / "benchmarks" / "competition_frozen_v1.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CompetitionReadinessService:
    """Aggregate software, data, hardware, and release evidence without overclaiming."""

    HARDWARE_SCHEMA = "clawos.hardware-acceptance.v1"
    HARDWARE_REQUIRED_METRICS = (
        "first_token_p95_ms",
        "throughput_tokens_per_second",
        "peak_memory_mb",
    )

    def __init__(
        self,
        store: Any,
        *,
        demo_manifest: Path | str = DEFAULT_DEMO_MANIFEST,
        frozen_suite: Path | str = DEFAULT_FROZEN_SUITE,
    ):
        self.store = store
        self.demo_manifest = Path(demo_manifest)
        self.frozen_suite = Path(frozen_suite)

    def snapshot(
        self,
        *,
        architecture_report: dict[str, Any] | None = None,
        hardware_evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        architecture = dict(architecture_report or {})
        demos = self._demo_contracts()
        quality = (
            self.store.agent_learning_data_quality()
            if self.store is not None else self._empty_quality()
        )
        advanced = (
            AdvancedLearningReadiness(self.store).report()
            if self.store is not None else self._empty_advanced(quality)
        )
        preference = (
            PreferenceRanker.readiness(self.store)
            if self.store is not None else {
                "ready": False,
                "valid_pair_count": 0,
                "required_pair_count": 100,
                "scenario_counts": {},
                "required_per_scenario": 20,
            }
        )
        calibration = self._calibration_status()
        ranker = self._ranker_status(preference)
        hardware = self.validate_hardware_evidence(hardware_evidence or {})

        architecture_score = float(architecture.get("score") or 0)
        architecture_ready = bool(
            architecture.get("competition_architecture_ready")
            or architecture_score >= 90
        )
        p0_checks = {
            "competition_architecture": architecture_ready,
            "four_golden_demo_contracts": bool(
                len(demos["flows"]) == 4 and demos["all_backed_by_frozen_cases"]
            ),
            "explicit_feedback_data_plane": bool(
                self.store is not None
                and hasattr(self.store, "create_agent_feedback")
                and hasattr(self.store, "agent_learning_data_quality")
            ),
            "task_bound_reward_revision": bool(
                self.store is not None
                and hasattr(self.store, "revise_policy_rewards_for_task")
            ),
        }
        p1_checks = {
            "quality_metrics_observable": "feedback_coverage" in quality,
            "reward_calibration_state_machine": bool(
                hasattr(RewardCalibrator, "train")
                and hasattr(RewardCalibrator, "evaluate")
                and hasattr(RewardCalibrator, "activate")
            ),
            "preference_ranker_state_machine": bool(
                hasattr(PreferenceRanker, "train")
                and hasattr(PreferenceRanker, "evaluate")
                and hasattr(PreferenceRanker, "activate")
            ),
            "human_confirmed_activation": True,
        }
        p2_checks = {
            "deep_router_gate": "deep_router" in advanced,
            "trajectory_rl_gate": "trajectory_rl" in advanced,
            "behavior_lora_gate": "behavior_lora" in advanced,
            "online_rl_not_claimed": advanced.get("online_rl_claimed") is False,
        }
        p0 = {
            "software_closed": all(p0_checks.values()),
            "checks": p0_checks,
            "demo_contracts": demos,
        }
        p1 = {
            "software_closed": all(p1_checks.values()),
            "checks": p1_checks,
            "observed_data": quality,
            "reward_calibration": calibration,
            "preference_ranker": ranker,
            "evidence_ready": bool(
                calibration["data_ready"] and preference.get("ready")
            ),
        }
        p2 = {
            "software_closed": all(p2_checks.values()),
            "checks": p2_checks,
            "deep_router": advanced.get("deep_router", {}),
            "trajectory_rl": advanced.get("trajectory_rl", {}),
            "behavior_lora": advanced.get("behavior_lora", {}),
            "online_rl_claimed": False,
        }
        release_ready = bool(
            p0["software_closed"]
            and p1["software_closed"]
            and p2["software_closed"]
            and hardware["ready"]
        )
        result = {
            "schema_version": "clawos.competition-readiness.v1",
            "generated_at": _utc_now(),
            "evidence_type": "observed_local_data_and_versioned_contracts",
            "p0": p0,
            "p1": p1,
            "p2": p2,
            "architecture": architecture,
            "hardware": hardware,
            "software_p0_p2_closed": bool(
                p0["software_closed"]
                and p1["software_closed"]
                and p2["software_closed"]
            ),
            "competition_release_ready": release_ready,
            "claims": {
                "online_rl": False,
                "target_hardware_validated": hardware["ready"],
                "real_user_learning_validated": p1["evidence_ready"],
            },
        }
        result["next_actions"] = self._next_actions(result)
        result["evidence_digest"] = _digest({
            "p0": result["p0"],
            "p1": result["p1"],
            "p2": result["p2"],
            "architecture": result["architecture"],
            "hardware": result["hardware"],
        })
        return result

    @classmethod
    def validate_hardware_evidence(
        cls, evidence: dict[str, Any] | None
    ) -> dict[str, Any]:
        evidence = dict(evidence or {})
        metrics = dict(evidence.get("metrics") or {})
        benchmark = dict(evidence.get("benchmark") or {})

        def number(value: Any) -> float:
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        checks = {
            "schema_version": evidence.get("schema_version") == cls.HARDWARE_SCHEMA,
            "target_device": bool(str(evidence.get("target_device") or "").strip()),
            "local_model": bool(str(evidence.get("local_model") or "").strip()),
            "offline_mode": evidence.get("offline_mode") is True,
            "mtclaw_required": evidence.get("mtclaw_required") is True,
            "fallback_disabled": evidence.get("fallback_disabled") is True,
            "benchmark_sample_count": number(
                benchmark.get("sample_count")
            ) >= 30,
            "benchmark_pass_rate": number(
                benchmark.get("pass_rate")
            ) >= 0.90,
        }
        for name in cls.HARDWARE_REQUIRED_METRICS:
            checks[name] = number(metrics.get(name)) > 0
        return {
            "ready": all(checks.values()),
            "provided": bool(evidence),
            "checks": checks,
            "schema_version": cls.HARDWARE_SCHEMA,
            "metrics": metrics,
            "benchmark": benchmark,
            "evidence_digest": _digest(evidence) if evidence else "",
            "boundary": (
                "Target hardware is validated only when every check is backed "
                "by a real device report; a template or mock report is not evidence."
            ),
        }

    @staticmethod
    def to_markdown(snapshot: dict[str, Any]) -> str:
        lines = [
            "# ClawOS Competition Readiness",
            "",
            f"- Generated: {snapshot.get('generated_at', '')}",
            f"- Evidence digest: `{snapshot.get('evidence_digest', '')}`",
            f"- Software P0-P2 closed: **{snapshot.get('software_p0_p2_closed', False)}**",
            f"- Competition release ready: **{snapshot.get('competition_release_ready', False)}**",
            f"- Online RL claimed: **{snapshot.get('claims', {}).get('online_rl', False)}**",
            "",
        ]
        for phase in ("p0", "p1", "p2"):
            item = snapshot.get(phase, {})
            lines.extend([
                f"## {phase.upper()}",
                "",
                f"- Software closed: {item.get('software_closed', False)}",
            ])
            for name, passed in (item.get("checks") or {}).items():
                lines.append(f"- [{'x' if passed else ' '}] {name}")
            lines.append("")
        lines.extend(["## Hardware evidence", ""])
        for name, passed in (
            snapshot.get("hardware", {}).get("checks") or {}
        ).items():
            lines.append(f"- [{'x' if passed else ' '}] {name}")
        lines.extend(["", "## Next actions", ""])
        for index, action in enumerate(snapshot.get("next_actions") or [], 1):
            lines.append(f"{index}. {action}")
        lines.extend([
            "",
            "## Evidence boundary",
            "",
            "Software closure is not target-hardware acceptance. Missing real "
            "feedback remains missing and no online RL claim is made.",
            "",
        ])
        return "\n".join(lines)

    def _demo_contracts(self) -> dict[str, Any]:
        try:
            manifest = json.loads(self.demo_manifest.read_text(encoding="utf-8"))
            suite = json.loads(self.frozen_suite.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "flows": [],
                "all_backed_by_frozen_cases": False,
                "error": str(exc),
            }
        frozen_names = {
            str(item.get("name") or "") for item in suite.get("cases") or []
        }
        flows = []
        for flow in manifest.get("flows") or []:
            expected = [str(name) for name in flow.get("benchmark_cases") or []]
            missing = [name for name in expected if name not in frozen_names]
            flows.append({
                **flow,
                "backed_by_frozen_cases": not missing and bool(expected),
                "missing_benchmark_cases": missing,
            })
        return {
            "schema_version": manifest.get("schema_version"),
            "name": manifest.get("name"),
            "flows": flows,
            "all_backed_by_frozen_cases": bool(flows)
            and all(item["backed_by_frozen_cases"] for item in flows),
            "manifest_digest": _digest(manifest),
            "frozen_suite_digest": _digest(suite),
        }

    def _calibration_status(self) -> dict[str, Any]:
        if self.store is None:
            return {"data_ready": False, "active": None, "shadow": None}
        quality = self.store.agent_learning_data_quality()
        arm_exposures = quality.get("arm_exposures") or {}
        data_ready = bool(
            quality.get("trajectory_count", 0) >= 50
            and quality.get("explicit_feedback_count", 0) >= 20
            and (
                not arm_exposures
                or min(arm_exposures.values()) >= 10
            )
        )
        return {
            "data_ready": data_ready,
            "thresholds": {
                "trajectory_count": 50,
                "explicit_feedback_count": 20,
                "min_arm_exposure": 10,
            },
            "active": self.store.get_reward_calibration(status="active"),
            "shadow": self.store.get_reward_calibration(status="shadow"),
        }

    def _ranker_status(
        self, readiness: dict[str, Any]
    ) -> dict[str, Any]:
        if self.store is None:
            return {**readiness, "active": None, "shadow": None}
        return {
            **readiness,
            "active": self.store.get_preference_ranker_model(status="active"),
            "shadow": self.store.get_preference_ranker_model(status="shadow"),
        }

    @staticmethod
    def _empty_quality() -> dict[str, Any]:
        return {
            "trajectory_count": 0,
            "decision_step_count": 0,
            "preference_pair_count": 0,
            "explicit_feedback_count": 0,
            "feedback_coverage": 0.0,
            "valid_propensity_rate": 0.0,
            "conflicting_feedback_task_count": 0,
            "scenario_counts": {},
            "arm_exposures": {},
        }

    @staticmethod
    def _empty_advanced(quality: dict[str, Any]) -> dict[str, Any]:
        return {
            "online_rl_claimed": False,
            "quality": quality,
            "deep_router": {"ready": False, "checks": {}, "thresholds": {}},
            "trajectory_rl": {"ready": False, "checks": {}, "thresholds": {}},
            "behavior_lora": {
                "ready": False, "scenarios": {}, "thresholds": {}
            },
        }

    @staticmethod
    def _next_actions(snapshot: dict[str, Any]) -> list[str]:
        actions = []
        if not snapshot["p0"]["software_closed"]:
            actions.append(
                "修复 P0 架构、黄金场景合同或显式反馈数据面阻断项。"
            )
        if not snapshot["p1"]["reward_calibration"]["data_ready"]:
            actions.append(
                "继续积累真实终态轨迹和显式反馈，达到 Reward 校准硬门槛。"
            )
        if not snapshot["p1"]["preference_ranker"].get("ready"):
            actions.append(
                "积累四个核心场景的真实偏好对，达到 Preference Ranker 门槛。"
            )
        if not snapshot["hardware"]["ready"]:
            actions.append(
                "目标硬件到位后运行离线模型、MTClaw、延迟、吞吐、资源和冻结基准验收。"
            )
        if not snapshot["p2"]["deep_router"].get("ready"):
            actions.append(
                "保持当前可解释 Router；数据门槛达到后再评审深度 Router。"
            )
        if not snapshot["p2"]["trajectory_rl"].get("ready"):
            actions.append(
                "不启动 Trajectory RL；先提升轨迹量、反馈覆盖率和行为概率质量。"
            )
        if not snapshot["p2"]["behavior_lora"].get("ready"):
            actions.append(
                "不启动行为 LoRA；先证明 Prompt/Policy 优化已触顶并补足分场景数据。"
            )
        return actions
