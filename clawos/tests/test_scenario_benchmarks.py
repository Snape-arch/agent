import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ScenarioBenchmarkTests(unittest.TestCase):
    def test_file_backed_default_suite_covers_required_scenarios(self):
        from scenario_benchmarks import DEFAULT_SUITE_FILE, load_suite_file

        suite = load_suite_file(DEFAULT_SUITE_FILE)
        scenarios = {case["scenario"] for case in suite["cases"]}

        self.assertEqual(suite["name"], "competition-frozen-v1")
        self.assertGreaterEqual(len(suite["cases"]), 5)
        self.assertTrue({"meeting", "research", "learning", "git", "template"}.issubset(scenarios))
        self.assertEqual(suite["thresholds"]["min_pass_rate"], 1.0)

    def test_default_suite_is_frozen_and_runs_with_evidence(self):
        from memoryos.memory_store import MemoryStore
        from scenario_benchmarks import FrozenScenarioBenchmark

        with tempfile.TemporaryDirectory() as td:
            benchmark = FrozenScenarioBenchmark(MemoryStore(str(Path(td) / "memory.db")))
            suites = benchmark.list_suites()

            def runner(tool, args):
                return {
                    "ok": True,
                    "status": "success",
                    "tool": tool,
                    "arguments": args,
                    "data": {
                        "meeting": {"id": 1, "title": "Frozen benchmark weekly sync", "agenda": []},
                        "results": [],
                        "count": 0,
                        "learning": {"id": 1, "items": [], "title": "Frozen benchmark learning goal"},
                        "git": {"repo": str(ROOT.parent), "branch": "test", "status": [], "recent_commits": []},
                        "templates": [],
                    },
                    "duration_ms": 10,
                }

            run = benchmark.run_suite(suites[0]["id"], runner)
            runs = benchmark.list_runs()

        self.assertTrue(suites[0]["frozen"])
        self.assertGreaterEqual(len(suites[0]["cases"]), 5)
        self.assertTrue(run["passed"])
        self.assertEqual(run["metrics"]["pass_rate"], 1.0)
        self.assertEqual(len(run["case_results"]), len(suites[0]["cases"]))
        self.assertEqual(runs[0]["id"], run["id"])

    def test_benchmark_gate_fails_on_missing_data_path(self):
        from memoryos.memory_store import MemoryStore
        from scenario_benchmarks import FrozenScenarioBenchmark

        with tempfile.TemporaryDirectory() as td:
            benchmark = FrozenScenarioBenchmark(MemoryStore(str(Path(td) / "memory.db")))
            suite = benchmark.create_suite(
                "missing-data-suite",
                [{
                    "name": "shape-case",
                    "scenario": "test",
                    "tool": "shape_tool",
                    "args": {},
                    "expected": {
                        "ok": True,
                        "status": "success",
                        "data_paths": ["payload.id"],
                    },
                }],
            )
            run = benchmark.run_suite(
                suite["id"],
                lambda tool, args: {
                    "ok": True,
                    "status": "success",
                    "tool": tool,
                    "arguments": args,
                    "data": {"payload": {}},
                    "duration_ms": 1,
                },
            )

        self.assertFalse(run["passed"])
        self.assertIn("missing data path: payload.id", run["case_results"][0]["reasons"])

    def test_frozen_runner_script_executes_file_suite(self):
        import subprocess

        script = ROOT / "scripts" / "run_frozen_benchmarks.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Frozen benchmark: passed=True", result.stdout)
        self.assertIn("meeting::meeting_create_structured_record", result.stdout)

    def test_benchmark_gate_fails_on_tool_error(self):
        from memoryos.memory_store import MemoryStore
        from scenario_benchmarks import FrozenScenarioBenchmark

        with tempfile.TemporaryDirectory() as td:
            benchmark = FrozenScenarioBenchmark(MemoryStore(str(Path(td) / "memory.db")))
            suite = benchmark.create_suite(
                "failure-suite",
                [{
                    "name": "bad-case",
                    "scenario": "test",
                    "tool": "bad_tool",
                    "args": {},
                    "expected": {"ok": True, "status": "success"},
                }],
            )
            run = benchmark.run_suite(
                suite["id"],
                lambda _tool, _args: {"ok": False, "status": "error", "duration_ms": 1},
            )

        self.assertFalse(run["passed"])
        self.assertIn("unexpected ok flag", run["case_results"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
