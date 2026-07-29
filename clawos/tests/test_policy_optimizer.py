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

    def test_best_arm_can_be_promoted_and_rolled_back(self):
        from memoryos.memory_store import MemoryStore
        from policy_optimizer import PolicyOptimizer

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.set_runtime_policy("agent_policy", "research", {"agent": "baseline"})
            optimizer = PolicyOptimizer(store)
            optimizer.register_group(
                "research",
                [
                    {"name": "fast", "arm_type": "agent", "payload": {"agent": "fast"}},
                    {"name": "deep", "arm_type": "agent", "payload": {"agent": "deep"}},
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
                "research", "agent_policy", "research", min_pulls=30
            )
            active = store.get_runtime_policy("agent_policy", "research")
            rolled_back = optimizer.rollback(promotion["id"])
            restored = store.get_runtime_policy("agent_policy", "research")

        self.assertEqual(active["payload"], {"agent": "deep"})
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(restored["payload"], {"agent": "baseline"})


if __name__ == "__main__":
    unittest.main()
