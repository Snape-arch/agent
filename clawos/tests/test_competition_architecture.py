import asyncio
import contextlib
import io
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
for path in (ROOT, ROOT / "scripts", MTCLAW_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class CompetitionArchitectureTests(unittest.TestCase):
    def test_mtclaw_omits_empty_model_authorization_header(self):
        server_path = next(REPO_ROOT.glob("MTClaw-*/function_router/server.py"))
        source = server_path.read_text(encoding="utf-8")

        self.assertIn('def model_headers(api_key: str = "", include_content_type: bool = False)', source)
        self.assertIn('if str(api_key or "").strip():', source)
        self.assertNotIn('"Authorization": f"Bearer {STATE.config.routing.api_key}"', source)
        self.assertNotIn('"Authorization": f"Bearer {STATE.config.upstream.api_key}"', source)
        self.assertIn('"chat_template_kwargs": {"enable_thinking": False}', source)
        self.assertIn('proxied_request.setdefault(', source)
        self.assertIn('STATE.config.upstream.base_url.rstrip("/")', source)
        self.assertNotIn('"enable_thinking": False,', source)

    def test_vertical_acceptance_dataset_closes_seven_routes(self):
        from scripts.run_mtclaw_vertical_acceptance import run

        result = run(ROOT / "benchmarks" / "mtclaw_vertical_acceptance_v1.json")
        self.assertTrue(result["passed"])
        self.assertEqual(result["passed_count"], 7)
        self.assertEqual(result["failed_count"], 0)

    def test_scenario_strategy_filters_tools_and_prefers_specific_route(self):
        import clawos_server as server

        old_tools = server.tools_def
        server.tools_def = [
            {"type": "function", "function": {"name": "paper_deep_read"}},
            {"type": "function", "function": {"name": "shell_exec"}},
        ]
        try:
            strategy = server.build_routing_strategy("请精读这篇论文")
            routed = server.tools_for_routing_strategy(strategy)
        finally:
            server.tools_def = old_tools

        self.assertEqual(strategy["mode"], "enforced_scenario_routing")
        self.assertEqual(strategy["scenario"], "research")
        self.assertEqual([item["function"]["name"] for item in routed], ["paper_deep_read"])

    def test_tool_loop_passes_only_selected_scenario_tools_to_model(self):
        import clawos_server as server

        old_tools = server.tools_def
        old_has_key = server.has_api_key
        old_call = server.call_routing_llm
        captured = {}

        async def fake_call(messages, available_tools=None):
            captured["tools"] = [item["function"]["name"] for item in available_tools or []]
            return {"choices": [{"message": {"content": "research route selected", "tool_calls": []}}]}

        server.tools_def = [
            {"type": "function", "function": {"name": "paper_deep_read"}},
            {"type": "function", "function": {"name": "knowledge_search"}},
            {"type": "function", "function": {"name": "shell_exec"}},
        ]
        server.has_api_key = lambda section="routing": True
        server.call_routing_llm = fake_call
        try:
            result = asyncio.run(server.run_tool_loop("科研 citation verification", "route-proof"))
        finally:
            server.tools_def = old_tools
            server.has_api_key = old_has_key
            server.call_routing_llm = old_call

        self.assertEqual(result["routing_strategy"]["scenario"], "research")
        self.assertEqual(set(captured["tools"]), {"paper_deep_read", "knowledge_search"})
        self.assertNotIn("shell_exec", captured["tools"])

    def test_vertical_bridge_rejects_write_and_mutating_actions(self):
        from mtclaw.bridge_runner import enforce_safe_payload

        self.assertEqual(
            enforce_safe_payload("research_pdf", {"action": "search", "query": "RAG"})["action"],
            "search",
        )
        with self.assertRaises(PermissionError):
            enforce_safe_payload("research_pdf", {"action": "import", "file_path": "paper.pdf"})
        with self.assertRaises(PermissionError):
            enforce_safe_payload("paper_deep_read", {"text": "paper", "output_path": "report.md"})
        self.assertEqual(
            enforce_safe_payload("paper_intelligence", {"action": "compare", "document_ids": [1, 2]})["action"],
            "compare",
        )

    def test_generated_vertical_schemas_are_least_privilege(self):
        from mtclaw.prepare_runtime import prepare

        with tempfile.TemporaryDirectory() as td:
            result = prepare(Path(td))
            functions = {
                item["name"]: item
                for item in (
                    json.loads(line)
                    for line in Path(result["functions"]).read_text(encoding="utf-8").splitlines()
                )
            }
        self.assertNotIn("output_path", functions["paper_deep_read"]["parameters"]["properties"])
        self.assertEqual(
            set(functions["research_pdf"]["parameters"]["properties"]["action"]["enum"]),
            {"search", "validate_citations", "compare_matrix"},
        )
        self.assertEqual(
            set(functions["learning_workspace"]["parameters"]["properties"]["action"]["enum"]),
            {"get", "graph", "assessment"},
        )
        self.assertEqual(
            set(functions["paper_intelligence"]["parameters"]["properties"]["action"]["enum"]),
            {"structure", "align_claims", "compare", "readiness"},
        )
        self.assertNotIn("scholarly_search", functions)
        self.assertNotIn("scholarly_download", functions)
        self.assertEqual(set(functions["coding_workflow"]["parameters"]["properties"]["action"]["enum"]), {"inspect", "plan"})
        self.assertEqual(set(functions["office_productivity"]["parameters"]["properties"]["action"]["enum"]), {"inspect"})
        self.assertNotIn("confirmed", functions["coding_workflow"]["parameters"]["properties"])
        self.assertNotIn("output_path", functions["office_productivity"]["parameters"]["properties"])
        self.assertNotIn("autonomous_subagents", functions)

    def test_knowledge_search_tool_returns_local_evidence(self):
        from memoryos.memory_store import MemoryStore
        import tool_runner

        with tempfile.TemporaryDirectory() as td:
            old_db = os.environ.get("CLAWOS_MEMORY_DB")
            os.environ["CLAWOS_MEMORY_DB"] = str(Path(td) / "memory.db")
            try:
                store = MemoryStore(os.environ["CLAWOS_MEMORY_DB"])
                doc=store.add_document("RAG source")
                store.add_document_chunk(doc['id'],1,"Local citation evidence for paper reading.",f"doc:{doc['id']}#chunk=1")
                store.add_knowledge("RAG evidence", "Local citation evidence for paper reading.", "research", "doc:1#chunk=1")
                tool_runner.input_data = {"query": "citation evidence", "category": "research"}
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    tool_runner.tool_knowledge_search()
                payload = json.loads(output.getvalue())
            finally:
                if old_db is None:
                    os.environ.pop("CLAWOS_MEMORY_DB", None)
                else:
                    os.environ["CLAWOS_MEMORY_DB"] = old_db

        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["source"], "doc:1#chunk=1")
        self.assertTrue(payload["evidence_required"])

    def test_competition_config_requires_mtclaw_without_fallback(self):
        config = json.loads((ROOT / "config.competition.json").read_text(encoding="utf-8"))
        self.assertTrue(config["mtclaw"]["enabled"])
        self.assertFalse(config["mtclaw"]["fallback_on_error"])
        self.assertEqual(config["model_fallbacks"], [])


class CompetitionStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_chat_still_routes_through_mtclaw(self):
        import clawos_server as server

        class FakeAdapter:
            enabled = True
            fallback_on_error = False
            base_url = "http://127.0.0.1:18791"

            async def route(self, messages, session_id, options=None):
                return {
                    "ok": True,
                    "provider": "mtclaw",
                    "model": "function-router",
                    "content": "streamed through MTClaw",
                    "raw": {},
                    "trace": [{"function_name": "knowledge_search", "tool_input": {"query": "paper"}, "tool_result": {"count": 1}}],
                    "duration_ms": 3.0,
                    "error": "",
                }

        old_adapter = server.g_mtclaw_adapter
        old_store = server.g_memory_store
        old_builder = server.g_context_builder
        server.g_mtclaw_adapter = FakeAdapter()
        server.g_memory_store = None
        server.g_context_builder = None
        try:
            transport = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://clawos") as client:
                response = await client.post("/v1/chat/completions", json={
                    "session_id": "stream-proof",
                    "stream": True,
                    "messages": [{"role": "user", "content": "请检索论文知识"}],
                })
        finally:
            server.g_mtclaw_adapter = old_adapter
            server.g_memory_store = old_store
            server.g_context_builder = old_builder

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: clawos_meta", response.text)
        self.assertIn('"used": true', response.text)
        self.assertIn('"scenario": "research"', response.text)
        self.assertIn("streamed through MTClaw", response.text)


if __name__ == "__main__":
    unittest.main()
