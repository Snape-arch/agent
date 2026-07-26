import subprocess
import tempfile
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.coding_workflow_service import CodingWorkflowService


class CodingWorkflowServiceTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (repo / "test_calc.py").write_text("import unittest\nfrom calc import add\nclass T(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
        return repo

    def test_complete_loop_passes_and_checkpoint_can_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            service = CodingWorkflowService(artifact_root=root / "artifacts")
            result = service.execute(
                repo,
                "Fix addition",
                [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a + b"}],
                [["python", "-m", "unittest", "test_calc.py"]],
                confirmed=True,
            )
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["rounds"][0]["review"]["all_tests_passed"])
            self.assertIn("return a + b", (repo / "calc.py").read_text(encoding="utf-8"))
            rolled = service.rollback(repo, result["checkpoint"], confirmed=True)
            self.assertTrue(rolled["rolled_back"])
            self.assertIn("return a - b", (repo / "calc.py").read_text(encoding="utf-8"))

    def test_failed_tests_restore_exact_prechange_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            before = (repo / "calc.py").read_bytes()
            service = CodingWorkflowService(artifact_root=root / "artifacts")
            result = service.execute(
                repo,
                "Bad repair",
                [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return 0"}],
                [["python", "-m", "unittest", "test_calc.py"]],
                confirmed=True,
                max_rounds=1,
            )
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["restored_on_failure"])
            self.assertEqual((repo / "calc.py").read_bytes(), before)

    def test_failure_can_be_repaired_in_bounded_second_round(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            service = CodingWorkflowService(artifact_root=root / "artifacts")
            result = service.execute(
                repo,
                "Repair after failed test",
                [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return 0"}],
                [["python", "-m", "unittest", "test_calc.py"]],
                confirmed=True,
                repair_rounds=[[{"path": "calc.py", "operation": "replace", "old_text": "return 0", "new_text": "return a + b"}]],
                max_rounds=2,
            )
            self.assertEqual(result["status"], "passed")
            self.assertEqual(len(result["rounds"]), 2)

    def test_confirmation_path_and_command_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            service = CodingWorkflowService(artifact_root=root / "artifacts")
            with self.assertRaises(PermissionError):
                service.execute(repo, "x", [{"path": "calc.py", "operation": "replace", "old_text": "a - b", "new_text": "a + b"}], [["python", "-V"]])
            with self.assertRaises(ValueError):
                service.plan(repo, "x", [{"path": "../escape.py", "operation": "create", "content": "x"}], [["python", "-V"]])
            with self.assertRaises(ValueError):
                service.plan(repo, "x", [{"path": "new.py", "operation": "create", "content": "x"}], "python -V; echo unsafe")


if __name__ == "__main__":
    unittest.main()
