from __future__ import annotations

import json
import time
from typing import Any, Callable


class ToolService:
    """Tool execution envelope, policy preflight, audit, and task-step tracing."""

    def __init__(
        self,
        *,
        python_executor: Callable[[str, str], dict[str, Any]],
        store_getter: Callable[[], Any],
        policy_getter: Callable[[], Any],
        vector_refresh: Callable[[], None] | None = None,
        logger: Any = None,
        confirmation_tools: set[str] | None = None,
    ):
        self.python_executor = python_executor
        self.store_getter = store_getter
        self.policy_getter = policy_getter
        self.vector_refresh = vector_refresh
        self.logger = logger
        self.confirmation_tools = confirmation_tools or set()

    @staticmethod
    def parse_arguments(args_str: str) -> dict[str, Any]:
        try:
            parsed = json.loads(args_str or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def task_step_status(tool_status: str) -> str:
        if tool_status == "success":
            return "succeeded"
        if tool_status == "error":
            return "failed"
        return tool_status or "failed"

    def record_execution(self, session_id: str, envelope: dict[str, Any]) -> None:
        store = self.store_getter()
        if not store:
            return
        try:
            store.record_tool_execution(
                session_id=session_id,
                tool_name=envelope.get("tool", ""),
                arguments=envelope.get("arguments", {}),
                result=envelope,
                status=envelope.get("status", "unknown"),
                duration_ms=float(envelope.get("duration_ms", 0) or 0),
                requires_confirmation=bool(envelope.get("requires_confirmation")),
            )
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"Tool execution log failed: {exc}")

    def execute(
        self,
        name: str,
        args_str: str,
        *,
        session_id: str = "default",
        confirmed_tools: set[str] | None = None,
        task_id: int | None = None,
    ) -> dict[str, Any]:
        confirmed_tools = confirmed_tools or set()
        store = self.store_getter()
        if task_id and store and store.is_task_cancelled(task_id):
            envelope = {
                "ok": False,
                "status": "canceled",
                "tool": name,
                "arguments": self.parse_arguments(args_str),
                "data": None,
                "error": "Task cancellation requested before tool execution.",
                "duration_ms": 0,
                "requires_confirmation": False,
                "risk_level": "low",
            }
            self.record_execution(session_id, envelope)
            return envelope

        args_obj = self.parse_arguments(args_str)
        policy_result = {
            "allowed": True,
            "decision": "allow",
            "reason": "security policy not initialized",
            "normalized_arguments": args_obj,
            "risk_level": "low",
        }
        policy = self.policy_getter()
        if policy:
            policy_result = policy.evaluate(name, args_obj)
            args_obj = policy_result.get("normalized_arguments", args_obj)
            args_str = json.dumps(args_obj, ensure_ascii=False)

        if store:
            store.record_audit_event(
                "tool.preflight",
                decision=policy_result.get("decision", "allow"),
                session_id=session_id,
                task_id=task_id,
                resource_type="tool",
                resource_id=name,
                reason=policy_result.get("reason", ""),
                details={"arguments": args_obj},
            )

        if not policy_result.get("allowed", False):
            envelope = {
                "ok": False,
                "status": "denied",
                "tool": name,
                "arguments": args_obj,
                "data": None,
                "error": policy_result.get("reason", "Denied by security policy"),
                "duration_ms": 0,
                "requires_confirmation": False,
                "risk_level": policy_result.get("risk_level", "low"),
            }
            self.record_execution(session_id, envelope)
            return envelope

        requires_confirmation = name in self.confirmation_tools or policy_result.get("decision") == "confirm"
        started = time.perf_counter()
        task_step = None
        if task_id and store:
            try:
                task_step = store.add_task_step(task_id, "tool", name, status="running", input_data=args_obj)
            except Exception as exc:
                if self.logger:
                    self.logger.warning(f"Task step start failed: {exc}")

        if requires_confirmation and name not in confirmed_tools:
            envelope = {
                "ok": False,
                "status": "needs_confirmation",
                "tool": name,
                "arguments": args_obj,
                "data": None,
                "error": f"Tool '{name}' requires explicit confirmation before execution.",
                "duration_ms": 0,
                "requires_confirmation": True,
                "risk_level": policy_result.get("risk_level", "medium"),
            }
            self.record_execution(session_id, envelope)
            if task_step and store:
                store.finish_task_step(
                    task_step["id"],
                    status="needs_confirmation",
                    output_data=envelope,
                    error=envelope["error"],
                )
            return envelope

        if requires_confirmation and name in confirmed_tools and name in {
            "office_productivity", "office_artifact", "coding_workflow",
            "scholarly_download", "meeting_workflow", "autonomous_subagents",
        }:
            args_obj["confirmed"] = True
            args_str = json.dumps(args_obj, ensure_ascii=False)

        raw = self.python_executor(name, args_str)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        ok = not (isinstance(raw, dict) and raw.get("error"))
        if ok and name == "web_fetch" and isinstance(raw, dict) and raw.get("ingested") and self.vector_refresh:
            self.vector_refresh()

        envelope = {
            "ok": ok,
            "status": "success" if ok else "error",
            "tool": name,
            "arguments": args_obj,
            "data": raw if ok else None,
            "error": "" if ok else str(raw.get("error", raw)),
            "duration_ms": duration_ms,
            "requires_confirmation": requires_confirmation,
            "risk_level": policy_result.get("risk_level", "low"),
        }
        self.record_execution(session_id, envelope)
        if store:
            store.record_audit_event(
                "tool.execute",
                decision="allow" if ok else "error",
                session_id=session_id,
                task_id=task_id,
                resource_type="tool",
                resource_id=name,
                reason=envelope["error"],
                details={
                    "duration_ms": duration_ms,
                    "requires_confirmation": requires_confirmation,
                    "risk_level": envelope["risk_level"],
                    "arguments": args_obj,
                },
            )
        if task_step and store:
            store.finish_task_step(
                task_step["id"],
                status=self.task_step_status(envelope["status"]),
                output_data=envelope,
                error=envelope["error"],
            )
        return envelope
