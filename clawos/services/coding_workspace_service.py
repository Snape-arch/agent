"""Approval-gated Git workspace isolation and delivery operations."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


BRANCH_RE = re.compile(r"^codex/[a-z0-9][a-z0-9._/-]{0,80}$")


class CodingWorkspaceService:
    """Create isolated worktrees and hand reviewed changes to Git.

    No remote operation is included.  Push and pull-request creation remain
    separate user-authorized actions.
    """

    def create(
        self,
        repo_path: str | Path,
        workspace_path: str | Path,
        branch: str,
        *,
        base_ref: str = "HEAD",
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to create a worktree")
        repo = self._repo(repo_path)
        target = Path(workspace_path).expanduser().resolve()
        if target.exists():
            raise ValueError("workspace_path already exists")
        if not BRANCH_RE.fullmatch(str(branch or "")):
            raise ValueError("branch must use the codex/ prefix and safe characters")
        target.parent.mkdir(parents=True, exist_ok=True)
        self._git(repo, "worktree", "add", "-b", branch, str(target), base_ref)
        return {
            "schema": "clawos.coding-workspace.v1",
            "repo": str(repo),
            "workspace": str(target),
            "branch": branch,
            "base_ref": base_ref,
            "isolated": True,
            "remote_mutation": False,
        }

    def status(self, repo_path: str | Path) -> dict[str, Any]:
        repo = self._repo(repo_path)
        rows = []
        current: dict[str, Any] = {}
        for line in self._git(repo, "worktree", "list", "--porcelain").splitlines():
            if not line:
                if current:
                    rows.append(current)
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value or True
        if current:
            rows.append(current)
        return {"repo": str(repo), "worktrees": rows}

    def commit(
        self,
        workspace_path: str | Path,
        paths: list[str],
        message: str,
        *,
        confirmed: bool = False,
        author: str = "coding-agent",
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to create a commit")
        repo = self._repo(workspace_path)
        scoped = self._scoped_paths(repo, paths)
        if not scoped:
            raise ValueError("at least one scoped path is required")
        subject = str(message or "").strip()
        if not subject or "\n" in subject or len(subject) > 120:
            raise ValueError("commit message must be a single line of at most 120 characters")
        self._git(repo, "add", "--", *scoped)
        staged = self._git(repo, "diff", "--cached", "--name-only", "--", *scoped).splitlines()
        if not staged:
            raise ValueError("no scoped changes are staged")
        self._git(repo, "commit", "-m", subject)
        return {
            "committed": True,
            "commit": self._git(repo, "rev-parse", "HEAD").strip(),
            "branch": self._git(repo, "branch", "--show-current").strip(),
            "paths": staged,
            "author": author,
            "remote_mutation": False,
        }

    @staticmethod
    def _scoped_paths(repo: Path, paths: list[str]) -> list[str]:
        rows = []
        for item in paths:
            rel = str(item).replace("\\", "/").strip("/")
            path = (repo / rel).resolve()
            try:
                path.relative_to(repo)
            except ValueError as exc:
                raise ValueError(f"path escapes workspace: {rel}") from exc
            rows.append(rel)
        return sorted(set(rows))

    @staticmethod
    def _repo(value: str | Path) -> Path:
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise ValueError("repository does not exist")
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if probe.returncode != 0:
            raise ValueError("path must be inside a Git repository")
        return path

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip())
        return result.stdout
