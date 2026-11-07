"""Tasks HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import re


class TasksAPI:
    def __init__(self, *,
        cancel_runtime_task: Callable[..., Any],
        claim_runtime_task: Callable[..., Any],
        enqueue_runtime_task: Callable[..., Any],
        get_task_service: Callable[..., Any],
        retry_runtime_task: Callable[..., Any],
        run_background_worker_once: Callable[..., Any],
        start_background_worker: Callable[..., Any],
        stop_background_worker: Callable[..., Any],
    ):
        self.cancel_runtime_task = cancel_runtime_task
        self.claim_runtime_task = claim_runtime_task
        self.enqueue_runtime_task = enqueue_runtime_task
        self.get_task_service = get_task_service
        self.retry_runtime_task = retry_runtime_task
        self.run_background_worker_once = run_background_worker_once
        self.start_background_worker = start_background_worker
        self.stop_background_worker = stop_background_worker
        self.router = APIRouter()
        self.router.add_api_route('/api/tasks/queue/claim', self.api_tasks_queue_claim, methods=['POST'])
        self.router.add_api_route('/api/tasks/recover', self.api_tasks_recover, methods=['POST'])
        self.router.add_api_route('/api/tasks/worker/tick', self.api_tasks_worker_tick, methods=['POST'])
        self.router.add_api_route('/api/tasks/worker/start', self.api_tasks_worker_start, methods=['POST'])
        self.router.add_api_route('/api/tasks/worker/stop', self.api_tasks_worker_stop, methods=['POST'])
        self.router.add_api_route('/api/tasks/jobs/report', self.api_tasks_job_report, methods=['POST'])
        self.router.add_api_route('/api/tasks/jobs/ocr-queue', self.api_tasks_job_ocr_queue, methods=['POST'])
        self.router.add_api_route('/api/tasks/jobs/batch-ingest', self.api_tasks_job_batch_ingest, methods=['POST'])
        self.router.add_api_route('/api/tasks/events/prune', self.api_task_events_prune, methods=['POST'])
        self.router.add_api_route('/api/tasks/{task_id}/cancel', self.api_task_cancel, methods=['POST'])
        self.router.add_api_route('/api/tasks/{task_id}/retry', self.api_task_retry, methods=['POST'])

    async def api_tasks_queue_claim(self, request: Request):
        data = await request.json()
        statuses = data.get("statuses")
        if isinstance(statuses, str):
            statuses = [item.strip() for item in statuses.split(",") if item.strip()]
        elif not isinstance(statuses, list):
            statuses = None
        task = self.claim_runtime_task(
            worker_id=str(data.get("worker_id", "worker")),
            statuses=statuses,
        )
        return JSONResponse({"task": task, "claimed": bool(task)})


    async def api_tasks_recover(self, request: Request):
        data = await request.json()
        result = self.get_task_service().recover(
            actor_id=str(data.get("actor_id", "user")),
            create_retries=bool(data.get("create_retries", False)),
        )
        return JSONResponse(result)


    async def api_tasks_worker_tick(self, request: Request):
        data = await request.json()
        result = await self.run_background_worker_once(
            worker_id=str(data.get("worker_id") or "api-worker"),
            max_attempts=int(data.get("max_attempts") or 3),
        )
        return JSONResponse(result)


    async def api_tasks_worker_start(self, request: Request):
        data = await request.json()
        return JSONResponse(await self.start_background_worker(data))

    async def api_tasks_worker_stop(self):
        return JSONResponse(await self.stop_background_worker())

    async def api_tasks_job_report(self, request: Request):
        data = await request.json()
        document_id = int(data.get("library_document_id") or data.get("document_id") or 0)
        if not document_id:
            raise HTTPException(400, "library_document_id is required")
        metadata = {
            "worker_action": "generate_report",
            "library_document_id": document_id,
            "report_style": data.get("report_style", "journal"),
            "depth": data.get("depth", 5),
            "question_count": data.get("question_count", 40),
            "output_dir": data.get("output_dir", "output/reports"),
            "formats": data.get("formats") or ["markdown", "pdf"],
            "idempotency_key": data.get("idempotency_key", ""),
        }
        task = self.enqueue_runtime_task("worker-jobs", f"Generate report for document {document_id}", metadata=metadata)
        return JSONResponse({"queued": True, "task": task})


    async def api_tasks_job_ocr_queue(self, request: Request):
        data = await request.json()
        metadata = {
            "worker_action": "process_ocr_queue",
            "category": data.get("category", ""),
            "limit": data.get("limit", 12),
            "force": bool(data.get("force", True)),
            "idempotency_key": data.get("idempotency_key", ""),
        }
        task = self.enqueue_runtime_task("worker-jobs", "Process OCR queue", metadata=metadata)
        return JSONResponse({"queued": True, "task": task})


    async def api_tasks_job_batch_ingest(self, request: Request):
        data = await request.json()
        files = data.get("files") or data.get("paths") or []
        if isinstance(files, str):
            files = [item.strip() for item in re.split(r"[\n,;]+", files) if item.strip()]
        if not isinstance(files, list) or not files:
            raise HTTPException(400, "files must be a non-empty list")
        metadata = {
            "worker_action": "batch_ingest_documents",
            "files": files,
            "category": data.get("category", "domain"),
            "limit": data.get("limit", 24),
            "idempotency_key": data.get("idempotency_key", ""),
        }
        task = self.enqueue_runtime_task("worker-jobs", f"Batch ingest {len(files)} documents", metadata=metadata)
        return JSONResponse({"queued": True, "task": task})


    async def api_task_events_prune(self, request: Request):
        data = await request.json()
        result = self.get_task_service().prune_events(
            older_than_days=data.get("older_than_days", 30),
            retain_latest_per_task=data.get("retain_latest_per_task", 100),
            dry_run=bool(data.get("dry_run", False)),
            actor_id=str(data.get("actor_id", "user")),
        )
        return JSONResponse(result)


    async def api_task_cancel(self, task_id: int, request: Request):
        data = await request.json()
        item = self.cancel_runtime_task(
            task_id,
            reason=str(data.get("reason", "")),
            actor_id=str(data.get("actor_id", "user")),
        )
        return JSONResponse({"task": item})


    async def api_task_retry(self, task_id: int, request: Request):
        data = await request.json()
        item = self.retry_runtime_task(
            task_id,
            reason=str(data.get("reason", "")),
            actor_id=str(data.get("actor_id", "user")),
        )
        return JSONResponse({"task": item})
