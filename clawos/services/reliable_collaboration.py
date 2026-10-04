"""Model-planned coding DAGs with isolated edits and restartable evidence.

Workers propose bounded patches; only this coordinator writes its own worktrees.
No source checkout writes, remote Git operations or model-selected commands occur.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import uuid
from typing import Any, Callable

from .autonomous_subagent_service import SubagentRoleSpec
from .coding_workspace_service import CodingWorkspaceService
from .coding_workflow_service import CodingWorkflowService
from .file_transactions import _file_lock, write_text
from .runtime_records import RunRecord, now_iso


class ReliableCollaborationService:
    """Single coordinator owner, concurrent workers, immutable accepted commits.

    The process lock is released by the OS on death. A replacement coordinator
    reuses only verified completed commits; interrupted attempts get new worktrees.
    This is process ownership, not a distributed lease or an OS sandbox itself.
    """

    def __init__(self, provider_factory: Callable, *, root: str | Path,
                 store=None, max_concurrency=3):
        self.factory = provider_factory
        self.root = Path(root).resolve()
        self.store = store
        self.concurrency = max(1, min(int(max_concurrency), 4))
        self.workspaces = CodingWorkspaceService()
        self.workflow = CodingWorkflowService(artifact_root=self.root / "coding-evidence")

    @staticmethod
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def git(repo, *args, check=True):
        result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                                "-c", "commit.gpgsign=false", "-c", "rerere.enabled=false", *args], cwd=repo,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=60)
        if check and result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-2000:])
        return result

    @staticmethod
    def safe_path(value):
        text = str(value)
        path = PurePosixPath(text)
        if (not text or "\\" in text or ":" in text or path.is_absolute()
                or any(part in {"..", ".git", "tools", ".aws", ".codex"}
                       or part.startswith(".env") for part in path.parts)
                or str(path) != text):
            raise ValueError("invalid or sensitive collaboration path")
        return text

    def read_files(self, repo, paths):
        files = {}
        for rel in paths:
            path = Path(repo) / self.safe_path(rel)
            if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != Path(repo).parent):
                raise ValueError("symbolic links are outside the collaboration contract")
            path.resolve().relative_to(Path(repo).resolve())
            if path.exists():
                if not path.is_file() or path.stat().st_size > 128_000:
                    raise ValueError("each collaboration file must be text under 128 KB")
                files[rel] = path.read_text(encoding="utf-8")
            else:
                files[rel] = None
        if sum(len(str(v).encode()) for v in files.values()) > 384_000:
            raise ValueError("collaboration context exceeds 384 KB")
        return files

    def source_stamp(self, repo, paths):
        # Ignored/runtime files are outside this assertion. Verify tracked Git
        # state and the explicitly authorized source files, never claim OS-wide isolation.
        return self.digest({"head":self.git(repo,"rev-parse","HEAD").stdout,
            "status":self.git(repo,"status","--porcelain").stdout,
            "diff":self.git(repo,"diff","--binary","HEAD").stdout,
            "index":self.git(repo,"diff","--cached","--binary").stdout,
            "files":self.read_files(repo,paths)})

    def validate_plan(self, plan, allowed):
        nodes = plan.get("nodes") if isinstance(plan, dict) else None
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 8:
            raise ValueError("plan requires 1..8 nodes")
        specs = []
        for node in nodes:
            if not isinstance(node, dict) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", str(node.get("id", ""))):
                raise ValueError("plan requires bounded node identifiers")
            paths = node.get("write_paths")
            deps = node.get("depends_on")
            if (not isinstance(paths, list) or not paths or len(paths) != len(set(paths))
                    or not set(paths) <= set(allowed) or not isinstance(deps, list)
                    or not all(isinstance(x, str) for x in deps)
                    or not isinstance(node.get("objective"), str) or not node["objective"].strip()
                    or len(node["objective"]) > 4000):
                raise ValueError("node assignment exceeds authorized paths or lacks a valid objective/dependencies")
            specs.append(SubagentRoleSpec(node["id"], "worker", node["objective"], depends_on=deps))
        from .autonomous_subagent_service import AutonomousSubagentService
        AutonomousSubagentService._validate_roles(specs)
        return nodes

    def save(self, state):
        state["updated_at"] = now_iso()
        payload = {"state": state, "sha256": self.digest(state)}
        write_text(self.root / state["run_id"] / "checkpoint.json",
                   json.dumps(payload, ensure_ascii=False, indent=2))

    def event(self, state, kind, **fields):
        state["events"].append({"event": kind, "timestamp": now_iso(), "wall_time_ns": time.time_ns(), **fields})
        self.save(state)

    def owned_workspace(self, state, metadata):
        workspace = Path(metadata["workspace"]).resolve()
        workspace.relative_to(self.root / state["run_id"] / "workspaces")
        disk = json.loads((workspace.parent / "workspace.json").read_text(encoding="utf-8"))
        if disk != metadata or not disk.get("isolated"):
            raise ValueError("workspace identity changed")
        return workspace

    def verify_commit(self, state, record):
        repo = self.owned_workspace(state, record["workspace"])
        commit = record["commit"]
        if self.git(repo, "rev-parse", "HEAD").stdout.strip() != commit:
            raise ValueError("completed worker HEAD changed")
        if self.git(repo, "status", "--porcelain").stdout.strip():
            raise ValueError("completed worker workspace changed")
        actual = self.git(repo, "show", "--format=", "--binary", commit).stdout
        if self.digest(actual) != record["patch_digest"]:
            raise ValueError("completed worker patch evidence changed")

    def provider_signature(self, provider):
        return self.digest({"class": type(provider).__module__ + "." + type(provider).__qualname__,
            "provider": getattr(provider, "name", ""), "model": getattr(provider, "model", ""),
            "endpoint": getattr(provider, "base_url", ""),
            "template": getattr(provider, "chat_template_kwargs", None)})

    def load(self, run_id):
        if not re.fullmatch(r"collab-[a-f0-9]{32}", run_id):
            raise ValueError("invalid collaboration run identity")
        try:
            envelope=json.loads((self.root/run_id/"checkpoint.json").read_text(encoding="utf-8"))
            state=envelope["state"]
            required={"run_id","request","baseline","source_stamp","status","nodes","results","attempts","events",
                      "ledger","integration","integration_history","review","provider_specs"}
            if not required <= set(state) or envelope["sha256"] != self.digest(state) or state["run_id"] != run_id:
                raise ValueError("checkpoint integrity check failed")
            return state
        except (OSError,KeyError,TypeError,ValueError) as exc:
            raise ValueError("checkpoint unreadable, incomplete or changed") from exc

    def inspect(self, run_id):
        state=self.load(run_id)
        owner_active=False
        try:
            with _file_lock(self.root/run_id/"coordinator",timeout=0):
                pass
        except TimeoutError:
            owner_active=True
        return self.public(state) | {"coordinator_active":owner_active,
            "needs_recovery":not owner_active and state["status"] in {"running","interrupted"}}

    def verify_receipts(self,state):
        root=self.root/state["run_id"]
        for event in state["events"]:
            if event["event"]!="model_receipt":
                continue
            try:
                path=(root/event["receipt"]).resolve()
                path.relative_to(root/"receipts")
                captured=json.loads(path.read_text(encoding="utf-8"))
                if (captured["role"]!=event["role"] or
                        self.digest(captured["content"])!=event["content_digest"] or
                        captured["content_digest"]!=event["content_digest"]):
                    raise ValueError("model receipt changed")
            except (ValueError,KeyError,OSError,TypeError) as exc:
                raise ValueError("model receipt missing or changed; recovery rejected") from exc

    async def run(self, repo_path, objective, *, allowed_paths, test_commands,
                  confirmed=False, resume_run="", actor="coordinator", limits=None):
        if confirmed is not True:
            raise PermissionError("confirmed=true is required for isolated edits and caller-selected tests")
        if (not isinstance(allowed_paths, list) or not all(isinstance(p, str) for p in allowed_paths)
                or not isinstance(test_commands, list) or not all(isinstance(c, list) and
                    all(isinstance(x, str) for x in c) for c in test_commands)
                or not isinstance(objective, str) or not isinstance(actor, str)
                or (limits is not None and not isinstance(limits, dict))):
            raise ValueError("invalid collaboration request types")
        repo = CodingWorkspaceService._repo(repo_path)
        paths = sorted({self.safe_path(p) for p in allowed_paths})
        if not 1 <= len(paths) <= 24 or not str(objective).strip() or len(objective) > 8000:
            raise ValueError("a bounded objective and 1..24 authorized paths are required")
        commands = [CodingWorkflowService._validate_command(c) for c in test_commands]
        if not commands or len(commands) > 5:
            raise ValueError("1..5 caller-selected test commands are required")
        policy = {"max_model_calls": 24, "max_tokens": 32000,
                  "timeout_seconds": 120, "max_wall_seconds": 900,
                  "max_attempts": 3, **(limits or {})}
        bounds = {"max_model_calls": (1, 48), "max_tokens": (500, 100000),
                  "timeout_seconds": (1, 600), "max_wall_seconds": (1, 3600),
                  "max_attempts": (1, 3)}
        if set(policy) != set(bounds) or any(type(policy[k]) is not int or not lo <= policy[k] <= hi
                                            for k, (lo, hi) in bounds.items()):
            raise ValueError("invalid collaboration limits")
        request = dict(repo=str(repo), objective=objective, paths=paths,
                       test_commands=commands, actor=actor, limits=policy)
        if resume_run and not re.fullmatch(r"collab-[a-f0-9]{32}", resume_run):
            raise ValueError("invalid collaboration run identity")
        run_id = resume_run or "collab-" + uuid.uuid4().hex
        folder = self.root / run_id
        if resume_run and not folder.is_dir():
            raise ValueError("collaboration run does not exist")
        folder.mkdir(parents=True, exist_ok=True)
        # Nonblocking acquisition: a running coordinator cannot be replaced.
        with _file_lock(folder / "coordinator", timeout=0):
            if resume_run:
                state = self.load(run_id)
                if state["request"] != request:
                    raise ValueError("checkpoint or frozen request changed")
                if await asyncio.to_thread(self.source_stamp,repo,paths) != state["source_stamp"]:
                    raise ValueError("source checkout changed; inspect the frozen task before starting a new run")
                await asyncio.to_thread(self.verify_receipts,state)
                if state["run_id"] != run_id:
                    raise ValueError("checkpoint run identity changed")
                for binding in state["provider_specs"].values():
                    provider = self.factory(SubagentRoleSpec(**binding["spec"]))
                    if self.provider_signature(provider) != binding["fingerprint"]:
                        raise ValueError("frozen provider configuration changed")
                if state.get("active_since"):
                    state["ledger"]["elapsed_seconds"] += max(0, time.time() - state.pop("active_since"))
                for attempts in state["attempts"].values():
                    for attempt in attempts:
                        if attempt["status"] == "running":
                            attempt.update(status="interrupted", error="previous coordinator exited before completion")
                for item in state["results"].values():
                    if item["status"] == "passed":
                        await asyncio.to_thread(self.verify_commit, state, item)
                if state["status"] == "passed":
                    await asyncio.to_thread(self.verify_commit, state, state["integration"])
                    return self.public(state)
                self.event(state, "coordinator_recovered")
            else:
                # Capture once. All workers derive from the same immutable baseline.
                source_stamp=await asyncio.to_thread(self.source_stamp,repo,paths)
                baseline = await asyncio.to_thread(self.workspaces.create_task, repo,
                    folder / "workspaces", "baseline", confirmed=True)
                if await asyncio.to_thread(self.source_stamp,repo,paths) != source_stamp:
                    raise ValueError("source checkout changed during baseline capture")
                state = dict(schema="clawos.reliable-collaboration.v1", run_id=run_id,
                    request=request, baseline=baseline, source_stamp=source_stamp, status="running", nodes=[],
                    results={}, attempts={}, events=[], integration_history=[], provider_specs={}, ledger={"model_calls": 0, "tokens": 0,
                    "reserved_tokens": 0, "elapsed_seconds": 0}, integration={}, review={})
                self.event(state, "baseline_captured", source_head=baseline["source_head"])
            started = time.monotonic()
            state["active_since"] = time.time()
            self.save(state)
            remaining = policy["max_wall_seconds"] - state["ledger"]["elapsed_seconds"]
            try:
                if remaining <= 0:
                    raise TimeoutError("cumulative run wall budget exhausted")
                await asyncio.wait_for(self.execute(state), timeout=remaining)
                state["source_preserved"] = await asyncio.to_thread(self.source_stamp,repo,paths)==state["source_stamp"]
                if not state["source_preserved"]:
                    state["status"]="source_changed"
                    self.event(state,"source_changed_during_run")
            except asyncio.CancelledError:
                state["status"] = "interrupted"
                self.event(state, "coordinator_cancelled")
                raise
            except Exception as exc:
                state["status"] = "failed"
                self.event(state, "coordinator_failed", error=f"{type(exc).__name__}: {exc}")
            finally:
                state.pop("active_since", None)
                state["ledger"]["elapsed_seconds"] += round(time.monotonic() - started, 3)
                self.save(state)
            result = self.public(state)
            if self.store:
                run = RunRecord(run_id=run_id, run_type="autonomous_subagents", title=objective,
                    status=state["status"], actor=actor, scenario="project", completed_at=now_iso(),
                    inputs={"plan": state["nodes"]}, outputs={"collaboration": result},
                    metrics=state["ledger"], workflow={"scheduler": "model_planned_dag"})
                self.store.save_run_record(run.to_dict())
            return result

    async def model(self, state, role, instruction, packet):
        policy = state["request"]["limits"]
        messages = [{"role": "system", "content": instruction +
                    " Return exactly one JSON object. Never claim unexecuted tests passed."},
                    {"role": "user", "content": json.dumps(packet, ensure_ascii=False)}]
        ledger = state["ledger"]
        reserve = len(messages[1]["content"]) + 1800  # Conservative admission; no unknown free usage.
        if (ledger["model_calls"] >= policy["max_model_calls"] or
                ledger["tokens"] + ledger["reserved_tokens"] + reserve > policy["max_tokens"]):
            raise RuntimeError("shared model/token budget exhausted")
        ledger["model_calls"] += 1
        ledger["reserved_tokens"] += reserve
        self.event(state, "model_started", role=role, prompt_digest=self.digest(messages))
        started = time.monotonic()
        accounted = False
        try:
            spec = SubagentRoleSpec(role, instruction, state["request"]["objective"])
            provider = self.factory(spec)
            fingerprint = self.provider_signature(provider)
            prior = state["provider_specs"].get(role)
            if prior and prior["fingerprint"] != fingerprint:
                raise ValueError("frozen provider configuration changed")
            state["provider_specs"].setdefault(role, {"spec": asdict(spec), "fingerprint": fingerprint})
            self.save(state)
            response = await asyncio.wait_for(provider.complete(messages,
                {"temperature": 0, "max_tokens": 1800, "response_format": {"type": "json_object"}}),
                timeout=policy["timeout_seconds"])
            tokens = int((response.get("usage") or {}).get("total_tokens") or reserve)
            if tokens < 0:
                raise ValueError("invalid provider usage")
            ledger["tokens"] += tokens
            accounted = True
            choices = (response.get("raw") or {}).get("choices") or [{}]
            if not response.get("ok") or choices[0].get("finish_reason") in {"length", "content_filter"}:
                raise RuntimeError(response.get("error") or "provider answer incomplete")
            content = str(response.get("content") or "").strip()
            receipt = self.root / state["run_id"] / "receipts" / (role + "-" + uuid.uuid4().hex + ".json")
            captured={"role":role,"content":content,"prompt_digest":self.digest(messages),
                      "content_digest":self.digest(content)}
            # Freeze the normalized public answer once, including malformed JSON.
            write_text(receipt,json.dumps(captured,ensure_ascii=False),create_only=True)
            self.event(state, "model_receipt", role=role, provider=response.get("provider"),
                model=response.get("model"), content_digest=self.digest(content), content_chars=len(content),
                receipt=str(receipt.relative_to(self.root / state["run_id"])),
                tokens=tokens, finish_reason=choices[0].get("finish_reason"))
            # Accept a single JSON code fence, never JSON embedded in arbitrary prose.
            fence = re.fullmatch(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", content)
            if fence:
                content = fence.group(1)
            output = json.loads(content)
            if not isinstance(output, dict) or ledger["tokens"] > policy["max_tokens"]:
                raise ValueError("invalid JSON object or provider exceeded token budget")
            self.event(state, "model_completed", role=role, provider=response.get("provider"),
                model=response.get("model"), output_digest=self.digest(output), tokens=tokens,
                receipt=str(receipt.relative_to(self.root / state["run_id"])),
                duration_ms=round((time.monotonic()-started)*1000, 2))
            return output
        finally:
            if not accounted:
                ledger["tokens"] += reserve
            ledger["reserved_tokens"] -= reserve
            self.save(state)

    async def execute(self, state):
        # Reservations left by a dead process stay charged conservatively on recovery.
        if state["ledger"]["reserved_tokens"]:
            state["ledger"]["tokens"] += state["ledger"]["reserved_tokens"]
            state["ledger"]["reserved_tokens"] = 0
        base = self.owned_workspace(state, state["baseline"])
        if self.git(base, "status", "--porcelain").stdout.strip() or self.git(base, "rev-parse", "HEAD").stdout.strip() != state["baseline"]["baseline_commit"]:
            raise ValueError("frozen baseline changed")
        files = self.read_files(base, state["request"]["paths"])
        if not state["nodes"]:
            instruction = (
                'Split the objective into minimal concrete edit tasks. Independent tasks have no dependencies. '
                'Use schema {"nodes":[{"id":"task_id","objective":"specific requirement",'
                '"write_paths":["authorized/path"],"depends_on":[]}]}. '
                'Assign only supplied paths. Use dependencies when a task needs another task\'s implementation.')
            packet = {"objective": state["request"]["objective"], "authorized_files": files}
            for attempt in range(2):
                try:
                    plan = await self.model(state, "planner", instruction, packet)
                    state["nodes"] = self.validate_plan(plan, state["request"]["paths"])
                    break
                except (ValueError, RuntimeError) as exc:
                    self.event(state, "plan_rejected", attempt=attempt+1, error=str(exc))
                    if attempt:
                        raise
                    packet["previous_failure"] = str(exc)
            self.event(state, "plan_frozen", plan_digest=self.digest(state["nodes"]))
        else:
            self.validate_plan({"nodes": state["nodes"]}, state["request"]["paths"])
        pending = {n["id"]: n for n in state["nodes"]
                   if state["results"].get(n["id"], {}).get("status") != "passed"}
        semaphore = asyncio.Semaphore(self.concurrency)
        while pending:
            ready = [n for n in pending.values() if all(
                state["results"].get(d, {}).get("status") == "passed" for d in n["depends_on"])]
            if not ready:
                self.event(state, "dependency_blocked", nodes=sorted(pending))
                state["status"] = "failed"
                return
            async def launch(node):
                async with semaphore:
                    await self.worker(state, node)
            tasks = [asyncio.create_task(launch(n)) for n in ready]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            for node in ready:
                pending.pop(node["id"])
        if any(state["results"].get(n["id"], {}).get("status") != "passed" for n in state["nodes"]):
            state["status"] = "failed"
            return
        await self.integrate(state)

    def ancestors(self, state, node):
        wanted = set(node["depends_on"])
        for _ in state["nodes"]:
            wanted.update(d for n in state["nodes"] if n["id"] in wanted for d in n["depends_on"])
        return [n for n in self.ordered(state) if n["id"] in wanted]

    @staticmethod
    def ordered(state):
        pending = {n["id"]: n for n in state["nodes"]}
        result = []
        while pending:
            ready = sorted(k for k, n in pending.items() if set(n["depends_on"]) <= {x["id"] for x in result})
            if not ready:
                raise ValueError("invalid DAG")
            for key in ready:
                result.append(pending.pop(key))
        return result

    def pick(self, repo, commit):
        result = self.git(repo, "-c", "user.name=ClawOS Coordinator", "-c",
                          "user.email=collaboration@clawos.local", "cherry-pick", commit, check=False)
        if result.returncode:
            conflicts = self.git(repo, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
            if not conflicts and not self.git(repo,"diff","HEAD").stdout.strip():
                changed=self.git(repo,"diff-tree","--no-commit-id","--name-only","-r",commit).stdout.splitlines()
                if changed and all(self.git(repo,"show",commit+":"+path).stdout==
                    (Path(repo)/path).read_text(encoding="utf-8") for path in changed):
                    # Both workers independently produced the same change.
                    # Git correctly sees an empty pick; reuse it without a conflict.
                    self.git(repo,"cherry-pick","--skip")
                    return []
            self.git(repo, "cherry-pick", "--abort")
            return conflicts or ["integration could not apply commit"]
        return []

    async def worker(self, state, node):
        key = node["id"]
        attempts = state["attempts"].setdefault(key, [])
        limit = state["request"]["limits"]["max_attempts"]
        feedback = attempts[-1].get("error", "") if attempts else ""
        while len(attempts) < limit:
            record = {"number": len(attempts)+1, "status": "running", "started_at": now_iso()}
            attempts.append(record)
            self.event(state, "worker_started", node=key, attempt=record["number"])
            try:
                meta = await asyncio.to_thread(self.workspaces.create_task,
                    state["baseline"]["workspace"], self.root / state["run_id"] / "workspaces",
                    key, confirmed=True)
                record["workspace"] = meta
                self.save(state)
                repo = self.owned_workspace(state, meta)
                for dep in self.ancestors(state, node):
                    conflicts = await asyncio.to_thread(self.pick, repo, state["results"][dep["id"]]["commit"])
                    if conflicts:
                        raise ValueError("dependency patch conflict: " + ", ".join(conflicts))
                patch = await self.model(state, key,
                    'You are ONE worker, not the project coordinator. Other workers implement the other tasks. '
                    'Implement ONLY the supplied assignment and write_paths. Dependency files are READ ONLY. Return '
                    '{"summary":"what changed","changes":[{"path":"authorized/path",'
                    '"operation":"replace","old_text":"exact unique text", "new_text":"replacement"}]}. '
                    'Use operation=create with content for a missing file. Never overwrite a whole existing file.',
                    {"assignment": node["objective"], "write_paths": node["write_paths"],
                     "files": self.read_files(repo, sorted(set(node["write_paths"]) | {
                         p for dep in self.ancestors(state,node) for p in dep["write_paths"]})),
                     "dependency_commits": {n["id"]: state["results"][n["id"]]["commit"] for n in self.ancestors(state,node)},
                     "previous_failure": feedback})
                changes = patch.get("changes")
                if not isinstance(changes, list) or not changes or len(changes) > 24:
                    raise ValueError("worker must provide nonempty bounded edits")
                if any(not isinstance(c, dict) or c.get("path") not in node["write_paths"]
                       or c.get("operation") not in {"replace", "create", "hunks"} for c in changes):
                    raise ValueError("invalid edit path/operation; authorized paths=" + json.dumps(node["write_paths"]) +
                        "; received=" + json.dumps([{k:c.get(k) for k in ("path","operation")} if isinstance(c,dict) else str(type(c)) for c in changes]) +
                        "; each change requires path, operation=replace, old_text and new_text")
                accepted = await asyncio.to_thread(self.apply_proposal, repo, patch, node["write_paths"], key)
                commit = accepted["commit"]
                record.update(status="passed", commit=commit, completed_at=now_iso())
                state["results"][key] = dict(status="passed", commit=commit, workspace=meta,
                    changed_paths=accepted["changed_paths"], summary=str(patch.get("summary", "")),
                    patch_digest=accepted["patch_digest"])
                self.event(state, "worker_completed", node=key, commit=commit)
                return
            except asyncio.CancelledError:
                record.update(status="interrupted", error="coordinator interrupted")
                self.save(state)
                raise
            except Exception as exc:
                feedback = f"{type(exc).__name__}: {exc}"
                record.update(status="failed", error=feedback, completed_at=now_iso())
                self.event(state, "worker_failed", node=key, attempt=record["number"], error=feedback)
        state["results"][key] = {"status": "failed", "error": feedback}
        self.save(state)

    async def integrate(self, state):
        if state["integration"]:
            state["integration_history"].append(state["integration"])
        meta = await asyncio.to_thread(self.workspaces.create_task, state["baseline"]["workspace"],
            self.root / state["run_id"] / "workspaces", "integration", confirmed=True)
        repo = self.owned_workspace(state, meta)
        state["integration"] = {"status": "running", "workspace": meta}
        self.event(state, "integration_started")
        conflicts = []
        for node in self.ordered(state):
            paths = await asyncio.to_thread(self.pick, repo, state["results"][node["id"]]["commit"])
            if paths:
                conflict = {"node": node["id"], "paths": paths,
                            "worker_commit": state["results"][node["id"]]["commit"]}
                self.event(state, "integration_conflict_detected", **conflict)
                # Aborted cherry-pick leaves ours clean. Resolve only genuine
                # conflicting paths; unrelated/unknown Git failures stay blocked.
                if not set(paths) <= set(node["write_paths"]):
                    conflicts.append(conflict)
                    break
                try:
                    proposal = await self.model(state, "conflict_resolver",
                        'Resolve the supplied three-way conflict preserving BOTH assignments. '
                        'Return {"summary":"resolution","changes":[{"path":"conflicting/path",'
                        '"operation":"replace","old_text":"exact current text","new_text":"merged text"}]}. '
                        'The current integrated files are ours; do not discard either requirement.',
                        {"objective": state["request"]["objective"], "plan": state["nodes"],
                         "base": self.read_files(state["baseline"]["workspace"], paths),
                         "ours": self.read_files(repo, paths),
                         "theirs": self.read_files(state["results"][node["id"]]["workspace"]["workspace"], paths)})
                    await asyncio.to_thread(self.apply_proposal, repo, proposal, paths, "conflict resolution")
                    conflict["resolution_digest"] = self.digest(proposal)
                    state["integration"].setdefault("resolutions", []).append(conflict)
                    self.event(state, "conflict_resolved", **conflict)
                except Exception as exc:
                    conflict["error"] = f"{type(exc).__name__}: {exc}"
                    conflicts.append(conflict)
                    break
        if conflicts:
            state["status"] = "conflict"
            state["integration"].update(status="conflict", conflicts=conflicts)
            self.event(state, "integration_conflict", conflicts=conflicts)
            return
        tests = []
        for round_no in range(3):
            tests = []
            for command in state["request"]["test_commands"]:
                result = await asyncio.to_thread(CodingWorkflowService._run_command, repo, command,
                                                state["request"]["limits"]["timeout_seconds"])
                tests.append(result)
                self.event(state, "integration_test", round=round_no, exit_code=result["exit_code"], command=command)
            state["integration"].setdefault("test_rounds", []).append({"round": round_no, "tests": tests})
            self.save(state)
            if all(t["exit_code"] == 0 for t in tests) or round_no == 2:
                break
            try:
                proposal = await self.model(state, "repairer",
                    'Repair the actual integrated test failure without changing the caller-selected tests. '
                    'Return {"summary":"repair","changes":[{"path":"authorized/path",'
                    '"operation":"replace","old_text":"exact current text","new_text":"correct text"}]}.',
                    {"objective": state["request"]["objective"],
                     "files": self.read_files(repo, state["request"]["paths"]),
                     "tests": [{k: t.get(k) for k in ("command","exit_code","stdout","stderr")} for t in tests]})
                await asyncio.to_thread(self.apply_proposal, repo, proposal, state["request"]["paths"], "integrated repair")
                self.event(state, "integrated_repair", round=round_no, patch_digest=self.digest(proposal))
            except Exception as exc:
                self.event(state, "integrated_repair_failed", error=f"{type(exc).__name__}: {exc}")
                break
        diff = self.git(repo, "diff", "--binary", state["baseline"]["baseline_commit"]).stdout
        state["integration"].update(tests=tests, diff_digest=self.digest(diff))
        if any(t["exit_code"] != 0 for t in tests):
            state["status"] = "test_failed"
            state["integration"]["status"] = "test_failed"
            self.save(state)
            return
        instruction = (
            'Independently review the objective, complete integrated files, patch and actual test evidence. '
            'Return {"approved":true,"reasons":["specific evidence"],"risks":[]}. '
            'Reject missing requirements even when tests pass. Your review cannot override failed tests or conflicts. '
            'Keep reasons to two short strings; provide no prose outside JSON.')
        packet = {"objective": state["request"]["objective"], "plan": state["nodes"],
             "files": self.read_files(repo, state["request"]["paths"]), "diff": diff,
             "tests": [{k: t.get(k) for k in ("command","exit_code","stdout","stderr")} for t in tests]}
        for attempt in range(2):
            try:
                review = await self.model(state, "reviewer", instruction, packet)
                if (type(review.get("approved")) is not bool or
                    any(not isinstance(review.get(k),list) or not all(isinstance(v,str) for v in review[k])
                        for k in ("reasons","risks"))):
                    raise ValueError("review requires approved boolean and reasons/risks string arrays")
                break
            except (ValueError,RuntimeError) as exc:
                self.event(state,"review_format_rejected",attempt=attempt+1,error=str(exc))
                if attempt:
                    raise
                packet["previous_failure"]=str(exc)
        state["review"] = review
        approved = (review.get("approved") is True and isinstance(review.get("reasons"), list)
                    and any(r.strip() for r in review["reasons"]) and isinstance(review.get("risks"), list) and not review["risks"])
        state["status"] = "passed" if approved else "review_rejected"
        commit = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        state["integration"].update(status=state["status"], commit=commit,
            patch_digest=self.digest(self.git(repo, "show", "--format=", "--binary", commit).stdout))
        self.event(state, "review_completed", approved=approved,
                   integrated_diff_digest=state["integration"]["diff_digest"])

    def apply_proposal(self, repo, proposal, allowed, message):
        changes = proposal.get("changes")
        if not isinstance(changes, list) or not changes or len(changes) > 24 or any(
            not isinstance(c, dict) or c.get("path") not in allowed or
            c.get("operation") not in {"replace", "create", "hunks"} for c in changes):
            raise ValueError("resolution exceeds its write scope")
        normalized = self.workflow._normalize_changes(repo, changes)
        for item in normalized:
            if len(item["content"].encode()) > 128000:
                raise ValueError("resolution too large")
            if item["path"].endswith(".py"):
                compile(item["content"], item["path"], "exec")
        CodingWorkflowService._apply_changes(repo, normalized)
        self.git(repo, "add", "--", *[c["path"] for c in normalized])
        self.git(repo, "-c", "user.name=ClawOS Coordinator", "-c", "user.email=collaboration@clawos.local",
                 "commit", "-m", "collaboration: " + message)
        commit = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        return {"commit": commit, "changed_paths": sorted(c["path"] for c in normalized),
                "patch_digest": self.digest(self.git(repo, "show", "--format=", "--binary", commit).stdout)}

    def public(self, state):
        return {k: state[k] for k in ("schema", "run_id", "status", "nodes", "results", "attempts",
                                     "events", "ledger", "integration", "integration_history", "review")} | {
            "checkpoint": str(self.root / state["run_id"] / "checkpoint.json"),
            "source_mutated": None if "source_preserved" not in state else not state["source_preserved"],
            "source_verification":"tracked Git state and authorized files", "human_release_required": True,
            "recovery": "process-lock-and-verified-commits",
            "model_quality_proven": False}
