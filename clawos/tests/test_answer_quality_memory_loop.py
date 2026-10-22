import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AnswerQualityValidatorTests(unittest.TestCase):
    def test_claim_evidence_failures_are_distinguished(self):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        evidence = [{"citation": "doc:1", "text": "仅当测试和回归测试都通过时，修复任务才可以结束。"}]
        supported = ClaimEvidenceAnswerValidator.validate(
            query="何时结束？", answer="仅当测试和回归测试都通过时，修复任务才可以结束。 [doc:1]",
            evidence=evidence,
        )
        missing = ClaimEvidenceAnswerValidator.validate(
            query="何时结束？", answer="仅当测试和回归测试都通过时，修复任务才可以结束。",
            evidence=evidence,
        )
        condition = ClaimEvidenceAnswerValidator.validate(
            query="何时结束？", answer="修复任务才可以结束。 [doc:1]", evidence=evidence,
        )
        mismatch = ClaimEvidenceAnswerValidator.validate(
            query="何时结束？", answer="仅当测试和回归测试都通过时，修复任务才可以结束。 [doc:2]",
            evidence=evidence,
        )

        self.assertTrue(supported["valid"])
        self.assertEqual(missing["issues"]["missing_citation"], 1)
        self.assertEqual(condition["issues"]["condition_omission"], 1)
        self.assertEqual(mismatch["issues"]["citation_mismatch"], 1)

    def test_refusal_contract(self):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        valid = ClaimEvidenceAnswerValidator.validate(
            query="未知事实", answer="现有知识库中没有足够证据支持这个结论。", evidence=[], must_refuse=True,
        )
        invalid = ClaimEvidenceAnswerValidator.validate(
            query="未知事实", answer="结论一定成立。 [doc:missing]", evidence=[], must_refuse=True,
        )
        self.assertEqual(valid["decision"], "correct_refusal")
        self.assertTrue(valid["valid"])
        self.assertEqual(invalid["issues"]["missing_refusal"], 1)

    def test_one_citation_can_support_multiple_atomic_evidence_rows(self):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        result = ClaimEvidenceAnswerValidator.validate(
            query="aware 与 naive datetime 有何区别？",
            answer="Aware datetime includes timezone information. [doc:datetime]",
            evidence=[
                {"citation": "doc:datetime", "text": "Aware datetime includes timezone information."},
                {"citation": "doc:datetime", "text": "Naive datetime lacks timezone information."},
            ],
        )
        self.assertTrue(result["valid"])

    def test_reversed_comparison_roles_are_rejected(self):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        cases = [
            ("Model A outperformed Model B in accuracy.", "Model B outperformed Model A in accuracy."),
            ("模型A的准确率高于模型B。", "模型B的准确率高于模型A。"),
            ("方案甲的延迟低于方案乙。", "方案甲的延迟高于方案乙。"),
        ]
        for evidence_text, answer_text in cases:
            with self.subTest(answer=answer_text):
                result = ClaimEvidenceAnswerValidator.validate(
                    query="比较两者", answer=f"{answer_text} [doc:comparison]",
                    evidence=[{"citation": "doc:comparison", "text": evidence_text}],
                )
                self.assertFalse(result["valid"])
                self.assertEqual(result["issues"]["relation_mismatch"], 1)
                self.assertEqual(result["claims"][0]["relation_mismatch"], 1)

    def test_reversed_condition_roles_are_rejected(self):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        cases = [
            ("The service retries only when the request fails.", "The request fails only when the service retries."),
            ("仅当测试通过时，任务才可以结束。", "仅当任务结束时，测试才可以通过。"),
        ]
        for evidence_text, answer_text in cases:
            with self.subTest(answer=answer_text):
                result = ClaimEvidenceAnswerValidator.validate(
                    query="条件是什么", answer=f"{answer_text} [doc:condition]",
                    evidence=[{"citation": "doc:condition", "text": evidence_text}],
                )
                self.assertFalse(result["valid"])
                self.assertEqual(result["issues"]["relation_mismatch"], 1)

    def test_relation_guard_keeps_supported_paraphrases(self):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        cases = [
            ("Model A outperformed Model B in accuracy.", "In accuracy, Model A exceeded Model B."),
            ("Model A was higher than Model B in accuracy.", "Model B was lower than Model A in accuracy."),
            ("仅当测试通过时，任务才可以结束。", "任务只有在测试通过时才可以结束。"),
        ]
        for evidence_text, answer_text in cases:
            with self.subTest(answer=answer_text):
                result = ClaimEvidenceAnswerValidator.validate(
                    query="总结结论", answer=f"{answer_text} [doc:supported]",
                    evidence=[{"citation": "doc:supported", "text": evidence_text}],
                )
                self.assertTrue(result["valid"])
                self.assertEqual(result["issues"]["relation_mismatch"], 0)

    def test_conflicting_relation_cannot_be_diluted_by_generic_evidence(self):
        from services.answer_quality_service import ClaimEvidenceAnswerValidator

        result = ClaimEvidenceAnswerValidator.validate(
            query="哪个模型更准确？",
            answer="Model B outperformed Model A in accuracy. [doc:mix]",
            evidence=[
                {"citation": "doc:mix", "text": "Model A outperformed Model B in accuracy."},
                {"citation": "doc:mix", "text": "Model A and Model B were compared in accuracy."},
            ],
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["issues"]["relation_mismatch"], 1)


class AnswerQualityFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        from memoryos.memory_store import MemoryStore
        from services.answer_quality_service import AnswerQualityService
        self.store = MemoryStore(str(Path(self.temp.name) / "quality.db"))
        self.quality = AnswerQualityService(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_real_feedback_requires_consent_and_is_not_mixed_with_proxy(self):
        common = {
            "query": "何时结束？", "answer": "测试通过后结束。 [doc:1]",
            "evidence": [{"citation": "doc:1", "text": "测试通过后结束。"}],
        }
        with self.assertRaises(ValueError):
            self.quality.record({**common, "origin": "consented_user"})
        with self.assertRaises(ValueError):
            self.quality.record({**common, "origin": "benchmark_proxy", "consented": True})
        self.quality.record({**common, "origin": "consented_user", "consented": True})
        self.quality.record({**common, "query": "代理问题", "origin": "benchmark_proxy"})
        stats = self.quality.stats()
        self.assertEqual(stats["consented_user_count"], 1)
        self.assertEqual(stats["proxy_count"], 1)
        self.assertIn("never counted", stats["truth_boundary"])

    def test_frozen_proxy_benchmark_includes_relation_adversaries_and_confidence_intervals(self):
        from services.answer_quality_benchmark import DEFAULT_CORPUS, run_answer_quality_benchmark

        report = run_answer_quality_benchmark(DEFAULT_CORPUS)
        self.assertEqual(report["case_count"], 252)
        self.assertEqual(report["fixed_test_count"], 60)
        self.assertFalse(report["counts_as_real_user_feedback"])
        self.assertTrue(report["passed"])
        self.assertGreaterEqual(report["confidence_intervals"]["classification_accuracy"]["lower"], 0.95)
        self.assertEqual(report["split_confidence_intervals"]["test"]["total"], 60)
        self.assertEqual(report["confidence_intervals"]["relation_preservation"]["total"], 4)
        self.assertEqual(report["confidence_intervals"]["relation_reversal_rejection"]["total"], 8)
        self.assertEqual(report["metrics"]["relation_preservation"], 1.0)
        self.assertEqual(report["metrics"]["relation_reversal_rejection"], 1.0)
        self.assertFalse(report["failures"])

    def test_explicit_console_consent_captures_real_query_answer_pair(self):
        import clawos_server as server
        from services.task_service import TaskService

        task = TaskService(self.store).create("session-q", "真实查询：如何验证引用？")
        TaskService(self.store).finish(task["id"], "succeeded", result_payload={})

        class FakeRequest:
            headers = {}

            async def json(self):
                return {
                    "task_id": task["id"], "signal_type": "binary", "value": True,
                    "quality_consent": True,
                    "quality_answer": "答案必须由对应证据支持。 [doc:quality]",
                    "quality_evidence": [{"citation": "doc:quality", "text": "答案必须由对应证据支持。"}],
                }

        old_store = server.g_memory_store
        server.g_memory_store = self.store
        try:
            payload = json.loads(asyncio.run(server.api_agent_learning_feedback(FakeRequest())).body)
        finally:
            server.g_memory_store = old_store
        self.assertTrue(payload["answer_quality_feedback"]["recorded"])
        self.assertEqual(self.quality.stats()["consented_user_count"], 1)


class SelectiveMemoryLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        from memoryos.memory_store import MemoryStore
        from services.selective_memory_service import SelectiveMemoryService
        self.store = MemoryStore(str(Path(self.temp.name) / "memory.db"))
        self.service = SelectiveMemoryService(self.store)
        self.evidence = [{"type": "test_passed", "artifact": "report.xml", "digest": "sha256:abc"}]

    def tearDown(self):
        self.temp.cleanup()

    def test_candidate_requires_review_then_promotes_to_typed_store(self):
        proposal = self.service.propose_from_task(
            task_id=7, outcome="succeeded", success_evidence=self.evidence,
            candidates=[{"type": "fact", "key": "release gate", "content": "Regression tests must pass before release.", "source_ref": "task:7"}],
        )
        candidate = proposal["candidates"][0]
        self.assertEqual(candidate["status"], "pending_review")
        with self.assertRaises(ValueError):
            self.service.promote(candidate["id"], actor_id="user", confirmed=True)
        reviewed = self.service.review(candidate["id"], "approve", reviewer="user", confirmed=True)
        promoted = self.service.promote(reviewed["id"], actor_id="user", confirmed=True)
        self.assertEqual(promoted["status"], "promoted")
        self.assertEqual(promoted["promoted_target"]["kind"], "knowledge_v2")

    def test_sensitive_duplicate_and_implicit_preference_are_blocked(self):
        secret = self.service.propose_from_task(
            task_id=8, outcome="success", success_evidence=self.evidence,
            candidates=[{"type": "project_rule", "key": "credential", "content": "api_key=secret-value-123456"}],
        )["candidates"][0]
        self.assertEqual(secret["status"], "blocked_sensitive")
        self.assertNotIn("secret-value-123456", secret["content"])

        implicit = self.service.propose_from_task(
            task_id=9, outcome="success", success_evidence=self.evidence,
            candidates=[{"type": "user_preference", "key": "format", "content": "User prefers concise answers."}],
        )["candidates"][0]
        self.assertEqual(implicit["status"], "rejected_insufficient_evidence")

        first = self.service.propose_from_task(
            task_id=10, outcome="success", success_evidence=self.evidence,
            candidates=[{"type": "project_rule", "key": "gate", "content": "Run regression tests before release."}],
        )["candidates"][0]
        duplicate = self.service.propose_from_task(
            task_id=11, outcome="success", success_evidence=self.evidence,
            candidates=[{"type": "project_rule", "key": "gate", "content": "Run regression tests before release."}],
        )["candidates"][0]
        self.assertEqual(first["status"], "pending_review")
        self.assertEqual(duplicate["status"], "duplicate")

    def test_task_completion_emits_reviewable_candidates(self):
        from services.task_service import TaskService

        tasks = TaskService(self.store)
        task = tasks.create("session-1", "verify release gate")
        finished = tasks.finish(task["id"], "succeeded", result_payload={
            "memory_candidates": [{"type": "failure_experience", "key": "lint retry", "content": "Re-run lint after changing formatter settings."}],
            "success_evidence": self.evidence,
        })
        proposal = finished["metadata"]["selective_memory_proposal"]
        self.assertEqual(proposal["review_required"], 1)
        self.assertEqual(len(proposal["candidate_ids"]), 1)


class QualitySurfaceTests(unittest.TestCase):
    def test_console_exposes_quality_boundary_and_memory_review(self):
        html = (ROOT / "static" / "console.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "assets" / "console.js").read_text(encoding="utf-8")
        functions = (ROOT / "functions.jsonl").read_text(encoding="utf-8")
        for token in ("answerQualitySummary", "memoryCandidateTable"):
            self.assertIn(token, html)
        for token in ("consented_user_count", "reviewMemoryCandidate", "promoteMemoryCandidate"):
            self.assertIn(token, script)
        for token in ('"name":"answer_quality_benchmark"', '"name":"answer_quality_validate"', '"name":"selective_memory"'):
            self.assertIn(token, functions)


if __name__ == "__main__":
    unittest.main()
