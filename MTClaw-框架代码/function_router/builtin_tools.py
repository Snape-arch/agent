"""Builtin shell tools for Function Router."""

from __future__ import annotations

import copy
import json
import os
import shlex
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


MAX_CAPTURE_CHARS = 16000
BUILTIN_FUNCTIONS_PATH = Path(__file__).with_name("function-builtin.jsonl")


@dataclass(slots=True)
class CommandResult:
    """Normalized shell execution result."""

    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def timed_out(self) -> bool:
        return self.exit_code in {124, 137}


@lru_cache(maxsize=1)
def load_builtin_function_schemas() -> tuple[dict[str, Any], ...]:
    """Load builtin function schemas from the packaged JSONL file."""

    if not BUILTIN_FUNCTIONS_PATH.exists():
        raise RuntimeError(f"builtin functions file not found: {BUILTIN_FUNCTIONS_PATH}")

    functions: list[dict[str, Any]] = []
    try:
        with BUILTIN_FUNCTIONS_PATH.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    function_obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"failed parsing {BUILTIN_FUNCTIONS_PATH}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(function_obj, dict):
                    raise RuntimeError(
                        f"invalid builtin function object at {BUILTIN_FUNCTIONS_PATH}:{line_number}"
                    )
                functions.append(function_obj)
    except OSError as exc:
        raise RuntimeError(
            f"failed reading builtin functions file: {BUILTIN_FUNCTIONS_PATH}"
        ) from exc

    return tuple(functions)


def get_builtin_tools() -> list[dict[str, Any]]:
    """Return builtin tools in OpenAI tools format."""

    return [
        {"type": "function", "function": copy.deepcopy(tool)}
        for tool in load_builtin_function_schemas()
    ]


def is_builtin_tool(name: str) -> bool:
    """Return whether *name* is handled internally."""

    return any(tool["name"] == name for tool in load_builtin_function_schemas())


def execute_builtin_tool(function_name: str, arguments_json: str, timeout_s: int) -> dict[str, Any]:
    """Execute one builtin tool via ``os.system`` and return JSON-compatible output."""

    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return {"error": f"invalid tool arguments: {exc.msg}"}

    if not isinstance(arguments, dict):
        return {"error": "tool arguments must be a JSON object"}

    try:
        if function_name == "find":
            return _execute_find(arguments, timeout_s)
        if function_name == "ls":
            return _execute_ls(arguments, timeout_s)
        if function_name == "cat":
            return _execute_cat(arguments, timeout_s)
        if function_name == "grep":
            return _execute_grep(arguments, timeout_s)
        if function_name == "sleep":
            return _execute_sleep(arguments, timeout_s)
    except ValueError as exc:
        return {"error": str(exc)}

    return {"error": f"unknown builtin tool: {function_name}"}


