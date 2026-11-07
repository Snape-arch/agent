"""Coding agent HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import subprocess


class CodingAgentAPI:
    def __init__(self, *,
        _competition_hardware_evidence: Callable[..., Any],
        base_dir_provider: Callable[[], Any],
        output_root_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
    ):
        self._competition_hardware_evidence = _competition_hardware_evidence
        self.base_dir_provider = base_dir_provider
        self.output_root_provider = output_root_provider
        self.memory_store_provider = memory_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/coding-agent/readiness', self.api_coding_agent_readiness, methods=['GET'])
        self.router.add_api_route('/api/coding-agent/evidence', self.api_coding_agent_evidence, methods=['GET'])
        self.router.add_api_route('/api/coding-agent/evidence', self.api_coding_agent_evidence_record, methods=['POST'])

    async def api_coding_agent_readiness(self):
        from services.learning.readiness import AdvancedLearningReadiness
        from services.execution_governance import CodingAgentReadiness

        from services.evidence_registry import CapabilityEvidenceRegistry
        registry = CapabilityEvidenceRegistry(
            self.output_root_provider() / "evidence" / "capabilities.json"
        )
        commit = ""
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=self.base_dir_provider().parent,
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        evidence = registry.latest(expected_commit=commit)
        learning = (
            AdvancedLearningReadiness(self.memory_store_provider()).report()
            if self.memory_store_provider() else {}
        )
        evidence["real_data_thresholds"] = {
            "verified": bool(
                (learning.get("deep_router") or {}).get("ready")
                and (learning.get("trajectory_rl") or {}).get("ready")
            )
        }
        hardware = self._competition_hardware_evidence()
        evidence["target_hardware"] = {
            "verified": bool(
                hardware
                and hardware.get("passed")
                and hardware.get("task_count", 0) >= 30
            )
        }
        result = CodingAgentReadiness.report(evidence)
        result["learning_readiness"] = learning
        result["evidence"] = evidence
        result["truth_boundary"] = (
            "Readiness is fail-closed and evidence-backed. Missing or expired "
            "software evidence, production learning data, and hardware acceptance "
            "remain unverified; online RL is not claimed."
        )
        return JSONResponse(result)


    async def api_coding_agent_evidence(self):
        from services.evidence_registry import CapabilityEvidenceRegistry
        return JSONResponse({
            "records": CapabilityEvidenceRegistry(
                self.output_root_provider() / "evidence" / "capabilities.json"
            ).list()
        })


    async def api_coding_agent_evidence_record(self, request: Request):
        from services.evidence_registry import CapabilityEvidenceRegistry
        data = await request.json()
        try:
            result = CapabilityEvidenceRegistry(
                self.output_root_provider() / "evidence" / "capabilities.json"
            ).record(
                str(data.get("capability") or ""),
                status=str(data.get("status") or ""),
                evidence_type=str(data.get("evidence_type") or ""),
                source=str(data.get("source") or ""),
                metrics=data.get("metrics") or {},
                artifact_digest=str(data.get("artifact_digest") or ""),
                commit=str(data.get("commit") or ""),
                environment=str(data.get("environment") or ""),
                expires_at=str(data.get("expires_at") or ""),
                truth_scope=str(data.get("truth_scope") or "software"),
                confirmed=data.get("confirmed") is True,
            )
        except (PermissionError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)
