import asyncio
import json
import tempfile
import time
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.autonomous_subagent_service import AutonomousSubagentService, SubagentRoleSpec


def payload(summary="ok", confidence=0.9, **extra):
    return json.dumps({"summary": summary, "claims": [], "evidence": [], "artifacts": [], "proposed_actions": [], "confidence": confidence, "open_risks": [], "hard_gate_failures": [], "requires_human_approval": False, **extra})


class FakeProvider:
    def __init__(self, role, captures, delay=0.0, tool_call=None, content=None):
        self.role = role
        self.captures = captures
        self.delay = delay
        self.tool_call = tool_call
        self.content = content
        self.calls = 0

    async def complete(self, messages, options=None, **_kwargs):
        self.calls += 1
        self.captures.setdefault(self.role, []).append(messages)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.tool_call and self.calls == 1:
            message = {"role": "assistant", "content": "", "tool_calls": [{"id": "call-1", "function": {"name": self.tool_call, "arguments": "{}"}}]}
            return {"ok": True, "provider": "fake", "model": "fake", "content": "", "raw": {"choices": [{"message": message}]}, "usage": {"total_tokens": 10}}
        content = self.content or payload(self.role)
        return {"ok": True, "provider": "fake", "model": "fake", "content": content, "raw": {"choices": [{"message": {"role": "assistant", "content": content}}]}, "usage": {"total_tokens": 10}}


class AutonomousSubagentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_advanced_data_team_and_output_contract_repair(self):
        captures = {}
        invalid = json.dumps({"summary": "first", "confidence": 2})
        class RepairProvider(FakeProvider):
            async def complete(self, messages, options=None, **kwargs):
                if self.calls == 0:
                    self.calls += 1; self.captures.setdefault(self.role, []).append(messages)
                    return {"ok": True, "provider": "fake", "model": "fake", "content": invalid, "raw": {"choices": [{"message": {"content": invalid}}]}, "usage": {"total_tokens": 10}}
                return await super().complete(messages, options, **kwargs)
        with tempfile.TemporaryDirectory() as td:
            roles = AutonomousSubagentService.advanced_data_team("Analyze sales", source_description="sales table")
            self.assertEqual([item.role_id for item in roles], ["data_profiler", "data_analyst", "workbook_builder", "quality_reviewer"])
            self.assertTrue(roles[-1].hard_gate)
            service = AutonomousSubagentService(lambda spec: RepairProvider(spec.role_id, captures), checkpoint_root=Path(td), max_concurrency=2)
            result = await service.run("Analyze sales", roles)
            self.assertEqual(result["status"], "passed", result)
            self.assertTrue(any(trace["type"] == "output_repair" for item in result["results"].values() for trace in item["trace"]))

    async def test_roles_use_independent_model_calls_and_dependency_packets(self):
        captures = {}
        with tempfile.TemporaryDirectory() as td:
            service = AutonomousSubagentService(lambda spec: FakeProvider(spec.role_id, captures), checkpoint_root=Path(td))
            result = await service.run("Build release", [
                SubagentRoleSpec("planner", "Plan only", "Create plan"),
                SubagentRoleSpec("researcher", "Research only", "Collect evidence"),
                SubagentRoleSpec("reviewer", "Review evidence", "Review outputs", depends_on=["planner", "researcher"], hard_gate=True),
            ])
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["execution_mode"], "model_driven_autonomous")
            self.assertEqual(set(captures), {"planner", "researcher", "reviewer"})
            planner_packet = json.loads(captures["planner"][0][1]["content"])
            researcher_packet = json.loads(captures["researcher"][0][1]["content"])
            reviewer_packet = json.loads(captures["reviewer"][0][1]["content"])
            self.assertEqual(planner_packet["dependencies"], {})
            self.assertEqual(researcher_packet["dependencies"], {})
            self.assertEqual(set(reviewer_packet["dependencies"]), {"planner", "researcher"})
            self.assertNotEqual(result["results"]["planner"]["context_hash"], result["results"]["reviewer"]["context_hash"])

    async def test_independent_roles_execute_concurrently(self):
        captures = {}
        with tempfile.TemporaryDirectory() as td:
            service = AutonomousSubagentService(lambda spec: FakeProvider(spec.role_id, captures, delay=0.15), checkpoint_root=Path(td), max_concurrency=2)
            started = time.perf_counter()
            result = await service.run("Parallel", [SubagentRoleSpec("a", "A", "A"), SubagentRoleSpec("b", "B", "B")])
            elapsed = time.perf_counter() - started
            self.assertEqual(result["status"], "passed")
            self.assertLess(elapsed, 0.28)

    async def test_role_tool_allowlist_and_side_effect_gate(self):
        captures = {}
        with tempfile.TemporaryDirectory() as td:
            denied = AutonomousSubagentService(lambda spec: FakeProvider(spec.role_id, captures, tool_call="shell_exec"), checkpoint_root=Path(td) / "a", tool_definitions=[{"function": {"name": "shell_exec", "parameters": {"type": "object"}}}], tool_executor=lambda *_: {"ok": True})
            result = await denied.run("Denied", [SubagentRoleSpec("reviewer", "Review", "Review", allowed_tools=["knowledge_search"], hard_gate=True)])
            self.assertEqual(result["status"], "failed")

            gated = AutonomousSubagentService(lambda spec: FakeProvider(spec.role_id, captures, tool_call="shell_exec"), checkpoint_root=Path(td) / "b", tool_definitions=[{"function": {"name": "shell_exec", "parameters": {"type": "object"}}}], tool_executor=lambda *_: {"ok": True})
            result = await gated.run("Gate", [SubagentRoleSpec("builder", "Build", "Build", allowed_tools=["shell_exec"], hard_gate=True)])
            self.assertEqual(result["status"], "failed")
            self.assertIn("confirmation", result["arbitration"]["hard_gate_failures"][0])

    async def test_hard_gate_overrides_other_successes_and_low_confidence_needs_human(self):
        captures = {}
        with tempfile.TemporaryDirectory() as td:
            def factory(spec):
                content = payload(spec.role_id, confidence=0.9)
                if spec.role_id == "risk":
                    content = payload("unsafe", hard_gate_failures=["security review failed"])
                return FakeProvider(spec.role_id, captures, content=content)
            service = AutonomousSubagentService(factory, checkpoint_root=Path(td) / "hard")
            result = await service.run("Release", [SubagentRoleSpec("builder", "Build", "Build"), SubagentRoleSpec("risk", "Risk", "Risk", depends_on=["builder"], hard_gate=True)])
            self.assertEqual(result["status"], "failed")
            self.assertIn("security review failed", result["arbitration"]["hard_gate_failures"][0])

            low = AutonomousSubagentService(lambda spec: FakeProvider(spec.role_id, captures, content=payload("uncertain", confidence=0.4)), checkpoint_root=Path(td) / "low")
            result = await low.run("Uncertain", [SubagentRoleSpec("analyst", "Analyze", "Analyze")])
            self.assertEqual(result["status"], "human_gate")

    async def test_budget_is_hard_and_checkpoint_is_written(self):
        captures = {}
        with tempfile.TemporaryDirectory() as td:
            service = AutonomousSubagentService(lambda spec: FakeProvider(spec.role_id, captures), checkpoint_root=Path(td))
            result = await service.run("Budget", [SubagentRoleSpec("a", "A", "A"), SubagentRoleSpec("b", "B", "B")], run_budget={"max_model_calls": 1, "max_tokens": 10000})
            self.assertIn(result["status"], {"budget_exhausted", "human_gate"})
            self.assertEqual(result["budget"]["model_calls"], 1)
            self.assertTrue(Path(result["checkpoint"]).is_file())

    async def test_reviewer_rejection_drives_executor_rework_and_release(self):
        captures = {}
        calls = {}

        class ReviewCycleProvider(FakeProvider):
            async def complete(self, messages, options=None, **kwargs):
                calls[self.role] = calls.get(self.role, 0) + 1
                self.captures.setdefault(self.role, []).append(messages)
                if self.role == "reviewer" and calls[self.role] == 1:
                    content = payload("Reject v1", hard_gate_failures=["missing passing test evidence"])
                elif self.role == "reviewer":
                    content = payload("Release v2", confidence=0.97)
                elif self.role == "executor" and calls[self.role] > 1:
                    content = payload("Reworked v2 with passing test evidence", confidence=0.95)
                else:
                    content = payload(f"{self.role} v1")
                return {"ok": True, "provider": "fake", "model": "fake", "content": content, "raw": {"choices": [{"message": {"content": content}}]}, "usage": {"total_tokens": 10}}

        with tempfile.TemporaryDirectory() as td:
            service = AutonomousSubagentService(lambda spec: ReviewCycleProvider(spec.role_id, captures), checkpoint_root=Path(td))
            roles = [
                SubagentRoleSpec("planner", "Plan", "Plan the change"),
                SubagentRoleSpec("executor", "Execute", "Implement and test", depends_on=["planner"]),
                SubagentRoleSpec("reviewer", "Review independently", "Gate evidence", depends_on=["executor"], hard_gate=True),
            ]
            result = await service.run(
                "Repair a repository defect",
                roles,
                review_cycle={"executor_role": "executor", "reviewer_role": "reviewer", "max_rounds": 2},
            )
            self.assertEqual(result["status"], "passed", result)
            self.assertEqual(calls, {"planner": 1, "executor": 2, "reviewer": 2})
            self.assertEqual(len(result["review_cycle"]["disagreements"]), 1)
            self.assertEqual(result["review_cycle"]["rounds"][0]["status"], "released")
            self.assertEqual(result["review_cycle"]["release"]["reviewer_role"], "reviewer")
            rework_packet = json.loads(captures["executor"][1][1]["content"])
            self.assertEqual(rework_packet["evidence"][-1]["type"], "reviewer_rework_request")
            checkpoint = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["review_cycle"]["release"]["status"], "released")
            event_names = [item["event"] for item in result["events"]]
            self.assertIn("reviewer_rejected", event_names)
            self.assertIn("reviewer_released", event_names)
            self.assertTrue(all(item.get("timestamp") for item in result["events"]))

    async def test_tool_trace_has_timestamp_duration_and_status(self):
        captures = {}
        with tempfile.TemporaryDirectory() as td:
            service = AutonomousSubagentService(
                lambda spec: FakeProvider(spec.role_id, captures, tool_call="shell_exec"),
                checkpoint_root=Path(td),
                tool_definitions=[{"function": {"name": "shell_exec", "parameters": {"type": "object"}}}],
                tool_executor=lambda *_: {"ok": True},
            )
            result = await service.run(
                "Audited tool call",
                [SubagentRoleSpec("executor", "Execute", "Run approved check", allowed_tools=["shell_exec"])],
                confirmed_side_effect_tools=["shell_exec"],
            )
            self.assertEqual(result["status"], "passed", result)
            tool_trace = next(item for item in result["results"]["executor"]["trace"] if item["type"] == "tool")
            self.assertEqual(tool_trace["status"], "passed")
            self.assertIn("timestamp", tool_trace)
            self.assertIn("completed_at", tool_trace)
            self.assertGreaterEqual(tool_trace["duration_ms"], 0)

    async def test_cancel_persists_completed_parallel_role_for_resume(self):
        captures={}
        with tempfile.TemporaryDirectory() as td:
            slow=True
            def factory(spec):
                return FakeProvider(spec.role_id,captures,delay=100 if slow and spec.role_id=="b" else .01)
            service=AutonomousSubagentService(factory,checkpoint_root=td,max_concurrency=2)
            roles=[SubagentRoleSpec("a","A","A"),SubagentRoleSpec("b","B","B")]
            task=asyncio.create_task(service.run("Recover",roles))
            checkpoint=None
            try:
                for _ in range(100):
                    found=list(Path(td).glob("*/checkpoint.json"))
                    if found:
                        checkpoint=found[0];break
                    await asyncio.sleep(.02)
                self.assertIsNotNone(checkpoint)
                saved=json.loads(checkpoint.read_text())
                self.assertEqual(saved["completed"]["a"]["status"],"passed")
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            slow=False
            result=await service.run("Recover",roles,resume_checkpoint=str(checkpoint))
            self.assertEqual(result["status"],"passed")
            self.assertEqual(len(captures["a"]),1)


if __name__ == "__main__":
    unittest.main()
