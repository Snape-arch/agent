import tempfile
import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FeedbackPreferenceLearningTests(unittest.TestCase):
    def _store(self, directory):
        from memoryos.memory_store import MemoryStore

        return MemoryStore(str(Path(directory) / "memory.db"))

    def test_missing_feedback_is_explicitly_missing_not_neutral_rating(self):
        from agent_learning import TrajectoryLearningService
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            task = TaskService(store).create(
                "missing-feedback",
                "Task without explicit feedback",
                metadata={"scenario": "general"},
            )
            TaskService(store).finish(task["id"], "succeeded")
            trajectory = store.get_agent_trajectory(task_id=task["id"])
            components, _ = TrajectoryLearningService(store).reward_from_task(
                store.get_task(task["id"])["task"]
            )

        self.assertEqual(trajectory["reward_components"]["feedback_missing"], 1.0)
        self.assertIsNone(trajectory["reward_components"]["explicit_feedback"])
        self.assertEqual(components["feedback_missing"], 1.0)
        self.assertIsNone(components["explicit_feedback"])

    def test_explicit_feedback_revises_trajectory_and_policy_reward(self):
        from agent_learning import FeedbackLearningService
        from policy_optimizer import PolicyOptimizer
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            tasks = TaskService(store)
            optimizer = PolicyOptimizer(store, random_seed=2)
            optimizer.register_group(
                "routing:general",
                [{
                    "name": "baseline",
                    "arm_type": "workflow",
                    "payload": {"workflow": "baseline"},
                }],
                exploration_rate=0,
            )
            task = tasks.create(
                "feedback-session",
                "Feedback-bound task",
                metadata={"scenario": "general"},
            )
            selection = optimizer.select(
                "routing:general",
                {"scenario": "general"},
                task_id=task["id"],
                session_id="feedback-session",
            )
            store.update_task_metadata(
                task["id"],
                {
                    "policy_optimizer_selections": [{
                        "selection_id": selection["id"],
                        "group_name": selection["group_name"],
                        "arm_name": selection["arm_name"],
                    }]
                },
            )
            tasks.finish(task["id"], "succeeded")
            before = optimizer.stats("routing:general")["arms"][0]["average_reward"]
            result = FeedbackLearningService(store).record(
                task_id=task["id"],
                signal_type="rating",
                value=5,
                idempotency_key="feedback-once",
            )
            after = optimizer.stats("routing:general")["arms"][0]["average_reward"]
            trajectory = store.get_agent_trajectory(task_id=task["id"])
            duplicate = FeedbackLearningService(store).record(
                task_id=task["id"],
                signal_type="rating",
                value=5,
                idempotency_key="feedback-once",
            )

        self.assertGreater(after, before)
        self.assertEqual(
            trajectory["reward_components"]["explicit_feedback"], 1.0
        )
        self.assertEqual(trajectory["reward_components"]["feedback_missing"], 0.0)
        self.assertEqual(len(result["revised_policy_rewards"]), 1)
        self.assertEqual(
            duplicate["feedback"]["id"], result["feedback"]["id"]
        )

    def test_reward_calibration_blocks_when_real_data_gate_is_not_met(self):
        from agent_learning import RewardCalibrator

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            with self.assertRaisesRegex(ValueError, "data gate not met"):
                RewardCalibrator(store).train(
                    min_trajectories=1,
                    min_explicit_feedback=1,
                    min_arm_exposure=1,
                )

    def test_codex_evaluator_feedback_is_grounded_but_not_a_human_user(self):
        from agent_learning import FeedbackLearningService
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            tasks = TaskService(store)
            human_task = tasks.create("human", "Human-rated task")
            tasks.finish(human_task["id"], "succeeded")
            evaluator_task = tasks.create("codex", "Evaluator-rated task")
            tasks.finish(evaluator_task["id"], "succeeded")
            feedback = FeedbackLearningService(store)
            feedback.record(
                task_id=human_task["id"], signal_type="score", value=1,
                owner_id="human-1",
            )
            with self.assertRaisesRegex(ValueError, "evidence_digest"):
                feedback.record(
                    task_id=evaluator_task["id"],
                    signal_type="score", value=1,
                    owner_id="codex-evaluator",
                    metadata={"evaluator_origin": "codex_evaluator"},
                )
            result = feedback.record(
                task_id=evaluator_task["id"],
                signal_type="score", value=1,
                owner_id="codex-evaluator",
                metadata={
                    "evaluator_origin": "codex_evaluator",
                    "evidence_digest": "sha256:test-evidence",
                    "evaluation_method": "hidden_tests_and_patch_review",
                },
            )
            quality = feedback.quality_report()

        self.assertFalse(
            result["provenance"]["counts_as_independent_human"]
        )
        self.assertTrue(result["provenance"]["counts_as_grounded_reward"])
        self.assertEqual(quality["explicit_feedback_count"], 2)
        self.assertEqual(quality["grounded_feedback_count"], 2)
        self.assertEqual(quality["independent_human_owner_count"], 1)
        self.assertEqual(quality["evaluator_owner_count"], 1)
        self.assertEqual(
            quality["feedback_origin_counts"]["codex_evaluator"], 1
        )

    def test_reward_calibration_trains_evaluates_and_requires_confirmation(self):
        from agent_learning import FeedbackLearningService, RewardCalibrator
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            tasks = TaskService(store)
            feedback = FeedbackLearningService(store)
            for index in range(50):
                succeeded = index % 2 == 0
                task = tasks.create(
                    f"calibration-{index}",
                    f"Calibration task {index}",
                    metadata={
                        "scenario": "research",
                        "evidence_correctness": 1.0 if succeeded else 0.0,
                        "citation_validity": 1.0 if succeeded else 0.0,
                    },
                )
                tasks.finish(
                    task["id"], "succeeded" if succeeded else "failed"
                )
                feedback.record(
                    task_id=task["id"],
                    signal_type="score",
                    value=1.0 if succeeded else 0.0,
                    idempotency_key=f"calibration-feedback-{index}",
                )
            calibrator = RewardCalibrator(store)
            candidate = calibrator.train(trained_by="test")
            evaluated = calibrator.evaluate(candidate["id"])
            with self.assertRaisesRegex(ValueError, "confirmed=true"):
                calibrator.activate(candidate["id"], confirmed=False)
            active = calibrator.activate(candidate["id"], confirmed=True)

        self.assertEqual(candidate["status"], "candidate")
        self.assertTrue(evaluated["evaluation_metrics"]["passed"])
        self.assertEqual(evaluated["status"], "shadow")
        self.assertEqual(active["status"], "active")
        self.assertEqual(active["training_metrics"]["sample_count"], 50)

    def test_preference_ranker_blocks_below_hard_sample_gate(self):
        from agent_learning import PreferenceRanker

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            store.create_agent_preference_pair(
                {"scenario": "research"},
                {"text": "preferred"},
                {"text": "rejected"},
            )
            with self.assertRaisesRegex(ValueError, "data gate not met"):
                PreferenceRanker(store).train(min_pairs=1, min_per_scenario=1)

    def test_preference_ranker_full_candidate_shadow_active_loop(self):
        from agent_learning import PreferenceRanker

        scenarios = ("learning", "research", "project", "office")
        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            for index in range(100):
                scenario = scenarios[index % len(scenarios)]
                store.create_agent_preference_pair(
                    {
                        "scenario": scenario,
                        "task_id": index,
                        "request": f"{scenario} task",
                    },
                    {
                        "text": (
                            "preferred structured evidence-first response "
                            f"for {scenario} {index}"
                        )
                    },
                    {"text": f"bad {scenario} {index}"},
                    confidence=1.0,
                )
            ranker = PreferenceRanker(store, feature_dim=64, epochs=120)
            readiness = ranker.readiness(store)
            candidate = ranker.train(trained_by="test")
            evaluated = ranker.evaluate(candidate["id"])
            with self.assertRaisesRegex(ValueError, "confirmed=true"):
                ranker.activate(candidate["id"], confirmed=False)
            active = ranker.activate(candidate["id"], confirmed=True)
            result = ranker.rank(
                {"scenario": "research", "request": "research task"},
                [
                    {"text": "bad research answer"},
                    {"text": "preferred structured evidence-first response"},
                ],
            )

        self.assertTrue(readiness["ready"])
        self.assertEqual(candidate["status"], "candidate")
        self.assertTrue(evaluated["evaluation_metrics"]["passed"])
        self.assertEqual(evaluated["status"], "shadow")
        self.assertEqual(active["status"], "active")
        self.assertEqual(result["selected_index"], 1)
        self.assertGreaterEqual(result["confidence"], 0.5)

    def test_advanced_learning_reports_not_ready_without_real_scale(self):
        from agent_learning import AdvancedLearningReadiness

        with tempfile.TemporaryDirectory() as td:
            report = AdvancedLearningReadiness(self._store(td)).report()

        self.assertFalse(report["online_rl_claimed"])
        self.assertFalse(report["deep_router"]["ready"])
        self.assertFalse(report["trajectory_rl"]["ready"])
        self.assertFalse(report["behavior_lora"]["ready"])

    def test_server_and_console_expose_explicit_feedback_loop(self):
        server = (ROOT / "clawos_server.py").read_text(encoding="utf-8")
        console = (
            ROOT / "static" / "assets" / "console.js"
        ).read_text(encoding="utf-8")

        self.assertIn("/api/agent-learning/feedback", server)
        self.assertIn("/api/agent-learning/data-quality", server)
        self.assertIn("/api/agent-learning/reward-calibrations/train", server)
        self.assertIn("/api/agent-learning/preference-ranker/train", server)
        self.assertIn("/api/agent-learning/advanced-readiness", server)
        self.assertIn("attachFeedbackControls", console)
        self.assertIn("submitTaskFeedback", console)


if __name__ == "__main__":
    unittest.main()
