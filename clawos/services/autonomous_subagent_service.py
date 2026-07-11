from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .runtime_records import RunRecord, now_iso


SIDE_EFFECT_TOOLS = {"file_write", "shell_exec", "git_workspace", "office_artifact", "office_productivity", "meeting_workflow", "scholarly_download", "coding_workflow"}


@dataclass
class SubagentRoleSpec:
    role_id: str
    system_policy: str
    objective: str
    allowed_tools: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    model_profile: str = "reasoning"
    policy_version: str = "v1"
    max_model_calls: int = 3
    max_tool_calls: int = 6
    max_tokens: int = 3000
    timeout_seconds: int = 120
    hard_gate: bool = False


class AutonomousSubagentService:
    """Bounded model-driven subagents with isolated context, DAG scheduling and hard gates."""

    def __init__(
        self,
        provider_factory: Callable[[SubagentRoleSpec], Any],
        *,
        tool_executor: Callable[[str, dict[str, Any], dict[str, Any]], Any] | None = None,
        tool_definitions: list[dict[str, Any]] | None = None,
        store: Any | None = None,
        checkpoint_root: str | Path = "output/subagents",
        max_concurrency: int = 3,
    ):
        self.provider_factory = provider_factory
        self.tool_executor = tool_executor
        self.tool_definitions = tool_definitions or []
        self.store = store
        self.checkpoint_root = Path(checkpoint_root).expanduser().resolve()
        self.max_concurrency = max(1, min(int(max_concurrency or 3), 8))

    async def run(
        self,
        objective: str,
        roles: list[SubagentRoleSpec | dict[str, Any]],
        *,
        shared_evidence: list[dict[str, Any]] | None = None,
        confirmed_side_effect_tools: list[str] | None = None,
        run_budget: dict[str, Any] | None = None,
        resume_checkpoint: str = "",
        actor: str = "coordinator",
    ) -> dict[str, Any]:
        specs = [item if isinstance(item, SubagentRoleSpec) else SubagentRoleSpec(**item) for item in roles]
        self._validate_roles(specs)
        budget = {
            "max_model_calls": 20,
            "max_tool_calls": 30,
            "max_tokens": 20_000,
            "max_wall_ms": 600_000,
            **(run_budget or {}),
        }
        run_id = f"subagents-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        root = self.checkpoint_root / run_id
        completed: dict[str, dict[str, Any]] = {}
        if resume_checkpoint:
            checkpoint = Path(resume_checkpoint).expanduser().resolve()
            try:
                checkpoint.relative_to(self.checkpoint_root)
            except ValueError as exc:
                raise ValueError("resume checkpoint is outside the subagent root") from exc
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            run_id = str(saved["run_id"])
            root = checkpoint.parent
            completed = dict(saved.get("completed") or {})
        root.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        ledger = {"model_calls": 0, "tool_calls": 0, "tokens": 0, "estimated_tokens": False}
        budget_lock = asyncio.Lock()
        events = []
        confirmed = set(confirmed_side_effect_tools or [])
        pending = {item.role_id: item for item in specs if item.role_id not in completed}
        semaphore = asyncio.Semaphore(self.max_concurrency)
        while pending:
            if (time.perf_counter() - started) * 1000 > int(budget["max_wall_ms"]):
                break
            ready = [item for item in pending.values() if set(item.depends_on) <= set(completed)]
            if not ready:
                raise ValueError("subagent dependency graph is cyclic or blocked")
            async def launch(spec: SubagentRoleSpec):
                async with semaphore:
                    return await self._run_role(objective, spec, completed, shared_evidence or [], confirmed, ledger, budget, events, budget_lock)
            results = await asyncio.gather(*(launch(item) for item in ready))
            for spec, result in zip(ready, results):
                completed[spec.role_id] = result
                pending.pop(spec.role_id, None)
                self._write_checkpoint(root, run_id, objective, specs, completed, ledger, events)
                if result["status"] in {"failed", "budget_exhausted", "human_gate"} and spec.hard_gate:
                    pending.clear()
                    break
        arbitration = self._arbitrate(specs, completed)
        status = arbitration["status"]
        payload = {
            "schema": "clawos.autonomous-subagents.v1",
            "run_id": run_id,
            "execution_mode": "model_driven_autonomous",
            "objective": objective,
            "status": status,
            "roles": [asdict(item) for item in specs],
            "results": completed,
            "arbitration": arbitration,
            "budget": {**budget, **ledger},
            "events": events,
            "checkpoint": str(root / "checkpoint.json"),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "human_approval_required": status == "human_gate",
        }
        self._write_checkpoint(root, run_id, objective, specs, completed, ledger, events, arbitration)
        self._save_run(payload, actor)
        return payload

    async def _run_role(self, objective: str, spec: SubagentRoleSpec, completed: dict[str, dict[str, Any]], shared_evidence: list[dict[str, Any]], confirmed: set[str], ledger: dict[str, Any], budget: dict[str, Any], events: list[dict[str, Any]], budget_lock: asyncio.Lock) -> dict[str, Any]:
        dependency_outputs = {key: self._public_result(completed[key]) for key in spec.depends_on}
        packet = {
            "role_id": spec.role_id,
            "objective": objective,
            "assignment": spec.objective,
            "dependencies": dependency_outputs,
            "evidence": shared_evidence,
            "required_output": {"summary": "string", "claims": [], "evidence": [], "artifacts": [], "proposed_actions": [], "confidence": "0..1", "open_risks": [], "hard_gate_failures": [], "requires_human_approval": "boolean"},
        }
        messages = [
            {"role": "system", "content": spec.system_policy + "\nNever reveal hidden reasoning. Return concise JSON matching required_output. Use only allowed tools."},
            {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
        ]
        provider = self.provider_factory(spec)
        trace = []
        local_model_calls = local_tool_calls = local_tokens = 0
        output: dict[str, Any] = {}
        status = "failed"
        error = ""
        tools = self._tools_for(spec.allowed_tools)
        for attempt in range(1, max(1, min(spec.max_model_calls, 8)) + 1):
            estimated = sum(len(str(item.get("content") or "")) for item in messages) // 4 + 1
            async with budget_lock:
                if ledger["model_calls"] >= int(budget["max_model_calls"]) or ledger["tokens"] + estimated > int(budget["max_tokens"]):
                    status, error = "budget_exhausted", "run model/token budget exhausted"
                    break
                ledger["model_calls"] += 1
                ledger["tokens"] += estimated
            started = time.perf_counter()
            try:
                result = await asyncio.wait_for(provider.complete(messages, {"temperature": 0.0, "max_tokens": spec.max_tokens, "tools": tools}), timeout=max(1, min(spec.timeout_seconds, 600)))
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "content": "", "raw": {}, "usage": {}}
            usage = result.get("usage") or {}
            used_tokens = int(usage.get("total_tokens") or estimated)
            estimated_flag = not bool(usage.get("total_tokens"))
            async with budget_lock:
                ledger["tokens"] += used_tokens - estimated
                ledger["estimated_tokens"] = ledger["estimated_tokens"] or estimated_flag
            local_model_calls += 1
            local_tokens += used_tokens
            invocation = {"attempt": attempt, "ok": bool(result.get("ok")), "provider": result.get("provider", ""), "model": result.get("model", ""), "duration_ms": round((time.perf_counter() - started) * 1000, 2), "tokens": used_tokens, "tokens_estimated": estimated_flag, "prompt_hash": self._hash_json(messages), "error": result.get("error", "")}
            trace.append({"type": "model", **invocation})
            events.append({"role_id": spec.role_id, "event": "model_invocation", **invocation})
            if not result.get("ok"):
                error = str(result.get("error") or "provider failed")
                if attempt < spec.max_model_calls:
                    await asyncio.sleep(min(0.1 * attempt, 0.5))
                    continue
                break
            raw_message = (((result.get("raw") or {}).get("choices") or [{}])[0].get("message") or {})
            tool_calls = raw_message.get("tool_calls") or []
            if tool_calls:
                messages.append({"role": "assistant", "content": raw_message.get("content") or "", "tool_calls": tool_calls})
                for call in tool_calls:
                    name = str((call.get("function") or {}).get("name") or "")
                    if name not in spec.allowed_tools:
                        status, error = "failed", f"role tool policy denied: {name}"
                        break
                    async with budget_lock:
                        if ledger["tool_calls"] >= int(budget["max_tool_calls"]) or local_tool_calls >= spec.max_tool_calls:
                            status, error = "budget_exhausted", "tool budget exhausted"
                            break
                        ledger["tool_calls"] += 1
                    if name in SIDE_EFFECT_TOOLS and name not in confirmed:
                        status, error = "human_gate", f"side-effect tool requires confirmation: {name}"
                        break
                    arguments_raw = (call.get("function") or {}).get("arguments") or "{}"
                    try:
                        arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else dict(arguments_raw)
                    except (TypeError, json.JSONDecodeError):
                        arguments = {}
                    tool_result = await self._execute_tool(name, arguments, {"role_id": spec.role_id, "objective": objective, "confirmed_tools": sorted(confirmed)})
                    local_tool_calls += 1
                    trace.append({"type": "tool", "name": name, "arguments_hash": self._hash_json(arguments), "result_hash": self._hash_json(tool_result), "ok": not bool(tool_result.get("error") if isinstance(tool_result, dict) else False)})
                    messages.append({"role": "tool", "tool_call_id": call.get("id", f"call-{local_tool_calls}"), "name": name, "content": json.dumps(tool_result, ensure_ascii=False)[:12000]})
                if status in {"failed", "budget_exhausted", "human_gate"}:
                    break
                continue
            output = self._parse_output(result.get("content") or raw_message.get("content") or "")
            status = "human_gate" if output.get("requires_human_approval") else "passed"
            break
        return {
            "role_id": spec.role_id,
            "status": status,
            "output": output,
            "trace": trace,
            "metrics": {"model_calls": local_model_calls, "tool_calls": local_tool_calls, "tokens": local_tokens},
            "context_hash": self._hash_json(packet),
            "dependency_roles": spec.depends_on,
            "error": error,
        }

    async def _execute_tool(self, name: str, arguments: dict[str, Any], context: dict[str, Any]) -> Any:
        if not self.tool_executor:
            return {"error": "tool executor unavailable"}
        result = self.tool_executor(name, arguments, context)
        return await result if asyncio.iscoroutine(result) else result

    def _arbitrate(self, specs: list[SubagentRoleSpec], completed: dict[str, dict[str, Any]]) -> dict[str, Any]:
        hard_failures = []
        human_reasons = []
        confidences = []
        budget_failures = []
        for spec in specs:
            result = completed.get(spec.role_id) or {}
            output = result.get("output") or {}
            if spec.hard_gate and result.get("status") != "passed":
                hard_failures.append(f"{spec.role_id}: {result.get('error') or result.get('status')}")
            hard_failures.extend(f"{spec.role_id}: {item}" for item in (output.get("hard_gate_failures") or []))
            if result.get("status") == "human_gate" or output.get("requires_human_approval"):
                human_reasons.append(f"{spec.role_id}: human approval requested")
            if result.get("status") == "budget_exhausted":
                budget_failures.append(spec.role_id)
            try:
                confidences.append(float(output.get("confidence")))
            except (TypeError, ValueError):
                pass
        if hard_failures:
            status = "failed"
        elif human_reasons or (confidences and min(confidences) < 0.55):
            status = "human_gate"
            if confidences and min(confidences) < 0.55:
                human_reasons.append("one or more roles have confidence below 0.55")
        elif budget_failures or len(completed) < len(specs):
            status = "budget_exhausted"
        else:
            status = "passed"
        return {"status": status, "hard_gate_failures": hard_failures, "human_gate_reasons": human_reasons, "average_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None, "rule": "hard safety/test/evidence gates override judge or majority"}

    def _tools_for(self, allowed: list[str]) -> list[dict[str, Any]]:
        return [item for item in self.tool_definitions if str(item.get("function", item).get("name") or "") in allowed]

    @staticmethod
    def _parse_output(content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {"summary": text, "confidence": 0.5}
        except json.JSONDecodeError:
            match = __import__("re").search(r"\{[\s\S]*\}", text)
            if match:
                try:
                    value = json.loads(match.group(0))
                    if isinstance(value, dict):
                        return value
                except json.JSONDecodeError:
                    pass
        return {"summary": text, "claims": [], "evidence": [], "artifacts": [], "proposed_actions": [], "confidence": 0.5, "open_risks": ["unstructured model output"], "hard_gate_failures": [], "requires_human_approval": True}

    @staticmethod
    def _public_result(result: dict[str, Any]) -> dict[str, Any]:
        return {"role_id": result.get("role_id"), "status": result.get("status"), "output": result.get("output") or {}, "metrics": result.get("metrics") or {}}

    @staticmethod
    def _validate_roles(specs: list[SubagentRoleSpec]) -> None:
        ids = [item.role_id for item in specs]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("roles require unique role_id values")
        valid = set(ids)
        for item in specs:
            if item.role_id in item.depends_on or not set(item.depends_on) <= valid:
                raise ValueError(f"invalid dependencies for role: {item.role_id}")

    @staticmethod
    def _hash_json(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

    def _write_checkpoint(self, root: Path, run_id: str, objective: str, specs: list[SubagentRoleSpec], completed: dict[str, Any], ledger: dict[str, Any], events: list[dict[str, Any]], arbitration: dict[str, Any] | None = None) -> None:
        payload = {"schema": "clawos.subagent-checkpoint.v1", "run_id": run_id, "objective": objective, "roles": [asdict(item) for item in specs], "completed": completed, "ledger": ledger, "events": events, "arbitration": arbitration or {}, "updated_at": now_iso()}
        temporary = root / ".checkpoint.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(root / "checkpoint.json")

    def _save_run(self, payload: dict[str, Any], actor: str) -> None:
        if not self.store:
            return
        run = RunRecord(run_id=payload["run_id"], run_type="autonomous_subagents", title=payload["objective"], status=payload["status"], actor=actor, scenario="multi_agent", completed_at=now_iso(), inputs={"roles": payload["roles"]}, outputs={"arbitration": payload["arbitration"], "checkpoint": payload["checkpoint"]}, metrics={**payload["budget"], "duration_ms": payload["duration_ms"], "role_count": len(payload["results"])}, workflow={"scheduler": "dependency_dag", "execution_mode": payload["execution_mode"]}, tags=["subagent", "model-driven", "isolated-context", "budgeted"])
        run.add_artifact("checkpoint", "Autonomous subagent checkpoint", payload["checkpoint"])
        for role_id, result in payload["results"].items():
            run.add_evidence("subagent_role", f"{role_id} completed with status {result.get('status')}", citation=f"run:{payload['run_id']}#role={role_id}", score=(result.get("output") or {}).get("confidence"))
        for failure in payload["arbitration"].get("hard_gate_failures") or []:
            run.add_failure_case("subagent_hard_gate", failure, severity="high", remediation="Resolve the hard gate and resume from checkpoint.")
        self.store.save_run_record(run.to_dict())
