#!/usr/bin/env python3
"""Thin stdin/stdout bridge from MTClaw wrappers to ClawOS tools."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import tool_runner


SAFE_TOOLS = {
    "time_now",
    "calc",
    "text_stats",
    "ls",
    "cat",
    "find_files",
    "grep_text",
    "file_info",
    "code_stats",
    "find_todos",
    "dir_tree",
    "memory_profile_get",
    "memory_preference_get",
    "memory_stats",
    "memory_history",
    "reflection_list",
    "skill_list",
    "tools_list",
    "knowledge_search",
    "meeting_action_items",
    "paper_deep_read",
    "exam_practice_builder",
    "research_pdf",
    "paper_intelligence",
    "coding_workflow",
    "office_productivity",
    "learning_workspace",
}

SAFE_ACTIONS = {
    "research_pdf": {"search", "validate_citations", "compare_matrix"},
    "paper_intelligence": {"structure", "align_claims", "compare", "readiness"},
    "coding_workflow": {"inspect", "plan"},
    "office_productivity": {"inspect"},
    "learning_workspace": {"get", "graph", "assessment"},
}

NO_WRITE_ARGUMENTS = {
    "meeting_action_items": {"output_path"},
    "paper_deep_read": {"output_path"},
    "exam_practice_builder": {"output_path"},
    "research_pdf": {"file_path", "output_path", "output_dir", "steps", "formats"},
    "coding_workflow": {"confirmed", "repair_rounds", "checkpoint", "create_change_request", "commit_message"},
    "office_productivity": {"output_path", "output_dir", "confirmed", "connector", "idempotency_key", "attachments"},
}


def enforce_safe_payload(tool_name: str, payload: dict) -> dict:
    """Enforce action-level read-only policy before invoking a vertical wrapper."""
    guarded = dict(payload or {})
    allowed_actions = SAFE_ACTIONS.get(tool_name)
    if allowed_actions is not None:
        action = str(guarded.get("action") or "").strip()
        if action not in allowed_actions:
            raise PermissionError(f"action not allowed through MTClaw: {tool_name}.{action or '<missing>'}")
    removed = sorted(key for key in NO_WRITE_ARGUMENTS.get(tool_name, set()) if guarded.get(key))
    if removed:
        raise PermissionError(f"write-capable arguments not allowed through MTClaw: {', '.join(removed)}")
    return guarded


def main() -> int:
    if len(sys.argv) != 2:
        print(json.dumps({"error": "tool name required"}))
        return 2
    tool_name = sys.argv[1]
    if tool_name not in SAFE_TOOLS:
        print(json.dumps({"error": f"tool not allowed through MTClaw: {tool_name}"}))
        return 3
    handler = tool_runner.handlers.get(tool_name)
    if not handler:
        print(json.dumps({"error": f"unknown tool: {tool_name}"}))
        return 4
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid JSON: {exc}"}))
        return 5

    try:
        guarded = enforce_safe_payload(tool_name, payload if isinstance(payload, dict) else {})
        guarded = tool_runner.security_check(tool_name, guarded)
    except PermissionError as exc:
        print(json.dumps({"error": str(exc), "status": "denied"}, ensure_ascii=False))
        return 6
    tool_runner.input_data = guarded
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

    text = output.getvalue().strip()
    print(text or json.dumps({"result": "ok"}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
