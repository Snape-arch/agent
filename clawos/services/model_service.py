from __future__ import annotations

from typing import Any, Callable


class ModelService:
    """Small boundary for provider status/config decisions used by the API."""

    def __init__(self, config: dict[str, Any], provider_factory: Callable[[dict[str, Any]], Any]):
        self.config = config or {}
        self.provider_factory = provider_factory

    def status(self) -> dict[str, Any]:
        provider_cfg = self.config.get("model_provider") or self.config.get("upstream") or {}
        provider = self.provider_factory(provider_cfg)
        configured = provider.is_configured() if hasattr(provider, "is_configured") else True
        return {
            "provider": getattr(provider, "name", provider_cfg.get("provider", "")),
            "model": getattr(provider, "model", provider_cfg.get("model", "")),
            "configured": bool(configured),
        }

    @staticmethod
    def mode_label(provider: str, configured: bool) -> str:
        provider = str(provider or "").lower()
        if provider == "qwen":
            return "Local Qwen 模式" if configured else "Local Qwen 待启动"
        if provider == "mock":
            return "Mock/offline test 模式"
        if provider in {"qwen_api", "glm", "zhipu", "deepseek", "openai_compatible"}:
            return "DeepSeek/API 模式" if configured else "API 待配置"
        return "模型待配置"
