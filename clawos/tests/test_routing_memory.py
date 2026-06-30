import asyncio
import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def body(self):
        return json.dumps(self._payload).encode("utf-8")

    async def json(self):
        return self._payload


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
            old_memory_db = os.environ.get("CLAWOS_MEMORY_DB")
            tool_runner.BASE_DIR = td
            os.environ["CLAWOS_MEMORY_DB"] = str(Path(td) / "memoryos.db")
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
                if old_memory_db is None:
                    os.environ.pop("CLAWOS_MEMORY_DB", None)
                else:
                    os.environ["CLAWOS_MEMORY_DB"] = old_memory_db

    def test_model_mode_labels_are_user_facing_modes(self):
        from services.model_service import ModelService

        self.assertEqual(ModelService.mode_label("deepseek", True), "API \u6a21\u5f0f")
        self.assertEqual(ModelService.mode_label("qwen_api", True), "API \u6a21\u5f0f")
        self.assertEqual(ModelService.mode_label("qwen", True), "\u672c\u5730\u6a21\u5f0f")
        self.assertEqual(ModelService.mode_label("mock", False), "\u79bb\u7ebf\u6a21\u5f0f")
        self.assertEqual(ModelService.mode_label("deepseek", False), "API \u5f85\u914d\u7f6e")

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

    def test_latest_deepseek_qwen_acceptance_api_summarizes_report(self):
        server = importlib.import_module("clawos_server")

        with tempfile.TemporaryDirectory() as td:
            fake_base = Path(td) / "clawos"
            report_dir = fake_base.parent / "output"
            fake_base.mkdir()
            report_dir.mkdir()
            (report_dir / "deepseek_hybrid_rag_acceptance.json").write_text(json.dumps({
                "ok": True,
                "model": "deepseek-chat",
                "benchmark": {
                    "name": "deepseek-qwen3-complex-task-acceptance-v2",
                    "case_count": 25,
                    "metrics": {
                        "pass_rate": 1.0,
                        "passed_count": 25,
                        "failed_count": 0,
                        "citation_hit_rate": 1.0,
                        "judge_grounded_rate": 1.0,
                        "latency_p50_ms": 1200.5,
                        "latency_p95_ms": 1800.25,
                    },
                },
                "cases": [
                    {
                        "scenario": "research",
                        "name": "Research synthesis",
                        "pass": True,
                        "citation_hit": True,
                        "latency_ms": 1100,
                        "vector_rank": 1,
                        "rerank_rank": 1,
                    }
                ],
            }), encoding="utf-8")
            old_base = server.BASE_DIR
            server.BASE_DIR = fake_base
            try:
                response = asyncio.run(server.api_latest_deepseek_qwen_acceptance())
                payload = json.loads(response.body.decode("utf-8"))
            finally:
                server.BASE_DIR = old_base

        self.assertTrue(payload["found"])
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["benchmark"]["case_count"], 25)
        self.assertEqual(payload["benchmark"]["metrics"]["citation_hit_rate"], 1.0)
        self.assertEqual(payload["cases"][0]["scenario"], "research")
        self.assertIn("deepseek_hybrid_rag_acceptance.json", payload["report_path"])

    def test_chat_attachments_become_hidden_context(self):
        server = importlib.import_module("clawos_server")
        context, meta = server._build_attachment_context([
            {
                "name": "notes.md",
                "type": "text/markdown",
                "size": 18,
                "content": "Agent should read this as context.",
            }
        ])

        self.assertIn("hidden attachment context", context)
        self.assertIn("notes.md", context)
        self.assertIn("Agent should read this as context.", context)
        self.assertEqual(meta[0]["name"], "notes.md")
        self.assertEqual(meta[0]["type"], "text/markdown")

    def test_uploaded_document_attachment_uses_indexed_chunks(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_memory_store = store
            try:
                doc = store.add_document(
                    title="Indexed Notes",
                    filename="notes.md",
                    file_hash="abc",
                    category="research",
                    metadata={"extractor": "text"},
                )
                store.add_document_chunk(
                    doc["id"],
                    1,
                    "Indexed retrieval chunk about agent document upload.",
                    f"doc:{doc['id']}#chunk=1",
                )
                context, meta = server._build_uploaded_document_context(
                    [{"document_id": doc["id"], "name": "notes.md"}],
                    "document upload",
                )
            finally:
                server.g_memory_store = old_store

        self.assertIn("hidden uploaded document context", context)
        self.assertIn("doc:", context)
        self.assertIn("Indexed retrieval chunk", context)
        self.assertEqual(meta[0]["document_id"], doc["id"])

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

    def test_network_fetch_requires_confirmation_and_reports_risk(self):
        import clawos_server as server
        from security.policy import ToolSecurityPolicy

        old_policy = server.g_security_policy
        old_execute = server.execute_python_tool
        called = []
        server.g_security_policy = ToolSecurityPolicy([Path.cwd()])
        server.execute_python_tool = lambda name, args: called.append((name, args)) or {"ran": True}
        try:
            result = server.execute_tool_call("web_fetch", json.dumps({"url": "https://example.com"}), "s1")
            allowed = server.g_security_policy.evaluate("web_fetch", {"url": "https://example.com"})
            denied = server.g_security_policy.evaluate("web_fetch", {"url": "http://127.0.0.1:8000"})
        finally:
            server.g_security_policy = old_policy
            server.execute_python_tool = old_execute

        self.assertEqual(result["status"], "needs_confirmation")
        self.assertEqual(result["risk_level"], "medium")
        self.assertEqual(called, [])
        self.assertEqual(allowed["decision"], "confirm")
        self.assertFalse(denied["allowed"])

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

    def test_tool_accuracy_endpoint_summarizes_execution_quality(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            try:
                server.g_memory_store.record_tool_execution("s1", "web_fetch", status="success", duration_ms=20, requires_confirmation=True)
                server.g_memory_store.record_tool_execution("s1", "web_fetch", status="error", duration_ms=10, requires_confirmation=True)
                resp = asyncio.run(server.api_tools_accuracy(session_id="s1"))
                payload = json.loads(resp.body)
            finally:
                server.g_memory_store = old_store

        self.assertEqual(payload["tools"][0]["tool"], "web_fetch")
        self.assertEqual(payload["tools"][0]["calls"], 2)
        self.assertEqual(payload["tools"][0]["success_rate"], 0.5)

    def test_routing_policy_returns_scored_strategy(self):
        import clawos_server as server

        resp = asyncio.run(server.api_routing_policy(q="请联网搜索一篇科研论文并入库生成引用回答"))
        payload = json.loads(resp.body)

        self.assertEqual(payload["scenario"], "research")
        self.assertIn("candidates", payload)
        self.assertGreater(payload["candidates"][0]["score"], 0)
        self.assertEqual(payload["strategy"]["mode"], "scored_policy_routing")
        self.assertEqual(payload["strategy"]["retrieval"], "citations_required")

    def test_document_ocr_citation_and_graph_endpoints(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_service = server.g_knowledge_service
            store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_memory_store = store
            server.g_knowledge_service = None
            try:
                doc = store.add_document(
                    "Web RAG Note",
                    filename="web.html",
                    file_hash="web-rag-note",
                    category="research",
                    extractor="html",
                    metadata={"ocr_required": True, "ocr_pages": [1], "source_url": "https://example.com"},
                )
                chunk = store.add_document_chunk(doc["id"], 1, "Web ingestion supports chunk citations and RAG answers.", f"doc:{doc['id']}#chunk=1")
                store.add_knowledge("RAG summary", "Citation aware answers use indexed chunks.", "research", "doc")

                ocr_payload = json.loads(asyncio.run(server.api_documents_ocr_queue(category="research")).body)
                run_payload = json.loads(asyncio.run(server.api_document_run_ocr(
                    doc["id"],
                    FakeRequest({"sidecar_text": "Scanned PDF OCR text now supports citation chunks.", "force": True}),
                )).body)
                answer_payload = json.loads(asyncio.run(server.api_document_citation_answer(q="citation chunks", category="research")).body)
                graph_payload = json.loads(asyncio.run(server.api_knowledge_graph(category="research")).body)
            finally:
                server.g_memory_store = old_store
                server.g_knowledge_service = old_service

        self.assertEqual(ocr_payload["count"], 1)
        self.assertEqual(ocr_payload["documents"][0]["ocr_pages"], [1])
        self.assertTrue(run_payload["ok"])
        self.assertEqual(run_payload["chunk_count"], 1)
        self.assertNotEqual(answer_payload["citations"][0]["chunk_id"], chunk["id"])
        self.assertIn("citation chunks", answer_payload["answer"])
        self.assertTrue(any(node["type"] == "document" for node in graph_payload["nodes"]))
        self.assertTrue(any(edge["type"] == "cites" for edge in graph_payload["edges"]))
        self.assertTrue(any(edge["type"] == "mentions" for edge in graph_payload["edges"]))

    def test_learning_analysis_accepts_library_document_id(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore
        from reportlab.pdfgen import canvas
        from security.policy import ToolSecurityPolicy
        from workspace_services import WorkspaceServices

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_services = server.g_workspace_services
            store = MemoryStore(str(Path(td) / "memory.db"))
            services = WorkspaceServices(store, ToolSecurityPolicy([td]))
            pdf = Path(td) / "library.pdf"
            doc = canvas.Canvas(str(pdf))
            doc.drawString(72, 720, "1 Introduction")
            doc.drawString(72, 700, "Local knowledge reports should reuse uploaded library documents.")
            doc.showPage()
            doc.drawString(72, 720, "2 Evidence")
            doc.drawString(72, 700, "The report keeps citations, questions, and output files together.")
            doc.save()
            library_doc = store.add_document(
                "Library RAG Paper",
                filename="library.pdf",
                file_path=str(pdf),
                file_hash="library-rag-paper",
                category="research",
                status="ready",
            )
            server.g_memory_store = store
            server.g_workspace_services = services
            try:
                payload = json.loads(asyncio.run(server.api_research_learning_analysis(FakeRequest({
                    "library_document_id": library_doc["id"],
                    "output_dir": str(Path(td) / "reports"),
                    "formats": ["markdown", "pdf"],
                    "depth": 2,
                    "question_count": 8,
                    "report_style": "learning_notes",
                }))).body)
                markdown_exists = Path(payload["report"]["markdown_path"]).exists()
                pdf_exists = Path(payload["report"]["pdf_path"]).exists()
            finally:
                server.g_memory_store = old_store
                server.g_workspace_services = old_services

        self.assertEqual(payload["library_document"]["id"], library_doc["id"])
        self.assertEqual(payload["report"]["metadata"]["report_style"], "learning_notes")
        self.assertTrue(markdown_exists)
        self.assertTrue(pdf_exists)
        self.assertIn("Library RAG Paper", payload["document"]["title"])

    def test_user_report_flow_generate_save_and_search_followup(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore
        from reportlab.pdfgen import canvas
        from security.policy import ToolSecurityPolicy
        from workspace_services import WorkspaceServices

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_services = server.g_workspace_services
            old_vector = server.g_vector_store
            store = MemoryStore(str(Path(td) / "memory.db"))
            services = WorkspaceServices(store, ToolSecurityPolicy([td]))
            pdf = Path(td) / "source.pdf"
            doc = canvas.Canvas(str(pdf))
            doc.drawString(72, 720, "1 Upload")
            doc.drawString(72, 700, "A normal user uploads a source document for local knowledge work.")
            doc.showPage()
            doc.drawString(72, 720, "2 Follow up")
            doc.drawString(72, 700, "The generated report should be saved, searchable, and ready for follow-up questions.")
            doc.save()
            library_doc = store.add_document(
                "User Flow Source",
                filename="source.pdf",
                file_path=str(pdf),
                file_hash="user-flow-source",
                category="research",
                status="ready",
            )
            server.g_memory_store = store
            server.g_workspace_services = services
            server.g_vector_store = None
            try:
                generated = json.loads(asyncio.run(server.api_research_learning_analysis(FakeRequest({
                    "library_document_id": library_doc["id"],
                    "output_dir": str(Path(td) / "reports"),
                    "formats": ["markdown", "pdf"],
                    "depth": 2,
                    "question_count": 8,
                    "report_style": "compact",
                }))).body)
                report = generated["report"]
                saved = json.loads(asyncio.run(server.api_knowledge_save(FakeRequest({
                    "title": "User Flow Source - compact",
                    "content": "\n".join([
                        "# User Flow Source - compact",
                        f"Markdown: {report['markdown_path']}",
                        f"PDF: {report['pdf_path']}",
                        "Style: compact",
                        "## Preview",
                        generated.get("preview", ""),
                    ]),
                    "category": "research",
                    "source": report["markdown_path"],
                    "tags": ["report", "compact", "generated"],
                }))).body)
                vault_dir = server.resolve_obsidian_output_dir("user-flow-e2e-test", "research")
                exported = json.loads(asyncio.run(server.api_knowledge_obsidian_export(FakeRequest({
                    "category": "research",
                    "output_dir": "user-flow-e2e-test",
                    "limit": 20,
                }))).body)
                note_path = vault_dir / "notes" / "User_Flow_Source_-_compact.md"
                note_content = note_path.read_text(encoding="utf-8")
                markdown_exists = Path(report["markdown_path"]).exists()
                pdf_exists = Path(report["pdf_path"]).exists()
                listed = json.loads(asyncio.run(server.api_knowledge_list(category="research")).body)
            finally:
                server.g_memory_store = old_store
                server.g_workspace_services = old_services
                server.g_vector_store = old_vector

        self.assertTrue(saved["saved"])
        self.assertTrue(saved["item"]["id"])
        self.assertIn("Markdown:", saved["item"]["content"])
        self.assertIn("PDF:", saved["item"]["content"])
        self.assertTrue(markdown_exists)
        self.assertTrue(pdf_exists)
        self.assertTrue(any(item["id"] == saved["item"]["id"] for item in listed["items"]))
        self.assertTrue(exported["exported"])
        self.assertEqual(exported["output_dir"], str(vault_dir))
        self.assertTrue(note_path.exists())
        self.assertIn("Markdown:", note_content)
        self.assertIn("PDF:", note_content)
        self.assertIn("compact", note_content)

    def test_obsidian_export_output_dir_accepts_repo_relative_path(self):
        import clawos_server as server

        output_root = (server.BASE_DIR.parent / "output" / "obsidian").resolve()
        full_relative = server.resolve_obsidian_output_dir("output/obsidian/browser-flow-check", "research")
        short_relative = server.resolve_obsidian_output_dir("browser-flow-check", "research")
        default_dir = server.resolve_obsidian_output_dir("", "research")

        self.assertEqual(full_relative, output_root / "browser-flow-check")
        self.assertEqual(short_relative, output_root / "browser-flow-check")
        self.assertEqual(default_dir, output_root / "research")

    def test_knowledge_obsidian_check_and_vault_export(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore
        from services.knowledge_service import KnowledgeService

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_service = server.g_knowledge_service
            store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_memory_store = store
            server.g_knowledge_service = None
            try:
                first = store.add_knowledge(
                    "Retrieval Augmented Generation",
                    "Use [[Citation Grounding]] to keep generated answers auditable.",
                    "research",
                    "doc:1#chunk=1",
                    ["paper", "rag"],
                    0.91,
                )
                second = store.add_knowledge(
                    "Citation Grounding",
                    "Backlinks from [[Retrieval Augmented Generation]] should appear in the vault graph.",
                    "research",
                    "doc:1#chunk=2",
                    ["paper", "citation"],
                    0.89,
                )
                store.add_document("RAG Paper", filename="rag.pdf", file_hash="rag-paper", category="research")
                check_payload = json.loads(asyncio.run(server.api_knowledge_obsidian_check(category="research")).body)
                graph_payload = json.loads(asyncio.run(server.api_knowledge_graph(category="research", limit=80)).body)
                service = KnowledgeService(store, Path(td) / "uploads")
                export_payload = service.export_obsidian_vault(Path(td) / "vault", category="research")
                first_note = (Path(td) / "vault" / "notes" / "Retrieval_Augmented_Generation.md").read_text(encoding="utf-8")
            finally:
                server.g_memory_store = old_store
                server.g_knowledge_service = old_service

        self.assertTrue(first["id"])
        self.assertTrue(second["id"])
        self.assertTrue(check_payload["ok"])
        self.assertEqual(check_payload["standard"], "obsidian-frontmatter-tags-wikilinks-backlinks-graph")
        self.assertGreaterEqual(check_payload["wikilink_count"], 1)
        self.assertGreaterEqual(check_payload["backlink_count"], 2)
        self.assertTrue(export_payload["exported"])
        self.assertGreaterEqual(export_payload["file_count"], 3)
        self.assertTrue(any(edge["type"] == "tagged" for edge in graph_payload["edges"]))
        self.assertTrue(any(edge["type"] == "links_to" for edge in graph_payload["edges"]))
        self.assertTrue(any(edge["type"] == "backlink" for edge in graph_payload["edges"]))
        self.assertTrue(any(edge["type"] == "sourced_from" for edge in graph_payload["edges"]))
        self.assertIn("title: \"Retrieval Augmented Generation\"", first_note)
        self.assertIn("[[Citation Grounding]]", first_note)
        self.assertIn("## Backlinks", first_note)

    def test_run_tool_loop_records_task_step_for_rule_based_tool(self):
        from memoryos.memory_store import MemoryStore

        server = importlib.import_module("clawos_server")
        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_memory_store = store
            task = store.start_task("s1", "查看工具列表", source="chat")
            try:
                result = asyncio.run(server.run_tool_loop("查看工具列表", "s1", task_id=task["id"]))
                detail = store.get_task(task["id"])
            finally:
                server.g_memory_store = old_store

        self.assertTrue(result["used_tools"])
        self.assertEqual(detail["steps"][0]["name"], "tools_list")
        self.assertEqual(detail["steps"][0]["status"], "succeeded")
        self.assertTrue(detail["steps"][0]["output"]["ok"])
        self.assertIn("step_finished", [event["event_type"] for event in detail["events"]])

    def test_server_task_helpers_list_and_return_detail(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            try:
                task = server.create_runtime_task("s1", "demo task")
                server.g_memory_store.add_task_event(task["id"], "custom", "hello")
                listed = server.list_runtime_tasks(session_id="s1")
                detail = server.get_runtime_task(task["id"])
            finally:
                server.g_memory_store = old_store

        self.assertEqual(listed[0]["id"], task["id"])
        self.assertEqual(detail["task"]["title"], "demo task")
        self.assertEqual(detail["events"][-1]["event_type"], "custom")

    def test_chat_completion_creates_finished_runtime_task(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_context = server.g_context_builder
            old_mtclaw = server.g_mtclaw_adapter
            old_reflection = server.g_reflection_engine
            old_config = server.config
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_context_builder = None
            server.g_mtclaw_adapter = None
            server.g_reflection_engine = None
            server.config = {"upstream": {}, "routing": {}}
            try:
                resp = asyncio.run(server.chat_completions(FakeRequest({
                    "session_id": "s-task",
                    "messages": [{"role": "user", "content": "查看工具列表"}],
                    "stream": False,
                })))
                body = json.loads(resp.body)
                task_id = body["clawos"]["task_id"]
                detail = server.g_memory_store.get_task(task_id)
            finally:
                server.g_memory_store = old_store
                server.g_context_builder = old_context
                server.g_mtclaw_adapter = old_mtclaw
                server.g_reflection_engine = old_reflection
                server.config = old_config

        self.assertEqual(detail["task"]["status"], "succeeded")
        self.assertEqual(detail["steps"][0]["name"], "tools_list")
        self.assertTrue(detail["steps"][0]["output"]["ok"])

    def test_task_api_routes_expose_list_and_detail(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            try:
                task = server.create_runtime_task("s1", "api task")
                list_resp = asyncio.run(server.api_tasks(session_id="s1"))
                detail_resp = asyncio.run(server.api_task_detail(task["id"]))
                listed = json.loads(list_resp.body)
                detail = json.loads(detail_resp.body)
            finally:
                server.g_memory_store = old_store

        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["tasks"][0]["title"], "api task")
        self.assertEqual(detail["task"]["id"], task["id"])
        self.assertIn("events", detail)

    def test_reflection_collects_persisted_tool_trajectory(self):
        from memoryos.memory_store import MemoryStore
        from reflection.perception import PerceptionLayer

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.record_tool_execution(
                session_id="s1",
                tool_name="time_now",
                result={"ok": True, "status": "success", "data": {"time": "10:00"}},
            )
            trajectory = PerceptionLayer(store).collect("s1", tool_logs=[])

        self.assertEqual(len(trajectory["tool_calls"]), 1)
        self.assertEqual(trajectory["tool_calls"][0]["name"], "time_now")


if __name__ == "__main__":
    unittest.main()
