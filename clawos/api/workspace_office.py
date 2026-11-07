"""Workspace office HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request


class WorkspaceOfficeAPI:
    def __init__(self, *,
        get_office_productivity_service: Callable[..., Any],
        workspace_services_provider: Callable[[], Any],
    ):
        self.get_office_productivity_service = get_office_productivity_service
        self.workspace_services_provider = workspace_services_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workspace/office/spreadsheets', self.api_office_spreadsheet_create, methods=['POST'])
        self.router.add_api_route('/api/workspace/office/spreadsheets/edit', self.api_office_spreadsheet_edit, methods=['POST'])
        self.router.add_api_route('/api/workspace/office/presentations', self.api_office_presentation_create, methods=['POST'])
        self.router.add_api_route('/api/workspace/office/presentations/edit', self.api_office_presentation_edit, methods=['POST'])
        self.router.add_api_route('/api/workspace/office/productivity', self.api_office_productivity, methods=['POST'])

    async def api_office_spreadsheet_create(self, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for office writes")
        try:
            artifact = self.workspace_services_provider().create_spreadsheet(
                data.get("output_path", ""),
                sheets=data.get("sheets", []),
                title=data.get("title", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"artifact": artifact})


    async def api_office_spreadsheet_edit(self, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for office writes")
        try:
            artifact = self.workspace_services_provider().edit_spreadsheet(
                data.get("file_path", ""),
                updates=data.get("updates", []),
                output_path=data.get("output_path", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"artifact": artifact})


    async def api_office_presentation_create(self, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for office writes")
        try:
            artifact = self.workspace_services_provider().create_presentation(
                data.get("output_path", ""),
                title=data.get("title", ""),
                slides=data.get("slides", []),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"artifact": artifact})


    async def api_office_presentation_edit(self, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for office writes")
        try:
            artifact = self.workspace_services_provider().edit_presentation(
                data.get("file_path", ""),
                replacements=data.get("replacements", {}),
                output_path=data.get("output_path", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"artifact": artifact})


    async def api_office_productivity(self, request: Request):
        data = await request.json()
        action = str(data.get("action") or "inspect")
        service = self.get_office_productivity_service()
        try:
            if action == "capabilities":
                result = service.capabilities()
            elif action == "create":
                result = service.create(data.get("output_path", ""), title=data.get("title", ""), sections=data.get("sections") or [], data=data.get("data"), metadata=data.get("metadata") or {}, confirmed=bool(data.get("confirmed")))
            elif action == "edit":
                result = service.edit(data.get("file_path", ""), data.get("output_path", ""), replacements=data.get("replacements") or {}, updates=data.get("updates") or [], comments=data.get("comments") or [], revisions=data.get("revisions") or [], recalculate=bool(data.get("recalculate")), confirmed=bool(data.get("confirmed")))
            elif action == "inspect":
                result = service.inspect(data.get("file_path", ""))
            elif action == "quality_audit":
                result = service.quality_audit(data.get("file_path", ""), template_path=data.get("template_path", ""), strict_visual=bool(data.get("strict_visual")))
            elif action == "data_analysis":
                result = service.analyze_data(data.get("rows") or [], data.get("output_path", ""), title=data.get("title", "Data Analysis"), group_by=data.get("group_by", ""), metrics=data.get("metrics") or [], confirmed=bool(data.get("confirmed")))
            elif action == "meeting_package":
                result = service.meeting_package(data.get("meeting") or {}, data.get("output_dir", ""), recipients=data.get("recipients") or [], confirmed=bool(data.get("confirmed")))
            elif action == "email_draft":
                result = service.create_email_draft(data.get("output_path", ""), subject=data.get("subject", ""), body=data.get("body", ""), to=data.get("to") or [], cc=data.get("cc") or [], attachments=data.get("attachments") or [], confirmed=bool(data.get("confirmed")))
            elif action == "calendar_draft":
                result = service.create_calendar_event(data.get("output_path", ""), summary=data.get("summary", ""), start=data.get("start", ""), duration_minutes=data.get("duration_minutes", 60), attendees=data.get("attendees") or [], description=data.get("description", ""), location=data.get("location", ""), organizer=data.get("organizer", ""), alarm_minutes=data.get("alarm_minutes", 15), confirmed=bool(data.get("confirmed")))
            elif action == "email_send":
                result = service.send_email(data.get("file_path", ""), data.get("connector") or {}, confirmed=bool(data.get("confirmed")), idempotency_key=data.get("idempotency_key", ""))
            elif action == "calendar_publish":
                result = service.publish_calendar(data.get("file_path", ""), data.get("connector") or {}, confirmed=bool(data.get("confirmed")), idempotency_key=data.get("idempotency_key", ""))
            else:
                raise ValueError(f"unknown office productivity action: {action}")
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(409 if isinstance(exc, PermissionError) else 400, str(exc))
        return JSONResponse(result)
