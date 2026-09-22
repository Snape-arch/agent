import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.coding_context_service import CodingContextService
from services.repository_intelligence_service import RepositoryIntelligenceService


class RepositoryIntelligenceTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        for directory in ("src", "tests", ".github/workflows", "config"):
            (repo / directory).mkdir(parents=True, exist_ok=True)
        (repo / "README.md").write_text("# Graph sample\n", encoding="utf-8")
        (repo / "src/core.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        (repo / "src/api.py").write_text(
            "from src.core import add\n\ndef handle():\n    return add(2, 3)\n",
            encoding="utf-8",
        )
        (repo / "src/unrelated.py").write_text("def idle():\n    return None\n", encoding="utf-8")
        (repo / "tests/test_core.py").write_text(
            "from src.core import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )
        (repo / "package.json").write_text(json.dumps({
            "scripts": {"test": "pytest"}, "dependencies": {"fastapi": "1.0.0"}
        }), encoding="utf-8")
        (repo / "config/base.json").write_text("{}", encoding="utf-8")
        (repo / "config/child.json").write_text(
            json.dumps({"extends": "./base.json"}), encoding="utf-8"
        )
        (repo / ".github/workflows/ci.yml").write_text(
            "name: ci\non: [push]\njobs: {}\n", encoding="utf-8"
        )
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
        return repo

    def test_builds_layered_tree_sitter_graph_and_relationships(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            graph = RepositoryIntelligenceService(Path(td) / "cache").build(repo)
        self.assertEqual(graph["schema"], "clawos.repository-intelligence.v1")
        self.assertGreaterEqual(graph["metrics"]["tree_sitter_files"], 4)
        self.assertIn(".github/workflows/ci.yml", graph["repo_map"]["ci"])
        self.assertIn("package.json", graph["repo_map"]["build_systems"])
        self.assertIn("fastapi", graph["repo_map"]["dependencies"])
        types = {row["type"] for row in graph["edges"]}
        self.assertTrue({
            "imports", "calls", "may_test", "may_cover", "inherits_config",
        } <= types)
        self.assertNotIn("covers", types)
        self.assertFalse({"builds", "configured_by", "potentially_built_by", "potentially_configured_by"} & types)
        unresolved_scope = [
            row for row in graph["nodes"]
            if row.get("kind") in {"build", "config", "ci"}
            and row.get("scope_verification") == "unresolved"
        ]
        self.assertTrue(unresolved_scope)
        syntax_calls = [row for row in graph["edges"] if row["type"] == "calls"]
        self.assertTrue(syntax_calls)
        self.assertTrue(all(row["evidence_tier"] == "syntax" for row in syntax_calls))
        self.assertTrue(all(row["verification"] == "inferred" for row in syntax_calls))
        cross_file_calls = [row for row in syntax_calls if row.get("resolution") == "unique_repository_name"]
        self.assertTrue(cross_file_calls)
        self.assertTrue(all(row["confidence"] < 0.6 for row in cross_file_calls))
        self.assertEqual(graph["evidence_summary"]["verified_coverage_edges"], 0)

    def test_impact_slice_and_git_incremental_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            cache = root / "cache"
            service = RepositoryIntelligenceService(cache)
            first = service.build(repo)
            second = RepositoryIntelligenceService(cache).build(repo)
            self.assertEqual(second["incremental"]["cache_misses"], 0)
            self.assertEqual(second["incremental"]["cache_hits"], first["metrics"]["files"])
            impact = service.impact_analysis(first, ["src/core.py"])
            self.assertIn("src/api.py", impact["impacted_files"])
            self.assertNotIn("tests/test_core.py", impact["impacted_files"])
            self.assertNotIn("tests/test_core.py", impact["tests"])
            self.assertIn("tests/test_core.py", impact["candidate_tests"])
            self.assertEqual(impact["verified_tests"], [])
            self.assertTrue(impact["coverage_gap"])
            context = service.task_slice(
                first, "fix add behavior", focus_paths=["src/core.py"], max_files=5
            )
            self.assertIn("src/core.py", context["selected_files"])
            self.assertIn("src/api.py", context["selected_files"])
            self.assertNotIn("tests/test_core.py", context["selected_files"])
            self.assertNotIn("src", context["selected_files"])
            (repo / "src/core.py").write_text(
                "def add(a, b):\n    return int(a) + int(b)\n", encoding="utf-8"
            )
            third = RepositoryIntelligenceService(cache).build(repo)
            self.assertEqual(third["incremental"]["changed_files"], ["src/core.py"])
            self.assertEqual(third["incremental"]["cache_misses"], 1)

    def test_coding_context_uses_bounded_graph_slice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            manifest = CodingContextService(root / "context.json").build(
                repo, "fix add", focus_paths=["src/core.py"], token_budget=2400
            )
        self.assertTrue(manifest["repository_intelligence"]["digest"])
        self.assertEqual(manifest["task_context"]["schema"], "clawos.task-context-slice.v1")
        evidence_paths = {row["path"] for row in manifest["code_evidence"]}
        self.assertTrue(evidence_paths <= set(manifest["task_context"]["selected_files"]))
        self.assertIn("src/api.py", manifest["impact_analysis"]["impacted_files"])

    def test_lsp_evidence_is_connected_to_repository_symbols(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            semantic = {"graphs": [{
                "language": "python",
                "nodes": [{
                    "id": "symbol:core:add", "kind": "symbol", "name": "add",
                    "path": "src/core.py", "line": 1,
                }],
                "edges": [], "diagnostics": [],
            }]}
            graph = RepositoryIntelligenceService().build(repo, semantic_graph=semantic)
        types = {row["type"] for row in graph["edges"]}
        self.assertIn("semantic_evidence", types)
        self.assertIn("corroborates", types)

    def test_lsp_calls_are_projected_as_confirmed_repository_edges(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            semantic = {"graphs": [{
                "language": "python",
                "nodes": [
                    {"id": "caller", "kind": "symbol", "name": "handle", "path": "src/api.py", "line": 3},
                    {"id": "callee", "kind": "symbol", "name": "add", "path": "src/core.py", "line": 1},
                ],
                "edges": [
                    {"source": "caller", "target": "callee", "kind": "calls"},
                    {"source": "callee", "target": "caller", "kind": "referenced_at"},
                ],
                "diagnostics": [],
            }]}
            graph = RepositoryIntelligenceService().build(repo, semantic_graph=semantic)
        confirmed = [
            row for row in graph["edges"]
            if row["type"] == "calls" and row["evidence_tier"] == "lsp"
        ]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["verification"], "confirmed")
        self.assertGreaterEqual(confirmed[0]["confidence"], 0.9)
        references = [
            row for row in graph["edges"]
            if row["type"] == "references" and row["evidence_tier"] == "lsp"
        ]
        self.assertEqual(len(references), 1)
        impact = RepositoryIntelligenceService().impact_analysis(graph, ["src/core.py"])
        self.assertIn("src/api.py", impact["confirmed_impacted_files"])

    def test_execution_coverage_is_digest_bound_and_only_verified_source_of_covers(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            core = repo / "src/core.py"
            service = RepositoryIntelligenceService()
            with self.assertRaises(ValueError):
                service.bind_coverage_py_report(
                    repo, {"files": {}}, run_id="invalid",
                    command=["pytest"], tests_passed=True,
                )
            coverage = service.bind_coverage_py_report(
                repo,
                {"meta": {"version": "7.6.0", "show_contexts": True},
                 "files": {"src/core.py": {
                    "executed_lines": [1, 2],
                    "contexts": {"1": ["tests/test_core.py::test_add"]},
                }}},
                run_id="pytest-run-1", command=["pytest", "--cov-context=test"],
                tests_passed=True,
            )
            graph = service.build(repo, execution_coverage=coverage)
            covers = [row for row in graph["edges"] if row["type"] == "covers"]
            self.assertTrue(covers)
            self.assertTrue(all(row["evidence_tier"] == "execution" for row in covers))
            self.assertTrue(all(row["verification"] == "verified" for row in covers))
            impact = service.impact_analysis(graph, ["src/core.py"])
            self.assertEqual(impact["verified_tests"], ["tests/test_core.py"])
            self.assertFalse(impact["coverage_gap"])

            core.write_text("def add(a, b):\n    return int(a) + int(b)\n", encoding="utf-8")
            stale_graph = service.build(repo, execution_coverage=coverage)
            self.assertFalse([row for row in stale_graph["edges"] if row["type"] == "covers"])
            self.assertEqual(stale_graph["execution_coverage"]["rejected_files"], ["src/core.py"])

            failed_run = json.loads(json.dumps(coverage))
            failed_run["tests_passed"] = False
            failed_graph = service.build(repo, execution_coverage=failed_run)
            self.assertEqual(failed_graph["execution_coverage"]["status"], "rejected_contract")
            self.assertFalse([row for row in failed_graph["edges"] if row["type"] == "covers"])


if __name__ == "__main__":
    unittest.main()
