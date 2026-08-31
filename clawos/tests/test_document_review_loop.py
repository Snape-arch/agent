import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import fitz

from memoryos.memory_store import MemoryStore
from services.document_review_service import DocumentReviewService
from services.document_semantic_graph_service import DocumentSemanticGraphService
from services.knowledge_service import KnowledgeService
from services.office_productivity_service import OfficeProductivityService
from services.paper_intelligence_service import PaperIntelligenceService
from services.knowledge_core_service import KnowledgeCoreService


class ReviewLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "scan.pdf"
        with fitz.open() as pdf:
            page = pdf.new_page(width=400, height=200)
            page.insert_text((30,50), "Score 95%+")
            pdf.save(self.source)
        self.store = MemoryStore(str(self.root / "test.db"))
        self.service = DocumentReviewService(self.store, [self.root])
        table = {"id":"ocr_table:p1:1","type":"table","page":1,"bbox":[20,20,350,150],
                 "rows":[["Condition","Score"],["not blinded","959%+"],["blinded","7信"]],
                 "headers":["Condition","Score"],"header_rows":1,"row_groups":[],
                 "locator":"page=1&ocr_table=1","representation":"raster_header_grid","cells":[]}
        for r, row in enumerate(table["rows"]):
            for c, text in enumerate(row):
                table["cells"].append({"id":f"{table['id']}:r{r}c{c}","row":r,"column":c,"text":text,"value_text":text,
                                      "original_text":text,"page":1,"bbox":[20+c*150,20+r*40,170+c*150,60+r*40],
                                      "column_header":table["headers"][c],"confidence":.99,"review_required":True,
                                      "header_refs":[f"{table['id']}:r0c{c}"] if r else []})
        nodes, relations = [], []
        DocumentSemanticGraphService._attach_table_structure(nodes, relations, [table])
        graph = {"schema":DocumentSemanticGraphService.SCHEMA,"tables":[table],"nodes":nodes,"relations":relations,"pages":[],
                 "evidence_units":DocumentSemanticGraphService._evidence_units(nodes)}
        self.doc = self.store.add_document("Scan",filename="scan.pdf",file_path=str(self.source),
            file_hash=hashlib.sha256(self.source.read_bytes()).hexdigest(),status="needs_review",
            metadata={"semantic_graph":graph,"structure":{"tables":[table]},"ocr_review_pages":[1]})
        for i, chunk in enumerate(DocumentSemanticGraphService().semantic_chunks(graph), 1):
            self.store.add_document_chunk(self.doc["id"],i,chunk.pop("content"),f"doc:{self.doc['id']}#page=1&chunk={i}",metadata=chunk)

    def form(self, index=0):
        queue = self.service.queue(self.doc["id"])
        item = queue["items"][index]
        values = {cell["id"]:cell["text"].replace("959%+","95%+").replace("7信","7倍") for cell in item["cells"]}
        return dict(chunk_id=item["chunk_id"],revision=queue["revision"],values=values,confirmed=True)

    def test_pending_excluded_from_chunks_search_paper_graph_and_export(self):
        self.assertEqual(self.store.get_document_chunks(self.doc["id"]), [])
        self.assertEqual(self.store.search_document_chunks("959"), [])
        self.assertNotIn("959", json.dumps(self.store.get_document(self.doc["id"])))
        self.assertNotIn("959", json.dumps(self.store.list_documents()))
        analysis = PaperIntelligenceService(self.store).analyze_document(self.doc["id"])
        self.assertNotIn("959", json.dumps(analysis))
        self.assertEqual(KnowledgeService(self.store,self.root).citation_answer(document_id=self.doc["id"])["count"],0)
        table = self.doc["metadata"]["semantic_graph"]["tables"][0]
        with self.assertRaisesRegex(ValueError,"review"):
            OfficeProductivityService._expand_semantic_tables([{"table":table}])

    def test_correct_publish_idempotent_and_auditable(self):
        first = self.form()
        self.service.submit(self.doc["id"], **first)
        chunks = self.store.get_document_chunks(self.doc["id"])
        self.assertEqual(len(chunks),1)
        self.assertIn("Score = 95%+",chunks[0]["content"])
        self.assertEqual(self.store.list_knowledge(),[])
        result = self.service.publish(self.doc["id"],confirmed=True)
        self.assertEqual(result["count"],1)
        self.assertEqual(self.service.publish(self.doc["id"],confirmed=True)["knowledge_ids"],result["knowledge_ids"])
        self.service.submit(self.doc["id"], **self.form())
        self.assertEqual(self.store.get_document(self.doc["id"])["status"],"ready")
        safe = json.dumps(self.store.get_document(self.doc["id"]),ensure_ascii=False)
        self.assertNotIn("959",safe)
        self.assertNotIn("7信",safe)
        self.assertIn("7倍",safe)
        queue = self.service.queue(self.doc["id"])
        self.assertEqual(len(queue["history"]),2)
        self.assertIn("959%+",queue["history"][0]["payload"])
        self.assertEqual(self.service.publish(self.doc["id"],confirmed=True)["count"],2)
        self.assertTrue(self.store.search_knowledge_v2("Score"))

    def test_requires_explicit_confirmation_and_all_headers(self):
        payload = self.form(); payload["confirmed"] = "true"
        with self.assertRaises(ValueError): self.service.submit(self.doc["id"],**payload)
        payload["confirmed"] = True
        payload["values"].pop(next(iter(payload["values"])))
        with self.assertRaises(ValueError): self.service.submit(self.doc["id"],**payload)
        self.assertFalse(self.service.queue(self.doc["id"])["history"])

    def test_stale_revision_and_reingestion_do_not_reuse_approval(self):
        stale = self.form(1)
        self.service.submit(self.doc["id"],**self.form(0))
        with self.assertRaisesRegex(ValueError,"Stale"):
            self.service.submit(self.doc["id"],**stale)
        pending = self.form()
        raw = self.store.get_document(self.doc["id"],include_review=True)
        self.store.add_document(raw["title"],file_hash=raw["file_hash"],file_path=raw["file_path"],metadata=self.doc["metadata"],status="needs_review")
        with self.assertRaises(ValueError): self.service.submit(self.doc["id"],**pending)
        self.assertEqual(len(self.service.queue(self.doc["id"])["history"]),1)

    def test_source_changed_and_disallowed_root_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"outside"):
            DocumentReviewService(self.store,[self.root/"other"]).queue(self.doc["id"])
        payload = self.form()
        with self.source.open("ab") as handle: handle.write(b"\n%changed\n")
        with self.assertRaisesRegex(ValueError,"changed"):
            self.service.submit(self.doc["id"],**payload)

    def test_rejection_remains_quarantined_and_can_be_reviewed_later(self):
        self.service.submit(self.doc["id"],action="reject",**self.form())
        self.assertEqual(self.service.queue(self.doc["id"])["items"][0]["state"],"rejected")
        self.assertEqual(self.service.publish(self.doc["id"],confirmed=True)["count"],0)
        self.assertEqual(self.store.get_document_chunks(self.doc["id"]),[])
        self.service.submit(self.doc["id"],**self.form())
        self.assertEqual(len(self.store.get_document_chunks(self.doc["id"])),1)

    def test_all_rejections_settled_without_becoming_usable(self):
        self.service.submit(self.doc["id"],action="reject",**self.form(0))
        result = self.service.submit(self.doc["id"],action="reject",**self.form(1))
        self.assertEqual(result["remaining"],0)
        self.assertEqual(result["withheld"],2)
        self.assertEqual(result["status"],"ready_with_exclusions")
        self.assertEqual(self.store.get_document_chunks(self.doc["id"]),[])

    def test_background_ocr_queue_does_not_overwrite_review(self):
        import clawos_server as server
        service = KnowledgeService(self.store,self.root)
        with patch.object(server,"get_knowledge_service",return_value=service), patch.object(service,"run_ocr",side_effect=AssertionError("review is not an OCR retry")):
            result = server.worker_process_ocr_queue({"id":1},{"force":True})
        self.assertEqual(result["processed"],0)

    def test_shared_confirmed_header_cannot_silently_change(self):
        self.service.submit(self.doc["id"],**self.form())
        payload = self.form()
        header = next(k for k in payload["values"] if ":r0c" in k)
        payload["values"][header] = "other units"
        with self.assertRaisesRegex(ValueError,"Previously"):
            self.service.submit(self.doc["id"],**payload)

    def test_direct_knowledge_writes_and_stale_legacy_rows_are_gated(self):
        source = f"doc:{self.doc['id']}#page=1&chunk=1"
        with self.assertRaisesRegex(ValueError,"review"):
            self.store.add_knowledge("bad","959%",source=source)
        core = KnowledgeCoreService(self.store)
        with self.assertRaisesRegex(ValueError,"review"):
            core.absorb(title="bad",statement="959%",source_ref=source)
        with self.store._conn() as c:
            c.execute("INSERT INTO knowledge(title,content,source) VALUES(?,?,?)",("old","959%",source))
        self.assertEqual(self.store.search_knowledge("959"),[])
        self.assertEqual(self.store.list_knowledge(),[])
        self.assertEqual(self.store.search_all_text("959"),[])
        self.assertFalse(self.store.document_source_usable(source))

    def test_crop_is_real_png(self):
        node_id = self.service.queue(self.doc["id"])["items"][0]["cells"][0]["id"]
        self.assertTrue(self.service.crop(self.doc["id"],node_id).startswith(b"\x89PNG"))

    def test_http_review_crop_confirmation_conflict_and_publish(self):
        import clawos_server as server
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        for route in server.app.routes:
            if "/review" in route.path and "/api/documents/" in route.path:
                app.router.routes.append(route)
        with patch.object(server,"get_document_review_service",return_value=self.service), patch.object(server,"get_knowledge_service",return_value=KnowledgeService(self.store,self.root)), TestClient(app) as client:
            url = f"/api/documents/{self.doc['id']}/review"
            queue = client.get(url).json()
            self.assertEqual(len(queue["items"]),2)
            crop = client.get(queue["items"][0]["cells"][0]["crop_url"])
            self.assertEqual(crop.status_code,200)
            payload = self.form()
            self.assertEqual(client.post(url,json={**payload,"confirmed":False}).status_code,409)
            self.assertEqual(client.post(url,json=payload).status_code,200)
            self.assertEqual(client.post(url,json=payload).status_code,409)
            self.assertEqual(client.post(url+"/publish",json={"confirmed":True}).json()["count"],1)

    def test_approved_values_reach_markdown_cells_not_dictionary_keys(self):
        self.service.submit(self.doc["id"],**self.form())
        self.service.submit(self.doc["id"],**self.form())
        table = self.store.get_document(self.doc["id"])["metadata"]["semantic_graph"]["tables"][0]
        sections = OfficeProductivityService._expand_semantic_tables([{"table":table}])
        text = OfficeProductivityService._sections_markdown("Verified",sections)
        self.assertIn("| Condition | Score |",text)
        self.assertIn("| --- | --- |",text)
        self.assertIn("95%+",text)
        self.assertIn("7倍",text)
        self.assertNotIn("959",text)

    def test_retired_knowledge_and_old_vector_version_cannot_resurface(self):
        source = f"doc:{self.doc['id']}#page=1&chunk=1"
        # Simulate a pre-gate published record, then restore pending evidence.
        with self.store._conn() as c:
            c.execute("UPDATE document_chunks SET metadata=json_set(metadata,'$.review_required',0)")
        old = self.store.add_knowledge("Old OCR","Score 959%+",source=source)
        with self.store._conn() as c:
            c.execute("UPDATE document_chunks SET metadata=json_set(metadata,'$.review_required',1)")
        self.service.submit(self.doc["id"],**self.form())
        self.assertIsNone(self.store.get_knowledge_by_id(old["id"]))
        self.assertFalse(self.store.document_source_usable(source,old["knowledge_v2_id"],1))
        self.assertEqual(self.store.search_knowledge_v2("959"),[])
        self.assertIn("invalidated_knowledge",self.service.queue(self.doc["id"])["history"][0]["payload"])
        from memoryos.services.retrieval import RetrievalService
        class StaleVector:
            def search(self,*args,**kwargs):
                return [{"id":"stale", "text":"Score 959%+", "score":.99,"metadata":{"source":source,"knowledge_id":old["knowledge_v2_id"],"version":1}}]
        retrieval = RetrievalService(self.store, StaleVector())
        self.assertEqual(retrieval.semantic_rerank("959"),[])
        from memoryos.services.vector_store import MemoryVectorStore
        vector = MemoryVectorStore(self.store._db_path,provider="lightweight",embedding_provider="hash")
        with patch.object(vector,"_ensure_loaded"), patch.object(vector,"_sync_outbox"), patch.object(vector._store,"search",return_value=[{
            "id":"stale","text":"959%+","score":.99,"metadata":{"source":source,"type":"knowledge_v2","knowledge_id":old["knowledge_v2_id"],"version":1}}]):
            self.assertEqual(vector.search("959"),[])


if __name__ == "__main__":
    unittest.main()
