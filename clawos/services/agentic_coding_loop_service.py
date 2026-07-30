"""Iterative observe -> act -> edit -> test -> review coding agent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .coding_context_service import CodingContextService
from .coding_trace_service import CodingTraceService
from .coding_workflow_service import CodingWorkflowService
from .execution_governance import GovernedExecutionContext


class AgenticCodingLoopService:
    """A bounded tool-using loop; the model proposes one action per turn."""

    ACTIONS = {"search", "read", "symbols", "propose_patch", "finish"}

    def __init__(
        self,
        provider: Any,
        *,
        workflow: CodingWorkflowService | None = None,
        context: CodingContextService | None = None,
        trace: CodingTraceService | None = None,
    ):
        self.provider = provider
        self.workflow = workflow or CodingWorkflowService()
        self.context = context or CodingContextService()
        self.trace = trace or CodingTraceService()

    async def run(
        self,
        repo_path: str | Path,
        objective: str,
        *,
        confirmed: bool = False,
        task_id: str,
        session_id: str,
        actor_id: str = "local-user",
        focus_paths: list[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        max_turns: int = 8,
        timeout_seconds: int = 180,
        governance: GovernedExecutionContext | None = None,
    ) -> dict[str, Any]:
        if not str(task_id).strip() or not str(session_id).strip():
            raise ValueError("task_id and session_id are required")
        repo = Path(repo_path).expanduser().resolve()
        if not repo.is_dir():
            raise ValueError("repository does not exist")
        governed = governance or GovernedExecutionContext.local(
            actor_id=actor_id, workspace_id=str(repo)
        )
        run = self.trace.start(
            objective=objective, repo_path=repo, task_id=task_id,
            session_id=session_id, actor_id=actor_id,
        )
        governed.gate("before_context", {
            "task_id": task_id, "session_id": session_id, "repo": str(repo),
        })
        manifest = self.context.build(
            repo, objective, focus_paths=focus_paths, diagnostics=diagnostics
        )
        governed.gate("after_context", {
            "task_id": task_id, "context_digest": manifest["context_digest"],
        })
        self.trace.step(
            run["id"], "context", status="observed",
            output_value=manifest["context_digest"],
            metadata={"task_id": task_id, "session_id": session_id},
        )
        observations: list[dict[str, Any]] = [{
            "type": "repository_context",
            "digest": manifest["context_digest"],
            "repo_map": manifest.get("repo_map"),
            "ranked_files": [
                item.get("path") for item in (manifest.get("code_evidence") or [])[:30]
            ],
            "diagnostics": manifest.get("diagnostics") or [],
        }]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an iterative coding agent. Return exactly one JSON "
                    "action per turn. Allowed actions: search {query,glob}, read "
                    "{path,start_line,end_line}, symbols {path}, propose_patch "
                    "{changes,test_commands,explanation}, finish {summary}. "
                    "Use repository-relative paths. Observe before editing. Never "
                    "claim tests passed unless tool evidence says so."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "objective": objective,
                    "initial_observation": observations[0],
                }, ensure_ascii=False),
            },
        ]
        attempts: list[dict[str, Any]] = []
        for turn in range(1, max(2, min(int(max_turns), 20)) + 1):
            governed.budget.consume(model_calls=1)
            governed.gate("before_model", {"task_id": task_id, "turn": turn})
            response = await self.provider.complete(
                messages, {"temperature": 0.0, "max_tokens": 4000}
            )
            if not response.get("ok"):
                return self._fail(
                    run["id"], attempts, observations,
                    response.get("error") or "model action failed",
                    governed,
                )
            content = str(response.get("content") or "").strip()
            governed.budget.consume(
                tokens=int((response.get("usage") or {}).get("total_tokens") or 0)
            )
            governed.gate("after_model", {
                "task_id": task_id, "turn": turn,
                "response_digest": hashlib.sha256(content.encode()).hexdigest(),
            })
            try:
                action = self._parse_action(content)
            except ValueError as exc:
                self.trace.step(
                    run["id"], "failure", status="recoverable",
                    output_value={"error": str(exc)},
                    metadata={"turn": turn, "phase": "parse_action"},
                )
                messages.extend([
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": json.dumps({
                        "error": str(exc),
                        "instruction": "Return one valid JSON action.",
                    })},
                ])
                continue
            action_name = action["action"]
            self.trace.step(
                run["id"], "model", status="selected_action",
                input_value={"turn": turn, "observation_count": len(observations)},
                output_value=action,
                behavior_propensity=1.0,
                metadata={
                    "turn": turn, "action": action_name,
                    "policy": "deterministic-model-action",
                    "learned_propensity": False,
                },
            )
            if action_name in {"search", "read", "symbols"}:
                governed.budget.consume(tool_calls=1)
                governed.gate("before_tool", {
                    "task_id": task_id, "tool": action_name, "turn": turn,
                })
                try:
                    observation = self._observe(repo, manifest, action)
                except (OSError, ValueError) as exc:
                    observation = {
                        "type": "tool_error", "tool": action_name,
                        "error": str(exc),
                    }
                governed.gate("after_tool", {
                    "task_id": task_id, "tool": action_name,
                    "turn": turn, "ok": observation["type"] != "tool_error",
                })
                self.trace.step(
                    run["id"], "tool",
                    status=(
                        "failed" if observation["type"] == "tool_error" else "passed"
                    ),
                    input_value=action, output_value=observation,
                    metadata={"turn": turn, "tool": action_name},
                )
                observations.append(observation)
                messages.extend([
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": json.dumps(
                        {"observation": observation}, ensure_ascii=False
                    )},
                ])
                continue
            if action_name == "finish":
                if not attempts or attempts[-1].get("status") != "passed":
                    messages.extend([
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": json.dumps({
                            "error": "finish requires a passed patch and test evidence"
                        })},
                    ])
                    continue
                self.trace.step(
                    run["id"], "review", status="human_required",
                    output_value=action,
                )
                self.trace.finish(run["id"], "passed")
                return {
                    "schema": "clawos.agentic-coding-run.v1",
                    "status": "passed",
                    "trajectory_id": run["id"],
                    "turns": turn,
                    "attempts": attempts,
                    "observations": observations,
                    "summary": str(action.get("summary") or ""),
                    "human_review_required": True,
                    "commit_created": False,
                    "online_rl_claimed": False,
                }
            proposal = {
                "changes": action.get("changes") or [],
                "test_commands": action.get("test_commands") or [],
                "explanation": str(action.get("explanation") or ""),
            }
            plan = self.workflow.plan(
                repo, objective, proposal["changes"], proposal["test_commands"]
            )
            if not confirmed:
                self.trace.finish(run["id"], "waiting_confirmation")
                return {
                    "schema": "clawos.agentic-coding-run.v1",
                    "status": "waiting_confirmation",
                    "trajectory_id": run["id"],
                    "plan": plan,
                    "proposal": proposal,
                    "observations": observations,
                    "requires_confirmation": True,
                }
            governed.gate("before_write", {
                "task_id": task_id, "turn": turn,
                "paths": [item.get("path") for item in proposal["changes"]],
            })
            governed.budget.consume(
                tool_calls=1 + len(proposal["test_commands"])
            )
            result = self.workflow.execute(
                repo, objective, proposal["changes"], proposal["test_commands"],
                confirmed=True, max_rounds=1, timeout_seconds=timeout_seconds,
                actor=actor_id,
            )
            governed.gate("after_write", {
                "task_id": task_id, "turn": turn, "status": result["status"],
            })
            attempt = {
                "turn": turn, "status": result["status"],
                "proposal_digest": hashlib.sha256(content.encode()).hexdigest(),
                "workflow": result,
            }
            attempts.append(attempt)
            self.trace.step(
                run["id"], "edit", status=result["status"],
                input_value=proposal["changes"], output_value=result.get("rounds"),
                metadata={"turn": turn},
            )
            for test in (
                item for round_item in result.get("rounds") or []
                for item in round_item.get("tests") or []
            ):
                self.trace.step(
                    run["id"], "test",
                    status="passed" if test.get("exit_code") == 0 else "failed",
                    input_value=test.get("command"), output_value=test,
                    metadata={"turn": turn},
                )
            observation = {
                "type": "patch_result", "turn": turn,
                "status": result["status"], "failure": result.get("failure"),
                "rounds": result.get("rounds") or [],
            }
            observations.append(observation)
            messages.extend([
                {"role": "assistant", "content": content},
                {"role": "user", "content": json.dumps(
                    {"observation": observation}, ensure_ascii=False
                )[:16_000]},
            ])
        return self._fail(
            run["id"], attempts, observations, "agentic turn budget exhausted",
            governed,
        )

    def _observe(
        self, repo: Path, manifest: dict[str, Any], action: dict[str, Any]
    ) -> dict[str, Any]:
        name = action["action"]
        if name == "search":
            query = str(action.get("query") or "").lower()
            glob = str(action.get("glob") or "*")
            matches = []
            for path in repo.rglob(glob):
                if not path.is_file() or ".git" in path.parts:
                    continue
                rel = path.relative_to(repo).as_posix()
                try:
                    for number, line in enumerate(
                        path.read_text(encoding="utf-8", errors="replace").splitlines(),
                        1,
                    ):
                        if query in line.lower():
                            matches.append({
                                "path": rel, "line": number, "text": line[:400],
                            })
                            if len(matches) >= 100:
                                break
                except OSError:
                    continue
                if len(matches) >= 100:
                    break
            return {"type": "search", "query": query, "matches": matches}
        rel = str(action.get("path") or "").replace("\\", "/").strip("/")
        path = (repo / rel).resolve()
        try:
            path.relative_to(repo)
        except ValueError as exc:
            raise ValueError("observation path escapes repository") from exc
        if name == "read":
            if not path.is_file():
                raise ValueError("read path does not exist")
            lines = path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            start = max(1, int(action.get("start_line") or 1))
            end = min(len(lines), max(start, int(action.get("end_line") or start + 199)))
            return {
                "type": "read", "path": rel, "start_line": start,
                "end_line": end, "content": "\n".join(lines[start - 1:end]),
            }
        symbols = []
        for item in (manifest.get("repo_map") or {}).get("files") or []:
            if item.get("path") == rel:
                symbols = item.get("symbols") or []
                break
        return {"type": "symbols", "path": rel, "symbols": symbols}

    @classmethod
    def _parse_action(cls, content: str) -> dict[str, Any]:
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("model response is not a strict JSON action") from exc
        if not isinstance(value, dict):
            raise ValueError("model action must be an object")
        if "action" not in value and value.get("changes"):
            value = {**value, "action": "propose_patch"}
        action = str(value.get("action") or "")
        if action not in cls.ACTIONS:
            raise ValueError(f"unsupported agentic coding action: {action}")
        if action == "propose_patch" and (
            not isinstance(value.get("changes"), list)
            or not isinstance(value.get("test_commands"), list)
            or not value.get("changes") or not value.get("test_commands")
        ):
            raise ValueError("propose_patch requires changes and test_commands")
        return value

    def _fail(
        self, run_id: str, attempts: list[dict[str, Any]],
        observations: list[dict[str, Any]], error: str,
        governance: GovernedExecutionContext,
    ) -> dict[str, Any]:
        try:
            governance.gate("on_failure", {"error": error})
        except PermissionError:
            pass
        self.trace.step(
            run_id, "failure", status="failed", output_value={"error": error}
        )
        self.trace.finish(run_id, "failed")
        return {
            "schema": "clawos.agentic-coding-run.v1",
            "status": "failed", "trajectory_id": run_id,
            "attempts": attempts, "observations": observations,
            "error": error, "online_rl_claimed": False,
        }
