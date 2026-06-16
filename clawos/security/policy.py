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
        "research_pdf": ("file_path", "output_path"),
        "git_workspace": ("path",),
        "template_instantiate": ("target_path",),
        "shell_exec": ("workdir",),
    }
    WRITE_TOOLS = {
        "file_write", "file_organize", "batch_rename", "project_init",
        "note_save", "meeting_template", "template_instantiate",
    }
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
                return command_result
        return {
            "allowed": True,
            "decision": "confirm" if tool_name in self.WRITE_TOOLS or tool_name == "shell_exec" else "allow",
            "reason": "policy checks passed",
            "normalized_arguments": args,
        }

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
        return {"allowed": True, "decision": "confirm", "reason": "command policy passed"}

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
