import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class WorkspaceServicesTests(unittest.TestCase):
    def _services(self, td):
        from memoryos.memory_store import MemoryStore
        from security.policy import ToolSecurityPolicy
        from workspace_services import WorkspaceServices

        store = MemoryStore(str(Path(td) / "memory.db"))
        return store, WorkspaceServices(store, ToolSecurityPolicy([td]))

    def test_meeting_flow_extracts_decisions_risks_actions_and_memory(self):
        with tempfile.TemporaryDirectory() as td:
            store, services = self._services(td)
            meeting = services.create_meeting(
                "Delivery review",
                "2026-06-15",
                ["Alice", "Bob"],
                ["Release readiness"],
            )
            completed = services.process_meeting_transcript(
                meeting["id"],
                "\n".join([
                    "Decision: Ship the local demo on Friday",
                    "Risk: PDF extraction dependency may be missing",
                    "Action: Alice | Verify MTT deployment | 2026-06-18",
                ]),
            )
            memories = store.search_memories("Ship the local demo")

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["decisions"], ["Ship the local demo on Friday"])
        self.assertEqual(completed["risks"], ["PDF extraction dependency may be missing"])
        self.assertEqual(completed["actions"][0]["owner"], "Alice")
        self.assertTrue(memories)

    def test_research_pdf_import_preserves_page_citations(self):
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            pdf = Path(td) / "paper.pdf"
            doc = canvas.Canvas(str(pdf))
            doc.drawString(72, 720, "MemoryOS improves long-term task continuity.")
            doc.showPage()
            doc.drawString(72, 720, "Policy Optimizer uses contextual bandit rewards.")
            doc.save()

            imported = services.import_research_pdf(pdf, "ClawOS Paper")
            results = services.search_research("contextual bandit")

        self.assertEqual(imported["page_count"], 2)
        self.assertGreaterEqual(imported["chunk_count"], 2)
        self.assertEqual(results[0]["page_number"], 2)
        self.assertIn("p.2", results[0]["citation"])
        self.assertIn("#page=2", results[0]["source_ref"])

    def test_learning_mastery_requires_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            goal = services.create_learning_goal(
                "Master RAG",
                topics=["Hybrid retrieval"],
            )
            item_id = goal["items"][0]["id"]
            with self.assertRaises(ValueError):
                services.record_learning_review(item_id, 1.0, "")
            reviewed = services.record_learning_review(
                item_id,
                0.9,
                "Quiz 2026-06-15: 9/10 correct",
            )

        self.assertGreater(reviewed["mastery"], 0)
        self.assertEqual(reviewed["evidence_count"], 1)
        self.assertGreaterEqual(reviewed["interval_days"], 2)

    def test_git_snapshot_and_commit_plan_are_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            repo = Path(td) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
            (repo / "README.md").write_text("# Demo\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "Initial"], check=True, capture_output=True)
            (repo / "README.md").write_text("# Demo\nChanged\n", encoding="utf-8")

            snapshot = services.git_snapshot(repo)
            plan = services.prepare_commit_plan(repo, "Update README")
            status_after = subprocess.run(
                ["git", "-C", str(repo), "status", "--short"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

        self.assertFalse(snapshot["clean"])
        self.assertTrue(plan["dry_run"])
        self.assertTrue(plan["requires_confirmation"])
        self.assertIn("README.md", status_after)

    def test_template_center_instantiates_atomically_and_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            target = Path(td) / "demo"
            result = services.instantiate_template(
                "python-service",
                target,
                {"project_name": "Industrial Demo"},
            )
            readme = (target / "README.md").read_text(encoding="utf-8")
            services.register_template(
                "unsafe",
                "Unsafe template",
                {"../escape.txt": "bad"},
            )
            with self.assertRaises(ValueError):
                services.instantiate_template("unsafe", Path(td) / "unsafe-target")

        self.assertIn("Industrial Demo", readme)
        self.assertIn("tests/test_main.py", result["created_files"])
        self.assertFalse((Path(td) / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()
