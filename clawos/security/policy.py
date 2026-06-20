"""Path sandbox and command policy for local tools."""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from pathlib import Path


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
        "file_write": ("path",),
        "file_organize": ("path",),
        "batch_rename": ("path",),
        "project_init": ("root",),
        "meeting_workflow": ("audio_path", "transcript_path", "output_dir"),
        "research_pdf": ("file_path", "output_path", "output_dir"),
        "office_artifact": ("file_path", "output_path"),
        "git_workspace": ("path",),
        "template_instantiate": ("target_path",),
        "shell_exec": ("workdir",),
    }
    NETWORK_TOOLS = {"web_search", "web_fetch", "weather"}
    EXTERNAL_API_TOOLS = {"web_search", "web_fetch", "weather", "model_provider"}
    WRITE_TOOLS = {
        "file_write", "file_organize", "batch_rename", "project_init",
        "note_save", "meeting_template", "template_instantiate",
        "office_artifact", "git_workspace",
    }
    HIGH_RISK_TOOLS = {"shell_exec", "template_instantiate"}
    ALLOWED_COMMANDS = {
        "python", "python3", "py", "git", "pytest", "npm", "node",
        "uv", "pip", "pip3", "cargo", "go", "java", "javac", "echo",
    }
    GIT_SUBCOMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
    BLOCKED_TOKENS = re.compile(r"(?:[;&|><`]|\r|\n|\$\(|\b(?:rm|del|erase|format|shutdown|reboot)\b)", re.I)

    def __init__(self, allowed_roots=None):
        self.allowed_roots = self._build_roots(allowed_roots)

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
            command_result["risk_level"] = "high"
            command_result["normalized_arguments"] = args
            return command_result
        if tool_name == "web_fetch":
            url_check = self.evaluate_url(args.get("url", ""))
            if not url_check["allowed"]:
                url_check["normalized_arguments"] = args
                url_check["risk_level"] = risk_level
                return url_check
        decision = "allow"
        reason = "policy checks passed"
        if tool_name in self.WRITE_TOOLS or tool_name in self.NETWORK_TOOLS:
            decision = "confirm"
            reason = f"{risk_level} risk tool requires confirmation"
        return {
            "allowed": True,
            "decision": decision,
            "reason": reason,
            "normalized_arguments": args,
            "risk_level": risk_level,
        }

    def risk_level(self, tool_name, arguments=None):
        arguments = arguments or {}
        if tool_name in self.HIGH_RISK_TOOLS:
            return "high"
        if tool_name == "git_workspace":
            action = str(arguments.get("action", "")).lower()
            return "high" if action in {"approve", "rollback"} else "medium"
        if tool_name in self.WRITE_TOOLS:
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
