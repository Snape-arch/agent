import tempfile
import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SelfEvolutionTests(unittest.TestCase):
    def _benchmarks(self, retrieval_candidate=None):
        retrieval_candidate = retrieval_candidate or {
            "recall_at_5": 1.0,
            "mrr": 0.9,
            "latency_p95_ms": 95,
            "passed": True,
        }
        return {
            "frozen": {
                "baseline": {"pass_rate": 1.0, "p95_latency_ms": 120, "passed": True},
                "candidate": {"pass_rate": 1.0, "p95_latency_ms": 100, "passed": True},
            },
            "core_e2e": {
                "baseline": {"pass_rate": 1.0, "p95_latency_ms": 80, "passed": True},
                "candidate": {"pass_rate": 1.0, "p95_latency_ms": 80, "passed": True},
            },
            "retrieval": {
                "baseline": {
                    "recall_at_5": 1.0,
                    "mrr": 0.8,
                    "latency_p95_ms": 100,
                    "passed": True,
                },
                "candidate": retrieval_candidate,
            },
        }

    def test_run_publishes_only_after_all_regression_gates_pass(self):
        from memoryos.memory_store import MemoryStore
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            store.set_runtime_policy(
                "retrieval_params",
                "default",
                {"top_k": 10, "rerank_top_k": 3},
            )
            manager = SelfEvolutionManager(store)
            run = manager.create_run(
                "retrieval_params",
                "default",
                {"top_k": 10, "rerank_top_k": 3},
                {"top_k": 30, "rerank_top_k": 5},
                benchmarks=self._benchmarks(),
            )
            evaluated = manager.evaluate(run["id"])
            published = manager.publish(run["id"], actor_id="self-evolution")
            active = store.get_runtime_policy("retrieval_params", "default")

        self.assertEqual(run["status"], "candidate")
        self.assertEqual(evaluated["status"], "validated")
        self.assertEqual(evaluated["publish_decision"], "publish")
        self.assertTrue(evaluated["gate_result"]["passed"])
        self.assertEqual(published["status"], "published")
        self.assertEqual(active["payload"], {"top_k": 30, "rerank_top_k": 5})
        self.assertTrue(published["rollback_payload"]["existed"])

    def test_retrieval_regression_blocks_publish(self):
        from memoryos.memory_store import MemoryStore
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            manager = SelfEvolutionManager(store)
            run = manager.create_run(
                "prompt",
                "paper_reader",
                {"system": "baseline"},
                {"system": "candidate"},
                benchmarks=self._benchmarks({
                    "recall_at_5": 0.75,
                    "mrr": 0.7,
                    "latency_p95_ms": 90,
                    "passed": True,
                }),
            )
            rejected = manager.evaluate(run["id"])

            with self.assertRaises(ValueError):
                manager.publish(run["id"])

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["publish_decision"], "reject")
        self.assertFalse(rejected["gate_result"]["passed"])
        failed = [
            item for item in rejected["gate_result"]["checks"]
            if item["benchmark"] == "retrieval_benchmark" and not item["passed"]
        ]
        self.assertTrue(failed)

    def test_missing_required_benchmark_blocks_publish(self):
        from memoryos.memory_store import MemoryStore
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            manager = SelfEvolutionManager(MemoryStore(str(Path(td) / "memory.db")))
            run = manager.create_run(
                "report_template",
                "journal_pdf",
                {"font": "baseline"},
                {"font": "candidate"},
                benchmarks={"frozen": self._benchmarks()["frozen"]},
            )
            rejected = manager.evaluate(run["id"])

        self.assertEqual(rejected["status"], "rejected")
        self.assertIn("core_e2e", rejected["gate_result"]["missing_benchmarks"])
        self.assertIn("retrieval_benchmark", rejected["gate_result"]["missing_benchmarks"])

    def test_code_targets_are_rejected(self):
        from memoryos.memory_store import MemoryStore
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            manager = SelfEvolutionManager(MemoryStore(str(Path(td) / "memory.db")))
            with self.assertRaises(ValueError):
                manager.create_run(
                    "code",
                    "clawos_server.py",
                    {"old": True},
                    {"new": True},
                )


if __name__ == "__main__":
    unittest.main()
