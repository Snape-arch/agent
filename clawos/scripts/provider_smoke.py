#!/usr/bin/env python3
"""Real model-provider smoke test. Reads credentials only from environment."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers import create_model_provider


def provider_config():
    return {
        "provider": os.environ.get("MODEL_PROVIDER", "deepseek"),
        "base_url": os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com/v1"),
        "model": os.environ.get("MODEL_NAME", "deepseek-chat"),
        "api_key": os.environ.get("MODEL_API_KEY", ""),
        "timeout_s": float(os.environ.get("MODEL_TIMEOUT_S", "60")),
    }


async def run():
    cfg = provider_config()
    provider = create_model_provider(cfg)
    checks = []

    direct = await provider.complete([
        {"role": "system", "content": "Reply with exactly CLAWOS_PROVIDER_OK."},
        {"role": "user", "content": "Run the provider connectivity check."},
    ], {"temperature": 0})
    checks.append({
        "name": "direct_completion",
        "ok": direct["ok"] and "CLAWOS_PROVIDER_OK" in direct["content"],
        "duration_ms": direct["duration_ms"],
        "usage": direct["usage"],
        "error": direct["error"],
    })

    tool = await provider.complete([
        {"role": "system", "content": "Use the provided tool for time requests."},
        {"role": "user", "content": "What time is it?"},
    ], {
        "temperature": 0,
        "tools": [{
            "type": "function",
            "function": {
                "name": "time_now",
                "description": "Get current local time",
                "parameters": {"type": "object", "properties": {}},
            },
        }],
        "tool_choice": "auto",
    })
    message = {}
    if tool["ok"]:
        choices = tool["raw"].get("choices") or []
        message = choices[0].get("message") or {} if choices else {}
    checks.append({
        "name": "tool_calling",
        "ok": tool["ok"] and bool(message.get("tool_calls")),
        "duration_ms": tool["duration_ms"],
        "error": tool["error"] or ("" if message.get("tool_calls") else "no_tool_call"),
    })

    reflection = await provider.complete([
        {
            "role": "system",
            "content": (
                "Return JSON only with keys root_cause, insights, improvements, patterns. "
                "The last tool failed because the path did not exist."
            ),
        },
        {"role": "user", "content": "Reflect on the failed file task."},
    ], {"temperature": 0})
    parsed = None
    if reflection["ok"]:
        try:
            parsed = json.loads(reflection["content"].strip().strip("`").removeprefix("json").strip())
        except json.JSONDecodeError:
            parsed = None
    checks.append({
        "name": "reflection_json",
        "ok": isinstance(parsed, dict) and "root_cause" in parsed,
        "duration_ms": reflection["duration_ms"],
        "error": reflection["error"] or ("" if parsed else "invalid_json"),
    })

    report = {
        "provider": cfg["provider"],
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "configured": bool(cfg["api_key"]),
        "checks": checks,
        "passed": all(item["ok"] for item in checks),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
