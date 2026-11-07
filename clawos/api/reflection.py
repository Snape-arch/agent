"""Reflection HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import json


class ReflectionAPI:
    def __init__(self, *,
        memory_store_provider: Callable[[], Any],
        reflection_engine_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
    ):
        self.memory_store_provider = memory_store_provider
        self.reflection_engine_provider = reflection_engine_provider
        self.vector_store_provider = vector_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/reflection/trigger', self.trigger_reflection, methods=['POST'])
        self.router.add_api_route('/api/reflection/list', self.list_reflections, methods=['GET'])
        self.router.add_api_route('/api/reflection/cards/{card_id}', self.reflection_card_detail, methods=['GET'])
        self.router.add_api_route('/api/reflection/cards/{card_id}/feedback', self.reflection_card_feedback, methods=['POST'])
        self.router.add_api_route('/api/reflection/improvements', self.reflection_improvements, methods=['GET'])
        self.router.add_api_route('/api/reflection/improvements/{improvement_id}/transition', self.reflection_improvement_transition, methods=['POST'])
        self.router.add_api_route('/api/reflection/improvements/{improvement_id}/validate', self.reflection_improvement_validate, methods=['POST'])
        self.router.add_api_route('/api/reflection/improvements/{improvement_id}/publish', self.reflection_improvement_publish, methods=['POST'])
        self.router.add_api_route('/api/reflection/improvements/{improvement_id}/rollback', self.reflection_improvement_rollback, methods=['POST'])
        self.router.add_api_route('/api/reflection/stats', self.reflection_stats, methods=['GET'])

    async def trigger_reflection(self, request: Request):
        if not self.reflection_engine_provider():
            raise HTTPException(503, "Reflection Engine not initialized")
        try:
            body = await request.body()
            req_data = json.loads(body) if body else {}
        except:
            req_data = {}
        sid = req_data.get("session_id", "default")
        task = req_data.get("task", "Manual reflection")
        fb = req_data.get("feedback", "")
        result = self.reflection_engine_provider().reflect("user_triggered", sid, [], fb, task)
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse(result)


    async def list_reflections(self, limit: int = 20):
        if not self.reflection_engine_provider():
            raise HTTPException(503, "Reflection Engine not initialized")
        from reflection.memory_writer import ReflectionMemoryWriter
        writer = ReflectionMemoryWriter(self.memory_store_provider())
        cards = writer.get_reflection_cards(limit)
        return JSONResponse({"cards": cards, "count": len(cards)})


    async def reflection_card_detail(self, card_id: str):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        card = self.memory_store_provider().get_reflection_card(card_id)
        if not card:
            raise HTTPException(404, "Reflection card not found")
        return JSONResponse({"card": card})


    async def reflection_card_feedback(self, card_id: str, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        card = self.memory_store_provider().update_reflection_feedback(
            card_id,
            {
                "rating": data.get("rating"),
                "satisfied": data.get("satisfied"),
                "comment": str(data.get("comment", "") or ""),
                "correction": str(data.get("correction", "") or ""),
                "reason": str(data.get("reason", "") or ""),
            },
            actor_id=data.get("actor_id", "system"),
        )
        if not card:
            raise HTTPException(404, "Reflection card not found")
        return JSONResponse({"card": card, "updated": True})


    async def reflection_improvements(self, status: str = "", limit: int = 100):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        rows = self.memory_store_provider().list_reflection_improvements(status, limit)
        return JSONResponse({"improvements": rows, "count": len(rows)})


    async def reflection_improvement_transition(self, improvement_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.improvement_manager import ImprovementManager
        data = await request.json()
        try:
            item = ImprovementManager(self.memory_store_provider()).transition(
                improvement_id,
                str(data.get("to_status", "") or ""),
                actor_id=data.get("actor_id", "system"),
                reason=data.get("reason", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"improvement": item})


    async def reflection_improvement_validate(self, improvement_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.improvement_manager import ImprovementManager
        data = await request.json()
        try:
            item = ImprovementManager(self.memory_store_provider()).validate(
                improvement_id,
                baseline=data.get("baseline", {}),
                candidate=data.get("candidate", {}),
                thresholds=data.get("thresholds", {}),
                actor_id=data.get("actor_id", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"improvement": item})


    async def reflection_improvement_publish(self, improvement_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.improvement_manager import ImprovementManager
        data = await request.json()
        try:
            item = ImprovementManager(self.memory_store_provider()).publish(
                improvement_id,
                actor_id=data.get("actor_id", "system"),
                reason=data.get("reason", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"improvement": item})


    async def reflection_improvement_rollback(self, improvement_id: int, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from reflection.improvement_manager import ImprovementManager
        data = await request.json()
        try:
            item = ImprovementManager(self.memory_store_provider()).rollback(
                improvement_id,
                actor_id=data.get("actor_id", "system"),
                reason=data.get("reason", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"improvement": item})


    async def reflection_stats(self):
        if not self.reflection_engine_provider():
            raise HTTPException(503, "Reflection Engine not initialized")
        from reflection.learning_loop import LearningLoop
        loop = LearningLoop(self.reflection_engine_provider(), self.memory_store_provider())
        return JSONResponse(loop.get_cycle_stats())
