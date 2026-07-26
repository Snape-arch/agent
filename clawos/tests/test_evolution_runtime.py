import tempfile
import unittest
from pathlib import Path


class EvolutionRuntimeTests(unittest.TestCase):
    def test_runtime_policy_shadow_and_canary_are_stably_resolved(self):
        from memoryos.memory_store import MemoryStore
        from reflection.evolution_runtime import RuntimePolicyController
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.set_runtime_policy("retrieval_params", "default", {"top_k": 5})
            manager = SelfEvolutionManager(store, benchmark_runner=object())
            run = manager.create_run(
                "retrieval_params", "default", {"top_k": 5}, {"top_k": 30}
            )
            store.update_self_evolution_run(
                run["id"],
                status="shadow",
                release_stage="shadow",
                publish_decision="canary_pending",
            )
            controller = RuntimePolicyController(store)
            shadow = controller.resolve("retrieval_params", "default", "session-a")
            store.update_self_evolution_run(
                run["id"],
                status="canary",
                release_stage="canary",
                traffic_percent=50,
                publish_decision="canary",
            )
            first = controller.resolve("retrieval_params", "default", "session-a")
            second = controller.resolve("retrieval_params", "default", "session-a")

        self.assertEqual(shadow["payload"], {"top_k": 5})
        self.assertEqual(shadow["shadow_payload"], {"top_k": 30})
        self.assertEqual(first["bucket"], second["bucket"])
        self.assertEqual(first["exposure"], second["exposure"])

    def test_runtime_policy_materializes_prompt_retrieval_and_routing(self):
        from reflection.evolution_runtime import RuntimePolicyController

        base = {
            "allowed_tools": ["knowledge_search", "web_fetch"],
            "requires_confirmation": ["web_fetch"],
        }
        selection = {
            "payload": {"allowed_tools": ["knowledge_search"], "deny_tools": ["web_fetch"]},
            "target_type": "tool_routing_policy",
            "target_key": "research",
            "policy_version": 2,
            "source": "runtime_policy",
            "release_stage": "active",
            "exposure": "candidate",
        }
        routed = RuntimePolicyController.apply_routing(base, selection)
        prompt = RuntimePolicyController.apply_prompt(
            "base", {"payload": {"system": "cite evidence"}}
        )
        retrieval = RuntimePolicyController.retrieval_options({
            "payload": {"top_k": 9, "recall_top_k": 40, "rerank_top_k": 7}
        })

        self.assertEqual(routed["allowed_tools"], ["knowledge_search"])
        self.assertIn("cite evidence", prompt)
        self.assertEqual(retrieval["recall_top_k"], 40)

    def test_failed_canary_task_automatically_stops_run(self):
        from memoryos.memory_store import MemoryStore
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            manager = SelfEvolutionManager(store, benchmark_runner=object())
            run = manager.create_run(
                "prompt_policy", "research", {"system": "base"}, {"system": "candidate"}
            )
            store.update_self_evolution_run(
                run["id"],
                status="canary",
                release_stage="canary",
                traffic_percent=10,
                publish_decision="canary",
            )
            task = store.start_task(
                "s1",
                "candidate task",
                metadata={"runtime_policies": [{
                    "run_id": run["id"],
                    "exposure": "candidate",
                }]},
            )
            store.finish_task(task["id"], "failed", error="boom")
            stopped = store.get_self_evolution_run(run["id"])

        self.assertEqual(stopped["status"], "rolled_back")
        self.assertEqual(stopped["release_stage"], "stopped")
        self.assertEqual(stopped["traffic_percent"], 0)

    def test_policy_reward_is_derived_from_bound_terminal_task(self):
        from memoryos.memory_store import MemoryStore
        from policy_optimizer import PolicyOptimizer

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            optimizer = PolicyOptimizer(store)
            optimizer.register_group(
                "routing",
                [{"name": "safe", "arm_type": "workflow", "payload": {"safe": True}}],
                exploration_rate=0,
            )
            task = store.start_task("s1", "run")
            selection = optimizer.select("routing", task_id=task["id"], session_id="s1")
            store.finish_task(task["id"], "succeeded", result_payload={"ok": True})
            reward = optimizer.reward_from_task(
                selection["id"], task["id"], satisfaction=1
            )

        self.assertGreater(reward["reward"], 0)
        self.assertEqual(reward["selection"]["status"], "rewarded")

    def test_task_service_automatically_rewards_selected_policy(self):
        from memoryos.memory_store import MemoryStore
        from policy_optimizer import PolicyOptimizer
        from services.task_service import TaskService

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            optimizer = PolicyOptimizer(store)
            optimizer.register_group(
                "routing:research",
                [{"name": "evidence-first", "arm_type": "workflow", "payload": {
                    "allowed_tools": ["knowledge_search"],
                }}],
                exploration_rate=0,
            )
            service = TaskService(store)
            task = service.create("s1", "research")
            selection = optimizer.select(
                "routing:research", task_id=task["id"], session_id="s1"
            )
            store.update_task_metadata(task["id"], {
                "policy_optimizer_selections": [{
                    "selection_id": selection["id"],
                    "group_name": selection["group_name"],
                    "arm_name": selection["arm_name"],
                }],
            })
            service.finish(task["id"], "succeeded", result_payload={"ok": True})
            stats = optimizer.stats("routing:research")

        self.assertEqual(stats["arms"][0]["pull_count"], 1)

    def test_reflection_failure_clusters_drive_candidate(self):
        from reflection.self_evolution import SelfEvolutionManager

        candidate = SelfEvolutionManager.generate_candidate_from_failures(
            "tool_routing_policy",
            {},
            [
                {"failure_category": "parameter", "patterns": ["invalid path"]},
                {"failure_category": "parameter", "patterns": ["invalid path"]},
                {"failure_category": "permission", "patterns": ["permission denied"]},
            ],
        )

        self.assertTrue(candidate["validate_inputs"])
        self.assertTrue(candidate["confirm_high_risk"])
        self.assertEqual(
            candidate["evidence_summary"]["repeated_patterns"][0]["count"], 2
        )

    def test_restrictive_runtime_routing_does_not_bypass_through_mtclaw(self):
        server_source = (
            Path(__file__).resolve().parents[1] / "clawos_server.py"
        ).read_text(encoding="utf-8")

        self.assertIn("mtclaw_policy_compatible = not", server_source)
        self.assertIn("routing_policy_payload.get(\"deny_tools\")", server_source)
        self.assertIn(
            "g_mtclaw_adapter.enabled and mtclaw_policy_compatible",
            server_source,
        )


if __name__ == "__main__":
    unittest.main()
