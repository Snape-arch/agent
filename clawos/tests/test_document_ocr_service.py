import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from memoryos.document_ingestion import extract_pdf_text_enhanced, ingest_file
from memoryos.memory_store import MemoryStore
from services.document_ocr_benchmark import characters, edit_distance, score
from services.document_ocr_service import DocumentOCRService
from services.knowledge_service import KnowledgeService
from services.document_semantic_graph_service import DocumentSemanticGraphService

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


def tsv(text="实验", confidence=92, left=20, level=5, number=1, line=1):
    return f"{level}\t1\t1\t1\t{line}\t{number}\t{left}\t40\t20\t10\t{confidence}\t{text}\n"


class DocumentOCRTests(unittest.TestCase):
    def test_mixed_pdf_header_does_not_hide_scanned_body(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "mixed.pdf"
            with fitz.open() as raster:
                page = raster.new_page(width=300, height=300)
                page.insert_text((20, 60), "Scanned lesson body with evidence")
                png = page.get_pixmap().tobytes("png")
            with fitz.open() as pdf:
                page = pdf.new_page(width=400, height=500)
                header = "Native header longer than twenty characters"
                page.insert_text((20, 30), header)
                header_box = list(page.get_text("blocks")[0][:4])
                page.insert_image(fitz.Rect(20, 100, 380, 460), stream=png)
                pdf.save(source)
            words = [{"text": header, "bbox": header_box, "confidence": .99},
                     {"text": "Scanned lesson body with evidence", "bbox": [44, 150, 310, 170], "confidence": .99}]
            result = {"page": 1, "status": "completed", "required": True, "words": words,
                      "lines": [{**word, "word_indices": [i]} for i, word in enumerate(words, 1)],
                      "tables": [], "reading_text": header + "\nScanned lesson body with evidence"}
            with patch.object(DocumentSemanticGraphService, "_ocr_pdf_page", return_value=result) as recognize:
                graph = DocumentSemanticGraphService().parse(source)
            recognize.assert_called_once()
            self.assertEqual(graph["ocr_pages"][0]["trigger"], "uncovered_raster_region")
            self.assertEqual(graph["plain_text"].count(header), 1)
            self.assertIn("Scanned lesson body", graph["plain_text"])
            ordered = graph["pages"][0]["reading_order"]
            self.assertTrue(ordered[0].startswith(("paragraph:", "heading:")))
            with patch.object(DocumentSemanticGraphService, "_ocr_pdf_page", return_value={"page": 1, "status": "engine_unavailable", "words": []}):
                text, metadata = extract_pdf_text_enhanced(source)
            self.assertTrue(metadata["ocr_required"])
            self.assertIn(header, text)

    def test_native_body_and_small_logo_do_not_force_ocr(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "native.pdf"
            with fitz.open() as pdf:
                page = pdf.new_page(width=400, height=500)
                page.insert_text((20, 80), "Native lesson body contains enough searchable text.")
                pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
                pix.clear_with(255)
                page.insert_image(fitz.Rect(20, 10, 40, 30), pixmap=pix)
                pdf.save(source)
            with patch.object(DocumentSemanticGraphService, "_ocr_pdf_page") as recognize:
                graph = DocumentSemanticGraphService().parse(source)
            recognize.assert_not_called()
            self.assertFalse(graph["ocr_pages"])

    def test_tsv_rejects_malformed_confidence_geometry_and_nonwords(self):
        rows = HEADER + tsv() + tsv(confidence=-1) + tsv(confidence=101) + tsv(left="nan") + tsv(left=-1) + tsv(level=4)
        words = DocumentOCRService.parse_tsv(rows, .5)
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["bbox"], [10, 20, 20, 25])
        with self.assertRaises(ValueError):
            DocumentOCRService.parse_tsv(rows, float("nan"))

    def test_lines_preserve_latin_spaces_and_cjk_word_links(self):
        words = DocumentOCRService.parse_tsv(HEADER + tsv() + tsv("条件", number=2) + tsv("Deep", number=3) + tsv("Learning", number=4))
        line = DocumentOCRService.lines(words)[0]
        self.assertEqual(line["text"], "实验条件 Deep Learning")
        self.assertEqual(line["word_indices"], [1, 2, 3, 4])
        self.assertFalse(line["review_required"])

    def test_low_confidence_number_requires_review_even_high_mean(self):
        words = DocumentOCRService.parse_tsv(HEADER + tsv("Experimentalcondition", confidence=99) + tsv("200", confidence=20, number=2))
        line = DocumentOCRService.lines(words)[0]
        self.assertGreater(line["confidence"], .75)
        self.assertTrue(line["review_required"])

    def test_column_gap_is_preserved_and_not_promoted_as_confident_prose(self):
        words = DocumentOCRService.parse_tsv(HEADER + tsv("条件") + tsv("结果", left=100, number=2))
        line = DocumentOCRService.lines(words)[0]
        self.assertEqual(line["text"], "条件 | 结果")
        self.assertTrue(line["layout_ambiguous"])
        self.assertTrue(line["review_required"])

    def test_requested_missing_language_never_silently_falls_back(self):
        service = DocumentOCRService(language="chi_sim+eng")
        service.executable = "tesseract"
        with patch("services.document_ocr_service.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "List of available languages (1):\neng\n", "")):
            result = service.recognize(Path("unused.pdf"), 1)
        self.assertEqual(result["status"], "language_unavailable")
        self.assertEqual(result["missing_languages"], ["chi_sim"])
        self.assertFalse(result["words"])

    def test_engine_absence_and_empty_success_are_not_completed(self):
        service = DocumentOCRService()
        service.executable = ""
        self.assertEqual(service.capability()["status"], "engine_unavailable")
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "blank.pdf"
            with fitz.open() as pdf:
                pdf.new_page(width=200, height=300)
                pdf.save(source)
            with patch.object(service, "capability", return_value={"status": "ready", "language": "eng"}), patch("services.document_ocr_service.subprocess.run", return_value=subprocess.CompletedProcess([], 0, HEADER, "")):
                self.assertEqual(service.recognize(source, 1)["status"], "empty")

    def test_rotation_maps_word_boxes_back_to_unrotated_points(self):
        service = DocumentOCRService()
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "rotated.pdf"
            with fitz.open() as pdf:
                page = pdf.new_page(width=200, height=300)
                page.set_rotation(90)
                pdf.save(source)
            with patch.object(service, "capability", return_value={"status": "ready", "language": "eng"}), patch("services.document_ocr_service.subprocess.run", return_value=subprocess.CompletedProcess([], 0, HEADER + tsv("word"), "")):
                result = service.recognize(source, 1)
            expected = fitz.Rect([20/3, 40/3, 40/3, 50/3]) * fitz.Matrix(0, -1, 1, 0, 0, 300)
            self.assertEqual(result["words"][0]["bbox"], [round(x, 2) for x in expected])

    def test_graph_and_ingestion_preserve_line_evidence_without_word_duplication(self):
        words = DocumentOCRService.parse_tsv(HEADER + tsv("实验") + tsv("条件", number=2))
        ocr = {"page": 1, "required": True, "status": "completed", "words": words, "lines": DocumentOCRService.lines(words), "language": "chi_sim"}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "scan.pdf"
            with fitz.open() as pdf:
                pdf.new_page()
                pdf.save(source)
            with patch.object(DocumentOCRService, "recognize", return_value=ocr):
                graph = DocumentSemanticGraphService().parse_pdf(source)
                text, metadata = extract_pdf_text_enhanced(source)
                store = MemoryStore(str(root / "test.db"))
                stored = ingest_file(store, root / "uploads", source)
            self.assertEqual(graph["plain_text"], "实验条件")
            self.assertEqual(len(graph["evidence_units"]), 1)
            self.assertEqual(len([r for r in graph["relations"] if r["type"] == "word_of"]), 2)
            self.assertFalse(metadata["ocr_required"])
            self.assertEqual(stored["status"], "ready")
            chunks = store.get_document_chunks(stored["id"], 10)
            self.assertEqual(chunks[0]["metadata"]["evidence_types"], ["ocr_line"])
            self.assertEqual(chunks[0]["metadata"]["recognition_confidence_min"], .92)

    def test_failed_page_survives_extraction_and_partial_document_not_ready(self):
        failure = {"page": 2, "required": True, "status": "language_unavailable", "words": [], "lines": []}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "partial.pdf"
            with fitz.open() as pdf:
                pdf.new_page().insert_text((30, 40), "Native page with enough readable source text.")
                pdf.new_page()
                pdf.save(source)
            with patch.object(DocumentOCRService, "recognize", return_value=failure):
                _, metadata = extract_pdf_text_enhanced(source)
                stored = ingest_file(MemoryStore(str(root / "test.db")), root / "uploads", source)
            self.assertEqual(metadata["ocr_pages"], [2])
            self.assertEqual(metadata["semantic_graph"]["ocr_pages"][0]["status"], "language_unavailable")
            self.assertEqual(stored["status"], "needs_ocr")
            self.assertGreater(stored["chunk_count"], 0)

    def test_uncertain_ocr_is_stored_for_review_not_promoted_to_knowledge(self):
        words = DocumentOCRService.parse_tsv(HEADER + tsv("Sample count 200", confidence=20))
        ocr = {"page": 1, "required": True, "status": "completed", "review_required": True, "words": words, "lines": DocumentOCRService.lines(words)}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "uncertain.pdf"
            with fitz.open() as pdf:
                pdf.new_page()
                pdf.save(source)
            with patch.object(DocumentOCRService, "recognize", return_value=ocr):
                result = ingest_file(MemoryStore(str(root / "test.db")), root / "uploads", source)
            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(result["chunk_count"], 1)
            self.assertEqual(result["knowledge_ids"], [])

    def test_scoring_detects_chinese_loss_reordering_and_wrong_coordinates(self):
        self.assertEqual(characters("实验 200"), "实验200")
        self.assertEqual(edit_distance("甲乙丙", "丙乙甲"), 2)
        words = [{"text": "实验", "bbox": [80, 80, 100, 100]}]
        result = score("实验200", "200", [[0, 0, 20, 20, "实验"]], words, [0, 0, 100, 100])
        self.assertEqual(result["cjk_recall"], 0)
        self.assertEqual(result["coordinate_validity"], 1)
        self.assertEqual(result["text_position_hit_rate"], 0)

    def test_position_scoring_excludes_punctuation_from_text_denominator_only(self):
        words = [{"text": "实验", "bbox": [0, 0, 20, 20]}, {"text": "。", "bbox": [20, 0, 22, 20]}]
        result = score("实验。", "实验。", [[0, 0, 20, 20, "实验"]], words, [0, 0, 100, 100])
        self.assertEqual(result["position_evaluated_words"], 1)
        self.assertEqual(result["ocr_words"], 2)
        self.assertEqual(result["text_position_hit_rate"], 1)

    def test_console_ocr_entry_uses_graph_and_withholds_uncertain_citation_draft(self):
        words = DocumentOCRService.parse_tsv(HEADER + tsv("实验条件200", confidence=20))
        ocr = {"page": 1, "required": True, "status": "completed", "review_required": True, "words": words, "lines": DocumentOCRService.lines(words)}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "scan.pdf"
            with fitz.open() as pdf:
                pdf.new_page()
                pdf.save(source)
            store = MemoryStore(str(root / "test.db"))
            document = store.add_document("Source", filename=source.name, file_path=str(source), file_hash="scan-id", status="needs_ocr", metadata={"ocr_required": True})
            service = KnowledgeService(store, root / "uploads")
            with patch.object(DocumentOCRService, "recognize", return_value=ocr), patch.object(service, "_load_ocr_text", side_effect=AssertionError("old text-only route must not run")):
                result = service.run_ocr(document["id"])
            self.assertEqual(result["status"], "needs_review")
            self.assertFalse(result["ok"])
            self.assertEqual(result["document"]["knowledge_ids"], [])
            self.assertEqual(store.get_document_chunks(document["id"], 10), [])
            chunks = store.get_document_chunks(document["id"], 10, include_review=True)
            self.assertIn("#page=1", chunks[0]["citation"])
            self.assertEqual(chunks[0]["metadata"]["evidence_types"], ["ocr_line"])
            self.assertEqual(service.citation_answer(document_id=document["id"])["count"], 0)
            self.assertEqual(service.list_ocr_queue()[0]["ocr_pages"], [1])
            with self.assertRaisesRegex(ValueError, "cannot bypass"):
                service.run_ocr(document["id"], sidecar_text="Corrected experiment count is 200.")


if __name__ == "__main__":
    unittest.main()
