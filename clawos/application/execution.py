"""Model, tool and routing execution with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi.responses import JSONResponse
from pathlib import Path
from services.response_contract import SYSTEM_PROMPT
from services import ToolService
from services.search_evidence import decide_search_need
import hashlib
import json
import re
from services.response_contract import request_history
import time


class ExecutionRuntime:
    def __init__(self, *,
        _provider_candidates: Callable[..., Any],
        call_routing_llm: Callable[..., Any],
        execute_python_tool: Callable[..., Any],
        execute_tool_call: Callable[..., Any],
        get_coding_workflow_service: Callable[..., Any],
        has_api_key: Callable[..., Any],
        output_root_provider: Callable[[], Any],
        scenario_routing_keywords_provider: Callable[[], Any],
        scenario_routing_policy_provider: Callable[[], Any],
        tools_requiring_confirmation_provider: Callable[[], Any],
        web_research_synthesis_prompt_provider: Callable[[], Any],
        web_research_tools_provider: Callable[[], Any],
        config_provider: Callable[[], Any],
        context_builder_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
        runtime_policy_controller_provider: Callable[[], Any],
        security_policy_provider: Callable[[], Any],
        skill_evolution_provider: Callable[[], Any],
        upstream_provider_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
        http_client_provider: Callable[[], Any],
        logger_provider: Callable[[], Any],
        tools_def_provider: Callable[[], Any],
    ):
        self._provider_candidates = _provider_candidates
        self.call_routing_llm = call_routing_llm
        self.execute_python_tool = execute_python_tool
        self.execute_tool_call = execute_tool_call
        self.get_coding_workflow_service = get_coding_workflow_service
        self.has_api_key = has_api_key
        self.output_root_provider = output_root_provider
        self.scenario_routing_keywords_provider = scenario_routing_keywords_provider
        self.scenario_routing_policy_provider = scenario_routing_policy_provider
        self.tools_requiring_confirmation_provider = tools_requiring_confirmation_provider
        self.web_research_synthesis_prompt_provider = web_research_synthesis_prompt_provider
        self.web_research_tools_provider = web_research_tools_provider
        self.config_provider = config_provider
        self.context_builder_provider = context_builder_provider
        self.memory_store_provider = memory_store_provider
        self.runtime_policy_controller_provider = runtime_policy_controller_provider
        self.security_policy_provider = security_policy_provider
        self.skill_evolution_provider = skill_evolution_provider
        self.upstream_provider_provider = upstream_provider_provider
        self.vector_store_provider = vector_store_provider
        self.http_client_provider = http_client_provider
        self.logger_provider = logger_provider
        self.tools_def_provider = tools_def_provider

    def _tool_service(self) -> ToolService:
        return ToolService(
            python_executor=self.execute_python_tool,
            store_getter=lambda: self.memory_store_provider(),
            policy_getter=lambda: self.security_policy_provider(),
            vector_refresh=(lambda: self.vector_store_provider().refresh()) if self.vector_store_provider() else None,
            logger=self.logger_provider(),
            confirmation_tools=self.tools_requiring_confirmation_provider(),
        )


    async def call_model_with_fallback(self, section: str, messages: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
        attempts = []
        for index, provider in enumerate(self._provider_candidates(section)):
            if not provider:
                continue
            provider_options = dict(options)
            if index:
                provider_options.pop("model", None)
            result = await provider.complete(messages, provider_options, http_client=self.http_client_provider())
            attempts.append({
                "provider": result.get("provider", getattr(provider, "name", "")),
                "model": result.get("model", getattr(provider, "model", "")),
                "ok": bool(result.get("ok")),
                "error": result.get("error", ""),
                "duration_ms": result.get("duration_ms", 0),
            })
            if result.get("ok"):
                result["fallback_attempts"] = attempts
                return result
        return {
            "ok": False,
            "provider": section,
            "model": "",
            "content": "",
            "raw": {},
            "usage": {},
            "duration_ms": 0,
            "error": attempts[-1]["error"] if attempts else "no_provider",
            "fallback_attempts": attempts,
        }


    def classify_scenario(self, text: str) -> str:
        low = str(text or "").lower()
        mapping = [
            ("research", ["论文", "科研", "文献", "paper", "research", "citation"]),
            ("learning", ["学习", "考试", "复习", "课程", "exam", "learn"]),
            ("office", ["会议", "纪要", "汇报", "报告", "ppt", "excel", "meeting", "brief", "report", "办公", "文档", "docx", "邮件", "日历", "calendar"]),
            ("project", ["代码", "项目", "git", "repo", "bug", "测试", "commit"]),
            ("web", ["搜索", "联网", "网页", "url", "http", "search", "crawl"]),
        ]
        for scenario, keys in mapping:
            if any(k in low for k in keys):
                return scenario
        return "general"


    def score_scenarios(self, text: str) -> list[dict[str, Any]]:
        low = str(text or "").lower()
        rows: list[dict[str, Any]] = []
        for scenario, policy in self.scenario_routing_policy_provider().items():
            keys = self.scenario_routing_keywords_provider().get(scenario, [])
            hits = [key for key in keys if key.lower() in low]
            score = 0.18 if scenario == "general" else 0.0
            if hits:
                score += 0.26 + min(0.48, 0.12 * (len(hits) - 1))
            if scenario == "research" and any(k in low for k in ["pdf", "docx", "rag", "chunk", "引用", "文献"]):
                score += 0.16
            if scenario == "web" and any(k in low for k in ["http://", "https://", "url", "网页"]):
                score += 0.18
            if scenario == "project" and any(k in low for k in ["写入", "commit", "git", "文件", "shell"]):
                score += 0.12
            if scenario == "office" and any(k in low for k in ["xlsx", "pptx", "docx", "表格", "演示"]):
                score += 0.12
            if not low.strip() and scenario == "general":
                score = 0.52
            rows.append({
                "scenario": scenario,
                "score": round(min(score, 0.98), 4),
                "matched_keywords": hits[:8],
                "risk": policy.get("risk", "low"),
                "tools": policy.get("tools", []),
                "model_profile": policy.get("model_profile", "balanced"),
                "retrieval": policy.get("retrieval", "memory_optional"),
                "requires_confirmation": policy.get("requires_confirmation", []),
                "reason": "keyword_match" if hits else ("default_low_risk" if scenario == "general" else "available_capability"),
            })
        rows.sort(key=lambda item: (item["score"], -len(item.get("requires_confirmation", []))), reverse=True)
        if rows and rows[0]["score"] <= 0:
            rows = sorted(rows, key=lambda item: item["scenario"] != "general")
            rows[0]["score"] = 0.52
            rows[0]["reason"] = "default_low_risk"
        return rows


    def build_routing_strategy(self, text: str) -> dict[str, Any]:
        candidates = self.score_scenarios(text)
        selected = candidates[0] if candidates else {"scenario": self.classify_scenario(text), "score": 0.0}
        scenario = selected["scenario"]
        policy = self.scenario_routing_policy_provider()[scenario]
        return {
            "mode": "enforced_scenario_routing",
            "scenario": scenario,
            "confidence": selected.get("score", 0.0),
            "matched_keywords": selected.get("matched_keywords", []),
            "model_profile": policy.get("model_profile", "balanced"),
            "retrieval": policy.get("retrieval", "memory_optional"),
            "risk": policy.get("risk", "low"),
            "allowed_tools": list(policy.get("tools", [])),
            "requires_confirmation": list(policy.get("requires_confirmation", [])),
        }


    def apply_web_search_policy(self,
        strategy: dict[str, Any],
        user_text: str,
        *,
        mode: str = "auto",
        has_attachments: bool = False,
        local_context_sufficient: bool = False,
    ) -> dict[str, Any]:
        decision = decide_search_need(
            user_text,
            mode=mode,
            has_attachments=has_attachments,
            local_context_sufficient=local_context_sufficient,
        )
        result = dict(strategy or {})
        allowed = list(result.get("allowed_tools") or [])
        confirmations = list(result.get("requires_confirmation") or [])
        if not decision["should_search"]:
            allowed = [name for name in allowed if name not in self.web_research_tools_provider()]
            confirmations = [name for name in confirmations if name not in self.web_research_tools_provider()]
        else:
            for name in ("web_search", "web_fetch"):
                if name not in allowed:
                    allowed.append(name)
            if "web_fetch" not in confirmations:
                confirmations.append("web_fetch")
        result["allowed_tools"] = allowed
        result["requires_confirmation"] = confirmations
        result["web_search_decision"] = decision
        return result


    def web_search_prompt_policy(self, decision: dict[str, Any]) -> str:
        if decision.get("should_search"):
            return self.web_research_synthesis_prompt_provider() + (
                " Internal evidence policy: "
                + json.dumps({
                    "source_policy": decision.get("source_policy"),
                    "coverage": decision.get("coverage") or {},
                    "max_source_reads": decision.get("max_source_reads", 0),
                    "stop_when": decision.get("stop_when"),
                }, ensure_ascii=False, separators=(",", ":"))
                + ". Stop issuing search calls when the coverage target is met. Open only the "
                  "few pages needed for claim-level verification. Never mention this policy or "
                  "the search process in the final answer."
            )
        return (
            "Web search is not needed for this request. Use the supplied conversation, "
            "attachments, and local knowledge; do not call web_search or web_fetch."
        )


    async def execute_coding_agent_call(self,
        arguments: dict[str, Any],
        session_id: str,
        confirmed_tools: set[str],
        task_id: int | None,
    ) -> dict[str, Any]:
        """Run the existing iterative coding loop through the default chat router."""
        if not self.upstream_provider_provider():
            return {"ok": False, "status": "error", "tool": "coding_agent", "error": "model provider is not initialized", "data": None}
        from services.agentic_coding_loop_service import AgenticCodingLoopService
        from services.coding_trace_service import CodingTraceService
        from services.coding_workspace_service import CodingWorkspaceService

        repo_value = str(arguments.get("repo_path") or "")
        try:
            repo = self.security_policy_provider().resolve_path(repo_value) if self.security_policy_provider() else Path(repo_value).expanduser().resolve()
        except ValueError as exc:
            return {"ok": False, "status": "denied", "tool": "coding_agent", "error": str(exc), "data": None, "risk_level": "high"}
        confirmed = "coding_agent" in confirmed_tools
        workspace_service = CodingWorkspaceService()
        workspace = None
        run_repo = repo
        if confirmed:
            try:
                workspace = workspace_service.create_task(
                    repo,
                    self.output_root_provider() / "coding" / "workspaces",
                    str(task_id or f"chat-{int(time.time())}"),
                    confirmed=True,
                )
                run_repo = Path(workspace["workspace"])
            except (OSError, PermissionError, RuntimeError, ValueError) as exc:
                return {
                    "ok": False, "status": "error", "tool": "coding_agent",
                    "error": f"isolated task workspace could not be created: {exc}",
                    "data": None, "risk_level": "high",
                }
        service = AgenticCodingLoopService(
            self.upstream_provider_provider(),
            workflow=self.get_coding_workflow_service(),
            context=getattr(self.context_builder_provider(), "_coding_context", None),
            trace=CodingTraceService(self.output_root_provider() / "traces" / "coding.json"),
            learning_store=self.memory_store_provider(),
        )
        try:
            data = await service.run(
                run_repo,
                str(arguments.get("objective") or ""),
                confirmed=confirmed,
                focus_paths=arguments.get("focus_paths") or [],
                diagnostics=arguments.get("diagnostics") or [],
                enable_lsp=True,
                max_turns=int(arguments.get("max_turns") or 10),
                timeout_seconds=int(arguments.get("timeout_seconds") or 180),
                task_id=str(task_id or f"chat-{int(time.time())}"),
                session_id=session_id,
                actor_id="chat-coding-agent",
            )
        except (OSError, PermissionError, RuntimeError, ValueError) as exc:
            source_verification = workspace_service.verify_source(workspace) if workspace else None
            return {
                "ok": False, "status": "error", "tool": "coding_agent",
                "error": str(exc),
                "data": {"workspace": workspace, "source_verification": source_verification} if workspace else None,
                "risk_level": "high",
            }
        if workspace:
            data["workspace"] = workspace
            data["workspace_changes"] = workspace_service.changes(workspace)
            data["source_verification"] = workspace_service.verify_source(workspace)
            data["workspace_lifecycle"] = workspace_service.touch_task(
                Path(workspace["workspace_root"]) / "workspace.json"
            )
        waiting = data.get("status") == "waiting_confirmation"
        return {
            "ok": not waiting,
            "status": "needs_confirmation" if waiting else ("success" if data.get("status") == "passed" else "error"),
            "tool": "coding_agent",
            "arguments": arguments,
            "data": data,
            "error": "Review the proposed patch and confirm execution." if waiting else str(data.get("failure") or ""),
            "requires_confirmation": waiting,
            "risk_level": "high",
        }


    def tool_result_for_model(self, tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
        """Remove operational noise before evidence is given back to the model."""
        if not result.get("ok"):
            return result
        if tool_name == "web_fetch":
            data = result.get("data") or {}
            return {
                "ok": True,
                "tool": tool_name,
                "evidence": {
                    "title": data.get("title", ""),
                    "url": data.get("final_url") or data.get("url") or (result.get("arguments") or {}).get("url", ""),
                    "text": str(data.get("text") or "")[:12_000],
                    "published_at": data.get("published_at", ""),
                },
                "instruction": "Use only passages that support the answer; cite this page next to the supported claim.",
                "next_step": "Synthesize the supported claim; do not narrate the fetch operation.",
            }
        if tool_name != "web_search":
            return result
        data = result.get("data") or {}
        evidence = []
        for item in data.get("results") or []:
            evidence.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "published_at": item.get("published_at", ""),
                "domain": item.get("domain", ""),
                "source_type": item.get("source_type", "other"),
                "credibility": item.get("credibility", ""),
                "source_score": (item.get("scores") or {}).get("source_score", 0),
            })
        sufficiency = data.get("evidence_sufficiency") or {}
        return {
            "ok": True,
            "tool": tool_name,
            "query": data.get("query", ""),
            "evidence": evidence,
            "quality_summary": data.get("quality_summary") or {},
            "evidence_sufficiency": sufficiency,
            "next_step": (
                "Evidence coverage is sufficient. Stop searching; fetch at most the few pages "
                "needed for claim-level verification, then answer naturally."
                if sufficiency.get("enough_to_stop_search") else
                "One evidence lane is still missing. Run one focused search for only the missing "
                "lane; do not repeat the same broad query."
            ),
        }


    def resolve_runtime_policies(self, scenario: str, identity: str) -> dict[str, dict[str, Any]]:
        if not self.runtime_policy_controller_provider():
            return {}

        def resolve_with_default(target_type: str):
            selected = self.runtime_policy_controller_provider().resolve(target_type, scenario, identity)
            if (
                not selected.get("payload")
                and not selected.get("run_id")
                and scenario != "default"
            ):
                selected = self.runtime_policy_controller_provider().resolve(target_type, "default", identity)
            return selected

        return {
            "prompt": resolve_with_default("prompt_policy"),
            "retrieval": resolve_with_default("retrieval_params"),
            "routing": resolve_with_default("tool_routing_policy"),
        }


    def runtime_policy_trace(self, selections: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for name, item in (selections or {}).items():
            if not item:
                continue
            rows.append({
                "name": name,
                **{
                    key: item.get(key)
                    for key in (
                        "target_type", "target_key", "policy_version", "source",
                        "release_stage", "run_id", "exposure", "bucket",
                        "candidate_digest", "baseline_digest",
                    )
                    if item.get(key) is not None
                },
            })
        return rows


    def evaluate_shadow_policies(self,
        base_routing: dict[str, Any],
        selections: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Materialize candidate behavior without exposing it to the user."""

        if not self.runtime_policy_controller_provider():
            return []
        rows = []
        for name, selection in (selections or {}).items():
            candidate = selection.get("shadow_payload")
            if candidate is None:
                continue
            candidate_selection = {**selection, "payload": candidate}
            if name == "routing":
                materialized = self.runtime_policy_controller_provider().apply_routing(
                    base_routing, candidate_selection
                )
                summary = {
                    "allowed_tools": materialized.get("allowed_tools", []),
                    "requires_confirmation": materialized.get("requires_confirmation", []),
                }
            elif name == "retrieval":
                summary = self.runtime_policy_controller_provider().retrieval_options(candidate_selection)
            else:
                prompt = self.runtime_policy_controller_provider().apply_prompt(
                    SYSTEM_PROMPT, candidate_selection
                )
                summary = {
                    "prompt_chars": len(prompt),
                    "prompt_digest": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                }
            rows.append({
                "name": name,
                "run_id": selection.get("run_id"),
                "candidate_digest": selection.get("candidate_digest"),
                "materialized": summary,
                "visible_to_user": False,
            })
        return rows


    def tools_for_routing_strategy(self, strategy: dict[str, Any]) -> list[dict[str, Any]]:
        allowed = set(strategy.get("allowed_tools") or [])
        return [
            item for item in self.tools_def_provider()
            if str((item.get("function") or {}).get("name") or "") in allowed
        ]


    def rule_based_tool(self, user_text: str) -> tuple[str, dict[str, Any]] | None:
        """Small offline router for high-confidence local operations."""
        text = user_text.strip()
        low = text.lower()
        if any(k in low for k in ["current time", "what time", "time now"]) or any(k in text for k in ["现在几点", "当前时间", "今天几号"]):
            return "time_now", {}
        if low in {"list skills", "show skills", "skill list"} or any(k in text for k in ["列出技能", "查看技能", "技能列表"]):
            return "skill_list", {}
        if low in {"memory stats", "memory status"} or any(k in text for k in ["记忆统计", "memoryos统计"]):
            return "memory_stats", {}
        if low in {"memory history", "conversation history", "show history"} or any(k in text for k in ["记忆历史", "对话历史", "聊天历史", "查看历史"]):
            return "memory_history", {}
        if low in {"profiles", "profile memory", "show profile"} or any(k in text for k in ["查看画像", "用户画像", "我的画像", "个人资料"]):
            return "memory_profile_get", {}
        if low in {"preferences", "preference memory", "show preferences"} or any(k in text for k in ["查看偏好", "我的偏好", "偏好设置"]):
            return "memory_preference_get", {}
        if low in {"list tools", "show tools", "tool list"} or any(k in text for k in ["列出工具", "查看工具", "工具列表"]):
            return "tools_list", {}
        m = re.search(r"^set profile:\s*([^=：:]+)\s*[=：:]\s*(.+)$", text, re.I)
        if m:
            return "memory_profile_set", {"key": m.group(1).strip(), "value": m.group(2).strip()}
        m = re.search(r"^set preference:\s*([^=：:]+)\s*[=：:]\s*(.+)$", text, re.I)
        if m:
            return "memory_preference_set", {"key": m.group(1).strip(), "value": m.group(2).strip()}
        m = re.search(r"记住(?:我的)?(.{1,24}?)(?:是|为|:|：)(.+)", text)
        if m:
            return "memory_preference_set", {"key": m.group(1).strip(), "value": m.group(2).strip()}
        return None


    async def run_tool_loop(self,
        user_text: str,
        session_id: str = "default",
        confirmed_tools: set[str] | None = None,
        task_id: int | None = None,
        routing_strategy_override: dict[str, Any] | None = None,
        prompt_policy: dict[str, Any] | None = None,
        retrieval_policy: dict[str, Any] | None = None,
        coding_context: dict[str, Any] | None = None,
        governance=None,
        conversation_messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Tool detection + execution loop."""
        if governance is None:
            from services.execution_governance import GovernedExecutionContext
            governance = GovernedExecutionContext.local(
                actor_id=f"session:{session_id}", workspace_id="default"
            )
        governance.gate("before_context", {
            "session_id": session_id, "task_id": task_id, "user_text": user_text,
        })
        confirmed_tools = confirmed_tools or set()
        routing_strategy = routing_strategy_override or self.build_routing_strategy(user_text)
        allowed_tool_names = set(routing_strategy.get("allowed_tools") or [])
        routed_tools = self.tools_for_routing_strategy(routing_strategy)
        # Fast path: known solidified skills should bypass the LLM router.
        try:
            from skills.skill_registry import match_skill_by_text
            matched_skill = match_skill_by_text(user_text)
            if matched_skill:
                canary = (
                    self.skill_evolution_provider().select_runtime_definition(
                        matched_skill["name"], identity=f"{session_id}:{task_id or ''}"
                    )
                    if self.skill_evolution_provider() else {}
                )
                if canary.get("exposure") == "candidate":
                    from skills.skill_registry import execute_skill_definition
                    result = execute_skill_definition(
                        canary["definition"], params={}, plan_only=False
                    )
                    args = json.dumps({
                        "name": matched_skill["name"],
                        "params": {},
                        "candidate_version_id": canary.get("version_id"),
                    }, ensure_ascii=False)
                else:
                    args = json.dumps({"name": matched_skill["name"], "params": {}}, ensure_ascii=False)
                    governance.budget.consume(tool_calls=1)
                    try:
                        governance.authorize_egress(json.loads(args))
                    except json.JSONDecodeError:
                        pass
                    governance.gate("before_tool", {
                        "tool": "skill_execute", "skill": matched_skill["name"],
                    })
                    result = self.execute_tool_call(
                        "skill_execute", args, session_id, confirmed_tools, task_id=task_id
                    )
                    governance.gate("after_tool", {
                        "tool": "skill_execute", "ok": bool(result.get("ok")),
                    })
                if result.get("ok"):
                    return {
                        "used_tools": True,
                        "tool_calls": [{
                            "name": "skill_execute",
                            "arguments": args,
                            "result": result,
                            "skill_canary": {
                                key: canary.get(key)
                                for key in (
                                    "exposure", "canary_id", "version_id", "bucket", "percent"
                                )
                                if canary.get(key) is not None
                            },
                        }],
                        "final_text": "",
                        "routing_rounds": 0,
                        "matched_skill": matched_skill["name"],
                        "routing_strategy": routing_strategy,
                    }
                if self.logger_provider():
                    self.logger_provider().info("Skill fast path needs parameters or failed: %s", matched_skill["name"])
        except Exception as e:
            self.logger_provider().debug(f"Skill fast path skipped: {e}")

        rb = self.rule_based_tool(user_text)
        if rb:
            fn_name, fn_args_obj = rb
            fn_args = json.dumps(fn_args_obj, ensure_ascii=False)
            governance.budget.consume(tool_calls=1)
            governance.gate("before_tool", {"tool": fn_name})
            result = self.execute_tool_call(fn_name, fn_args, session_id, confirmed_tools, task_id=task_id)
            governance.gate("after_tool", {
                "tool": fn_name, "ok": bool(result.get("ok")),
            })
            return {
                "used_tools": True,
                "tool_calls": [{"name": fn_name, "arguments": fn_args, "result": result}],
                "final_text": "",
                "routing_rounds": 0,
                "matched_skill": "",
                "routing_strategy": routing_strategy,
            }

        if not self.has_api_key("routing"):
            lang_zh = bool(re.search(r"[\u4e00-\u9fff]", user_text))
            text = "模型尚未配置，请在设置中选择可用模型。" if lang_zh else "No model is configured. Select an available model in settings."
            return {"used_tools": False, "tool_calls": [], "final_text": text, "model_error": "not_configured", "routing_rounds": 0, "routing_strategy": routing_strategy}

        # Use MemoryOS to build messages with context
        if self.context_builder_provider():
            coding = dict(coding_context or {})
            messages = self.context_builder_provider().build_messages(
                session_id,
                user_text,
                prompt_policy=prompt_policy,
                retrieval_policy=retrieval_policy,
                repo_path=str(coding.get("repo_path") or ""),
                focus_paths=coding.get("focus_paths") or [],
                diagnostics=coding.get("diagnostics") or [],
                coding_token_budget=int(coding.get("token_budget") or 12000),
                conversation_messages=conversation_messages,
            )
        else:
            messages = [{"role": "system", "content": SYSTEM_PROMPT + "\n" + str((prompt_policy or {}).get("system") or "")}, *(request_history(conversation_messages) or []), {"role": "user", "content": user_text}]
        governance.gate("after_context", {
            "message_count": len(messages), "task_id": task_id,
        })
        max_rounds = self.config_provider().get("max_tool_rounds", 6)
        tc_log: list[dict[str, Any]] = []
        used = False
        last_model_error = ""
        search_decision = routing_strategy.get("web_search_decision") or {}
        search_complete = False
        source_reads = 0

        for ri in range(1, max_rounds + 1):
            try:
                governance.budget.consume(model_calls=1)
                governance.gate("before_model", {"round": ri, "task_id": task_id})
                resp = await self.call_routing_llm(messages, routed_tools)
                governance.gate("after_model", {"round": ri, "task_id": task_id})
            except Exception as e:
                last_model_error = str(e)[:160] or type(e).__name__
                try:
                    governance.gate("on_failure", {
                        "stage": "model", "round": ri, "error": type(e).__name__,
                    })
                except PermissionError:
                    pass
                self.logger_provider().warning(f"Routing LLM error round {ri}: {e}")
                break
            choices = resp.get("choices", [])
            if not choices:
                last_model_error = "empty_model_response"
                break
            msg = choices[0].get("message", {})
            tcs = msg.get("tool_calls") or []
            content = msg.get("content", "")

            if not tcs:
                if not isinstance(content, str) or not content.strip():
                    last_model_error = "empty_final_answer"
                    break
                return {"used_tools": used, "tool_calls": tc_log, "final_text": content, "answer_complete": True, "model_result": resp.get("clawos_model", {}), "routing_rounds": ri, "routing_strategy": routing_strategy}

            used = True
            tc_msgs = []
            tool_messages = []
            for tc in tcs:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                fn_args = fn.get("arguments", "{}")
                tc_id = tc.get("id", f"call_{fn_name}_{ri}")
                tc_msgs.append({"id": tc_id, "type": "function", "function": {"name": fn_name, "arguments": fn_args}})
                self.logger_provider().info(f"Tool: {fn_name}({fn_args[:150]})")
                if fn_name not in allowed_tool_names:
                    result = {
                        "ok": False,
                        "status": "denied",
                        "tool": fn_name,
                        "error": f"tool is outside the enforced {routing_strategy['scenario']} scenario policy",
                    }
                elif fn_name == "coding_agent":
                    governance.budget.consume(tool_calls=1)
                    try:
                        parsed_args = json.loads(fn_args or "{}")
                    except json.JSONDecodeError:
                        parsed_args = {}
                    result = await self.execute_coding_agent_call(
                        parsed_args if isinstance(parsed_args, dict) else {},
                        session_id,
                        confirmed_tools,
                        task_id,
                    )
                else:
                    governance.budget.consume(tool_calls=1)
                    try:
                        parsed_args = json.loads(fn_args)
                    except json.JSONDecodeError:
                        parsed_args = {}
                    if not isinstance(parsed_args, dict):
                        parsed_args = {}
                    if fn_name == "web_search":
                        if search_complete:
                            result = {
                                "ok": False, "status": "denied", "tool": fn_name,
                                "error": "evidence coverage is already sufficient; synthesize the answer",
                                "data": {"stop_search": True},
                            }
                            tc_log.append({"name": fn_name, "arguments": fn_args, "result": result})
                            model_result = self.tool_result_for_model(fn_name, result)
                            tool_messages.append({"role": "tool", "tool_call_id": tc_id, "name": fn_name, "content": json.dumps(model_result, ensure_ascii=False)})
                            continue
                        parsed_args["evidence_policy"] = search_decision
                        parsed_args.setdefault("breadth", search_decision.get("breadth", "balanced"))
                        fn_args = json.dumps(parsed_args, ensure_ascii=False)
                    if fn_name == "web_fetch":
                        max_reads = int(search_decision.get("max_source_reads") or 0)
                        if max_reads and source_reads >= max_reads:
                            result = {
                                "ok": False, "status": "denied", "tool": fn_name,
                                "error": "source read budget reached; synthesize from collected evidence",
                                "data": {"stop_fetching": True},
                            }
                            tc_log.append({"name": fn_name, "arguments": fn_args, "result": result})
                            model_result = self.tool_result_for_model(fn_name, result)
                            tool_messages.append({"role": "tool", "tool_call_id": tc_id, "name": fn_name, "content": json.dumps(model_result, ensure_ascii=False)})
                            continue
                        source_reads += 1
                    try:
                        governance.authorize_egress(parsed_args)
                    except (PermissionError, ValueError):
                        raise
                    governance.gate("before_tool", {
                        "tool": fn_name, "arguments_digest": hashlib.sha256(
                            fn_args.encode("utf-8")
                        ).hexdigest(),
                    })
                    result = self.execute_tool_call(
                        fn_name, fn_args, session_id, confirmed_tools, task_id=task_id
                    )
                    governance.gate("after_tool", {
                        "tool": fn_name, "ok": bool(result.get("ok")),
                    })
                    if fn_name == "web_search" and result.get("ok"):
                        sufficiency = ((result.get("data") or {}).get("evidence_sufficiency") or {})
                        search_complete = bool(sufficiency.get("enough_to_stop_search"))
                tc_log.append({"name": fn_name, "arguments": fn_args, "result": result})
                model_result = self.tool_result_for_model(fn_name, result)
                tool_messages.append({"role": "tool", "tool_call_id": tc_id, "name": fn_name, "content": json.dumps(model_result, ensure_ascii=False)})
            assistant_msg = {"role": "assistant", "content": content or "", "tool_calls": tc_msgs}
            assistant_msg["tool_calls"] = tc_msgs
            messages.append(assistant_msg)
            messages.extend(tool_messages)
            if any(tc["result"].get("status") == "needs_confirmation" for tc in tc_log):
                return {"used_tools": True, "tool_calls": tc_log, "final_text": "", "routing_rounds": ri, "routing_strategy": routing_strategy}

        lang_zh = bool(re.search(r"[\u4e00-\u9fff]", user_text))
        if last_model_error:
            final_text = (
                f"模型未能完成回答（{last_model_error}），请重试或检查模型设置。"
                if lang_zh else
                f"The model could not complete the answer ({last_model_error}). Retry or check model settings."
            )
        else:
            final_text = "模型没有返回有效内容，请重试。" if lang_zh else "The model returned no usable content. Please retry."
        return {"used_tools": used, "tool_calls": tc_log, "final_text": final_text, "routing_rounds": max_rounds, "routing_strategy": routing_strategy, "model_error": last_model_error}


    def build_openai_response(self, content: str, model: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build a small OpenAI-compatible chat completion response."""
        payload = {
            "id": f"chatcmpl-clawos-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model or self.config_provider().get("upstream", {}).get("model", "clawos-agent"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content or ""},
                "finish_reason": "stop",
            }],
        }
        if extra:
            payload["clawos"] = extra
        return payload


    def extract_assistant_text(self, resp: JSONResponse) -> str:
        try:
            body = json.loads(resp.body)
            for ch in body.get("choices", []):
                msg = ch.get("message", {})
                if msg.get("content"):
                    return str(msg["content"])
        except Exception:
            pass
        return ""
