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
                "metadata": self._executed_metadata("frozen"),
            },
            "core_e2e": {
                "baseline": {"pass_rate": 1.0, "p95_latency_ms": 80, "passed": True},
                "candidate": {"pass_rate": 1.0, "p95_latency_ms": 80, "passed": True},
                "metadata": self._executed_metadata("core"),
            },
            "retrieval": {
                "baseline": {
                    "recall_at_5": 1.0,
                    "mrr": 0.8,
                    "latency_p95_ms": 100,
                    "passed": True,
                },
                "candidate": retrieval_candidate,
                "metadata": self._executed_metadata("retrieval"),
            },
        }

    @staticmethod
    def _executed_metadata(name):
        return {
            "evidence_type": "executed",
            "baseline_report_digest": f"{name}-baseline",
            "candidate_report_digest": f"{name}-candidate",
            "case_count": 1,
        }

    def test_run_moves_through_shadow_canary_before_activation(self):
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
            shadow = manager.start_shadow(run["id"])
            for sample in range(30):
                for signal in ("user_retry_rate", "cancel_rate", "long_task_failure_rate"):
                    for variant, value in (("control", 0.03), ("candidate", 0.02)):
                        shadow = manager.record_quality_signal(
                            shadow["id"], signal, value,
                            metadata={
                                "task_id": sample + 1,
                                "session_id": f"shadow-{sample}",
                                "repository_id": "repo-a",
                                "variant": variant,
                            },
                            created_by="test",
                        )
            canary = manager.promote_canary(shadow["id"], traffic_percent=10)
            with self.assertRaisesRegex(ValueError, "30 runtime quality"):
                manager.activate(canary["id"])
            for sample in range(30):
                for variant in ("control", "candidate"):
                    manager.record_quality_signal(canary["id"], "quality_score", 0.9,
                        metadata={"task_id": 1000 + sample, "session_id": f"canary-{sample}", "variant": variant})
            published = manager.activate(canary["id"], actor_id="self-evolution")
            active = store.get_runtime_policy("retrieval_params", "default")

        self.assertEqual(run["status"], "candidate")
        self.assertEqual(evaluated["status"], "validated")
        self.assertEqual(evaluated["publish_decision"], "shadow_required")
        self.assertTrue(evaluated["gate_result"]["passed"])
        self.assertEqual(shadow["status"], "shadow")
        self.assertEqual(canary["status"], "canary")
        self.assertEqual(canary["traffic_percent"], 10)
        self.assertEqual(published["status"], "published")
        self.assertEqual(published["release_stage"], "active")
        self.assertEqual(active["payload"], {"top_k": 30, "rerank_top_k": 5})
        self.assertTrue(published["rollback_payload"]["existed"])

    def test_repeated_aggregate_snapshot_does_not_count_as_independent_evidence(self):
        from memoryos.memory_store import MemoryStore
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            manager = SelfEvolutionManager(store)
            run = manager.create_run(
                "prompt_policy", "default", {"prompt": "a"}, {"prompt": "b"},
                benchmarks=self._benchmarks(),
            )
            manager.evaluate(run["id"])
            manager.start_shadow(run["id"])
            for _ in range(40):
                manager.record_quality_signal(
                    run["id"], "user_retry_rate", 0.01,
                    metadata={"source": "same aggregate snapshot"},
                )
            with self.assertRaisesRegex(ValueError, "30 runtime quality"):
                manager.promote_canary(run["id"])

    def test_candidate_generator_covers_low_risk_targets(self):
        from reflection.self_evolution import SelfEvolutionManager

        prompt = SelfEvolutionManager.generate_candidate("prompt", {"system": "Read papers."})
        retrieval = SelfEvolutionManager.generate_candidate("retrieval_params", {"top_k": 10, "rerank_top_k": 3})
        template = SelfEvolutionManager.generate_candidate("report_template", {"version": 1})
        routing = SelfEvolutionManager.generate_candidate("tool_routing_policy", {})

        self.assertIn("quality check", prompt["system"])
        self.assertGreaterEqual(retrieval["top_k"], 30)
        self.assertEqual(template["typography"], "journal")
        self.assertTrue(routing["confirm_high_risk"])

    def _assert_measured_worker_gate(self, run):
        gate=run['gate_result']
        self.assertEqual(gate['missing_benchmarks'],[],gate)
        failed=[c for c in gate['checks'] if not c['passed']]
        # Wall-clock latency can legitimately regress under machine contention.
        # Keep quality/causality checks strict and verify rejection stays closed.
        self.assertTrue(all('latency' in c['metric'] for c in failed),failed)
        self.assertEqual(gate['passed'],not failed)
        self.assertEqual(run['status'],'shadow' if gate['passed'] else 'rejected',gate)
        if gate['passed']:self.assertEqual(run['release_stage'],'shadow')
        else:self.assertEqual(run['publish_decision'],'reject')

    def test_worker_generated_benchmarks_obey_measured_gate(self):
        from memoryos.memory_store import MemoryStore
        from reflection.self_evolution import SelfEvolutionManager

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            manager = SelfEvolutionManager(store)
            run = manager.create_run(
                "retrieval_params",
                "default",
                {"top_k": 10, "rerank_top_k": 3},
                {},
            )
            shadow = manager.run_automatic_benchmarks(run["id"])

        self._assert_measured_worker_gate(shadow)
        self.assertIn("retrieval_benchmark", shadow["benchmarks"])

    def test_api_creation_auto_queues_worker_and_enters_shadow(self):
        import asyncio
        import json
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        class JsonRequest:
            def __init__(self, payload):
                self._payload = payload

            async def json(self):
                return self._payload

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_task_service = server.g_task_service
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            server.g_task_service = None
            try:
                response = asyncio.run(server.api_self_evolution_create_run(JsonRequest({
                    "target_type": "retrieval_params",
                    "target_key": "default",
                    "baseline_payload": {"top_k": 10, "rerank_top_k": 3},
                    "candidate_payload": {},
                    "auto_queue": True,
                })))
                payload = json.loads(response.body.decode("utf-8"))
                worker = asyncio.run(server.api_tasks_worker_tick(JsonRequest({"worker_id": "evo-worker"})))
                run = server.g_memory_store.get_self_evolution_run(payload["run"]["id"])
                queue = server.g_memory_store.list_task_queue()
            finally:
                server.g_memory_store = old_store
                server.g_task_service = old_task_service

        self.assertTrue(payload["queued"])
        self.assertTrue(json.loads(worker.body.decode("utf-8"))["ok"])
        self.assertEqual(queue, [])
        self._assert_measured_worker_gate(run)

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
