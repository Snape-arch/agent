"""Bounded model-propose -> patch -> test -> repair coding loop."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .coding_context_service import CodingContextService
from .coding_workflow_service import CodingWorkflowService
from .execution_governance import ExecutionBudget, PolicyHookRegistry


class AutonomousCodingService:
    """Use a model for structured edits while keeping writes approval-gated."""

    def __init__(
        self,
        provider: Any,
        *,
        workflow: CodingWorkflowService | None = None,
        context: CodingContextService | None = None,
        hooks: PolicyHookRegistry | None = None,
        budget_factory: Callable[[], ExecutionBudget] | None = None,
    ):
        self.provider = provider
        self.workflow = workflow or CodingWorkflowService()
        self.context = context or CodingContextService()
        self.hooks = hooks or PolicyHookRegistry()
        self.budget_factory = budget_factory or (
            lambda: ExecutionBudget(
                max_model_calls=4, max_tool_calls=12,
                max_tokens=80_000, max_wall_seconds=900,
            )
        )

    async def propose(
        self,
        repo_path: str | Path,
        objective: str,
        *,
        focus_paths: list[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        previous_failure: dict[str, Any] | None = None,
        budget: ExecutionBudget | None = None,
    ) -> dict[str, Any]:
        execution_budget = budget or self.budget_factory()
        gate = self.hooks.run("before_context", {
            "repo_path": str(repo_path), "objective": objective,
        })
        if not gate["allowed"]:
            raise PermissionError("before_context policy hook denied the request")
        manifest = self.context.build(
            repo_path, objective,
            focus_paths=focus_paths,
            diagnostics=diagnostics,
        )
        prompt = (
            "Return exactly one JSON object, without markdown, using schema "
            '{"changes":[{"path":"relative","operation":"replace|create|hunks",'
            '"old_text":"...","new_text":"...","content":"...",'
            '"hunks":[{"old_text":"...","new_text":"..."}]}],'
            '"test_commands":[["python","-m","pytest","..."]],'
            '"explanation":"...","confidence":0.0}. '
            "Use exact old_text from evidence. Never use overwrite. Keep scope "
            "minimal. Tests must be argv arrays and must validate the change.\n\n"
            + self.context.render_for_prompt(manifest)
        )
        if previous_failure:
            prompt += (
                "\n\n[Previous attempt failed and was restored]\n"
                + json.dumps(previous_failure, ensure_ascii=False)[:12_000]
            )
        execution_budget.consume(model_calls=1)
        before_model = self.hooks.run("before_model", {
            "objective": objective,
            "context_digest": manifest["context_digest"],
        })
        if not before_model["allowed"]:
            raise PermissionError("before_model policy hook denied the request")
        response = await self.provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a repository coding planner. You may propose "
                        "changes but cannot claim they were applied or tested."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            {"temperature": 0.0},
        )
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "model proposal failed")
        content = str(response.get("content") or "").strip()
        try:
            proposal = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("model response is not strict JSON") from exc
        self._validate_proposal(proposal)
        execution_budget.consume(
            tokens=int((response.get("usage") or {}).get("total_tokens") or 0)
        )
        plan = self.workflow.plan(
            repo_path,
            objective,
            proposal["changes"],
            proposal["test_commands"],
        )
        return {
            "schema": "clawos.autonomous-coding-proposal.v1",
            "proposal": proposal,
            "plan": plan,
            "context_digest": manifest["context_digest"],
            "proposal_digest": hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest(),
            "writes_performed": False,
            "requires_confirmation": True,
        }

    async def run(
        self,
        repo_path: str | Path,
        objective: str,
        *,
        confirmed: bool = False,
        focus_paths: list[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        max_attempts: int = 3,
        timeout_seconds: int = 180,
    ) -> dict[str, Any]:
        if confirmed is not True:
            proposal = await self.propose(
                repo_path, objective,
                focus_paths=focus_paths, diagnostics=diagnostics,
            )
            return {**proposal, "status": "waiting_confirmation"}
        budget = self.budget_factory()
        attempts = []
        previous_failure = None
        for attempt in range(1, max(1, min(int(max_attempts), 4)) + 1):
            proposal = await self.propose(
                repo_path,
                objective,
                focus_paths=focus_paths,
                diagnostics=diagnostics,
                previous_failure=previous_failure,
                budget=budget,
            )
            before_write = self.hooks.run("before_write", {
                "attempt": attempt,
                "proposal_digest": proposal["proposal_digest"],
                "paths": [
                    item["path"] for item in proposal["proposal"]["changes"]
                ],
            })
            if not before_write["allowed"]:
                raise PermissionError("before_write policy hook denied the patch")
            budget.consume(
                tool_calls=1 + len(proposal["proposal"]["test_commands"])
            )
            result = self.workflow.execute(
                repo_path,
                objective,
                proposal["proposal"]["changes"],
                proposal["proposal"]["test_commands"],
                confirmed=True,
                max_rounds=1,
                timeout_seconds=timeout_seconds,
                actor="autonomous-coding-service",
            )
            attempts.append({
                "attempt": attempt,
                "proposal_digest": proposal["proposal_digest"],
                "context_digest": proposal["context_digest"],
                "workflow": result,
            })
            if result["status"] == "passed":
                return {
                    "schema": "clawos.autonomous-coding-run.v1",
                    "status": "passed",
                    "attempts": attempts,
                    "human_review_required": True,
                    "commit_created": False,
                    "online_rl_claimed": False,
                }
            previous_failure = {
                "failure": result.get("failure"),
                "rounds": result.get("rounds"),
            }
        return {
            "schema": "clawos.autonomous-coding-run.v1",
            "status": "failed",
            "attempts": attempts,
            "restored_on_failure": all(
                item["workflow"].get("restored_on_failure") for item in attempts
            ),
            "human_review_required": True,
            "commit_created": False,
            "online_rl_claimed": False,
        }

    @staticmethod
    def _validate_proposal(proposal: dict[str, Any]) -> None:
        if not isinstance(proposal, dict):
            raise ValueError("proposal must be an object")
        changes = proposal.get("changes")
        commands = proposal.get("test_commands")
        if not isinstance(changes, list) or not changes:
            raise ValueError("proposal requires non-empty changes")
        if not isinstance(commands, list) or not commands:
            raise ValueError("proposal requires non-empty test_commands")
        if len(changes) > 20 or len(commands) > 5:
            raise ValueError("proposal exceeds bounded change or test limits")
        for item in changes:
            if not isinstance(item, dict) or item.get("operation") not in {
                "replace", "create", "hunks",
            }:
                raise ValueError("proposal contains an unsupported operation")
