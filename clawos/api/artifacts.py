"""Artifacts HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi.responses import FileResponse
from fastapi import HTTPException
from fastapi.responses import JSONResponse


class ArtifactsAPI:
    def __init__(self, *,
        get_artifact_delivery_service: Callable[..., Any],
    ):
        self.get_artifact_delivery_service = get_artifact_delivery_service
        self.router = APIRouter()
        self.router.add_api_route('/api/artifacts/{artifact_id}', self.api_artifact_metadata, methods=['GET'])
        self.router.add_api_route('/api/artifacts/{artifact_id}/download', self.api_artifact_download, methods=['GET'])
        self.router.add_api_route('/api/artifacts/{artifact_id}/preview', self.api_artifact_preview, methods=['GET'])

    async def api_artifact_metadata(self, artifact_id: str):
        try:
            item, _ = self.get_artifact_delivery_service().resolve(artifact_id)
        except KeyError:
            raise HTTPException(404, "Artifact not found")
        except FileNotFoundError:
            raise HTTPException(410, "Artifact file is unavailable")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return JSONResponse({key: value for key, value in item.items() if key != "path"})


    async def api_artifact_download(self, artifact_id: str):
        try:
            item, path = self.get_artifact_delivery_service().resolve(artifact_id)
        except KeyError:
            raise HTTPException(404, "Artifact not found")
        except FileNotFoundError:
            raise HTTPException(410, "Artifact file is unavailable")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return FileResponse(path, media_type=item.get("mime_type"), filename=item.get("name") or path.name)


    async def api_artifact_preview(self, artifact_id: str):
        try:
            item, path = self.get_artifact_delivery_service().resolve(artifact_id)
        except KeyError:
            raise HTTPException(404, "Artifact not found")
        except FileNotFoundError:
            raise HTTPException(410, "Artifact file is unavailable")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        suffix = path.suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".md", ".markdown", ".txt", ".csv", ".json", ".diff", ".patch"}:
            raise HTTPException(415, "Artifact type is not previewable")
        media = item.get("mime_type") or "application/octet-stream"
        if suffix in {".md", ".markdown", ".txt", ".csv", ".json", ".diff", ".patch"}:
            media = "text/plain; charset=utf-8"
        return FileResponse(path, media_type=media, headers={"Content-Disposition": "inline"})