def _execute_find(arguments: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    raw_path = _optional_string(arguments, "path")
    path = os.path.expanduser(raw_path) if raw_path else os.path.expanduser("~")
    name_pattern = _optional_string(arguments, "name_pattern")
    name_patterns = _optional_string_list(arguments, "name_patterns")
    if name_pattern and not name_patterns:
        name_patterns = name_pattern.split() if " " in name_pattern else [name_pattern]
    entry_type = _optional_string(arguments, "entry_type") or "any"
    max_depth = _optional_non_negative_int(arguments, "max_depth")
    # 从 ~ 搜索时默认限制深度，避免超时
    if max_depth is None and not raw_path:
        max_depth = 6
    limit = _optional_positive_int(arguments, "limit", 100)
    case_insensitive = _optional_bool(arguments, "case_insensitive", True)

    if entry_type not in {"file", "directory", "any"}:
        raise ValueError("entry_type must be one of: file, directory, any")

    command_parts = ["find", shlex.quote(path)]
    if max_depth is not None:
        command_parts.extend(["-maxdepth", str(max_depth)])
    if entry_type == "file":
        command_parts.extend(["-type", "f"])
    elif entry_type == "directory":
        command_parts.extend(["-type", "d"])
    if name_patterns:
        name_operator = "-iname" if case_insensitive else "-name"
        if len(name_patterns) == 1:
            command_parts.extend([name_operator, shlex.quote(name_patterns[0])])
        else:
            command_parts.append(r"\(")
            for index, pattern in enumerate(name_patterns):
                if index:
                    command_parts.append("-o")
                command_parts.extend([name_operator, shlex.quote(pattern)])
            command_parts.append(r"\)")

    command = " ".join(command_parts) + f" | head -n {limit}"
    result = _run_command(command, timeout_s)
    return _success_payload("find", result, "matches")


def _execute_ls(arguments: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    path = _require_path(arguments, "path")
    show_hidden = _optional_bool(arguments, "show_hidden", False)
    long_listing = _optional_bool(arguments, "long", False)
    recursive = _optional_bool(arguments, "recursive", False)

    command_parts = ["ls"]
    if long_listing:
        command_parts.append("-l")
    else:
        command_parts.append("-1")
    if show_hidden:
        command_parts.append("-A")
    if recursive:
        command_parts.append("-R")
    command_parts.extend(["--", shlex.quote(path)])

    result = _run_command(" ".join(command_parts), timeout_s)
    return _success_payload("ls", result, "entries")


def _execute_cat(arguments: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    path = _require_path(arguments, "path")
    max_lines = _optional_positive_int(arguments, "max_lines", 200)

    command = f"cat -- {shlex.quote(path)} | head -n {max_lines}"
    result = _run_command(command, timeout_s)
    return _success_payload("cat", result)


def _execute_grep(arguments: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    pattern = _require_string(arguments, "pattern")
    path = _require_path(arguments, "path")
    recursive = _optional_bool(arguments, "recursive", False)
    ignore_case = _optional_bool(arguments, "ignore_case", False)
    line_numbers = _optional_bool(arguments, "line_numbers", True)
    file_glob = _optional_string(arguments, "file_glob")
    limit = _optional_positive_int(arguments, "limit", 100)

    if file_glob and not recursive:
        raise ValueError("file_glob requires recursive=true")

    command_parts = ["grep"]
    if recursive:
        command_parts.append("-R")
    if ignore_case:
        command_parts.append("-i")
    if line_numbers:
        command_parts.append("-n")
    if file_glob:
        command_parts.append(f"--include={shlex.quote(file_glob)}")
    command_parts.extend(["--", shlex.quote(pattern), shlex.quote(path)])

    command = " ".join(command_parts) + f" | head -n {limit}"
    result = _run_command(command, timeout_s)
    if result.exit_code == 1 and not result.stderr:
        return {
            "result": "ok",
            "command": result.command,
            "tool_output": "",
            "matches": [],
            "count": 0,
        }
    return _success_payload("grep", result, "matches")


def _execute_sleep(arguments: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    seconds = _require_number(arguments, "seconds")
    if seconds < 0:
        raise ValueError("seconds must be a non-negative number")

    seconds_text = _format_number(seconds)
    command = f"sleep {seconds_text}"
    result = _run_command(command, timeout_s)
    payload = _success_payload("sleep", result)
    if "error" not in payload:
        payload["seconds"] = seconds
        payload["tool_output"] = f"slept {seconds_text} seconds"
    return payload


def _success_payload(tool_name: str, result: CommandResult, list_key: str | None = None) -> dict[str, Any]:
    if result.timed_out:
        payload: dict[str, Any] = {
            "error": "execution timeout",
            "returncode": result.exit_code,
            "command": result.command,
        }
        if result.stdout:
            payload["stdout"] = result.stdout
        if result.stderr:
            payload["stderr"] = result.stderr
        return payload

    if result.exit_code != 0:
        payload = {
            "error": result.stderr or f"{tool_name} command failed",
            "returncode": result.exit_code,
            "command": result.command,
        }
        if result.stdout:
            payload["stdout"] = result.stdout
        return payload

    payload = {
        "result": "ok",
        "command": result.command,
        "tool_output": result.stdout,
    }
    if list_key is not None:
        items = [line for line in result.stdout.splitlines() if line]
        payload[list_key] = items
        payload["count"] = len(items)
    return payload


def _run_command(command: str, timeout_s: int) -> CommandResult:
    timeout_seconds = max(int(timeout_s), 1)
    stdout_path = ""
    stderr_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as stdout_file:
            stdout_path = stdout_file.name
        with tempfile.NamedTemporaryFile(delete=False) as stderr_file:
            stderr_path = stderr_file.name

        wrapped = (
            f"timeout {timeout_seconds}s bash -o pipefail -c {shlex.quote(command)} "
            f"> {shlex.quote(stdout_path)} 2> {shlex.quote(stderr_path)}"
        )
        status = os.system(wrapped)
        exit_code = os.waitstatus_to_exitcode(status)
        stdout = _read_text(stdout_path)
        stderr = _read_text(stderr_path)
        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        for path in (stdout_path, stderr_path):
            if path:
                try:
                    Path(path).unlink()
                except FileNotFoundError:
                    pass


def _read_text(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    text = text.rstrip("\n")
    if len(text) > MAX_CAPTURE_CHARS:
        return text[:MAX_CAPTURE_CHARS] + "\n...[truncated]"
    return text


def _require_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _require_path(arguments: dict[str, Any], key: str) -> str:
    return os.path.expanduser(_require_string(arguments, key))


def _optional_string(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    value = value.strip()
    return value or None


def _optional_string_list(arguments: dict[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} must be a list of strings")
        item = item.strip()
        if item:
            items.append(item)
    return items


def _optional_bool(arguments: dict[str, Any], key: str, default: bool) -> bool:
    value = arguments.get(key, default)
    if isinstance(value, bool):
        return value
    raise ValueError(f"{key} must be a boolean")


def _optional_non_negative_int(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _optional_positive_int(arguments: dict[str, Any], key: str, default: int) -> int:
    value = arguments.get(key, default)
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _require_number(arguments: dict[str, Any], key: str) -> float:
    value = arguments.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return format(value, "g")
