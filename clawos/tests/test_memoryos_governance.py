import tempfile
import unittest
from pathlib import Path


class MemoryOSGovernanceTests(unittest.TestCase):
    def test_versions_evidence_conflict_and_review_resolution(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            original = store.upsert_memory(
                "preference",
                "reply_style",
                "concise",
                source="manual",
                actor_id="user-1",
                evidence=[{
                    "evidence_type": "user_confirmation",
                    "source_ref": "session-1",
                    "excerpt": "Please be concise",
                }],
            )
            conflict = store.upsert_memory(
                "preference",
                "reply_style",
                "detailed",
                source="conversation_ingestion",
                actor_id="session-2",
                evidence=[{
                    "evidence_type": "conversation",
                    "source_ref": "session-2",
                    "excerpt": "Please explain in detail",
                }],
                conflict_policy="review",
            )
            pending = store.list_memory_reviews()
            before = store.get_memory(original["id"])
            resolved = store.resolve_memory_review(
                pending[0]["id"], "approve", reviewer="reviewer-1", notes="User confirmed"
            )
            after = store.get_memory(original["id"])
            versions = store.list_memory_versions(original["id"])
            evidence = store.list_memory_evidence(original["id"])

        self.assertTrue(conflict["review_required"])
        self.assertEqual(before["value"], "concise")
        self.assertEqual(resolved["status"], "approved")
        self.assertEqual(after["value"], "detailed")
        self.assertEqual([item["version"] for item in versions], [2, 1])
        self.assertEqual({item["source_ref"] for item in evidence}, {"session-1", "session-2"})

    def test_acl_filters_restricted_memory(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            item = store.upsert_memory(
                "project",
                "secret-plan",
                "confidential",
                owner_id="owner-1",
            )
            store.grant_memory_acl(item["id"], "user", "alice", "read")

            alice = store.search_memories("confidential", actor_id="alice")
            bob = store.search_memories("confidential", actor_id="bob")
            owner = store.search_memories("confidential", actor_id="owner-1")

        self.assertEqual(len(alice), 1)
        self.assertEqual(bob, [])
        self.assertEqual(len(owner), 1)

    def test_retrieval_benchmark_persists_metrics(self):
        from memoryos.memory_store import MemoryStore
        from memoryos.services.retrieval import RetrievalService
        from memoryos.services.retrieval_benchmark import RetrievalBenchmark

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            item = store.upsert_memory(
                "project",
                "deployment_target",
                "MTT AIBOOK offline deployment",
            )
            run = RetrievalBenchmark(store, RetrievalService(store)).run(
                [{
                    "query": "MTT AIBOOK offline",
                    "expected_ids": [f"mem_{item['id']}"],
                }],
                top_k=5,
                name="unit",
            )

        self.assertEqual(run["case_count"], 1)
        self.assertEqual(run["metrics"]["hit_rate"], 1.0)
        self.assertEqual(run["metrics"]["recall_at_5"], 1.0)


if __name__ == "__main__":
    unittest.main()
