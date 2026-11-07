"""Coding HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import json
import re


class CodingAPI:
    def __init__(self, *,
        get_artifact_delivery_service: Callable[..., Any],
        output_root_provider: Callable[[], Any],
    ):
        self.get_artifact_delivery_service = get_artifact_delivery_service
        self.output_root_provider = output_root_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/coding/workspaces', self.api_coding_workspaces, methods=['GET'])
        self.router.add_api_route('/api/coding/workspaces/{workspace_id}/rollback', self.api_coding_workspace_rollback, methods=['POST'])
        self.router.add_api_route('/api/coding/workspaces/prune', self.api_coding_workspaces_prune, methods=['POST'])

    async def api_coding_workspaces(self):
        from services.coding_workspace_service import CodingWorkspaceService

        root = self.output_root_provider() / "coding" / "workspaces"
        rows = CodingWorkspaceService().list_tasks(root)
        public = []
        for row in rows:
            changes = dict(row.get("changes") or {})
            public.append({
                "id": row.get("id"), "task_id": row.get("task_id"),
                "branch": row.get("branch"),
                "source_dirty": bool(row.get("source_dirty")),
                "changed_files": changes.get("changed_files") or [],
                "status": changes.get("status") or [],
                "patch_sha256": changes.get("patch_sha256") or "",
                "patch_available": bool(changes.get("patch_path")),
                "source_verification": row.get("source_verification") or {},
                "lifecycle": row.get("lifecycle") or {},
            })
        return JSONResponse({"workspaces": public, "count": len(public)})


    async def api_coding_workspace_rollback(self, workspace_id: str, request: Request):
        from services.coding_workspace_service import CodingWorkspaceService

        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", str(workspace_id or "")):
            raise HTTPException(400, "Invalid workspace id")
        body = await request.json()
        if body.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for rollback")
        root = (self.output_root_provider() / "coding" / "workspaces").resolve()
        metadata_path = (root / workspace_id / "workspace.json").resolve()
        try:
            metadata_path.relative_to(root)
        except ValueError:
            raise HTTPException(400, "Workspace path escapes coding root")
        if not metadata_path.is_file():
            raise HTTPException(404, "Task workspace not found")
        try:
            result = CodingWorkspaceService().rollback_task(
                metadata_path, confirmed=True,
            )
            artifact = self.get_artifact_delivery_service().register(
                result["recovery_manifest"], source_tool="coding_workspace_rollback",
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({
            "rolled_back": True, "workspace_id": workspace_id,
            "baseline_commit": result.get("baseline_commit"),
            "recoverable": True, "recovery_artifact": artifact,
            "source_mutated": False,
        })


    async def api_coding_workspaces_prune(self, request: Request):
        from services.coding_workspace_service import CodingWorkspaceService

        body = await request.json()
        dry_run = bool(body.get("dry_run", True))
        try:
            result = CodingWorkspaceService().prune_tasks(
                self.output_root_provider() / "coding" / "workspaces",
                max_age_hours=int(body.get("max_age_hours") or 168),
                dry_run=dry_run,
                confirmed=body.get("confirmed") is True,
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse(result)
