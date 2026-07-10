from __future__ import annotations

from typing import Any

from .openai_compatible import OpenAICompatibleProvider


class QwenProvider(OpenAICompatibleProvider):
    name = "qwen"

    def __init__(self, cfg: dict[str, Any]):
        merged = {
            "provider": "qwen",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "Qwen3.5-9B-Q4_K_M",
            "requires_api_key": False,
            "chat_template_kwargs": {"enable_thinking": False},
            **cfg,
        }
        super().__init__(merged)
        self.name = "qwen"
