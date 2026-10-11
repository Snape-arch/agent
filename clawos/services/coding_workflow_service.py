from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .coding_context_service import CodingContextService
from .coding_diagnostics_service import CodingDiagnosticsService
from .egress_proxy import AuditedEgressProxy, EgressProxyPolicy
from .os_sandbox import WindowsJobSandbox, WindowsRestrictedTokenSandbox
from .windows_appcontainer_boundary import WindowsAppContainerBoundary
from .runtime_records import RunRecord, now_iso


ALLOWED_SOURCE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".sh",
    ".ps1", ".html", ".css", ".scss", ".json", ".yaml", ".yml", ".toml",
    ".ini", ".md", ".txt", ".sql", ".xml",
}
ALLOWED_TEST_COMMANDS = {"python", "python3", "py", "pytest", "npm", "pnpm", "node", "cargo", "go", "dotnet", "mvn", "gradle"}
BLOCKED_COMMAND = re.compile(r"(?:[;&|><`] |[;&|><`]|\r|\n|\$\(|\b(?:rm|del|erase|format|shutdown|reboot)\b)", re.I)


class CodingWorkflowService:
    """Approval-gated coding loop with scoped changes, tests, review, retry and rollback."""

    def __init__(self, store: Any | None = None, artifact_root: str | Path = "output/coding"):
        self.store = store
        self.artifact_root = Path(artifact_root).expanduser().resolve()
        self.context_service = CodingContextService()
        self.diagnostics_service = CodingDiagnosticsService()

    def inspect(
        self,
        repo_path: str | Path,
        query: str = "",
        limit: int = 80,
        *,
        token_budget: int = 12000,
        focus_paths: list[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        repo = self._repo(repo_path)
        files = self._git(repo, "ls-files").splitlines()
        files.extend(
            self._git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
        )
        selected = []
        tokens = [item.lower() for item in re.findall(r"[A-Za-z0-9_./-]{2,}", query or "")]
        for rel in files:
            path = (repo / rel).resolve()
            if path.suffix.lower() not in ALLOWED_SOURCE_SUFFIXES or not path.is_file():
                continue
            score = sum(token in rel.lower() for token in tokens)
            if tokens and score == 0:
                try:
                    sample = path.read_text(encoding="utf-8", errors="replace")[:120_000].lower()
                    score = sum(token in sample for token in tokens)
                except OSError:
                    score = 0
            selected.append({"path": rel.replace("\\", "/"), "bytes": path.stat().st_size, "match_score": score})
        selected.sort(key=lambda item: (item["match_score"], -item["bytes"]), reverse=True)
        status = self._git(repo, "status", "--short")
        context_pack = self.context_service.build(
            repo,
            query,
            focus_paths=focus_paths,
            token_budget=token_budget,
            diagnostics=diagnostics,
        )
        return {
            "repo": str(repo),
            "head": self._git(repo, "rev-parse", "HEAD").strip(),
            "branch": self._git(repo, "branch", "--show-current").strip(),
            "dirty": bool(status.strip()),
            "status": status.splitlines(),
            "candidate_files": selected[: max(1, min(int(limit or 80), 200))],
            "query": query,
            "context_pack": context_pack,
            "recommended_tests": self.discover_tests(repo, [
                item["path"] for item in selected[:10]
            ]),
        }

    def discover_tests(
        self, repo_path: str | Path, changed_paths: list[str] | None = None
    ) -> list[list[str]]:
        """Return bounded, deterministic test commands for the repository."""

        repo = self._repo(repo_path)
        changed = [str(item).replace("\\", "/") for item in (changed_paths or [])]
        commands: list[list[str]] = []
        if (repo / "pyproject.toml").exists() or (repo / "pytest.ini").exists():
            related = [
                rel for rel in self._git(repo, "ls-files").splitlines()
                if ("test" in rel.lower() or "spec" in rel.lower())
                and any(Path(path).stem.removeprefix("test_") in rel for path in changed)
            ][:20]
            commands.append(["python", "-m", "pytest", *(related or ["-q"])])
        elif any((repo / name).exists() for name in ("setup.py", "requirements.txt")):
            commands.append(["python", "-m", "unittest", "discover"])
        if (repo / "package.json").exists():
            commands.append(["npm", "test", "--", "--runInBand"])
        if (repo / "Cargo.toml").exists():
            commands.append(["cargo", "test"])
        if (repo / "go.mod").exists():
            commands.append(["go", "test", "./..."])
        if (repo / "pom.xml").exists():
            commands.append(["mvn", "test"])
        if any((repo / name).exists() for name in ("build.gradle", "build.gradle.kts")):
            commands.append(["gradle", "test"])
        return commands[:5]

    def plan(self, repo_path: str | Path, objective: str, changes: list[dict[str, Any]], test_commands: list[Any] | None = None) -> dict[str, Any]:
        repo = self._repo(repo_path)
        normalized = self._normalize_changes(repo, changes)
        commands = [self._validate_command(item) for item in (test_commands or [])]
        return {
            "schema": "clawos.coding-plan.v1",
            "objective": str(objective or "").strip(),
            "repo": str(repo),
            "base_head": self._git(repo, "rev-parse", "HEAD").strip(),
            "changes": [{key: item[key] for key in ("path", "operation", "before_sha256", "after_sha256") if key in item} for item in normalized],
            "test_commands": commands,
            "risk": "high" if normalized else "low",
            "requires_confirmation": bool(normalized),
            "gate": "ready" if objective and normalized and commands else "incomplete",
        }

    def execute(
        self,
        repo_path: str | Path,
        objective: str,
        changes: list[dict[str, Any]],
        test_commands: list[Any],
        *,
        confirmed: bool = False,
        repair_rounds: list[list[dict[str, Any]]] | None = None,
        max_rounds: int = 2,
        timeout_seconds: int = 180,
        actor: str = "coding-agent",
        acceptance_criteria: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required for coding writes and test execution")
        repo = self._repo(repo_path)
        normalized = self._normalize_changes(repo, changes)
        commands = [self._validate_command(item) for item in test_commands]
        if not normalized or not commands:
            raise ValueError("at least one scoped change and one test command are required")
        run_id = f"coding-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        checkpoint_dir = self.artifact_root / "checkpoints" / run_id
        checkpoint_dir.mkdir(parents=True, exist_ok=False)
        base_head = self._git(repo, "rev-parse", "HEAD").strip()
        manifest = self._checkpoint(repo, checkpoint_dir, normalized, base_head, objective)
        rounds = []
        started = time.perf_counter()
        status = "failed"
        restored = False
        failure = ""
        repair_payloads = list(repair_rounds or [])
        scoped_paths = {item["path"] for item in normalized}
        try:
            allowed_rounds = max(1, min(int(max_rounds or 2), 5))
            for round_no in range(1, allowed_rounds + 1):
                if round_no == 1:
                    round_changes = normalized
                elif round_no - 2 < len(repair_payloads):
                    round_changes = self._normalize_changes(repo, repair_payloads[round_no - 2])
                    if any(item["path"] not in scoped_paths for item in round_changes):
                        raise ValueError("repair rounds may only modify checkpointed files")
                else:
                    break
                round_checkpoint = checkpoint_dir / f"round-{round_no:02d}"
                round_checkpoint.mkdir(parents=True, exist_ok=False)
                self._checkpoint(
                    repo, round_checkpoint, round_changes, base_head,
                    f"{objective} (round {round_no})",
                )
                self._apply_changes(repo, round_changes)
                tests = [self._run_command(repo, command, timeout_seconds) for command in commands]
                diagnostics = self.diagnostics_service.analyze(repo, tests)
                review = self._review(
                    repo, [item["path"] for item in manifest["files"]], tests,
                    acceptance_criteria=acceptance_criteria,
                    diagnostics=diagnostics,
                )
                rounds.append({
                    "round": round_no,
                    "changes": [item["path"] for item in round_changes],
                    "checkpoint": str(round_checkpoint / "manifest.json"),
                    "tests": tests,
                    "diagnostics": diagnostics,
                    "review": review,
                })
                if review["gate"] == "pass":
                    status = "passed"
                    break
                failure = "; ".join(review["failures"])
            if status != "passed":
                self._restore(repo, checkpoint_dir, manifest)
                restored = True
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
            self._restore(repo, checkpoint_dir, manifest)
            restored = True
        diff = self._git(repo, "diff", "--", *[item["path"] for item in manifest["files"]]) if status == "passed" else ""
        diff_path = checkpoint_dir / "accepted.diff"
        if diff:
            diff_path.write_text(diff, encoding="utf-8")
        payload = {
            "schema": "clawos.coding-workflow.v1",
            "run_id": run_id,
            "status": status,
            "objective": objective,
            "repo": str(repo),
            "base_head": base_head,
            "checkpoint": str(checkpoint_dir / "manifest.json"),
            "rounds": rounds,
            "restored_on_failure": restored,
            "failure": failure,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "diff_path": str(diff_path) if diff else "",
            "commit_created": False,
            "human_review_required": True,
            "acceptance": rounds[-1]["review"].get("acceptance") if rounds else {
                "passed": False, "criteria": [], "failures": ["no execution round completed"]
            },
        }
        self._save_run(payload, actor)
        return payload

    def rollback(self, repo_path: str | Path, checkpoint: str | Path, *, confirmed: bool = False, actor: str = "user") -> dict[str, Any]:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required for rollback")
        repo = self._repo(repo_path)
        manifest_path = Path(checkpoint).expanduser().resolve()
        expected_root = (self.artifact_root / "checkpoints").resolve()
        try:
            manifest_path.relative_to(expected_root)
        except ValueError as exc:
            raise ValueError("checkpoint is outside the coding artifact root") from exc
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._restore(repo, manifest_path.parent, manifest)
        return {"rolled_back": True, "checkpoint": str(manifest_path), "actor": actor, "files": [item["path"] for item in manifest["files"]]}

    def _checkpoint(self, repo: Path, root: Path, changes: list[dict[str, Any]], base_head: str, objective: str) -> dict[str, Any]:
        rows = []
        for index, item in enumerate(changes, 1):
            path = repo / item["path"]
            existed = path.is_file()
            backup = f"{index:04d}.bin"
            if existed:
                (root / backup).write_bytes(path.read_bytes())
            rows.append({"path": item["path"], "existed": existed, "backup": backup if existed else "", "sha256": self._sha(path.read_bytes()) if existed else ""})
        manifest = {"schema": "clawos.coding-checkpoint.v1", "repo": str(repo), "base_head": base_head, "objective": objective, "created_at": now_iso(), "files": rows}
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest

    def _normalize_changes(self, repo: Path, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        for raw in changes or []:
            rel = str(raw.get("path") or "").replace("\\", "/").strip(" /")
            if not rel or rel in seen:
                raise ValueError("each change requires a unique relative path")
            path = (repo / rel).resolve()
            try:
                path.relative_to(repo)
            except ValueError as exc:
                raise ValueError(f"change escapes repository: {rel}") from exc
            if path.suffix.lower() not in ALLOWED_SOURCE_SUFFIXES:
                raise ValueError(f"unsupported source file type: {rel}")
            before = path.read_text(encoding="utf-8", errors="strict") if path.is_file() else ""
            operation = str(raw.get("operation") or "replace").lower()
            if operation == "replace":
                old = str(raw.get("old_text") or "")
                new = str(raw.get("new_text") or "")
                if not old or before.count(old) != 1:
                    raise ValueError(f"old_text must match exactly once: {rel}")
                after = before.replace(old, new, 1)
            elif operation == "create":
                if path.exists():
                    raise ValueError(f"create target already exists: {rel}")
                after = str(raw.get("content") or "")
            elif operation == "overwrite":
                expected = str(raw.get("expected_sha256") or "")
                if not expected or expected != self._sha(before.encode("utf-8")):
                    raise ValueError(f"overwrite requires matching expected_sha256: {rel}")
                after = str(raw.get("content") or "")
            elif operation == "hunks":
                after = before
                hunks = list(raw.get("hunks") or [])
                if not hunks:
                    raise ValueError(f"hunks operation requires hunks: {rel}")
                for hunk in hunks:
                    old = str(hunk.get("old_text") or "")
                    new = str(hunk.get("new_text") or "")
                    if not old or after.count(old) != 1:
                        raise ValueError(
                            f"each hunk old_text must match exactly once: {rel}"
                        )
                    after = after.replace(old, new, 1)
            else:
                raise ValueError(f"unsupported change operation: {operation}")
            rows.append({"path": rel, "operation": operation, "content": after, "before_sha256": self._sha(before.encode("utf-8")), "after_sha256": self._sha(after.encode("utf-8"))})
            seen.add(rel)
        return rows

    @staticmethod
    def _apply_changes(repo: Path, changes: list[dict[str, Any]]) -> None:
        for item in changes:
            path = repo / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_text(item["content"], encoding="utf-8")
            os.replace(temporary, path)
            CodingWorkflowService._invalidate_bytecode(path)

    @staticmethod
    def _restore(repo: Path, root: Path, manifest: dict[str, Any]) -> None:
        for item in manifest.get("files", []):
            path = (repo / item["path"]).resolve()
            if item.get("existed"):
                backup = root / item["backup"]
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.restore")
                shutil.copyfile(backup, temporary)
                os.replace(temporary, path)
                CodingWorkflowService._invalidate_bytecode(path)
            elif path.exists():
                path.unlink()

    @staticmethod
    def _invalidate_bytecode(path: Path) -> None:
        """Prevent same-size/same-second Python edits from reusing stale pyc."""
        if path.suffix.lower() != ".py":
            return
        cache = path.parent / "__pycache__"
        if not cache.is_dir():
            return
        for compiled in cache.glob(f"{path.stem}.*.pyc"):
            try:
                compiled.unlink()
            except OSError:
                continue

    def _review(
        self, repo: Path, files: list[str], tests: list[dict[str, Any]], *,
        acceptance_criteria: list[dict[str, Any]] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        failures = [f"test failed: {item['command']}" for item in tests if item["exit_code"] != 0 or item.get("timed_out")]
        diff_check = subprocess.run(["git", "diff", "--check", "--", *files], cwd=repo, capture_output=True, text=True, timeout=30)
        if diff_check.returncode != 0:
            failures.append("git diff --check failed")
        changed = self._git(repo, "diff", "--name-only", "--", *files).splitlines()
        if not changed:
            failures.append("no scoped diff produced")
        syntax = self._syntax_review(repo, changed)
        failures.extend(
            f"syntax failed: {item['path']}: {item['message']}"
            for item in syntax if not item["passed"]
        )
        acceptance = self._acceptance_gate(
            acceptance_criteria or [], tests=tests, changed=changed,
            diff_check=diff_check, syntax=syntax,
        )
        failures.extend(acceptance["failures"])
        return {
            "gate": "pass" if not failures else "revision_required",
            "failures": failures, "changed_files": changed,
            "diff_check": diff_check.stdout + diff_check.stderr,
            "syntax_review": syntax,
            "all_tests_passed": all(item["exit_code"] == 0 and not item.get("timed_out") for item in tests),
            "failure_category": (diagnostics or {}).get("failure_category", "none"),
            "diagnostics": diagnostics or {}, "acceptance": acceptance,
        }

    @staticmethod
    def _acceptance_gate(
        criteria: list[dict[str, Any]], *, tests: list[dict[str, Any]],
        changed: list[str], diff_check: subprocess.CompletedProcess,
        syntax: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized = list(criteria or [
            {"id": "tests_pass", "type": "tests_pass"},
            {"id": "scoped_diff", "type": "scoped_diff"},
            {"id": "syntax_pass", "type": "syntax_pass"},
            {"id": "diff_check", "type": "diff_check"},
        ])
        evidence = {
            "tests_pass": bool(tests) and all(item.get("exit_code") == 0 and not item.get("timed_out") for item in tests),
            "scoped_diff": bool(changed),
            "syntax_pass": all(item.get("passed") for item in syntax),
            "diff_check": diff_check.returncode == 0,
        }
        results, failures = [], []
        for criterion in normalized:
            kind = str(criterion.get("type") or criterion.get("id") or "")
            passed = bool(evidence.get(kind, False))
            item = {"id": str(criterion.get("id") or kind), "type": kind, "passed": passed}
            results.append(item)
            if not passed:
                failures.append(f"acceptance criterion failed: {item['id']}")
        return {"passed": not failures, "criteria": results, "failures": failures}

    @staticmethod
    def _syntax_review(repo: Path, files: list[str]) -> list[dict[str, Any]]:
        rows = []
        for rel in files:
            path = repo / rel
            if path.suffix.lower() != ".py" or not path.is_file():
                continue
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
                rows.append({"path": rel, "passed": True, "message": ""})
            except (SyntaxError, UnicodeError) as exc:
                rows.append({"path": rel, "passed": False, "message": str(exc)})
        return rows

    @staticmethod
    def _validate_command(command: Any) -> list[str]:
        parts = [str(item) for item in command] if isinstance(command, list) else shlex.split(str(command or ""), posix=os.name != "nt")
        if not parts or BLOCKED_COMMAND.search(" ".join(parts)):
            raise ValueError("unsafe or empty test command")
        executable = Path(parts[0]).stem.lower()
        if executable not in ALLOWED_TEST_COMMANDS:
            raise ValueError(f"test command is not allowlisted: {executable}")
        return parts

    @staticmethod
    def _run_command(repo: Path, command: list[str], timeout_seconds: int) -> dict[str, Any]:
        started = time.perf_counter()
        strict = os.environ.get("CLAWOS_REQUIRE_OS_SANDBOX", "").lower() in {"1", "true", "yes"}
        metadata_path = repo.parent / "workspace.json"
        if os.name == "nt" and metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                if (
                    metadata.get("schema") == "clawos.task-workspace.v1"
                    and Path(str(metadata.get("workspace") or "")).resolve() == repo
                    and metadata.get("isolated") is True
                ):
                    appcontainer = WindowsAppContainerBoundary(
                        os.environ.get("CLAWOS_APPCONTAINER_PROFILE") or "ClawOS.CodingSandbox"
                    )
                    if not os.environ.get('CLAWOS_APPCONTAINER_RUNTIME') and not os.environ.get('CLAWOS_APPCONTAINER_PROFILE'):
                        from .sandbox_runtime import SandboxRuntime
                        managed = SandboxRuntime().resolve()
                        if managed is not None: appcontainer = managed
                    appcontainer_status = appcontainer.status()
                    if appcontainer_status.get("installed"):
                        try:
                            result = appcontainer.run_command(
                                command, repo, timeout_seconds=timeout_seconds,
                                confirmed_acl=True,
                            )
                            if not result.get('sandbox', {}).get('strict_boundary_verified'):
                                raise RuntimeError('parent-attested strict boundary is required')
                            result["sandbox"]["egress"] = {
                                "policy": "deny-direct-network",
                                "broker_required": True,
                                "network_capabilities": [],
                                "direct_socket_non_bypass_enforced": result['sandbox'].get('direct_socket_non_bypass_enforced') is True,
                            }
                            return result
                        except (OSError, RuntimeError, ValueError, TimeoutError) as exc:
                            return {
                                "command": command, "exit_code": 126, "stdout": "",
                                "stderr": f"AppContainer launch failed closed: {type(exc).__name__}: {exc}",
                                "timed_out": False,
                                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                                "sandbox": {
                                    "backend": "windows-appcontainer",
                                    "os_enforced": False, "launch_failed_closed": True,
                                    "production_sandbox_ready": False,
                                    "downgrade_blocked": True,
                                },
                            }
                    if strict:
                        raise ValueError("strict sandbox requires an installed AppContainer; fallback blocked")
                    proxy = AuditedEgressProxy(
                        EgressProxyPolicy(allowed_hosts=[]),
                        secrets.token_urlsafe(32),
                    ).start()
                    proxy_host, proxy_port = proxy.address
                    proxy_url = f"http://{proxy_host}:{proxy_port}"
                    sandbox_environment = {
                        "PATH": os.environ.get("PATH", ""),
                        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                        "TEMP": os.environ.get("TEMP", ""),
                        "TMP": os.environ.get("TMP", ""),
                        "PYTHONIOENCODING": "utf-8",
                        "HTTP_PROXY": proxy_url,
                        "HTTPS_PROXY": proxy_url,
                        "ALL_PROXY": proxy_url,
                        "NO_PROXY": "127.0.0.1,localhost,::1",
                    }
                    try:
                        try:
                            sandbox_result = WindowsRestrictedTokenSandbox().run_command(
                                command, repo, environment=sandbox_environment,
                                timeout_seconds=timeout_seconds,
                            )
                        except (OSError, RuntimeError, ValueError) as exc:
                            sandbox_result = WindowsJobSandbox(
                                max_processes=8, process_memory_mb=1024,
                            ).run(
                                command, repo,
                                environment=sandbox_environment,
                                timeout_seconds=timeout_seconds,
                            )
                            sandbox_result["sandbox"]["restricted_token_attempted"] = True
                            sandbox_result["sandbox"]["restricted_token_error"] = (
                                f"{type(exc).__name__}: {exc}"
                            )
                            sandbox_result["sandbox"]["filesystem_write_boundary"] = (
                                "isolated-task-worktree-application-boundary"
                            )
                            sandbox_result["sandbox"]["production_sandbox_ready"] = False
                    finally:
                        proxy.stop()
                    sandbox_result["sandbox"]["egress"] = {
                        "authenticated_proxy_started": True,
                        "default_deny_external": True,
                        "proxy_environment_configured": True,
                        "loopback_test_bypass": True,
                        "audit_events": len(proxy.audit),
                        "direct_socket_non_bypass_enforced": False,
                    }
                    return sandbox_result
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                return {
                    "command": command, "exit_code": 126, "stdout": "",
                    "stderr": f"sandbox orchestration failed closed: {type(exc).__name__}: {exc}",
                    "timed_out": False,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "sandbox": {
                        "backend": "task-sandbox-orchestrator",
                        "os_enforced": False, "launch_failed_closed": True,
                        "production_sandbox_ready": False,
                    },
                }
        if strict:
            return {"command": command, "exit_code": 126, "stdout": "",
                    "stderr": "strict sandbox requires an isolated task workspace and Windows AppContainer",
                    "timed_out": False, "duration_ms": round((time.perf_counter()-started)*1000, 2),
                    "sandbox": {"backend": "strict-sandbox-gate", "launch_failed_closed": True,
                                "downgrade_blocked": True, "production_sandbox_ready": False}}
        try:
            result = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=max(1, min(int(timeout_seconds or 180), 900)))
            return {"command": command, "exit_code": result.returncode, "stdout": result.stdout[-8000:], "stderr": result.stderr[-4000:], "timed_out": False, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "sandbox": {"backend": "subprocess-policy-boundary", "os_enforced": False, "production_sandbox_ready": False}}
        except subprocess.TimeoutExpired as exc:
            return {"command": command, "exit_code": 124, "stdout": str(exc.stdout or "")[-8000:], "stderr": str(exc.stderr or "")[-4000:], "timed_out": True, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "sandbox": {"backend": "subprocess-policy-boundary", "os_enforced": False, "production_sandbox_ready": False}}

    def _save_run(self, payload: dict[str, Any], actor: str) -> None:
        if not self.store:
            return
        run = RunRecord(run_id=payload["run_id"], run_type="coding_workflow", title=payload["objective"], status=payload["status"], actor=actor, scenario="project", completed_at=now_iso(), inputs={"repo": payload["repo"], "base_head": payload["base_head"]}, outputs={key: payload[key] for key in ("checkpoint", "diff_path", "restored_on_failure", "failure")}, metrics={"rounds": len(payload["rounds"]), "duration_ms": payload["duration_ms"]}, workflow={"stages": ["inspect", "plan", "patch", "test", "review", "retry", "checkpoint", "rollback"]}, tags=["coding", "approval-gated", "rollback"])
        if payload.get("diff_path"):
            run.add_artifact("patch", "Accepted scoped diff", payload["diff_path"])
        run.add_artifact("checkpoint", "Pre-change checkpoint", payload["checkpoint"])
        if payload["status"] != "passed":
            run.add_failure_case("coding_gate", payload.get("failure") or "coding gate failed", severity="high", remediation="Inspect failed tests and submit a scoped repair round.")
        self.store.save_run_record(run.to_dict())

    @staticmethod
    def _repo(value: str | Path) -> Path:
        path = Path(value).expanduser().resolve()
        if not path.is_dir() or not (path / ".git").exists():
            raise ValueError("repo_path must be a Git repository")
        return path

    @staticmethod
    def _git(repo: Path, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip())
        return result.stdout

    @staticmethod
    def _sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()
