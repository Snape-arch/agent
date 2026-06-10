import asyncio
import contextlib
import importlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MemoryAndRoutingTests(unittest.TestCase):
    def test_chinese_memory_ingestion_extracts_profile_and_preference(self):
        from memoryos.context_builder import ContextBuilder
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            builder = ContextBuilder(store)

            extracted = builder.ingest_and_store(
                "s1",
                "user",
                "我叫陈同学，我的研究方向是智能体系统。我喜欢简洁直接的中文回复。",
            )

            self.assertTrue(extracted["profiles"])
            self.assertTrue(extracted["preferences"])
            profiles = {p["key"]: p["value"] for p in store.get_all_profiles()}
            prefs = {p["key"]: p["value"] for p in store.get_all_preferences()}
            self.assertEqual(profiles["name"], "陈同学")
            self.assertIn("智能体系统", profiles["research_direction"])
            self.assertIn("简洁直接", prefs["reply_style"])

    def test_memory_history_tool_returns_history_without_unknown_tool_error(self):
        from memoryos.memory_store import MemoryStore
        from scripts import tool_runner

        with tempfile.TemporaryDirectory() as td:
            old_base = tool_runner.BASE_DIR
            tool_runner.BASE_DIR = td
            try:
                store = MemoryStore(str(Path(td) / "memoryos.db"))
                store.add_message("s1", "user", "hello")
                tool_runner.input_data = {"session_id": "s1", "limit": 5}
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    tool_runner.tool_memory_history()
                payload = json.loads(out.getvalue())
                self.assertEqual(payload["count"], 1)
                self.assertEqual(payload["messages"][0]["content"], "hello")
                self.assertNotIn("error", payload)
            finally:
                tool_runner.BASE_DIR = old_base

    def test_rule_based_tool_recognizes_chinese_memory_and_tool_queries(self):
        server = importlib.import_module("clawos_server")

        self.assertEqual(server.rule_based_tool("查看记忆历史")[0], "memory_history")
        self.assertEqual(server.rule_based_tool("查看我的偏好")[0], "memory_preference_get")
        self.assertEqual(server.rule_based_tool("查看我的画像")[0], "memory_profile_get")
        self.assertEqual(server.rule_based_tool("查看工具列表")[0], "tools_list")

    def test_run_tool_loop_prefers_rule_based_memory_route_over_skill_match(self):
        server = importlib.import_module("clawos_server")
        old_execute = server.execute_python_tool
        server.execute_python_tool = lambda name, args: {"called": name, "args": args}
        try:
            result = asyncio.run(server.run_tool_loop("查看记忆历史", "s1"))
        finally:
            server.execute_python_tool = old_execute

        self.assertTrue(result["used_tools"])
        self.assertEqual(result["tool_calls"][0]["name"], "memory_history")

    def test_skill_matching_ignores_garbled_question_mark_triggers(self):
        from skills.skill_registry import match_skill_by_text

        self.assertIsNone(match_skill_by_text("??????"))

    def test_tool_execution_returns_structured_envelope(self):
        server = importlib.import_module("clawos_server")
        result = server.execute_tool_call("time_now", "{}", "s1")

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "time_now")
        self.assertEqual(result["arguments"], {})
        self.assertIn("data", result)
        self.assertIn("duration_ms", result)
        self.assertFalse(result["requires_confirmation"])

    def test_dangerous_tool_requires_confirmation_before_execution(self):
        server = importlib.import_module("clawos_server")
        old_execute = server.execute_python_tool
        called = []
        server.execute_python_tool = lambda name, args: called.append((name, args)) or {"ran": True}
        try:
            result = server.execute_tool_call("shell_exec", "{\"command\":\"echo hi\"}", "s1")
        finally:
            server.execute_python_tool = old_execute

        self.assertFalse(result["ok"])
        self.assertTrue(result["requires_confirmation"])
        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(called, [])

    def test_memory_store_records_tool_execution_log(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.record_tool_execution(
                session_id="s1",
                tool_name="time_now",
                arguments={"x": 1},
                result={"ok": True, "data": {"x": 2}},
                status="success",
                duration_ms=12.5,
                requires_confirmation=False,
            )
            rows = store.list_tool_executions("s1", limit=5)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tool_name"], "time_now")
        self.assertEqual(rows[0]["status"], "success")
        self.assertEqual(rows[0]["arguments"]["x"], 1)
        self.assertTrue(rows[0]["result"]["ok"])


if __name__ == "__main__":
    unittest.main()
