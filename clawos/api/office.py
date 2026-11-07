"""Office HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import httpx
import os
import time


class OfficeAPI:
    def __init__(self, *,
        get_artifact_delivery_service: Callable[..., Any],
        logger_provider: Callable[[], Any],
    ):
        self.get_artifact_delivery_service = get_artifact_delivery_service
        self.logger_provider = logger_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/office/editor/capabilities', self.api_office_editor_capabilities, methods=['GET'])
        self.router.add_api_route('/api/office/editor/session', self.api_office_editor_session, methods=['POST'])
        self.router.add_api_route('/api/office/editor/callback/onlyoffice/{session_id}', self.api_onlyoffice_editor_callback, methods=['POST'])

    async def api_office_editor_capabilities(self):
        from services.office_editor_service import OfficeEditorService
        return JSONResponse(OfficeEditorService().capabilities())


    async def api_office_editor_session(self, request: Request):
        from services.office_editor_service import OfficeEditorService
        body = await request.json()
        try:
            item, path = self.get_artifact_delivery_service().resolve(str(body.get("artifact_id") or ""))
            public_base = os.environ.get("CLAWOS_PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")
            result = OfficeEditorService().create_session(
                str(body.get("provider") or "onlyoffice"), artifact_id=item["id"],
                file_name=path.name, sha256=item["sha256"], public_base_url=public_base,
                mode=str(body.get("mode") or "edit"), user_name=str(body.get("user_name") or "ClawOS User"),
            )
            return JSONResponse(result)
        except KeyError:
            raise HTTPException(404, "Artifact not found")
        except FileNotFoundError:
            raise HTTPException(410, "Artifact file is unavailable")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc))


    async def api_onlyoffice_editor_callback(self, session_id: str, request: Request):
        from urllib.parse import urlparse
        from services.office_editor_service import OfficeEditorService
        artifact_id = str(request.query_params.get("artifact_id") or "")
        try:
            expires = int(request.query_params.get("expires") or 0)
        except ValueError:
            expires = 0
        if not OfficeEditorService.validate_callback(session_id, artifact_id, expires, str(request.query_params.get("sig") or "")):
            raise HTTPException(403, "Invalid or expired editor callback")
        body = await request.json()
        status = int(body.get("status") or 0)
        if status not in {2, 6}:
            return JSONResponse({"error": 0})
        configured = urlparse(os.environ.get("ONLYOFFICE_DOCUMENT_SERVER_URL", ""))
        remote = urlparse(str(body.get("url") or ""))
        if not configured.hostname or remote.hostname != configured.hostname or remote.scheme not in {"https", "http"}:
            raise HTTPException(403, "Callback download URL is outside the configured document server")
        try:
            _, original = self.get_artifact_delivery_service().resolve(artifact_id)
            version = original.with_name(f"{original.stem}.edited-{int(time.time())}{original.suffix}")
            async with httpx.AsyncClient(follow_redirects=False, timeout=30) as client:
                response = await client.get(remote.geturl())
                response.raise_for_status()
                if len(response.content) > 100 * 1024 * 1024:
                    raise ValueError("Edited artifact exceeds 100 MiB")
                version.write_bytes(response.content)
            artifact = self.get_artifact_delivery_service().register(
                {"path": str(version), "format": version.suffix.lstrip("."), "valid": True, "operation": "embedded_editor_save"},
                source_tool="office_embedded_editor",
            )
            return JSONResponse({"error": 0, "artifact": artifact})
        except (KeyError, FileNotFoundError, ValueError, httpx.HTTPError, OSError) as exc:
            self.logger_provider().warning("OnlyOffice callback save failed: %s", exc)
            return JSONResponse({"error": 1})
