from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from services.context_ledger import ContextLedgerService
from services.learning_product_service import LearningProductService


class LearningProductClosureTests(unittest.TestCase):
    def _service(self, directory: str):
        store = MemoryStore(str(Path(directory) / "memory.db"))
        return store, LearningProductService(store)

    def test_dashboard_is_persisted_and_ui_clicks_are_not_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            _, service = self._service(directory)
            dashboard = service.dashboard()
            repeated = service.dashboard()

        self.assertEqual(
            dashboard["enrollment"]["id"], repeated["enrollment"]["id"]
        )
        self.assertEqual(dashboard["mastered_count"], 0)
        self.assertTrue(all(
            int(item["evidence_count"]) == 0
            for item in dashboard["topics"]
        ))
        self.assertIn("UI clicks cannot", dashboard["truth_boundary"])

    def test_assessment_hides_answer_and_updates_explainable_model(self):
        with tempfile.TemporaryDirectory() as directory:
            _, service = self._service(directory)
            quiz = service.next_quiz()
            self.assertFalse(quiz["answer_disclosed"])
            self.assertNotIn("expected_concepts", quiz["question"])
            with self.assertRaises(ValueError):
                service.submit_answer(
                    quiz["question"]["id"], "retrieval"
                )
            result = service.submit_answer(
                quiz["question"]["id"],
                (
                    "Retrieval introduces evidence because generated answers "
                    "can have a failure when the retrieved evidence is "
                    "irrelevant, for example an outdated source."
                ),
            )
            dashboard = service.dashboard()

        self.assertGreater(result["score"], 0.7)
        self.assertEqual(
            result["model_after"]["algorithm_version"], "bkt-fsrs-lite.v1"
        )
        self.assertEqual(dashboard["topics"][0]["evidence_count"], 1)
        self.assertGreater(dashboard["topics"][0]["p_known"], 0.05)

    def test_project_evidence_is_digest_bound_and_idempotent(self):
        digest = hashlib.sha256(b"tested coding artifact").hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            store, service = self._service(directory)
            item_id = service.dashboard()["topics"][0]["id"]
            task = store.start_task(
                "learning-project", "Build tested artifact", status="running"
            )
            store.finish_task(
                task["id"], "succeeded",
                result_payload={"artifact_digest": digest, "tests": "passed"},
            )
            first = service.record_project_evidence(
                learner_id="local-user", item_id=item_id,
                task_id=str(task["id"]),
                artifact_digest=digest, evidence_type="tested_patch",
                score=0.9, explanation="Patch and tests passed",
            )
            repeated = service.record_project_evidence(
                learner_id="local-user", item_id=item_id,
                task_id=str(task["id"]),
                artifact_digest=digest, evidence_type="tested_patch",
                score=0.9, explanation="Patch and tests passed",
            )

        self.assertTrue(first["accepted"])
        self.assertFalse(repeated["accepted"])

    def test_course_publish_gate_requires_sources_and_assessments(self):
        with tempfile.TemporaryDirectory() as directory:
            _, service = self._service(directory)
            course = service.list_courses()[0]
            validation = service.validate_course_for_publish(course["id"])
            with self.assertRaises(ValueError):
                service.add_question(
                    course["id"], topic_key="rag",
                    prompt="Explain a sufficiently detailed retrieval question",
                    expected_concepts=["retrieval", "evidence"],
                    cognitive_level="explain", difficulty=0.5, source_ref="",
                )

        self.assertTrue(validation["valid"])
        self.assertTrue(validation["checks"]["all_topics_sourced"])
        self.assertTrue(validation["checks"]["all_topics_assessed"])

    def test_authored_course_is_fail_closed_until_every_topic_is_assessed(self):
        with tempfile.TemporaryDirectory() as directory:
            _, service = self._service(directory)
            course = service.create_course(
                course_key="student-python-v1",
                title="Student Python",
                description="A governed authored course",
                topics=[
                    {
                        "topic_key": "syntax", "title": "Syntax",
                        "source_ref": "book:python#syntax",
                    },
                    {
                        "topic_key": "testing", "title": "Testing",
                        "prerequisites": ["syntax"],
                        "source_ref": "book:python#testing",
                    },
                ],
                created_by="teacher",
            )
            blocked = service.validate_course_for_publish(course["id"])
            for topic in ("syntax", "testing"):
                service.add_question(
                    course["id"], topic_key=topic,
                    prompt=(
                        f"Explain {topic} with one boundary and an example."
                    ),
                    expected_concepts=[topic, "example"],
                    cognitive_level="apply", difficulty=0.5,
                    source_ref=f"book:python#{topic}",
                )
            published = service.publish_course(course["id"])

        self.assertFalse(blocked["valid"])
        self.assertFalse(blocked["checks"]["all_topics_assessed"])
        self.assertEqual(published["course"]["status"], "published")
        self.assertTrue(
            published["validation"]["checks"]["prerequisite_graph_acyclic"]
        )

    def test_mistake_resolution_does_not_fake_mastery(self):
        with tempfile.TemporaryDirectory() as directory:
            _, service = self._service(directory)
            quiz = service.next_quiz()
            service.submit_answer(
                quiz["question"]["id"],
                "I am not yet able to explain this concept in enough detail.",
            )
            queue = service.mistake_queue()
            item_id = queue["mistakes"][0]["item_id"]
            before = service.explain_item(item_id)
            resolved = service.resolve_mistake(
                queue["mistakes"][0]["id"],
                resolution_evidence=(
                    "Reviewed the source and wrote a corrected explanation."
                ),
            )
            after = service.explain_item(item_id)

        self.assertEqual(queue["count"], 1)
        self.assertEqual(resolved["mistake"]["status"], "resolved")
        self.assertFalse(resolved["mastery_changed"])
        self.assertEqual(
            before["decision"]["p_known"], after["decision"]["p_known"]
        )
        self.assertEqual(len(after["assessment_attempts"]), 1)

    def test_context_and_review_share_task_evidence_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(str(Path(directory) / "memory.db"))
            task = store.start_task(
                "ledger-session", "Review a change", status="pending"
            )
            ledger = ContextLedgerService(store)
            context = ledger.record_context(
                task["id"],
                {
                    "objective": "Review a change",
                    "context_digest": hashlib.sha256(b"context").hexdigest(),
                    "sources": [{"kind": "instruction", "path": "AGENTS.md"}],
                    "budget": {"used": 100, "limit": 1000},
                    "trust_policy": {"instruction_precedence": ["AGENTS.md"]},
                },
                omitted_candidates=[{"path": "large.log", "reason": "budget"}],
            )
            review = ledger.record_review(task["id"], {
                "scope": "working_tree",
                "diff_digest": hashlib.sha256(b"diff").hexdigest(),
                "reviewer": "local-reviewer",
                "findings": [{
                    "file": "app.py", "line": 12, "severity": "medium",
                    "reason": "Missing error handling",
                }],
                "tests": [{"name": "unit", "passed": True}],
            })
            result = ledger.task_ledger(task["id"])

        self.assertTrue(context["context_digest"])
        self.assertTrue(review["valid"])
        self.assertEqual(len(result["contexts"]), 1)
        self.assertEqual(len(result["reviews"]), 1)
        self.assertEqual(
            result["contexts"][0]["omitted_candidates"][0]["path"],
            "large.log",
        )


if __name__ == "__main__":
    unittest.main()
