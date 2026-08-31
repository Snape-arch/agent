from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from services.coding_oss_corpus_benchmark import CodingOSSCorpusBenchmark


class OSSCorpusBenchmarkTests(unittest.TestCase):
    def test_manifest_requires_full_revision_and_human_approval(self):
        errors = CodingOSSCorpusBenchmark().validate_manifest({
            "schema": "clawos.coding-oss-corpus.v1",
            "cases": [{"id": "x", "repository": "https://example.test/repo", "revision": "abc"}],
        })
        self.assertTrue(any("40-character" in item for item in errors))
        self.assertTrue(any("human_review" in item for item in errors))

    def test_exact_revision_evaluation_has_intervals_and_loro(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = root / "repo-a"; repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            (repo / "app.py").write_text("print(1)\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=t@example.test", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
            revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            manifest = {"schema": "clawos.coding-oss-corpus.v1", "cases": [{
                "id": "repo-a::undefined", "repository": "https://github.com/example/repo-a",
                "revision": revision, "language": "python", "path": "app.py",
                "label": "implementation_failure", "command": ["python", "app.py"],
                "mutation": {"old_text": "print(1)", "new_text": "print(missing_name)"},
                "repair": {"old_text": "print(missing_name)", "new_text": "print(1)"},
                "human_review": {"status": "approved", "reviewer": "fixture-reviewer", "reviewed_at": "2026-08-12"},
            }]}
            report = CodingOSSCorpusBenchmark().evaluate(root, manifest, bootstrap_samples=250)
        self.assertEqual(report["metrics"]["classification"]["rate"], 1.0)
        self.assertEqual(report["metrics"]["repair"]["rate"], 1.0)
        self.assertEqual(len(report["metrics"]["classification"]["wilson_95"]), 2)
        self.assertEqual(report["metrics"]["leave_one_repository_out"][0]["held_out_cases"], 1)


if __name__ == "__main__": unittest.main()
