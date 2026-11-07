"""Model HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi.responses import JSONResponse


class ModelAPI:
    def __init__(self, *,
        _provider_candidates: Callable[..., Any],
        local_model_assets_status: Callable[..., Any],
        http_client_provider: Callable[[], Any],
    ):
        self._provider_candidates = _provider_candidates
        self.local_model_assets_status = local_model_assets_status
        self.http_client_provider = http_client_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/model/health', self.api_model_health, methods=['GET'])

    async def api_model_health(self, probe: bool = False):
        sections = {}
        for section in ("routing", "upstream"):
            attempts = []
            for provider in self._provider_candidates(section):
                if not provider:
                    continue
                configured = provider.is_configured() if hasattr(provider, "is_configured") else True
                item = {
                    "provider": getattr(provider, "name", ""),
                    "model": getattr(provider, "model", ""),
                    "configured": bool(configured),
                    "reachable": None,
                    "error": "",
                    "duration_ms": 0,
                }
                if probe and configured:
                    result = await provider.complete(
                        [{"role": "user", "content": "health check: reply ok"}],
                        {"temperature": 0.0},
                        http_client=self.http_client_provider(),
                    )
                    item.update({
                        "reachable": bool(result.get("ok")),
                        "error": result.get("error", ""),
                        "duration_ms": result.get("duration_ms", 0),
                    })
                attempts.append(item)
            sections[section] = {
                "primary": attempts[0] if attempts else {},
                "fallbacks": attempts[1:],
                "configured": any(a.get("configured") for a in attempts),
                "reachable": any(a.get("reachable") for a in attempts) if probe else None,
                "fallback_strategy": "ordered_provider_fallback",
            }
        sections["local_model_assets"] = self.local_model_assets_status()
        return JSONResponse(sections)
