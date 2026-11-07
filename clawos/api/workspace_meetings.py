"""Workspace meetings HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi import Request
from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool
from memoryos.document_ingestion import safe_filename
import time


class WorkspaceMeetingsAPI:
    def __init__(self, *,
        upload_dir_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
        workspace_services_provider: Callable[[], Any],
    ):
        self.upload_dir_provider = upload_dir_provider
        self.vector_store_provider = vector_store_provider
        self.workspace_services_provider = workspace_services_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workspace/meetings', self.api_meeting_create, methods=['POST'])
        self.router.add_api_route('/api/workspace/meetings/{meeting_id}/transcript', self.api_meeting_transcript, methods=['POST'])
        self.router.add_api_route('/api/workspace/meetings/audio', self.api_meeting_audio_import, methods=['POST'])
        self.router.add_api_route('/api/workspace/meetings/audio/upload', self.api_meeting_audio_upload, methods=['POST'])
        self.router.add_api_route('/api/workspace/meetings/{meeting_id}/connector-drafts', self.api_meeting_connector_drafts, methods=['POST'])
        self.router.add_api_route('/api/workspace/meetings/{meeting_id}', self.api_meeting_detail, methods=['GET'])

    async def api_meeting_create(self, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for meeting writes")
        meeting = self.workspace_services_provider().create_meeting(
            data.get("title", "Untitled meeting"),
            data.get("meeting_date", ""),
            data.get("attendees", []),
            data.get("agenda", []),
        )
        return JSONResponse({"meeting": meeting})


    async def api_meeting_transcript(self, meeting_id: int, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for meeting writes")
        meeting = self.workspace_services_provider().process_meeting_transcript(
            meeting_id, data.get("transcript", "")
        )
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse({"meeting": meeting})


    async def api_meeting_audio_import(self, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for meeting writes")
        try:
            result = await run_in_threadpool(self.workspace_services_provider().import_meeting_audio,
                data.get("audio_path", ""),
                transcript_path=data.get("transcript_path", ""),
                transcript=data.get("transcript", ""),
                title=data.get("title", ""),
                meeting_id=data.get("meeting_id"),
                output_dir=data.get("output_dir", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse(result)


    async def api_meeting_audio_upload(self,
        audio: UploadFile = File(...),
        transcript_file: UploadFile | None = File(None),
        title: str = Form(""),
        transcript: str = Form(""),
        meeting_id: str = Form(""),
        confirmed: bool = Form(False),
    ):
        if confirmed is not True:
            raise HTTPException(409, "confirmed=true is required for meeting audio processing")
        filename = safe_filename(audio.filename or "meeting.wav")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
            raise HTTPException(400, "supported audio files: wav, mp3, m4a, flac, ogg")
        upload_root = self.upload_dir_provider() / "meeting_audio"
        upload_root.mkdir(parents=True, exist_ok=True)
        stamp = str(int(time.time() * 1000)) + '_' + __import__('uuid').uuid4().hex[:12]
        audio_path = upload_root / f"{stamp}_{filename}"
        audio_bytes = await audio.read(100_000_001)
        if not audio_bytes or len(audio_bytes) > 100_000_000:
            raise HTTPException(400, "meeting audio must be between 1 byte and 100 MB")
        if suffix == ".wav" and not (audio_bytes.startswith(b"RIFF") and b"WAVE" in audio_bytes[:16]):
            raise HTTPException(400, "invalid WAV signature")
        audio_path.write_bytes(audio_bytes)

        transcript_path = ""
        if transcript_file and transcript_file.filename:
            transcript_name = safe_filename(transcript_file.filename or "transcript.txt")
            transcript_path_obj = upload_root / f"{stamp}_{transcript_name}"
            transcript_bytes = await transcript_file.read(5_000_001)
            if len(transcript_bytes) > 5_000_000:
                raise HTTPException(400, "transcript file exceeds 5 MB")
            transcript_path_obj.write_bytes(transcript_bytes)
            transcript_path = str(transcript_path_obj)

        try:
            result = await run_in_threadpool(self.workspace_services_provider().import_meeting_audio,
                str(audio_path),
                transcript_path=transcript_path,
                transcript=transcript,
                title=title or Path(filename).stem,
                meeting_id=int(meeting_id) if str(meeting_id or "").strip() else None,
                output_dir=str(upload_root / "artifacts"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse(result)


    async def api_meeting_connector_drafts(self, meeting_id: int, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for connector draft writes")
        try:
            result = self.workspace_services_provider().draft_meeting_connectors(
                meeting_id,
                data.get("output_dir", ""),
                calendar=bool(data.get("calendar", True)),
                email=bool(data.get("email", True)),
                recipients=data.get("recipients", []),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_meeting_detail(self, meeting_id: int):
        meeting = self.workspace_services_provider().get_meeting(meeting_id)
        if not meeting:
            raise HTTPException(404, "Meeting not found")
        return JSONResponse({"meeting": meeting})
