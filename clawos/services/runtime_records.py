from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


RUN_SCHEMA_VERSION = "clawos.run.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _compact(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


@dataclass
class ArtifactRecord:
    artifact_id: str
    kind: str
    title: str
    uri: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "title": self.title,
            "uri": self.uri,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class EvidenceRecord:
    evidence_id: str
    source: str
    claim: str
    citation: str = ""
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source": self.source,
            "claim": self.claim,
            "citation": self.citation,
            "score": self.score,
            "metadata": self.metadata,
        }


@dataclass
class FailureCaseRecord:
    failure_id: str
    category: str
    reason: str
    source_run_id: str
    severity: str = "medium"
    input_summary: str = ""
    output_summary: str = ""
    remediation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_id": self.failure_id,
            "category": self.category,
            "reason": self.reason,
            "source_run_id": self.source_run_id,
            "severity": self.severity,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "remediation": self.remediation,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class RunRecord:
    run_id: str
    run_type: str
    title: str
    status: str = "created"
    actor: str = "system"
    scenario: str = ""
    started_at: str = field(default_factory=now_iso)
    completed_at: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    workflow: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    failure_cases: list[FailureCaseRecord] = field(default_factory=list)
    parent_run_id: str = ""
    tags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)

    def add_artifact(self, kind: str, title: str, uri: str = "", **metadata: Any) -> ArtifactRecord:
        item = ArtifactRecord(
            artifact_id=f"art-{len(self.artifacts) + 1:03d}",
            kind=kind,
            title=title,
            uri=uri,
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
        self.artifacts.append(item)
        return item

    def add_evidence(self, source: str, claim: str, citation: str = "", score: float | None = None, **metadata: Any) -> EvidenceRecord:
        item = EvidenceRecord(
            evidence_id=f"ev-{len(self.evidence) + 1:03d}",
            source=source,
            claim=_compact(claim),
            citation=citation,
            score=score,
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
        self.evidence.append(item)
        return item

    def add_failure_case(
        self,
        category: str,
        reason: str,
        *,
        severity: str = "medium",
        input_summary: str = "",
        output_summary: str = "",
        remediation: str = "",
        **metadata: Any,
    ) -> FailureCaseRecord:
        item = FailureCaseRecord(
            failure_id=f"fc-{len(self.failure_cases) + 1:03d}",
            category=category,
            reason=_compact(reason, 400),
            source_run_id=self.run_id,
            severity=severity,
            input_summary=_compact(input_summary, 400),
            output_summary=_compact(output_summary, 400),
            remediation=_compact(remediation, 400),
            metadata={key: value for key, value in metadata.items() if value is not None},
        )
        self.failure_cases.append(item)
        return item

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RUN_SCHEMA_VERSION,
            "run_id": self.run_id,
            "run_type": self.run_type,
            "title": self.title,
            "status": self.status,
            "actor": self.actor,
            "scenario": self.scenario,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "metrics": self.metrics,
            "workflow": self.workflow,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "evidence": [item.to_dict() for item in self.evidence],
            "failure_cases": [item.to_dict() for item in self.failure_cases],
            "parent_run_id": self.parent_run_id,
            "tags": self.tags,
            "provenance": self.provenance,
            "verification": self.verification,
        }


def run_from_task(task: dict[str, Any]) -> dict[str, Any]:
    run = RunRecord(
        run_id=f"task-{task.get('id')}",
        run_type="task",
        title=str(task.get("title") or "Runtime task"),
        status=str(task.get("status") or "unknown"),
        actor=str((task.get("metadata") or {}).get("actor_id") or "task-runtime"),
        scenario=str(task.get("source") or ""),
        started_at=str(task.get("started_at") or now_iso()),
        completed_at=str(task.get("completed_at") or ""),
        inputs={"session_id": task.get("session_id"), "metadata": task.get("metadata") or {}},
        outputs={"error": task.get("error") or "", "response_payload": (task.get("metadata") or {}).get("response_payload")},
        tags=["task", str(task.get("source") or "runtime")],
    )
    if task.get("error") or str(task.get("status")) == "failed":
        run.add_failure_case(
            "runtime_task_failure",
            task.get("error") or f"Task ended with status {task.get('status')}",
            severity="high" if str(task.get("status")) == "failed" else "medium",
            input_summary=task.get("title") or "",
            remediation="Retry through the workflow engine and attach step-level evidence.",
        )
    return run.to_dict()


def run_from_multi_agent_result(result: dict[str, Any]) -> dict[str, Any]:
    run = RunRecord(
        run_id=str(result.get("run_id") or f"multi-agent-{result.get('project_name', 'clawos')}-{result.get('score', 0)}"),
        run_type="multi_agent",
        title=f"{result.get('project_name', 'ClawOS')} multi-agent review",
        status=str((result.get("quality_gate") or {}).get("status") or result.get("status") or "unknown"),
        actor="fixed-role-squad",
        scenario=str(result.get("focus") or ""),
        completed_at=now_iso(),
        inputs={"focus": result.get("focus"), "project_name": result.get("project_name")},
        outputs={"score": result.get("score"), "quality_gate": result.get("quality_gate")},
        metrics={
            "score": result.get("score"),
            "rubric_score": (result.get("rubric_matrix") or {}).get("score"),
            "trace_steps": len(result.get("execution_trace") or []),
            "rework_rounds": len((result.get("rework_loop") or {}).get("rounds") or []),
        },
        workflow={
            "name": "multi_agent_delivery_gate",
            "states": ["planned", "evidence_collected", "built", "reviewed", "risk_checked", "judged", "reworked"],
            "timeline": result.get("timeline") or [],
        },
        tags=["multi-agent", "review", "gate"],
    )
    if result.get("committee_report"):
        run.add_artifact("report", "Multi-agent committee report", result.get("committee_report"))
    for step in result.get("execution_trace") or []:
        for artifact in step.get("artifacts") or []:
            run.add_artifact("trace_artifact", f"{step.get('agent', 'agent')} {step.get('phase', 'step')}", artifact, step_id=step.get("id"))
        run.add_evidence(
            str(step.get("agent") or "agent"),
            step.get("output") or step.get("task") or "",
            score=step.get("score"),
            phase=step.get("phase"),
        )
    for item in (result.get("quality_gate") or {}).get("failures") or []:
        run.add_failure_case(
            "quality_gate_failure",
            item,
            severity="high",
            input_summary=result.get("focus") or "",
            remediation="Execute rework round, compare v1/v2 artifacts, and rescore Reviewer/Risk/Judge.",
        )
    for item in result.get("disagreement_log") or []:
        if item.get("requires_rework"):
            run.add_failure_case(
                "agent_disagreement",
                item.get("opposes") or item.get("arbitration_decision") or "Agent disagreement requires rework.",
                severity="medium",
                input_summary=item.get("objector") or "",
                output_summary=item.get("evidence") or "",
                remediation=item.get("arbitration_decision") or "",
            )
    return run.to_dict()


def run_from_acceptance_report(report: dict[str, Any], report_path: str = "") -> dict[str, Any]:
    benchmark = report.get("benchmark") or {}
    metrics = benchmark.get("metrics") or {}
    run = RunRecord(
        run_id=f"acceptance-{benchmark.get('name') or 'deepseek-qwen'}",
        run_type="evaluation",
        title=str(benchmark.get("name") or "DeepSeek + Qwen complex-task acceptance"),
        status="pass" if report.get("ok") else "failed",
        actor="evaluation-service",
        scenario="deepseek-qwen-hybrid-rag",
        completed_at=now_iso(),
        inputs={"model": report.get("model"), "case_count": benchmark.get("case_count")},
        outputs={"ok": report.get("ok"), "report_path": report_path},
        metrics=metrics,
        workflow={
            "name": "complex_task_acceptance",
            "states": ["case_loaded", "retrieved", "reranked", "answered", "judged", "aggregated"],
            "by_scenario": metrics.get("by_scenario") or benchmark.get("by_scenario") or {},
        },
        tags=["evaluation", "rag", "deepseek", "qwen"],
    )
    if report_path:
        run.add_artifact("evaluation_report", "DeepSeek + Qwen acceptance report", report_path)
    for case in report.get("cases") or []:
        run.add_evidence(
            source=str(case.get("scenario") or "case"),
            claim=f"{case.get('name', '')}: pass={case.get('pass')} citation_hit={case.get('citation_hit')}",
            citation=str(case.get("expected_citation") or case.get("citation") or ""),
            score=1.0 if case.get("pass") else 0.0,
            latency_ms=case.get("latency_ms"),
            vector_rank=case.get("vector_rank"),
            rerank_rank=case.get("rerank_rank"),
        )
        if not case.get("pass") or case.get("failure_reason"):
            reason = case.get("failure_reason") or "case failed acceptance gate"
            if reason != "pass":
                run.add_failure_case(
                    "acceptance_case_failure",
                    reason,
                    severity="high" if not case.get("pass") else "low",
                    input_summary=case.get("query") or case.get("task") or case.get("name") or "",
                    output_summary=case.get("answer") or case.get("judge_output") or "",
                    remediation="Add this case to the failure library and rerun after retrieval, citation, or answer-quality fixes.",
                    scenario=case.get("scenario"),
                    case_name=case.get("name"),
                )
    return run.to_dict()
