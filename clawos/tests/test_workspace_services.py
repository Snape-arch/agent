import subprocess
import sys
import tempfile
import unittest
import zipfile
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

    def test_meeting_audio_sidecar_diarization_and_connector_drafts(self):
        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            audio = Path(td) / "sync.wav"
            audio.write_bytes(b"RIFF....WAVE")
            transcript = Path(td) / "sync.txt"
            transcript.write_text(
                "\n".join([
                    "Alice: Decision: Use local deployment",
                    "Bob: Risk: audio model may be unavailable",
                    "Action: Alice | prepare demo | 2026-06-20",
                ]),
                encoding="utf-8",
            )
            result = services.import_meeting_audio(
                audio, transcript_path=transcript, title="Audio sync"
            )
            meeting = services.get_meeting(result["meeting"]["id"])
            drafts = services.draft_meeting_connectors(
                result["meeting"]["id"],
                Path(td) / "drafts",
                recipients=["team@example.com"],
            )
            draft_exists = any(Path(d["draft_path"]).exists() for d in drafts["drafts"])

        self.assertEqual(result["transcript_status"], "transcript_imported")
        self.assertEqual({turn["speaker"] for turn in result["diarization"]}, {"Alice", "Bob"})
        self.assertIn("Use local deployment", meeting["decisions"])
        self.assertIn("audio model may be unavailable", meeting["risks"])
        self.assertTrue(any(d["connector_type"] == "calendar_ics" for d in drafts["drafts"]))
        self.assertTrue(draft_exists)

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

    def test_research_citation_matrix_and_repro_workflow(self):
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            pdf = Path(td) / "rag.pdf"
            doc = canvas.Canvas(str(pdf))
            doc.drawString(72, 720, "Retrieval augmented generation uses citations.")
            doc.save()
            imported = services.import_research_pdf(pdf, "RAG Paper")
            citation = f"{imported['file_path']}#page=1"
            validation = services.validate_citations([citation, f"{imported['file_path']}#page=9"])
            matrix = services.research_compare_matrix(
                [imported["id"]], ["retrieval", "citations"]
            )
            workflow = services.create_repro_workflow(
                "RAG Reproduction",
                "Can citations improve answer quality?",
                output_path=Path(td) / "repro",
            )
            plan_exists = (Path(workflow["output_path"]) / "experiment_plan.json").exists()

        self.assertFalse(validation["valid"])
        self.assertTrue(validation["results"][0]["valid"])
        self.assertGreater(matrix["matrix"][0]["coverage"]["retrieval"], 0)
        self.assertTrue(plan_exists)

    def test_research_learning_analysis_generates_markdown_and_pdf(self):
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            pdf = Path(td) / "paper.pdf"
            doc = canvas.Canvas(str(pdf))
            doc.drawString(72, 720, "1 Introduction")
            doc.drawString(72, 700, "Retrieval augmented generation solves evidence grounded question answering.")
            doc.showPage()
            doc.drawString(72, 720, "2 Method")
            doc.drawString(72, 700, "The system combines a retriever, a generator, citations, and evaluation metrics.")
            doc.save()
            imported = services.import_research_pdf(pdf, "RAG Study")
            result = services.generate_research_learning_analysis(
                document_id=imported["id"],
                output_dir=Path(td) / "analysis",
                formats=["markdown", "pdf"],
                depth=3,
                question_count=9,
                report_style="business_brief",
            )
            report = result["report"]
            markdown = Path(report["markdown_path"])
            generated_pdf = Path(report["pdf_path"])
            content = markdown.read_text(encoding="utf-8")
            markdown_exists = markdown.exists()
            pdf_exists = generated_pdf.exists()
            pdf_size = generated_pdf.stat().st_size if generated_pdf.exists() else 0
            pdf_blob = generated_pdf.read_bytes() if generated_pdf.exists() else b""
            page_markers = pdf_blob.count(b"/Type /Page")
            title_marker = b"/Title" in pdf_blob

        self.assertEqual(report["question_count"], 9)
        self.assertEqual(report["metadata"]["report_style"], "business_brief")
        self.assertTrue(markdown_exists)
        self.assertTrue(pdf_exists)
        self.assertGreaterEqual(page_markers, 2)
        self.assertTrue(title_marker)
        self.assertGreater(pdf_size, 6000)
        self.assertIn("Paper Intelligence Addendum", content)
        self.assertIn("Method And Evidence Signals", content)
        self.assertIn("Reproducibility Checklist", content)
        self.assertIn("论文深度解析报告", content)
        self.assertIn("L1 自问", content)
        self.assertIn("证据：第", content)

    def test_learning_analysis_pdf_prefers_mixed_cjk_latin_font(self):
        source = Path(__file__).resolve().parents[1] / "workspace_services.py"
        text = source.read_text(encoding="utf-8")

        self.assertLess(text.index("msyh.ttc"), text.index("simhei.ttf"))
        self.assertIn("NotoSansSC-VF.ttf", text)

    def test_office_artifacts_create_and_edit_xlsx_pptx_without_external_packages(self):
        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            xlsx = Path(td) / "report.xlsx"
            xlsx_edited = Path(td) / "report_edited.xlsx"
            pptx = Path(td) / "briefing.pptx"
            pptx_edited = Path(td) / "briefing_edited.pptx"

            spreadsheet = services.create_spreadsheet(
                xlsx,
                sheets=[{"name": "Metrics", "rows": [["Metric", "Value"], ["Pass Rate", 0.95]]}],
                title="Metrics",
            )
            edited_sheet = services.edit_spreadsheet(
                xlsx,
                updates=[{"sheet": "Metrics", "cell": "B2", "value": 0.98}],
                output_path=xlsx_edited,
            )
            deck = services.create_presentation(
                pptx,
                title="Demo Deck",
                slides=[{"title": "Demo Deck", "bullets": ["XLSX and PPTX are built in"]}],
            )
            edited_deck = services.edit_presentation(
                pptx,
                replacements={"Demo Deck": "Customer Demo"},
                output_path=pptx_edited,
            )

            with zipfile.ZipFile(xlsx_edited) as z:
                sheet_xml = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
            with zipfile.ZipFile(pptx_edited) as z:
                slide_xml = z.read("ppt/slides/slide1.xml").decode("utf-8")

        self.assertEqual(spreadsheet["artifact_type"], "spreadsheet")
        self.assertEqual(edited_sheet["action"], "edit")
        self.assertEqual(deck["artifact_type"], "presentation")
        self.assertEqual(edited_deck["action"], "edit")
        self.assertIn("0.98", sheet_xml)
        self.assertIn("Customer Demo", slide_xml)

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

    def test_learning_graph_mistakes_and_long_term_assessment(self):
        with tempfile.TemporaryDirectory() as td:
            _, services = self._services(td)
            goal = services.create_learning_goal("Master agents", topics=["Memory", "Reflection"])
            first, second = goal["items"]
            edge = services.add_learning_dependency(
                goal["id"], "Memory", "Reflection", evidence="Reflection uses memory"
            )
            services.record_learning_review(first["id"], 0.8, "quiz: 8/10")
            mistake = services.record_learning_mistake(
                first["id"],
                "What is MemoryOS?",
                "A prompt only",
                "A governed long-term memory layer",
                "wrong answer notebook row 3",
            )
            graph = services.learning_graph(goal["id"])
            assessment = services.long_term_mastery(goal["id"])

        self.assertEqual(edge["source_topic"], "Memory")
        self.assertEqual(mistake["status"], "open")
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertGreaterEqual(assessment["items"][0]["mistake_count"], 1)

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

    def test_git_change_request_approval_and_revert_rollback(self):
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

            request = services.create_git_change_request(repo, "Update README")
            approved = services.approve_git_change_request(request["id"], "reviewer")
            rolled = services.rollback_git_change_request(request["id"], "reviewer")
            log = subprocess.run(
                ["git", "-C", str(repo), "log", "--oneline", "-3"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

        self.assertEqual(request["status"], "pending_approval")
        self.assertIn("Changed", request["diff_preview"])
        self.assertEqual(approved["status"], "committed")
        self.assertEqual(rolled["status"], "rolled_back")
        self.assertIn("Revert", log)

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
