"""Chat HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from services.grounded_paper_report import GroundedPaperReport
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
from services.response_contract import SYSTEM_PROMPT
import json
import re
from services.response_contract import request_history
from services.artifact_storage import safe_artifact_slug


class ChatAPI:
    def __init__(self, *,
        apply_web_search_policy: Callable[..., Any],
        build_openai_response: Callable[..., Any],
        build_routing_strategy: Callable[..., Any],
        collect_deliverable_artifacts: Callable[..., Any],
        create_runtime_task: Callable[..., Any],
        evaluate_shadow_policies: Callable[..., Any],
        extract_assistant_text: Callable[..., Any],
        finish_runtime_task: Callable[..., Any],
        get_paper_intelligence_service: Callable[..., Any],
        has_api_key: Callable[..., Any],
        model_provider_status: Callable[..., Any],
        proxy_upstream: Callable[..., Any],
        resolve_runtime_policies: Callable[..., Any],
        run_tool_loop: Callable[..., Any],
        runtime_policy_trace: Callable[..., Any],
        sse_from_text: Callable[..., Any],
        store_assistant_response: Callable[..., Any],
        tool_result_for_model: Callable[..., Any],
        web_search_prompt_policy: Callable[..., Any],
        output_root_provider: Callable[[], Any],
        web_research_tools_provider: Callable[[], Any],
        config_provider: Callable[[], Any],
        context_builder_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
        mtclaw_adapter_provider: Callable[[], Any],
        policy_optimizer_provider: Callable[[], Any],
        reflection_engine_provider: Callable[[], Any],
        runtime_policy_controller_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
        logger_provider: Callable[[], Any],
    ):
        self.apply_web_search_policy = apply_web_search_policy
        self.build_openai_response = build_openai_response
        self.build_routing_strategy = build_routing_strategy
        self.collect_deliverable_artifacts = collect_deliverable_artifacts
        self.create_runtime_task = create_runtime_task
        self.evaluate_shadow_policies = evaluate_shadow_policies
        self.extract_assistant_text = extract_assistant_text
        self.finish_runtime_task = finish_runtime_task
        self.get_paper_intelligence_service = get_paper_intelligence_service
        self.has_api_key = has_api_key
        self.model_provider_status = model_provider_status
        self.proxy_upstream = proxy_upstream
        self.resolve_runtime_policies = resolve_runtime_policies
        self.run_tool_loop = run_tool_loop
        self.runtime_policy_trace = runtime_policy_trace
        self.sse_from_text = sse_from_text
        self.store_assistant_response = store_assistant_response
        self.tool_result_for_model = tool_result_for_model
        self.web_search_prompt_policy = web_search_prompt_policy
        self.output_root_provider = output_root_provider
        self.web_research_tools_provider = web_research_tools_provider
        self.config_provider = config_provider
        self.context_builder_provider = context_builder_provider
        self.memory_store_provider = memory_store_provider
        self.mtclaw_adapter_provider = mtclaw_adapter_provider
        self.policy_optimizer_provider = policy_optimizer_provider
        self.reflection_engine_provider = reflection_engine_provider
        self.runtime_policy_controller_provider = runtime_policy_controller_provider
        self.vector_store_provider = vector_store_provider
        self.logger_provider = logger_provider
        self.router = APIRouter()
        self.router.add_api_route('/v1/models', self.list_models, methods=['GET'])
        self.router.add_api_route('/v1/chat/completions', self.chat_completions, methods=['POST'])

    def _record_mtclaw_task_steps(self, task_id: int | None, trace: list[dict[str, Any]]) -> None:
        if not task_id or not self.memory_store_provider():
            return
        for item in trace:
            name = str(item.get("function_name") or "mtclaw_tool")
            arguments = item.get("tool_input") if isinstance(item.get("tool_input"), dict) else {}
            result = item.get("tool_result")
            error = str(result.get("error") or "") if isinstance(result, dict) else ""
            status = "failed" if error else "succeeded"
            try:
                step = self.memory_store_provider().add_task_step(
                    task_id,
                    "tool",
                    name,
                    status="running",
                    input_data=arguments,
                )
                self.memory_store_provider().finish_task_step(
                    step["id"],
                    status=status,
                    output_data={"source": "mtclaw", "result": result},
                    error=error,
                )
            except Exception as exc:
                self.logger_provider().warning(f"MTClaw task step persistence failed: {exc}")


    def _confirmed_tools_from_request(self, req_data: dict[str, Any]) -> set[str]:
        value = req_data.get("clawos_confirmed_tools", req_data.get("confirmed_tools", []))
        if isinstance(value, str):
            return {value}
        if isinstance(value, list):
            return {str(item) for item in value}
        return set()


    async def list_models(self):
        provider_state = self.model_provider_status(self.config_provider()) if self.config_provider() else {"model": "clawos-agent", "provider": "clawos"}
        return JSONResponse({"object":"list","data":[{"id":provider_state["model"],"object":"model","owned_by":provider_state["provider"]}]})


    def _build_attachment_context(self, raw_attachments: Any) -> tuple[str, list[dict[str, Any]]]:
        if not isinstance(raw_attachments, list):
            return "", []
        normalized: list[dict[str, Any]] = []
        blocks: list[str] = []
        total_chars = 0
        for idx, item in enumerate(raw_attachments[:8], start=1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"attachment-{idx}")[:180]
            content = str(item.get("content") or "")
            if not content.strip():
                continue
            remaining = max(0, 60000 - total_chars)
            if remaining <= 0:
                break
            clipped = content[: min(30000, remaining)]
            total_chars += len(clipped)
            meta = {
                "name": name,
                "type": str(item.get("type") or "")[:80],
                "size": int(item.get("size") or 0) if str(item.get("size") or "").isdigit() else item.get("size", 0),
                "chars": len(clipped),
            }
            normalized.append(meta)
            blocks.append(
                f"[Attachment {idx}: {name}]\n"
                f"type={meta['type'] or 'unknown'} size={meta['size']}\n"
                f"{clipped}"
            )
        if not blocks:
            return "", normalized
        context = (
            "\n\n[ClawOS hidden attachment context]\n"
            "The user attached the following local files. Treat them as task context. "
            "Do not claim the user pasted this text, and only quote from it when useful.\n\n"
            + "\n\n---\n\n".join(blocks)
        )
        return context, normalized


    def _build_uploaded_document_context(self, raw_attachments: Any, query: str) -> tuple[str, list[dict[str, Any]]]:
        if not isinstance(raw_attachments, list) or not self.memory_store_provider():
            return self._build_attachment_context(raw_attachments)
        normalized: list[dict[str, Any]] = []
        blocks: list[str] = []
        fallback_attachments: list[dict[str, Any]] = []
        for item in raw_attachments[:8]:
            if not isinstance(item, dict):
                continue
            doc_id = item.get("document_id") or item.get("id")
            if not doc_id:
                fallback_attachments.append(item)
                continue
            document = self.memory_store_provider().get_document(int(doc_id))
            if not document:
                continue
            deep_read = bool(re.search(r"精读|论文|方法|实验|发现|局限|引用|evidence|method|experiment|limitation|deep[ -]?read", str(query or ""), re.I))
            if deep_read:
                try:
                    intelligence = self.get_paper_intelligence_service().analyze_document(int(doc_id))
                    bundle = GroundedPaperReport.build_evidence_bundle(intelligence)
                    evidence_context = {key: value for key, value in bundle.items() if key != "allowed_citations"}
                    blocks.append(
                        f"[Document: {document.get('title')}]\n"
                        f"[Local editable source: {document.get('file_path', '')}]\n"
                        "This is a structure-balanced evidence bundle. Cite only citation IDs present in it.\n"
                        + json.dumps(evidence_context, ensure_ascii=False)
                    )
                    normalized.append({
                        "document_id": int(doc_id),
                        "name": document.get("filename") or document.get("title"),
                        "title": document.get("title"),
                        "category": document.get("category"),
                        "chunk_count": sum(len(rows) for rows in bundle.get("sections", {}).values()),
                        "context_mode": "structure_balanced",
                    })
                    continue
                except Exception:
                    pass
            chunks = self.memory_store_provider().search_document_chunks(query or document.get("title", ""), document.get("category", ""), 12)
            chunks = [c for c in chunks if int(c.get("document_id") or 0) == int(doc_id)]
            if not chunks:
                chunks = self.memory_store_provider().get_document_chunks(int(doc_id), 8)
            meta = {
                "document_id": int(doc_id),
                "name": document.get("filename") or document.get("title"),
                "title": document.get("title"),
                "category": document.get("category"),
                "chunk_count": len(chunks),
            }
            normalized.append(meta)
            excerpt_parts = []
            for chunk in chunks[:8]:
                citation = chunk.get("citation") or f"doc:{doc_id}#chunk={chunk.get('chunk_index')}"
                excerpt_parts.append(f"[{citation}]\n{chunk.get('content', '')[:2200]}")
            excerpt = "\n\n".join(excerpt_parts)
            blocks.append(f"[Document: {meta['title']}]\n[Local editable source: {document.get('file_path', '')}]\n{excerpt}")
        fallback_context, fallback_meta = self._build_attachment_context(fallback_attachments)
        normalized.extend(fallback_meta)
        if not blocks:
            return fallback_context, normalized
        context = (
            "\n\n[ClawOS hidden uploaded document context]\n"
            "The user attached indexed documents. Use these retrieved chunks as RAG context. "
            "When referring to evidence, cite doc:N#chunk=M where available.\n\n"
            + "\n\n---\n\n".join(blocks)
        )
        return context + fallback_context, normalized


    async def chat_completions(self, request: Request):
        try:
            body = await request.body()
            req_data = json.loads(body)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid JSON: {e}")

        messages = req_data.get("messages", [])
        request_headers = getattr(request, "headers", {}) or {}
        if not messages:
            raise HTTPException(400, "messages array required")

        user_text = ""
        session_id = req_data.get("session_id", "default")
        confirmed_tools = self._confirmed_tools_from_request(req_data)
        for m in reversed(messages):
            if m.get("role") == "user" and m.get("content"):
                user_text = str(m["content"])
                break

        attachment_context, attachment_meta = self._build_uploaded_document_context(req_data.get("clawos_attachments", []), user_text)
        effective_user_text = user_text + attachment_context
        web_search_mode = str(req_data.get("clawos_web_search_mode") or "auto").lower()
        coding_context = dict(req_data.get("clawos_coding_context") or {})
        stream = req_data.get("stream", False)
        routing_strategy = self.build_routing_strategy(effective_user_text)
        base_routing_strategy = dict(routing_strategy)
        policy_selections = self.resolve_runtime_policies(
            routing_strategy.get("scenario", "general"),
            str(session_id),
        )
        shadow_evaluations = self.evaluate_shadow_policies(
            base_routing_strategy, policy_selections
        )
        if self.runtime_policy_controller_provider() and policy_selections.get("routing"):
            routing_strategy = self.runtime_policy_controller_provider().apply_routing(
                routing_strategy, policy_selections["routing"]
            )
        prompt_policy = (policy_selections.get("prompt") or {}).get("payload") or {}
        retrieval_policy = (
            self.runtime_policy_controller_provider().retrieval_options(policy_selections["retrieval"])
            if self.runtime_policy_controller_provider() and policy_selections.get("retrieval")
            else {}
        )
        policy_trace = self.runtime_policy_trace(policy_selections)

        if not user_text:
            resp = await self.proxy_upstream(req_data, stream)
            if isinstance(resp, JSONResponse):
                await self.store_assistant_response(session_id, resp)
            return resp

        runtime_task = None
        task_id = None
        if self.memory_store_provider():
            runtime_task = self.create_runtime_task(
                session_id,
                user_text[:120] or "Chat completion",
                metadata={
                    "stream": bool(stream),
                    "user_text": user_text,
                    "scenario": routing_strategy.get("scenario", "general"),
                    "tags": routing_strategy.get("matched_keywords", []),
                    "user_context": req_data.get("clawos_user_context") or {},
                    "environment_state": {
                        "stream": bool(stream),
                        "mtclaw_enabled": bool(
                            self.mtclaw_adapter_provider() and self.mtclaw_adapter_provider().enabled
                        ),
                        "attachment_count": len(attachment_meta),
                    },
                    "attachments": attachment_meta,
                    "runtime_policies": policy_trace,
                    "shadow_policy_evaluations": shadow_evaluations,
                    "idempotency_key": str(
                        req_data.get("clawos_idempotency_key")
                        or request_headers.get("Idempotency-Key", "")
                        or ""
                    ),
                },
            )
            task_id = runtime_task.get("id")
            stored_payload = runtime_task.get("metadata", {}).get("response_payload")
            if runtime_task.get("idempotent_replay") and stored_payload and not stream:
                return JSONResponse(stored_payload)
            if self.policy_optimizer_provider() and task_id:
                try:
                    optimizer_selection = self.policy_optimizer_provider().select(
                        f"routing:{routing_strategy.get('scenario', 'general')}",
                        context={
                            "scenario": routing_strategy.get("scenario", "general"),
                            "tags": routing_strategy.get("matched_keywords", []),
                            "task_description": user_text,
                            "session_id": str(session_id),
                            "history": {
                                "message_count": len(messages),
                                "user_turn_count": sum(
                                    1 for message in messages
                                    if message.get("role") == "user"
                                ),
                            },
                            "user": req_data.get("clawos_user_context") or {},
                            "environment": {
                                "stream": bool(stream),
                                "attachment_count": len(attachment_meta),
                                "mtclaw_enabled": bool(
                                    self.mtclaw_adapter_provider() and self.mtclaw_adapter_provider().enabled
                                ),
                            },
                        },
                        task_id=task_id,
                        session_id=session_id,
                    )
                    optimizer_policy = {
                        "payload": optimizer_selection.get("payload") or {},
                        "target_type": "tool_routing_policy",
                        "target_key": routing_strategy.get("scenario", "general"),
                        "policy_version": 0,
                        "source": "contextual_ucb",
                        "release_stage": "online_selection",
                        "exposure": "candidate",
                    }
                    if self.runtime_policy_controller_provider():
                        routing_strategy = self.runtime_policy_controller_provider().apply_routing(
                            routing_strategy, optimizer_policy
                        )
                    optimizer_payload = optimizer_selection.get("payload") or {}
                    learned_prompt = (
                        optimizer_payload.get("system")
                        or optimizer_payload.get("prompt")
                        or optimizer_payload.get("workflow_prompt")
                    )
                    if learned_prompt:
                        prompt_policy = {
                            **prompt_policy,
                            "system": "\n".join(
                                part for part in (
                                    str(prompt_policy.get("system") or "").strip(),
                                    str(learned_prompt).strip(),
                                )
                                if part
                            ),
                        }
                    learned_retrieval = optimizer_payload.get("retrieval_params")
                    if isinstance(learned_retrieval, dict):
                        retrieval_policy = {
                            **retrieval_policy,
                            **learned_retrieval,
                        }
                    routing_strategy["agent_learning_decision"] = {
                        "selection_id": optimizer_selection["id"],
                        "arm_name": optimizer_selection["arm_name"],
                        "agent": optimizer_payload.get("agent"),
                        "workflow": optimizer_payload.get("workflow"),
                        "skills": optimizer_payload.get("skills") or [],
                        "model": (
                            (optimizer_selection.get("context") or {})
                            .get("_agent_learning", {})
                            .get("model")
                        ),
                    }
                    self.memory_store_provider().update_task_metadata(
                        task_id,
                        {
                            "policy_optimizer_selections": [{
                                "selection_id": optimizer_selection["id"],
                                "group_name": optimizer_selection["group_name"],
                                "arm_name": optimizer_selection["arm_name"],
                                "payload": optimizer_selection.get("payload") or {},
                            }],
                        },
                        event_type="policy_selected",
                    )
                except ValueError:
                    # Policy groups are opt-in; the enforced static/runtime policy
                    # remains active until a group has been registered.
                    pass

        # --- TOOL ROUTING ---
        routing_strategy = self.apply_web_search_policy(
            routing_strategy,
            user_text,
            mode=web_search_mode,
            has_attachments=bool(attachment_meta),
            local_context_sufficient=bool(coding_context.get("repo_path")),
        )
        search_guidance = self.web_search_prompt_policy(routing_strategy["web_search_decision"])
        artifact_guidance = (
            "When the user asks to create, generate, save, export, or modify a report, "
            "document, spreadsheet, presentation, PDF, or project file, do not merely "
            "describe file contents. Use an available write or office tool to create the "
            f"actual file under {str(self.output_root_provider() / 'chat' / safe_artifact_slug(str(session_id)))} "
            "unless the user supplied another allowed path. Return the completed artifact "
            "only after the tool reports that it exists and passed its quality checks."
        )
        prompt_policy = {
            **prompt_policy,
            "system": "\n".join(
                part for part in (
                    str(prompt_policy.get("system") or "").strip(),
                    search_guidance,
                    artifact_guidance,
                )
                if part
            ),
        }
        if self.context_builder_provider():
            self.context_builder_provider().ingest_and_store(session_id, "user", user_text)
        elif self.memory_store_provider():
            self.memory_store_provider().add_message(session_id, "user", user_text)

        routing_policy_payload = (policy_selections.get("routing") or {}).get("payload") or {}
        mtclaw_policy_compatible = not (
            routing_policy_payload.get("allowed_tools")
            or routing_policy_payload.get("deny_tools")
        )
        if self.mtclaw_adapter_provider() and self.mtclaw_adapter_provider().enabled and mtclaw_policy_compatible:
            mtclaw_messages = (
                self.context_builder_provider().build_messages(
                    session_id,
                    effective_user_text,
                    prompt_policy=prompt_policy,
                    retrieval_policy=retrieval_policy,
                    repo_path=str(coding_context.get("repo_path") or ""),
                    focus_paths=coding_context.get("focus_paths") or [],
                    diagnostics=coding_context.get("diagnostics") or [],
                    coding_token_budget=int(coding_context.get("token_budget") or 12000),
                    conversation_messages=messages,
                )
                if self.context_builder_provider()
                else [
                    {
                        "role": "system",
                        "content": self.runtime_policy_controller_provider().apply_prompt(
                            SYSTEM_PROMPT, policy_selections.get("prompt") or {}
                        ) if self.runtime_policy_controller_provider() else SYSTEM_PROMPT,
                    },
                    *(request_history(messages) or []),
                    {"role": "user", "content": effective_user_text},
                ]
            )
            mtclaw_result = await self.mtclaw_adapter_provider().route(
                mtclaw_messages,
                session_id,
                {"temperature": req_data.get("temperature", 0.0)},
            )
            if self.memory_store_provider():
                self.memory_store_provider().record_mtclaw_trace(
                    session_id=session_id,
                    route_status="success" if mtclaw_result["ok"] else "fallback",
                    provider_url=self.mtclaw_adapter_provider().base_url,
                    model=mtclaw_result.get("model", ""),
                    duration_ms=mtclaw_result.get("duration_ms", 0),
                    tool_history=mtclaw_result.get("trace", []),
                    error=mtclaw_result.get("error", ""),
                )
            if mtclaw_result["ok"]:
                trace = mtclaw_result.get("trace", [])
                self._record_mtclaw_task_steps(task_id, trace)
                text = mtclaw_result.get("content", "")
                if self.memory_store_provider() and text:
                    self.memory_store_provider().add_message(session_id, "assistant", text)
                raw = mtclaw_result.get("raw") or self.build_openai_response(text)
                mtclaw_tool_calls = [
                    {
                        "name": item.get("function_name", ""),
                        "arguments": item.get("tool_input", {}),
                        "result": item.get("tool_result", {}),
                    }
                    for item in trace
                ]
                raw["clawos"] = {
                    "mtclaw": {
                        "used": True,
                        "provider": self.mtclaw_adapter_provider().base_url,
                        "duration_ms": mtclaw_result.get("duration_ms", 0),
                        "request_id": mtclaw_result.get("request_id", ""),
                        "trace_status": mtclaw_result.get("trace_status", "no_current_tool_evidence"),
                        "trace": trace,
                    },
                    "task_id": task_id,
                    "attachments": attachment_meta,
                    "used_tools": bool(trace),
                    "tool_calls": mtclaw_tool_calls,
                    "artifacts": self.collect_deliverable_artifacts(mtclaw_tool_calls, task_id),
                    "routing_strategy": routing_strategy,
                    "runtime_policies": policy_trace,
                }
                self.finish_runtime_task(task_id, "succeeded", result_payload=raw)
                if stream:
                    return self.sse_from_text(text, task_id=task_id, extra=raw["clawos"])
                return JSONResponse(raw)
            if not self.mtclaw_adapter_provider().fallback_on_error:
                self.finish_runtime_task(task_id, "failed", mtclaw_result["error"])
                raise HTTPException(503, f"MTClaw unavailable: {mtclaw_result['error']}")

        if task_id and self.memory_store_provider() and self.memory_store_provider().is_task_cancelled(task_id):
            text = "任务已收到取消请求，未继续执行。"
            body = self.build_openai_response(text, extra={"task_id": task_id, "canceled": True})
            if self.memory_store_provider():
                self.memory_store_provider().add_message(session_id, "assistant", text)
            self.finish_runtime_task(task_id, "canceled", "Canceled before tool loop", result_payload=body)
            return JSONResponse(body)

        tool_result = await self.run_tool_loop(
            effective_user_text,
            session_id,
            confirmed_tools,
            task_id=task_id,
            routing_strategy_override=routing_strategy,
            prompt_policy=prompt_policy,
            retrieval_policy=retrieval_policy,
            coding_context=coding_context,
            conversation_messages=messages,
        )
        confirmation_calls = [
            tc for tc in tool_result.get("tool_calls", [])
            if isinstance(tc.get("result"), dict) and tc["result"].get("status") == "needs_confirmation"
        ]
        if confirmation_calls:
            requested_names = list(dict.fromkeys(str(tc.get("name") or "") for tc in confirmation_calls if tc.get("name")))
            names = "、".join(requested_names)
            if requested_names and set(requested_names).issubset(self.web_research_tools_provider()):
                text = f"需要你确认后才能联网读取来源：{names}。确认后我会自动继续，不需要重新输入问题。"
            else:
                text = f"需要你确认后才能执行以下本地变更：{names}。确认后会继续写入、测试或生成文件，不需要重新输入问题。"
            extra = {
                "used_tools": True,
                "tool_calls": tool_result.get("tool_calls", []),
                "needs_confirmation": True,
                "confirmation_tools": requested_names,
                "routing_rounds": tool_result.get("routing_rounds", 0),
                "matched_skill": tool_result.get("matched_skill", ""),
                "routing_strategy": tool_result.get("routing_strategy", routing_strategy),
                "attachments": attachment_meta,
                "task_id": task_id,
                "runtime_policies": policy_trace,
            }
            if self.memory_store_provider():
                self.memory_store_provider().add_message(session_id, "assistant", text)
            self.finish_runtime_task(task_id, "waiting_confirmation")
            if stream:
                return self.sse_from_text(text, task_id=task_id, extra=extra)
            return JSONResponse(self.build_openai_response(text, extra=extra))

        # Auto-trigger reflection after tool execution
        reflection_result = None
        if tool_result["used_tools"] and self.reflection_engine_provider():
            try:
                trigger = self.reflection_engine_provider().should_reflect(
                    tool_result["tool_calls"], effective_user_text)
                if trigger:
                    reflection_result = self.reflection_engine_provider().reflect(
                        trigger, session_id,
                        tool_result["tool_calls"],
                        "", user_text[:100])
                    if self.vector_store_provider():
                        self.vector_store_provider().refresh()
            except Exception as e:
                self.logger_provider().warning(f"Reflection failed: {e}")

        if tool_result["used_tools"]:
            # Store tool-call context in memory before returning
            if self.memory_store_provider():
                for tc in tool_result["tool_calls"]:
                    self.memory_store_provider().add_message(session_id, "tool", json.dumps(tc.get("result", {}), ensure_ascii=False)[:4000])

            extra = {
                "used_tools": True,
                "tool_calls": tool_result["tool_calls"],
                "artifacts": self.collect_deliverable_artifacts(tool_result["tool_calls"], task_id),
                "reflection": reflection_result,
                "routing_rounds": tool_result.get("routing_rounds", 0),
                "matched_skill": tool_result.get("matched_skill", ""),
                "routing_strategy": tool_result.get("routing_strategy", routing_strategy),
                "task_id": task_id,
                "runtime_policies": policy_trace,
            }
            if tool_result.get("answer_complete"):
                text = tool_result["final_text"]
                extra["model_result"] = tool_result.get("model_result", {})
                body = self.build_openai_response(text, model=extra["model_result"].get("model"), extra=extra)
                if self.memory_store_provider():
                    self.memory_store_provider().add_message(session_id, "assistant", text)
                self.finish_runtime_task(task_id, "succeeded", result_payload=body)
                return self.sse_from_text(text, task_id=task_id, extra=extra) if stream else JSONResponse(body)
            upstream_msgs = (
                self.context_builder_provider().build_messages(
                    session_id,
                    effective_user_text,
                    prompt_policy=prompt_policy,
                    retrieval_policy=retrieval_policy,
                    repo_path=str(coding_context.get("repo_path") or ""),
                    focus_paths=coding_context.get("focus_paths") or [],
                    diagnostics=coding_context.get("diagnostics") or [],
                    coding_token_budget=int(coding_context.get("token_budget") or 12000),
                    conversation_messages=messages,
                )
                if self.context_builder_provider()
                else [
                    {
                        "role": "system",
                        "content": (
                            self.runtime_policy_controller_provider().apply_prompt(
                                SYSTEM_PROMPT, policy_selections.get("prompt") or {}
                            )
                            if self.runtime_policy_controller_provider() else SYSTEM_PROMPT
                        ),
                    },
                    *(request_history(messages) or []),
                    {"role": "user", "content": effective_user_text},
                ]
            )
            upstream_msgs.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": f"result_{index}", "type": "function", "function": {
                    "name": tc["name"], "arguments": tc.get("arguments") if isinstance(tc.get("arguments"), str)
                    else json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                }} for index, tc in enumerate(tool_result["tool_calls"])
            ]})
            upstream_msgs.extend({"role": "tool", "tool_call_id": f"result_{index}",
                                  "content": json.dumps(self.tool_result_for_model(tc["name"], tc["result"]), ensure_ascii=False)}
                                 for index, tc in enumerate(tool_result["tool_calls"]))
            if not self.has_api_key("upstream"):
                text = "工具步骤已结束，但回答模型尚未配置，无法整理结果。已生成的文件可在下方查看。"
                extra["status"] = "failed"
                body = self.build_openai_response(text, extra=extra)
                if self.memory_store_provider():
                    self.memory_store_provider().add_message(session_id, "assistant", text)
                self.finish_runtime_task(task_id, "failed", "answer_model_not_configured", result_payload=body)
                if stream:
                    return self.sse_from_text(text, task_id=task_id, extra=extra)
                return JSONResponse(body)
            resp = await self.proxy_upstream({**req_data, "messages": upstream_msgs}, False if stream else stream)
            if isinstance(resp, JSONResponse):
                text = self.extract_assistant_text(resp)
                body = json.loads(resp.body)
                extra = {**body.get("clawos", {}), **extra}
                body["clawos"] = extra
                if self.memory_store_provider() and text:
                    self.memory_store_provider().add_message(session_id, "assistant", text)
                failed = extra.get("status") == "failed"
                self.finish_runtime_task(task_id, "failed" if failed else "succeeded", result_payload=body)
                if stream:
                    return self.sse_from_text(text, task_id=task_id, extra=extra)
                return JSONResponse(body)
            return resp

        final_text = tool_result.get("final_text", "")
        failed = bool(tool_result.get("model_error"))
        if stream:
            if self.memory_store_provider() and final_text:
                self.memory_store_provider().add_message(session_id, "assistant", final_text)
            self.finish_runtime_task(task_id, "failed" if failed else "succeeded")
            return self.sse_from_text(final_text, task_id=task_id, extra={
                "used_tools": False,
                "status": "failed" if failed else "succeeded",
                "model_result": tool_result.get("model_result", {}),
                "tool_calls": [],
                "routing_rounds": tool_result.get("routing_rounds", 0),
                "attachments": attachment_meta,
                "task_id": task_id,
                "routing_strategy": tool_result.get("routing_strategy", routing_strategy),
                "runtime_policies": policy_trace,
            })

        resp_payload = self.build_openai_response(final_text, model=tool_result.get("model_result", {}).get("model"), extra={
            "used_tools": False,
            "status": "failed" if failed else "succeeded",
            "model_result": tool_result.get("model_result", {}),
            "tool_calls": [],
            "routing_rounds": tool_result.get("routing_rounds", 0),
            "attachments": attachment_meta,
            "task_id": task_id,
            "routing_strategy": tool_result.get("routing_strategy", routing_strategy),
            "runtime_policies": policy_trace,
        })
        if self.memory_store_provider() and final_text:
            self.memory_store_provider().add_message(session_id, "assistant", final_text)
        self.finish_runtime_task(task_id, "failed" if failed else "succeeded", result_payload=resp_payload)
        return JSONResponse(resp_payload)
