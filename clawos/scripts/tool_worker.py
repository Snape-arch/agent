#!/usr/bin/env python3
"""Isolated ClawOS tool worker with stdin/stdout JSON contract."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import tool_runner


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "tool name required"}))
        return 2
    name = sys.argv[1]
    if name in ("bash", "exec", "sh"):
        name = "shell_exec"
    handler = tool_runner.handlers.get(name)
    if not handler:
        print(json.dumps({"error": f"Unknown tool: {name}"}))
        return 3
    try:
        payload = json.load(sys.stdin)
        payload = payload if isinstance(payload, dict) else {}
        payload = tool_runner.security_check(name, payload)
    except (json.JSONDecodeError, PermissionError) as exc:
        print(json.dumps({"error": str(exc), "status": "denied"}, ensure_ascii=False))
        return 4

    tool_runner.input_data = payload
    tool_runner.tool_name = name
    output = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = output
    exit_code = 0
    try:
        handler()
    except SystemExit as exc:
        exit_code = int(exc.code or 0)
    except Exception as exc:
        sys.stdout = old_stdout
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        sys.stdout = old_stdout
    print(output.getvalue().strip() or json.dumps({"result": "ok"}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
