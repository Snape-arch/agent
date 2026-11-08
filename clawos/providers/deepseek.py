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

    def prepare_options(self, options: dict[str, Any]) -> dict[str, Any]:
        response_format = options.get("response_format") or {}
        schema = response_format.get("json_schema") or {}
        if (self.base_url in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}
                and response_format.get("type") == "json_schema"
                and str(schema.get("name", "")).startswith("coding_")):
            # Chat Completions supports JSON mode. Coding callers still apply
            # the original bounded schema to every completed answer locally.
            return options | {"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}
        return options
