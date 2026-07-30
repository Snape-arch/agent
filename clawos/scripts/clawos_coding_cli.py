#!/usr/bin/env python3
"""Headless ClawOS coding client with stable JSON output."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _post(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _validate_schema(value: dict[str, Any], schema_path: str) -> None:
    if not schema_path:
        return
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    missing = [
        key for key in schema.get("required") or [] if key not in value
    ]
    if missing:
        raise ValueError("output schema missing required fields: " + ", ".join(missing))
    expected = schema.get("properties") or {}
    type_map = {
        "string": str, "object": dict, "array": list,
        "boolean": bool, "integer": int, "number": (int, float),
    }
    invalid = [
        key for key, rule in expected.items()
        if key in value and rule.get("type") in type_map
        and not isinstance(value[key], type_map[rule["type"]])
    ]
    if invalid:
        raise ValueError("output schema type mismatch: " + ", ".join(invalid))


def main() -> int:
    parser = argparse.ArgumentParser(prog="clawos-code")
    parser.add_argument("objective")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:18790")
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument(
        "--output-format", choices=("text", "json", "stream-json"),
        default="text",
    )
    parser.add_argument("--json-schema", default="")
    args = parser.parse_args()
    try:
        result = _post(args.base_url, "/api/workspace/coding/autonomous", {
            "repo_path": str(Path(args.repo).expanduser().resolve()),
            "objective": args.objective,
            "task_id": args.task_id,
            "session_id": args.session_id,
            "confirmed": args.confirmed,
            "max_turns": args.max_turns,
            "actor_id": "headless-cli",
        })
        _validate_schema(result, args.json_schema)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "type": "error", "error": f"{type(exc).__name__}: {exc}"
        }), file=sys.stderr)
        return 2
    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False))
    elif args.output_format == "stream-json":
        print(json.dumps({
            "type": "start", "trajectory_id": result.get("trajectory_id"),
        }, ensure_ascii=False))
        for observation in result.get("observations") or []:
            print(json.dumps({
                "type": "observation", "data": observation,
            }, ensure_ascii=False))
        for attempt in result.get("attempts") or []:
            print(json.dumps({
                "type": "attempt", "data": attempt,
            }, ensure_ascii=False))
        print(json.dumps({"type": "result", "data": result}, ensure_ascii=False))
    else:
        print(
            result.get("summary")
            or result.get("error")
            or result.get("status")
            or ""
        )
    return 0 if result.get("status") in {
        "passed", "waiting_confirmation"
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
