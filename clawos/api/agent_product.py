"""Modular API for the unified agent product contracts."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services.agent_product_kernel import AgentProductKernel, TaskRunContract
from services.coding_context_service import CodingContextService
from services.os_sandbox import WindowsJobSandbox
from services.task_service import TaskService


def create_agent_product_router(
    store_provider: Callable[[], Any],
    repository_root: str | Path,
) -> APIRouter:
    router = APIRouter(tags=["agent-product"])
    context = CodingContextService()

    def service() -> TaskService:
        store = store_provider()
        if not store:
            raise HTTPException(503, "MemoryOS not initialized")
        return TaskService(store)

    @router.get("/api/agent-product/contracts")
    async def contracts() -> JSONResponse:
        return JSONResponse(AgentProductKernel.contracts())

    @router.post("/api/agent-product/task-runs")
    async def create_task_run(request: Request) -> JSONResponse:
        data = await request.json()
        title = str(data.get("title") or data.get("objective") or "").strip()
        if not title:
            raise HTTPException(400, "title or objective is required")
        metadata = dict(data.get("metadata") or {})
        metadata.update({
            "protocol": TaskRunContract.SCHEMA,
            "actor_id": str(data.get("actor_id") or "local-user"),
            "surface": str(data.get("surface") or "api"),
        })
        task = service().enqueue(
            str(data.get("session_id") or "default"),
            title,
            source=str(data.get("source") or "agent-product"),
            metadata=metadata,
        )
        detail = service().detail(int(task["id"]))
        return JSONResponse(TaskRunContract.envelope(detail))

    @router.get("/api/agent-product/task-runs/{task_id}")
    async def task_run(task_id: int) -> JSONResponse:
        detail = service().detail(task_id)
        if not detail:
            raise HTTPException(404, "task run not found")
        return JSONResponse(TaskRunContract.envelope(detail))

    @router.get("/api/agent-product/task-runs/{task_id}/events")
    async def task_run_events(task_id: int) -> JSONResponse:
        detail = service().detail(task_id)
        if not detail:
            raise HTTPException(404, "task run not found")
        return JSONResponse({
            "schema": "clawos.task-run-events.v1",
            "run_id": str(task_id),
            "events": detail.get("events") or [],
        })

    @router.post("/api/agent-product/task-runs/{task_id}/transition")
    async def transition_task_run(task_id: int, request: Request) -> JSONResponse:
        data = await request.json()
        store = service().require_store()
        try:
            item = store.transition_task(
                task_id,
                str(data.get("status") or ""),
                actor_id=str(data.get("actor_id") or "local-user"),
                reason=str(data.get("reason") or ""),
                checkpoint=data.get("checkpoint") or {},
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not item:
            raise HTTPException(404, "task run not found")
        return JSONResponse(TaskRunContract.envelope(service().detail(task_id)))

    @router.post("/api/agent-product/context/explain")
    async def explain_context(request: Request) -> JSONResponse:
        data = await request.json()
        manifest = data.get("manifest")
        if not isinstance(manifest, dict):
            repo = str(data.get("repo_path") or repository_root)
            objective = str(data.get("objective") or "").strip()
            if not objective:
                raise HTTPException(400, "manifest or objective is required")
            manifest = context.build(
                repo, objective,
                focus_paths=data.get("focus_paths") or [],
                diagnostics=data.get("diagnostics") or [],
                token_budget=int(data.get("token_budget") or 12000),
            )
        return JSONResponse(AgentProductKernel.explain_context(manifest))

    @router.get("/api/agent-product/memories/{memory_id}/explain")
    async def explain_memory(memory_id: int) -> JSONResponse:
        try:
            result = AgentProductKernel.explain_memory(
                service().require_store(), memory_id
            )
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return JSONResponse(result)

    @router.post("/api/agent-product/memories/{memory_id}/enabled")
    async def control_memory(memory_id: int, request: Request) -> JSONResponse:
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(400, "confirmed=true is required")
        item = service().require_store().set_memory_enabled(
            memory_id,
            bool(data.get("enabled")),
            actor_id=str(data.get("actor_id") or "local-user"),
            change_reason=str(data.get("reason") or "user personalization control"),
        )
        if not item:
            raise HTTPException(404, "memory not found")
        return JSONResponse(AgentProductKernel.explain_memory(
            service().require_store(), memory_id
        ))

    @router.post("/api/agent-product/plugins/validate")
    async def validate_plugin(request: Request) -> JSONResponse:
        data = await request.json()
        return JSONResponse(AgentProductKernel.validate_plugin(
            data.get("manifest") or {}, data.get("granted_capabilities") or []
        ))

    @router.post("/api/agent-product/agent-graphs/validate")
    async def validate_agent_graph(request: Request) -> JSONResponse:
        return JSONResponse(AgentProductKernel.validate_agent_graph(
            await request.json()
        ))

    @router.post("/api/agent-product/sandbox/plan")
    async def sandbox_plan(request: Request) -> JSONResponse:
        return JSONResponse(AgentProductKernel.sandbox_plan(
            await request.json()
        ))

    @router.post("/api/agent-product/sandbox/probe")
    async def sandbox_probe(request: Request) -> JSONResponse:
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(400, "confirmed=true is required")
        try:
            result = WindowsJobSandbox(
                max_processes=int(data.get("max_processes") or 1),
                process_memory_mb=int(data.get("process_memory_mb") or 256),
            ).run_probe(str(data.get("workspace") or repository_root))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)

    return router
