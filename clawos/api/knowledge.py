"""Knowledge HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import asyncio
import json


class KnowledgeAPI:
    def __init__(self, *,
        get_knowledge_service: Callable[..., Any],
        resolve_obsidian_output_dir: Callable[..., Any],
        output_root_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
    ):
        self.get_knowledge_service = get_knowledge_service
        self.resolve_obsidian_output_dir = resolve_obsidian_output_dir
        self.output_root_provider = output_root_provider
        self.memory_store_provider = memory_store_provider
        self.vector_store_provider = vector_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/knowledge', self.api_knowledge_list, methods=['GET'])
        self.router.add_api_route('/api/knowledge', self.api_knowledge_save, methods=['POST'])
        self.router.add_api_route('/api/knowledge/{knowledge_id}', self.api_knowledge_update, methods=['PUT'])
        self.router.add_api_route('/api/knowledge/{knowledge_id}', self.api_knowledge_delete, methods=['DELETE'])
        self.router.add_api_route('/api/knowledge/search', self.api_knowledge_search, methods=['GET'])
        self.router.add_api_route('/api/knowledge/context-pack', self.api_knowledge_context_pack, methods=['GET'])
        self.router.add_api_route('/api/knowledge/answer', self.api_knowledge_answer, methods=['GET'])
        self.router.add_api_route('/api/knowledge/v2/stats', self.api_knowledge_v2_stats, methods=['GET'])
        self.router.add_api_route('/api/knowledge/v2/index/rebuild', self.api_knowledge_v2_index_rebuild, methods=['POST'])
        self.router.add_api_route('/api/knowledge/v2/quality/latest', self.api_knowledge_v2_quality_latest, methods=['GET'])
        self.router.add_api_route('/api/knowledge/v2/conflicts', self.api_knowledge_v2_conflicts, methods=['GET'])
        self.router.add_api_route('/api/knowledge/v2/conflicts/{conflict_id}/resolve', self.api_knowledge_v2_conflict_resolve, methods=['POST'])
        self.router.add_api_route('/api/knowledge/v2/backfill', self.api_knowledge_v2_backfill, methods=['POST'])
        self.router.add_api_route('/api/knowledge/v2/usage', self.api_knowledge_v2_usage, methods=['POST'])
        self.router.add_api_route('/api/knowledge/v2/answer-quality/validate', self.api_answer_quality_validate, methods=['POST'])
        self.router.add_api_route('/api/knowledge/v2/answer-quality/feedback', self.api_answer_quality_feedback, methods=['POST'])
        self.router.add_api_route('/api/knowledge/v2/answer-quality/feedback', self.api_answer_quality_feedback_list, methods=['GET'])
        self.router.add_api_route('/api/knowledge/v2/answer-quality/latest', self.api_answer_quality_latest, methods=['GET'])
        self.router.add_api_route('/api/knowledge/graph', self.api_knowledge_graph, methods=['GET'])
        self.router.add_api_route('/api/knowledge/obsidian/check', self.api_knowledge_obsidian_check, methods=['GET'])
        self.router.add_api_route('/api/knowledge/obsidian/export', self.api_knowledge_obsidian_export, methods=['POST'])

    async def api_knowledge_list(self, category: str = ""):
        if not self.memory_store_provider():
            return JSONResponse({"items": [], "count": 0}, status_code=503)
        rows = self.memory_store_provider().list_knowledge(category)
        return JSONResponse({"items": rows, "count": len(rows)})


    async def api_knowledge_save(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        if not title or not content:
            raise HTTPException(400, "title and content are required")
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        item = self.memory_store_provider().add_knowledge(
            title=title,
            content=content,
            category=str(data.get("category", "domain") or "domain").strip() or "domain",
            source=str(data.get("source", "manual") or "manual").strip(),
            tags=tags if isinstance(tags, list) else [],
            confidence=float(data.get("confidence", 0.7) or 0.7),
        )
        if self.vector_store_provider():
            await asyncio.to_thread(self.vector_store_provider().refresh)
        return JSONResponse({"item": item, "saved": True})


    async def api_knowledge_update(self, knowledge_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        title = str(data.get("title", "")).strip()
        content = str(data.get("content", "")).strip()
        if not title or not content:
            raise HTTPException(400, "title and content are required")
        tags = data.get("tags", [])
        if isinstance(tags, str):
            tags = [item.strip() for item in tags.split(",") if item.strip()]
        item = self.memory_store_provider().update_knowledge(
            knowledge_id,
            title=title,
            content=content,
            category=str(data.get("category", "domain") or "domain").strip() or "domain",
            source=str(data.get("source", "manual") or "manual").strip(),
            tags=tags if isinstance(tags, list) else [],
            confidence=float(data.get("confidence", 0.7) or 0.7),
        )
        if not item:
            raise HTTPException(404, "Knowledge item not found")
        if self.vector_store_provider():
            await asyncio.to_thread(self.vector_store_provider().refresh)
        return JSONResponse({"item": item, "updated": True})


    async def api_knowledge_delete(self, knowledge_id: int):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        deleted = self.memory_store_provider().delete_knowledge(knowledge_id)
        if not deleted:
            raise HTTPException(404, "Knowledge item not found")
        if self.vector_store_provider():
            await asyncio.to_thread(self.vector_store_provider().refresh)
        return JSONResponse({"deleted": True, "id": knowledge_id})


    async def api_knowledge_search(self, q: str = "", category: str = "", limit: int = 10):
        if not self.memory_store_provider():
            return JSONResponse({"items": [], "count": 0}, status_code=503)
        if not q:
            return JSONResponse({"items": [], "count": 0})
        bounded = max(1, min(int(limit or 10), 50))
        rows = self.memory_store_provider().search_knowledge_v2(q, category, bounded)
        if not rows:
            rows = self.memory_store_provider().search_knowledge(q, category, bounded)
        return JSONResponse({"items": rows, "count": len(rows), "schema": "evidence_knowledge_v2"})


    async def api_knowledge_context_pack(self, q: str = "", category: str = "", limit: int = 6, token_budget: int = 1600):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        if not q.strip():
            raise HTTPException(400, "q is required")
        return JSONResponse(self.memory_store_provider().knowledge_context_pack(
            q, category, max(1, min(int(limit or 6), 20)), max(400, min(int(token_budget or 1600), 8000)),
        ))


    async def api_knowledge_answer(self,
        q: str = "", category: str = "", limit: int = 6, token_budget: int = 1600,
        session_id: str = "", task_id: str = "",
    ):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        if not q.strip():
            raise HTTPException(400, "q is required")
        return JSONResponse(self.memory_store_provider().answer_from_knowledge(
            q, category, max(1, min(int(limit or 6), 20)), max(400, min(int(token_budget or 1600), 8000)),
            session_id, task_id,
        ))


    async def api_knowledge_v2_stats(self):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        stats = self.memory_store_provider().knowledge_v2_stats()
        stats["vector_projection"] = self.vector_store_provider().stats() if self.vector_store_provider() else {
            "provider": "unavailable", "consistent": False, "last_index_error": "VectorStore not initialized",
        }
        return JSONResponse(stats)


    async def api_knowledge_v2_index_rebuild(self, request: Request):
        if not self.vector_store_provider():
            raise HTTPException(503, "VectorStore not initialized")
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for a full vector index rebuild")
        return JSONResponse({"rebuilt": True, **self.vector_store_provider().rebuild()})


    async def api_knowledge_v2_quality_latest(self):
        path = (self.output_root_provider() / "knowledge_quality" / "knowledge_quality_report.json").resolve()
        if not path.exists():
            return JSONResponse({"found": False, "report_path": str(path)})
        data = json.loads(path.read_text(encoding="utf-8"))
        data["found"] = True
        data["report_path"] = str(path)
        return JSONResponse(data)


    async def api_knowledge_v2_conflicts(self, status: str = "pending", limit: int = 100):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        allowed = {"", "pending", "resolved", "dismissed"}
        if status not in allowed:
            raise HTTPException(400, "invalid conflict status")
        items = self.memory_store_provider().list_knowledge_conflicts(status, max(1, min(int(limit or 100), 500)))
        return JSONResponse({"items": items, "count": len(items)})


    async def api_knowledge_v2_conflict_resolve(self, conflict_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        try:
            item = self.memory_store_provider().resolve_knowledge_conflict(
                conflict_id, str(data.get("decision") or ""),
                reviewer=str(data.get("reviewer") or "user"), reason=str(data.get("reason") or ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse({"resolved": True, "item": item})


    async def api_knowledge_v2_backfill(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        result = self.memory_store_provider().backfill_knowledge_v2(max(1, min(int(data.get("limit") or 10000), 100000)))
        if self.vector_store_provider() and result.get("migrated"):
            self.vector_store_provider().refresh()
        return JSONResponse(result)


    async def api_knowledge_v2_usage(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        ids = data.get("knowledge_ids") or []
        if not isinstance(ids, list):
            raise HTTPException(400, "knowledge_ids must be a list")
        self.memory_store_provider().record_knowledge_usage(
            ids, query=str(data.get("query") or ""), session_id=str(data.get("session_id") or ""),
            task_id=str(data.get("task_id") or ""), usage_type=str(data.get("usage_type") or "answer_cited"),
            outcome=str(data.get("outcome") or "unknown"),
        )
        return JSONResponse({"recorded": True, "count": len(set(int(item) for item in ids))})


    async def api_answer_quality_validate(self, request: Request):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        data = await request.json()
        try:
            return JSONResponse(ClaimEvidenceAnswerValidator.validate(
                query=str(data.get("query") or ""), answer=str(data.get("answer") or ""),
                evidence=data.get("evidence") or [], expected_answer=str(data.get("expected_answer") or ""),
                must_refuse=bool(data.get("must_refuse")), claims=data.get("claims"),
            ))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc


    async def api_answer_quality_feedback(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.answer_quality_service import AnswerQualityService

        try:
            item = AnswerQualityService(self.memory_store_provider()).record(await request.json())
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse({"recorded": True, "feedback": item})


    async def api_answer_quality_feedback_list(self, origin: str = "", split: str = "", limit: int = 500):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.answer_quality_service import AnswerQualityService

        service = AnswerQualityService(self.memory_store_provider())
        items = service.list(origin=origin, split=split, limit=limit)
        return JSONResponse({"items": items, "count": len(items), "stats": service.stats()})


    async def api_answer_quality_latest(self):
        path = (self.output_root_provider() / "answer_quality" / "answer_quality_report.json").resolve()
        if not path.exists():
            return JSONResponse({"found": False, "report_path": str(path)})
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update({"found": True, "report_path": str(path)})
        return JSONResponse(data)


    async def api_knowledge_graph(self, category: str = "", limit: int = 80):
        service = self.get_knowledge_service()
        return JSONResponse(service.knowledge_graph(category, limit))


    async def api_knowledge_obsidian_check(self, category: str = "", limit: int = 120):
        service = self.get_knowledge_service()
        return JSONResponse(service.obsidian_check(category, limit))


    async def api_knowledge_obsidian_export(self, request: Request):
        service = self.get_knowledge_service()
        data = await request.json()
        category = str(data.get("category", "") or "")
        limit = max(1, min(int(data.get("limit", 300) or 300), 1000))
        output_dir = self.resolve_obsidian_output_dir(str(data.get("output_dir", "") or ""), category)
        return JSONResponse(service.export_obsidian_vault(output_dir, category=category, limit=limit))
