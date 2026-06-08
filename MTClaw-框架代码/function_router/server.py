"""Function Router service.

This module implements a FastAPI service that accepts OpenAI-compatible
``/v1/chat/completions`` requests, uses a local Qwen model to detect tool calls
for system control actions, executes those actions via local shell scripts, and
falls back to transparently proxying requests to an upstream model provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

try:
    from .builtin_tools import execute_builtin_tool, get_builtin_tools, is_builtin_tool
except ImportError:  # pragma: no cover - direct script execution fallback
    from builtin_tools import execute_builtin_tool, get_builtin_tools, is_builtin_tool


#SYSTEM_PROMPT = (
#    "You are a system and filesystem assistant. Use the provided tools to handle "
#    "user requests about system settings, wallpaper, volume, brightness, file "
#    "search, directory listing, file reading, text search, and short waits. If a "
#    "user request does not match any available tool, respond with a brief text "
#    "saying you cannot handle it. Always respond in the same language as the user."
#)

#SYSTEM_PROMPT = (
#    "You are a system and filesystem assistant. Use the provided tools to handle "
#    "user requests about system settings, wallpaper, volume, brightness, file "
#    "search, directory listing, file reading, text search, and short waits. If a "
#    "user request does not match any available tool, respond with a brief text "
#    "saying you cannot handle it. Always respond in the same language as the user."
#)

SYSTEM_PROMPT = (
    "You are a system and filesystem assistant. Use only the provided tools to handle "
    "user requests about system settings, wallpaper, volume, brightness, file search, "
    "directory listing, file reading, text search, and short waits. "
    "If a request does not match any available tool, reply briefly that you cannot handle it. "
    "You must always reply in Chinese. "
    "Do not use emojis, emoticons, or decorative symbols. "
    "You must strictly base your reply on tool outputs only. Do not add any information "
    "that is not directly supported by the tool results. Do not speculate, infer, expand, "
    "or provide extra commentary. "
    "When issuing a tool call that uses any exact value from a previous tool result, such as a "
    "file path, file name, URL, ID, command output field, or other identifier, you must copy that "
    "value verbatim exactly as it appears in the tool result. "
    "Never shorten, summarize, normalize, translate, rename, or rewrite such values. "
    "Never replace any part of an exact value with ellipsis like '...' or similar placeholders. "
    "Never substitute visually similar Unicode characters, homoglyphs, confusable characters, or "
    "characters from another script such as Cyrillic or Greek letters for any part of an exact value. "
    "For example, if a tool result contains an ASCII file path, you must preserve the exact original "
    "ASCII characters and must not replace Latin letters with look-alike Unicode letters. "
    "If the exact value is missing or ambiguous, do not guess; call another tool to retrieve it first. "
    "Replies must be concise, accurate, reliable, and focused on the core result only."
)

SYSTEM_PROMPT_REVIEW = '''You are a task completion judge.

Return TASK_COMPLETE if:
- the assistant completed the request, or
- the assistant successfully moved the task forward and is now waiting for the user to choose, confirm, or provide the next input.

Return TASK_INCOMPLETE only if:
- a necessary tool call failed,
- the assistant was blocked,
- the assistant did not meaningfully address the request,
- or the task did not reach a valid stopping point.

Do not require the user's ultimate real-world goal to be fully finished.
If the workflow has reached a natural handoff point after successful tool use, return TASK_COMPLETE.

Use only the shown conversation and tool results.

Reply with exactly one of:
TASK_COMPLETE
TASK_INCOMPLETE'''

ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
DEFAULT_CONFIG_PATH = Path.home() / ".function-router" / "config.json"
DEFAULT_ROOT_DIR = Path.home() / ".function-router"


class RecreatingRotatingFileHandler(RotatingFileHandler):
    """Rotating file handler that recreates the target file if deleted.

    If the log file path is removed while the process is still running,
    the next emit reopens a fresh file at the original path. Old deleted-file
    contents are not recovered.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if self.stream is not None and not os.path.exists(self.baseFilename):
            self.acquire()
            try:
                if self.stream is not None:
                    self.stream.close()
                    self.stream = self._open()
            finally:
                self.release()
        super().emit(record)
DEBUG_LOGGER_NAME = "function_router.debug"
REQUEST_LOGGER_NAME = "function_router.request"


@dataclass(slots=True)
class ModelConfig:
    """Connection details for a model endpoint."""

    base_url: str
    model: str
    api_key: str


@dataclass(slots=True)
class AppConfig:
    """Runtime configuration loaded from disk."""

    listen_host: str
    listen_port: int
    routing: ModelConfig
    upstream: ModelConfig
    functions_file: str
    scripts_dir: str
    max_tool_rounds: int
    tool_exec_timeout_s: int
    root_dir: Path
    config_path: Path
    tools_base_dir: str | None = None
    fr_completion_check: bool = True
    fr_completion_check_mode: str = "permissive"
    fr_completion_check_always_true: bool = False
    fr_context_history: bool = True
    fr_context_preserve: bool = False
    debug_logging: bool = False
    routing_timeout_s: float = 10.0

    @property
    def functions_path(self) -> Path:
        """Return the resolved functions file path."""

        path = Path(self.functions_file)
        return path if path.is_absolute() else self.root_dir / path

    @property
    def resolved_scripts_dir(self) -> Path:
        """Return the resolved scripts directory."""

        path = Path(self.scripts_dir)
        return path if path.is_absolute() else self.root_dir / path


@dataclass(slots=True)
class AppStateData:
    """Mutable application state populated during startup."""

    config_path: Path
    config: AppConfig | None = None
    tools: list[dict[str, Any]] | None = None
    logger: logging.Logger | None = None
    http_client: httpx.AsyncClient | None = None
    warmup_ok: bool = False


STATE = AppStateData(config_path=DEFAULT_CONFIG_PATH)

# Ring buffer for recent tool executions (thread-safe via deque).
TOOL_HISTORY: deque[dict[str, Any]] = deque(maxlen=200)

# Qwen internal context buckets keyed by caller-provided session id.
# Each value contains messages[1:] from the last successful tool loop
# (everything after system prompt).
_QWEN_SAVED_CONTEXTS: dict[str, list[dict[str, Any]]] = {}

# Pending Qwen-completed plain-text turns to expose to upstream later,
# keyed by caller-provided session id. Each item is a dict with
# user_text/assistant_text only; tool traces remain in Qwen internal history.
_QWEN_PENDING_UPSTREAM_TURNS: dict[str, list[dict[str, str]]] = {}
_LAST_DEBUG_SESSION_KEY: str | None = None


def _get_pending_upstream_turns(session_key: str) -> list[dict[str, str]]:
    """Return pending plain-text completed turns for one session key."""

    return _QWEN_PENDING_UPSTREAM_TURNS.get(session_key, [])


def _append_pending_upstream_turn(session_key: str, user_text: str, assistant_text: str) -> None:
    """Queue one completed Qwen turn for future upstream visibility."""

    turns = _QWEN_PENDING_UPSTREAM_TURNS.setdefault(session_key, [])
    turns.append({"user_text": user_text, "assistant_text": assistant_text})


def _clear_pending_upstream_turns(session_key: str) -> None:
    """Clear pending upstream-visible turns for one session key."""

    _QWEN_PENDING_UPSTREAM_TURNS[session_key] = []


def _render_pending_upstream_messages(session_key: str) -> list[dict[str, str]]:
    """Render pending completed turns as plain OpenAI-style chat messages."""

    rendered: list[dict[str, str]] = []
    for turn in _get_pending_upstream_turns(session_key):
        rendered.append({"role": "user", "content": turn["user_text"]})
        rendered.append({"role": "assistant", "content": turn["assistant_text"]})
    return rendered


def _get_saved_context(session_key: str) -> list[dict[str, Any]]:
    """Return saved Qwen context for one session key."""

    return _QWEN_SAVED_CONTEXTS.get(session_key, [])


def _set_saved_context(session_key: str, messages: list[dict[str, Any]]) -> None:
    """Store saved Qwen context for one session key."""

    _QWEN_SAVED_CONTEXTS[session_key] = list(messages)


