from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .runtime_records import now_iso


WORKFLOW_STATES = {
    "created",
    "planned",
    "running",
    "waiting_gate",
    "rework_required",
    "saving_artifacts",
    "passed",
    "failed",
    "blocked",
}

WORKFLOW_TRANSITIONS = {
    "created": {"planned", "running", "failed"},
    "planned": {"running", "failed", "blocked"},
    "running": {"waiting_gate", "saving_artifacts", "failed", "blocked"},
    "waiting_gate": {"passed", "rework_required", "saving_artifacts", "blocked"},
    "rework_required": {"running", "blocked", "failed"},
    "saving_artifacts": {"passed", "failed", "blocked"},
    "passed": set(),
    "failed": set(),
    "blocked": set(),
}


@dataclass
class WorkflowRun:
    workflow_id: str
    name: str
    state: str = "created"
    steps: list[dict[str, Any]] = field(default_factory=list)
    gates: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def transition(self, next_state: str, *, reason: str = "", actor: str = "system", data: dict[str, Any] | None = None) -> None:
        if next_state not in WORKFLOW_STATES:
            raise ValueError(f"Unknown workflow state: {next_state}")
        allowed = WORKFLOW_TRANSITIONS.get(self.state, set())
        if next_state not in allowed and next_state != self.state:
            raise ValueError(f"Invalid workflow transition: {self.state} -> {next_state}")
        self.state = next_state
        self.updated_at = now_iso()
        self.steps.append({
            "state": next_state,
            "reason": reason,
            "actor": actor,
            "data": data or {},
            "at": self.updated_at,
        })

    def add_gate(self, name: str, status: str, score: float | int | None = None, failures: list[str] | None = None) -> None:
        self.gates.append({
            "name": name,
            "status": status,
            "score": score,
            "failures": failures or [],
            "at": now_iso(),
        })

    def add_artifact(self, artifact: dict[str, Any]) -> None:
        self.artifacts.append(artifact)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "state": self.state,
            "states": sorted(WORKFLOW_STATES),
            "transitions": {key: sorted(value) for key, value in WORKFLOW_TRANSITIONS.items()},
            "steps": self.steps,
            "gates": self.gates,
            "artifacts": self.artifacts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class WorkflowEngine:
    """Generic state machine for agent gates, reports, acceptance, and KB saves."""

    def start(self, workflow_id: str, name: str) -> WorkflowRun:
        run = WorkflowRun(workflow_id=workflow_id, name=name)
        run.transition("planned", reason="workflow accepted")
        return run

    def gate_rework_until_done(
        self,
        *,
        workflow_id: str,
        name: str,
        gate_statuses: list[dict[str, Any]],
        artifact_saves: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        run = self.start(workflow_id, name)
        run.transition("running", reason="executor started")
        if not gate_statuses:
            run.transition("failed", reason="no quality gate evidence supplied")
            return run.to_dict()
        final_status = "failed"
        for index, gate in enumerate(gate_statuses or [], start=1):
            status = str(gate.get("status") or "failed")
            failures = list(gate.get("failures") or [])
            run.transition("waiting_gate", reason=f"gate round {index}")
            run.add_gate(str(gate.get("name") or f"round-{index}"), status, gate.get("score"), failures)
            if status in {"pass", "passed"} and not failures:
                final_status = "passed"
                break
            if status in {"blocked", "blocked_external_dependency"}:
                final_status = "blocked"
                run.transition("blocked", reason="external blocker or hard gate failure", data=gate)
                break
            final_status = "rework_required"
            run.transition("rework_required", reason="quality gate requested rework", data=gate)
            run.transition("running", reason="rework round started")
        if final_status == "passed":
            if artifact_saves:
                run.transition("saving_artifacts", reason="persisting accepted artifacts")
                for artifact in artifact_saves:
                    run.add_artifact(artifact)
            run.transition("passed", reason="all gates passed")
        elif final_status == "rework_required":
            run.transition("failed", reason="rework attempts exhausted")
        return run.to_dict()
