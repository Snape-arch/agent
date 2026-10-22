from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memoryos.memory_store import MemoryStore
from services.academy_curriculum import LESSONS, PAPERS, PROJECTS, RESOURCES, TRACKS, track_nodes
from services.academy_studio_service import AcademyStudioService
from services.learning_product_service import LearningProductService


class AcademyStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(str(Path(self.temp.name) / "learning.db"))
        self.learning = LearningProductService(self.store)
        self.studio = AcademyStudioService(self.learning)

    def test_catalog_has_acyclic_complete_paths_and_real_sources(self):
        seen = set()
        resources = {r["id"] for r in RESOURCES}
        for row in LESSONS:
            self.assertNotIn(row["id"], seen)
            self.assertTrue(set(row["prerequisites"]) <= seen)
            self.assertIn(row["resource"], resources)
            self.assertGreaterEqual(len(row["checks"]), 3)
            seen.add(row["id"])
        for track in TRACKS:
            nodes = track_nodes(track)
            self.assertIn(track["goal"], nodes)
            for row in LESSONS:
                if row["id"] in nodes:
                    self.assertTrue(set(row["prerequisites"]) <= set(nodes))
        for row in PAPERS + PROJECTS:
            self.assertIn(row["topic"], seen)
        for row in RESOURCES + PAPERS:
            self.assertTrue(row["url"].startswith("https://"))

    def test_idempotent_seeding_preserves_existing_enrollment(self):
        original = self.learning.dashboard()
        for _ in range(3):
            state = AcademyStudioService(LearningProductService(self.store)).state()
        self.assertFalse(state["active"])
        self.assertEqual(original["course"]["id"], self.learning.dashboard()["course"]["id"])
        with self.store._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM learning_questions WHERE course_id=?", (self.studio.course_id,)).fetchone()[0]
        self.assertEqual(count, 2 * len(LESSONS))
        active = self.studio.start("builder", 20)
        self.assertTrue(active["active"])
        self.assertEqual(active["dashboard"]["due_count"], 0)
        self.assertEqual(active["records"]["plan"], {"track": "builder", "minutes": 20})
        switched = self.studio.start("research", 60)
        self.assertEqual(active["dashboard"]["enrollment"]["id"], switched["dashboard"]["enrollment"]["id"])

    def test_notes_checklists_persist_without_mastery_and_are_learner_scoped(self):
        self.studio.start("builder")
        before = self.learning.dashboard()["topics"]
        self.studio.save("lesson:python", {"read": True, "note": "自己的解释 <script> 并非 HTML"})
        self.studio.save("paper:rag", {"problem": "证据是否可靠？", "evidence": "§2：待核对"})
        self.studio.save("project:knowledge-assistant", {"steps": [True]*4, "note": "个人自查"})
        restored = AcademyStudioService(LearningProductService(self.store))
        state = restored.state()
        self.assertTrue(state["records"]["lesson:python"]["read"])
        self.assertEqual(state["records"]["paper:rag"]["evidence"], "§2：待核对")
        self.assertEqual(before, state["dashboard"]["topics"])
        self.assertEqual(restored.state("another-learner")["records"], {})

    def test_invalid_records_cannot_write_arbitrary_or_mastery_state(self):
        for key, payload in [("lesson:missing", {"read": True}), ("lesson:python", {"read": "true"}),
                             ("paper:rag", {"method": []}), ("project:knowledge-assistant", {"steps": [1]*4}),
                             ("plan", {"track": "builder", "minutes": True}), ("plan", {"track": "missing", "minutes": 40}),
                             ("mastery:python", {"mastered": True})]:
            with self.subTest(key=key, payload=payload), self.assertRaises(ValueError):
                self.studio.save(key, payload)
        self.studio.save("lesson:python", {"read": True, "mastered": True})
        self.assertNotIn("mastered", self.studio.state()["records"]["lesson:python"])

    def test_topic_quiz_unlocks_rotates_and_closes_real_mistake(self):
        self.studio.start("builder")
        for key in ["rag", "missing"]:
            with self.assertRaisesRegex(ValueError, "unlocked"):
                self.learning.next_quiz(topic_key=key)
        with self.assertRaisesRegex(ValueError,'unlocked'):
            self.learning.next_quiz(topic_key='python')
        self.assertEqual(self.learning.next_quiz(topic_key='computing')['question']['topic_key'],'computing')
        # Synthetic prerequisite evidence only, to isolate the existing quiz rotation contract.
        self.seed_prerequisite_fixture(['computing','logic'])
        quiz = self.learning.next_quiz(topic_key="python")
        qid = quiz["question"]["id"]
        self.assertEqual(quiz["question"]["topic_key"], "python")
        self.learning.submit_answer(qid, "我现在还不理解这个主题，也不知道应该怎样展开回答，需要重新阅读和练习。")
        self.assertEqual(self.learning.mistake_queue()["count"], 1)
        answer = "因为函数让数据处理步骤可以独立检查，异常处理能记录错误输入，例如空文件返回零条数据，并在错误行写明原因。"
        self.learning.submit_answer(qid, answer)
        self.assertEqual(self.learning.mistake_queue()["count"], 0)
        second = self.learning.next_quiz(topic_key="python")
        self.assertNotEqual(qid, second["question"]["id"])
        self.assertFalse(self.learning.submit_answer(qid, answer)["accepted"])

    def test_studio_http_handlers_and_live_page_routes(self):
        import clawos_server as server
        from starlette.requests import Request

        def request(payload):
            async def receive():
                return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}
            return Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)

        async def exercise():
            with patch.object(server, "_learning_product", return_value=self.learning):
                start = await server.api_academy_studio_start(request({"track": "foundation", "minutes": 40}))
                self.assertTrue(json.loads(start.body)["active"])
                await server.api_academy_studio_save("paper:attention", request({"record": {"method": "注意力与位置"}}))
                state = json.loads((await server.api_academy_studio()).body)
                self.assertEqual(state["records"]["paper:attention"]["method"], "注意力与位置")
                self.seed_prerequisite_fixture(['numeracy'])
                quiz = json.loads((await server.api_academy_learning_quiz(topic_key="linear")).body)
                self.assertEqual(quiz["question"]["topic_key"], "linear")
                for handler in [server.academy_page, server.academy_path_page]:
                    self.assertEqual(Path((await handler()).path).name, "academy-studio.html")
        asyncio.run(exercise())

    def seed_prerequisite_fixture(self,keys):
        with self.store._conn() as c:
            for key in keys:
                c.execute('UPDATE learning_item_models SET p_known=.99 WHERE topic_key=?',(key,))
                c.execute('UPDATE learning_items SET evidence_count=2 WHERE id IN (SELECT item_id FROM learning_item_models WHERE topic_key=?)',(key,))

    def test_existing_enrollment_gets_new_foundations_without_reset(self):
        self.studio.start('builder')
        self.seed_prerequisite_fixture(['statistics'])
        before=self.learning.dashboard()['enrollment']
        with self.store._conn() as c:
            ids=[r['item_id'] for r in c.execute("SELECT item_id FROM learning_item_models WHERE topic_key='computing'")]
            for item in ids:
                c.execute('DELETE FROM learning_item_models WHERE item_id=?',(item,))
                c.execute('DELETE FROM learning_items WHERE id=?',(item,))
        AcademyStudioService(self.learning)
        after=self.learning.dashboard()
        self.assertEqual(before,after['enrollment'])
        self.assertTrue(next(t for t in after['topics'] if t['topic_key']=='statistics')['mastered'])
        self.assertEqual(next(t for t in after['topics'] if t['topic_key']=='computing')['evidence_count'],0)


if __name__ == "__main__":
    unittest.main()
