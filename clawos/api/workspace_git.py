"""Workspace git HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request


class WorkspaceGitAPI:
    def __init__(self, *,
        workspace_services_provider: Callable[[], Any],
    ):
        self.workspace_services_provider = workspace_services_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workspace/git/snapshot', self.api_git_snapshot, methods=['GET'])
        self.router.add_api_route('/api/workspace/git/commit-plan', self.api_git_commit_plan, methods=['POST'])
        self.router.add_api_route('/api/workspace/git/change-requests', self.api_git_change_request, methods=['POST'])
        self.router.add_api_route('/api/workspace/git/change-requests/{request_id}/approve', self.api_git_change_request_approve, methods=['POST'])
        self.router.add_api_route('/api/workspace/git/change-requests/{request_id}/rollback', self.api_git_change_request_rollback, methods=['POST'])

    async def api_git_snapshot(self, path: str):
        try:
            return JSONResponse(self.workspace_services_provider().git_snapshot(path))
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))


    async def api_git_commit_plan(self, request: Request):
        data = await request.json()
        try:
            plan = self.workspace_services_provider().prepare_commit_plan(
                data.get("path", ""),
                data.get("message", ""),
                data.get("files"),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"plan": plan})


    async def api_git_change_request(self, request: Request):
        data = await request.json()
        try:
            item = self.workspace_services_provider().create_git_change_request(
                data.get("path", ""),
                data.get("message", ""),
                data.get("files"),
                created_by=data.get("created_by", "user"),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"change_request": item})


    async def api_git_change_request_approve(self, request_id: int, request: Request):
        data = await request.json()
        try:
            item = self.workspace_services_provider().approve_git_change_request(
                request_id,
                approved_by=data.get("approved_by", "user"),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"change_request": item})


    async def api_git_change_request_rollback(self, request_id: int, request: Request):
        data = await request.json()
        try:
            item = self.workspace_services_provider().rollback_git_change_request(
                request_id,
                actor_id=data.get("actor_id", "user"),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"change_request": item})
