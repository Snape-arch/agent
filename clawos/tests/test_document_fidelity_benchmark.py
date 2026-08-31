import json
import tempfile
import unittest
import zipfile
import subprocess
from unittest.mock import patch
from pathlib import Path
from xml.etree import ElementTree as ET

from services.document_fidelity_benchmark import DEFAULT_MANIFEST, DocumentFidelityBenchmark
from services.document_semantic_graph_service import DocumentSemanticGraphService
from services.office_visual_quality_service import OfficeVisualQualityService
from services.office_cross_application_service import OfficeCrossApplicationService
from office_artifacts import create_docx


class DocumentFidelityBenchmarkTests(unittest.TestCase):
    def test_fixed_real_corpus_has_identity_review_and_enough_labels(self):
        manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual([], DocumentFidelityBenchmark().validate_manifest(manifest))
        self.assertEqual(len(manifest["documents"]), 7)
        self.assertGreaterEqual(sum(len(item["assertions"]) for item in manifest["documents"]), 40)
        self.assertFalse(manifest["maintainer_signoff"])

    def test_pdf_heading_rules_reject_affiliations_and_numeric_chart_rows(self):
        service = DocumentSemanticGraphService()
        self.assertFalse(service._is_heading("Stanford University author@example.com", 14, 10))
        self.assertFalse(service._is_heading("47.9 69.6 33.3 No Memory", 14, 10))
        self.assertTrue(service._is_heading("3.2 Experimental Setup", 10, 10))

    def test_reference_expansion_is_atomic_and_removes_running_header(self):
        references = [
            {"id": "r1", "type": "reference", "text": "[1] First citation with enough text. [2] Second citation with enough text.", "page": 3},
            {"id": "r2", "type": "reference", "text": "Generative Agents UIST '23", "page": 3},
        ]
        nodes = [{"id": "body", "type": "paragraph", "text": "Keep ordinary prose", "page": 3}, *references]
        pages = [{"page": 3, "reading_order": ["body", "r1", "r2"]}]
        expanded = DocumentSemanticGraphService._expand_pdf_references(nodes, pages, references)
        self.assertEqual(len(expanded), 2)
        self.assertEqual([node["type"] for node in nodes], ["paragraph", "reference", "reference", "page_header"])
        self.assertEqual(len(pages[0]["reading_order"]), 4)
        self.assertEqual(pages[0]["reading_order"][0], "body")

    def test_caption_relations_do_not_cross_figure_and_table_types(self):
        service = DocumentSemanticGraphService()
        caption = {"id": "caption", "type": "table_caption", "page": 1, "text": "Table 1 Results", "bbox": [10, 40, 100, 50]}
        figure = {"id": "figure", "type": "figure", "page": 1, "bbox": [10, 10, 100, 30]}
        nodes, figures, tables = [caption, figure], [figure], []
        relations = service._relations(nodes, figures, tables)
        target = next(node for node in nodes if node.get("semantic_only"))
        self.assertEqual(target["type"], "table")
        self.assertEqual(relations[0]["target"], target["id"])
        evaluation = DocumentFidelityBenchmark._relation({"nodes": nodes, "relations": relations}, {
            "source_text": "Table 1", "type": "caption_of", "target_type": "table",
        })
        self.assertFalse(evaluation["correct"], "caption-only inference is not verified table recovery")

    def test_generated_docx_has_fixed_table_geometry_and_word_safe_note_package(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fixture.docx"
            create_docx(path, "Fixture", [{"heading": "Evidence", "paragraphs": ["Body[[FN:x]]"], "table": {
                "rows": [["A", "B"], ["1", "2"]], "column_widths": [2, 4.5], "header_rows": 1,
            }}], {"footnotes": [{"marker": "x", "text": "Note"}]})
            with zipfile.ZipFile(path) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
                content_types = archive.read("[Content_Types].xml").decode("utf-8")
                relationships = archive.read("word/_rels/document.xml.rels").decode("utf-8")
                footnotes = ET.fromstring(archive.read("word/footnotes.xml"))
            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            self.assertEqual(document.find(".//w:tblW", namespace).get(f"{{{namespace['w']}}}w"), "9360")
            self.assertEqual(sum(int(item.get(f"{{{namespace['w']}}}w")) for item in document.findall(".//w:tblGrid/w:gridCol", namespace)), 9360)
            self.assertNotIn("Ignorable", str(document.attrib))
            self.assertIn('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">', content_types)
            self.assertIn('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">', relationships)
            note = footnotes.find("w:footnote[@w:id='1']/w:p", namespace)
            self.assertEqual(len(note.findall("w:r", namespace)), 2)
            self.assertEqual(note.find("w:r/w:rPr/w:vertAlign", namespace).get(f"{{{namespace['w']}}}val"), "superscript")
            self.assertEqual(note.find("w:r/w:t", namespace).get("{http://www.w3.org/XML/1998/namespace}space"), "preserve")
            separator = footnotes.find("w:footnote[@w:id='-1']", namespace)
            self.assertEqual(separator.get(f"{{{namespace['w']}}}type"), "separator")
            missing = OfficeVisualQualityService.rendered_note_checks(path, Path(td) / "missing.pdf")
            self.assertFalse(missing[0]["passed"])

    def test_renderer_timeout_is_reported_as_environment_failure(self):
        def timed_out(*args):
            raise subprocess.TimeoutExpired("office", 1)
        result = OfficeCrossApplicationService._safe_render("word", timed_out)
        self.assertEqual(result["failure_category"], "environment_failure")
        self.assertTrue(result["timed_out"])

    def test_cross_application_returns_failed_report_when_engines_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.docx"
            create_docx(source, "Fixture", [], {})
            service = OfficeCrossApplicationService()
            with patch.object(service, "_safe_render", return_value={"status": "unavailable"}):
                report = service.evaluate(source, root / "renders")
                second = service.evaluate(source, root / "renders")
            self.assertEqual(report["schema"], service.SCHEMA)
            self.assertFalse(report["acceptance"]["passed"])
            self.assertFalse(second["acceptance"]["passed"])
            self.assertEqual(len(list((root / "renders").iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
