"""Research HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi import Request
import asyncio
from memoryos.document_ingestion import ingest_file


class ResearchAPI:
    def __init__(self, *,
        get_paper_intelligence_service: Callable[..., Any],
        get_scholarly_search_service: Callable[..., Any],
        upload_dir_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
        security_policy_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
    ):
        self.get_paper_intelligence_service = get_paper_intelligence_service
        self.get_scholarly_search_service = get_scholarly_search_service
        self.upload_dir_provider = upload_dir_provider
        self.memory_store_provider = memory_store_provider
        self.security_policy_provider = security_policy_provider
        self.vector_store_provider = vector_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/research/papers/{document_id}/structure', self.api_paper_structure, methods=['GET'])
        self.router.add_api_route('/api/research/claims/align', self.api_claim_citation_alignment, methods=['POST'])
        self.router.add_api_route('/api/research/papers/compare', self.api_paper_comparison, methods=['POST'])
        self.router.add_api_route('/api/research/papers/readiness', self.api_paper_readiness, methods=['GET'])
        self.router.add_api_route('/api/research/literature/search', self.api_scholarly_search, methods=['GET'])
        self.router.add_api_route('/api/research/literature/open-access', self.api_scholarly_open_access, methods=['GET'])
        self.router.add_api_route('/api/research/literature/download', self.api_scholarly_download, methods=['POST'])

    async def api_paper_structure(self, document_id: int):
        try:
            return JSONResponse(self.get_paper_intelligence_service().analyze_document(document_id))
        except ValueError as exc:
            raise HTTPException(404, str(exc))


    async def api_claim_citation_alignment(self, request: Request):
        data = await request.json()
        claims = data.get("claims") or []
        if not isinstance(claims, list) or not claims:
            raise HTTPException(400, "claims must be a non-empty list")
        try:
            document_ids = [int(item) for item in (data.get("document_ids") or [])]
            threshold = float(data.get("threshold", 0.34))
        except (TypeError, ValueError):
            raise HTTPException(400, "document_ids and threshold must be numeric")
        return JSONResponse(self.get_paper_intelligence_service().align_claims(claims, document_ids, threshold))


    async def api_paper_comparison(self, request: Request):
        data = await request.json()
        try:
            document_ids = [int(item) for item in (data.get("document_ids") or [])]
        except (TypeError, ValueError):
            raise HTTPException(400, "document_ids must be numeric")
        if len(set(document_ids)) < 2:
            raise HTTPException(400, "at least two document_ids are required")
        try:
            return JSONResponse(self.get_paper_intelligence_service().compare_documents(document_ids))
        except ValueError as exc:
            raise HTTPException(404, str(exc))


    async def api_paper_readiness(self, document_ids: str = ""):
        try:
            ids = [int(item) for item in document_ids.split(",") if item.strip()] or None
        except ValueError:
            raise HTTPException(400, "document_ids must be comma-separated integers")
        return JSONResponse(self.get_paper_intelligence_service().readiness(ids))


    async def api_scholarly_search(self,
        q: str,
        limit: int = 10,
        providers: str = "crossref,openalex,semantic_scholar",
        year_from: int = 0,
        year_to: int = 0,
        open_access_only: bool = False,
    ):
        selected = [item.strip() for item in providers.split(",") if item.strip()]
        try:
            result = await asyncio.to_thread(
                self.get_scholarly_search_service().search,
                q,
                limit,
                selected,
                year_from,
                year_to,
                open_access_only,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)


    async def api_scholarly_open_access(self, doi: str, email: str = ""):
        try:
            result = await asyncio.to_thread(self.get_scholarly_search_service().resolve_open_access, doi, email)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(502, f"open-access registry unavailable: {type(exc).__name__}")
        return JSONResponse(result)


    async def api_scholarly_download(self, request: Request):
        data = await request.json()
        if data.get("confirmed") is not True:
            raise HTTPException(409, "confirmed=true is required for network download and local ingestion")
        try:
            if not self.memory_store_provider() or not self.security_policy_provider():
                raise HTTPException(503, "research storage is not initialized")
            paper = dict(data.get("paper") or {})
            if not paper.get("open_access_pdf_url") and paper.get("doi"):
                resolved = await asyncio.to_thread(
                    self.get_scholarly_search_service().resolve_open_access,
                    paper["doi"],
                    data.get("email", ""),
                )
                paper.update({"pdf_url": resolved.get("pdf_url", ""), "license": resolved.get("license", ""), "open_access_verified_by": "unpaywall"})
            output_dir = self.security_policy_provider().resolve_path(data.get("output_dir") or str(self.upload_dir_provider() / "scholarly"))
            download = await asyncio.to_thread(
                self.get_scholarly_search_service().download_open_access,
                paper,
                output_dir,
                int(data.get("max_bytes") or 50_000_000),
            )
            document = await asyncio.to_thread(
                ingest_file,
                self.memory_store_provider(),
                self.upload_dir_provider(),
                Path(download["path"]),
                title=str(paper.get("title") or ""),
                category="research",
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(502, f"scholarly download or ingestion failed: {type(exc).__name__}")
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse({"download": download, "document": document, "next": {"structure_url": f"/api/research/papers/{document['id']}/structure"}})
