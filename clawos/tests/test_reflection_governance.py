import tempfile
import unittest
from pathlib import Path


class ReflectionGovernanceTests(unittest.TestCase):
    def _create_card(self, store):
        from reflection.memory_writer import ReflectionMemoryWriter

        return ReflectionMemoryWriter(store).store_reflection(
            task="Run project checks",
            outcome="partial",
            outcome_detail={"outcome": "partial", "error_count": 1, "total_tools": 2},
            analysis={
                "root_cause": "Invalid tool argument",
                "failure_category": "parameter",
                "insights": ["Validate inputs"],
                "improvements": [{
                    "title": "Strict input validation",
                    "detail": "Validate tool parameters before execution",
                    "target_type": "tool_policy",
                    "target_key": "input-validation",
                    "candidate_payload": {"strict": True},
                }],
                "patterns": ["Repeated invalid argument"],
            },
            trajectory={
                "tool_calls": [{
                    "name": "project_check",
                    "arguments": {"path": ""},
                    "result": {"ok": False, "error": "invalid argument"},
                }],
            },
            trigger="failure_detected",
            session_id="s1",
            user_feedback={"satisfied": False, "comment": "Need a safer retry"},
        )

    def test_full_reflection_card_is_persisted(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            card = self._create_card(store)
            detail = store.get_reflection_card(card["id"])
            updated = store.update_reflection_feedback(
                card["id"],
                {"satisfied": True, "correction": "Confirmed after review"},
                actor_id="user-1",
            )

        self.assertEqual(detail["failure_category"], "parameter")
        self.assertEqual(detail["trajectory"]["tool_calls"][0]["name"], "project_check")
        self.assertEqual(detail["evidence"][0]["evidence_type"], "tool_execution")
        self.assertEqual(detail["improvements"][0]["status"], "proposed")
        self.assertTrue(updated["user_feedback"]["satisfied"])
        self.assertEqual(updated["version"], 2)

    def test_improvement_requires_regression_then_can_publish_and_rollback(self):
        from memoryos.memory_store import MemoryStore
        from reflection.improvement_manager import ImprovementManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.set_runtime_policy(
                "tool_policy", "input-validation", {"strict": False}, actor_id="admin"
            )
            card = self._create_card(store)
            improvement_id = card["improvements"][0]["id"]
            manager = ImprovementManager(store)
            manager.transition(improvement_id, "approved", actor_id="reviewer")
            validated = manager.validate(
                improvement_id,
                baseline={
                    "success_rate": 0.80,
                    "quality_score": 0.75,
                    "latency_ms": 100,
                    "error_rate": 0.20,
                },
                candidate={
                    "success_rate": 0.90,
                    "quality_score": 0.82,
                    "latency_ms": 110,
                    "error_rate": 0.10,
                },
                actor_id="qa",
            )
            published = manager.publish(improvement_id, actor_id="admin")
            active = store.get_runtime_policy("tool_policy", "input-validation")
            rolled_back = manager.rollback(improvement_id, actor_id="admin")
            restored = store.get_runtime_policy("tool_policy", "input-validation")

        self.assertEqual(validated["status"], "validated")
        self.assertTrue(validated["regression_result"]["passed"])
        self.assertEqual(published["status"], "published")
        self.assertEqual(active["payload"], {"strict": True})
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(restored["payload"], {"strict": False})
        self.assertEqual(
            [event["to_status"] for event in rolled_back["events"]],
            ["proposed", "approved", "testing", "validated", "published", "rolled_back"],
        )

    def test_failed_regression_rejects_improvement(self):
        from memoryos.memory_store import MemoryStore
        from reflection.improvement_manager import ImprovementManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            card = self._create_card(store)
            improvement_id = card["improvements"][0]["id"]
            manager = ImprovementManager(store)
            manager.transition(improvement_id, "approved", actor_id="reviewer")
            rejected = manager.validate(
                improvement_id,
                baseline={"success_rate": 0.9, "latency_ms": 100},
                candidate={"success_rate": 0.7, "latency_ms": 180},
                actor_id="qa",
            )
            with self.assertRaises(ValueError):
                manager.publish(improvement_id, actor_id="admin")

        self.assertEqual(rejected["status"], "rejected")
        self.assertFalse(rejected["regression_result"]["passed"])


if __name__ == "__main__":
    unittest.main()
