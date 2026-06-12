from __future__ import annotations

from typing import Any

from .base import model_result, now_ms


class MockProvider:
    name = "mock"

    def __init__(self, cfg: dict[str, Any]):
        self.model = str(cfg.get("model") or "mock-model")
        self.response = str(cfg.get("mock_response") or "mock response")
        self.fail_with = str(cfg.get("fail_with") or "")

    def is_configured(self) -> bool:
        return True

    async def complete(
        self,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        *,
        http_client: Any = None,
    ) -> dict[str, Any]:
        started = now_ms()
        if self.fail_with:
            return model_result(
                ok=False,
                provider=self.name,
                model=self.model,
                duration_ms=now_ms() - started,
                error=self.fail_with,
            )
        raw = {
            "choices": [{"message": {"role": "assistant", "content": self.response}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        return model_result(
            ok=True,
            provider=self.name,
            model=self.model,
            content=self.response,
            raw=raw,
            usage=raw["usage"],
            duration_ms=now_ms() - started,
        )
