#!/usr/bin/env python3
"""Generate a minimal, low-risk MTClaw runtime for ClawOS."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

try:
    from .bridge_runner import NO_WRITE_ARGUMENTS, SAFE_ACTIONS, SAFE_TOOLS
except ImportError:
    from bridge_runner import NO_WRITE_ARGUMENTS, SAFE_ACTIONS, SAFE_TOOLS


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ROOT / "functions.jsonl"
RUNTIME = ROOT / "mtclaw_runtime"


def _least_privilege_schema(function: dict) -> dict:
    item = json.loads(json.dumps(function))
    name = str(item.get("name") or "")
    parameters = item.get("parameters") or {}
    properties = parameters.get("properties") or {}
    for key in NO_WRITE_ARGUMENTS.get(name, set()):
        properties.pop(key, None)
        parameters["required"] = [value for value in parameters.get("required", []) if value != key]
    if name in SAFE_ACTIONS and "action" in properties:
        properties["action"]["enum"] = sorted(SAFE_ACTIONS[name])
    parameters["properties"] = properties
    item["parameters"] = parameters
    return item


def prepare(runtime_dir: Path = RUNTIME) -> dict:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = runtime_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)

    selected = []
    with FUNCTIONS.open("r", encoding="utf-8-sig") as source:
        for line in source:
            if not line.strip():
                continue
            function = json.loads(line)
            if function.get("name") in SAFE_TOOLS:
                selected.append(_least_privilege_schema(function))

    functions_path = runtime_dir / "functions.jsonl"
    functions_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in selected),
        encoding="utf-8",
    )

    bridge = ROOT / "mtclaw" / "bridge_runner.py"
    for function in selected:
        name = function["name"]
        wrapper = scripts_dir / f"{name}.sh"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'exec "${{PYTHON:-python3}}" "{bridge.as_posix()}" {name}\n',
            encoding="utf-8",
            newline="\n",
        )
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        cmd_wrapper = scripts_dir / f"{name}.cmd"
        cmd_wrapper.write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            'if "%PYTHON%"=="" set "PYTHON=python"\r\n'
            f'"%PYTHON%" "{bridge}" {name}\r\n'
            "exit /b %ERRORLEVEL%\r\n",
            encoding="utf-8",
            newline="",
        )

    config = {
        "listen_host": "127.0.0.1",
        "listen_port": 18791,
        "builtin_tools_enabled": False,
        "routing": {
            "base_url": os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com/v1"),
            "model": os.environ.get("MODEL_NAME", "deepseek-chat"),
            "api_key": "${MODEL_API_KEY}",
        },
        "upstream": {
            "base_url": os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com/v1"),
            "model": os.environ.get("MODEL_NAME", "deepseek-chat"),
            "api_key": "${MODEL_API_KEY}",
        },
        "functions_file": "functions.jsonl",
        "scripts_dir": "scripts",
        "max_tool_rounds": 6,
        "tool_exec_timeout_s": 30,
        "routing_timeout_s": 15.0,
        "fr_completion_check": {"enabled": True, "mode": "strict", "always_true": False},
        "fr_context_history": {"enabled": True},
        "fr_context_preserve": {"enabled": False},
        "debug_logging": {"enabled": True},
    }
    config_path = runtime_dir / "config.json"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "runtime_dir": str(runtime_dir),
        "config": str(config_path),
        "functions": str(functions_path),
        "scripts": len(selected),
        "safe_tools": [item["name"] for item in selected],
    }


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