def _clear_saved_context(session_key: str) -> None:
    """Clear saved Qwen context for one session key."""

    _QWEN_SAVED_CONTEXTS.pop(session_key, None)


def derive_session_key(
    original_request: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> str:
    """Return a stable session key from request headers/body if present."""

    if headers:
        header_value = headers.get("x-openclaw-session-key")
        if isinstance(header_value, str):
            header_value = header_value.strip()
            if header_value:
                return header_value

        header_value = headers.get("x-openclaw-session-id")
        if isinstance(header_value, str):
            header_value = header_value.strip()
            if header_value:
                return header_value

    direct_key_candidates = (
        "sessionKey",
        "session_key",
        "sessionId",
        "session_id",
        "conversationId",
        "conversation_id",
        "chatId",
        "chat_id",
    )
    nested_key_candidates = ("metadata", "extra_body")

    for key in direct_key_candidates:
        value = original_request.get(key)
        if value not in (None, ""):
            return str(value)

    for container_key in nested_key_candidates:
        container = original_request.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in direct_key_candidates:
            value = container.get(key)
            if value not in (None, ""):
                return str(value)

    return "default"


def substitute_env_vars(value: Any) -> Any:
    """Recursively substitute ``${VAR_NAME}`` placeholders from the environment."""

    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.environ.get(match.group(1), ""), value)
    if isinstance(value, list):
        return [substitute_env_vars(item) for item in value]
    if isinstance(value, dict):
        return {key: substitute_env_vars(item) for key, item in value.items()}
    return value


def setup_logging(root_dir: Path, debug_logging: bool = False) -> logging.Logger:
    """Configure rotating file and stderr logging."""
    global _LAST_DEBUG_SESSION_KEY

    logs_dir = root_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    _LAST_DEBUG_SESSION_KEY = None

    logger = logging.getLogger("function_router")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    file_handler = RotatingFileHandler(
        logs_dir / "router.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)

    request_logger = logging.getLogger(REQUEST_LOGGER_NAME)
    request_logger.setLevel(logging.INFO)
    request_logger.handlers.clear()
    request_logger.propagate = False
    request_logger.addHandler(file_handler)
    request_logger.addHandler(stderr_handler)

    debug_logger = logging.getLogger(DEBUG_LOGGER_NAME)
    debug_logger.setLevel(logging.DEBUG)
    debug_logger.handlers.clear()
    debug_logger.propagate = False
    if debug_logging:
        debug_handler = RecreatingRotatingFileHandler(
            logs_dir / "router.debug.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        debug_handler.setFormatter(logging.Formatter(fmt="%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        debug_logger.addHandler(debug_handler)

    return logger


def load_config(config_path: Path) -> AppConfig:
    """Load and validate configuration from JSON."""

    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"config file not found: {config_path}") from exc
    except OSError as exc:
        raise RuntimeError(f"failed to read config file: {config_path}") from exc

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid config JSON in {config_path}: {exc}") from exc

    data = substitute_env_vars(raw_data)
    root_dir = config_path.expanduser().resolve().parent

    try:
        routing_data = data.get("routing", data.get("qwen"))
        if routing_data is None:
            raise KeyError("routing")
        routing = ModelConfig(**routing_data)
        upstream = ModelConfig(**data["upstream"])
        completion_cfg = data.get("fr_completion_check", {})
        completion_mode = str(completion_cfg.get("mode", "permissive"))
        if completion_mode not in {"permissive", "strict"}:
            raise RuntimeError(
                f"invalid fr_completion_check.mode in {config_path}: {completion_mode}"
            )
        return AppConfig(
            listen_host=data["listen_host"],
            listen_port=int(data["listen_port"]),
            routing=routing,
            upstream=upstream,
            functions_file=data["functions_file"],
            scripts_dir=data["scripts_dir"],
            max_tool_rounds=int(data["max_tool_rounds"]),
            tool_exec_timeout_s=int(data["tool_exec_timeout_s"]),
            root_dir=root_dir,
            config_path=config_path,
            tools_base_dir=data.get("tools_base_dir"),
            fr_completion_check=bool(
                data.get("fr_completion_check", {}).get("enabled", True)
                or data.get("qwen_completion_check", {}).get("enabled", False)
            ),
            fr_completion_check_mode=completion_mode,
            fr_completion_check_always_true=bool(
                data.get("fr_completion_check", {}).get("always_true", False)
            ),
            fr_context_history=bool(
                data.get("fr_context_history", {}).get("enabled", True)
                or data.get("qwen_context_history", {}).get("enabled", False)
            ),
            fr_context_preserve=bool(
                data.get("fr_context_preserve", {}).get("enabled", False)
                or data.get("qwen_context_preserve", {}).get("enabled", False)
            ),
            debug_logging=bool(
                data.get("debug_logging", {}).get("enabled", False)
            ),
            routing_timeout_s=float(data.get("routing_timeout_s", 10.0)),
        )
    except KeyError as exc:
        raise RuntimeError(f"missing config key: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid config structure in {config_path}: {exc}") from exc


def load_tools(functions_path: Path) -> list[dict[str, Any]]:
    """Load JSONL functions and convert them to OpenAI tools format."""

    if not functions_path.exists():
        raise RuntimeError(f"functions file not found: {functions_path}")

    tools: list[dict[str, Any]] = []
    try:
        with functions_path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    function_obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        f"failed parsing {functions_path}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(function_obj, dict):
                    raise RuntimeError(
                        f"invalid function object at {functions_path}:{line_number}"
                    )
                tools.append({"type": "function", "function": function_obj})
    except OSError as exc:
        raise RuntimeError(f"failed reading functions file: {functions_path}") from exc

    seen_names = {
        tool.get("function", {}).get("name")
        for tool in tools
        if isinstance(tool.get("function"), dict)
    }
    for builtin_tool in get_builtin_tools():
        builtin_name = builtin_tool["function"].get("name")
        if builtin_name in seen_names:
            continue
        tools.append(builtin_tool)
        seen_names.add(builtin_name)

    return tools


def now_iso() -> str:
    """Return a UTC timestamp string for request logs."""

    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, max_len: int = 1024) -> str:
    """Return text capped to max_len with an explicit truncation marker."""

    if not isinstance(text, str):
        text = str(text)
    if len(text) > max_len:
        return text[:max_len] + "...[truncated]"
    return text


def _debug_log(event: str, **fields: Any) -> None:
    """Deprecated metadata logger kept as a no-op for transcript-only debug logs."""

    return


def _append_debug_entry(lines: list[str], prefix: str, label: str, content: Any) -> None:
    text = "" if content is None else str(content)
    text_lines = text.splitlines() or [""]
    lines.append(f"{prefix}{label}: {text_lines[0]}")
    for continuation in text_lines[1:]:
        lines.append(f"{prefix}  {continuation}")


def _debug_log_messages(
    label: str,
    messages: list[dict[str, Any]],
    *,
    offset: int = 0,
) -> None:
    """Write current-turn debug logs for non-upstream routing."""

    if not (STATE.config and STATE.config.debug_logging):
        return

    subset = messages[offset:]
    if not subset:
        return

    logger = logging.getLogger(DEBUG_LOGGER_NAME)
    lines: list[str] = []

    for msg in subset:
        role = (msg.get("role") or "unknown").upper()
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls")

        if role == "USER":
            lines.append(f"USER: {content}")
        elif role == "ASSISTANT":
            if tool_calls:
                for tool_call in tool_calls:
                    function_meta = tool_call.get("function", {})
                    name = function_meta.get("name", "?")
                    arguments = function_meta.get("arguments", "")
                    lines.append(f"TOOL: {name}({arguments})")
            elif content:
                lines.append(f"ASSISTANT: {content}")
        elif role == "TOOL":
            name = msg.get("name") or msg.get("tool_call_id") or "?"
            lines.append(f"TOOL RESULT [{name}]: {content}")

    if lines:
        logger.debug("\n".join(lines))


def _debug_message_content(msg: dict[str, Any]) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                value = item.get("text")
                if isinstance(value, str):
                    text_parts.append(value)
        text = "".join(text_parts)
    else:
        text = ""

    if (msg.get("role") or "").lower() == "user":
        return _strip_openclaw_metadata(text)
    return text


