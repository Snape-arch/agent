from __future__ import annotations

import time
from typing import Any, Protocol


class ModelProvider(Protocol):
    name: str
    model: str

    async def complete(
        self,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        *,
        http_client: Any = None,
    ) -> dict[str, Any]:
        ...


def model_result(
    *,
    ok: bool,
    provider: str,
    model: str,
    content: str = "",
    raw: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    duration_ms: float = 0,
    error: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "provider": provider,
        "model": model,
        "content": content,
        "raw": raw or {},
        "usage": usage or {},
        "duration_ms": round(float(duration_ms or 0), 2),
        "error": error,
    }


def now_ms() -> float:
    return time.perf_counter() * 1000
