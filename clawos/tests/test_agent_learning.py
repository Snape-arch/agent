import tempfile
import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class AgentLearningTests(unittest.TestCase):
    def _store(self, directory):
        from memoryos.memory_store import MemoryStore

        return MemoryStore(str(Path(directory) / "memory.db"))

    def test_task_service_closes_trajectory_with_task_bound_reward(self):
        from agent_learning import TrajectoryLearningService
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            service = TaskService(store)
            task = service.create(
                "session-1",
                "Research a paper",
                metadata={
                    "scenario": "research",
                    "user_satisfaction": 0.8,
                    "duration_ms": 100,
                },
            )
            finished = service.finish(task["id"], "succeeded", result_payload={"ok": True})
            trajectory = store.get_agent_trajectory(task_id=task["id"])
            dataset = TrajectoryLearningService(store).export_dataset()

        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(trajectory["status"], "completed")
        self.assertEqual(trajectory["scenario"], "research")
        self.assertGreater(trajectory["total_reward"], 0)
        self.assertEqual(dataset["manifest"]["trajectory_count"], 1)
        self.assertEqual(dataset["schema"], "clawos.agent-learning.v1")

    def test_policy_decision_and_reward_are_persisted_as_trajectory_step(self):
        from policy_optimizer import PolicyOptimizer
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            tasks = TaskService(store)
            optimizer = PolicyOptimizer(store, random_seed=3)
            optimizer.register_group(
                "routing:research",
                [
                    {
                        "name": "deep",
                        "arm_type": "workflow",
                        "payload": {"workflow": "deep"},
                    }
                ],
                exploration_rate=0,
            )
            task = tasks.create(
                "session-2", "Analyze evidence", metadata={"scenario": "research"}
            )
            selection = optimizer.select(
                "routing:research",
                {"scenario": "research", "task_description": "Analyze evidence"},
                task_id=task["id"],
                session_id="session-2",
            )
            optimizer.reward(
                selection["id"], success=1, satisfaction=0.9, latency_ms=100
            )
            tasks.finish(task["id"], "succeeded")
            trajectory = store.get_agent_trajectory(task_id=task["id"])

        self.assertEqual(len(trajectory["steps"]), 1)
        step = trajectory["steps"][0]
        self.assertEqual(step["action_name"], "deep")
        self.assertEqual(step["policy_selection_id"], selection["id"])
        self.assertIsNotNone(step["step_reward"])
        self.assertIsNotNone(step["discounted_return"])

    def test_dataset_and_preferences_redact_secrets(self):
        from agent_learning import TrajectoryLearningService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            service = TrajectoryLearningService(store)
            preference = service.record_preference(
                task_context={"api_key": "do-not-export", "scenario": "writing"},
                chosen={"text": "concise", "token": "private"},
                rejected={"text": "verbose"},
            )
            dataset = service.export_dataset()

        self.assertEqual(preference["task_context"]["api_key"], "[redacted]")
        self.assertEqual(preference["chosen"]["token"], "[redacted]")
        self.assertEqual(
            dataset["preference_pairs"][0]["chosen"]["token"], "[redacted]"
        )

    def test_train_evaluate_activate_and_route_with_policy_network(self):
        from agent_learning import (
            AgentSkillPolicyNetwork,
            TrajectoryCritic,
        )
        from policy_optimizer import PolicyOptimizer
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            tasks = TaskService(store)
            optimizer = PolicyOptimizer(store, random_seed=11)
            optimizer.register_group(
                "routing:research",
                [
                    {
                        "name": "fast",
                        "arm_type": "workflow",
                        "payload": {"workflow": "fast"},
                    },
                    {
                        "name": "deep",
                        "arm_type": "workflow",
                        "payload": {"workflow": "deep"},
                    },
                ],
                exploration_rate=1,
            )
            for index in range(300):
                task = tasks.create(
                    f"session-{index}",
                    f"Research task {index}",
                    metadata={"scenario": "research"},
                )
                selection = optimizer.select(
                    "routing:research",
                    {
                        "scenario": "research",
                        "task_description": f"compare evidence {index % 3}",
                    },
                    task_id=task["id"],
                    session_id=f"session-{index}",
                )
                reward = 0.95 if selection["arm_name"] == "deep" else 0.1
                optimizer.reward(
                    selection["id"],
                    success=reward,
                    satisfaction=reward,
                    latency_ms=100,
                )
                tasks.finish(
                    task["id"],
                    "succeeded" if selection["arm_name"] == "deep" else "failed",
                )

            network = AgentSkillPolicyNetwork(store, feature_dim=64, epochs=80)
            candidate = network.train(
                "routing:research", min_examples=30, trained_by="test"
            )
            evaluated = TrajectoryCritic(store).evaluate(
                candidate["id"], min_samples=30, regression_tolerance=0.1
            )
            with self.assertRaisesRegex(ValueError, "confirmed=true"):
                TrajectoryCritic(store).activate(candidate["id"], confirmed=False)
            active = TrajectoryCritic(store).activate(
                candidate["id"], confirmed=True
            )
            arms, _ = store.list_policy_arms("routing:research")
            scores = network.active_scores(
                "routing:research",
                {"scenario": "research", "task_description": "compare evidence"},
                arms,
            )
            store.upsert_policy_group(
                "routing:research",
                optimizer_type="hybrid_ucb_agent_skill_policy_v0",
                exploration_rate=0,
            )
            live_task = tasks.create(
                "live-session",
                "Compare live evidence",
                metadata={"scenario": "research"},
            )
            live_selection = PolicyOptimizer(
                store, random_seed=5, policy_network=network
            ).select(
                "routing:research",
                {
                    "scenario": "research",
                    "task_description": "compare evidence",
                },
                task_id=live_task["id"],
                session_id="live-session",
            )
            with self.assertRaisesRegex(ValueError, "confirmed=true"):
                TrajectoryCritic(store).rollback(active["id"], confirmed=False)
            rolled_back = TrajectoryCritic(store).rollback(
                active["id"], confirmed=True
            )

        self.assertEqual(candidate["status"], "candidate")
        self.assertTrue(candidate["training_metrics"]["group_disjoint_holdout"])
        self.assertEqual(candidate["training_metrics"]["holdout_count"], 60)
        self.assertTrue(
            set(candidate["weights"]["training_example_ids"]).isdisjoint(
                candidate["weights"]["holdout_example_ids"]
            )
        )
        self.assertTrue(evaluated["evaluation_metrics"]["passed"])
        self.assertTrue(
            evaluated["evaluation_metrics"]["group_disjoint_holdout"]
        )
        self.assertEqual(
            evaluated["evaluation_metrics"]["independent_reward_model"],
            "training_arm_mean_v1",
        )
        self.assertEqual(evaluated["status"], "shadow")
        self.assertEqual(active["status"], "active")
        self.assertEqual(
            max(scores["scores"], key=scores["scores"].get), "deep"
        )
        self.assertEqual(scores["model"]["id"], active["id"])
        self.assertEqual(live_selection["arm_name"], "deep")
        self.assertEqual(
            live_selection["context"]["_agent_learning"]["model"]["id"],
            active["id"],
        )
        self.assertEqual(rolled_back["rolled_back"]["status"], "rolled_back")
        self.assertIsNone(rolled_back["restored"])

    def test_critic_rejects_candidate_when_matched_action_has_safety_violation(self):
        from agent_learning import AgentSkillPolicyNetwork, TrajectoryCritic
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = self._store(td)
            tasks = TaskService(store)
            store.upsert_policy_group("routing:general", exploration_rate=0)
            arm = store.upsert_policy_arm(
                "routing:general",
                "unsafe",
                "workflow",
                payload={"workflow": "unsafe"},
            )
            group = store.upsert_policy_group("routing:general", exploration_rate=0)
            for index in range(150):
                task = tasks.create(
                    f"unsafe-{index}", "Unsafe candidate",
                    metadata={"scenario": "general"},
                )
                selection = store.create_policy_selection(
                    group["id"],
                    arm["id"],
                    {"scenario": "general"},
                    1.0,
                    task_id=task["id"],
                    session_id=f"unsafe-{index}",
                )
                store.append_agent_trajectory_step(
                    task["id"],
                    state={"scenario": "general"},
                    action_type="workflow",
                    action_name="unsafe",
                    action_payload=arm["payload"],
                    policy_selection_id=selection["id"],
                    behavior_propensity=1.0,
                    safety_violation=True,
                )
                store.record_policy_reward(
                    selection["id"], 1, 1, 0, 0, 0.9
                )
                store.complete_agent_trajectory_selection(
                    selection["id"], 0.9, {"success": 1}
                )
                tasks.finish(task["id"], "succeeded")
            candidate = AgentSkillPolicyNetwork(
                store, feature_dim=32
            ).train("routing:general", min_examples=30)
            evaluated = TrajectoryCritic(store).evaluate(
                candidate["id"], min_samples=30
            )

        self.assertFalse(evaluated["evaluation_metrics"]["passed"])
        self.assertEqual(evaluated["status"], "rejected")
        self.assertGreater(
            evaluated["evaluation_metrics"]["safety_violation_count"], 0
        )

    def test_server_exposes_agent_learning_control_plane(self):
        server_source = (ROOT / "clawos_server.py").read_text(encoding="utf-8")

        self.assertIn("/api/agent-learning/trajectories", server_source)
        self.assertIn("/api/agent-learning/models/train", server_source)
        self.assertIn("/api/agent-learning/models/{model_id}/evaluate", server_source)
        self.assertIn("/api/agent-learning/models/{model_id}/activate", server_source)
        self.assertIn("/api/agent-learning/models/{model_id}/rollback", server_source)


if __name__ == "__main__":
    unittest.main()
