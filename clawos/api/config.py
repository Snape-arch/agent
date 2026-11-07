"""Config HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request


class ConfigAPI:
    def __init__(self, *,
        apply_model_config_updates: Callable[..., Any],
        model_config_payload: Callable[..., Any],
        config_provider: Callable[[], Any],
    ):
        self.apply_model_config_updates = apply_model_config_updates
        self.model_config_payload = model_config_payload
        self.config_provider = config_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/config/model', self.get_model_config, methods=['GET'])
        self.router.add_api_route('/api/config/model', self.update_model_config, methods=['POST'])

    async def get_model_config(self):
        return self.model_config_payload(self.config_provider())


    async def update_model_config(self, request: Request):
        try:
            payload = await request.json()
            updated = self.apply_model_config_updates(payload if isinstance(payload, dict) else {})
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            raise HTTPException(500, f"Model config update failed: {e}")
        return updated
