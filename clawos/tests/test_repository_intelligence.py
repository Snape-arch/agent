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
            "imports", "calls", "tests", "covers", "inherits_config",
            "builds", "configured_by",
        } <= types)

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
            self.assertIn("tests/test_core.py", impact["tests"])
            context = service.task_slice(
                first, "fix add behavior", focus_paths=["src/core.py"], max_files=5
            )
            self.assertIn("src/core.py", context["selected_files"])
            self.assertIn("src/api.py", context["selected_files"])
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


if __name__ == "__main__":
    unittest.main()
