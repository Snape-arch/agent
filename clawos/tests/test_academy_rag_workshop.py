import asyncio
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memoryos.memory_store import MemoryStore
from services import academy_rag_engine as engine
from services.academy_rag_workshop import RagWorkshop
from services.learning_product_service import LearningProductService

GOOD = dict(chunk_size=80, top_k=2, min_score=.3, current_only=True)


class RagWorkshopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = MemoryStore(str(Path(self.temp.name)/"learning.db"))
        self.service = RagWorkshop(self.store)

    def test_default_failures_and_repaired_config_are_real_computations(self):
        before = engine.run(engine.DEFAULT_CONFIG)
        after = engine.run(GOOD)
        self.assertLess(before["passed"], before["total"])
        self.assertEqual(after["passed"], 6)
        self.assertTrue(after["rows"][-1]["response"]["abstain"])
        self.assertEqual(after["rows"][1]["chunks"][0]["document_id"], "loan")
        for row in after["rows"]:
            for chunk in row["chunks"]:
                doc = next(d for d in engine.DOCUMENTS if d["id"] == chunk["document_id"])
                self.assertEqual(chunk["text"], doc["text"][chunk["start"]:chunk["end"]])

    def test_valid_citation_alone_and_fabricated_ids_do_not_pass(self):
        case = engine.CASES[1]
        chunks = engine.retrieve(case["query"], GOOD)
        for answer in [dict(answer="7 天", citations=["fabricated:0"], abstain=False),
                       dict(answer="14 天", citations=[chunks[0]["id"]], abstain=False)]:
            self.assertFalse(engine.evaluate(case, chunks, answer)["passed"])
        with self.assertRaises(ValueError):
            engine.evaluate(case, chunks, {"answer": [], "citations": [], "abstain": False})

    def test_config_rejects_invalid_types_nan_and_extra_fields(self):
        for key, value in [("top_k", True), ("min_score", float('nan')), ("chunk_size", 0), ("current_only", "false")]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                engine.run(dict(GOOD, **{key: value}))
        with self.assertRaises(ValueError):
            engine.run(dict(GOOD, code="print('not executed')"))

    def test_diagnosis_is_scoped_and_does_not_create_mastery(self):
        learning = LearningProductService(self.store)
        before = learning.dashboard()
        self.assertNotIn("correct", self.service.state()["diagnostic"][0])
        diagnosis = self.service.diagnose({"source": 0, "missing": 0, "test": 0})
        self.assertEqual(diagnosis["passed"], 1)
        self.assertEqual(diagnosis["review_topics"], ["rag", "embedding"])
        self.assertIsNone(self.service.state("other")["diagnosis"])
        self.assertEqual(before, learning.dashboard())

    def test_acceptance_requires_owned_run_diagnosis_and_transfer(self):
        run = self.service.run(GOOD)
        answers = {"updated": 1, "absence": 2, "negation": 1}
        with self.assertRaises(ValueError):
            self.service.accept(run["id"], answers)
        self.service.diagnose({"source": 1, "missing": 2, "test": 0})
        wrong = self.service.accept(run["id"], dict(answers, negation=0))
        self.assertFalse(wrong["passed"])
        self.assertTrue(self.service.accept(run["id"], answers)["passed"])
        with self.assertRaises(ValueError):
            self.service.accept(run["id"], answers, "other")
        with self.assertRaises(ValueError):
            self.service.export(run["id"], "other")
        self.assertEqual(RagWorkshop(self.store).state()["acceptance"]["data"]["run_digest"], run["digest"])

    def test_export_runs_without_models_and_matches_saved_baseline(self):
        run = self.service.run(GOOD)
        archive = zipfile.ZipFile(io.BytesIO(self.service.export(run["id"])))
        self.assertEqual(set(archive.namelist()), {"rag_lab.py", "config.json", "run-report.json", "README.md"})
        root = Path(self.temp.name)/"export"
        root.mkdir()
        archive.extractall(root)
        process = subprocess.run([sys.executable, "rag_lab.py"], cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["rows"], run["rows"])

    def test_older_evidence_and_tutor_survive_history_window(self):
        self.service.diagnose({"source": 1, "missing": 2, "test": 0})
        run = self.service.run(GOOD)
        for i in range(105):
            self.service.save_tutor_reply(run["id"], "为什么拒答？", str(i))
        state = RagWorkshop(self.store).state()
        self.assertIsNotNone(state["diagnosis"])
        self.assertEqual(state["runs"][0]["id"], run["id"])
        self.assertEqual(state["tutor"]["data"]["answer"], "104")
        self.assertTrue(self.service.export(run["id"]).startswith(b"PK"))
        self.assertTrue(self.service.accept(run["id"], {"updated": 1, "absence": 2, "negation": 1})["passed"])
        with self.assertRaises(ValueError):
            self.service.save_tutor_reply(run["id"], "为什么拒答？", "test", "other")

    def test_http_model_mode_uses_shared_router_without_tools(self):
        import clawos_server as server
        from starlette.requests import Request
        from fastapi import HTTPException
        def request(body):
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}
            return Request({"type":"http", "method":"POST", "path":"/", "headers":[]}, receive)
        async def fake_model(messages, tools):
            self.assertEqual(tools, [])
            payload = json.loads(messages[1]["content"])
            result = engine.baseline_answer(payload["passages"])
            return {"choices": [{"message": {"content": json.dumps(result)}}]}
        async def exercise():
            with patch.object(server, "_rag_workshop", return_value=self.service), patch.object(server, "call_routing_llm", side_effect=fake_model):
                response = await server.api_academy_rag_action("run", request({"config":GOOD,"mode":"model"}))
                data = json.loads(response.body)
                self.assertEqual(data["passed"], 6)
                self.assertEqual(data["mode"], "model")
                exported = await server.api_academy_rag_export(data["id"])
                self.assertTrue(exported.body.startswith(b"PK"))
            count = len(self.service.state()["runs"])
            with patch.object(server, "_rag_workshop", return_value=self.service), patch.object(server, "call_routing_llm", new=AsyncMock(side_effect=RuntimeError("offline"))):
                with self.assertRaises(HTTPException) as caught:
                    await server.api_academy_rag_action("run", request({"config":GOOD,"mode":"model"}))
                self.assertEqual(caught.exception.status_code, 502)
            self.assertEqual(len(self.service.state()["runs"]), count)
            tutor = AsyncMock(return_value={"choices": [{"message": {"content": "请先比较无答案问题的召回片段与原文。"}}]})
            with patch.object(server, "_rag_workshop", return_value=self.service), patch.object(server, "call_routing_llm", tutor):
                reply = await server.api_academy_rag_action("tutor", request({"run_id": data["id"], "question": "为什么这里需要拒答？"}))
                self.assertIn("原文", json.loads(reply.body)["answer"])
                self.assertEqual(tutor.call_args.args[1], [])
                with self.assertRaises(HTTPException):
                    await server.api_academy_rag_action("tutor", request({"run_id": data["id"], "learner_id": "other", "question": "为什么这里需要拒答？"}))
                self.assertEqual(tutor.call_count, 1)
            saved = self.service.state()["tutor"]
            with patch.object(server, "_rag_workshop", return_value=self.service), patch.object(server, "call_routing_llm", new=AsyncMock(side_effect=RuntimeError("offline"))):
                with self.assertRaises(HTTPException) as caught:
                    await server.api_academy_rag_action("tutor", request({"run_id": data["id"], "question": "为什么这里需要拒答？"}))
                self.assertEqual(caught.exception.status_code, 502)
            self.assertEqual(self.service.state()["tutor"], saved)
        asyncio.run(exercise())


if __name__ == '__main__':
    unittest.main()
