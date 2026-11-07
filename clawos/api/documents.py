"""Documents HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from typing import Annotated
from fastapi import File
from fastapi.responses import FileResponse
from fastapi import Form
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi import Request
from services.runtime_records import RunRecord
from fastapi import UploadFile
import asyncio
import time


class DocumentsAPI:
    def __init__(self, *,
        get_document_index_worker: Callable[..., Any],
        get_document_review_service: Callable[..., Any],
        get_knowledge_service: Callable[..., Any],
        get_paper_intelligence_service: Callable[..., Any],
        data_dir_provider: Callable[[], Any],
        output_root_provider: Callable[[], Any],
        upload_dir_provider: Callable[[], Any],
        _pdf_page_renderer_provider: Callable[[], Any],
        document_index_worker_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
    ):
        self.get_document_index_worker = get_document_index_worker
        self.get_document_review_service = get_document_review_service
        self.get_knowledge_service = get_knowledge_service
        self.get_paper_intelligence_service = get_paper_intelligence_service
        self.data_dir_provider = data_dir_provider
        self.output_root_provider = output_root_provider
        self.upload_dir_provider = upload_dir_provider
        self._pdf_page_renderer_provider = _pdf_page_renderer_provider
        self.document_index_worker_provider = document_index_worker_provider
        self.memory_store_provider = memory_store_provider
        self.vector_store_provider = vector_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/documents/upload', self.api_document_upload, methods=['POST'])
        self.router.add_api_route('/api/documents/indexing', self.api_document_indexing_status, methods=['GET'])
        self.router.add_api_route('/api/documents/indexing/retry', self.api_document_indexing_retry, methods=['POST'])
        self.router.add_api_route('/api/documents', self.api_documents, methods=['GET'])
        self.router.add_api_route('/api/documents/ocr-queue', self.api_documents_ocr_queue, methods=['GET'])
        self.router.add_api_route('/api/documents/{document_id}/ocr', self.api_document_run_ocr, methods=['POST'])
        self.router.add_api_route('/api/documents/{document_id}/review', self.api_document_review, methods=['GET'])
        self.router.add_api_route('/api/documents/{document_id}/review/crop', self.api_document_review_crop, methods=['GET'])
        self.router.add_api_route('/api/documents/{document_id}/review', self.api_document_review_submit, methods=['POST'])
        self.router.add_api_route('/api/documents/{document_id}/review/publish', self.api_document_review_publish, methods=['POST'])
        self.router.add_api_route('/api/documents/{document_id}/source', self.api_document_source, methods=['GET'])
        self.router.add_api_route('/api/documents/{document_id}/page', self.api_document_page, methods=['GET'])
        self.router.add_api_route('/api/documents/{document_id}/semantic-graph', self.api_document_semantic_graph, methods=['GET'])
        self.router.add_api_route('/api/documents/{document_id}/chunks', self.api_document_chunks, methods=['GET'])
        self.router.add_api_route('/api/documents/search', self.api_document_search, methods=['GET'])
        self.router.add_api_route('/api/documents/citation-answer', self.api_document_citation_answer, methods=['GET'])

    async def api_document_upload(self,
        files: list[UploadFile] = File(...),
        category: str = Form("domain"),
        indexing_mode: Annotated[str, Form()] = "auto",
    ):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        from memoryos.document_ingestion import ingest_file, safe_filename

        if indexing_mode not in {'auto','wait','background'}:
            raise HTTPException(400,'indexing_mode must be auto, wait or background')

        self.upload_dir_provider().mkdir(parents=True, exist_ok=True)
        documents = []
        errors = []
        for file in files[:12]:
            raw = await file.read()
            if not raw:
                errors.append({"filename": file.filename, "error": "empty file"})
                continue
            if len(raw) > 50 * 1024 * 1024:
                errors.append({"filename": file.filename, "error": "file too large; max 50MB"})
                continue
            target = self.upload_dir_provider() / f"{int(time.time() * 1000)}_{safe_filename(file.filename or 'upload')}"
            await asyncio.to_thread(target.write_bytes,raw)
            try:
                doc = await asyncio.to_thread(ingest_file,
                    self.memory_store_provider(),
                    self.upload_dir_provider(),
                    target,
                    title=Path(file.filename or target.name).stem,
                    category=str(category or "domain"),
                )
                documents.append(doc)
            except Exception as exc:
                errors.append({"filename": file.filename, "error": str(exc)})
        deferred = indexing_mode=='background' or indexing_mode=='auto' and sum(int(d.get('chunk_count') or 0) for d in documents)>=16
        if indexing_mode=='auto' and self.document_index_worker_provider() is not None and self.document_index_worker_provider().store is self.memory_store_provider():
            backlog=await asyncio.to_thread(self.document_index_worker_provider().status)
            deferred=deferred or backlog['running'] or backlog['pending']>=16
        indexing = None
        if self.vector_store_provider() and deferred:
            worker=self.get_document_index_worker();worker.start()
            indexing=await asyncio.to_thread(worker.status)
        elif self.vector_store_provider():
            await asyncio.to_thread(self.vector_store_provider().refresh)
        return JSONResponse({"documents": documents, "errors": errors, "count": len(documents),"indexing":indexing},status_code=202 if deferred and documents else 200)


    async def api_document_indexing_status(self):
        return JSONResponse(await asyncio.to_thread(self.get_document_index_worker().status))


    async def api_document_indexing_retry(self):
        worker=self.get_document_index_worker();worker.start()
        return JSONResponse(await asyncio.to_thread(worker.status),status_code=202)


    async def api_documents(self, category: str = ""):
        if not self.memory_store_provider():
            return JSONResponse({"documents": [], "count": 0}, status_code=503)
        docs = self.memory_store_provider().list_documents(category)
        return JSONResponse({"documents": docs, "count": len(docs)})


    async def api_documents_ocr_queue(self, category: str = ""):
        service = self.get_knowledge_service()
        pending = service.list_ocr_queue(category)
        return JSONResponse({"documents": pending, "count": len(pending)})


    async def api_document_run_ocr(self, document_id: int, request: Request):
        service = self.get_knowledge_service()
        data = await request.json()
        try:
            result = service.run_ocr(
                document_id,
                sidecar_text=str(data.get("sidecar_text") or ""),
                force=bool(data.get("force")),
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Document not found":
                raise HTTPException(404, message)
            raise HTTPException(400, message)
        return JSONResponse(result)


    async def api_document_review(self, document_id: int):
        try:
            return JSONResponse(self.get_document_review_service().queue(document_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc))


    async def api_document_review_crop(self, document_id: int, node_id: str):
        from fastapi.responses import Response
        try:
            return Response(self.get_document_review_service().crop(document_id, node_id), media_type="image/png", headers={"Cache-Control": "no-store"})
        except ValueError as exc:
            raise HTTPException(409, str(exc))


    async def api_document_review_submit(self, document_id: int, request: Request):
        data = await request.json()
        try:
            result = self.get_document_review_service().submit(document_id, chunk_id=int(data.get("chunk_id") or 0),
                        revision=str(data.get("revision") or ""), values=data.get("values"),
                        confirmed=data.get("confirmed"), action=str(data.get("action") or "approve"),
                        active_review_ms=data.get("active_review_ms"))
            return JSONResponse(result)
        except (ValueError, TypeError) as exc:
            raise HTTPException(409, str(exc))


    async def api_document_review_publish(self, document_id: int, request: Request):
        data = await request.json()
        try:
            result = self.get_document_review_service().publish(document_id, confirmed=data.get("confirmed"))
            service = self.get_knowledge_service()
            if service.vector_refresh:
                service.vector_refresh()
            return JSONResponse(result)
        except ValueError as exc:
            raise HTTPException(409, str(exc))


    async def api_document_source(self, document_id: int):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        document = self.memory_store_provider().get_document(document_id)
        if not document:
            raise HTTPException(404, "Document not found")
        source = Path(str(document.get("file_path") or "")).expanduser()
        if not source:
            raise HTTPException(404, "Document has no source file")
        source = source.resolve()
        preview_roots = [self.upload_dir_provider().resolve(), self.data_dir_provider().resolve(), self.output_root_provider().resolve()]
        allowed = False
        for root in preview_roots:
            try:
                source.relative_to(root)
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            raise HTTPException(403, "Document source is outside the configured local workspace")
        if not source.exists() or not source.is_file():
            raise HTTPException(404, "Document source file not found")
        suffix = source.suffix.lower()
        media_types = {
            ".pdf": "application/pdf",
            ".txt": "text/plain; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
            ".markdown": "text/markdown; charset=utf-8",
            ".csv": "text/csv; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".htm": "text/html; charset=utf-8",
        }
        if suffix not in media_types:
            raise HTTPException(415, "Document source type is not previewable")
        return FileResponse(source, media_type=media_types[suffix], headers={"Content-Disposition": "inline"})


    async def api_document_page(self, document_id:int,page:int=1):
        # Reuse the source endpoint's document ownership/root/type checks.
        source=await self.api_document_source(document_id)
        try:
            value=await asyncio.to_thread(self._pdf_page_renderer_provider().render,source.path,page)
            return JSONResponse(value)
        except (ValueError,OSError) as e:raise HTTPException(400,str(e))
        except ImportError:raise HTTPException(503,'PDF 页渲染依赖不可用，请安装项目 PyMuPDF 依赖。')


    async def api_document_semantic_graph(self, document_id: int, compact: bool = False):
        try:
            graph = self.get_paper_intelligence_service().semantic_graph(document_id, compact=compact)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return JSONResponse({"document_id": document_id, "graph": graph})


    async def api_document_chunks(self, document_id: int, limit: int = 20, offset: int = 0, include_review: bool = False):
        if not self.memory_store_provider():
            return JSONResponse({"chunks": [], "count": 0}, status_code=503)
        document = self.memory_store_provider().get_document(document_id)
        if not document:
            raise HTTPException(404, "Document not found")
        take=max(1,min(int(limit or 20),100));offset=max(0,offset)
        chunks = self.memory_store_provider().get_document_chunks(document_id, take+1, offset=offset,include_review=include_review)
        has_more=len(chunks)>take;chunks=chunks[:take]
        return JSONResponse({"document": document, "chunks": chunks, "count": len(chunks),"has_more":has_more,"next_offset":offset+len(chunks),
            "boundary":"Review-required chunks are reader text only; they are not admitted as verified evidence." if include_review else "Only evidence-ready chunks."})


    async def api_document_search(self, q: str = "", category: str = "", limit: int = 10):
        if not self.memory_store_provider():
            return JSONResponse({"chunks": [], "count": 0}, status_code=503)
        if not q:
            return JSONResponse({"chunks": [], "count": 0})
        chunks = self.memory_store_provider().search_document_chunks(q, category, max(1, min(int(limit or 10), 50)))
        return JSONResponse({"chunks": chunks, "count": len(chunks)})


    async def api_document_citation_answer(self, q: str = "", category: str = "", document_id: int = 0, limit: int = 5):
        service = self.get_knowledge_service()
        try:
            result = service.citation_answer(q, category, document_id, limit)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        result["document_id"] = int(document_id or 0)
        if self.memory_store_provider():
            stamp = int(time.time() * 1000)
            citations = result.get("citations") or []
            title_query = (q or "citation answer").strip()[:96] or "citation answer"
            run = RunRecord(
                run_id=f"academy-citation-answer-{int(document_id or 0)}-{stamp}",
                run_type="academy_citation_answer",
                title=f"Academy citation answer: {title_query}",
                status=result["status"],
                actor="system",
                scenario="research",
                inputs={"query": q, "category": category, "document_id": int(document_id or 0), "limit": int(limit or 5)},
                outputs={"answer": result.get("answer", ""), "citations": citations, "count": result.get("count", len(citations)), "answer_verified": False, "mode": result["mode"]},
                metrics={"citation_count": len(citations)},
                tags=["academy", "paper", "citation-answer"],
            )
            for citation in citations[:12]:
                citation_doc_id = int(citation.get("document_id") or document_id or 0)
                run.add_evidence(
                    "academy_citation_answer",
                    str(citation.get("snippet") or citation.get("title") or "Citation evidence")[:360],
                    citation=str(citation.get("citation") or f"doc:{citation_doc_id}"),
                    document_id=citation_doc_id,
                    chunk_id=citation.get("chunk_id"),
                )
            result["run"] = self.memory_store_provider().save_run_record(run.to_dict())
        return JSONResponse(result)
