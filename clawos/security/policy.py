"""Path sandbox and command policy for local tools."""

from __future__ import annotations

import os
import fnmatch
import re
import shlex
import tempfile
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class SecurityGrantStore:
    """Persistent, expiring allow/deny grants used by the Permission Center."""

    VALID_DECISIONS = {"allow", "confirm", "deny"}
    VALID_SCOPES = {"tool", "url_host", "path_prefix", "command"}

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def list(self, include_expired: bool = False) -> list[dict]:
        payload = self._read()
        grants = payload.get("grants", [])
        if include_expired:
            return grants
        return [grant for grant in grants if not self.is_expired(grant)]

    def add(self, grant: dict) -> dict:
        item = self._normalize(grant)
        payload = self._read()
        grants = [existing for existing in payload.get("grants", []) if existing.get("id") != item["id"]]
        grants.append(item)
        self._write({"grants": grants})
        return item

    def revoke(self, grant_id: str) -> bool:
        payload = self._read()
        grants = payload.get("grants", [])
        remaining = [grant for grant in grants if str(grant.get("id")) != str(grant_id)]
        self._write({"grants": remaining})
        return len(remaining) != len(grants)

    def match(self, tool_name: str, arguments: dict, risk_level: str) -> dict | None:
        for grant in self.list(include_expired=False):
            if self._matches(grant, tool_name, arguments or {}, risk_level):
                return grant
        return None

    @staticmethod
    def is_expired(grant: dict) -> bool:
        expires_at = _parse_time(grant.get("expires_at"))
        return bool(expires_at and expires_at <= _utc_now())

    def _normalize(self, grant: dict) -> dict:
        decision = str(grant.get("decision") or "confirm").lower()
        scope_type = str(grant.get("scope_type") or "tool").lower()
        if decision not in self.VALID_DECISIONS:
            raise ValueError(f"invalid decision: {decision}")
        if scope_type not in self.VALID_SCOPES:
            raise ValueError(f"invalid scope_type: {scope_type}")
        expires_at = str(grant.get("expires_at") or "").strip()
        minutes = grant.get("expires_in_minutes")
        if not expires_at and minutes not in (None, ""):
            expires_at = (_utc_now() + timedelta(minutes=max(1, int(minutes)))).isoformat()
        return {
            "id": str(grant.get("id") or uuid.uuid4().hex[:12]),
            "tool": str(grant.get("tool") or "*").strip() or "*",
            "decision": decision,
            "risk_level": str(grant.get("risk_level") or "").lower(),
            "scope_type": scope_type,
            "scope_value": str(grant.get("scope_value") or "").strip(),
            "reason": str(grant.get("reason") or "manual permission grant").strip(),
            "created_by": str(grant.get("created_by") or "system").strip(),
            "created_at": str(grant.get("created_at") or _utc_now().isoformat()),
            "expires_at": expires_at,
        }

    def _matches(self, grant: dict, tool_name: str, arguments: dict, risk_level: str) -> bool:
        tool = str(grant.get("tool") or "*")
        if tool not in {"*", tool_name}:
            return False
        grant_risk = str(grant.get("risk_level") or "")
        if grant_risk and grant_risk != str(risk_level or ""):
            return False
        scope_type = str(grant.get("scope_type") or "tool")
        scope_value = str(grant.get("scope_value") or "").strip()
        if scope_type == "tool":
            return True
        if scope_type == "url_host":
            url = str(arguments.get("url") or "")
            return bool(scope_value and urlparse(url).hostname == scope_value)
        if scope_type == "path_prefix":
            values = [str(v) for v in arguments.values() if isinstance(v, (str, os.PathLike))]
            return any(str(value).lower().startswith(scope_value.lower()) for value in values if scope_value)
        if scope_type == "command":
            command = str(arguments.get("command") or "").strip().lower()
            return bool(scope_value and command.startswith(scope_value.lower()))
        return False

    def _read(self) -> dict:
        if not self.path.exists():
            return {"grants": []}
        try:
            return json.loads(self.path.read_text(encoding="utf-8-sig") or "{}")
        except json.JSONDecodeError:
            return {"grants": []}

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ToolSecurityPolicy:
    """Validate filesystem and shell operations before tool execution."""

    PATH_FIELDS = {
        "ls": ("path",),
        "cat": ("path",),
        "find_files": ("path",),
        "grep_text": ("path",),
        "file_info": ("path",),
        "code_stats": ("path",),
        "find_todos": ("path",),
        "dir_tree": ("path",),
        "text_stats": ("file_path",),
        "meeting_action_items": ("transcript_path", "output_path"),
        "paper_deep_read": ("file_path", "output_path"),
        "exam_practice_builder": ("output_path",),
        "file_write": ("path",),
        "file_organize": ("path",),
        "batch_rename": ("path",),
        "project_init": ("root",),
        "meeting_workflow": ("audio_path", "transcript_path", "output_dir"),
        "research_pdf": ("file_path", "output_path", "output_dir"),
        "coding_workflow": ("repo_path", "checkpoint"),
        "office_productivity": ("file_path", "output_path", "output_dir"),
        "scholarly_download": ("output_dir",),
        "office_artifact": ("file_path", "output_path"),
        "git_workspace": ("path",),
        "competition_delivery_package": ("root", "output_dir"),
        "multi_agent_review_committee": ("root", "output_dir"),
        "template_instantiate": ("target_path",),
        "shell_exec": ("workdir",),
    }
    NETWORK_TOOLS = {"web_search", "web_fetch", "weather", "scholarly_search", "scholarly_download"}
    EXTERNAL_API_TOOLS = {"web_search", "web_fetch", "weather", "model_provider", "scholarly_search", "scholarly_download"}
    WRITE_TOOLS = {
        "file_write", "file_organize", "batch_rename", "project_init",
        "note_save", "meeting_template", "template_instantiate",
        "office_artifact", "git_workspace",
        "meeting_workflow", "coding_workflow", "office_productivity", "autonomous_subagents",
        "competition_delivery_package",
        "multi_agent_review_committee",
        "scholarly_download",
    }
    HIGH_RISK_TOOLS = {"shell_exec", "template_instantiate", "scholarly_download", "coding_workflow", "autonomous_subagents"}
    ALLOWED_COMMANDS = {
        "python", "python3", "py", "git", "pytest", "npm", "node",
        "uv", "pip", "pip3", "cargo", "go", "java", "javac", "echo",
    }
    GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
    BLOCKED_TOKENS = re.compile(r"(?:[;&|><`]|\r|\n|\$\(|\b(?:rm|del|erase|format|shutdown|reboot)\b)", re.I)

    def __init__(self, allowed_roots=None, grant_store: SecurityGrantStore | None = None):
        self.allowed_roots = self._build_roots(allowed_roots)
        self.grant_store = grant_store

    def evaluate(self, tool_name, arguments):
        args = dict(arguments or {})
        risk_level = self.risk_level(tool_name, args)
        normalized = {}
        for field in self.PATH_FIELDS.get(tool_name, ()):
            value = args.get(field)
            if not value:
                continue
            try:
                normalized[field] = str(self.resolve_path(value))
            except ValueError as exc:
                return {
                    "allowed": False,
                    "decision": "deny",
                    "reason": str(exc),
                    "normalized_arguments": args,
                }
        args.update(normalized)
        if tool_name == "shell_exec":
            command_result = self.evaluate_command(args.get("command", ""))
            if not command_result["allowed"]:
                command_result["normalized_arguments"] = args
                command_result["risk_level"] = "high"
                return command_result
            grant_result = self.apply_grant(tool_name, args, "high")
            if grant_result:
                grant_result["normalized_arguments"] = args
                return grant_result
            command_result["risk_level"] = "high"
            command_result["normalized_arguments"] = args
            return command_result
        if tool_name == "web_fetch":
            url_check = self.evaluate_url(args.get("url", ""))
            if not url_check["allowed"]:
                url_check["normalized_arguments"] = args
                url_check["risk_level"] = risk_level
                return url_check
        grant_result = self.apply_grant(tool_name, args, risk_level)
        if grant_result:
            grant_result["normalized_arguments"] = args
            return grant_result
        decision = "allow"
        reason = "policy checks passed"
        writes_optional_output = tool_name in {"meeting_action_items", "paper_deep_read", "exam_practice_builder"} and bool(args.get("output_path"))
        readonly_action = (tool_name == "coding_workflow" and str(args.get("action") or "") in {"inspect", "discover_tests", "plan"}) or (tool_name == "office_productivity" and str(args.get("action") or "") == "inspect")
        if (tool_name in self.WRITE_TOOLS and not readonly_action) or tool_name in self.NETWORK_TOOLS or writes_optional_output:
            decision = "confirm"
            reason = f"{risk_level} risk tool requires confirmation"
        return {
            "allowed": True,
            "decision": decision,
            "reason": reason,
            "normalized_arguments": args,
            "risk_level": risk_level,
        }

    def apply_grant(self, tool_name: str, arguments: dict, risk_level: str) -> dict | None:
        if not self.grant_store:
            return None
        grant = self.grant_store.match(tool_name, arguments, risk_level)
        if not grant:
            return None
        decision = grant.get("decision", "confirm")
        return {
            "allowed": decision != "deny",
            "decision": decision,
            "reason": grant.get("reason") or f"permission grant matched: {grant.get('id')}",
            "risk_level": risk_level,
            "grant_id": grant.get("id"),
        }

    def list_grants(self, include_expired: bool = False):
        return self.grant_store.list(include_expired) if self.grant_store else []

    def add_grant(self, grant: dict):
        if not self.grant_store:
            raise ValueError("grant store is not configured")
        return self.grant_store.add(grant)

    def revoke_grant(self, grant_id: str):
        return self.grant_store.revoke(grant_id) if self.grant_store else False

    def risk_level(self, tool_name, arguments=None):
        arguments = arguments or {}
        if tool_name == "office_productivity" and str(arguments.get("action") or "") in {"email_send", "calendar_publish"}:
            return "high"
        if tool_name == "coding_workflow" and str(arguments.get("action") or "") in {"inspect", "discover_tests", "plan"}:
            return "low"
        if tool_name in self.HIGH_RISK_TOOLS:
            return "high"
        if tool_name == "git_workspace":
            action = str(arguments.get("action", "")).lower()
            return "high" if action in {"approve", "rollback"} else "medium"
        if tool_name in self.WRITE_TOOLS:
            return "medium"
        if tool_name in {"meeting_action_items", "paper_deep_read", "exam_practice_builder"} and arguments.get("output_path"):
            return "medium"
        if tool_name in self.NETWORK_TOOLS or tool_name in self.EXTERNAL_API_TOOLS:
            return "medium"
        return "low"

    def evaluate_url(self, value):
        raw = str(value or "").strip()
        if not raw:
            return {"allowed": False, "decision": "deny", "reason": "url is required"}
        if not re.match(r"^https?://", raw, re.I):
            return {"allowed": False, "decision": "deny", "reason": "only http(s) URLs are allowed"}
        if re.match(r"^https?://(?:localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[0-1])\.)", raw, re.I):
            return {"allowed": False, "decision": "deny", "reason": "private or local network URLs are not allowed"}
        host = (urlparse(raw).hostname or "").lower()
        denied = [
            item.strip().lower()
            for item in os.environ.get("CLAWOS_DENIED_EGRESS_HOSTS", "").split(",")
            if item.strip()
        ]
        allowed = [
            item.strip().lower()
            for item in os.environ.get("CLAWOS_ALLOWED_EGRESS_HOSTS", "").split(",")
            if item.strip()
        ]
        if any(fnmatch.fnmatch(host, pattern) for pattern in denied):
            return {"allowed": False, "decision": "deny", "reason": "network host matched deny policy"}
        if allowed and not any(fnmatch.fnmatch(host, pattern) for pattern in allowed):
            return {"allowed": False, "decision": "deny", "reason": "network host is not allowlisted"}
        return {"allowed": True, "decision": "confirm", "reason": "network URL policy passed"}

    def resolve_path(self, value):
        path = Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve(strict=False)
        for root in self.allowed_roots:
            try:
                path.relative_to(root)
                return path
            except ValueError:
                continue
        raise ValueError(f"path is outside allowed roots: {path}")

    def evaluate_command(self, command):
        command = str(command or "").strip()
        if not command:
            return {"allowed": False, "decision": "deny", "reason": "command is required"}
        if self.BLOCKED_TOKENS.search(command):
            return {"allowed": False, "decision": "deny", "reason": "command contains blocked operators or destructive tokens"}
        try:
            parts = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            return {"allowed": False, "decision": "deny", "reason": "command parsing failed"}
        if not parts:
            return {"allowed": False, "decision": "deny", "reason": "command is required"}
        executable = Path(parts[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        if executable not in self.ALLOWED_COMMANDS:
            return {"allowed": False, "decision": "deny", "reason": f"command is not allowlisted: {executable}"}
        if executable == "git" and len(parts) > 1 and parts[1].lower() not in self.GIT_SUBCOMMANDS:
            return {"allowed": False, "decision": "deny", "reason": f"git subcommand is not allowlisted: {parts[1]}"}
        return {"allowed": True, "decision": "confirm", "reason": "command policy passed", "risk_level": "high"}

    @staticmethod
    def _build_roots(roots):
        if roots is None:
            configured = os.environ.get("CLAWOS_ALLOWED_ROOTS", "")
            roots = [item for item in configured.split(os.pathsep) if item]
            if not roots:
                home = Path.home()
                roots = [
                    Path(__file__).resolve().parents[2],
                    home / "Desktop",
                    home / "Documents",
                    Path(tempfile.gettempdir()),
                ]
        return tuple(Path(root).expanduser().resolve(strict=False) for root in roots)
