"""Read endpoints for runtime tasks, registered behind the workbench access gate."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from services.task_service import TaskService


def create_task_query_router(
    get_service: Callable[[], TaskService],
    *,
    memory_available: Callable[[], bool],
    events_available: Callable[[], bool],
    worker_status: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(prefix="/api/tasks")

    @router.get("")
    async def api_tasks(session_id: str = "", status: str = "", limit: int = 50):
        rows = get_service().list(session_id=session_id, status=status, limit=limit)
        return JSONResponse({"tasks": rows, "count": len(rows)})

    @router.get("/queue")
    async def api_tasks_queue(status: str = "", limit: int = 50):
        statuses = [item.strip() for item in status.split(",") if item.strip()] if status else None
        rows = get_service().queue(statuses=statuses, limit=limit)
        return JSONResponse({"tasks": rows, "count": len(rows)})

    @router.get("/worker/status")
    async def api_tasks_worker_status():
        return JSONResponse(worker_status())

    @router.get("/events")
    async def api_task_events(session_id: str = "", after_id: int = 0, limit: int = 100):
        if not events_available():
            return JSONResponse({"events": [], "count": 0}, status_code=503)
        rows = get_service().events(session_id=session_id, after_id=after_id, limit=limit)
        return JSONResponse({"events": rows, "count": len(rows)})

    @router.get("/stream")
    async def api_task_stream(session_id: str = "", after_id: int = 0):
        if not memory_available():
            raise HTTPException(503, "MemoryOS not initialized")

        async def gen():
            cursor = int(after_id or 0)
            for _ in range(180):
                rows = get_service().events(session_id=session_id, after_id=cursor, limit=50)
                if rows:
                    cursor = max(int(row["id"]) for row in rows)
                    yield f"event: task_events\ndata: {json.dumps(rows, ensure_ascii=False)}\n\n"
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @router.get("/{task_id}")
    async def api_task_detail(task_id: int):
        detail = get_service().detail(task_id)
        if not detail:
            raise HTTPException(404, "Task not found")
        return JSONResponse(detail)

    return router
