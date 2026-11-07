"""Skills HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request


class SkillsAPI:
    def __init__(self, *,
        memory_store_provider: Callable[[], Any],
        skill_evolution_provider: Callable[[], Any],
    ):
        self.memory_store_provider = memory_store_provider
        self.skill_evolution_provider = skill_evolution_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/skills/list', self.skills_list, methods=['GET'])
        self.router.add_api_route('/api/skills/execute', self.skills_execute, methods=['POST'])
        self.router.add_api_route('/api/skills/stats', self.skills_stats, methods=['GET'])
        self.router.add_api_route('/api/skills/evolution/versions', self.skill_evolution_versions, methods=['GET'])
        self.router.add_api_route('/api/skills/evolution/runs', self.skill_evolution_runs, methods=['GET'])
        self.router.add_api_route('/api/skills/evolution/review-inbox', self.skill_evolution_review_inbox, methods=['GET'])
        self.router.add_api_route('/api/skills/evolution/candidates', self.skill_evolution_candidate, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/suites', self.skill_evolution_suite, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/versions/{version_id}/evaluate', self.skill_evolution_evaluate, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/versions/{version_id}/promote', self.skill_evolution_promote, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/versions/{version_id}/review', self.skill_evolution_review, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/versions/{version_id}/manifest', self.skill_evolution_manifest, methods=['GET'])
        self.router.add_api_route('/api/skills/evolution/versions/{version_id}/sign', self.skill_evolution_sign, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/versions/{version_id}/fresh-audit', self.skill_evolution_fresh_audit, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/versions/{version_id}/canary', self.skill_evolution_canary, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/promotions/{promotion_id}/rollback', self.skill_evolution_rollback, methods=['POST'])
        self.router.add_api_route('/api/skills/evolution/library-health', self.skill_evolution_library_health, methods=['GET'])
        self.router.add_api_route('/api/skills/evolution/library-compact', self.skill_evolution_library_compact, methods=['POST'])

    async def skills_list(self):
        try:
            from skills.skill_registry import list_skills
            return JSONResponse({"skills": list_skills(), "count": len(list_skills())})
        except Exception as e:
            return JSONResponse({"skills": [], "count": 0, "error": str(e)})


    async def skills_execute(self, request: Request):
        try:
            from skills.skill_registry import execute_skill, execute_skill_definition, get_skill

            data = await request.json()
            name = str(data.get("name") or "").strip()
            params = data.get("params") or {}
            plan_only = bool(data.get("plan_only", True))
            if not name:
                raise HTTPException(400, "skill name is required")
            if not isinstance(params, dict):
                raise HTTPException(400, "params must be an object")
            if plan_only:
                skill = get_skill(name)
                if not skill:
                    raise HTTPException(404, f"skill not found: {name}")
                result = execute_skill_definition(skill, params=params, plan_only=True)
            else:
                result = execute_skill(name, params)
            return JSONResponse({"mode": "plan" if plan_only else "execute", "result": result})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"skill execution failed: {e}")


    async def skills_stats(self):
        if not self.memory_store_provider():
            return JSONResponse({"records": [], "count": 0})
        records = self.memory_store_provider().get_skill_stats()
        return JSONResponse({"records": records, "count": len(records)})


    async def skill_evolution_versions(self, skill_name: str = "", limit: int = 100):
        if not self.skill_evolution_provider():
            return JSONResponse({"versions": [], "count": 0}, status_code=503)
        rows = self.skill_evolution_provider().list_versions(skill_name, limit)
        return JSONResponse({"versions": rows, "count": len(rows)})


    async def skill_evolution_runs(self, version_id: int = 0, limit: int = 100):
        if not self.skill_evolution_provider():
            return JSONResponse({"runs": [], "count": 0}, status_code=503)
        rows = self.skill_evolution_provider().list_runs(version_id, limit)
        return JSONResponse({"runs": rows, "count": len(rows)})


    async def skill_evolution_review_inbox(self, status: str = "", limit: int = 100):
        if not self.skill_evolution_provider():
            return JSONResponse({"items": [], "count": 0}, status_code=503)
        rows = self.skill_evolution_provider().review_inbox(status=status, limit=limit)
        return JSONResponse({"items": rows, "count": len(rows)})


    async def skill_evolution_candidate(self, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        try:
            result = self.skill_evolution_provider().propose(
                str(data.get("skill_name", "")),
                data.get("definition") or {},
                change_reason=str(data.get("change_reason", "")),
                source_ref=str(data.get("source_ref", "")),
                created_by=str(data.get("created_by", "user")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_suite(self, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        try:
            result = self.skill_evolution_provider().create_suite(
                str(data.get("name", "")),
                str(data.get("skill_name", "")),
                data.get("cases") or [],
                frozen=bool(data.get("frozen", True)),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_evaluate(self, version_id: int, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        try:
            result = self.skill_evolution_provider().evaluate(
                version_id, int(data.get("suite_id", 0)), data.get("thresholds") or {}
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_promote(self, version_id: int, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        if not bool(data.get("confirmed")):
            raise HTTPException(409, "explicit confirmed=true is required for skill promotion")
        try:
            result = self.skill_evolution_provider().promote(
                version_id, actor=str(data.get("actor", "user"))
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_review(self, version_id: int, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        try:
            result = self.skill_evolution_provider().review(
                version_id,
                action=str(data.get("action", "")),
                reviewer=str(data.get("reviewer", "user")),
                notes=str(data.get("notes", "")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_manifest(self, version_id: int):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        try:
            result = self.skill_evolution_provider().dependency_manifest(version_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return JSONResponse(result)


    async def skill_evolution_sign(self, version_id: int, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        try:
            result = self.skill_evolution_provider().sign_version(
                version_id,
                signer=str(data.get("signer", "user")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_fresh_audit(self, version_id: int, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        try:
            result = self.skill_evolution_provider().fresh_agent_audit(
                version_id,
                suite_id=data.get("suite_id"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_canary(self, version_id: int, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        try:
            result = self.skill_evolution_provider().start_canary(
                version_id,
                percent=data.get("percent", 10),
                actor=str(data.get("actor", "user")),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_rollback(self, promotion_id: int, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        if not bool(data.get("confirmed")):
            raise HTTPException(409, "explicit confirmed=true is required for skill rollback")
        try:
            result = self.skill_evolution_provider().rollback(promotion_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def skill_evolution_library_health(self):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        return JSONResponse(self.skill_evolution_provider().library_health())


    async def skill_evolution_library_compact(self, request: Request):
        if not self.skill_evolution_provider():
            raise HTTPException(503, "skill evolution is unavailable")
        data = await request.json()
        dry_run = bool(data.get("dry_run", True))
        if not dry_run and not bool(data.get("confirmed")):
            raise HTTPException(409, "explicit confirmed=true is required for compaction")
        return JSONResponse(self.skill_evolution_provider().compact_library(
            dry_run=dry_run,
            max_versions_per_skill=data.get("max_versions_per_skill", 5),
            actor=str(data.get("actor", "user")),
        ))
