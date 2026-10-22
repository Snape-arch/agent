import json
import tempfile
import unittest
from pathlib import Path

import fitz

from services.pdf_table_structure import RuledTableRecovery, glyph_text
from services.document_semantic_graph_service import DocumentSemanticGraphService
from services.document_table_benchmark import DocumentTableBenchmark, MANIFEST
from services.office_productivity_service import OfficeProductivityService
from memoryos.memory_store import MemoryStore
from memoryos.document_ingestion import ingest_file


class PdfTableStructureTests(unittest.TestCase):
    def test_float_ties_do_not_transpose_ligature_characters(self):
        glyphs = [{"text": "l", "origin_x": 149.606033, "bbox": [149.606033, 0, 150, 10], "size": 10},
                  {"text": "e", "origin_x": 149.606018, "bbox": [149.606018, 0, 154, 10], "size": 10}]
        self.assertEqual(glyph_text(glyphs), "le")

    def _table(self, page, top=80, caption="Table 1 Results", group=False):
        page.insert_text((50, top-10), caption, fontsize=11)
        bottom = top + (95 if group else 75)
        for y in (top, top+20, bottom):
            page.draw_line((50, y), (320, y))
        for x, text in ((55, "Method"), (235, "Score")):
            page.insert_text((x, top+14), text, fontsize=11)
        shift = 20 if group else 0
        if group:
            page.insert_text((180, top+34), "Executor: Model-A", fontsize=11)
        for index, (label, value) in enumerate((("Method-A", "12.3"), ("+ Extension", "18.5"))):
            baseline = top+36+shift+index*20
            page.insert_text((55, baseline), label, fontsize=11)
            page.insert_text((235, baseline), value, fontsize=11)
            page.insert_text((263, baseline+2), "0.4", fontsize=6)
        return {"id": caption, "text": caption, "bbox": [50, top-22, 230, top-7], "page": 1}

    def test_numeric_annotations_and_group_parent_context_are_separate(self):
        with fitz.open() as doc:
            page = doc.new_page()
            caption = self._table(page, group=True)
            tables = RuledTableRecovery().extract(page, [caption])
        self.assertEqual(len(tables), 1)
        cells = {(c["row"], c["column"]): c for c in tables[0]["cells"]}
        self.assertEqual(cells[1, 1]["value_text"], "12.3")
        self.assertEqual(cells[1, 1]["annotations"][0]["text"], "0.4")
        self.assertEqual(cells[2, 1]["row_context"], "Method-A")
        self.assertEqual(cells[2, 1]["group_context"], "Executor: Model-A")
        nodes, relations = [], []
        DocumentSemanticGraphService._attach_table_structure(nodes, relations, tables)
        ids = {n["id"] for n in nodes}
        self.assertTrue(all(c["header_refs"][0] in ids for c in tables[0]["cells"] if c["row"] > 0))
        units = DocumentSemanticGraphService._evidence_units(nodes)
        self.assertEqual(len(units), 2)
        self.assertIn("Executor: Model-A", units[1]["text"])
        self.assertIn("Method-A", units[1]["text"])
        self.assertIn("Score = 18.5", units[1]["text"])

    def test_same_width_tables_are_separate_and_unlabelled_regions_rejected(self):
        with fitz.open() as doc:
            page = doc.new_page()
            captions = [self._table(page), self._table(page, 230, "Table 2 Other results")]
            self.assertEqual(len(RuledTableRecovery().extract(page, captions)), 2)
            self.assertEqual(RuledTableRecovery().extract(page, []), [])

    def test_knowledge_ingestion_and_report_export_preserve_conditions(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "table.pdf"
            with fitz.open() as doc:
                self._table(doc.new_page(), group=True)
                doc.save(source)
            graph = DocumentSemanticGraphService().parse_pdf(source)
            table = next(t for t in graph["tables"] if t.get("representation") == "ruled_region_glyph_grid")
            store = MemoryStore(str(root / "memory.db"))
            record = ingest_file(store, root / "uploads", source, category="research")
            chunks = store.get_document_chunks(record["id"], 100)
            self.assertTrue(any("Executor: Model-A" in c["content"] and "Score = 18.5" in c["content"] and "Method-A" in c["content"] for c in chunks))
            service = OfficeProductivityService(allowed_roots=[root])
            result = service.create(root / "report.json", sections=[{"heading": "Recovered", "table": table}], confirmed=True)
            output = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
            section = output["sections"][0]
            self.assertIn("Executor: Model-A", section["paragraphs"])
            self.assertIn("Source: table.pdf, page 1", section["paragraphs"])
            self.assertFalse(any("page=1&table=" in p for p in section["paragraphs"]))
            self.assertIn("page=1&table=", section["table"]["source_locator"])
            self.assertEqual(section["table"]["rows"][2][0], "Method-A / + Extension")
            self.assertIn("small-type: 0.4", section["table"]["rows"][2][1])

    def test_prose_and_ambiguous_sparse_rows_fail_closed(self):
        with fitz.open() as doc:
            page = doc.new_page()
            for y in (80, 100, 170):
                page.draw_line((50, y), (320, y))
            page.insert_text((55, 94), "Ordinary prose header", fontsize=11)
            page.insert_text((55, 120), "This is not a statistical table.", fontsize=11)
            page.insert_text((55, 140), "Neither are the next two sentences.", fontsize=11)
            caption = {"id": "c", "text": "Table 1", "bbox": [50, 55, 200, 70]}
            self.assertEqual(RuledTableRecovery().extract(page, [caption]), [])

    def test_real_fixed_cells_and_conditions(self):
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        if not all((root / row["path"]).is_file() for row in manifest["documents"]):
            self.skipTest("fixed real PDF corpus is not installed")
        report = DocumentTableBenchmark().evaluate(root)
        self.assertEqual(report["metrics"]["values"]["n"], 239)
        self.assertTrue(report["acceptance"]["passed"], report["tables"])
        self.assertFalse(report["release_claim_allowed"])

    def test_evaluator_rejects_empty_output_instead_of_shrinking_denominator(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        spec = manifest["documents"][0]["tables"][0]
        row = DocumentTableBenchmark.evaluate_table({}, spec)
        self.assertEqual(len(row["checks"]["values"]), 25)
        self.assertFalse(any(row["checks"]["values"]))


if __name__ == "__main__":
    unittest.main()
