"""Approval-gated Git workspace isolation and delivery operations."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BRANCH_RE = re.compile(r"^codex/[a-z0-9][a-z0-9._/-]{0,80}$")


class CodingWorkspaceService:
    """Create isolated worktrees and hand reviewed changes to Git.

    No remote operation is included.  Push and pull-request creation remain
    separate user-authorized actions.
    """

    def create_task(
        self,
        repo_path: str | Path,
        workspace_root: str | Path,
        task_id: str,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Create a reviewable task worktree without mutating the source tree.

        Dirty tracked and untracked source content is copied into an internal
        baseline commit on the task branch.  The user's index, branch and
        working tree are never changed.
        """

        if confirmed is not True:
            raise PermissionError("confirmed=true is required to create a task workspace")
        repo = self._repo(repo_path)
        root = Path(workspace_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9-]+", "-", str(task_id or "task").lower()).strip("-")[:36] or "task"
        nonce = uuid.uuid4().hex[:8]
        task_root = (root / f"{slug}-{nonce}").resolve()
        try:
            task_root.relative_to(root)
        except ValueError as exc:
            raise ValueError("task workspace escapes workspace_root") from exc
        target = task_root / "repo"
        branch = f"codex/task-{slug[:32]}-{nonce}"
        source_head = self._git(repo, "rev-parse", "HEAD").strip()
        source_status = self._git(repo, "status", "--short").splitlines()
        task_root.mkdir(parents=True, exist_ok=False)
        created = False
        try:
            self._git(repo, "worktree", "add", "-b", branch, str(target), source_head)
            created = True
            tracked_patch = self._git_bytes(repo, "diff", "--binary", "HEAD")
            if tracked_patch:
                applied = subprocess.run(
                    ["git", "apply", "--binary", "--whitespace=nowarn", "-"],
                    cwd=target, input=tracked_patch, capture_output=True, timeout=60,
                )
                if applied.returncode != 0:
                    raise RuntimeError(
                        (applied.stderr or applied.stdout).decode("utf-8", errors="replace").strip()
                        or "failed to materialize tracked source changes"
                    )
            untracked = [
                item.decode("utf-8", errors="strict")
                for item in self._git_bytes(
                    repo, "ls-files", "--others", "--exclude-standard", "-z"
                ).split(b"\0") if item
            ]
            for rel in untracked:
                source = (repo / rel).resolve()
                destination = (target / rel).resolve()
                try:
                    source.relative_to(repo)
                    destination.relative_to(target)
                except ValueError as exc:
                    raise ValueError(f"untracked path escapes repository: {rel}") from exc
                if source.is_symlink():
                    raise ValueError(f"untracked symbolic links are not supported: {rel}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            snapshot_commit = ""
            if source_status:
                self._git(target, "add", "-A")
                if self._git(target, "diff", "--cached", "--name-only").strip():
                    env = dict(os.environ)
                    env.update({
                        "GIT_AUTHOR_NAME": "ClawOS Task Baseline",
                        "GIT_AUTHOR_EMAIL": "task-baseline@clawos.local",
                        "GIT_COMMITTER_NAME": "ClawOS Task Baseline",
                        "GIT_COMMITTER_EMAIL": "task-baseline@clawos.local",
                    })
                    self._git_with_env(
                        target, env, "commit", "-m", "chore: capture task baseline"
                    )
                    snapshot_commit = self._git(target, "rev-parse", "HEAD").strip()
            baseline_commit = self._git(target, "rev-parse", "HEAD").strip()
            created_at = datetime.now(timezone.utc)
            metadata = {
                "schema": "clawos.task-workspace.v1",
                "task_id": str(task_id),
                "source_repo": str(repo),
                "source_head": source_head,
                "source_dirty": bool(source_status),
                "source_status": source_status,
                "workspace": str(target),
                "workspace_root": str(task_root),
                "branch": branch,
                "baseline_commit": baseline_commit,
                "dirty_snapshot_commit": snapshot_commit,
                "isolated": True,
                "source_mutated": False,
                "remote_mutation": False,
                "lifecycle": {
                    "state": "active",
                    "created_at": created_at.isoformat(),
                    "last_activity_at": created_at.isoformat(),
                    "expires_at": (created_at + timedelta(days=7)).isoformat(),
                    "retention_days": 7,
                },
            }
            (task_root / "workspace.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return metadata
        except Exception:
            if created:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(target)],
                    cwd=repo, capture_output=True, timeout=60,
                )
                subprocess.run(
                    ["git", "branch", "-D", branch], cwd=repo,
                    capture_output=True, timeout=30,
                )
            shutil.rmtree(task_root, ignore_errors=True)
            raise

    def changes(self, workspace_metadata: dict[str, Any]) -> dict[str, Any]:
        """Persist and describe the task-only diff from its captured baseline."""

        target = self._repo(str(workspace_metadata.get("workspace") or ""))
        task_root = Path(str(workspace_metadata.get("workspace_root") or "")).resolve()
        baseline = str(workspace_metadata.get("baseline_commit") or "")
        if not baseline or task_root.parent == task_root:
            raise ValueError("invalid task workspace metadata")
        try:
            target.relative_to(task_root)
        except ValueError as exc:
            raise ValueError("task workspace does not match metadata root") from exc
        patch = self._git_bytes(target, "diff", "--binary", baseline)
        patch_path = task_root / "task-changes.diff"
        if patch:
            temporary = patch_path.with_name(f".{patch_path.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_bytes(patch)
            os.replace(temporary, patch_path)
        elif patch_path.exists():
            patch_path.unlink()
        files = self._git(target, "diff", "--name-only", baseline).splitlines()
        status = self._git(target, "status", "--short").splitlines()
        return {
            "schema": "clawos.task-workspace-changes.v1",
            "workspace": str(target),
            "branch": str(workspace_metadata.get("branch") or ""),
            "baseline_commit": baseline,
            "changed_files": files,
            "status": status,
            "patch_path": str(patch_path) if patch else "",
            "patch_sha256": hashlib.sha256(patch).hexdigest() if patch else "",
            "source_mutated": False,
            "human_review_required": True,
        }

    def touch_task(
        self, workspace_metadata_path: str | Path, *, retention_days: int = 7,
    ) -> dict[str, Any]:
        metadata_path = Path(workspace_metadata_path).expanduser().resolve()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        task_root = Path(str(metadata.get("workspace_root") or "")).resolve()
        if metadata_path != task_root / "workspace.json":
            raise ValueError("workspace metadata path does not match task root")
        now = datetime.now(timezone.utc)
        days = max(1, min(int(retention_days or 7), 90))
        lifecycle = dict(metadata.get("lifecycle") or {})
        lifecycle.update({
            "state": "active", "last_activity_at": now.isoformat(),
            "expires_at": (now + timedelta(days=days)).isoformat(),
            "retention_days": days,
        })
        metadata["lifecycle"] = lifecycle
        self._atomic_json(metadata_path, metadata)
        return lifecycle

    def verify_source(self, workspace_metadata: dict[str, Any]) -> dict[str, Any]:
        source = self._repo(str(workspace_metadata.get("source_repo") or ""))
        head = self._git(source, "rev-parse", "HEAD").strip()
        status = self._git(source, "status", "--short").splitlines()
        expected_head = str(workspace_metadata.get("source_head") or "")
        expected_status = list(workspace_metadata.get("source_status") or [])
        return {
            "head_unchanged": head == expected_head,
            "working_tree_unchanged": status == expected_status,
            "source_mutated": head != expected_head or status != expected_status,
            "current_head": head,
        }

    def list_tasks(self, workspace_root: str | Path) -> list[dict[str, Any]]:
        root = Path(workspace_root).expanduser().resolve()
        if not root.is_dir():
            return []
        rows = []
        for metadata_path in sorted(root.glob("*/workspace.json")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if metadata.get("schema") != "clawos.task-workspace.v1":
                    continue
                workspace = Path(str(metadata.get("workspace") or "")).resolve()
                if workspace.parent != metadata_path.parent or not workspace.is_dir():
                    continue
                rows.append({
                    "id": metadata_path.parent.name,
                    "task_id": metadata.get("task_id"),
                    "branch": metadata.get("branch"),
                    "source_dirty": bool(metadata.get("source_dirty")),
                    "changes": self.changes(metadata),
                    "source_verification": self.verify_source(metadata),
                    "lifecycle": metadata.get("lifecycle") or {},
                })
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                continue
        return rows

    def prune_tasks(
        self,
        workspace_root: str | Path,
        *,
        max_age_hours: int = 168,
        dry_run: bool = True,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Expire clean worktrees and archive dirty worktrees before removal."""

        root = Path(workspace_root).expanduser().resolve()
        threshold = datetime.now(timezone.utc) - timedelta(
            hours=max(1, min(int(max_age_hours or 168), 24 * 365))
        )
        candidates = []
        for metadata_path in sorted(root.glob("*/workspace.json")) if root.is_dir() else []:
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                lifecycle = dict(metadata.get("lifecycle") or {})
                raw_time = lifecycle.get("last_activity_at") or lifecycle.get("created_at")
                observed = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                if observed > threshold:
                    continue
                changes = self.changes(metadata)
                candidates.append({
                    "id": metadata_path.parent.name,
                    "metadata_path": str(metadata_path),
                    "dirty": bool(changes.get("status")),
                    "changed_files": changes.get("changed_files") or [],
                })
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                continue
        if dry_run:
            return {
                "schema": "clawos.task-workspace-prune.v1",
                "dry_run": True, "candidates": candidates,
                "removed": [], "archives": [],
            }
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to prune task workspaces")
        removed, archives = [], []
        archive_root = root / ".archives"
        archive_root.mkdir(parents=True, exist_ok=True)
        for candidate in candidates:
            metadata_path = Path(candidate["metadata_path"]).resolve()
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            archive = self._archive_task(metadata, archive_root) if candidate["dirty"] else None
            source = self._repo(str(metadata.get("source_repo") or ""))
            workspace = self._repo(str(metadata.get("workspace") or ""))
            registered = any(
                Path(str(item.get("worktree") or "")).resolve() == workspace
                for item in self.status(source)["worktrees"]
            )
            if not registered:
                continue
            self._git(source, "worktree", "remove", "--force", str(workspace))
            shutil.rmtree(metadata_path.parent, ignore_errors=True)
            removed.append(candidate["id"])
            if archive:
                archives.append(archive)
        return {
            "schema": "clawos.task-workspace-prune.v1",
            "dry_run": False, "candidates": candidates,
            "removed": removed, "archives": archives,
            "recoverable_dirty_workspaces": len(archives),
        }

    def rollback_task(
        self, workspace_metadata_path: str | Path, *, confirmed: bool = False,
    ) -> dict[str, Any]:
        """Restore a task worktree to baseline after saving recovery evidence."""

        if confirmed is not True:
            raise PermissionError("confirmed=true is required to rollback a task workspace")
        metadata_path = Path(workspace_metadata_path).expanduser().resolve()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("schema") != "clawos.task-workspace.v1":
            raise ValueError("invalid task workspace metadata")
        task_root = Path(str(metadata.get("workspace_root") or "")).resolve()
        workspace = self._repo(str(metadata.get("workspace") or ""))
        if metadata_path != task_root / "workspace.json" or workspace.parent != task_root:
            raise ValueError("workspace metadata path does not match task root")
        source = self._repo(str(metadata.get("source_repo") or ""))
        registered = any(
            Path(str(item.get("worktree") or "")).resolve() == workspace
            for item in self.status(source)["worktrees"]
        )
        if not registered:
            raise ValueError("task workspace is not a registered worktree")
        baseline = str(metadata.get("baseline_commit") or "")
        self._git(workspace, "cat-file", "-e", f"{baseline}^{{commit}}")
        recovery = task_root / "recovery" / uuid.uuid4().hex
        recovery.mkdir(parents=True, exist_ok=False)
        patch = self._git_bytes(workspace, "diff", "--binary", baseline)
        if patch:
            (recovery / "tracked.diff").write_bytes(patch)
        untracked = [
            item.decode("utf-8", errors="strict")
            for item in self._git_bytes(
                workspace, "ls-files", "--others", "--exclude-standard", "-z"
            ).split(b"\0") if item
        ]
        for rel in untracked:
            source_path = (workspace / rel).resolve()
            destination = (recovery / "untracked" / rel).resolve()
            try:
                source_path.relative_to(workspace)
                destination.relative_to(recovery / "untracked")
            except ValueError as exc:
                raise ValueError(f"recovery path escapes task workspace: {rel}") from exc
            if source_path.is_symlink():
                raise ValueError(f"cannot safely recover symbolic link: {rel}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        recovery_manifest = {
            "schema": "clawos.task-workspace-recovery.v1",
            "workspace": str(workspace), "baseline_commit": baseline,
            "tracked_patch": str(recovery / "tracked.diff") if patch else "",
            "untracked_files": untracked,
        }
        (recovery / "recovery.json").write_text(
            json.dumps(recovery_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._git(workspace, "reset", "--hard", baseline)
        self._git(workspace, "clean", "-fd")
        return {
            "rolled_back": True, "workspace": str(workspace),
            "baseline_commit": baseline,
            "recovery_manifest": str(recovery / "recovery.json"),
            "recoverable": True, "source_mutated": False,
        }

    def _archive_task(
        self, metadata: dict[str, Any], archive_root: Path,
    ) -> dict[str, Any]:
        workspace = self._repo(str(metadata.get("workspace") or ""))
        task_id = Path(str(metadata.get("workspace_root") or "")).name
        target = (archive_root / f"{task_id}-{uuid.uuid4().hex[:8]}").resolve()
        target.mkdir(parents=True, exist_ok=False)
        patch = self._git_bytes(
            workspace, "diff", "--binary",
            str(metadata.get("baseline_commit") or "HEAD"),
        )
        if patch:
            (target / "tracked.diff").write_bytes(patch)
        untracked = [
            item.decode("utf-8", errors="strict")
            for item in self._git_bytes(
                workspace, "ls-files", "--others", "--exclude-standard", "-z"
            ).split(b"\0") if item
        ]
        for rel in untracked:
            source = (workspace / rel).resolve()
            destination = (target / "untracked" / rel).resolve()
            source.relative_to(workspace)
            destination.relative_to(target / "untracked")
            if source.is_symlink():
                raise ValueError(f"cannot archive symbolic link: {rel}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        archive = {
            "schema": "clawos.task-workspace-archive.v1",
            "task_id": metadata.get("task_id"), "branch": metadata.get("branch"),
            "baseline_commit": metadata.get("baseline_commit"),
            "source_repo": metadata.get("source_repo"),
            "tracked_patch": str(target / "tracked.diff") if patch else "",
            "untracked_files": untracked, "recoverable": True,
        }
        self._atomic_json(target / "archive.json", archive)
        return {"id": target.name, "recoverable": True, "dirty": True}

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

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

    def merge_plan(
        self, repo_path: str | Path, branch: str, *, base_ref: str = "HEAD"
    ) -> dict[str, Any]:
        """Return a read-only delivery plan; never merge automatically."""

        repo = self._repo(repo_path)
        if not BRANCH_RE.fullmatch(str(branch or "")):
            raise ValueError("branch must use the codex/ prefix and safe characters")
        commits = self._git(
            repo, "log", "--oneline", f"{base_ref}..{branch}"
        ).splitlines()
        files = self._git(
            repo, "diff", "--name-only", f"{base_ref}...{branch}"
        ).splitlines()
        return {
            "schema": "clawos.coding-delivery-plan.v1",
            "branch": branch,
            "base_ref": base_ref,
            "commits": commits,
            "files": files,
            "merge_performed": False,
            "requires_human_review": True,
        }

    def remove(
        self,
        repo_path: str | Path,
        workspace_path: str | Path,
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to remove a worktree")
        repo = self._repo(repo_path)
        target = Path(workspace_path).expanduser().resolve()
        worktrees = self.status(repo)["worktrees"]
        registered = next(
            (
                item for item in worktrees
                if Path(str(item.get("worktree") or "")).resolve() == target
            ),
            None,
        )
        if not registered:
            raise ValueError("workspace is not a registered worktree")
        target_repo = self._repo(target)
        dirty = self._git(target_repo, "status", "--porcelain").strip()
        if dirty:
            raise ValueError("refusing to remove a dirty worktree")
        self._git(repo, "worktree", "remove", str(target))
        return {
            "removed": True,
            "workspace": str(target),
            "recoverable_from_branch": bool(registered.get("branch")),
            "branch": str(registered.get("branch") or "").removeprefix("refs/heads/"),
        }

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

    @staticmethod
    def _git_bytes(repo: Path, *args: str) -> bytes:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
            )
        return result.stdout

    @staticmethod
    def _git_with_env(repo: Path, env: dict[str, str], *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip())
        return result.stdout
