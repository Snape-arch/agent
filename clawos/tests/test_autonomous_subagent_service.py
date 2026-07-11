import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
