from __future__ import annotations

from typing import Any

from .deepseek import DeepSeekProvider
from .mock import MockProvider
from .openai_compatible import OpenAICompatibleProvider
from .qwen import QwenProvider


def create_model_provider(cfg: dict[str, Any]):
    provider = str(cfg.get("provider") or "deepseek").lower()
    if provider == "deepseek":
        return DeepSeekProvider(cfg)
    if provider in {"openai_compatible", "openai-compatible", "local_openai"}:
        return OpenAICompatibleProvider({**cfg, "provider": "openai_compatible"})
    if provider == "qwen":
        return QwenProvider(cfg)
    if provider == "mock":
        return MockProvider(cfg)
    raise ValueError(f"Unsupported model provider: {provider}")
