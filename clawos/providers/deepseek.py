from __future__ import annotations

from typing import Any

from .openai_compatible import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"

    def __init__(self, cfg: dict[str, Any]):
        merged = {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            **cfg,
        }
        super().__init__(merged)
        self.name = "deepseek"
