import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
MTCLAW_ROOT = REPO_ROOT / "MTClaw-框架代码"
for path in (ROOT, MTCLAW_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class MTClawAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_uses_real_mtclaw_api_and_tool_history_contract(self):
        from function_router import server as mt_server
        from mtclaw.adapter import MTClawAdapter

        old_config = mt_server.STATE.config
        old_tools = mt_server.STATE.tools
        old_loop = mt_server.run_tool_loop
        mt_server.TOOL_HISTORY.clear()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mt_server.STATE.config = mt_server.AppConfig(
                listen_host="127.0.0.1",
                listen_port=18791,
                routing=mt_server.ModelConfig("http://router/v1", "router", "any"),
                upstream=mt_server.ModelConfig("http://upstream/v1", "upstream", "any"),
                functions_file="functions.jsonl",
                scripts_dir="scripts",
                max_tool_rounds=3,
                tool_exec_timeout_s=30,
                root_dir=root,
                config_path=root / "config.json",
                fr_completion_check_always_true=True,
            )
            mt_server.STATE.tools = [{
                "type": "function",
                "function": {"name": "time_now", "parameters": {"type": "object"}},
            }]

            async def fake_loop(user_text, history=None):
                tool_call = {
                    "id": "call_time",
                    "type": "function",
                    "function": {"name": "time_now", "arguments": "{}"},
                }
                return mt_server.ToolLoopResult(
                    used_any_tool=True,
                    last_function_name="time_now",
                    tool_rounds=2,
                    tool_context=[
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": "", "tool_calls": [tool_call]},
                        {
                            "role": "tool",
                            "tool_call_id": "call_time",
                            "name": "time_now",
                            "content": json.dumps({"datetime": "2026-06-13 22:00:00"}),
                        },
                    ],
                    max_rounds_exhausted=False,
                    qwen_reply="当前时间是 2026-06-13 22:00:00。",
                    _loop_messages=[],
                )

            mt_server.run_tool_loop = fake_loop
            transport = httpx.ASGITransport(app=mt_server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://mtclaw") as client:
                adapter = MTClawAdapter(
                    {"enabled": True, "base_url": "http://mtclaw", "model": "function-router"},
                    http_client=client,
                )
                result = await adapter.route(
                    [{"role": "user", "content": "现在几点"}],
                    "session-proof-001",
                )

        mt_server.run_tool_loop = old_loop
        mt_server.STATE.config = old_config
        mt_server.STATE.tools = old_tools

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "mtclaw")
        self.assertIn("2026-06-13", result["content"])
        self.assertEqual(result["trace"][0]["session_key"], "session-proof-001")
        self.assertEqual(result["trace"][0]["function_name"], "time_now")
        self.assertEqual(result["trace"][0]["tool_result"]["datetime"], "2026-06-13 22:00:00")

    def test_prepare_runtime_exposes_only_safe_clawos_tools(self):
        from mtclaw.bridge_runner import SAFE_TOOLS
        from mtclaw.prepare_runtime import prepare

        with tempfile.TemporaryDirectory() as td:
            result = prepare(Path(td))
            functions = [
                json.loads(line)
                for line in Path(result["functions"]).read_text(encoding="utf-8").splitlines()
            ]
            wrappers = list((Path(td) / "scripts").glob("*.sh"))

        names = {item["name"] for item in functions}
        self.assertEqual(names, SAFE_TOOLS)
        self.assertEqual(len(wrappers), len(SAFE_TOOLS))
        self.assertNotIn("shell_exec", names)
        self.assertNotIn("file_write", names)
        self.assertNotIn("skill_delete", names)

    def test_prepare_runtime_writes_windows_cmd_wrappers(self):
        if os.name != "nt":
            self.skipTest("Windows-specific wrapper generation")

        from mtclaw.bridge_runner import SAFE_TOOLS
        from mtclaw.prepare_runtime import prepare

        with tempfile.TemporaryDirectory() as td:
            prepare(Path(td))
            wrappers = list((Path(td) / "scripts").glob("*.cmd"))
            sample = (Path(td) / "scripts" / "time_now.cmd").read_text(encoding="utf-8")

        self.assertEqual(len(wrappers), len(SAFE_TOOLS))
        self.assertIn("bridge_runner.py", sample)
        self.assertIn("time_now", sample)

    async def test_mtclaw_execute_tool_uses_windows_cmd_wrapper(self):
        if os.name != "nt":
            self.skipTest("Windows-specific tool execution")

        from function_router import server as mt_server

        old_config = mt_server.STATE.config
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "time_now.cmd").write_text(
                '@echo off\r\n'
                'echo {"result":"ok","tool_output":"windows-cmd"}\r\n',
                encoding="utf-8",
            )
            mt_server.STATE.config = mt_server.AppConfig(
                listen_host="127.0.0.1",
                listen_port=18791,
                routing=mt_server.ModelConfig("http://router/v1", "router", "any"),
                upstream=mt_server.ModelConfig("http://upstream/v1", "upstream", "any"),
                functions_file="functions.jsonl",
                scripts_dir="scripts",
                max_tool_rounds=3,
                tool_exec_timeout_s=30,
                root_dir=root,
                config_path=root / "config.json",
            )
            result = await mt_server.execute_tool("time_now", "{}")

        mt_server.STATE.config = old_config

        self.assertEqual(result["result"], "ok")
        self.assertEqual(result["tool_output"], "windows-cmd")

    def test_memory_store_persists_mtclaw_trace_evidence(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            trace_id = store.record_mtclaw_trace(
                "s1",
                "success",
                provider_url="http://127.0.0.1:18791",
                model="function-router",
                duration_ms=12.5,
                tool_history=[{"function_name": "time_now"}],
            )
            rows = store.list_mtclaw_traces("s1")

        self.assertGreater(trace_id, 0)
        self.assertEqual(rows[0]["route_status"], "success")
        self.assertEqual(rows[0]["tool_history"][0]["function_name"], "time_now")

    async def test_clawos_chat_endpoint_routes_through_mtclaw_adapter(self):
        import clawos_server as claw_server
        from memoryos.context_builder import ContextBuilder
        from memoryos.memory_store import MemoryStore

        class FakeAdapter:
            enabled = True
            fallback_on_error = True
            base_url = "http://127.0.0.1:18791"

            async def route(self, messages, session_id, options=None):
                return {
                    "ok": True,
                    "provider": "mtclaw",
                    "model": "function-router",
                    "content": "由 MTClaw 路由完成。",
                    "raw": {
                        "id": "fr-proof",
                        "object": "chat.completion",
                        "model": "function-router",
                        "choices": [{
                            "index": 0,
                            "message": {"role": "assistant", "content": "由 MTClaw 路由完成。"},
                            "finish_reason": "stop",
                        }],
                    },
                    "trace": [{
                        "session_key": session_id,
                        "function_name": "time_now",
                        "tool_input": {},
                        "tool_result": {"datetime": "2026-06-13 22:00:00"},
                    }],
                    "duration_ms": 9.5,
                    "error": "",
                }

        old_store = claw_server.g_memory_store
        old_builder = claw_server.g_context_builder
        old_adapter = claw_server.g_mtclaw_adapter
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            claw_server.g_memory_store = store
            claw_server.g_context_builder = ContextBuilder(store)
            claw_server.g_mtclaw_adapter = FakeAdapter()
            transport = httpx.ASGITransport(app=claw_server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://clawos") as client:
                response = await client.post("/v1/chat/completions", json={
                    "session_id": "competition-session",
                    "stream": False,
                    "messages": [{"role": "user", "content": "现在几点"}],
                })
                traces = store.list_mtclaw_traces("competition-session")

        claw_server.g_memory_store = old_store
        claw_server.g_context_builder = old_builder
        claw_server.g_mtclaw_adapter = old_adapter

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["clawos"]["mtclaw"]["used"])
        self.assertEqual(payload["clawos"]["tool_calls"][0]["name"], "time_now")
        self.assertEqual(traces[0]["route_status"], "success")


if __name__ == "__main__":
    unittest.main()
