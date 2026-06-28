import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class MemoryOSMvpTests(unittest.TestCase):
    def test_unified_memory_supports_five_types_and_metadata(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            ids = []
            for memory_type in ("profile", "preference", "project", "experience", "skill"):
                item = store.upsert_memory(
                    memory_type=memory_type,
                    key=f"{memory_type}:demo",
                    value=f"{memory_type} value",
                    source="unit_test",
                    confidence=0.8,
                )
                ids.append(item["id"])

            rows = store.list_memories(include_disabled=True)

        self.assertEqual(len(rows), 5)
        self.assertEqual({r["memory_type"] for r in rows}, {"profile", "preference", "project", "experience", "skill"})
        self.assertTrue(all(r["enabled"] for r in rows))
        self.assertTrue(all(r["source"] == "unit_test" for r in rows))
        self.assertTrue(all(r["confidence"] == 0.8 for r in rows))
        self.assertEqual(len(set(ids)), 5)

    def test_memory_update_disable_and_search_reuse(self):
        from memoryos.context_builder import ContextBuilder
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            first = store.upsert_memory(
                "preference",
                "reply_style",
                "Prefer concise direct answers",
                source="manual",
                confidence=0.7,
            )
            updated = store.upsert_memory(
                "preference",
                "reply_style",
                "Prefer concise direct Chinese answers",
                source="manual_edit",
                confidence=0.9,
            )
            project = store.upsert_memory(
                "project",
                "clawos",
                "Build a local Windows agent OS",
                source="manual",
                confidence=0.8,
            )
            store.set_memory_enabled(project["id"], False)

            results = store.search_memories("Chinese", limit=5)
            disabled_results = store.search_memories("Windows", limit=5)
            messages = ContextBuilder(store).build_messages("s1", "How should you answer?", max_history=4)

        self.assertEqual(first["id"], updated["id"])
        self.assertEqual(results[0]["value"], "Prefer concise direct Chinese answers")
        self.assertEqual(disabled_results, [])
        self.assertIn("Prefer concise direct Chinese answers", messages[0]["content"])
        self.assertNotIn("Build a local Windows agent OS", messages[0]["content"])

    def test_server_memory_api_helpers_validate_and_return_items(self):
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            try:
                item = server.save_memory_item({
                    "memory_type": "skill",
                    "key": "review",
                    "value": "Use tests before refactors",
                    "source": "api_test",
                    "confidence": 0.75,
                })
                rows = server.list_memory_items("skill", include_disabled=True)
                disabled = server.set_memory_item_enabled(item["id"], False)
            finally:
                server.g_memory_store = old_store

        self.assertEqual(item["memory_type"], "skill")
        self.assertEqual(rows[0]["key"], "review")
        self.assertFalse(disabled["enabled"])

    def test_ingestion_extracts_real_chinese_into_unified_memories(self):
        from memoryos.context_builder import ContextBuilder
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            builder = ContextBuilder(store)
            builder.ingest_and_store(
                "s1",
                "user",
                "\u6211\u53eb\u9648\u540c\u5b66\uff0c\u6211\u7684\u7814\u7a76\u65b9\u5411\u662f\u667a\u80fd\u4f53\u7cfb\u7edf\u3002\u6211\u559c\u6b22\u7b80\u6d01\u76f4\u63a5\u7684\u4e2d\u6587\u56de\u590d\u3002",
            )
            memories = store.list_memories(include_disabled=True)

        values = {m["key"]: m["value"] for m in memories}
        self.assertEqual(values["name"], "\u9648\u540c\u5b66")
        self.assertIn("\u667a\u80fd\u4f53\u7cfb\u7edf", values["research_direction"])
        self.assertIn("\u7b80\u6d01\u76f4\u63a5", values["reply_style"])

    def test_vector_store_indexes_unified_memories_and_context_retrieves_them(self):
        from memoryos.context_builder import ContextBuilder
        from memoryos.memory_store import MemoryStore
        from memoryos.services.vector_store import MemoryVectorStore

        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "memory.db")
            store = MemoryStore(db_path)
            store.upsert_memory(
                "project",
                "deployment_target",
                "ClawOS must run offline on MTT AIBOOK",
                source="plan",
                confidence=0.95,
            )
            vectors = MemoryVectorStore(db_path)
            vectors.refresh()
            results = vectors.search("MTT AIBOOK offline", top_k=5, min_score=0.0)
            messages = ContextBuilder(store, vectors).build_messages(
                "s1",
                "What is the offline deployment target?",
                max_history=4,
            )

        self.assertTrue(any(r["id"].startswith("mem_") for r in results))
        self.assertTrue(any("MTT AIBOOK" in m["content"] for m in messages if m["role"] == "system"))

    def test_vector_store_chroma_provider_is_offline_and_fallback_safe(self):
        from memoryos.memory_store import MemoryStore
        from memoryos.services.vector_store import MemoryVectorStore

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "memory.db"
            store = MemoryStore(str(db_path))
            store.upsert_memory(
                "project",
                "vector_backend",
                "Chroma offline vector store should persist local knowledge retrieval.",
                source="unit_test",
                confidence=0.9,
            )
            vectors = MemoryVectorStore(str(db_path), provider="chroma", persist_dir=str(root / "chroma"))
            try:
                vectors.refresh()
                stats = vectors.stats()
                results = vectors.search("offline Chroma vector retrieval", top_k=5, min_score=0.0)
            finally:
                vectors.close()

        self.assertEqual(stats["requested_provider"], "chroma")
        self.assertIn(stats["provider"], {"chroma", "lightweight"})
        if stats["provider"] == "lightweight":
            self.assertIn("chromadb", stats["fallback_reason"])
        self.assertTrue(any(r["id"].startswith("mem_") for r in results))

    def test_user_knowledge_library_can_be_saved_searched_and_listed(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            item = store.add_knowledge(
                "Agent 论文精读",
                "这篇论文讨论工具调用评测和可复现实验。",
                category="research",
                source="unit_test",
                tags=["paper", "agent"],
                confidence=0.9,
            )
            updated = store.update_knowledge(
                item["id"],
                "Agent 论文精读更新",
                "这篇论文讨论工具调用评测、可复现实验和知识库管理。",
                category="research",
                source="unit_test_edit",
                tags=["paper", "agent", "rag"],
                confidence=0.95,
            )
            listed = store.list_knowledge("research")
            results = store.search_knowledge("知识库管理", "research")
            deleted = store.delete_knowledge(item["id"])
            after_delete = store.list_knowledge("research")

        self.assertEqual(item["title"], "Agent 论文精读")
        self.assertEqual(updated["title"], "Agent 论文精读更新")
        self.assertEqual(listed[0]["category"], "research")
        self.assertEqual(results[0]["source"], "unit_test_edit")
        self.assertTrue(deleted)
        self.assertEqual(after_delete, [])

    def test_document_ingestion_chunks_indexes_and_deduplicates_uploaded_files(self):
        from memoryos.document_ingestion import ingest_file
        from memoryos.memory_store import MemoryStore
        from memoryos.services.vector_store import MemoryVectorStore

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "memory.db"
            source = root / "rag_notes.md"
            source.write_text(
                "RAG upload pipeline should parse files, chunk evidence, and cite sources.\n" * 80,
                encoding="utf-8",
            )
            store = MemoryStore(str(db_path))
            first = ingest_file(store, root / "uploads", source, title="RAG Notes", category="research")
            second = ingest_file(store, root / "uploads", source, title="RAG Notes", category="research")

            docs = store.list_documents("research")
            chunks = store.get_document_chunks(second["id"], limit=20)
            knowledge = store.search_knowledge("upload pipeline", "research", limit=20)
            vectors = MemoryVectorStore(str(db_path))
            vector_hits = vectors.search_knowledge("chunk evidence cite sources", top_k=5)

        self.assertEqual(first["id"], second["id"])
        self.assertGreaterEqual(second["chunk_count"], 2)
        self.assertEqual(len(docs), 1)
        self.assertEqual(len(chunks), second["chunk_count"])
        self.assertTrue(all(str(row["source"]).startswith(f"doc:{second['id']}#") for row in knowledge))
        self.assertTrue(vector_hits)

    def test_document_ingestion_preserves_pdf_page_citations(self):
        from memoryos.document_ingestion import ingest_file
        from memoryos.memory_store import MemoryStore
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pdf = root / "paper.pdf"
            doc = canvas.Canvas(str(pdf))
            doc.drawString(72, 720, "Page one discusses overview material.")
            doc.showPage()
            doc.drawString(72, 720, "Page two discusses citation fidelity evidence chains.")
            doc.save()
            store = MemoryStore(str(root / "memory.db"))
            imported = ingest_file(store, root / "uploads", pdf, title="Paper", category="research")
            chunks = store.get_document_chunks(imported["id"], limit=10)

        self.assertEqual(imported["metadata"]["page_count"], 2)
        self.assertTrue(any("#page=2&chunk=1" in chunk["citation"] for chunk in chunks))

    def test_scanned_pdf_ingestion_enters_ocr_queue_instead_of_failing(self):
        import memoryos.document_ingestion as ingestion
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "scan.pdf"
            source.write_bytes(b"%PDF-1.4\n% scanned placeholder")
            store = MemoryStore(str(root / "memory.db"))
            old_extract = ingestion.extract_text
            ingestion.extract_text = lambda path: ("", {"extractor": "test-pdf", "ocr_required": True, "ocr_pages": [1]})
            try:
                doc = ingestion.ingest_file(store, root / "uploads", source, title="Scanned", category="research")
                docs = store.list_documents("research")
            finally:
                ingestion.extract_text = old_extract

        self.assertEqual(doc["status"], "needs_ocr")
        self.assertEqual(doc["chunk_count"], 0)
        self.assertTrue(docs[0]["metadata"]["ocr_required"])

    def test_sessions_have_compact_topic_and_tags(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.add_message("s1", "user", "请分析当前项目的前端代码和测试风险")
            store.add_message("s1", "assistant", "可以，建议先检查布局和单元测试。")
            sessions = store.list_sessions()

        self.assertEqual(sessions[0]["title"], "请分析当前项目的前端代码和测试风险")
        self.assertIn("项目", sessions[0]["tags"])

    def test_task_runtime_persists_steps_events_and_status(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            task = store.start_task("s1", "查看工具列表", source="chat")
            step = store.add_task_step(task["id"], "tool", "tools_list", status="running", input_data={"q": "tools"})
            store.finish_task_step(step["id"], status="succeeded", output_data={"count": 3}, error="")
            store.add_task_event(task["id"], "tool_completed", "tools_list", step_id=step["id"], data={"ok": True})
            finished = store.finish_task(task["id"], "succeeded")
            detail = store.get_task(task["id"])
            tasks = store.list_tasks(session_id="s1")

        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(tasks[0]["id"], task["id"])
        self.assertEqual(detail["task"]["title"], "查看工具列表")
        self.assertEqual(detail["steps"][0]["name"], "tools_list")
        self.assertEqual(detail["steps"][0]["status"], "succeeded")
        self.assertEqual(detail["steps"][0]["output"]["count"], 3)
        event_types = [event["event_type"] for event in detail["events"]]
        self.assertIn("task_started", event_types)
        self.assertIn("tool_completed", event_types)
        self.assertIn("task_finished", event_types)


if __name__ == "__main__":
    unittest.main()
