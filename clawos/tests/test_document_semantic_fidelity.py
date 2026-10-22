import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from memoryos.memory_store import MemoryStore
from memoryos.document_ingestion import ingest_file
from services.document_semantic_graph_service import DocumentSemanticGraphService
from services.office_productivity_service import OfficeProductivityService
from services.paper_intelligence_service import PaperIntelligenceService


class DocumentSemanticFidelityTests(unittest.TestCase):
    def _image(self, root: Path) -> Path:
        path = root / "chart.png"
        image = Image.new("RGB", (640, 240), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 30, 180, 210), fill="#2f5597")
        draw.rectangle((250, 80, 370, 210), fill="#70ad47")
        draw.rectangle((440, 120, 560, 210), fill="#ed7d31")
        image.save(path)
        return path

    def test_docx_generation_roundtrips_semantic_objects_and_review_links(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chart = self._image(root)
            service = OfficeProductivityService(allowed_roots=[root], preview_root=root / "previews")
            sections = [{
                "heading": "Methods",
                "paragraphs": [
                    "We used a blinded protocol[[FN:protocol]] with 200 participants.",
                    "See Figure [[REF:figure_1]] for the prespecified comparison.",
                ],
                "table": {
                    "rows": [["Cohort", "N", "Accuracy"], ["Control", "100", "0.81"], ["Treatment", "100", "0.91"]],
                    "header_rows": 1,
                    "caption": "Prespecified cohort results",
                    "label": "Table 1",
                    "bookmark": "table_1",
                },
                "formulas": [{"text": "accuracy = supported / total", "label": "1"}],
                "figures": [{"path": str(chart), "caption": "Accuracy by cohort", "label": "Figure 1", "bookmark": "figure_1", "alt_text": "Three-bar accuracy chart"}],
            }, {
                "heading": "References",
                "paragraphs": ["[1] Smith et al. Evidence evaluation. 2025. doi:10.1000/test"],
            }]
            metadata = {
                "footnotes": [{"marker": "[[FN:protocol]]", "text": "Protocol and exclusions were fixed before evaluation."}],
                "comments": [{"target": "200 participants", "text": "Verify enrollment count", "author": "Reviewer"}],
                "revisions": [{"old": "blinded", "new": "double-blinded", "author": "Editor"}],
            }
            result = service.create(root / "semantic-report.docx", title="Semantic Report", sections=sections, metadata=metadata, confirmed=True)
            self.assertEqual(result["quality_gate"], "pass", result)
            self.assertEqual(result["semantic_quality"]["gate"], "pass", result)

            graph = DocumentSemanticGraphService().parse_docx(result["path"])
            self.assertEqual(len(graph["footnotes"]), 1)
            self.assertEqual(len(graph["comments"]), 1)
            self.assertGreaterEqual(len(graph["revisions"]), 2)
            self.assertEqual(graph["formulas"][0]["representation"], "omml")
            self.assertEqual(graph["tables"][0]["header_rows"], 1)
            body_cells = [cell for cell in graph["tables"][0]["cells"] if cell["row"] > 0]
            self.assertTrue(all(cell["header_refs"] for cell in body_cells))
            relation_types = {item["type"] for item in graph["relations"]}
            self.assertTrue({"comments_on", "revises", "footnote_for", "cross_reference", "caption_of"} <= relation_types)
            cross_ref = next(item for item in graph["relations"] if item["type"] == "cross_reference")
            self.assertEqual(cross_ref.get("bookmark"), "figure_1")
            self.assertFalse(str(cross_ref["target"]).startswith("bookmark:"))
            with zipfile.ZipFile(result["path"]) as archive:
                self.assertIn("word/footnotes.xml", archive.namelist())
                self.assertIn("word/comments.xml", archive.namelist())
            store = MemoryStore(str(root / "memory.db"))
            stored = ingest_file(store, root / "uploads", Path(result["path"]), category="research")
            persisted_graph = PaperIntelligenceService(store).semantic_graph(stored["id"], compact=True)
            self.assertEqual(persisted_graph["schema"], DocumentSemanticGraphService.SCHEMA)
            chunks = store.get_document_chunks(stored["id"], 100)
            self.assertTrue(any(item.get("metadata", {}).get("node_ids") for item in chunks))
            self.assertTrue(any(item.get("metadata", {}).get("locators") for item in chunks))

    def test_pdf_generation_preserves_layout_tables_figures_formulas_and_pages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chart = self._image(root)
            service = OfficeProductivityService(allowed_roots=[root])
            sections = [{
                "heading": "1 Methods",
                "paragraphs": ["We evaluated 200 participants under a prespecified blinded protocol."],
                "table": {"rows": [["Method", "N", "Score"], ["A", "100", "0.81"], ["B", "100", "0.91"]], "header_rows": 1, "caption": "Evaluation results", "label": "Table 1"},
                "formulas": [{"text": "score = correct / total", "label": "1"}],
                "figures": [{"path": str(chart), "caption": "Score by method", "label": "Figure 1"}],
            }, {
                "heading": "References", "page_break": True,
                "paragraphs": ["[1] Smith et al. Layout-aware evidence. 2025. doi:10.1000/layout"],
            }]
            result = service.create(root / "semantic-report.pdf", title="Semantic Report", sections=sections, confirmed=True)
            self.assertEqual(result["quality_gate"], "pass", result)
            graph = DocumentSemanticGraphService().parse_pdf(result["path"])
            self.assertGreaterEqual(len(graph["pages"]), 2)
            self.assertTrue(graph["sections"])
            self.assertTrue(graph["tables"])
            self.assertTrue(graph["figures"])
            self.assertTrue(graph["formulas"])
            self.assertTrue(graph["references"])
            self.assertTrue(all(node.get("bbox") for node in graph["nodes"] if node["type"] in {"paragraph", "heading"}))

    def test_reading_order_and_ocr_coordinate_contract(self):
        blocks = [
            {"bbox": [40, 20, 560, 45], "text": "Title"},
            {"bbox": [40, 70, 260, 90], "text": "L1"},
            {"bbox": [40, 100, 260, 120], "text": "L2"},
            {"bbox": [340, 70, 560, 90], "text": "R1"},
            {"bbox": [340, 100, 560, 120], "text": "R2"},
            {"bbox": [40, 150, 560, 175], "text": "Footer section"},
        ]
        ordered, columns = DocumentSemanticGraphService._pdf_reading_order(blocks, 600)
        self.assertEqual(columns, 2)
        self.assertEqual([item["text"] for item in ordered], ["Title", "L1", "L2", "R1", "R2", "Footer section"])
        tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t20\t40\t60\t20\t92\tEvidence"
        words = DocumentSemanticGraphService._parse_tesseract_tsv(tsv, scale=0.5)
        self.assertEqual(words[0]["bbox"], [10.0, 20.0, 40.0, 30.0])
        self.assertEqual(words[0]["confidence"], 0.92)

    def test_claim_alignment_can_require_conditions_and_multiple_pages(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            doc = store.add_document(title="Study", filename="study.pdf", file_hash="hash", category="research", metadata={})
            store.add_document_chunk(doc["id"], 1, "The reranker improved citation accuracy by 20 percent.", f"doc:{doc['id']}#page=4&chunk=1")
            store.add_document_chunk(doc["id"], 2, "The blinded evaluation included 200 claims and three annotators.", f"doc:{doc['id']}#page=2&chunk=1")
            aligned = PaperIntelligenceService(store).align_claims([
                {"claim": "The reranker improved citation accuracy by 20 percent.", "conditions": ["blinded evaluation", "200 claims", "three annotators"]}
            ], [doc["id"]])
            row = aligned["alignments"][0]
            self.assertEqual(row["status"], "supported")
            self.assertGreaterEqual(len({item["page"] for item in row["evidence"]}), 2)
            self.assertEqual(row["condition_coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
