"""Subagents HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
from dataclasses import asdict
import asyncio


class SubagentsAPI:
    def __init__(self, *,
        get_autonomous_subagent_service: Callable[..., Any],
        get_reliable_collaboration_service: Callable[..., Any],
    ):
        self.get_autonomous_subagent_service = get_autonomous_subagent_service
        self.get_reliable_collaboration_service = get_reliable_collaboration_service
        self.router = APIRouter()
        self.router.add_api_route('/api/subagents/run', self.api_autonomous_subagents, methods=['POST'])
        self.router.add_api_route('/api/subagents/collaboration/{run_id}', self.api_collaboration_progress, methods=['GET'])
        self.router.add_api_route('/api/subagents/collaboration/{run_id}/delivery', self.api_collaboration_delivery, methods=['GET', 'POST'])
        self.router.add_api_route('/api/subagents/collaboration/{run_id}/delivery/approve', self.api_collaboration_delivery_approve, methods=['POST'])

    async def api_autonomous_subagents(self, request: Request):
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(400,"request must be an object")
        if data.get("team_profile") == "reliable_coding":
            try:
                result = await self.get_reliable_collaboration_service().run(
                    data.get("repo_path", ""), data.get("objective", ""),
                    allowed_paths=data.get("allowed_paths") or [],
                    test_commands=data.get("test_commands") or [],
                    confirmed=data.get("confirmed") is True,
                    resume_run=data.get("resume_run", ""),
                    actor=data.get("actor", "coordinator"), limits=data.get("limits") or None,
                    requirements=data.get('requirements'))
            except (ValueError, PermissionError, RuntimeError, TimeoutError) as exc:
                raise HTTPException(409 if isinstance(exc, (PermissionError, TimeoutError)) else 400, str(exc))
            return JSONResponse(result)
        roles = data.get("roles") or []
        if data.get("team_profile") == "advanced_data_analysis" and not roles:
            roles = [asdict(item) for item in self.get_autonomous_subagent_service().advanced_data_team(data.get("objective", ""), source_description=data.get("source_description", "tabular dataset"))]
        if not isinstance(roles, list) or not roles:
            raise HTTPException(400, "roles must be a non-empty list")
        try:
            result = await self.get_autonomous_subagent_service().run(
                data.get("objective", ""),
                roles,
                shared_evidence=data.get("shared_evidence") or [],
                confirmed_side_effect_tools=data.get("confirmed_tools") or [],
                run_budget=data.get("budget") or {},
                resume_checkpoint=data.get("resume_checkpoint", ""),
                review_cycle=data.get("review_cycle") or None,
                actor=data.get("actor", "coordinator"),
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(409 if isinstance(exc, PermissionError) else 400, str(exc))
        return JSONResponse(result)


    async def api_collaboration_progress(self, run_id: str):
        try:
            result = await asyncio.to_thread(self.get_reliable_collaboration_service(require_model=False).inspect, run_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_collaboration_delivery(self, run_id: str, request: Request):
        from services.collaboration_delivery import CollaborationDelivery
        service = CollaborationDelivery(self.get_reliable_collaboration_service(require_model=False))
        try:
            if request.method == 'GET':
                result = await asyncio.to_thread(service.inspect, run_id)
            else:
                data = await request.json()
                if not isinstance(data, dict):
                    raise ValueError('request must be an object')
                result = await service.prepare(run_id, confirmed=data.get('confirmed') is True)
        except (ValueError, PermissionError, RuntimeError, TimeoutError, OSError) as exc:
            raise HTTPException(409 if isinstance(exc, (PermissionError, TimeoutError)) else 400, str(exc))
        return JSONResponse(result)


    async def api_collaboration_delivery_approve(self, run_id: str, request: Request):
        from services.collaboration_delivery import CollaborationDelivery
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError('request must be an object')
            result = await asyncio.to_thread(CollaborationDelivery(self.get_reliable_collaboration_service(require_model=False)).approve,
                run_id, manifest_digest=data.get('manifest_digest'), actor=data.get('actor'),
                confirmed=data.get('confirmed') is True)
        except (ValueError, PermissionError, RuntimeError, TimeoutError, OSError) as exc:
            raise HTTPException(409 if isinstance(exc, (PermissionError, TimeoutError)) else 400, str(exc))
        return JSONResponse(result)
