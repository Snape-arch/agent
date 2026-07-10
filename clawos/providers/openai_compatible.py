from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .base import model_result, now_ms


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self, cfg: dict[str, Any]):
        self.provider = str(cfg.get("provider") or self.name)
        self.name = self.provider
        self.base_url = str(cfg.get("base_url") or "").rstrip("/")
        self.model = str(cfg.get("model") or "")
        self.api_key = str(cfg.get("api_key") or "")
        self.timeout_s = float(cfg.get("timeout_s", 120.0) or 120.0)
        self.requires_api_key = _as_bool(cfg.get("requires_api_key", True))
        self.chat_template_kwargs = cfg.get("chat_template_kwargs")

    def is_configured(self) -> bool:
        has_endpoint = bool(self.base_url and self.model)
        has_key = bool(self.api_key and "${" not in self.api_key)
        return has_endpoint and (has_key or not self.requires_api_key)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        options: dict[str, Any] | None = None,
        *,
        http_client: Any = None,
    ) -> dict[str, Any]:
        started = now_ms()
        if not self.is_configured():
            return model_result(
                ok=False,
                provider=self.name,
                model=self.model,
                duration_ms=now_ms() - started,
                error="missing_api_key",
            )

        options = options or {}
        payload = {
            "model": options.get("model") or self.model,
            "messages": messages,
            "stream": False,
            "temperature": options.get("temperature", 0.0),
        }
        if options.get("max_tokens") is not None:
            payload["max_tokens"] = int(options["max_tokens"])
        if options.get("response_format") is not None:
            payload["response_format"] = options["response_format"]
        if options.get("grammar") is not None:
            payload["grammar"] = options["grammar"]
        if options.get("stop") is not None:
            payload["stop"] = options["stop"]
        if options.get("tools") is not None:
            payload["tools"] = options["tools"]
        if options.get("tool_choice") is not None:
            payload["tool_choice"] = options["tool_choice"]
        chat_template_kwargs = options.get("chat_template_kwargs", self.chat_template_kwargs)
        if chat_template_kwargs is not None:
            payload["chat_template_kwargs"] = chat_template_kwargs

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        client = http_client or httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_s))
        close_client = http_client is None
        try:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            raw = resp.json()
            choices = raw.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                return model_result(
                    ok=False,
                    provider=self.name,
                    model=payload["model"],
                    raw=raw if isinstance(raw, dict) else {},
                    duration_ms=now_ms() - started,
                    error="invalid_response",
                )
            msg = choices[0].get("message") or {}
            content = str(msg.get("content") or msg.get("reasoning_content") or "")
            return model_result(
                ok=True,
                provider=self.name,
                model=payload["model"],
                content=content,
                raw=raw,
                usage=raw.get("usage") or {},
                duration_ms=now_ms() - started,
            )
        except (httpx.TimeoutException, asyncio.TimeoutError):
            return model_result(ok=False, provider=self.name, model=self.model, duration_ms=now_ms() - started, error="timeout")
        except httpx.HTTPStatusError:
            return model_result(ok=False, provider=self.name, model=self.model, duration_ms=now_ms() - started, error="provider_error")
        except (httpx.NetworkError, httpx.ConnectError, httpx.ReadError):
            return model_result(ok=False, provider=self.name, model=self.model, duration_ms=now_ms() - started, error="network_error")
        except Exception:
            return model_result(ok=False, provider=self.name, model=self.model, duration_ms=now_ms() - started, error="provider_error")
        finally:
            if close_client:
                await client.aclose()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}
