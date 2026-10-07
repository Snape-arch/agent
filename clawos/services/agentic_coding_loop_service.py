"""Iterative observe -> act -> edit -> test -> review coding agent."""

from __future__ import annotations

import hashlib
import fnmatch
import json
from pathlib import Path
from typing import Any

from .coding_context_service import CodingContextService
from .coding_execution_context import CodingExecutionContext
from .coding_diagnostics_service import CodingEvidenceGate
from .coding_trace_service import CodingTraceService
from .lsp_semantic_graph_service import LSPSemanticGraphService
from .coding_workflow_service import CodingWorkflowService
from .execution_governance import GovernedExecutionContext


class AgenticCodingLoopService:
    """A bounded tool-using loop; the model proposes one action per turn."""

    ACTIONS = {"search", "read", "symbols", "semantic", "propose_patch", "finish"}

    def __init__(
        self,
        provider: Any,
        *,
        workflow: CodingWorkflowService | None = None,
        context: CodingContextService | None = None,
        trace: CodingTraceService | None = None,
        learning_store: Any | None = None,
    ):
        self.provider = provider
        self.workflow = workflow or CodingWorkflowService()
        self.context = context or CodingContextService()
        self.trace = trace or CodingTraceService()
        self.learning_store = learning_store

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
        enable_lsp: bool = False,
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
        semantic_workspace: dict[str, Any] = {}
        if enable_lsp:
            try:
                semantic_workspace = LSPSemanticGraphService(
                    cache_root=self.workflow.artifact_root / "semantic-index"
                ).build_available(
                    repo, files=focus_paths, max_languages=3,
                    max_files=40, max_symbols=120, include_calls=True,
                )
            except (OSError, RuntimeError, TimeoutError, ValueError):
                semantic_workspace = {}
        manifest = self.context.build_execution(repo, objective, focus_paths=focus_paths,
            failure_context=diagnostics, semantic_graph=semantic_workspace)
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
            "execution_context": manifest,
            "repo_map": {'files':[{'path':r['path'], 'symbols':r['symbols'], 'dependencies':r['imports']}
                                  for r in manifest['code_evidence']]},
            "ranked_files": [
                item.get("path") for item in (manifest.get("code_evidence") or [])[:30]
            ],
            "diagnostics": manifest.get("diagnostics") or [],
            "semantic_graph": {
                "available": bool(semantic_workspace.get('graphs')),
                "metrics": semantic_workspace.get('metrics') or {},
            },
            "repository_intelligence": manifest.get("repository_intelligence") or {},
            "task_context": {
                "digest": (manifest.get("task_context") or {}).get("digest"),
                "selected_files": manifest['scope']['read_paths'],
                "nodes": (manifest.get("task_context") or {}).get("nodes") or [],
                "edges": (manifest.get("task_context") or {}).get("edges") or [],
            },
            "impact_analysis": manifest.get("impact_analysis") or {},
        }]
        evidence_gate = CodingEvidenceGate(manifest)
        hypothesis_history: list[dict[str, Any]] = []
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an iterative coding agent. Return exactly one JSON "
                    "object and no prose. The action field must be exactly one "
                    "of search, read, symbols, semantic, propose_patch, finish. Put every "
                    "parameter in a separate field; never put parameters inside "
                    "the action string. Read example: "
                    '{"action":"read","path":"maths.py","start_line":1,'
                    '"end_line":200}. Search example: '
                    '{"action":"search","query":"add","glob":"*.py"}. '
                    "Semantic graph example: "
                    '{"action":"semantic","path":"maths.py","symbol":"add",'
                    '"depth":2}. '
                    "Patch example: "
                    '{"action":"propose_patch","changes":[{"path":"maths.py",'
                    '"operation":"replace","old_text":"old","new_text":"new"}],'
                    '"test_commands":[["python","-m","unittest","-q"]],'
                    '"explanation":"reason"}. Use repository-relative paths. '
                    "Each changed path may appear only once in a proposal. "
                    "Observe before editing. Never claim tests passed unless "
                    "tool evidence says so. Every propose_patch must include a "
                    "hypothesis object with claim, evidence_paths and predicted_outcome, "
                    "plus acceptance_criteria. After every failed patch, reassess the "
                    "hypothesis from structured diagnostics before deciding whether to "
                    "retrieve more evidence or propose a different patch. Do not finish "
                    "until the acceptance gate explicitly passes."
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
        learning_decision_count = 0
        for turn in range(1, max(2, min(int(max_turns), 20)) + 1):
            governed.budget.consume(model_calls=1)
            governed.gate("before_model", {"task_id": task_id, "turn": turn})
            try:
                CodingExecutionContext.verify(repo, manifest)
            except ValueError as exc:
                return self._fail(run['id'], attempts, observations, str(exc), governed)
            response = await self.provider.complete(
                messages, {
                    "temperature": 0.0,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                }
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
                behavior_propensity=None,
                metadata={
                    "turn": turn, "action": action_name,
                    "policy": "deterministic-model-action",
                    "learned_propensity": False,
                },
            )
            learning_decision_count += int(self._record_learning_decision(
                task_id,
                turn=turn,
                action=action,
                observations=observations,
                context_digest=manifest["context_digest"],
            ))
            if action_name in {"search", "read", "symbols"}:
                if evidence_gate.retrieval_complete():
                    observation = {
                        "type": "retrieval_stopped", "tool": action_name,
                        "reason": "relevant evidence is sufficient; propose a hypothesis and patch instead of reading more files",
                        "observed_paths": sorted(evidence_gate.observed_paths),
                    }
                    observations.append(observation)
                    messages.extend([
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": json.dumps({"observation": observation}, ensure_ascii=False)},
                    ])
                    continue
                governed.budget.consume(tool_calls=1)
                governed.gate("before_tool", {
                    "task_id": task_id, "tool": action_name, "turn": turn,
                })
                try:
                    observation = self._observe(repo, manifest, action, semantic_workspace=semantic_workspace)
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
                evidence = evidence_gate.register(action, observation)
                observation["evidence_gate"] = evidence
                messages.extend([
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": json.dumps(
                        {"observation": observation}, ensure_ascii=False
                    )},
                ])
                continue
            if action_name == "finish":
                final_acceptance = (
                    ((attempts[-1].get("workflow") or {}).get("acceptance") or {})
                    if attempts else {}
                )
                final_hypothesis = hypothesis_history[-1] if hypothesis_history else {}
                if (
                    not attempts or attempts[-1].get("status") != "passed"
                    or not final_acceptance.get("passed")
                    or final_hypothesis.get("status") != "confirmed"
                ):
                    messages.extend([
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": json.dumps({
                            "error": "finish requires confirmed hypothesis and a passed acceptance gate",
                            "acceptance": final_acceptance,
                            "hypothesis": final_hypothesis,
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
                    "learning_decision_count": learning_decision_count,
                    "hypothesis_history": hypothesis_history,
                    "acceptance": final_acceptance,
                }
            if not evidence_gate.patch_ready():
                target = evidence_gate.automatic_target()
                observation = {
                    "type": "evidence_required", "turn": turn,
                    "reason": "patch blocked until relevant repository evidence is retrieved",
                    "suggested_action": {"action": "read", "path": target, "start_line": 1, "end_line": 240} if target else {"action": "search", "query": objective, "glob": "*"},
                }
                observations.append(observation)
                messages.extend([
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": json.dumps({"observation": observation}, ensure_ascii=False)},
                ])
                continue
            proposal = {
                "changes": action.get("changes") or [],
                "test_commands": action.get("test_commands") or [],
                "explanation": str(action.get("explanation") or ""),
                "hypothesis": action.get("hypothesis") or {
                    "claim": str(action.get("explanation") or "proposed change addresses the objective"),
                    "evidence_paths": sorted(evidence_gate.observed_paths or evidence_gate.initial_paths),
                    "predicted_outcome": "configured tests and acceptance criteria pass",
                },
                "acceptance_criteria": action.get("acceptance_criteria") or [],
            }
            try:
                CodingExecutionContext.verify(repo, manifest)
                CodingExecutionContext.assert_changes(manifest, proposal['changes'])
                plan = self.workflow.plan(
                    repo, objective, proposal["changes"],
                    proposal["test_commands"],
                )
            except (OSError, RuntimeError, ValueError) as exc:
                observation = {
                    "type": "proposal_error", "turn": turn,
                    "error": str(exc),
                    "instruction": (
                        "Repair the proposal structure and return a new "
                        "propose_patch action."
                    ),
                }
                observations.append(observation)
                self.trace.step(
                    run["id"], "failure", status="recoverable",
                    input_value=proposal, output_value=observation,
                    metadata={"turn": turn, "phase": "plan_patch"},
                )
                messages.extend([
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": json.dumps(
                        {"observation": observation}, ensure_ascii=False
                    )},
                ])
                continue
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
                    "learning_decision_count": learning_decision_count,
                }
            governed.gate("before_write", {
                "task_id": task_id, "turn": turn,
                "paths": [item.get("path") for item in proposal["changes"]],
            })
            governed.budget.consume(
                tool_calls=1 + len(proposal["test_commands"])
            )
            try:
                result = self.workflow.execute(
                    repo, objective, proposal["changes"],
                    proposal["test_commands"],
                    confirmed=True, max_rounds=1,
                    timeout_seconds=timeout_seconds, actor=actor_id,
                    acceptance_criteria=proposal["acceptance_criteria"],
                )
            except (OSError, PermissionError, RuntimeError, ValueError) as exc:
                observation = {
                    "type": "patch_execution_error", "turn": turn,
                    "error": str(exc),
                    "instruction": (
                        "Repair the patch or test command and return a new "
                        "propose_patch action."
                    ),
                }
                observations.append(observation)
                self.trace.step(
                    run["id"], "failure", status="recoverable",
                    input_value=proposal, output_value=observation,
                    metadata={"turn": turn, "phase": "execute_patch"},
                )
                messages.extend([
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": json.dumps(
                        {"observation": observation}, ensure_ascii=False
                    )},
                ])
                continue
            governed.gate("after_write", {
                "task_id": task_id, "turn": turn, "status": result["status"],
            })
            attempt = {
                "turn": turn, "status": result["status"],
                "proposal_digest": hashlib.sha256(content.encode()).hexdigest(),
                "workflow": result,
            }
            attempts.append(attempt)
            assessment = self._assess_hypothesis(proposal["hypothesis"], result)
            hypothesis_history.append(assessment)
            attempt["hypothesis_assessment"] = assessment
            if assessment["status"] != "confirmed":
                evidence_gate.reopen_after_failure()
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
                "diagnostics": [
                    item.get("diagnostics") for item in result.get("rounds") or []
                ],
                "failure_category": next((
                    item.get("diagnostics", {}).get("failure_category")
                    for item in reversed(result.get("rounds") or [])
                    if item.get("diagnostics")
                ), "none"),
                "hypothesis_assessment": assessment,
                "acceptance": result.get("acceptance") or {},
            }
            observations.append(observation)
            failed_tests = [test for round_item in result.get('rounds', []) for test in round_item.get('tests', [])]
            manifest = self.context.build_execution(repo, objective, write_paths=manifest['scope']['write_paths'],
                failure_context=CodingExecutionContext.failure_context(repo, failed_tests))
            semantic_workspace = {}  # Initial LSP evidence is stale after an edit attempt.
            observation['execution_context'] = manifest
            self.trace.step(run['id'], 'context', status='refreshed', output_value=manifest['context_digest'],
                metadata={'turn':turn, 'source_fingerprint':manifest['source_fingerprint']})
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

    @staticmethod
    def _assess_hypothesis(
        hypothesis: dict[str, Any], workflow: dict[str, Any]
    ) -> dict[str, Any]:
        rounds = workflow.get("rounds") or []
        diagnostic = (rounds[-1].get("diagnostics") or {}) if rounds else {}
        acceptance = workflow.get("acceptance") or {}
        category = str(diagnostic.get("failure_category") or "none")
        if workflow.get("status") == "passed" and acceptance.get("passed"):
            status, decision = "confirmed", "finish_when_requested"
        elif category == "environment_failure":
            status, decision = "inconclusive", "repair_environment_without_changing_implementation"
        elif category == "requirements_failure":
            status, decision = "invalidated", "clarify_or_retrieve_requirement_evidence"
        elif category == "test_failure":
            status, decision = "invalidated", "inspect_assertion_and_related_symbols_then_revise"
        else:
            status, decision = "invalidated", "inspect_diagnostics_and_revise_implementation"
        return {
            "schema": "clawos.coding-hypothesis-assessment.v1",
            "claim": str(hypothesis.get("claim") or ""),
            "predicted_outcome": str(hypothesis.get("predicted_outcome") or ""),
            "evidence_paths": list(hypothesis.get("evidence_paths") or []),
            "status": status, "failure_category": category,
            "next_decision": decision,
            "diagnostic_count": len(diagnostic.get("diagnostics") or []),
            "related_symbols": diagnostic.get("related_symbols") or [],
            "acceptance_passed": bool(acceptance.get("passed")),
        }

    def _record_learning_decision(
        self, task_id: str, *, turn: int, action: dict[str, Any],
        observations: list[dict[str, Any]], context_digest: str,
    ) -> bool:
        if self.learning_store is None:
            return False
        try:
            numeric_task_id = int(task_id)
            if not self.learning_store.get_task(numeric_task_id):
                return False
            from agent_learning import TrajectoryLearningService

            TrajectoryLearningService(self.learning_store).record_decision(
                numeric_task_id,
                state={
                    "turn": int(turn),
                    "observation_types": [
                        str(item.get("type") or "") for item in observations
                    ],
                },
                action_type="agentic_coding_action",
                action_name=str(action.get("action") or ""),
                action_payload={
                    key: value for key, value in action.items()
                    if key not in {"changes"}
                },
                behavior_propensity=0.0,
                candidate_set=sorted(self.ACTIONS),
                candidate_scores={},
                policy_version="agentic-coding-loop-v1",
                exploration_source="model_action_without_logged_distribution",
                context_digest=context_digest,
            )
            return True
        except (KeyError, TypeError, ValueError):
            return False

    def _observe(
        self, repo: Path, manifest: dict[str, Any], action: dict[str, Any], *, semantic_workspace=None
    ) -> dict[str, Any]:
        name = action["action"]
        CodingExecutionContext.verify(repo, manifest)
        if name == "search":
            query = str(action.get("query") or "").lower()
            glob = str(action.get("glob") or "*")
            matches = []
            for rel in manifest['scope']['read_paths']:
                if not fnmatch.fnmatch(rel, glob):continue
                data = CodingExecutionContext.read(repo, rel)
                if data is None:continue
                try:
                    for number, line in enumerate(
                        data.decode('utf-8-sig').splitlines(),
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
        if name == "semantic":
            workspace = self.context._semantic_context(semantic_workspace or {},
                [{'path':p} for p in manifest['scope']['read_paths']])
            requested_path = str(action.get("path") or "").replace("\\", "/").strip("/")
            if requested_path not in manifest['scope']['read_paths']:
                raise ValueError('semantic path outside execution context')
            requested_symbol = str(action.get("symbol") or "")
            depth = max(0, min(int(action.get("depth") or 2), 5))
            merged_nodes, merged_edges, seeds = [], [], []
            for graph in workspace.get("graphs") or []:
                queried = LSPSemanticGraphService().query(
                    graph, path=requested_path, symbol=requested_symbol,
                    depth=depth, limit=100,
                )
                merged_nodes.extend(queried["nodes"])
                merged_edges.extend(queried["edges"])
                seeds.extend(queried["seed_ids"])
            return {
                "type": "semantic", "path": requested_path,
                "symbol": requested_symbol, "seed_ids": sorted(set(seeds)),
                "nodes": merged_nodes[:100], "edges": merged_edges[:300],
                "available": bool((workspace.get("graphs") or [])),
            }
        rel = str(action.get("path") or "").replace("\\", "/").strip("/")
        if rel not in manifest['scope']['read_paths']:
            raise ValueError('observation path outside execution context')
        path = (repo / rel).resolve()
        try:
            path.relative_to(repo)
        except ValueError as exc:
            raise ValueError("observation path escapes repository") from exc
        if name == "read":
            if not path.is_file():
                raise ValueError("read path does not exist")
            lines = CodingExecutionContext.read(repo, rel).decode('utf-8-sig').splitlines()
            start = max(1, int(action.get("start_line") or 1))
            end = min(len(lines), start + 239, max(start, int(action.get("end_line") or start + 199)))
            return {
                "type": "read", "path": rel, "start_line": start,
                "end_line": end, "content": "\n".join(lines[start - 1:end])[:12000],
            }
        symbols = []
        for item in manifest.get('code_evidence') or []:
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
