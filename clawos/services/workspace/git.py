"""Git workflows and their domain dependencies."""
from __future__ import annotations
import json
import hashlib
import re
import subprocess
from pathlib import Path


class GitWorkspace:
    """Workspace git responsibilities."""

    def __init__(self, store, security):
        self.store = store
        self.security = security

    def git_snapshot(self, repo_path):
        repo = self.security.resolve_path(repo_path)
        if not (repo / ".git").exists():
            raise ValueError("path is not a Git repository")
        branch = self._git(repo, "branch", "--show-current").strip()
        status = self._git(repo, "status", "--short")
        diff = self._git(repo, "diff", "--stat")
        log = self._git(repo, "log", "-5", "--oneline")
        changed = [line for line in status.splitlines() if line.strip()]
        return {
            "repo": str(repo),
            "branch": branch,
            "status": changed,
            "diff_stat": diff.splitlines(),
            "recent_commits": log.splitlines(),
            "clean": not changed,
        }


    def prepare_commit_plan(self, repo_path, message, files=None):
        snapshot = self.git_snapshot(repo_path)
        repo = Path(snapshot["repo"])
        selected = self._normalize_git_files(repo, files or [line[3:] for line in snapshot["status"] if len(line) > 3])
        if not str(message or "").strip() or not selected:
            raise ValueError("commit message and at least one changed file are required")
        return {
            "repo": snapshot["repo"],
            "branch": snapshot["branch"],
            "message": str(message).strip(),
            "files": selected,
            "commands": [
                ["git", "add", "--", *selected],
                ["git", "commit", "-m", str(message).strip()],
            ],
            "dry_run": True,
            "requires_confirmation": True,
        }


    def create_git_change_request(self, repo_path, message, files=None, created_by="user"):
        plan = self.prepare_commit_plan(repo_path, message, files)
        repo = Path(plan["repo"])
        selected = plan["files"]
        diff_preview, diff_fingerprint = self._git_change_snapshot(repo, selected)
        diff_preview = f"{diff_preview}\n# CLAWOS_DIFF_SHA256={diff_fingerprint}\n"
        checkpoint = self._git(repo, "rev-parse", "HEAD").strip()
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO git_change_requests
                    (repo_path, branch, message, files, diff_preview, checkpoint_ref, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan["repo"], plan["branch"], plan["message"],
                    json.dumps(selected, ensure_ascii=False), diff_preview,
                    checkpoint, str(created_by or "user"),
                ),
            )
            row = c.execute("SELECT * FROM git_change_requests WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return self._git_request_from_row(row)


    def approve_git_change_request(self, request_id, approved_by="user"):
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)).fetchone()
            if not row:
                raise ValueError("change request not found")
            request = self._git_request_from_row(row)
            if request["status"] != "pending_approval":
                raise ValueError("change request is not pending approval")
        repo = self.security.resolve_path(request["repo_path"])
        current_head = self._git(repo, "rev-parse", "HEAD").strip()
        if current_head != request["checkpoint_ref"]:
            raise ValueError("repository HEAD changed after approval request; create a new request")
        current_preview, current_fingerprint = self._git_change_snapshot(repo, request["files"])
        marker = re.search(r"# CLAWOS_DIFF_SHA256=([a-f0-9]{64})", request["diff_preview"])
        if not marker or marker.group(1) != current_fingerprint:
            raise ValueError("approved diff changed after request; create a new request")
        self._git(repo, "add", "--", *request["files"])
        self._git(repo, "commit", "-m", request["message"])
        after = self._git(repo, "rev-parse", "HEAD").strip()
        with self.store._conn() as c:
            c.execute(
                """
                UPDATE git_change_requests
                SET status='committed', approved_by=?, after_ref=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (str(approved_by or "user"), after, int(request_id)),
            )
            return self._git_request_from_row(c.execute(
                "SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)
            ).fetchone())


    def rollback_git_change_request(self, request_id, actor_id="user"):
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)).fetchone()
            if not row:
                raise ValueError("change request not found")
            request = self._git_request_from_row(row)
            if request["status"] != "committed" or not request["after_ref"]:
                raise ValueError("only committed change requests can be rolled back")
        repo = self.security.resolve_path(request["repo_path"])
        if self._git(repo, "rev-parse", "HEAD").strip() != request["after_ref"]:
            raise ValueError("repository HEAD moved after the approved commit; rollback requires manual review")
        if self._git(repo, "status", "--porcelain").strip():
            raise ValueError("rollback requires a clean working tree")
        self._git(repo, "revert", "--no-edit", request["after_ref"])
        with self.store._conn() as c:
            c.execute(
                """
                UPDATE git_change_requests
                SET status='rolled_back', approved_by=approved_by || '; rollback:' || ?, updated_at=datetime('now')
                WHERE id=?
                """,
                (str(actor_id or "user"), int(request_id)),
            )
            return self._git_request_from_row(c.execute(
                "SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)
            ).fetchone())


    @staticmethod
    def _normalize_git_files(repo, files):
        rows = []
        for raw in files or []:
            rel = str(raw or "").replace("\\", "/").strip()
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            path = (repo / rel).resolve()
            try:
                path.relative_to(repo.resolve())
            except ValueError as exc:
                raise ValueError(f"Git file escapes repository: {rel}") from exc
            if not rel or rel.startswith(".git/"):
                raise ValueError(f"invalid Git file: {rel}")
            rows.append(rel)
        return sorted(set(rows))


    def _git_change_snapshot(self, repo, selected):
        preview = self._git(repo, "diff", "--binary", "--", *selected)
        payload = [preview]
        tracked = set(self._git(repo, "ls-files", "--", *selected).splitlines())
        for rel in selected:
            path = repo / rel
            if rel not in tracked and path.is_file():
                data = path.read_bytes()
                excerpt = data.decode("utf-8", errors="replace")[:20000]
                payload.append(f"\n--- /dev/null\n+++ b/{rel}\n# untracked sha256={hashlib.sha256(data).hexdigest()} bytes={len(data)}\n{excerpt}")
        rendered = "".join(payload)
        return rendered, hashlib.sha256(rendered.encode("utf-8")).hexdigest()


    @staticmethod
    def _git(repo, *args):
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git command failed")
        return proc.stdout


    @staticmethod
    def _git_request_from_row(row):
        item = dict(row)
        item["files"] = json.loads(item.get("files") or "[]")
        return item
