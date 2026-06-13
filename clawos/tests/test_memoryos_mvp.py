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


if __name__ == "__main__":
    unittest.main()
