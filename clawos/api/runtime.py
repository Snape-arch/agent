"""Runtime HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from services.competition_evidence_service import CompetitionEvidenceService
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from services.runtime_records import RUN_SCHEMA_VERSION
from fastapi import Request
import asyncio
import json
from services.runtime_records import run_from_task


class RuntimeAPI:
    def __init__(self, *,
        _competition_hardware_evidence: Callable[..., Any],
        get_evaluation_service: Callable[..., Any],
        get_task_service: Callable[..., Any],
        get_workflow_engine: Callable[..., Any],
        output_root_provider: Callable[[], Any],
        runtime_release_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
    ):
        self._competition_hardware_evidence = _competition_hardware_evidence
        self.get_evaluation_service = get_evaluation_service
        self.get_task_service = get_task_service
        self.get_workflow_engine = get_workflow_engine
        self.output_root_provider = output_root_provider
        self.runtime_release_provider = runtime_release_provider
        self.memory_store_provider = memory_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/runtime/release', self.runtime_release, methods=['GET'])
        self.router.add_api_route('/api/competition/readiness', self.api_competition_readiness, methods=['GET'])
        self.router.add_api_route('/api/competition/hardware-evidence/validate', self.api_competition_hardware_evidence_validate, methods=['POST'])
        self.router.add_api_route('/api/competition/readiness/export', self.api_competition_readiness_export, methods=['POST'])
        self.router.add_api_route('/api/acceptance/deepseek-qwen/latest', self.api_latest_deepseek_qwen_acceptance, methods=['GET'])
        self.router.add_api_route('/api/search/live/latest', self.api_latest_search_live_acceptance, methods=['GET'])
        self.router.add_api_route('/api/runtime/schema', self.api_runtime_schema, methods=['GET'])
        self.router.add_api_route('/api/runtime/runs/latest', self.api_runtime_runs_latest, methods=['GET'])
        self.router.add_api_route('/api/runtime/failure-cases', self.api_runtime_failure_cases, methods=['GET'])
        self.router.add_api_route('/api/runtime/evidence-chains', self.api_runtime_evidence_chains, methods=['GET'])
        self.router.add_api_route('/api/runtime/evidence-chains/verify', self.api_runtime_evidence_chain_verify, methods=['POST'])

    async def runtime_release(self):
        return await asyncio.to_thread(self.runtime_release_provider().status)


    def _competition_readiness_snapshot(self) -> dict[str, Any]:
        from competition_readiness import CompetitionReadinessService
        from scripts.validate_competition_architecture import validate

        return CompetitionReadinessService(self.memory_store_provider()).snapshot(
            architecture_report=validate(),
            hardware_evidence=self._competition_hardware_evidence(),
        )


    async def api_competition_readiness(self):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        return JSONResponse(self._competition_readiness_snapshot())


    async def api_competition_hardware_evidence_validate(self, request: Request):
        from competition_readiness import CompetitionReadinessService

        data = await request.json()
        evidence = data.get("evidence") if isinstance(data, dict) else {}
        if not isinstance(evidence, dict):
            raise HTTPException(400, "evidence must be an object")
        return JSONResponse(
            CompetitionReadinessService.validate_hardware_evidence(evidence)
        )


    async def api_competition_readiness_export(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        if not bool(data.get("confirmed")):
            raise HTTPException(400, "confirmed=true is required to export")
        from competition_readiness import CompetitionReadinessService

        snapshot = self._competition_readiness_snapshot()
        self.output_root_provider().mkdir(parents=True, exist_ok=True)
        json_path = self.output_root_provider() / "competition_readiness.json"
        markdown_path = self.output_root_provider() / "competition_readiness.md"
        json_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        markdown_path.write_text(
            CompetitionReadinessService.to_markdown(snapshot),
            encoding="utf-8",
        )
        return JSONResponse({
            "ok": True,
            "competition_release_ready": snapshot["competition_release_ready"],
            "evidence_digest": snapshot["evidence_digest"],
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
        })


    async def api_latest_deepseek_qwen_acceptance(self):
        try:
            return JSONResponse(self.get_evaluation_service().read_latest_deepseek_qwen())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read report: {type(exc).__name__}") from exc


    async def api_latest_search_live_acceptance(self):
        try:
            report_dir = (self.output_root_provider() / "search_evidence").resolve()
            preferred = report_dir / "live_search_report.json"
            candidates = [preferred]
            if report_dir.exists():
                candidates.extend(sorted(report_dir.glob("*live*search*report*.json"), key=lambda item: item.stat().st_mtime, reverse=True))
            path = next((item for item in candidates if item.exists()), None)
            if not path:
                return JSONResponse({
                    "found": False,
                    "ok": False,
                    "message": "No live search acceptance report found. Run clawos/scripts/search_live_acceptance.py first.",
                    "report_path": str(preferred),
                })
            data = json.loads(path.read_text(encoding="utf-8"))
            data["found"] = True
            data["ok"] = int(data.get("failed_count", 1) or 0) == 0
            data["report_path"] = str(path)
            return JSONResponse(data)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read live search report: {type(exc).__name__}") from exc


    async def api_runtime_schema(self):
        workflow = self.get_workflow_engine().start("schema-preview", "runtime schema preview").to_dict()
        return JSONResponse({
            "schema": RUN_SCHEMA_VERSION,
            "service_boundaries": [
                "server_api",
                "workflow_engine",
                "agent_orchestration",
                "artifact_storage",
                "evaluation_service",
            ],
            "run_entities": ["Run", "Artifact", "Evidence", "FailureCase"],
            "workflow_states": workflow["states"],
            "workflow_transitions": workflow["transitions"],
        })


    async def api_runtime_runs_latest(self, limit: int = 12):
        capped = max(1, min(int(limit or 12), 50))
        runs = self.memory_store_provider().list_run_records(limit=capped) if self.memory_store_provider() else []
        if runs:
            return JSONResponse({"schema": RUN_SCHEMA_VERSION, "runs": runs, "count": len(runs), "durable": True})
        runs = []
        if self.memory_store_provider():
            for task in self.get_task_service().list(limit=capped):
                runs.append(run_from_task(task))
        acceptance = self.get_evaluation_service().read_latest_deepseek_qwen()
        if acceptance.get("run_record"):
            runs.insert(0, acceptance["run_record"])
        return JSONResponse({"schema": RUN_SCHEMA_VERSION, "runs": runs[:capped], "count": len(runs), "durable": False})


    async def api_runtime_failure_cases(self, limit: int = 50):
        capped = max(1, min(int(limit or 50), 200))
        failures = self.memory_store_provider().list_failure_cases(limit=capped) if self.memory_store_provider() else []
        if failures:
            return JSONResponse({"schema": RUN_SCHEMA_VERSION, "failure_cases": failures, "count": len(failures), "durable": True})
        failures = []
        acceptance = self.get_evaluation_service().read_latest_deepseek_qwen()
        failures.extend(acceptance.get("failure_library") or [])
        if self.memory_store_provider():
            for task in self.get_task_service().list(limit=50):
                run = run_from_task(task)
                failures.extend(run.get("failure_cases") or [])
        return JSONResponse({
            "schema": RUN_SCHEMA_VERSION,
            "failure_cases": failures[:capped],
            "count": len(failures),
            "durable": False,
        })


    async def api_runtime_evidence_chains(self, include_regression: bool = False, limit: int = 200):
        """Return only judge-safe evidence by default; fixtures stay explicitly separated."""
        capped = max(5, min(int(limit or 200), 500))
        runs = self.memory_store_provider().list_run_records(limit=capped) if self.memory_store_provider() else []
        payload = CompetitionEvidenceService().catalog(runs, include_regression=bool(include_regression))
        payload["durable"] = bool(self.memory_store_provider())
        return JSONResponse(payload)


    async def api_runtime_evidence_chain_verify(self, request: Request):
        data = await request.json()
        run = data.get("run") if isinstance(data, dict) and isinstance(data.get("run"), dict) else data
        if not isinstance(run, dict):
            raise HTTPException(400, "run must be an object")
        return JSONResponse(CompetitionEvidenceService.validate(run))
