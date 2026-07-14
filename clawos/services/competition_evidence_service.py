from __future__ import annotations

import hashlib
import re
from datetime import datetime
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
TRACE_STATUSES = PASS_STATUSES | {"failed", "error", "revision_required", "rejected"}
CANONICAL_SCENARIOS = {key for key, _ in SCENARIOS}
SCENARIO_ALIASES = {"project": "coding", "office": "data_analysis", "research": "paper"}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.I)
REQUIRED_MODEL_ROLES = {"planner", "executor", "reviewer"}


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

        if str(run.get("schema") or "") != "clawos.run.v1":
            failures.append("invalid_run_schema")
        if str(workflow.get("schema") or "") != EVIDENCE_CHAIN_SCHEMA:
            failures.append("invalid_evidence_schema")
        scenario = SCENARIO_ALIASES.get(str(run.get("scenario") or "").strip().lower(), str(run.get("scenario") or "").strip().lower())
        if scenario not in CANONICAL_SCENARIOS:
            failures.append("invalid_scenario")

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
        if not provider or not str(provenance.get("model") or "").strip():
            failures.append("missing_live_model_provenance")
        if CompetitionEvidenceService._contains_non_real_marker(provider) or CompetitionEvidenceService._contains_non_real_marker(execution_mode):
            failures.append("mock_or_fixture_provider")
        if tags & NON_REAL_MARKERS:
            failures.append("non_real_tag")
        if input_origin not in {"user_supplied", "repository", "live_connector"}:
            failures.append("unverified_input_origin")
        duration = (run.get("metrics") or {}).get("duration_ms")
        if not isinstance(duration, (int, float)) or duration <= 0:
            failures.append("missing_real_duration")
        started_at = CompetitionEvidenceService._parse_timestamp(run.get("started_at"))
        completed_at = CompetitionEvidenceService._parse_timestamp(run.get("completed_at"))
        if not started_at or not completed_at:
            failures.append("missing_timestamps")
        elif completed_at <= started_at:
            failures.append("invalid_timestamp_order")
        elif isinstance(duration, (int, float)) and duration > 0:
            elapsed_ms = (completed_at - started_at).total_seconds() * 1000
            if abs(float(duration) - elapsed_ms) > max(5000, elapsed_ms * 0.10):
                failures.append("duration_timestamp_mismatch")
        artifacts = list(run.get("artifacts") or [])
        if not artifacts:
            failures.append("missing_artifacts")
        for artifact in artifacts:
            metadata = artifact.get("metadata") or {}
            artifact_id = str(artifact.get("artifact_id") or "unknown")
            if not str(artifact.get("uri") or "").strip():
                failures.append(f"artifact_without_uri:{artifact_id}")
            if not SHA256_PATTERN.fullmatch(str(metadata.get("sha256") or "")):
                failures.append(f"artifact_without_sha256:{artifact.get('artifact_id', 'unknown')}")
            if not isinstance(metadata.get("bytes"), int) or metadata.get("bytes") <= 0:
                failures.append(f"artifact_without_bytes:{artifact_id}")
        gate = stage_by_id.get("quality_gate") or {}
        if str(gate.get("status") or "").lower() not in {"pass", "passed"}:
            failures.append("quality_gate_not_passed")

        CompetitionEvidenceService._validate_model_roles(stage_by_id.get("subagent_delegation") or {}, failures)
        CompetitionEvidenceService._validate_tool_trace(stage_by_id.get("tool_trace") or {}, failures)
        CompetitionEvidenceService._validate_rework(run, stage_by_id.get("rework") or {}, failures)
        CompetitionEvidenceService._validate_knowledge_capture(run, stage_by_id.get("knowledge_capture") or {}, failures)

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

    @staticmethod
    def _records(stage: dict[str, Any]) -> list[dict[str, Any]]:
        raw = stage.get("records")
        if not isinstance(raw, list):
            raw = stage.get("evidence")
        return [item for item in (raw or []) if isinstance(item, dict)]

    @staticmethod
    def _contains_non_real_marker(value: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower())
        return any(marker in normalized.split("_") or marker in normalized for marker in NON_REAL_MARKERS)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _valid_timed_record(record: dict[str, Any]) -> bool:
        started = CompetitionEvidenceService._parse_timestamp(record.get("started_at") or record.get("timestamp"))
        completed = CompetitionEvidenceService._parse_timestamp(record.get("completed_at"))
        duration = record.get("duration_ms")
        return bool(
            started
            and isinstance(duration, (int, float))
            and duration > 0
            and (completed is None or completed >= started)
        )

    @staticmethod
    def _validate_model_roles(stage: dict[str, Any], failures: list[str]) -> None:
        records = CompetitionEvidenceService._records(stage)
        roles = set()
        for record in records:
            role = str(record.get("role_type") or record.get("role_id") or "").strip().lower()
            roles.add(role)
            provider = str(record.get("provider") or "").strip().lower()
            if (
                not role
                or not provider
                or CompetitionEvidenceService._contains_non_real_marker(provider)
                or not str(record.get("model") or "").strip()
                or not isinstance(record.get("tokens"), int)
                or record.get("tokens") <= 0
                or not CompetitionEvidenceService._valid_timed_record(record)
            ):
                failures.append(f"invalid_model_role_record:{role or 'unknown'}")
        missing_roles = sorted(REQUIRED_MODEL_ROLES - roles)
        if missing_roles:
            failures.append("missing_model_roles:" + ",".join(missing_roles))

    @staticmethod
    def _validate_tool_trace(stage: dict[str, Any], failures: list[str]) -> None:
        records = CompetitionEvidenceService._records(stage)
        if not records:
            failures.append("missing_tool_trace_records")
            return
        sequences = []
        for record in records:
            sequence = record.get("sequence")
            sequences.append(sequence)
            arguments_hash = str(record.get("arguments_hash") or "")
            status = str(record.get("status") or "").lower()
            if (
                not isinstance(sequence, int)
                or sequence <= 0
                or not str(record.get("tool") or record.get("name") or "").strip()
                or status not in TRACE_STATUSES
                or not SHA256_PATTERN.fullmatch(arguments_hash)
                or not SHA256_PATTERN.fullmatch(str(record.get("result_hash") or ""))
                or not CompetitionEvidenceService._valid_timed_record(record)
            ):
                failures.append(f"invalid_tool_trace_record:{sequence or 'unknown'}")
        if all(isinstance(item, int) for item in sequences) and sequences != list(range(1, len(sequences) + 1)):
            failures.append("unordered_tool_trace")

    @staticmethod
    def _validate_rework(run: dict[str, Any], stage: dict[str, Any], failures: list[str]) -> None:
        failure_cases = {str(item.get("failure_id") or ""): item for item in run.get("failure_cases") or []}
        artifact_ids = {str(item.get("artifact_id") or "") for item in run.get("artifacts") or []}
        records = CompetitionEvidenceService._records(stage)
        valid = False
        for record in records:
            failure_id = str(record.get("failure_id") or "")
            before_id = str(record.get("before_artifact_id") or "")
            after_id = str(record.get("after_artifact_id") or "")
            failure = failure_cases.get(failure_id) or {}
            if (
                failure_id
                and before_id
                and after_id
                and before_id != after_id
                and before_id in artifact_ids
                and after_id in artifact_ids
                and str(failure.get("reason") or "").strip()
                and str(failure.get("remediation") or "").strip()
                and CompetitionEvidenceService._valid_timed_record(record)
            ):
                valid = True
                break
        if not valid:
            failures.append("missing_verifiable_rework")

    @staticmethod
    def _validate_knowledge_capture(run: dict[str, Any], stage: dict[str, Any], failures: list[str]) -> None:
        artifact_ids = {str(item.get("artifact_id") or "") for item in run.get("artifacts") or []}
        valid = False
        for record in CompetitionEvidenceService._records(stage):
            result_hash = str(record.get("result_hash") or "")
            lookup_artifact_id = str(record.get("lookup_artifact_id") or "")
            if (
                str(record.get("knowledge_id") or "").strip()
                and record.get("lookup_verified") is True
                and str(record.get("lookup_query") or "").strip()
                and CompetitionEvidenceService._parse_timestamp(record.get("retrieved_at"))
                and SHA256_PATTERN.fullmatch(result_hash)
                and lookup_artifact_id in artifact_ids
            ):
                valid = True
                break
        if not valid:
            failures.append("missing_knowledge_lookup_evidence")

    def catalog(self, runs: list[dict[str, Any]], *, include_regression: bool = False) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _ in SCENARIOS}
        regression_count = 0
        for run in runs:
            scenario = str(run.get("scenario") or "").strip().lower()
            scenario = SCENARIO_ALIASES.get(scenario, scenario)
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
