"""Workspace learning HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request


class WorkspaceLearningAPI:
    def __init__(self, *,
        workspace_services_provider: Callable[[], Any],
    ):
        self.workspace_services_provider = workspace_services_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workspace/learning/goals', self.api_learning_goal_create, methods=['POST'])
        self.router.add_api_route('/api/workspace/learning/goals/{goal_id}', self.api_learning_goal_detail, methods=['GET'])
        self.router.add_api_route('/api/workspace/learning/items/{item_id}/reviews', self.api_learning_review, methods=['POST'])
        self.router.add_api_route('/api/workspace/learning/goals/{goal_id}/dependencies', self.api_learning_dependency, methods=['POST'])
        self.router.add_api_route('/api/workspace/learning/items/{item_id}/mistakes', self.api_learning_mistake, methods=['POST'])
        self.router.add_api_route('/api/workspace/learning/goals/{goal_id}/graph', self.api_learning_graph, methods=['GET'])
        self.router.add_api_route('/api/workspace/learning/goals/{goal_id}/assessment', self.api_learning_assessment, methods=['GET'])

    async def api_learning_goal_create(self, request: Request):
        data = await request.json()
        goal = self.workspace_services_provider().create_learning_goal(
            data.get("title", "Learning goal"),
            data.get("description", ""),
            data.get("target_date", ""),
            data.get("topics", []),
        )
        return JSONResponse({"goal": goal})


    async def api_learning_goal_detail(self, goal_id: int):
        goal = self.workspace_services_provider().get_learning_goal(goal_id)
        if not goal:
            raise HTTPException(404, "Learning goal not found")
        return JSONResponse({"goal": goal})


    async def api_learning_review(self, item_id: int, request: Request):
        data = await request.json()
        try:
            item = self.workspace_services_provider().record_learning_review(
                item_id,
                data.get("score", 0),
                data.get("evidence", ""),
                data.get("notes", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"item": item})


    async def api_learning_dependency(self, goal_id: int, request: Request):
        data = await request.json()
        try:
            edge = self.workspace_services_provider().add_learning_dependency(
                goal_id,
                data.get("source_topic", ""),
                data.get("target_topic", ""),
                data.get("relation", "depends_on"),
                data.get("evidence", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"edge": edge})


    async def api_learning_mistake(self, item_id: int, request: Request):
        data = await request.json()
        try:
            mistake = self.workspace_services_provider().record_learning_mistake(
                item_id,
                data.get("prompt", ""),
                data.get("wrong_answer", ""),
                data.get("correct_answer", ""),
                data.get("evidence", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"mistake": mistake})


    async def api_learning_graph(self, goal_id: int):
        try:
            return JSONResponse(self.workspace_services_provider().learning_graph(goal_id))
        except ValueError as exc:
            raise HTTPException(404, str(exc))


    async def api_learning_assessment(self, goal_id: int):
        return JSONResponse(self.workspace_services_provider().long_term_mastery(goal_id))
