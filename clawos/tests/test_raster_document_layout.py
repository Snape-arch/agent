import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from PIL import Image, ImageDraw

from memoryos.document_ingestion import ingest_file
from memoryos.memory_store import MemoryStore
from services.document_semantic_graph_service import DocumentSemanticGraphService
from services.raster_document_layout import RasterDocumentLayout
from services.scanned_table_benchmark import MANIFEST, score_graphs


class RasterLayoutTests(unittest.TestCase):
    def image(self, grid=False, merged=False):
        image = Image.new("RGB",(600,500),"white")
        draw = ImageDraw.Draw(image)
        for y in ([40,70,120,170,220] if grid else [40,70,220]):
            draw.line((40,y,560,y),fill="black",width=2)
        for x in [40,200,360,560]:
            draw.line((x,40 if not merged or x!=360 else 70,x,220 if grid else 70),fill="black",width=2)
        for y in [52,88,138,188]:
            for x in [55,215,375]:
                draw.rectangle((x,y,x+40,y+12),fill="black")
        return image

    def test_header_grid_and_fully_ruled_table_boundaries(self):
        for grid in (False,True):
            regions = RasterDocumentLayout().detect(self.image(grid),1)
            self.assertEqual(len(regions),1)
            self.assertEqual(len(regions[0]["pixel_columns"]),4)
            self.assertAlmostEqual(regions[0]["bbox"][3],222,delta=2)
            if grid:
                self.assertEqual(len(regions[0]["pixel_row_rules"]),4)
            else:
                self.assertEqual(len(regions[0]["body_bands"]),3)

    def test_prose_frame_borderless_and_merged_header_fail_closed(self):
        for kind in ("prose","frame","borderless"):
            image = Image.new("RGB",(600,500),"white")
            draw = ImageDraw.Draw(image)
            for y in range(50,220,25):
                draw.rectangle((70,y,500,y+10),fill="black")
            if kind=="frame":
                draw.rectangle((40,40,560,240),outline="black",width=2)
            self.assertEqual(RasterDocumentLayout().detect(image,1),[])
        self.assertEqual(RasterDocumentLayout().detect(self.image(True,True),1),[])

    def test_column_calls_preserve_grid_cells_word_positions_and_numeric_review(self):
        count = 0
        def recognize(crop):
            nonlocal count
            count += 1
            return {"status":"completed","words":[{"text":text,"bbox":[12,y,52,y+10],"confidence":.99,
                    "block_num":1,"paragraph_num":1,"line_num":i,"word_num":1}
                    for i,(text,y) in enumerate([(f"Header{count}",10),("Alpha",46),("95%",96),("Gamma",146)],1)]}
        for grid in (False,True):
            count = 0
            tables, _ = RasterDocumentLayout().recover(self.image(grid),1,recognize)
            self.assertEqual(count,3,"One OCR call per column, not per cell")
            self.assertEqual(len(tables),1)
            self.assertEqual(len(tables[0]["rows"]),4)
            cell = next(c for c in tables[0]["cells"] if c["row"]==2 and c["column"]==0)
            self.assertEqual(cell["text"],"95%")
            self.assertTrue(cell["review_required"])
            self.assertTrue(cell["numeric_verification_required"])
            self.assertGreater(cell["words"][0]["bbox"][1],120)

    def test_failed_region_is_not_published_as_table(self):
        tables,regions = RasterDocumentLayout().recover(self.image(),1,lambda _: {"status":"failed","words":[]})
        self.assertFalse(tables)
        self.assertEqual(regions[0]["structure_status"],"recognition_incomplete")

    def test_missing_tables_keep_all_label_denominators(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        report = score_graphs({},manifest)
        self.assertEqual(report["metrics"]["cell_text_exact"]["n"],60)
        self.assertEqual(report["metrics"]["critical_exact"]["n"],5)
        self.assertEqual(report["metrics"]["regions"]["successes"],0)
        self.assertFalse(report["acceptance"]["passed"])

    def test_graph_and_ingestion_keep_conditions_review_and_word_cell_links(self):
        table = {"id":"ocr_table:p1:1","type":"table","page":1,"bbox":[40,40,560,220],"rows":[["Condition","Score"],["Blinded","95%"]],
                 "headers":["Condition","Score"],"row_groups":[],"header_rows":1,"representation":"raster_header_grid","locator":"page=1&ocr_table=1","cells":[]}
        for r,row in enumerate(table["rows"]):
            for c,text in enumerate(row):
                table["cells"].append({"id":f"{table['id']}:r{r}c{c}","row":r,"column":c,"text":text,
                                      "column_header":table["headers"][c],"header_refs":[f"{table['id']}:r0c{c}"] if r else [],
                                      "bbox":[40+c*200,40+r*50,240+c*200,90+r*50],"confidence":.99,"review_required":bool(r),"word_indices":[1]})
        ocr = {"page":1,"required":True,"status":"completed","review_required":True,"tables":[table],
               "words":[{"text":"95%","bbox":[250,100,270,110],"confidence":.99}],"lines":[{"text":"95%","bbox":[250,100,270,110],"confidence":.99,"word_indices":[1]}]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/"scan.pdf"
            with fitz.open() as pdf:
                pdf.new_page(width=600,height=500)
                pdf.save(source)
            with patch.object(DocumentSemanticGraphService,"_ocr_pdf_page",return_value=ocr):
                graph = DocumentSemanticGraphService().parse_pdf(source)
                store = MemoryStore(str(root/"test.db"))
                result = ingest_file(store,root/"uploads",source)
            units = graph["evidence_units"]
            self.assertEqual(len(units),1)
            self.assertIn("Condition = Blinded",units[0]["text"])
            self.assertIn("Score = 95%",units[0]["text"])
            self.assertTrue(units[0]["review_required"])
            self.assertTrue(any(e["type"]=="word_in_cell" for e in graph["relations"]))
            self.assertEqual(result["knowledge_ids"],[])
            self.assertEqual(store.get_document_chunks(result["id"],10), [])
            self.assertEqual(store.get_document_chunks(result["id"],10,include_review=True)[0]["metadata"]["evidence_types"],["table_row"])


if __name__ == "__main__":
    unittest.main()
