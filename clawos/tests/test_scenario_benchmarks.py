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
        self.assertGreaterEqual(len(suite["cases"]), 20)
        self.assertTrue({"meeting", "research", "learning", "git", "template"}.issubset(scenarios))
        self.assertEqual(suite["thresholds"]["min_pass_rate"], 1.0)

    def test_default_suite_is_frozen_and_runs_with_evidence(self):
        from memoryos.memory_store import MemoryStore
        from scenario_benchmarks import FrozenScenarioBenchmark

        with tempfile.TemporaryDirectory() as td:
            benchmark = FrozenScenarioBenchmark(MemoryStore(str(Path(td) / "memory.db")))
            suites = benchmark.list_suites()

            def runner(tool, args):
                result = {
                    "ok": True,
                    "status": "success",
                    "tool": tool,
                    "arguments": args,
                    "data": {
                        "meeting": {
                            "id": 1,
                            "title": "Frozen benchmark weekly sync",
                            "agenda": [],
                            "audio_path": "fixture.wav",
                            "transcript_status": "transcript_imported",
                            "diarization": [],
                        },
                        "audio_path": "fixture.wav",
                        "transcript_status": "transcript_imported",
                        "diarization": [],
                        "results": [],
                        "count": 0,
                        "valid": True,
                        "terms": ["memory", "reflection"],
                        "matrix": [],
                        "id": 1,
                        "manifest": {
                            "title": "Frozen reproducible experiment NASA Apollo 11 Evidence Pack",
                            "artifacts": ["README.md", "experiment_plan.json"],
                            "steps": ["Apollo 11", "nasa.gov"],
                        },
                        "output_path": "out",
                        "learning": {"id": 1, "items": [], "title": "Frozen benchmark learning goal"},
                        "git": {
                            "id": 1,
                            "repo": str(ROOT.parent),
                            "repo_path": str(ROOT.parent),
                            "branch": "test",
                            "status": "pending",
                            "recent_commits": [],
                            "commands": [],
                            "dry_run": True,
                            "requires_confirmation": True,
                            "checkpoint_ref": "HEAD",
                            "message": "Frozen benchmark dry run",
                        },
                        "templates": [],
                        "project": "demo",
                        "type": "python",
                        "path": "demo",
                        "created": ["README.md", ".gitignore"],
                        "tools": [{"name": "time_now"}, {"name": "memory_stats"}],
                        "skills": [],
                        "profiles": 0,
                        "preferences": 0,
                        "memories": 0,
                        "reflection_cards": 0,
                        "characters": 10,
                        "words": 2,
                        "language": "en",
                        "expression": "21 * 2 + 8",
                        "result": 50,
                        "total_files": 1,
                        "total_lines": 1,
                        "by_language": {"Python": {"files": 1, "lines": 1}},
                        "todos": [],
                        "artifact": {
                            "id": 1,
                            "title": "UCI Iris Sample Project Gutenberg Alice Metadata",
                            "file_path": "artifact",
                            "artifact_type": "spreadsheet presentation",
                        },
                    },
                    "duration_ms": 10,
                }
                result["data"]["meeting"]["meeting"] = {"id": 1}
                result["data"]["learning"].update({
                    "goal": {},
                    "nodes": [],
                    "edges": [],
                    "goal_id": 1,
                    "mastery": 0.5,
                    "evidence_count": 1,
                    "correct_answer": "A frozen regression check plus evidence.",
                    "evidence": "MemoryOS and Reflection release gate requires frozen regression evidence.",
                    "mistake_count": 1,
                })
                result["data"]["template"] = "python-service research-project"
                result["data"]["target_path"] = "target"
                result["data"]["created_files"] = ["README.md", "references/README.md"]
                return result

            run = benchmark.run_suite(suites[0]["id"], runner)
            runs = benchmark.list_runs()

        self.assertTrue(suites[0]["frozen"])
        self.assertGreaterEqual(len(suites[0]["cases"]), 20)
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
        self.assertIn("passed_count=30", result.stdout)
        self.assertIn("failed_count=0", result.stdout)
        self.assertIn("meeting::meeting_create_structured_record", result.stdout)
        self.assertIn("cases=30/30", result.stdout)

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
