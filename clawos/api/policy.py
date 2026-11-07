"""Policy HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request


class PolicyAPI:
    def __init__(self, *,
        build_routing_strategy: Callable[..., Any],
        score_scenarios: Callable[..., Any],
        scenario_routing_policy_provider: Callable[[], Any],
        policy_optimizer_provider: Callable[[], Any],
    ):
        self.build_routing_strategy = build_routing_strategy
        self.score_scenarios = score_scenarios
        self.scenario_routing_policy_provider = scenario_routing_policy_provider
        self.policy_optimizer_provider = policy_optimizer_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/policy/groups', self.api_policy_group_register, methods=['POST'])
        self.router.add_api_route('/api/policy/groups/{group_name}/select', self.api_policy_select, methods=['POST'])
        self.router.add_api_route('/api/policy/selections/{selection_id}/reward', self.api_policy_reward, methods=['POST'])
        self.router.add_api_route('/api/policy/groups/{group_name}/stats', self.api_policy_stats, methods=['GET'])
        self.router.add_api_route('/api/policy/groups/{group_name}/promote', self.api_policy_promote, methods=['POST'])
        self.router.add_api_route('/api/policy/promotions/{promotion_id}/rollback', self.api_policy_promotion_rollback, methods=['POST'])
        self.router.add_api_route('/api/routing/policy', self.api_routing_policy, methods=['GET'])

    async def api_policy_group_register(self, request: Request):
        if not self.policy_optimizer_provider():
            raise HTTPException(503, "Policy Optimizer not initialized")
        data = await request.json()
        name = str(data.get("name", "") or "").strip()
        arms = data.get("arms", [])
        if not name or not isinstance(arms, list) or not arms:
            raise HTTPException(400, "name and non-empty arms are required")
        try:
            result = self.policy_optimizer_provider().register_group(
                name,
                arms,
                exploration_rate=data.get("exploration_rate", 0.1),
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_policy_select(self, group_name: str, request: Request):
        if not self.policy_optimizer_provider():
            raise HTTPException(503, "Policy Optimizer not initialized")
        data = await request.json()
        try:
            selection = self.policy_optimizer_provider().select(
                group_name,
                context=data.get("context", {}),
                task_id=data.get("task_id"),
                session_id=data.get("session_id", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"selection": selection})


    async def api_policy_reward(self, selection_id: int, request: Request):
        if not self.policy_optimizer_provider():
            raise HTTPException(503, "Policy Optimizer not initialized")
        data = await request.json()
        try:
            if not data.get("task_id"):
                raise ValueError("task_id is required; rewards are derived from terminal task evidence")
            result = self.policy_optimizer_provider().reward_from_task(
                selection_id,
                task_id=int(data["task_id"]),
                satisfaction=data.get("satisfaction"),
                resource_cost=data.get("resource_cost"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_policy_stats(self, group_name: str):
        if not self.policy_optimizer_provider():
            raise HTTPException(503, "Policy Optimizer not initialized")
        stats = self.policy_optimizer_provider().stats(group_name)
        if not stats:
            raise HTTPException(404, "Policy group not found")
        return JSONResponse(stats)


    async def api_policy_promote(self, group_name: str, request: Request):
        data = await request.json()
        if not bool(data.get("confirmed")):
            raise HTTPException(409, "explicit confirmed=true is required for policy promotion")
        try:
            promotion = self.policy_optimizer_provider().promote(
                group_name,
                data.get("target_type", "agent_policy"),
                data.get("target_key", group_name),
                min_pulls=data.get("min_pulls", 30),
                actor_id=data.get("actor_id", "system"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"promotion": promotion, "run": promotion, "activated": False,
                             "next_step": "execute regression and fresh paired shadow/canary evidence"})


    async def api_policy_promotion_rollback(self, promotion_id: int, request: Request):
        data = await request.json()
        try:
            promotion = self.policy_optimizer_provider().rollback(
                promotion_id, actor_id=data.get("actor_id", "system")
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"promotion": promotion})


    async def api_routing_policy(self, q: str = ""):
        candidates = self.score_scenarios(q)
        strategy = self.build_routing_strategy(q)
        scenario = strategy["scenario"]
        selected = self.scenario_routing_policy_provider()[scenario]
        return JSONResponse({
            "scenario": scenario,
            "selected": selected,
            "candidates": candidates,
            "strategy": strategy,
            "policies": self.scenario_routing_policy_provider(),
        })
