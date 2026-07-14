"""OpenAI-compatible adapter for the local MTClaw Function Router."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx


class MTClawAdapter:
    """Route ClawOS requests through an external MTClaw provider endpoint."""

    def __init__(self, config: dict[str, Any], http_client: Any = None):
        self.enabled = _as_bool(config.get("enabled", False))
        self.base_url = str(config.get("base_url", "http://127.0.0.1:18791")).rstrip("/")
        self.model = str(config.get("model", "function-router"))
        self.timeout_s = float(config.get("timeout_s", 120.0))
        self.fallback_on_error = _as_bool(config.get("fallback_on_error", True))
        self._http = http_client

    async def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "reachable": False, "status": "disabled"}
        started = time.perf_counter()
        try:
            response = await self._client().get(
                f"{self.base_url}/health",
                timeout=min(self.timeout_s, 10.0),
            )
            response.raise_for_status()
            payload = response.json()
            return {
                "enabled": True,
                "reachable": True,
                "status": payload.get("status", "ok"),
                "ready": payload.get("ready", payload.get("warmup_ok", True)),
                "tools_loaded": payload.get("tools_loaded"),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except Exception as exc:
            return {
                "enabled": True,
                "reachable": False,
                "status": "unavailable",
                "error": type(exc).__name__,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }

    async def route(
        self,
        messages: list[dict[str, Any]],
        session_id: str,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        request_started_at = datetime.now(timezone.utc).isoformat()
        options = options or {}
        payload = {
            "model": options.get("model") or self.model,
            "messages": messages,
            "stream": False,
            "temperature": options.get("temperature", 0.0),
            "session_id": session_id,
        }
        headers = {
            "Content-Type": "application/json",
            "x-openclaw-session-id": session_id,
        }
        try:
            response = await self._client().post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            raw = response.json()
            trace = await self._fetch_trace(session_id, request_started_at)
            return {
                "ok": True,
                "provider": "mtclaw",
                "model": raw.get("model", payload["model"]),
                "raw": raw,
                "content": _assistant_content(raw),
                "trace": trace,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": "",
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": "mtclaw",
                "model": payload["model"],
                "raw": {},
                "content": "",
                "trace": [],
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error": type(exc).__name__,
            }

    async def _fetch_trace(self, session_id: str, since: str) -> list[dict[str, Any]]:
        try:
            async def fetch(params: dict[str, Any]) -> list[dict[str, Any]]:
                response = await self._client().get(
                    f"{self.base_url}/v1/tool_history", params=params,
                    timeout=min(self.timeout_s, 10.0),
                )
                response.raise_for_status()
                return response.json().get("entries") or []

            entries = await fetch({"since": since, "limit": 20})
            matched = [entry for entry in entries if str(entry.get("session_key", "")) == str(session_id)]
            # Router history clocks may have coarser precision than the client
            # request timestamp. Retry without `since`, still scoped to the
            # exact session, instead of silently losing a real tool trace.
            if not matched:
                entries = await fetch({"limit": 50})
                matched = [entry for entry in entries if str(entry.get("session_key", "")) == str(session_id)]
            return _normalize_history(matched)
        except Exception:
            return []

    def _client(self):
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_s),
                trust_env=False,
            )
        return self._http


def _assistant_content(raw: dict[str, Any]) -> str:
    choices = raw.get("choices") or []
    if not choices:
        return ""
    return str((choices[0].get("message") or {}).get("content") or "")


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces = []
    for entry in entries:
        results = {
            item.get("tool_call_id", ""): item
            for item in entry.get("tool_results", [])
        }
        for call in entry.get("tool_calls", []):
            call_id = call.get("id", "")
            result = results.get(call_id, {})
            arguments = call.get("arguments", "{}")
            content = result.get("content", "{}")
            try:
                arguments = __import__("json").loads(arguments) if isinstance(arguments, str) else arguments
            except ValueError:
                arguments = {}
            try:
                content = __import__("json").loads(content) if isinstance(content, str) else content
            except ValueError:
                content = {"raw": str(content)}
            traces.append({
                "timestamp": call.get("timestamp") or entry.get("timestamp", ""),
                "session_key": entry.get("session_key", ""),
                "user_message": entry.get("user_message", ""),
                "function_name": call.get("name", ""),
                "tool_input": arguments,
                "tool_result": content,
                "is_error": bool(result.get("is_error")),
                "tool_rounds": entry.get("tool_rounds", 0),
            })
    return traces
