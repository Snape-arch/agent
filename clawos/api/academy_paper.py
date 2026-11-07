"""Academy paper HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from services import ArtifactStorage
from services.grounded_paper_report import GroundedPaperReport
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi import Request
from services.runtime_records import RunRecord
import base64
import json
import re
from services.artifact_storage import safe_artifact_slug
from memoryos.document_ingestion import safe_filename
import time


class AcademyPaperAPI:
    def __init__(self, *,
        _academy_offline_audit_payload: Callable[..., Any],
        output_root_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
    ):
        self._academy_offline_audit_payload = _academy_offline_audit_payload
        self.output_root_provider = output_root_provider
        self.memory_store_provider = memory_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/academy/paper/annotations', self.api_academy_paper_annotation_save, methods=['POST'])
        self.router.add_api_route('/api/academy/paper/status', self.api_academy_paper_status, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/checkpoint', self.api_academy_paper_checkpoint_save, methods=['POST'])
        self.router.add_api_route('/api/academy/paper/checkpoints', self.api_academy_paper_checkpoints, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/checkpoints/{run_id}', self.api_academy_paper_checkpoint_detail, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/project-board', self.api_academy_paper_project_board, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/project-board', self.api_academy_paper_project_item_save, methods=['POST'])
        self.router.add_api_route('/api/academy/paper/project-board/{run_id}/status', self.api_academy_paper_project_item_status, methods=['POST'])
        self.router.add_api_route('/api/academy/paper/project-board/export', self.api_academy_paper_project_board_export, methods=['POST'])
        self.router.add_api_route('/api/academy/paper/project-board/exports', self.api_academy_paper_project_exports, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/timeline', self.api_academy_paper_timeline, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/offline-audit', self.api_academy_paper_offline_audit, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/project-board/exports/{run_id}', self.api_academy_paper_project_export_detail, methods=['GET'])
        self.router.add_api_route('/api/academy/paper/knowledge-capture', self.api_academy_paper_knowledge_capture, methods=['POST'])

    async def api_academy_paper_annotation_save(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        try:
            document_id = int(data.get("document_id") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Invalid document id")
        if not document_id:
            raise HTTPException(400, "document_id is required")
        document = self.memory_store_provider().get_document(document_id)
        if not document:
            raise HTTPException(404, "Document not found")

        image_data = str(data.get("image_data") or "")
        prefix = "data:image/png;base64,"
        if not image_data.startswith(prefix):
            raise HTTPException(400, "image_data must be a PNG data URL")
        encoded = image_data[len(prefix):]
        if len(encoded) > 8 * 1024 * 1024:
            raise HTTPException(400, "annotation image is too large")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except Exception:
            raise HTTPException(400, "annotation image is not valid base64")
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(400, "annotation image must be PNG")

        title = str(data.get("title") or document.get("title") or document.get("filename") or f"document-{document_id}")[:160]
        page=data.get('page',0)
        if type(page) is not int or not 0<=page<=10000:raise HTTPException(400,'Invalid annotation page')
        revision=str(document.get('file_hash') or '')
        if data.get('source_revision') and data['source_revision']!=revision:raise HTTPException(409,'Source revision changed; reopen before saving annotation')
        coordinate_space=data.get('coordinate_space','viewport')
        if coordinate_space not in ('viewport','pdf_page'):raise HTTPException(400,'Invalid annotation coordinate space')
        stamp = int(time.time() * 1000)
        import uuid
        unique=uuid.uuid4().hex
        filename = safe_filename(f"{stamp}_{unique}_{title}_annotation.png")
        storage = ArtifactStorage(self.output_root_provider() / "academy" / "annotations")
        artifact = storage.write_bytes(filename, raw, kind="png")

        run = RunRecord(
            f"academy-annotation-{document_id}-{unique}",
            "academy_annotation",
            f"Academy paper annotation: {title}",
            status="pass",
            actor="user",
            scenario="research",
            inputs={"document_id": document_id, "title": title, "page":page,"source_revision":revision,"coordinate_space":coordinate_space},
            outputs={"artifact_path": artifact["path"]},
            tags=["academy", "paper", "annotation"],
        )
        run.add_artifact("annotation_png", f"Annotation for {title}", artifact["path"], storage=artifact)
        run.add_evidence("academy_paper_annotation", "User annotation is linked to the source document", citation=f"doc:{document_id}", document_id=document_id)
        saved_run = self.memory_store_provider().save_run_record(run.to_dict())
        return JSONResponse({"saved": True, "artifact": artifact, "run": saved_run, "document": document})


    def _latest_academy_run_for_document(self, run_type: str, document_id: int) -> dict[str, Any]:
        if not self.memory_store_provider():
            return {}
        for item in self.memory_store_provider().list_run_records(run_type=run_type, limit=100):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            inputs = run.get("inputs") or {}
            if int(inputs.get("document_id") or 0) == int(document_id):
                return run
        return {}


    def _academy_knowledge_for_document(self, document_id: int) -> dict[str, Any]:
        if not self.memory_store_provider():
            return {}
        marker = f"doc:{int(document_id)}"
        matches = []
        for item in self.memory_store_provider().list_knowledge("research"):
            source = str(item.get("source") or "")
            content = str(item.get("content") or "")
            if marker in source or marker in content:
                matches.append(item)
        if not matches:
            return {}
        return max(matches, key=lambda item: int(item.get("id") or 0))


    def _academy_paper_status_payload(self, document_id: int) -> dict[str, Any]:
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        document = self.memory_store_provider().get_document(document_id)
        if not document:
            raise HTTPException(404, "Document not found")
        chunks = self.memory_store_provider().get_document_chunks(document_id, 100)
        report_run = self._latest_academy_run_for_document("academy_paper_report", document_id)
        annotation_run = self._latest_academy_run_for_document("academy_annotation", document_id)
        checkpoint_run = self._latest_academy_run_for_document("academy_paper_checkpoint", document_id)
        knowledge = self._academy_knowledge_for_document(document_id)
        report = (report_run.get("outputs") or {}).get("report") or {}
        annotation_artifact = (annotation_run.get("artifacts") or [{}])[0] if annotation_run else {}
        checkpoint_artifact = (checkpoint_run.get("artifacts") or [{}])[0] if checkpoint_run else {}
        return {
            "ok": True,
            "document": document,
            "chunks": {"count": len(chunks), "ready": bool(chunks)},
            "report": {
                "ready": bool(report_run),
                "run_id": report_run.get("run_id", ""),
                "markdown_path": report.get("markdown_path", ""),
                "pdf_path": report.get("pdf_path", ""),
                "json_path": report.get('json_path') or (report.get('metadata') or {}).get('json_path', ''),
                "analysis": (report.get('metadata') or {}).get('synthesis', {}),
                "artifacts": (report.get('metadata') or {}).get('artifacts', []),
                "updated_at": report_run.get("updated_at", ""),
            },
            "knowledge": {
                "ready": bool(knowledge),
                "id": knowledge.get("id"),
                "title": knowledge.get("title", ""),
                "source": knowledge.get("source", ""),
            },
            "annotation": {
                "ready": bool(annotation_run),
                "run_id": annotation_run.get("run_id", ""),
                "artifact": annotation_artifact,
                "updated_at": annotation_run.get("updated_at", ""),
            },
            "checkpoint": {
                "ready": bool(checkpoint_run),
                "run_id": checkpoint_run.get("run_id", ""),
                "artifact": checkpoint_artifact,
                "updated_at": checkpoint_run.get("updated_at", ""),
            },
        }


    async def api_academy_paper_status(self, document_id: int):
        try:
            return JSONResponse(self._academy_paper_status_payload(document_id))
        except HTTPException as exc:
            if exc.status_code == 503:
                return JSONResponse({"ok": False, "error": exc.detail}, status_code=503)
            raise


    async def api_academy_paper_checkpoint_save(self, request: Request):
        if not self.memory_store_provider():
            return JSONResponse({"saved": False, "error": "MemoryOS not initialized"}, status_code=503)
        data = await request.json()
        document_id = int(data.get("document_id") or 0)
        if not document_id:
            raise HTTPException(400, "document_id is required")
        status = self._academy_paper_status_payload(document_id)
        document = status["document"]
        chunks = self.memory_store_provider().get_document_chunks(document_id, 12)
        title = str(document.get("title") or document.get("filename") or f"document-{document_id}")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        import uuid
        unique=uuid.uuid4().hex
        reading=data.get('reading') or {}
        if not isinstance(reading,dict) or type(reading.get('page',1)) is not int or not 1<=reading.get('page',1)<=10000:
            raise HTTPException(400,'Invalid reading position')
        checkpoint = {
            "schema": "clawos.academy.paper.checkpoint.v1",
            "created_at": stamp,
            "document": document,
            "status": status,
            "citation": data.get("citation") or {},
            "reading": {"page":reading.get('page',1),"source_revision":document.get('file_hash','')},
            "chunks": [
                {
                    "chunk_index": chunk.get("chunk_index"),
                    "citation": chunk.get("citation", ""),
                    "page": chunk.get("page"),
                    "preview": str(chunk.get("text") or chunk.get("content") or chunk.get("preview") or "")[:700],
                }
                for chunk in chunks
            ],
        }
        storage = ArtifactStorage(self.output_root_provider() / "academy" / "checkpoints")
        artifact = storage.write_json(f"{stamp}_{unique}_{safe_artifact_slug(title)}_checkpoint.json", checkpoint)
        report = status.get("report") or {}
        knowledge = status.get("knowledge") or {}
        annotation = status.get("annotation") or {}
        run = RunRecord(
            run_id=f"academy-paper-checkpoint-{document_id}-{unique}",
            run_type="academy_paper_checkpoint",
            title=f"Academy paper checkpoint: {title}",
            status="pass",
            actor="user",
            scenario="research",
            inputs={"document_id": document_id, "title": title},
            outputs={
                "checkpoint_path": artifact["path"],
                "report_run_id": report.get("run_id", ""),
                "knowledge_id": knowledge.get("id"),
                "annotation_run_id": annotation.get("run_id", ""),
                "chunk_count": status.get("chunks", {}).get("count", 0),
            },
            tags=["academy", "paper", "checkpoint"],
        )
        run.add_artifact("checkpoint_json", f"Checkpoint for {title}", artifact["path"], storage=artifact)
        run.add_evidence("academy_paper_checkpoint", "Checkpoint bundles document metadata, report, knowledge, annotation, and citation evidence", citation=f"doc:{document_id}", document_id=document_id)
        saved_run = self.memory_store_provider().save_run_record(run.to_dict())
        status["checkpoint"] = {
            "ready": True,
            "run_id": saved_run.get("run_id", ""),
            "artifact": saved_run.get("artifacts", [{}])[0] if saved_run.get("artifacts") else {},
            "updated_at": saved_run.get("updated_at", ""),
        }
        checkpoint["status"] = status
        return JSONResponse({"saved": True, "checkpoint": checkpoint, "artifact": artifact, "run": saved_run, "status": status})


    def _academy_checkpoint_artifact_path(self, run: dict[str, Any]) -> Path | None:
        for artifact in run.get("artifacts") or []:
            if artifact.get("kind") != "checkpoint_json":
                continue
            storage = (artifact.get("metadata") or {}).get("storage") or {}
            raw_path = artifact.get("uri") or storage.get("path") or ""
            if raw_path:
                return Path(str(raw_path)).expanduser().resolve()
        return None


    def _academy_checkpoint_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        inputs = run.get("inputs") or {}
        outputs = run.get("outputs") or {}
        artifact = (run.get("artifacts") or [{}])[0] if run.get("artifacts") else {}
        return {
            "run_id": run.get("run_id", ""),
            "title": run.get("title", ""),
            "updated_at": run.get("updated_at", ""),
            "document_id": inputs.get("document_id"),
            "document_title": inputs.get("title", ""),
            "checkpoint_path": outputs.get("checkpoint_path", ""),
            "report_run_id": outputs.get("report_run_id", ""),
            "knowledge_id": outputs.get("knowledge_id"),
            "annotation_run_id": outputs.get("annotation_run_id", ""),
            "chunk_count": outputs.get("chunk_count", 0),
            "artifact": artifact,
        }


    async def api_academy_paper_checkpoints(self, document_id: int = 0, limit: int = 20):
        if not self.memory_store_provider():
            return JSONResponse({"checkpoints": [], "count": 0}, status_code=503)
        max_items = max(1, min(int(limit or 20), 100))
        checkpoints = []
        for item in self.memory_store_provider().list_run_records(run_type="academy_paper_checkpoint", limit=100):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            inputs = run.get("inputs") or {}
            if document_id and int(inputs.get("document_id") or 0) != int(document_id):
                continue
            checkpoints.append(self._academy_checkpoint_summary(run))
            if len(checkpoints) >= max_items:
                break
        return JSONResponse({"checkpoints": checkpoints, "count": len(checkpoints)})


    async def api_academy_paper_checkpoint_detail(self, run_id: str):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        run = self.memory_store_provider().get_run_record(run_id)
        if not run or run.get("run_type") != "academy_paper_checkpoint":
            raise HTTPException(404, "Checkpoint not found")
        path = self._academy_checkpoint_artifact_path(run)
        if not path:
            raise HTTPException(404, "Checkpoint artifact not found")
        root = (self.output_root_provider() / "academy" / "checkpoints").resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise HTTPException(403, "Checkpoint artifact is outside the checkpoint directory")
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Checkpoint artifact file not found")
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
        return JSONResponse({"run": run, "checkpoint": checkpoint, "summary": self._academy_checkpoint_summary(run)})


    def _academy_project_item_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        inputs = run.get("inputs") or {}
        outputs = run.get("outputs") or {}
        return {
            "run_id": run.get("run_id", ""),
            "title": run.get("title", ""),
            "status": run.get("status", ""),
            "updated_at": run.get("updated_at", ""),
            "document_id": inputs.get("document_id"),
            "document_title": inputs.get("document_title", ""),
            "question": inputs.get("question", ""),
            "priority": inputs.get("priority", "normal"),
            "report_run_id": outputs.get("report_run_id", ""),
            "checkpoint_run_id": outputs.get("checkpoint_run_id", ""),
            "knowledge_id": outputs.get("knowledge_id"),
            "annotation_run_id": outputs.get("annotation_run_id", ""),
            "next_action": outputs.get("next_action", ""),
        }


    async def api_academy_paper_project_board(self, document_id: int = 0, limit: int = 50):
        if not self.memory_store_provider():
            return JSONResponse({"items": [], "count": 0}, status_code=503)
        max_items = max(1, min(int(limit or 50), 100))
        items = []
        for item in self.memory_store_provider().list_run_records(run_type="academy_research_project_item", limit=100):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            inputs = run.get("inputs") or {}
            if document_id and int(inputs.get("document_id") or 0) != int(document_id):
                continue
            items.append(self._academy_project_item_summary(run))
            if len(items) >= max_items:
                break
        return JSONResponse({"items": items, "count": len(items)})


    async def api_academy_paper_project_item_save(self, request: Request):
        if not self.memory_store_provider():
            return JSONResponse({"saved": False, "error": "MemoryOS not initialized"}, status_code=503)
        data = await request.json()
        document_id = int(data.get("document_id") or 0)
        if not document_id:
            raise HTTPException(400, "document_id is required")
        status = self._academy_paper_status_payload(document_id)
        document = status.get("document") or {}
        question = str(data.get("question") or data.get("title") or "").strip()
        if not question:
            raise HTTPException(400, "question is required")
        priority = str(data.get("priority") or "normal").strip() or "normal"
        next_action = str(data.get("next_action") or "follow-up research").strip() or "follow-up research"
        title = question[:96]
        stamp = int(time.time() * 1000)
        report = status.get("report") or {}
        checkpoint = status.get("checkpoint") or {}
        knowledge = status.get("knowledge") or {}
        annotation = status.get("annotation") or {}
        run = RunRecord(
            run_id=f"academy-research-project-item-{document_id}-{stamp}",
            run_type="academy_research_project_item",
            title=title,
            status=str(data.get("status") or "open"),
            actor="user",
            scenario="research",
            inputs={
                "document_id": document_id,
                "document_title": document.get("title") or document.get("filename") or f"doc:{document_id}",
                "question": question,
                "priority": priority,
            },
            outputs={
                "next_action": next_action,
                "report_run_id": report.get("run_id", ""),
                "checkpoint_run_id": checkpoint.get("run_id", ""),
                "knowledge_id": knowledge.get("id"),
                "annotation_run_id": annotation.get("run_id", ""),
            },
            tags=["academy", "paper", "project-board", "follow-up"],
        )
        run.add_evidence("academy_research_project", "Project item is linked to the active research document and local artifacts", citation=f"doc:{document_id}", document_id=document_id)
        saved_run = self.memory_store_provider().save_run_record(run.to_dict())
        return JSONResponse({"saved": True, "item": self._academy_project_item_summary(saved_run), "run": saved_run})


    async def api_academy_paper_project_item_status(self, run_id: str, request: Request):
        if not self.memory_store_provider():
            return JSONResponse({"saved": False, "error": "MemoryOS not initialized"}, status_code=503)
        data = await request.json()
        status = str(data.get("status") or "").strip().lower()
        if status not in {"open", "done", "blocked"}:
            raise HTTPException(400, "status must be open, done, or blocked")
        run = self.memory_store_provider().get_run_record(run_id)
        if not run or run.get("run_type") != "academy_research_project_item":
            raise HTTPException(404, "Project item not found")
        outputs = dict(run.get("outputs") or {})
        if "next_action" in data:
            outputs["next_action"] = str(data.get("next_action") or "")
        if "decision" in data:
            outputs["decision"] = str(data.get("decision") or "")
        run["status"] = status
        run["outputs"] = outputs
        saved_run = self.memory_store_provider().save_run_record(run)
        return JSONResponse({"saved": True, "item": self._academy_project_item_summary(saved_run), "run": saved_run})


    async def api_academy_paper_project_board_export(self, request: Request):
        if not self.memory_store_provider():
            return JSONResponse({"exported": False, "error": "MemoryOS not initialized"}, status_code=503)
        data = await request.json()
        document_id = int(data.get("document_id") or 0)
        if not document_id:
            raise HTTPException(400, "document_id is required")
        status = self._academy_paper_status_payload(document_id)
        document = status.get("document") or {}
        chunks = self.memory_store_provider().get_document_chunks(document_id, 20)
        project_items = []
        for item in self.memory_store_provider().list_run_records(run_type="academy_research_project_item", limit=100):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            inputs = run.get("inputs") or {}
            if int(inputs.get("document_id") or 0) == document_id:
                project_items.append(self._academy_project_item_summary(run))
        checkpoints = []
        for item in self.memory_store_provider().list_run_records(run_type="academy_paper_checkpoint", limit=100):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            inputs = run.get("inputs") or {}
            if int(inputs.get("document_id") or 0) == document_id:
                checkpoints.append(self._academy_checkpoint_summary(run))
        title = str(document.get("title") or document.get("filename") or f"doc-{document_id}")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        package = {
            "schema": "clawos.academy.research_project.v1",
            "created_at": stamp,
            "document": document,
            "status": status,
            "project_items": project_items,
            "checkpoints": checkpoints,
            "chunks": [
                {
                    "chunk_index": chunk.get("chunk_index"),
                    "citation": chunk.get("citation", ""),
                    "page": chunk.get("page"),
                    "preview": str(chunk.get("text") or chunk.get("content") or chunk.get("preview") or "")[:700],
                }
                for chunk in chunks
            ],
        }
        storage = ArtifactStorage(self.output_root_provider() / "academy" / "projects")
        artifact = storage.write_json(f"{stamp}_{safe_artifact_slug(title)}_project.json", package)
        run = RunRecord(
            run_id=f"academy-research-project-export-{document_id}-{stamp}",
            run_type="academy_research_project_export",
            title=f"Academy research project export: {title}",
            status="pass",
            actor="user",
            scenario="research",
            inputs={"document_id": document_id, "title": title},
            outputs={
                "project_path": artifact["path"],
                "project_item_count": len(project_items),
                "checkpoint_count": len(checkpoints),
            },
            tags=["academy", "paper", "project-board", "export"],
        )
        run.add_artifact("project_json", f"Research project package for {title}", artifact["path"], storage=artifact)
        run.add_evidence("academy_research_project_export", "Export bundles document, checkpoints, project items, chunks, and local evidence", citation=f"doc:{document_id}", document_id=document_id)
        saved_run = self.memory_store_provider().save_run_record(run.to_dict())
        return JSONResponse({"exported": True, "package": package, "artifact": artifact, "run": saved_run})


    def _academy_project_export_artifact_path(self, run: dict[str, Any]) -> Path | None:
        for artifact in run.get("artifacts") or []:
            if artifact.get("kind") != "project_json":
                continue
            storage = (artifact.get("metadata") or {}).get("storage") or {}
            raw_path = artifact.get("uri") or storage.get("path") or ""
            if raw_path:
                return Path(str(raw_path)).expanduser().resolve()
        return None


    def _academy_project_export_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        inputs = run.get("inputs") or {}
        outputs = run.get("outputs") or {}
        artifact = (run.get("artifacts") or [{}])[0] if run.get("artifacts") else {}
        return {
            "run_id": run.get("run_id", ""),
            "title": run.get("title", ""),
            "updated_at": run.get("updated_at", ""),
            "document_id": inputs.get("document_id"),
            "document_title": inputs.get("title", ""),
            "project_path": outputs.get("project_path", ""),
            "project_item_count": outputs.get("project_item_count", 0),
            "checkpoint_count": outputs.get("checkpoint_count", 0),
            "artifact": artifact,
        }


    async def api_academy_paper_project_exports(self, document_id: int = 0, limit: int = 20):
        if not self.memory_store_provider():
            return JSONResponse({"exports": [], "count": 0}, status_code=503)
        max_items = max(1, min(int(limit or 20), 100))
        exports = []
        for item in self.memory_store_provider().list_run_records(run_type="academy_research_project_export", limit=100):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            inputs = run.get("inputs") or {}
            if document_id and int(inputs.get("document_id") or 0) != int(document_id):
                continue
            exports.append(self._academy_project_export_summary(run))
            if len(exports) >= max_items:
                break
        return JSONResponse({"exports": exports, "count": len(exports)})


    def _academy_event_time(self, source: dict[str, Any]) -> str:
        return str(source.get("updated_at") or source.get("completed_at") or source.get("started_at") or source.get("created_at") or "")


    def _academy_run_document_id(self, run: dict[str, Any]) -> int:
        inputs = run.get("inputs") or {}
        outputs = run.get("outputs") or {}
        for value in (inputs.get("document_id"), outputs.get("document_id")):
            try:
                if int(value or 0):
                    return int(value)
            except (TypeError, ValueError):
                pass
        for evidence in run.get("evidence") or []:
            try:
                if int(evidence.get("document_id") or 0):
                    return int(evidence.get("document_id") or 0)
            except (TypeError, ValueError):
                pass
        return 0


    def _academy_timeline_event(self, kind: str, label: str, summary: str, updated_at: str, document_id: int = 0, run_id: str = "", status: str = "", payload: dict[str, Any] | None = None, target: dict[str, Any] | None = None) -> dict[str, Any]:
        detail = payload or {}
        return {
            "kind": kind,
            "label": label,
            "summary": summary,
            "updated_at": updated_at,
            "document_id": document_id,
            "run_id": run_id,
            "status": status,
            "target": target or {"kind": kind, "run_id": run_id, "document_id": document_id},
            "payload": detail,
        }


    def _academy_checkpoint_citation_payload(self, run: dict[str, Any]) -> dict[str, Any]:
        path = self._academy_checkpoint_artifact_path(run)
        if not path:
            return {}
        root = (self.output_root_provider() / "academy" / "checkpoints").resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return {}
        if not path.exists() or not path.is_file():
            return {}
        try:
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        citation = checkpoint.get("citation") or {}
        if not citation:
            return {}
        evidence = citation.get("citations") or citation.get("evidence") or citation.get("chunks") or []
        return {
            "answer": citation.get("answer") or citation.get("summary") or "",
            "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
            "checkpoint_run_id": run.get("run_id", ""),
        }


    def _academy_paper_timeline_payload(self, document_id: int = 0, limit: int = 30) -> dict[str, Any]:
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        max_items = max(1, min(int(limit or 30), 100))
        active_document = self.memory_store_provider().get_document(document_id) if document_id else {}
        documents = [active_document] if active_document else self.memory_store_provider().list_documents("research")
        events: list[dict[str, Any]] = []
        for doc in documents:
            if not doc:
                continue
            doc_id = int(doc.get("id") or 0)
            if document_id and doc_id != int(document_id):
                continue
            events.append(self._academy_timeline_event(
                "document_ingestion",
                "Document ingested",
                f"{doc.get('title') or doc.get('filename') or f'doc:{doc_id}'}; chunks:{doc.get('chunk_count', 0)}",
                self._academy_event_time(doc),
                document_id=doc_id,
                status=str(doc.get("status") or ""),
                payload={"document": doc},
                target={"kind": "document", "document_id": doc_id},
            ))
        knowledge_marker = f"doc:{int(document_id)}" if document_id else ""
        for item in self.memory_store_provider().list_knowledge("research"):
            source = str(item.get("source") or "")
            content = str(item.get("content") or "")
            if knowledge_marker and knowledge_marker not in source and knowledge_marker not in content:
                continue
            matched_doc = int(document_id or 0)
            if not matched_doc:
                marker = re.search(r"doc:(\d+)", source + "\n" + content)
                matched_doc = int(marker.group(1)) if marker else 0
            events.append(self._academy_timeline_event(
                "knowledge_capture",
                "Knowledge captured",
                str(item.get("title") or f"knowledge:{item.get('id')}")[:160],
                self._academy_event_time(item),
                document_id=matched_doc,
                status="saved",
                payload={"knowledge": item},
                target={"kind": "knowledge", "knowledge_id": item.get("id"), "document_id": matched_doc},
            ))
        run_kinds = {
            "academy_paper_report": ("report", "Report generated"),
            "academy_citation_answer": ("citation_answer", "Citation answer saved"),
            "academy_annotation": ("annotation", "Annotation saved"),
            "academy_paper_checkpoint": ("checkpoint", "Checkpoint saved"),
            "academy_research_project_item": ("project_item", "Project item updated"),
            "academy_research_project_export": ("project_export", "Project package exported"),
        }
        for run_type, (kind, label) in run_kinds.items():
            for item in self.memory_store_provider().list_run_records(run_type=run_type, limit=100):
                run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
                run_doc_id = self._academy_run_document_id(run)
                if document_id and run_doc_id != int(document_id):
                    continue
                events.append(self._academy_timeline_event(
                    kind,
                    label,
                    str(run.get("title") or run.get("run_id") or label)[:180],
                    self._academy_event_time(run),
                    document_id=run_doc_id,
                    run_id=run.get("run_id", ""),
                    status=str(run.get("status") or ""),
                    payload={"run": run},
                    target={"kind": kind, "run_id": run.get("run_id", ""), "document_id": run_doc_id},
                ))
                if run_type == "academy_paper_checkpoint":
                    citation = self._academy_checkpoint_citation_payload(run)
                    if citation:
                        events.append(self._academy_timeline_event(
                            "citation_answer",
                            "Citation evidence captured",
                            f"answer:{bool(citation.get('answer'))} evidence:{citation.get('evidence_count', 0)}",
                            self._academy_event_time(run),
                            document_id=run_doc_id,
                            run_id=run.get("run_id", ""),
                            status="saved",
                            payload={"citation": citation},
                            target={"kind": "checkpoint", "run_id": run.get("run_id", ""), "document_id": run_doc_id},
                        ))
        events.sort(key=lambda event: event.get("updated_at") or "", reverse=True)
        return {
            "ok": True,
            "durable": True,
            "standard": "local-first paper research workflow timeline",
            "document_id": int(document_id or 0),
            "document": active_document,
            "events": events[:max_items],
            "count": min(len(events), max_items),
            "total": len(events),
        }


    async def api_academy_paper_timeline(self, document_id: int = 0, limit: int = 30):
        return JSONResponse(self._academy_paper_timeline_payload(document_id, limit))


    async def api_academy_paper_offline_audit(self, document_id: int = 0):
        return JSONResponse(self._academy_offline_audit_payload(document_id))


    async def api_academy_paper_project_export_detail(self, run_id: str):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        run = self.memory_store_provider().get_run_record(run_id)
        if not run or run.get("run_type") != "academy_research_project_export":
            raise HTTPException(404, "Project export not found")
        path = self._academy_project_export_artifact_path(run)
        if not path:
            raise HTTPException(404, "Project export artifact not found")
        root = (self.output_root_provider() / "academy" / "projects").resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise HTTPException(403, "Project export artifact is outside the project directory")
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Project export artifact file not found")
        package = json.loads(path.read_text(encoding="utf-8"))
        return JSONResponse({"run": run, "package": package, "summary": self._academy_project_export_summary(run)})


    async def api_academy_paper_knowledge_capture(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        try:
            document_id = int(data.get("document_id") or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, "Invalid document id")
        document = self.memory_store_provider().get_document(document_id)
        if not document:
            raise HTTPException(404, "Document not found")
        with self.memory_store_provider()._conn() as conn:
            row = conn.execute(
                "SELECT * FROM research_analysis_reports WHERE document_id=? ORDER BY id DESC LIMIT 1",
                (document_id,),
            ).fetchone()
        if not row:
            raise HTTPException(400, "Generate a grounded report before saving it to the knowledge base")
        report_row = dict(row)
        metadata = json.loads(report_row.get("metadata") or "{}")
        synthesis = dict(metadata.get("synthesis") or {})
        if not synthesis:
            raise HTTPException(400, "The latest report has no structured analysis")
        markdown_path = Path(str(report_row.get("markdown_path") or ""))
        report_content = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else GroundedPaperReport.render_markdown(synthesis)
        title = str(document.get("title") or document.get("filename") or f"Paper {document_id}")
        bundle_key = f"paper:{document_id}:report:{report_row.get('id')}"
        common_source = f"academy-paper {bundle_key}"
        items = []
        items.append(self.memory_store_provider().add_knowledge(
            f"{title} · 精读报告",
            report_content,
            "research",
            common_source,
            ["academy", "paper", "grounded-report", str(synthesis.get("mode") or "")],
            0.92 if synthesis.get("mode") == "model_assisted" else 0.78,
        ))
        claim_lines = []
        claim_count = 0
        for section in ("contributions", "methodology", "experiments", "findings", "limitations"):
            for item in synthesis.get(section) or []:
                claim_count += 1
                citations = " ".join(f"[{value}]" for value in item.get("citations") or [])
                claim_lines.append(f"- [{section}/{item.get('status', 'review')}] {item.get('text', '')} {citations}".rstrip())
        items.append(self.memory_store_provider().add_knowledge(
            f"{title} · 结论与证据",
            "# 结论与证据\n\n" + ("\n".join(claim_lines) or "当前没有可保存的结构化结论。"),
            "research",
            common_source + " claims",
            ["academy", "paper", "claims", "citation-evidence"],
            0.9,
        ))
        questions = [str(item) for item in synthesis.get("open_questions") or [] if str(item).strip()]
        if questions:
            items.append(self.memory_store_provider().add_knowledge(
                f"{title} · 待验证问题",
                "# 待验证问题\n\n" + "\n".join(f"- [ ] {item}" for item in questions),
                "research",
                common_source + " open-questions",
                ["academy", "paper", "open-questions", "reproduction"],
                0.72,
            ))
        return JSONResponse({
            "schema": "clawos.paper-knowledge-bundle.v1",
            "bundle": bundle_key,
            "items": items,
            "counts": {"knowledge_items": len(items), "claims": claim_count, "open_questions": len(questions)},
            "primary_knowledge_id": items[0].get("id") if items else None,
        })
