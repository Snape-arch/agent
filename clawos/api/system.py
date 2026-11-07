"""System HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import asyncio
from services.runtime_release import core_ready


class SystemAPI:
    def __init__(self, *,
        _system_readiness_payload: Callable[..., Any],
        get_maintenance_service: Callable[..., Any],
        model_mode_label: Callable[..., Any],
        model_provider_status: Callable[..., Any],
        data_dir_provider: Callable[[], Any],
        memory_db_provider: Callable[[], Any],
        output_root_provider: Callable[[], Any],
        runtime_release_provider: Callable[[], Any],
        config_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
        mtclaw_adapter_provider: Callable[[], Any],
        policy_optimizer_provider: Callable[[], Any],
        reflection_engine_provider: Callable[[], Any],
        secret_manager_provider: Callable[[], Any],
        security_policy_provider: Callable[[], Any],
        skill_evolution_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
        workspace_services_provider: Callable[[], Any],
        tools_def_provider: Callable[[], Any],
    ):
        self._system_readiness_payload = _system_readiness_payload
        self.get_maintenance_service = get_maintenance_service
        self.model_mode_label = model_mode_label
        self.model_provider_status = model_provider_status
        self.data_dir_provider = data_dir_provider
        self.memory_db_provider = memory_db_provider
        self.output_root_provider = output_root_provider
        self.runtime_release_provider = runtime_release_provider
        self.config_provider = config_provider
        self.memory_store_provider = memory_store_provider
        self.mtclaw_adapter_provider = mtclaw_adapter_provider
        self.policy_optimizer_provider = policy_optimizer_provider
        self.reflection_engine_provider = reflection_engine_provider
        self.secret_manager_provider = secret_manager_provider
        self.security_policy_provider = security_policy_provider
        self.skill_evolution_provider = skill_evolution_provider
        self.vector_store_provider = vector_store_provider
        self.workspace_services_provider = workspace_services_provider
        self.tools_def_provider = tools_def_provider
        self.router = APIRouter()
        self.router.add_api_route('/health', self.health, methods=['GET'])
        self.router.add_api_route('/api/system/config/check', self.api_system_config_check, methods=['GET'])
        self.router.add_api_route('/api/system/migrations', self.api_system_migrations, methods=['GET'])
        self.router.add_api_route('/api/system/migrations/apply', self.api_system_migrations_apply, methods=['POST'])
        self.router.add_api_route('/api/system/backup', self.api_system_backup, methods=['POST'])
        self.router.add_api_route('/api/system/restore', self.api_system_restore, methods=['POST'])
        self.router.add_api_route('/api/system/backup/bundle', self.api_system_backup_bundle, methods=['POST'])
        self.router.add_api_route('/api/system/restore/drill', self.api_system_restore_drill, methods=['POST'])
        self.router.add_api_route('/api/system/readiness', self.api_system_readiness, methods=['GET'])
        self.router.add_api_route('/api/architecture/chain', self.architecture_chain, methods=['GET'])

    async def health(self):
        provider_state = self.model_provider_status(self.config_provider()) if self.config_provider() else {"provider": "", "model": "", "configured": False}
        mtclaw_state = (
            await self.mtclaw_adapter_provider().health()
            if self.mtclaw_adapter_provider()
            else {"enabled": False, "reachable": False, "status": "not_initialized"}
        )
        database_state = {"configured": False, "reachable": False, "status": "not_initialized"}
        if self.memory_store_provider():
            try:
                from services.recovery_bundle import assert_workspace_complete
                assert_workspace_complete(self.data_dir_provider(),self.memory_db_provider())
                with self.memory_store_provider()._conn() as conn:
                    conn.execute("SELECT 1").fetchone()
                database_state = {
                    "configured": True,
                    "reachable": True,
                    "status": "ok",
                    "engine": "sqlite",
                }
            except Exception as exc:
                database_state = {
                    "configured": True,
                    "reachable": False,
                    "status": "error",
                    "error": type(exc).__name__,
                    "engine": "sqlite",
                }
        release = await asyncio.to_thread(self.runtime_release_provider().status)
        vector_state = {'initialized': False, 'consistent': False}
        if self.vector_store_provider():
            try:
                stats = await asyncio.to_thread(self.vector_store_provider().stats)
                vector_state = {key: stats.get(key) for key in ('provider', 'requested_provider', 'embedding_provider', 'consistent', 'fallback_reason', 'outbox_pending', 'outbox_failed')}
                vector_state['initialized'] = True
            except Exception as exc:
                vector_state['error'] = type(exc).__name__
        return {
            "status": "ok",
            "version": "1.0.0",
            "release": release,
            "core_ready": core_ready(database_state, self.workspace_services_provider(), release, vector_state),
            "vector": vector_state,
            "tools": len(self.tools_def_provider()),
            "memory": bool(self.memory_store_provider()),
            "database": database_state,
            "reflection": bool(self.reflection_engine_provider()),
            "policy_optimizer": bool(self.policy_optimizer_provider()),
            "security_policy": bool(self.security_policy_provider()),
            "secret_manager": bool(self.secret_manager_provider()),
            "workspace_services": bool(self.workspace_services_provider()),
            "skill_evolution": bool(self.skill_evolution_provider()),
            "model_provider": provider_state,
            "model_mode": self.model_mode_label(provider_state.get("provider", ""), bool(provider_state.get("configured"))),
            "routing_model": self.config_provider().get("routing", {}).get("model", ""),
            "upstream_model": self.config_provider().get("upstream", {}).get("model", ""),
            "mtclaw": mtclaw_state,
        }


    async def api_system_config_check(self):
        try:
            return JSONResponse(self.get_maintenance_service().config_check())
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))


    async def api_system_migrations(self):
        try:
            return JSONResponse(self.get_maintenance_service().list_migrations())
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))


    async def api_system_migrations_apply(self):
        try:
            return JSONResponse(self.get_maintenance_service().apply_migrations())
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))


    async def api_system_backup(self, request: Request):
        data = await request.json()
        try:
            result = self.get_maintenance_service().backup_database(
                output_dir=str(data.get("output_dir") or ""),
                label=str(data.get("label") or ""),
            )
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_system_restore(self, request: Request):
        data = await request.json()
        try:
            result = self.get_maintenance_service().restore_database(
                str(data.get("backup_path") or data.get("path") or ""),
                confirm=bool(data.get("confirm", False)),
                label=str(data.get("label") or "pre-restore"),
            )
            if self.vector_store_provider():
                result['vector_recovery']=self.vector_store_provider().rebuild()
                if not result['vector_recovery'].get('consistent'):
                    raise RuntimeError('Database restored; vector rebuild is incomplete. Pre-restore backup retained.')
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_system_backup_bundle(self, request: Request):
        from services.recovery_bundle import RecoveryBundle
        data=await request.json()
        try:
            return await asyncio.to_thread(RecoveryBundle(self.get_maintenance_service(),self.output_root_provider()/'academy-materials').backup,str(data.get('label') or 'complete'))
        except (ValueError,RuntimeError,OSError) as e:raise HTTPException(400,str(e))


    async def api_system_restore_drill(self, request: Request):
        from services.recovery_bundle import RecoveryBundle
        data=await request.json()
        try:
            return await asyncio.to_thread(RecoveryBundle(self.get_maintenance_service(),self.output_root_provider()/'academy-materials').restore_isolated,str(data.get('bundle_path') or ''))
        except (ValueError,RuntimeError,OSError) as e:raise HTTPException(400,str(e))


    async def api_system_readiness(self):
        return JSONResponse(self._system_readiness_payload())


    async def architecture_chain(self):
        health = await self.mtclaw_adapter_provider().health() if self.mtclaw_adapter_provider() else {'enabled':False,'status':'not_initialized'}
        return {'architecture':'ClawOS 工作台 / 记忆 / 执行策略 → MTClaw 函数路由 → 受限工具桥 → 本次请求 trace → 反思',
                'mtclaw':health,'fallback_on_error':self.mtclaw_adapter_provider().fallback_on_error if self.mtclaw_adapter_provider() else None,
                'trace_contract':'request_id + session_key；旧路由器缺少 request_id 时不认领历史工具调用',
                'safe_tools':sorted(__import__('mtclaw.bridge_runner',fromlist=['SAFE_TOOLS']).SAFE_TOOLS),
                'boundary':'同会话请求在 ClawOS 适配器中串行；桥仅接受白名单动作，写操作仍走 ClawOS 策略。'}
