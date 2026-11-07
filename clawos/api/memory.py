"""Memory HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
from fastapi.responses import Response
import hashlib
import json


class MemoryAPI:
    def __init__(self, *,
        list_memory_items: Callable[..., Any],
        save_memory_item: Callable[..., Any],
        set_memory_item_enabled: Callable[..., Any],
        memory_store_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
    ):
        self.list_memory_items = list_memory_items
        self.save_memory_item = save_memory_item
        self.set_memory_item_enabled = set_memory_item_enabled
        self.memory_store_provider = memory_store_provider
        self.vector_store_provider = vector_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/memory/stats', self.memory_stats, methods=['GET'])
        self.router.add_api_route('/api/memory/items', self.api_memory_items, methods=['GET'])
        self.router.add_api_route('/api/memory/items', self.api_memory_item_save, methods=['POST'])
        self.router.add_api_route('/api/memory/items/{memory_id}/enabled', self.api_memory_item_enabled, methods=['POST'])
        self.router.add_api_route('/api/memory/items/search', self.api_memory_items_search, methods=['GET'])
        self.router.add_api_route('/api/memory/candidates/from-task', self.api_selective_memory_propose, methods=['POST'])
        self.router.add_api_route('/api/memory/candidates', self.api_selective_memory_list, methods=['GET'])
        self.router.add_api_route('/api/memory/candidates/{candidate_id}/review', self.api_selective_memory_review, methods=['POST'])
        self.router.add_api_route('/api/memory/candidates/{candidate_id}/promote', self.api_selective_memory_promote, methods=['POST'])
        self.router.add_api_route('/api/memory/items/{memory_id}/versions', self.api_memory_versions, methods=['GET'])
        self.router.add_api_route('/api/memory/items/{memory_id}/evidence', self.api_memory_evidence, methods=['GET'])
        self.router.add_api_route('/api/memory/reviews', self.api_memory_reviews, methods=['GET'])
        self.router.add_api_route('/api/memory/reviews/{review_id}/resolve', self.api_memory_review_resolve, methods=['POST'])
        self.router.add_api_route('/api/memory/items/{memory_id}/acl', self.api_memory_acl, methods=['GET'])
        self.router.add_api_route('/api/memory/items/{memory_id}/acl', self.api_memory_acl_grant, methods=['POST'])
        self.router.add_api_route('/api/memory/evaluations/run', self.api_memory_evaluation_run, methods=['POST'])
        self.router.add_api_route('/api/memory/profiles', self.api_memory_profiles, methods=['GET'])
        self.router.add_api_route('/api/memory/profiles', self.api_memory_profile_set, methods=['POST'])
        self.router.add_api_route('/api/memory/preferences', self.api_memory_preferences, methods=['GET'])
        self.router.add_api_route('/api/memory/preferences', self.api_memory_preference_set, methods=['POST'])
        self.router.add_api_route('/api/memory/experiences', self.api_memory_experiences, methods=['GET'])
        self.router.add_api_route('/api/mtclaw/traces', self.api_mtclaw_traces, methods=['GET'])
        self.router.add_api_route('/api/memory/context/{session_id}', self.memory_context, methods=['GET'])
        self.router.add_api_route('/api/history/{session_id}', self.get_history, methods=['GET'])
        self.router.add_api_route('/api/sessions', self.api_list_sessions, methods=['GET'])
        self.router.add_api_route('/api/history/{session_id}/export', self.api_export_history, methods=['GET'])
        self.router.add_api_route('/api/memory/search', self.api_memory_search, methods=['GET'])
        self.router.add_api_route('/api/memory/refresh', self.api_memory_refresh, methods=['GET'])

    async def memory_stats(self):
        if self.memory_store_provider():
            try:
                stats = self.memory_store_provider().get_stats()
                if self.vector_store_provider():
                    stats["vectors"] = self.vector_store_provider().stats().get("vector_count", 0)
                return JSONResponse(stats)
            except Exception as e:
                raise HTTPException(500, str(e))
        return JSONResponse({"error": "MemoryOS not initialized"}, status_code=503)


    async def api_memory_items(self,
        memory_type: str = "",
        include_disabled: bool = False,
        limit: int = 200,
        actor_id: str = "system",
        roles: str = "",
        workspace_id: str = "default",
    ):
        rows = self.list_memory_items(
            memory_type,
            include_disabled,
            limit,
            actor_id=actor_id,
            roles=[role for role in roles.split(",") if role],
            workspace_id=workspace_id,
        )
        return JSONResponse({"items": rows, "count": len(rows)})


    async def api_memory_item_save(self, request: Request):
        data = await request.json()
        item = self.save_memory_item(data)
        return JSONResponse({"item": item, "saved": True})


    async def api_memory_item_enabled(self, memory_id: int, request: Request):
        data = await request.json()
        item = self.set_memory_item_enabled(memory_id, bool(data.get("enabled", True)))
        return JSONResponse({"item": item, "updated": True})


    async def api_memory_items_search(self,
        q: str = "",
        memory_type: str = "",
        include_disabled: bool = False,
        limit: int = 20,
        actor_id: str = "system",
        roles: str = "",
        workspace_id: str = "default",
    ):
        if not self.memory_store_provider():
            return JSONResponse({"items": [], "count": 0}, status_code=503)
        rows = self.memory_store_provider().search_memories(
            q,
            memory_type,
            limit,
            include_disabled,
            actor_id=actor_id,
            roles=[role for role in roles.split(",") if role],
            workspace_id=workspace_id,
        )
        return JSONResponse({"items": rows, "count": len(rows)})


    async def api_selective_memory_propose(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.selective_memory_service import SelectiveMemoryService

        data = await request.json()
        try:
            result = SelectiveMemoryService(self.memory_store_provider()).propose_from_task(
                task_id=data.get("task_id") or "manual", outcome=str(data.get("outcome") or ""),
                candidates=data.get("candidates") or [], success_evidence=data.get("success_evidence") or [],
                session_id=str(data.get("session_id") or ""), owner_id=str(data.get("owner_id") or "default"),
                workspace_id=str(data.get("workspace_id") or "default"),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(result)


    async def api_selective_memory_list(self, status: str = "", owner_id: str = "", limit: int = 200):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.selective_memory_service import SelectiveMemoryService

        service = SelectiveMemoryService(self.memory_store_provider())
        items = service.list(status=status, owner_id=owner_id, limit=limit)
        return JSONResponse({"items": items, "count": len(items), "stats": service.stats()})


    async def api_selective_memory_review(self, candidate_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.selective_memory_service import SelectiveMemoryService

        data = await request.json()
        try:
            item = SelectiveMemoryService(self.memory_store_provider()).review(
                candidate_id, str(data.get("decision") or ""), reviewer=str(data.get("reviewer") or "user"),
                confirmed=bool(data.get("confirmed")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse({"reviewed": True, "candidate": item})


    async def api_selective_memory_promote(self, candidate_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from services.selective_memory_service import SelectiveMemoryService

        data = await request.json()
        try:
            item = SelectiveMemoryService(self.memory_store_provider()).promote(
                candidate_id, actor_id=str(data.get("actor_id") or "user"), confirmed=bool(data.get("confirmed")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if self.vector_store_provider() and item.get("promoted_target", {}).get("kind") == "knowledge_v2":
            self.vector_store_provider().refresh()
        return JSONResponse({"promoted": True, "candidate": item})


    async def api_memory_versions(self, memory_id: int, limit: int = 100):
        if not self.memory_store_provider() or not self.memory_store_provider().get_memory(memory_id):
            raise HTTPException(404, "Memory item not found")
        rows = self.memory_store_provider().list_memory_versions(memory_id, limit)
        return JSONResponse({"versions": rows, "count": len(rows)})


    async def api_memory_evidence(self, memory_id: int, limit: int = 100):
        if not self.memory_store_provider() or not self.memory_store_provider().get_memory(memory_id):
            raise HTTPException(404, "Memory item not found")
        rows = self.memory_store_provider().list_memory_evidence(memory_id, limit)
        return JSONResponse({"evidence": rows, "count": len(rows)})


    async def api_memory_reviews(self, status: str = "pending", limit: int = 100):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        rows = self.memory_store_provider().list_memory_reviews(status, limit)
        return JSONResponse({"reviews": rows, "count": len(rows)})


    async def api_memory_review_resolve(self, review_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        try:
            review = self.memory_store_provider().resolve_memory_review(
                review_id,
                data.get("decision", ""),
                reviewer=str(data.get("reviewer", "system") or "system"),
                notes=str(data.get("notes", "") or ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if not review:
            raise HTTPException(404, "Review not found")
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse({"review": review, "resolved": True})


    async def api_memory_acl(self, memory_id: int):
        if not self.memory_store_provider() or not self.memory_store_provider().get_memory(memory_id):
            raise HTTPException(404, "Memory item not found")
        rows = self.memory_store_provider().list_memory_acl(memory_id)
        return JSONResponse({"acl": rows, "count": len(rows)})


    async def api_memory_acl_grant(self, memory_id: int, request: Request):
        if not self.memory_store_provider() or not self.memory_store_provider().get_memory(memory_id):
            raise HTTPException(404, "Memory item not found")
        data = await request.json()
        try:
            rows = self.memory_store_provider().grant_memory_acl(
                memory_id,
                data.get("principal_type", ""),
                data.get("principal_id", ""),
                data.get("permission", ""),
                data.get("granted_by", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"acl": rows, "count": len(rows)})


    async def api_memory_evaluation_run(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        cases = data.get("cases", [])
        if not isinstance(cases, list) or not cases:
            raise HTTPException(400, "cases must be a non-empty list")
        from memoryos.services.retrieval import RetrievalService
        from memoryos.services.retrieval_benchmark import RetrievalBenchmark
        retrieval = RetrievalService(self.memory_store_provider(), self.vector_store_provider())
        run = RetrievalBenchmark(self.memory_store_provider(), retrieval).run(
            cases,
            top_k=data.get("top_k", 5),
            name=data.get("name", "memory-retrieval"),
            created_by=data.get("created_by", "system"),
        )
        return JSONResponse({"run": run})


    async def api_memory_profiles(self):
        if not self.memory_store_provider():
            return JSONResponse({"profiles": [], "count": 0}, status_code=503)
        profiles = self.memory_store_provider().get_all_profiles()
        return JSONResponse({"profiles": profiles, "count": len(profiles)})


    async def api_memory_profile_set(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        key = str(data.get("key", "")).strip()
        value = str(data.get("value", "")).strip()
        if not key or not value:
            raise HTTPException(400, "key and value are required")
        self.memory_store_provider().set_profile(
            key,
            value,
            str(data.get("category", "general") or "general"),
            float(data.get("importance", 0.7)),
        )
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse({"set": True, "key": key, "value": value})


    async def api_memory_preferences(self):
        if not self.memory_store_provider():
            return JSONResponse({"preferences": [], "count": 0}, status_code=503)
        prefs = self.memory_store_provider().get_all_preferences()
        return JSONResponse({"preferences": prefs, "count": len(prefs)})


    async def api_memory_preference_set(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        key = str(data.get("key", "")).strip()
        value = str(data.get("value", "")).strip()
        if not key or not value:
            raise HTTPException(400, "key and value are required")
        self.memory_store_provider().set_preference(
            key,
            value,
            str(data.get("category", "general") or "general"),
            float(data.get("confidence", 0.8)),
        )
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse({"set": True, "key": key, "value": value})


    async def api_memory_experiences(self, limit: int = 20):
        if not self.memory_store_provider():
            return JSONResponse({"experiences": [], "count": 0}, status_code=503)
        experiences = self.memory_store_provider().get_recent_experiences(min(limit, 100))
        return JSONResponse({"experiences": experiences, "count": len(experiences)})


    async def api_mtclaw_traces(self, session_id: str = "", limit: int = 50):
        if not self.memory_store_provider():
            return JSONResponse({"traces": [], "count": 0}, status_code=503)
        rows = self.memory_store_provider().list_mtclaw_traces(session_id, limit)
        return JSONResponse({"traces": rows, "count": len(rows)})


    async def memory_context(self, session_id: str):
        if self.memory_store_provider():
            try:
                msgs = self.memory_store_provider().get_recent_messages(session_id, 20)
                return JSONResponse({"session_id": session_id, "messages": msgs, "count": len(msgs)})
            except Exception as e:
                raise HTTPException(500, str(e))
        return JSONResponse({"error": "MemoryOS not initialized"}, status_code=503)


    async def get_history(self, session_id: str, limit: int = 50, before_id: int = 0):
        """Get conversation history for a session."""
        if self.memory_store_provider():
            try:
                return JSONResponse(self.memory_store_provider().conversation_history(session_id, limit, before_id))
            except Exception as e:
                raise HTTPException(500, str(e))
        return JSONResponse({"error": "MemoryOS not ready"}, status_code=503)


    async def api_list_sessions(self, q: str = "", limit: int = 500):
        if self.memory_store_provider():
            try:
                sessions = self.memory_store_provider().list_sessions(q[:500], limit)
                return JSONResponse({"sessions": sessions, "count": len(sessions)})
            except Exception as e:
                raise HTTPException(500, str(e))
        return JSONResponse({"sessions": [], "count": 0})


    async def api_export_history(self, session_id: str, format: str = 'markdown'):
        if not self.memory_store_provider():
            raise HTTPException(503, 'MemoryOS not ready')
        if format not in {'markdown', 'json'}:
            raise HTTPException(400, 'format must be markdown or json')
        from services.conversation_history import export_history
        try:
            payload = export_history(self.memory_store_provider(), session_id)
        except ValueError as exc:
            raise HTTPException(413, str(exc))
        suffix = 'json' if format == 'json' else 'md'
        name = hashlib.sha256(session_id.encode()).hexdigest()[:16]
        if format == 'json':
            body = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            body = '# 对话记录\n\n' + '\n\n'.join(
                f"## {'用户' if item['role']=='user' else '助手'} · {item['created_at']}\n\n{item['content']}"
                for item in payload['messages'])
        return Response(body, media_type='application/json' if format=='json' else 'text/markdown',
                        headers={'Content-Disposition': f'attachment; filename="conversation-{name}.{suffix}"',
                                 'Cache-Control': 'no-store'})


    async def api_memory_search(self, q: str = "", top_k: int = 10):
        if not q or not self.vector_store_provider():
            return JSONResponse({"results": []})
        try:
            results = self.vector_store_provider().search(q, min(20, top_k))
            return JSONResponse({"results": results, "count": len(results)})
        except Exception as e:
            return JSONResponse({"results": [], "error": str(e)})


    async def api_memory_refresh(self):
        if self.vector_store_provider():
            try:
                self.vector_store_provider().refresh()
                return JSONResponse({"refreshed": True, "stats": self.vector_store_provider().stats()})
            except Exception as e:
                return JSONResponse({"refreshed": False, "error": str(e)})
        return JSONResponse({"refreshed": False, "error": "VectorStore not initialized"})