def _debug_log_upstream_context(
    pending_messages: list[dict[str, Any]],
    current_user_message: dict[str, Any] | None,
    assistant_content: str,
    *,
    pending_before: int = 0,
    pending_injected: int = 0,
    pending_after: int | None = None,
) -> None:
    """Write only FR pending context plus the current user and upstream response."""

    if not (STATE.config and STATE.config.debug_logging):
        return

    logger = logging.getLogger(DEBUG_LOGGER_NAME)
    lines: list[str] = ["*** START UPSTREAM ***"]
    lines.append(f"\tPENDING_UPSTREAM_TURNS before: {pending_before}")
    lines.append(f"\tPENDING_UPSTREAM_TURNS injected: {pending_injected}")
    if pending_after is not None:
        lines.append(f"\tPENDING_UPSTREAM_TURNS after_clear: {pending_after}")

    user_index = 0
    assistant_index = 0
    for msg in pending_messages:
        role = (msg.get("role") or "unknown").upper()
        content = _debug_message_content(msg)
        if role == "USER":
            user_index += 1
            lines.append(f"\tUSER{user_index}: {content}")
        elif role == "ASSISTANT" and content:
            assistant_index += 1
            lines.append(f"\tASSISTANT{assistant_index}: {content}")

    if current_user_message is not None:
        user_index += 1
        lines.append(f"\tUSER{user_index}: {_debug_message_content(current_user_message)}")

    lines.append(f"\tASSISTANT last: {assistant_content}")
    lines.append("*** FINISHED UPSTREAM ***")
    logger.debug("\n".join(lines))


def _extract_upstream_assistant_content(response_bytes: bytes, content_type: str) -> str:
    text = response_bytes.decode("utf-8", errors="replace")
    content_parts: list[str] = []

    if "text/event-stream" in content_type.lower():
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data_text = line[5:].strip()
            if not data_text or data_text == "[DONE]":
                continue
            try:
                data = json.loads(data_text)
            except json.JSONDecodeError:
                continue
            for choice in data.get("choices") or []:
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                content = delta.get("content") or message.get("content")
                if isinstance(content, str):
                    content_parts.append(content)
        return "".join(content_parts)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    for choice in data.get("choices") or []:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            content_parts.append(content)
    return "".join(content_parts)


def _has_visible_assistant_reply(content: str) -> bool:
    visible = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)
    return bool(visible.strip())


def _debug_log_session(session_key: str) -> None:
    """Write a transcript section header when the active session changes."""
    global _LAST_DEBUG_SESSION_KEY

    if not (STATE.config and STATE.config.debug_logging):
        return

    logger = logging.getLogger(DEBUG_LOGGER_NAME)
    file_empty = True
    for handler in logger.handlers:
        base_filename = getattr(handler, "baseFilename", None)
        if base_filename and os.path.exists(base_filename):
            file_empty = os.path.getsize(base_filename) == 0
            break

    if session_key == _LAST_DEBUG_SESSION_KEY and not file_empty:
        return

    if not file_empty:
        logger.debug("")
    logger.debug("===== SESSION_KEY ======")
    logger.debug(session_key)
    _LAST_DEBUG_SESSION_KEY = session_key

_MEMORIES_RE = re.compile(r"<relevant-memories>.*?</relevant-memories>", re.DOTALL)
_INGEST_REPLY_ASSIST_RE = re.compile(
    r"<ingest-reply-assist\b[^>]*>.*?</ingest-reply-assist>", re.DOTALL | re.IGNORECASE
)
_SENDER_RE = re.compile(
    r"Sender \(untrusted metadata\):\s*```json\s*\{.*?\}\s*```", re.DOTALL
)
_CONVERSATION_INFO_RE = re.compile(
    r"Conversation info \(untrusted metadata\):\s*```json\s*\{.*?\}\s*```",
    re.DOTALL,
)
_TIMESTAMP_RE = re.compile(r"^\[.*?\]\s*", re.MULTILINE)
_TRANSCRIPT_SPEAKER_PREFIX_RE = re.compile(
    r"^\s*(?:System|User|Assistant)\s*:\s*\[[^\]]+\]\s*.*?\b(?:message|said|says)\b(?:\s+from\s+session\s+[^:]+)?\s*:\s*",
    re.IGNORECASE,
)
_SESSION_ECHO_RE = re.compile(
    r"(?:^|\s+)(?:session\s+)?[A-Za-z0-9_-]{6,}\s*:\s*"
)
_BRACKET_WRAPPER_RE = re.compile(r"\[[^\[\]]*\]|\{[^{}]*\}|<[^<>]*>")
_SINGLE_SESSION_ECHO_RE = re.compile(
    r"^(?:session\s+)?([A-Za-z0-9_-]{6,})\s*:\s*(.+)$",
    re.DOTALL,
)
_DUPLICATE_SESSION_ECHO_RE = re.compile(
    r"^([A-Za-z0-9_-]{6,})\s*:\s*(.+?)\s+\1\s*:\s*\2$",
    re.DOTALL,
)
_WRAPPER_KEYWORDS = (
    "Conversation info (untrusted metadata)",
    "Queued messages while agent was busy",
    "Xiaomai message from session",
)
_LAST_SESSION_ECHO_RE = re.compile(
    r"(?:^|\s)(?:session\s+)?([A-Za-z0-9_-]{6,})\s*:\s*([^\n]+?)\s*$",
    re.DOTALL,
)
_WORKSPACE_BOOTSTRAP_RE = re.compile(
    r"\n*Some workspace bootstrap files were truncated before injection\..*$",
    re.DOTALL,
)


def _extract_last_session_echo_for_wrappers(text: str) -> str | None:
    """For known wrappers, extract the trailing `session_id: message` payload."""

    if not any(keyword in text for keyword in _WRAPPER_KEYWORDS):
        return None
    match = _LAST_SESSION_ECHO_RE.search(text)
    if not match:
        return None
    return match.group(2).strip()


def _drop_bracket_wrappers(text: str) -> str:
    """Remove simple bracketed wrappers like [x], {x}, <x>."""

    previous = None
    while text != previous:
        previous = text
        text = _BRACKET_WRAPPER_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_transcript_message(text: str) -> str:
    """Extract the raw spoken message from transcript-style wrappers."""

    transcript_match = _TRANSCRIPT_SPEAKER_PREFIX_RE.match(text)
    if transcript_match:
        text = text[transcript_match.end() :].strip()
        if not text:
            return text

    duplicate_match = _DUPLICATE_SESSION_ECHO_RE.match(text)
    if duplicate_match:
        return duplicate_match.group(2).strip()

    single_match = _SINGLE_SESSION_ECHO_RE.match(text)
    if single_match:
        return single_match.group(2).strip()

    parts = _SESSION_ECHO_RE.split(text)
    normalized_parts = [part.strip() for part in parts if part.strip()]
    if len(normalized_parts) >= 2 and len(set(normalized_parts)) == 1:
        return normalized_parts[0]

    return text


def _strip_openclaw_metadata(text: str) -> str:
    """Strip OpenClaw-injected metadata, returning only the raw user input."""

    wrapped_text = _extract_last_session_echo_for_wrappers(text)
    if wrapped_text is not None:
        text = wrapped_text

    text = _MEMORIES_RE.sub("", text)
    text = _INGEST_REPLY_ASSIST_RE.sub(" ", text)
    text = _SENDER_RE.sub("", text)
    text = _CONVERSATION_INFO_RE.sub("", text)
    text = _TIMESTAMP_RE.sub("", text)
    text = _WORKSPACE_BOOTSTRAP_RE.sub("", text)
    text = _drop_bracket_wrappers(text)
    text = re.sub(r"^\s*:\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _extract_transcript_message(text)




def extract_user_text(messages: list[dict[str, Any]]) -> str | None:
    """Extract the latest user message text from OpenAI chat messages."""

    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return _strip_openclaw_metadata(content)
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        text_parts.append(text_value)
            return _strip_openclaw_metadata("".join(text_parts))
        return None
    return None


async def build_http_client() -> httpx.AsyncClient:
    """Create a shared HTTP client."""

    return httpx.AsyncClient(follow_redirects=True)


async def qwen_health_check() -> bool:
    """Check whether the local Qwen endpoint is reachable."""

    if STATE.http_client is None or STATE.config is None:
        return False

    url = f"{STATE.config.routing.base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {STATE.config.routing.api_key}"}
    try:
        response = await STATE.http_client.get(url, headers=headers, timeout=5.0)
        return response.status_code < 500
    except httpx.HTTPError:
        return False


