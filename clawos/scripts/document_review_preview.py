"""Loopback-only UI QA harness: real review routes, temporary DB, captured OCR.

No production DB, provider, startup job, or external network call is used.
Run only for interactive development; Ctrl+C removes its temporary database.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
import clawos_server as server
from memoryos.memory_store import MemoryStore
from services.document_review_service import DocumentReviewService
from services.document_semantic_graph_service import DocumentSemanticGraphService
from services.knowledge_service import KnowledgeService


def main():
    root = Path(__file__).resolve().parents[1]
    raw = root / "output/review-20260831/raw"
    source = raw / "scan-p1.pdf"
    graph = json.loads((raw/"graph-p1.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="clawos-review-ui-") as td:
        store = MemoryStore(str(Path(td)/"review.db"))
        document = store.add_document("OCR UI development fixture",filename=source.name,file_path=str(source),
                    file_hash=hashlib.sha256(source.read_bytes()).hexdigest(),status="needs_review",
                    metadata={"semantic_graph":graph,"structure":{"tables":graph["tables"]},"ocr_review_pages":[1]})
        for i, chunk in enumerate(DocumentSemanticGraphService().semantic_chunks(graph),1):
            if "959%" in chunk["content"] or "7 信" in chunk["content"]:
                store.add_document_chunk(document["id"],i,chunk.pop("content"),f"doc:{document['id']}#page=1&chunk={i}",metadata=chunk)
        server.get_document_review_service = lambda: DocumentReviewService(store,[raw])
        server.get_knowledge_service = lambda: KnowledgeService(store,Path(td))
        app = FastAPI()
        for route in server.app.routes:
            if "/api/documents/" in route.path and "/review" in route.path:
                app.router.routes.append(route)

        @app.get("/",response_class=HTMLResponse)
        def page():
            return '<!doctype html><html lang="zh"><meta charset="utf-8"><title>复核界面隔离验收</title><style>body{font:15px system-ui;background:#f5f6f8;color:#17212b;padding:24px}button{padding:8px 14px;margin:6px;cursor:pointer}textarea{box-sizing:border-box;font:15px system-ui;padding:8px}dialog::backdrop{background:#0005}label{display:block;margin:12px 0}</style><h1>原图复核 · 隔离验收</h1><p>临时数据库，不写入实际知识库。</p><button onclick="openDocumentReview(1)">对照原图复核</button><script src="/review-ui.js"></script></html>'

        @app.get("/review-ui.js")
        def script():
            text = (root/"static/assets/console.js").read_text(encoding="utf-8")
            function = text[text.index("async function openDocumentReview("):text.index("async function runDocumentOcr(")]
            helpers = 'async function api(url,options){const r=await fetch(url,options);const data=await r.json();if(!r.ok)throw new Error(data.detail);return data;} async function loadOcrQueue(){} async function loadKnowledge(){} async function searchKnowledge(){}'
            return Response(helpers+function,media_type="text/javascript")
        uvicorn.run(app,host="127.0.0.1",port=18896,log_level="warning")


if __name__ == "__main__":
    main()
