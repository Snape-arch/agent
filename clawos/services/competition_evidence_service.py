from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


EVIDENCE_CHAIN_SCHEMA = "clawos.real-task-evidence.v1"
REQUIRED_STAGES = (
    "user_goal",
    "agent_plan",
    "subagent_delegation",
    "tool_trace",
    "rework",
    "quality_gate",
    "final_artifacts",
    "knowledge_capture",
)
SCENARIOS = (
    ("coding", "真实仓库 Coding"),
    ("meeting", "会议音频到纪要、邮件与日历"),
    ("data_analysis", "Excel 数据分析与管理报告"),
    ("paper", "长论文阅读、批注、证据追问与复现计划"),
    ("learning", "知识库驱动的学习路线、测验与错因复习"),
)
NON_REAL_MARKERS = {"mock", "fixture", "synthetic", "deterministic", "demo", "sample", "example"}
PASS_STATUSES = {"pass", "passed", "succeeded", "completed", "captured", "reworked"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CompetitionEvidenceService:
    """Truth gate for competition-grade executions.

    Regression fixtures remain useful, but are deliberately separated from
    evidence that a judge may interpret as a real user task.
    """

    @staticmethod
    def validate(run: dict[str, Any]) -> dict[str, Any]:
        provenance = dict(run.get("provenance") or {})
        workflow = dict(run.get("workflow") or {})
        stages = list(workflow.get("evidence_chain") or [])
        stage_by_id = {str(item.get("id") or ""): item for item in stages}
        provider = str(provenance.get("provider") or "").strip().lower()
        execution_mode = str(provenance.get("execution_mode") or "").strip().lower()
        input_origin = str(provenance.get("input_origin") or "").strip().lower()
        tags = {str(item).strip().lower() for item in run.get("tags") or []}
        failures: list[str] = []

        missing = [stage for stage in REQUIRED_STAGES if stage not in stage_by_id]
        if missing:
            failures.append("missing_stages:" + ",".join(missing))
        for stage in REQUIRED_STAGES:
            item = stage_by_id.get(stage) or {}
            if str(item.get("status") or "").lower() not in PASS_STATUSES:
                failures.append(f"stage_not_complete:{stage}")
            if not (item.get("evidence") or item.get("records")):
                failures.append(f"stage_without_evidence:{stage}")
        if str(run.get("status") or "").lower() not in PASS_STATUSES:
            failures.append("run_not_passed")
        if provider in NON_REAL_MARKERS or execution_mode in NON_REAL_MARKERS:
            failures.append("mock_or_fixture_provider")
        if tags & NON_REAL_MARKERS:
            failures.append("non_real_tag")
        if input_origin not in {"user_supplied", "repository", "live_connector"}:
            failures.append("unverified_input_origin")
        duration = (run.get("metrics") or {}).get("duration_ms")
        if not isinstance(duration, (int, float)) or duration <= 0:
            failures.append("missing_real_duration")
        if not run.get("started_at") or not run.get("completed_at"):
            failures.append("missing_timestamps")
        artifacts = list(run.get("artifacts") or [])
        if not artifacts:
            failures.append("missing_artifacts")
        for artifact in artifacts:
            metadata = artifact.get("metadata") or {}
            if not metadata.get("sha256"):
                failures.append(f"artifact_without_sha256:{artifact.get('artifact_id', 'unknown')}")
        gate = stage_by_id.get("quality_gate") or {}
        if str(gate.get("status") or "").lower() not in {"pass", "passed"}:
            failures.append("quality_gate_not_passed")

        failures = list(dict.fromkeys(failures))
        return {
            "schema": EVIDENCE_CHAIN_SCHEMA,
            "eligible": not failures,
            "level": "competition_verified" if not failures else (
                "regression_only" if {provider, execution_mode} & NON_REAL_MARKERS or tags & NON_REAL_MARKERS else "incomplete"
            ),
            "failures": failures,
            "stage_count": len(stage_by_id),
            "required_stage_count": len(REQUIRED_STAGES),
        }

    def catalog(self, runs: list[dict[str, Any]], *, include_regression: bool = False) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in SCENARIOS}
        regression_count = 0
        for run in runs:
            scenario = str(run.get("scenario") or "").strip().lower()
            scenario = {
                "project": "coding", "office": "data_analysis", "research": "paper",
            }.get(scenario, scenario)
            if scenario not in grouped:
                continue
            validation = self.validate(run)
            if not validation["eligible"]:
                if validation["level"] == "regression_only":
                    regression_count += 1
                if not include_regression:
                    continue
            grouped[scenario].append(self._public_chain(run, validation))

        slots = []
        for key, label in SCENARIOS:
            chains = sorted(grouped[key], key=lambda item: item.get("completed_at") or "", reverse=True)
            slots.append({
                "scenario": key,
                "label": label,
                "state": "verified" if chains and chains[0]["verification"]["eligible"] else ("regression_only" if chains else "empty"),
                "latest": chains[0] if chains else None,
                "count": len(chains),
            })
        verified = sum(1 for item in slots if item["state"] == "verified")
        return {
            "schema": EVIDENCE_CHAIN_SCHEMA,
            "verified_count": verified,
            "required_count": len(SCENARIOS),
            "competition_ready": verified == len(SCENARIOS),
            "regression_excluded": regression_count,
            "slots": slots,
        }

    @staticmethod
    def _public_chain(run: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
        artifacts = []
        for item in run.get("artifacts") or []:
            metadata = item.get("metadata") or {}
            artifacts.append({
                "artifact_id": item.get("artifact_id"), "kind": item.get("kind"),
                "title": item.get("title"), "sha256": metadata.get("sha256"),
                "bytes": metadata.get("bytes"),
            })
        return {
            "run_id": run.get("run_id"), "title": run.get("title"), "scenario": run.get("scenario"),
            "status": run.get("status"), "started_at": run.get("started_at"), "completed_at": run.get("completed_at"),
            "duration_ms": (run.get("metrics") or {}).get("duration_ms"),
            "provenance": run.get("provenance") or {}, "verification": validation,
            "stages": (run.get("workflow") or {}).get("evidence_chain") or [], "artifacts": artifacts,
            "failures": run.get("failure_cases") or [],
        }