async def call_qwen(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Send a non-streaming chat completion request to the local Qwen endpoint.

    Retries once on timeout with a small random jitter to ride out brief
    routing-model latency spikes (e.g. KV cache warmup). After the retry is
    exhausted the timeout propagates so the caller can fall back to upstream.
    """

    if STATE.http_client is None or STATE.config is None or STATE.tools is None:
        raise RuntimeError("application state is not initialized")

    payload = {
        "model": STATE.config.routing.model,
        "messages": messages,
        "tools": STATE.tools,
        "stream": False,
        "temperature": 0.0,
        "repetition_penalty": 1.2,
        "frequency_penalty": 0.2,
        "parallel_tool_calls": False,
        "enable_thinking": False,
    }
    headers = {
        "Authorization": f"Bearer {STATE.config.routing.api_key}",
        "Content-Type": "application/json",
    }
    url = f"{STATE.config.routing.base_url.rstrip('/')}/chat/completions"
    timeout_s = STATE.config.routing_timeout_s

    try:
        response = await STATE.http_client.post(
            url, json=payload, headers=headers, timeout=timeout_s,
        )
    except httpx.TimeoutException as exc:
        if STATE.logger is not None:
            STATE.logger.warning("routing model timeout (%.1fs), retrying once", timeout_s)
        await asyncio.sleep(random.uniform(0.1, 0.5))
        try:
            response = await STATE.http_client.post(
                url, json=payload, headers=headers, timeout=timeout_s,
            )
        except httpx.TimeoutException as retry_exc:
            if STATE.logger is not None:
                STATE.logger.warning("routing model timeout on retry, giving up")
            raise retry_exc from exc

    response.raise_for_status()
    return response.json()


async def warmup_qwen() -> bool:
    """Warm the Qwen KV cache with a deterministic one-token request."""

    if STATE.http_client is None or STATE.config is None or STATE.tools is None:
        return False

    headers = {
        "Authorization": f"Bearer {STATE.config.routing.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": STATE.config.routing.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "hello"},
        ],
        "tools": STATE.tools,
        "stream": False,
        "max_tokens": 1,
        "temperature": 0.0,
        "repetition_penalty": 1.2,
        "frequency_penalty": 0.2,
        "parallel_tool_calls": False,
        "enable_thinking": False,
    }
    try:
        response = await STATE.http_client.post(
            f"{STATE.config.routing.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=STATE.config.routing_timeout_s,
        )
        response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        if STATE.logger is not None:
            STATE.logger.warning("qwen warmup failed: %s", exc)
        return False


def _validate_function_name(name: str) -> bool:
    """Validate function_name contains only safe characters (letters, digits, underscores)."""
    return bool(re.match(r"^[a-zA-Z0-9_]+$", name))


async def execute_tool(function_name: str, arguments_json: str) -> dict[str, Any]:
    """Execute a shell script for a tool call and parse its JSON stdout."""

    if STATE.config is None:
        raise RuntimeError("application config not initialized")

    if not _validate_function_name(function_name):
        return {"error": f"invalid function name: {function_name}"}

    if is_builtin_tool(function_name):
        return await asyncio.to_thread(
            execute_builtin_tool,
            function_name,
            arguments_json,
            STATE.config.tool_exec_timeout_s,
        )

    script_path = (STATE.config.resolved_scripts_dir / f"{function_name}.sh").resolve()
    # Ensure script is within the expected directory (prevent directory traversal)
    if not str(script_path).startswith(str(STATE.config.resolved_scripts_dir.resolve())):
        return {"error": f"script path outside scripts directory: {function_name}"}

    if not script_path.exists():
        return {"error": f"script not found: {function_name}.sh"}

    # Build env with FR_TOOLS_BASE_DIR if configured
    env = dict(os.environ)
    if STATE.config.tools_base_dir:
        env["FR_TOOLS_BASE_DIR"] = STATE.config.tools_base_dir

    process = await asyncio.create_subprocess_exec(
        "bash",
        str(script_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    stdin_bytes = arguments_json.encode("utf-8")
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(stdin_bytes),
            timeout=STATE.config.tool_exec_timeout_s,
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return {"error": "execution timeout"}

    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    stdout_text = stdout.decode("utf-8", errors="replace").strip()

    parsed_output: Any | None = None
    if stdout_text:
        try:
            parsed_output = json.loads(stdout_text)
        except json.JSONDecodeError:
            parsed_output = None

    if process.returncode != 0:
        logger = logging.getLogger("function_router")
        logger.warning(
            "tool %s failed (rc=%s) stdout=%r stderr=%r",
            function_name, process.returncode, stdout_text[:500], stderr_text[:500],
        )
        if isinstance(parsed_output, dict):
            return parsed_output
        return {
            "error": stderr_text or "script execution failed",
            "returncode": process.returncode,
            **({"stdout": stdout_text} if stdout_text else {}),
        }

    if not stdout_text:
        return {}

    if parsed_output is None:
        return {"error": "invalid JSON output", "stdout": stdout_text}

    if isinstance(parsed_output, dict):
        return parsed_output
    return {"result": parsed_output}


@dataclass(slots=True)
class ToolLoopResult:
    """Result from the Qwen tool selection and execution loop."""

    used_any_tool: bool
    last_function_name: str | None
    tool_rounds: int
    # Tool context messages to inject into upstream request (excludes system prompt
    # and the final assistant text reply, keeps: user, assistant+tool_calls, tool results)
    tool_context: list[dict[str, Any]]
    # Whether the loop ended because max rounds were exhausted (still had tool_calls)
    max_rounds_exhausted: bool
    # Qwen's text reply after tool execution (normally stripped); preserved for
    # completion-check so it can be returned directly on short-circuit.
    qwen_reply: str | None = None
    # Internal messages list from the tool loop (system + user + rounds);
    # used by completion-check to append the judgment prompt in-context.
    _loop_messages: list[dict[str, Any]] = field(default_factory=list)
    # Per-LLM-call timing records (one entry per call_qwen invocation).
    # Each entry: {kind, round, request_timestamp, response_timestamp, model}
    llm_calls: list[dict[str, Any]] = field(default_factory=list)


async def run_tool_loop(
    user_text: str,
    *,
    history: list[dict[str, Any]] | None = None,
) -> ToolLoopResult:
    """Run the Qwen tool selection and execution loop.

    Returns a ToolLoopResult containing the tool interaction context.
    The final assistant text reply (if any) is stripped — the upstream model
    will generate the user-facing response based on the tool context.

    If *history* is provided (from _QWEN_SAVED_CONTEXT), prior Qwen-internal
    turns are prepended before the current user message.
    """

    if STATE.tools is None:
        raise RuntimeError("tools not loaded")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    current_turn_offset = len(messages) - 1
    last_function_name: str | None = None
    used_any_tool = False
    max_rounds = STATE.config.max_tool_rounds if STATE.config else 0
    routing_model_name = STATE.config.routing.model if STATE.config else ""
    llm_calls: list[dict[str, Any]] = []

    _debug_log_messages("QWEN", messages, offset=current_turn_offset)

    for round_index in range(1, max_rounds + 1):
        llm_req_ts = now_iso()
        response_json = await call_qwen(messages)
        llm_resp_ts = now_iso()
        llm_calls.append({
            "kind": "qwen_tool_loop",
            "round": round_index,
            "model": routing_model_name,
            "request_timestamp": llm_req_ts,
            "response_timestamp": llm_resp_ts,
        })
        choices = response_json.get("choices") or []
        if not choices:
            # Qwen returned nothing — treat as no-tool
            return ToolLoopResult(
                used_any_tool=used_any_tool,
                last_function_name=last_function_name,
                tool_rounds=round_index,
                tool_context=[],
                max_rounds_exhausted=False,
                llm_calls=llm_calls,
            )

        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        content = message.get("content")
        if tool_calls or used_any_tool:
            _debug_log_messages("QWEN", [message])

        assistant_message: dict[str, Any] = {"role": "assistant"}
        if content is not None:
            assistant_message["content"] = content
        else:
            assistant_message["content"] = ""
        if tool_calls:
            tool_calls_with_ts = []
            for tool_call in tool_calls:
                tool_call_copy = dict(tool_call)
                tool_call_copy["timestamp"] = now_iso()
                tool_call_copy["llm_request_timestamp"] = llm_req_ts
                tool_call_copy["llm_response_timestamp"] = llm_resp_ts
                tool_calls_with_ts.append(tool_call_copy)
            assistant_message["tool_calls"] = tool_calls_with_ts
        messages.append(assistant_message)

        if not tool_calls:
            # Qwen finished with a text reply. If we used tools, strip this
            # final assistant reply and return the tool context for upstream.
            # If no tools were used, return empty context (pure non-function query).
            if used_any_tool:
                # Context = everything after system prompt; explicitly strip the
                # trailing assistant text-only message (the one we just appended).
                tool_context = messages[1:]  # skip system[0]
                qwen_reply: str | None = None
                if (
                    tool_context
                    and tool_context[-1].get("role") == "assistant"
                    and not tool_context[-1].get("tool_calls")
                ):
                    qwen_reply = tool_context[-1].get("content") or None
                    tool_context = tool_context[:-1]
                return ToolLoopResult(
                    used_any_tool=True,
                    last_function_name=last_function_name,
                    tool_rounds=round_index,
                    tool_context=tool_context,
                    max_rounds_exhausted=False,
                    qwen_reply=qwen_reply,
                    _loop_messages=messages,
                    llm_calls=llm_calls,
                )
            return ToolLoopResult(
                used_any_tool=False,
                last_function_name=last_function_name,
                tool_rounds=round_index,
                tool_context=[],
                max_rounds_exhausted=False,
                qwen_reply=content or None,
                _loop_messages=messages,
                llm_calls=llm_calls,
            )

        used_any_tool = True
        for tool_call in tool_calls:
            function_meta = tool_call.get("function") or {}
            function_name = function_meta.get("name", "")
            arguments_json = function_meta.get("arguments") or "{}"
            last_function_name = function_name or last_function_name
            tool_result = await execute_tool(function_name, arguments_json)
            tool_result_ts = now_iso()
            _debug_log_messages(
                "QWEN",
                [{
                    "role": "tool",
                    "name": function_name,
                    "tool_call_id": tool_call.get("id") or f"call_{function_name}_{round_index}",
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }],
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id") or f"call_{function_name}_{round_index}",
                    "name": function_name,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                    "timestamp": tool_result_ts,
                }
            )

    # Max rounds exhausted — return full context (everything after system prompt)
    # including the last assistant message (which may have tool_calls)
    tool_context = messages[1:]  # skip system[0]
    return ToolLoopResult(
        used_any_tool=used_any_tool,
        last_function_name=last_function_name,
        tool_rounds=max_rounds,
        tool_context=tool_context,
        max_rounds_exhausted=True,
        llm_calls=llm_calls,
    )

#COMPLETION_CHECK_PROMPT = (
#    "根据上面的对话，用户的请求是否已经被完全满足？只根据以下标准判断：\n"
#    "- 只要工具调用成功，且当前流程已经推进到等待用户挑选、确认或补充信息的阶段，输出 TASK_COMPLETE\n"
#    "- 只有工具调用失败、报错、或流程根本没有推进，输出 TASK_INCOMPLETE，不要根据‘是否已经最终下单’来判断。”\n"
#    "只输出上述两个标记之一，不要输出任何其他内容。"
#)

# COMPLETION_CHECK_PROMPT = (
#     "根据上面的对话，用户的请求是否已经被完全满足？\n"
#     "- 如果已完成，仅回复: TASK_COMPLETE\n"
#     "- 如果需要用户输入更多信息，或者希望用户进行挑选和确认，仅回复: TASK_COMPLETE\n"
#     "- 如果工具调用失败或不满足上述两个情况，仅回复: TASK_INCOMPLETE\n"
#     "只输出上述两个标记之一，不要输出任何其他内容。"
# )

COMPLETION_CHECK_PROMPT_PERMISSIVE = (
    "根据上面的对话，用户的请求是否已经被完全满足？只根据以下标准判断：\n"
    "- 只要工具调用成功，且当前流程已经推进到等待用户挑选、确认或补充信息的阶段，输出 TASK_COMPLETE\n"
    "- 只有工具调用失败、报错、或流程根本没有推进，输出 TASK_INCOMPLETE，不要根据‘是否已经最终下单’来判断。\n"
    "只输出上述两个标记之一，不要输出任何其他内容。"
)

COMPLETION_CHECK_PROMPT_STRICT = (
    "根据上面的对话，用户的请求是否已经被完全满足？\n"
    "- 如果已完成，仅回复: TASK_COMPLETE\n"
    "- 如果未完成（工具失败、信息不足、用户还需要更多操作等），仅回复: TASK_INCOMPLETE\n"
    "只输出上述两个标记之一，不要输出任何其他内容。"
)


def get_completion_check_prompt(mode: str) -> str:
    """Return the completion-check prompt for the configured mode."""

    if mode == "strict":
        return COMPLETION_CHECK_PROMPT_STRICT
    return COMPLETION_CHECK_PROMPT_PERMISSIVE



async def call_qwen_completion_check(
    messages: list[dict[str, Any]],
    out_llm_calls: list[dict[str, Any]] | None = None,
) -> bool:
    """Ask Qwen whether the user's task is complete.

    Appends a user message to the existing tool-loop *messages* (which already
    contain system + user + assistant+tool_calls + tool_results + assistant reply)
    and asks Qwen to judge.  This round does **not** send tools so Qwen cannot
    issue new tool calls.

    Returns True if Qwen judges the task complete, False otherwise (including
    on any error).  The appended judgment messages are **not** kept — callers
    should treat *messages* as consumed.
    """

    if STATE.http_client is None or STATE.config is None:
        return False

    completion_prompt = get_completion_check_prompt(STATE.config.fr_completion_check_mode)

    # Build a new list so callers can still use the original (e.g. context buffer).
    check_messages = [*messages, {"role": "user", "content": completion_prompt}]
    for i in range(len(check_messages)):
        if check_messages[i]["role"].lower() == "system":
            check_messages[i]["content"] = SYSTEM_PROMPT_REVIEW
            break

    payload = {
        "model": STATE.config.routing.model,
        "messages": check_messages,
        # No tools — prevent Qwen from issuing new tool calls in this round.
        "stream": False,
        "max_tokens": 128,
        "temperature": 0.0,
        "repetition_penalty": 1.2,
        "frequency_penalty": 0.2,
        "enable_thinking": False,
    }
    headers = {
        "Authorization": f"Bearer {STATE.config.routing.api_key}",
        "Content-Type": "application/json",
    }
    llm_req_ts = now_iso()
    try:
        response = await STATE.http_client.post(
            f"{STATE.config.routing.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=5.0,
        )
        llm_resp_ts = now_iso()
        if out_llm_calls is not None:
            out_llm_calls.append({
                "kind": "qwen_completion_check",
                "model": STATE.config.routing.model,
                "request_timestamp": llm_req_ts,
                "response_timestamp": llm_resp_ts,
            })
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            _debug_log_messages("QWEN", [{"role": "user", "content": completion_prompt}])
            _debug_log_messages("QWEN", [{"role": "assistant", "content": ""}])
            return False
        msg_obj = choices[0].get("message") or {}
        text = msg_obj.get("content") or ""
        is_complete = "TASK_COMPLETE" in text.upper().strip()
        _debug_log_messages("QWEN", [{"role": "user", "content": completion_prompt}])
        _debug_log_messages("QWEN", [{"role": "assistant", "content": text}])
        return is_complete
    except (httpx.HTTPError, Exception) as exc:
        if out_llm_calls is not None:
            out_llm_calls.append({
                "kind": "qwen_completion_check",
                "model": STATE.config.routing.model,
                "request_timestamp": llm_req_ts,
                "response_timestamp": now_iso(),
                "error": type(exc).__name__,
            })
        if STATE.logger is not None:
            STATE.logger.warning("qwen completion check failed, treating as incomplete")
        _debug_log_messages("QWEN", [{"role": "user", "content": completion_prompt}])
        _debug_log_messages("QWEN", [{"role": "assistant", "content": f"error:{type(exc).__name__}"}])
        return False



def _fr_only_mode() -> bool:
    return bool(STATE.config and STATE.config.fr_completion_check_always_true)


def _last_assistant_text(messages: list[dict[str, Any]]) -> str:
    """Return the last assistant text from a message list."""

    for message in reversed(messages):
        if message.get("role") == "assistant":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _build_completion_response(
    content: str,
    *,
    stream: bool = False,
) -> JSONResponse | StreamingResponse:
    """Build an OpenAI-compatible chat completion response from plain text.

    Supports both non-streaming (JSONResponse) and streaming (SSE) modes so
    the short-circuit reply is compatible with whatever the caller requested.
    """

    completion_id = f"fr-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if not stream:
        return JSONResponse({
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": "function-router",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    # SSE streaming: one chunk with the full content, then [DONE].
    chunk = json.dumps({
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": "function-router",
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }, ensure_ascii=False)

    async def sse_stream():
        yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        sse_stream(),
        media_type="text/event-stream",
    )


def _build_upstream_request(
    original_request: dict[str, Any],
    *,
    session_key: str,
    tool_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build upstream request body with pending plain-text history injection."""

    proxied_request = json.loads(json.dumps(original_request))

    pending_messages = _render_pending_upstream_messages(session_key)
    if pending_messages:
        msgs = list(proxied_request.get("messages", []))
        split_index = len(msgs)
        if msgs and msgs[-1].get("role") == "user":
            split_index -= 1
        proxied_request["messages"] = [
            *msgs[:split_index],
            *pending_messages,
            *msgs[split_index:],
        ]

    if tool_context:
        msgs = proxied_request.get("messages", [])
        if msgs and msgs[-1].get("role") == "user":
            msgs.pop()
        msgs.extend(tool_context)
        proxied_request["messages"] = msgs

    return proxied_request


async def proxy_upstream(
    original_request: dict[str, Any],
    tool_context: list[dict[str, Any]] | None = None,
    session_key: str | None = None,
    out_timing: dict[str, Any] | None = None,
    on_stream_end: Callable[[], None] | None = None,
) -> StreamingResponse:
    """Proxy the request to the configured upstream model endpoint.

    This is the single place that applies pending Qwen-completed turns to the
    upstream payload so we do not inject the same backlog twice.
    """

    if STATE.http_client is None or STATE.config is None:
        raise RuntimeError("application state not initialized")

    pending_messages: list[dict[str, Any]] = []
    pending_before = 0
    if session_key:
        pending_messages = _render_pending_upstream_messages(session_key)
        pending_before = len(_get_pending_upstream_turns(session_key))
        proxied_request = _build_upstream_request(
            original_request,
            session_key=session_key,
            tool_context=tool_context,
        )
    else:
        proxied_request = json.loads(json.dumps(original_request))
        if tool_context:
            msgs = proxied_request.get("messages", [])
            if msgs and msgs[-1].get("role") == "user":
                msgs.pop()
            msgs.extend(tool_context)
            proxied_request["messages"] = msgs

    proxied_request["model"] = STATE.config.upstream.model

    headers = {
        "Authorization": f"Bearer {STATE.config.upstream.api_key}",
        "Content-Type": "application/json",
    }
    target_url = f"{STATE.config.upstream.base_url.rstrip('/')}/chat/completions"
    upstream_req_ts = now_iso()
    stream_context = STATE.http_client.stream(
        "POST",
        target_url,
        json=proxied_request,
        headers=headers,
        timeout=120.0,
    )
    upstream_response = await stream_context.__aenter__()
    upstream_resp_ts = now_iso()
    if out_timing is not None:
        out_timing.update({
            "kind": "upstream_proxy",
            "model": STATE.config.upstream.model,
            "request_timestamp": upstream_req_ts,
            "response_timestamp": upstream_resp_ts,
        })

    if upstream_response.status_code >= 400:
        body = await upstream_response.aread()
        await stream_context.__aexit__(None, None, None)
        if STATE.logger is not None:
            STATE.logger.warning(
                "upstream returned %d: %s", upstream_response.status_code, body[:500]
            )
        raise HTTPException(
            status_code=upstream_response.status_code,
            detail=f"upstream error: {body.decode('utf-8', errors='replace')[:200]}",
        )

    async def stream_bytes() -> Any:
        first_chunk_seen = False
        response_chunks: list[bytes] = []
        try:
            async for chunk in upstream_response.aiter_bytes():
                response_chunks.append(chunk)
                if not first_chunk_seen:
                    first_chunk_seen = True
                    if out_timing is not None:
                        out_timing["first_chunk_timestamp"] = now_iso()
                yield chunk
        finally:
            if out_timing is not None:
                out_timing["stream_end_timestamp"] = now_iso()
            await stream_context.__aexit__(None, None, None)
            pending_after = None
            if session_key and response_chunks:
                _clear_pending_upstream_turns(session_key)
                pending_after = len(_get_pending_upstream_turns(session_key))
            if response_chunks:
                assistant_content = _extract_upstream_assistant_content(
                    b"".join(response_chunks),
                    response_content_type,
                )
                original_messages = original_request.get("messages")
                current_user_message = None
                if isinstance(original_messages, list):
                    for message in reversed(original_messages):
                        if isinstance(message, dict) and message.get("role") == "user":
                            current_user_message = message
                            break
                if assistant_content and _has_visible_assistant_reply(assistant_content):
                    _debug_log_upstream_context(
                        pending_messages,
                        current_user_message,
                        assistant_content,
                        pending_before=pending_before,
                        pending_injected=len(pending_messages) // 2,
                        pending_after=pending_after,
                    )
            if on_stream_end is not None:
                try:
                    on_stream_end()
                except Exception:
                    if STATE.logger is not None:
                        STATE.logger.exception("proxy_upstream on_stream_end callback failed")

    response_content_type = upstream_response.headers.get("content-type", "text/event-stream")

    return StreamingResponse(
        stream_bytes(),
        status_code=upstream_response.status_code,
        media_type=response_content_type,
        headers={"x-function-router-route": "upstream"},
    )


def log_request(
    *,
    user_message: str | None,
    route: str,
    function_name: str | None,
    tool_rounds: int,
    latency_ms: float,
    status: str,
) -> None:
    """Log a structured per-request record."""

    payload = {
        "timestamp": now_iso(),
        "user_message": (user_message or "")[:100],
        "route": route,
        "function_name": function_name,
        "tool_rounds": tool_rounds,
        "latency_ms": round(latency_ms, 2),
        "status": status,
    }
    logging.getLogger(REQUEST_LOGGER_NAME).info(json.dumps(payload, ensure_ascii=False))



def _record_tool_history(
    user_message: str | None,
    tool_context: list[dict[str, Any]],
    tool_rounds: int,
    session_key: str,
    llm_calls: list[dict[str, Any]] | None = None,
) -> None:
    """Parse tool_context (OpenAI messages) and append to TOOL_HISTORY ring buffer.

    *llm_calls* carries per-LLM-call timing records (FR Qwen rounds, completion
    check, upstream proxy). They are emitted into ordered_events as
    type="llm_call" entries so consumers can render request/response timestamps.
    """

    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    ordered_events: list[dict[str, Any]] = []

    for msg in tool_context:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                entry_ts = tc.get("timestamp") or now_iso()
                entry = {
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", "{}"),
                    "timestamp": entry_ts,
                }
                llm_req_ts = tc.get("llm_request_timestamp")
                llm_resp_ts = tc.get("llm_response_timestamp")
                if llm_req_ts:
                    entry["llm_request_timestamp"] = llm_req_ts
                if llm_resp_ts:
                    entry["llm_response_timestamp"] = llm_resp_ts
                tool_calls.append(entry)
                ordered_events.append({
                    "type": "tool_call",
                    **entry,
                })
        elif role == "tool":
            content_raw = msg.get("content", "")
            is_error = False
            try:
                parsed = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
                is_error = "error" in parsed and "result" not in parsed
            except (json.JSONDecodeError, TypeError):
                pass
            entry_ts = msg.get("timestamp") or now_iso()
            entry = {
                "tool_call_id": msg.get("tool_call_id", ""),
                "name": msg.get("name", ""),
                "content": content_raw,
                "is_error": is_error,
                "timestamp": entry_ts,
            }
            tool_results.append(entry)
            ordered_events.append({
                "type": "tool_result",
                **entry,
            })

    if llm_calls:
        for call in llm_calls:
            ordered_events.append({
                "type": "llm_call",
                **call,
            })

    if not tool_calls and not tool_results and not llm_calls:
        return

    def _ev_sort_key(ev: dict[str, Any]) -> str:
        return ev.get("request_timestamp") or ev.get("timestamp") or ""

    ordered_events.sort(key=_ev_sort_key)

    entry_timestamp = ordered_events[-1].get("timestamp") or ordered_events[-1].get("response_timestamp") or now_iso()
    TOOL_HISTORY.append({
        "timestamp": entry_timestamp,
        "session_key": session_key,
        "user_message": user_message or "",
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "ordered_events": ordered_events,
        "tool_rounds": tool_rounds,
        "llm_calls": list(llm_calls or []),
    })


app = FastAPI(title="Function Router", version="1.0.0")


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize config, tools, logging, and the HTTP client."""

    config = load_config(STATE.config_path)
    logger = setup_logging(config.root_dir, debug_logging=config.debug_logging)
    STATE.logger = logger
    STATE.config = config
    STATE.tools = load_tools(config.functions_path)
    STATE.http_client = await build_http_client()
    STATE.warmup_ok = await warmup_qwen()

    logger.info("config loaded from %s", config.config_path)
    logger.info("loaded %d tools from %s", len(STATE.tools), config.functions_path)
    logger.info("warmup result: %s", "success" if STATE.warmup_ok else "failure")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Close the shared HTTP client."""

    if STATE.http_client is not None:
        await STATE.http_client.aclose()
        STATE.http_client = None


@app.get("/health")
async def health() -> JSONResponse:
    """Return a basic health response."""

    tools_loaded = len(STATE.tools or [])
    return JSONResponse({"status": "ok", "tools_loaded": tools_loaded})


@app.get("/ready")
async def ready() -> JSONResponse:
    """Check readiness based on Qwen reachability."""

    ready_ok = await qwen_health_check()
    return JSONResponse({"status": "ok" if ready_ok else "unavailable"}, status_code=200 if ready_ok else 503)


@app.get("/v1/models")
async def list_models() -> JSONResponse:
    """List available models in OpenAI-compatible format."""

    return JSONResponse({
        "object": "list",
        "data": [
            {
                "id": "function-router",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "function-router"
            }
        ]
    })


@app.get("/v1/tool_history")
async def get_tool_history(since: str | None = None, limit: int = 50) -> JSONResponse:
    """Return recent tool execution history.

    Query params:
        since: ISO timestamp — only return entries after this time.
        limit: max entries to return (default 50, max 200).
    """

    limit = min(max(limit, 1), 200)
    entries = list(TOOL_HISTORY)  # snapshot

    if since:
        entries = [e for e in entries if e["timestamp"] > since]

    # Most recent first, apply limit.
    entries = entries[-limit:]
    entries.reverse()

    return JSONResponse({"entries": entries})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> StreamingResponse:
    """Handle OpenAI-compatible chat completion requests."""

    started_at = time.perf_counter()
    function_name: str | None = None
    tool_rounds = 0
    user_text: str | None = None

    try:
        body_bytes = await request.body()
        original_request = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {exc}") from exc

    messages = original_request.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="request body must include a messages array")

    try:
        user_text = extract_user_text(messages)
        request_headers = dict(request.headers)
        session_key = derive_session_key(original_request, request_headers)
        _debug_log_session(session_key)
        if STATE.logger:
            STATE.logger.info(
                "header x-openclaw-session-key=%s x-openclaw-session-id=%s session_key=%s",
                request_headers.get("x-openclaw-session-key", ""),
                request_headers.get("x-openclaw-session-id", ""),
                session_key,
            )
        _debug_log(
            "request_entry",
            session_key=session_key,
            user_text=user_text or "",
            message_count=len(messages),
            has_stream=original_request.get("stream", False),
        )
        if not user_text:
            if _fr_only_mode():
                return _build_completion_response(
                    _last_assistant_text(messages),
                    stream=original_request.get("stream", False),
                )
            upstream_timing: dict[str, Any] = {}
            _user_text_no_user = user_text

            def _finalize_no_user() -> None:
                if upstream_timing:
                    _record_tool_history(
                        _user_text_no_user,
                        [],
                        0,
                        session_key,
                        llm_calls=[upstream_timing],
                    )

            response = await proxy_upstream(
                original_request,
                session_key=session_key,
                out_timing=upstream_timing,
                on_stream_end=_finalize_no_user,
            )
            log_request(
                user_message=user_text,
                route="upstream",
                function_name=None,
                tool_rounds=0,
                latency_ms=(time.perf_counter() - started_at) * 1000,
                status="forwarded_no_user",
            )
            _debug_log(
                "route_decision",
                session_key=session_key,
                route="upstream",
                status="forwarded_no_user",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            return response

        # Check for HEARTBEAT keyword to bypass Qwen routing
        if ("HEARTBEAT" in user_text) or \
            ("Conversation summary" in user_text) or \
            ("A new session was started" in user_text):
            if _fr_only_mode():
                return _build_completion_response(
                    _last_assistant_text(messages),
                    stream=original_request.get("stream", False),
                )
            upstream_timing: dict[str, Any] = {}
            _user_text_heartbeat = user_text

            def _finalize_heartbeat() -> None:
                if upstream_timing:
                    _record_tool_history(
                        _user_text_heartbeat,
                        [],
                        0,
                        session_key,
                        llm_calls=[upstream_timing],
                    )

            response = await proxy_upstream(
                original_request,
                session_key=session_key,
                out_timing=upstream_timing,
                on_stream_end=_finalize_heartbeat,
            )
            log_request(
                user_message=user_text,
                route="upstream",
                function_name=None,
                tool_rounds=0,
                latency_ms=(time.perf_counter() - started_at) * 1000,
                status="skipped_qwen_heartbeat",
            )
            _debug_log(
                "route_decision",
                session_key=session_key,
                route="upstream",
                status="skipped_qwen_heartbeat",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            return response


        # 检查是否需要调用Qwen：只有最后一条是user消息时才需要
        # 如果最后一条是assistant或tool，说明是豆包自己在处理或工具在返回，
        # 不应该再调用Qwen（否则会用之前的user消息重复调用）
        last_role = messages[-1].get("role") if messages else None
        if last_role and last_role != "user":
            if _fr_only_mode():
                return _build_completion_response(
                    _last_assistant_text(messages),
                    stream=original_request.get("stream", False),
                )
            upstream_timing: dict[str, Any] = {}
            _user_text_continuation = user_text

            def _finalize_continuation() -> None:
                if upstream_timing:
                    _record_tool_history(
                        _user_text_continuation,
                        [],
                        1,
                        session_key,
                        llm_calls=[upstream_timing],
                    )

            response = await proxy_upstream(
                original_request,
                session_key=session_key,
                out_timing=upstream_timing,
                on_stream_end=_finalize_continuation,
            )
            log_request(
                user_message=user_text,
                route="upstream",
                function_name=None,
                tool_rounds=1,
                latency_ms=(time.perf_counter() - started_at) * 1000,
                status="skipped_qwen_continuation",
            )
            _debug_log(
                "route_decision",
                session_key=session_key,
                route="upstream",
                status="skipped_qwen_continuation",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            return response

        ctx_enabled = bool(
            STATE.config and STATE.config.fr_context_history
        )
        ctx_preserve = bool(
            STATE.config and STATE.config.fr_context_preserve
        )
        if STATE.logger:
            STATE.logger.info(
                "ctx_enabled=%s, ctx_preserve=%s, saved_context_len=%d",
                ctx_enabled, ctx_preserve, len(_get_saved_context(session_key)),
            )

        try:
            result = await run_tool_loop(
                user_text,
            history=(list(_get_saved_context(session_key)) or None) if ctx_enabled else None,
            )
            function_name = result.last_function_name
            tool_rounds = result.tool_rounds
        except (httpx.HTTPError, RuntimeError, asyncio.TimeoutError) as exc:
            if not ctx_preserve:
                _clear_saved_context(session_key)
            if STATE.logger is not None:
                STATE.logger.warning("qwen routing failed, falling back upstream: %s", exc)
            if _fr_only_mode():
                log_request(
                    user_message=user_text,
                    route="function",
                    function_name=function_name,
                    tool_rounds=tool_rounds,
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    status=f"qwen_error_always_true:{type(exc).__name__}",
                )
                return _build_completion_response(
                    "",
                    stream=original_request.get("stream", False),
                )
            upstream_timing: dict[str, Any] = {}
            _user_text_fallback = user_text
            _fallback_rounds = tool_rounds

            def _finalize_fallback() -> None:
                if upstream_timing:
                    _record_tool_history(
                        _user_text_fallback,
                        [],
                        _fallback_rounds,
                        session_key,
                        llm_calls=[upstream_timing],
                    )

            response = await proxy_upstream(
                original_request,
                session_key=session_key,
                out_timing=upstream_timing,
                on_stream_end=_finalize_fallback,
            )
            log_request(
                user_message=user_text,
                route="upstream",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=(time.perf_counter() - started_at) * 1000,
                status="fallback_upstream",
            )
            _debug_log(
                "route_decision",
                session_key=session_key,
                route="upstream",
                status="fallback_upstream",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            return response

        if not result.used_any_tool:
            if _fr_only_mode():
                if ctx_enabled and result._loop_messages:
                    _set_saved_context(session_key, result._loop_messages[1:])
                _record_tool_history(
                    user_text,
                    result.tool_context,
                    tool_rounds,
                    session_key,
                    llm_calls=result.llm_calls,
                )
                log_request(
                    user_message=user_text,
                    route="function",
                    function_name=function_name,
                    tool_rounds=tool_rounds,
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    status="qwen_completed_always_true",
                )
                return _build_completion_response(
                    result.qwen_reply or _last_assistant_text(result._loop_messages),
                    stream=original_request.get("stream", False),
                )
            if not ctx_preserve:
                _clear_saved_context(session_key)
            upstream_timing: dict[str, Any] = {}
            _user_text_after_routing = user_text
            _after_routing_rounds = tool_rounds
            _after_routing_tool_context = result.tool_context
            _after_routing_llm_calls = result.llm_calls

            def _finalize_after_routing() -> None:
                if upstream_timing:
                    _after_routing_llm_calls.append(upstream_timing)
                _record_tool_history(
                    _user_text_after_routing,
                    _after_routing_tool_context,
                    _after_routing_rounds,
                    session_key,
                    llm_calls=_after_routing_llm_calls,
                )

            response = await proxy_upstream(
                original_request,
                session_key=session_key,
                out_timing=upstream_timing,
                on_stream_end=_finalize_after_routing,
            )
            log_request(
                user_message=user_text,
                route="upstream",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=(time.perf_counter() - started_at) * 1000,
                status="forwarded_after_routing",
            )
            _debug_log(
                "route_decision",
                session_key=session_key,
                route="upstream",
                status="forwarded_after_routing",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
            )
            return response
        # Tools were used — check if Qwen judges the task complete (short-circuit)
        # or fall through to upstream (Doubao) for the final response.
        if (
            STATE.config
            and STATE.config.fr_completion_check
            and not result.max_rounds_exhausted
            and result.qwen_reply
        ):
            task_complete = _fr_only_mode() or await call_qwen_completion_check(
                result._loop_messages,
                out_llm_calls=result.llm_calls,
            )
            if task_complete:
                if ctx_enabled:
                    _set_saved_context(session_key, result._loop_messages[1:])
                    if STATE.logger:
                        STATE.logger.info(
                            "saved context[%s]: %d messages", session_key, len(_get_saved_context(session_key)),
                        )
                if user_text and result.qwen_reply:
                    _append_pending_upstream_turn(session_key, user_text, result.qwen_reply)
                _record_tool_history(
                    user_text,
                    result.tool_context,
                    tool_rounds,
                    session_key,
                    llm_calls=result.llm_calls,
                )
                log_request(
                    user_message=user_text,
                    route="function",
                    function_name=function_name,
                    tool_rounds=tool_rounds,
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    status="qwen_completed",
                )
                _debug_log(
                    "route_decision",
                    session_key=session_key,
                    route="function",
                    status="qwen_completed",
                    function_name=function_name,
                    tool_rounds=tool_rounds,
                    latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
                )
                return _build_completion_response(
                    result.qwen_reply,
                    stream=original_request.get("stream", False),
                )

        if _fr_only_mode():
            if ctx_enabled and result._loop_messages:
                _set_saved_context(session_key, result._loop_messages[1:])
            if user_text and result.qwen_reply:
                _append_pending_upstream_turn(session_key, user_text, result.qwen_reply)
            _record_tool_history(
                user_text,
                result.tool_context,
                tool_rounds,
                session_key,
                llm_calls=result.llm_calls,
            )
            log_request(
                user_message=user_text,
                route="function",
                function_name=function_name,
                tool_rounds=tool_rounds,
                latency_ms=(time.perf_counter() - started_at) * 1000,
                status="qwen_completed_always_true",
            )
            return _build_completion_response(
                result.qwen_reply or _last_assistant_text(result._loop_messages),
                stream=original_request.get("stream", False),
            )

        # Fall through: forward to upstream without injecting tool context.
        # This prevents upstream models (Doubao) from hallucinating Qwen's local tools.
        # Only clear if not preserving context.
        if not ctx_preserve:
            _clear_saved_context(session_key)
        elif STATE.logger:
            STATE.logger.info("ctx_preserve[%s]: keeping %d messages", session_key, len(_get_saved_context(session_key)))
        if result.max_rounds_exhausted:
            status = "tool_max_rounds_to_upstream"
        else:
            status = "tool_result_to_upstream"
        upstream_timing: dict[str, Any] = {}
        _user_text_final = user_text
        _final_rounds = tool_rounds
        _final_tool_context = result.tool_context
        _final_llm_calls = result.llm_calls

        def _finalize_final() -> None:
            if upstream_timing:
                _final_llm_calls.append(upstream_timing)
            _record_tool_history(
                _user_text_final,
                _final_tool_context,
                _final_rounds,
                session_key,
                llm_calls=_final_llm_calls,
            )

        response = await proxy_upstream(
            original_request,
            tool_context=None,
            session_key=session_key,
            out_timing=upstream_timing,
            on_stream_end=_finalize_final,
        )
        log_request(
            user_message=user_text,
            route="function",
            function_name=function_name,
            tool_rounds=tool_rounds,
            latency_ms=(time.perf_counter() - started_at) * 1000,
            status=status,
        )
        _debug_log(
            "route_decision",
            session_key=session_key,
            route="function",
            status=status,
            function_name=function_name,
            tool_rounds=tool_rounds,
            latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return response
    except httpx.HTTPError as exc:
        if STATE.logger is not None:
            STATE.logger.exception("upstream proxy failure")
        log_request(
            user_message=user_text,
            route="upstream",
            function_name=function_name,
            tool_rounds=tool_rounds,
            latency_ms=(time.perf_counter() - started_at) * 1000,
            status=f"error:{type(exc).__name__}",
        )
        _debug_log(
            "route_decision",
            session_key=session_key,
            route="upstream",
            status=f"error:{type(exc).__name__}",
            function_name=function_name,
            tool_rounds=tool_rounds,
            latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )
        raise HTTPException(status_code=502, detail="upstream request failed") from exc


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Function Router service")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config.json (default: ~/.function-router/config.json)",
    )
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint."""

    args = parse_args()
    STATE.config_path = Path(args.config).expanduser().resolve()
    STATE.config_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        config = load_config(STATE.config_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    setup_logging(config.root_dir, debug_logging=config.debug_logging)

    try:
        load_tools(config.functions_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc

    uvicorn.run(
        app,
        host=config.listen_host,
        port=config.listen_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
