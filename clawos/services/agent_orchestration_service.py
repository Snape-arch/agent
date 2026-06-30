from __future__ import annotations

from typing import Any

from .runtime_records import run_from_multi_agent_result
from .workflow_engine import WorkflowEngine


class AgentOrchestrationService:
    """Boundary for fixed-role squads and their quality-gate lifecycle."""

    def __init__(self, workflow_engine: WorkflowEngine | None = None):
        self.workflow_engine = workflow_engine or WorkflowEngine()

    def normalize_committee_result(self, result: dict[str, Any]) -> dict[str, Any]:
        run_record = run_from_multi_agent_result(result)
        gate = result.get("quality_gate") or {}
        rework_rounds = (result.get("rework_loop") or {}).get("rounds") or []
        gate_statuses = [{
            "name": "initial_quality_gate",
            "status": gate.get("status", "failed"),
            "score": result.get("score"),
            "failures": gate.get("failures") or [],
        }]
        for item in rework_rounds:
            gate_statuses.append({
                "name": f"rework_round_{item.get('round')}",
                "status": item.get("status", "failed"),
                "score": item.get("final_score"),
                "failures": item.get("required_rework") or item.get("unresolved") or [],
            })
        workflow = self.workflow_engine.gate_rework_until_done(
            workflow_id=run_record["run_id"],
            name="multi_agent_rework_gate",
            gate_statuses=gate_statuses,
            artifact_saves=run_record["artifacts"],
        )
        run_record["workflow"] = {**run_record.get("workflow", {}), "state_machine": workflow}
        return run_record
