import asyncio
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class KnowledgeCoreServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        from memoryos.memory_store import MemoryStore
        from services.knowledge_core_service import KnowledgeCoreService
        self.store = MemoryStore(str(Path(self.temp.name) / "memory.db"))
        self.core = KnowledgeCoreService(self.store)

    def source_fixture(self, citation, text):
        import re
        document_id=int(re.match(r'doc:(\d+)',citation).group(1))
        for i in range(1,document_id+1):
            if not self.store.get_document(i):
                self.store.add_document(f'Source fixture {i}')
        self.store.add_document_chunk(document_id,1,text,citation)

    def tearDown(self):
        self.temp.cleanup()

    def test_absorption_merges_sources_entities_and_locators(self):
        self.source_fixture('doc:1#page=2&chunk=3','The target network stabilizes DQN training.')
        first = self.core.absorb(
            title="DQN target network", statement="The target network stabilizes DQN training.",
            category="research", source_ref="doc:1#page=2&chunk=3", locator="page=2&chunk=3",
            entities=["DQN", "target network"], confidence=0.8,
        )
        second = self.core.absorb(
            title="DQN target network", statement="The target network stabilizes DQN training.",
            category="research", source_ref="https://example.org/paper#section=method",
            locator="section=method", confidence=0.9,
        )
        results = self.core.search("DQN target network", category="research")

        self.assertEqual(first["absorption_outcome"], "created")
        self.assertEqual(second["absorption_outcome"], "source_merged")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_count"], 2)
        self.assertTrue(any("page=2" in source["citation"] for source in results[0]["sources"]))
        stats = self.core.stats()
        self.assertEqual(stats["entities"], 2)
        self.assertEqual(stats["relations"], 2)

    def test_near_duplicate_merges_only_when_numbers_and_polarity_agree(self):
        first = self.core.absorb(
            title="Replay benefit", statement="Experience replay reduces correlation between sequential samples.",
            category="research", source_ref="doc:first",
        )
        merged = self.core.absorb(
            title="Benefit of replay", statement="Experience replay reduces the correlation between sequential samples.",
            category="research", source_ref="doc:second",
        )
        distinct = self.core.absorb(
            title="Replay batch size", statement="Experience replay samples 32 transitions per batch.",
            category="research", source_ref="doc:third",
        )

        self.assertEqual(merged["id"], first["id"])
        self.assertEqual(merged["absorption_outcome"], "near_duplicate_merged")
        self.assertNotEqual(distinct["id"], first["id"])
        self.assertEqual(self.core.stats()["records"], 2)

    def test_claim_classification_and_source_authority(self):
        self.assertEqual(self.core.classify_claim("We propose a target-network method."), "method")
        self.assertEqual(self.core.classify_claim("A limitation is the low sample efficiency."), "limitation")
        self.assertGreater(
            self.core.source_authority("https://www.nature.com/articles/example", "document_claim"),
            self.core.source_authority("https://example.com/post", "document_claim"),
        )

    def test_vector_projection_is_incremental_scoped_and_expires(self):
        from memoryos.services.vector_store import MemoryVectorStore

        vector = MemoryVectorStore(
            self.store._db_path, provider="chroma", persist_dir=str(Path(self.temp.name) / "chroma"),
            embedding_provider="hash", dim=64,
        )
        public = self.core.absorb(
            title="Public runbook", statement="Restart the public worker after draining requests.",
            category="operations", source_ref="doc:public", owner_id="alice", workspace_id="public",
        )
        secret = self.core.absorb(
            title="Secret runbook", statement="Restart the secret worker after rotating credentials.",
            category="operations", source_ref="doc:secret", owner_id="alice", workspace_id="secret",
        )

        public_hits = vector.search_knowledge(
            "restart worker credentials requests", top_k=10, owner_id="alice", workspace_id="public",
        )
        self.assertEqual({item["metadata"]["knowledge_id"] for item in public_hits}, {public["id"]})
        self.assertNotIn(secret["id"], {item["metadata"]["knowledge_id"] for item in public_hits})
        first_stats = vector.stats()
        self.assertTrue(first_stats["consistent"])
        self.assertEqual(first_stats["expected_knowledge_v2"], 2)

        self.core.expire(public["id"], "superseded")
        after = vector.search_knowledge(
            "restart public worker", top_k=10, owner_id="alice", workspace_id="public",
        )
        self.assertEqual(after, [])
        self.assertTrue(vector.stats()["consistent"])
        vector.close()

    def test_document_claim_extraction_creates_atomic_source_bound_records(self):
        from memoryos.document_ingestion import ingest_file

        source = Path(self.temp.name) / "notes.md"
        source.write_text(
            "Experience replay stores transitions for randomized minibatch sampling.\n\n"
            "A target network is held fixed between periodic updates to stabilize learning.",
            encoding="utf-8",
        )
        document = ingest_file(
            self.store, Path(self.temp.name) / "uploads", source,
            title="DQN Notes", category="research",
        )
        replay = self.core.search("randomized minibatch transitions", category="research")
        target = self.core.search("target network periodic updates", category="research")

        self.assertEqual(document["chunk_count"], 1)
        self.assertTrue(any(item["knowledge_type"] == "claim" for item in replay))
        self.assertTrue(any(item["knowledge_type"] == "claim" for item in target))
        self.assertTrue(all(item["sources"][0]["source_ref"].startswith("doc:") for item in replay[:1] + target[:1]))

    def test_conflict_is_recorded_and_excluded_until_review(self):
        self.source_fixture('doc:1#page=1','The target network updates every 10000 steps.')
        self.source_fixture('doc:2#page=2','The target network updates every 5000 steps.')
        original = self.core.absorb(
            title="DQN update interval", statement="The target network updates every 10000 steps.",
            category="research", source_ref="doc:1#page=1",
        )
        candidate = self.core.absorb(
            title="DQN update interval", statement="The target network updates every 5000 steps.",
            category="research", source_ref="doc:2#page=2",
        )

        self.assertEqual(candidate["absorption_outcome"], "conflict_recorded")
        self.assertEqual(candidate["conflict"]["type"], "numeric_disagreement")
        self.assertEqual(self.core.search("DQN update interval", category="research"), [])
        reviewed = self.core.search("DQN update interval", category="research", include_conflicted=True)
        self.assertEqual(reviewed[0]["id"], original["id"])
        self.assertEqual(self.core.stats()["pending_conflicts"], 1)

    def test_expired_knowledge_is_not_retrieved_or_packed(self):
        item = self.core.absorb(
            title="Old API endpoint", statement="Use endpoint version one for uploads.",
            category="product", source_ref="https://docs.example.com/v1",
        )
        before = self.core.task_context_pack("API endpoint uploads", category="product")
        expired = self.core.expire(item["id"], "source superseded")
        after = self.core.task_context_pack("API endpoint uploads", category="product")

        self.assertEqual(len(before["items"]), 1)
        self.assertEqual(before["citation_count"], 1)
        self.assertEqual(expired["status"], "expired")
        self.assertEqual(after["items"], [])

    def test_legacy_add_update_delete_propagates_lifecycle(self):
        self.source_fixture('doc:1#page=1','Uploads use endpoint v1.')
        self.source_fixture('doc:2#page=1','Uploads use endpoint v2.')
        legacy = self.store.add_knowledge(
            "Upload API", "Uploads use endpoint v1.", "product", "doc:1#page=1", ["API"], 0.8,
        )
        first_id = legacy["knowledge_v2_id"]
        updated = self.store.update_knowledge(
            legacy["id"], "Upload API", "Uploads use endpoint v2.", "product", "doc:2#page=1", ["API"], 0.9,
        )
        self.assertEqual(updated["knowledge_v2_id"], first_id)
        with self.store._conn() as connection:
            current = connection.execute(
                "SELECT status,statement,current_version FROM knowledge_records_v2 WHERE id=?", (first_id,),
            ).fetchone()
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["statement"], "Uploads use endpoint v2.")
        self.assertEqual(current["current_version"], 3)
        self.assertTrue(self.store.delete_knowledge(legacy["id"]))
        self.assertEqual(self.core.search("Upload API", category="product"), [])

    def test_retrieval_prefers_evidence_record_without_legacy_duplicate(self):
        self.source_fixture('doc:7#chunk=2','RAG answers should cite retrieved evidence.')
        legacy = self.store.add_knowledge(
            "RAG citations", "RAG answers should cite retrieved evidence.", "research", "doc:7#chunk=2", ["RAG"], 0.9,
        )
        from memoryos.services.retrieval import RetrievalService
        rows = RetrievalService(self.store).retrieve("RAG citations evidence", top_k=10)

        v2 = [item for item in rows if item["source"] == "knowledge_v2"]
        legacy_rows = [item for item in rows if item["source"] == "knowledge" and item["id"] == legacy["id"]]
        self.assertEqual(len(v2), 1)
        self.assertEqual(legacy_rows, [])
        self.assertEqual(v2[0]["citation"], "doc:7#chunk=2")

    def test_api_context_pack_and_stats(self):
        self.source_fixture('doc:9#page=4','Task context should contain compact cited claims.')
        import clawos_server as server

        self.store.add_knowledge(
            "Evidence pack", "Task context should contain compact cited claims.",
            "research", "doc:9#page=4", ["context"], 0.9,
        )
        old_store = server.g_memory_store
        server.g_memory_store = self.store
        try:
            pack = json.loads(asyncio.run(server.api_knowledge_context_pack(
                q="Evidence pack context", category="research", limit=6, token_budget=800,
            )).body)
            stats = json.loads(asyncio.run(server.api_knowledge_v2_stats()).body)
            answer = json.loads(asyncio.run(server.api_knowledge_answer(
                q="Evidence pack context", category="research", session_id="session-a", task_id="task-a",
            )).body)
        finally:
            server.g_memory_store = old_store

        self.assertEqual(pack["schema"], "clawos.knowledge-context.v1")
        self.assertEqual(pack["citation_count"], 1)
        self.assertLessEqual(pack["estimated_tokens"], 800)
        self.assertEqual(stats["records"], 1)
        self.assertTrue(answer["grounded"])
        self.assertEqual(answer["generation_mode"], "deterministic_evidence_composition")
        self.assertIn("doc:9#page=4", answer["citations"])

    def test_conflict_review_reactivates_selected_claim(self):
        original = self.core.absorb(
            title="Release channel", statement="The stable channel is version 2.",
            category="product", source_ref="doc:old",
        )
        conflict = self.core.absorb(
            title="Release channel", statement="The stable channel is version 3.",
            category="product", source_ref="doc:new",
        )
        pending = self.core.list_conflicts()
        resolved = self.core.resolve_conflict(
            conflict["conflict"]["id"], "accept_candidate", reviewer="maintainer", reason="new official source",
        )

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["knowledge_id"], original["id"])
        self.assertEqual(resolved["statement"], "The stable channel is version 3.")
        self.assertEqual(resolved["status"], "active")
        self.assertEqual(self.core.list_conflicts(), [])

    def test_legacy_backfill_and_context_usage_event(self):
        with self.store._conn() as connection:
            connection.execute(
                "INSERT INTO knowledge (category,title,content,source,tags,confidence) VALUES (?,?,?,?,?,?)",
                ("knowledge", "Legacy provenance", "Legacy records should retain source evidence.",
                 "doc:legacy#chunk=1", '["provenance"]', 0.8),
            )
        migrated = self.core.backfill_legacy()
        from memoryos.services.retrieval import RetrievalService
        context = RetrievalService(self.store).retrieve_for_context(
            "Legacy provenance source evidence",
            policy={"top_k": 3, "citation_aware": True, "session_id": "session-1", "task_id": "task-1"},
        )

        self.assertEqual(migrated["migrated"], 1)
        self.assertIn("doc:legacy#chunk=1", context)
        self.assertEqual(self.core.stats()["usage_events"], 1)

    def test_duplicate_legacy_backfill_is_mapped_and_idempotent(self):
        with self.store._conn() as connection:
            for source in ("doc:one", "doc:two"):
                connection.execute(
                    "INSERT INTO knowledge (category,title,content,source,tags,confidence) VALUES (?,?,?,?,?,?)",
                    ("research", "Same claim", "The same reviewed claim.", source, "[]", 0.8),
                )
        first = self.core.backfill_legacy()
        second = self.core.backfill_legacy()
        with self.store._conn() as connection:
            links = connection.execute("SELECT COUNT(*) FROM knowledge_legacy_links_v2").fetchone()[0]

        self.assertEqual(first["migrated"], 2)
        self.assertEqual(second["candidate_count"], 0)
        self.assertEqual(self.core.stats()["records"], 1)
        self.assertEqual(self.core.stats()["sources"], 2)
        self.assertEqual(links, 2)

    def test_reviewed_quality_benchmark_meets_goal_thresholds(self):
        from services.knowledge_quality_benchmark import run_knowledge_quality_benchmark

        report = run_knowledge_quality_benchmark()
        self.assertGreaterEqual(report["record_count"], 30)
        self.assertGreaterEqual(report["query_count"], 30)
        self.assertTrue(report["passed"])
        for metric, threshold in report["thresholds"].items():
            self.assertGreaterEqual(report["metrics"][metric], threshold)
        self.assertIn("not production user telemetry", report["truth_boundary"])

    def test_quality_benchmark_tool_persists_reviewed_report(self):
        from scripts import tool_runner

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(output):
            tool_runner.input_data = {"out": td}
            tool_runner.handlers["knowledge_quality_benchmark"]()
            report = json.loads(output.getvalue())
            self.assertTrue(Path(report["artifact"]["path"]).exists())

        self.assertTrue(report["passed"])
        self.assertEqual(report["mode"], "reviewed_local_corpus_real_sqlite_chroma")
        self.assertGreaterEqual(report["query_count"], 60)


if __name__ == "__main__":
    unittest.main()
