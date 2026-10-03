import tempfile
import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class PolicyOptimizerTests(unittest.TestCase):
    def test_contextual_ucb_learns_higher_reward_arm(self):
        from memoryos.memory_store import MemoryStore
        from policy_optimizer import PolicyOptimizer

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            optimizer = PolicyOptimizer(store, random_seed=7)
            optimizer.register_group(
                "research-agent",
                [
                    {
                        "name": "fast-reader",
                        "arm_type": "agent",
                        "payload": {"agent": "ResearchAgentFast"},
                        "contexts": ["research"],
                    },
                    {
                        "name": "deep-reader",
                        "arm_type": "agent",
                        "payload": {"agent": "ResearchAgentDeep"},
                        "contexts": ["research"],
                    },
                ],
                exploration_rate=0,
            )
            first = optimizer.select("research-agent", {"scenario": "research"})
            optimizer.reward(
                first["id"], success=0.2, satisfaction=0.2,
                latency_ms=900, resource_cost=0.8,
            )
            second = optimizer.select("research-agent", {"scenario": "research"})
            optimizer.reward(
                second["id"], success=1, satisfaction=1,
                latency_ms=200, resource_cost=0.2,
            )
            third = optimizer.select("research-agent", {"scenario": "research"})
            stats = optimizer.stats("research-agent")

        self.assertNotEqual(first["arm_id"], second["arm_id"])
        self.assertEqual(third["arm_id"], second["arm_id"])
        rewards = {arm["id"]: arm["average_reward"] for arm in stats["arms"]}
        self.assertGreater(rewards[second["arm_id"]], rewards[first["arm_id"]])

    def test_reward_formula_matches_plan(self):
        from memoryos.memory_store import MemoryStore
        from policy_optimizer import PolicyOptimizer

        with tempfile.TemporaryDirectory() as td:
            optimizer = PolicyOptimizer(MemoryStore(str(Path(td) / "memory.db")))
            optimizer.register_group(
                "prompt",
                [{"name": "concise", "arm_type": "prompt", "payload": {"prompt": "short"}}],
                exploration_rate=0,
            )
            selection = optimizer.select("prompt")
            result = optimizer.reward(
                selection["id"],
                success=1,
                satisfaction=1,
                latency_ms=500,
                latency_budget_ms=1000,
                resource_cost=0.5,
            )

        self.assertEqual(result["reward"], 0.55)

    def test_best_arm_is_nominated_without_bypassing_release_gates(self):
        from memoryos.memory_store import MemoryStore
        from policy_optimizer import PolicyOptimizer

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.set_runtime_policy("prompt", "research", {"prompt": "baseline"})
            optimizer = PolicyOptimizer(store)
            optimizer.register_group(
                "research",
                [
                    {"name": "fast", "arm_type": "prompt", "payload": {"prompt": "fast"}},
                    {"name": "deep", "arm_type": "prompt", "payload": {"prompt": "deep"}},
                ],
                exploration_rate=0,
            )
            for _ in range(200):
                selected = optimizer.select("research")
                success = 1.0 if selected["arm_name"] == "deep" else 0.2
                optimizer.reward(selected["id"], success=success, satisfaction=success)
                stats = optimizer.stats("research")
                if min(int(arm["pull_count"]) for arm in stats["arms"]) >= 30:
                    break
            promotion = optimizer.promote(
                "research", "prompt", "research", min_pulls=30
            )
            active = store.get_runtime_policy("prompt", "research")

        self.assertEqual(active["payload"], {"prompt": "baseline"})
        self.assertEqual(promotion["candidate_payload"], {"prompt": "deep"})
        self.assertEqual(promotion["status"], "candidate")
        self.assertEqual(promotion["baseline_policy_version"], active["version"])


if __name__ == "__main__":
    unittest.main()
