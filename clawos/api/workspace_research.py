"""Workspace research HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from services.grounded_paper_report import GroundedPaperReport
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi import Request
from services.runtime_records import RunRecord
import asyncio
import json
import time


class WorkspaceResearchAPI:
    def __init__(self, *,
        call_model_with_fallback: Callable[..., Any],
        get_artifact_delivery_service: Callable[..., Any],
        get_paper_intelligence_service: Callable[..., Any],
        memory_store_provider: Callable[[], Any],
        vector_store_provider: Callable[[], Any],
        workspace_services_provider: Callable[[], Any],
    ):
        self.call_model_with_fallback = call_model_with_fallback
        self.get_artifact_delivery_service = get_artifact_delivery_service
        self.get_paper_intelligence_service = get_paper_intelligence_service
        self.memory_store_provider = memory_store_provider
        self.vector_store_provider = vector_store_provider
        self.workspace_services_provider = workspace_services_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workspace/research/import', self.api_research_import, methods=['POST'])
        self.router.add_api_route('/api/workspace/research/search', self.api_research_search, methods=['GET'])
        self.router.add_api_route('/api/workspace/research/citations/validate', self.api_research_citations_validate, methods=['POST'])
        self.router.add_api_route('/api/workspace/research/compare-matrix', self.api_research_compare_matrix, methods=['POST'])
        self.router.add_api_route('/api/workspace/research/repro-workflows', self.api_research_repro_workflow, methods=['POST'])
        self.router.add_api_route('/api/workspace/research/learning-analysis', self.api_research_learning_analysis, methods=['POST'])

    async def api_research_import(self, request: Request):
        data = await request.json()
        try:
            document = self.workspace_services_provider().import_research_pdf(
                data.get("file_path", ""), data.get("title", "")
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        if self.vector_store_provider():
            self.vector_store_provider().refresh()
        return JSONResponse({"document": document})


    async def api_research_search(self, q: str, limit: int = 10):
        rows = self.workspace_services_provider().search_research(q, limit)
        return JSONResponse({"results": rows, "count": len(rows)})


    async def api_research_citations_validate(self, request: Request):
        data = await request.json()
        return JSONResponse(self.workspace_services_provider().validate_citations(data.get("citations", [])))


    async def api_research_compare_matrix(self, request: Request):
        data = await request.json()
        return JSONResponse(self.workspace_services_provider().research_compare_matrix(
            data.get("document_ids"),
            data.get("query_terms", []),
        ))


    async def api_research_repro_workflow(self, request: Request):
        data = await request.json()
        try:
            workflow = self.workspace_services_provider().create_repro_workflow(
                data.get("title", "Reproducible experiment"),
                question=data.get("question", ""),
                steps=data.get("steps"),
                output_path=data.get("output_path", ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"workflow": workflow})


    async def api_research_learning_analysis(self, request: Request):
        data = await request.json()
        library_document = None
        library_document_id = data.get("library_document_id")
        if library_document_id:
            if not self.memory_store_provider():
                raise HTTPException(503, "MemoryOS not initialized")
            try:
                library_document_id = int(library_document_id)
            except (TypeError, ValueError):
                raise HTTPException(400, "Invalid document id")
            library_document = self.memory_store_provider().get_document(library_document_id)
            if not library_document:
                raise HTTPException(404, "Document not found")
            if library_document.get("status") != "ready":
                raise HTTPException(400, "Document is not ready for report generation")
            if not library_document.get("file_path"):
                raise HTTPException(400, "Document has no source file path")
            data["file_path"] = library_document.get("file_path", "")
            data["title"] = data.get("title") or library_document.get("title", "")
        try:
            result = await asyncio.to_thread(
                self.workspace_services_provider().generate_research_learning_analysis,
                document_id=data.get("document_id"),
                file_path=data.get("file_path", ""),
                title=data.get("title", ""),
                output_dir=data.get("output_dir", ""),
                formats=data.get("formats"),
                depth=data.get("depth", 5),
                question_count=data.get("question_count", 50),
                report_style=data.get("report_style", "journal"),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        if library_document:
            intelligence = await asyncio.to_thread(self.get_paper_intelligence_service().analyze_document, library_document_id)
            source_chunks=await asyncio.to_thread(self.memory_store_provider().get_document_chunks,library_document_id,1000)
            evidence_bundle = GroundedPaperReport.build_evidence_bundle(intelligence,source_chunks)
            synthesis = None
            model_trace = {"ok": False, "error": "model_assistance_disabled"}
            if data.get("model_assisted", True) is not False:
                try:
                    model_trace = await asyncio.wait_for(
                        self.call_model_with_fallback(
                            "upstream",
                            GroundedPaperReport.prompt(evidence_bundle),
                            {"temperature": 0.0, "max_tokens": 4200},
                        ),
                        timeout=90,
                    )
                    if model_trace.get("ok"):
                        synthesis = GroundedPaperReport.parse_model_output(model_trace.get("content", ""), evidence_bundle)
                except asyncio.TimeoutError:
                    model_trace = {"ok": False, "error": "timeout"}
                except Exception as exc:
                    model_trace = {"ok": False, "error": type(exc).__name__}
            if synthesis is None:
                synthesis = GroundedPaperReport.fallback(evidence_bundle)
            grounded_markdown = GroundedPaperReport.render_markdown(synthesis)
            report_row = result.get("report") or {}
            markdown_path = str(report_row.get("markdown_path") or "")
            pdf_path = str(report_row.get("pdf_path") or "")
            if markdown_path:
                from services.file_transactions import write_text
                await asyncio.to_thread(write_text, markdown_path, grounded_markdown)
            structured_base = report_row.get('json_path') or markdown_path or pdf_path
            if structured_base:
                from services.file_transactions import write_text
                json_path = str(Path(structured_base).with_suffix('.json'))
                await asyncio.to_thread(write_text, json_path, json.dumps(synthesis, ensure_ascii=False, indent=2))
                report_row['json_path'] = json_path
            if pdf_path:
                await asyncio.to_thread(self.workspace_services_provider()._write_learning_analysis_pdf, Path(pdf_path), synthesis.get("title") or library_document.get("title") or "Paper report", grounded_markdown)
            metadata = dict(report_row.get("metadata") or {})
            metadata.update({
                "mode": synthesis.get("mode"),
                "schema": synthesis.get("schema"),
                "evidence_count": synthesis.get("evidence_count", 0),
                "source_quality": synthesis.get("source_quality") or {},
                "synthesis": synthesis,
                "json_path": report_row.get('json_path', ''),
                "model": {
                    "provider": model_trace.get("provider", ""),
                    "model": model_trace.get("model", ""),
                    "ok": bool(model_trace.get("ok")),
                    "error": model_trace.get("error", ""),
                },
            })
            report_row["metadata"] = metadata
            if report_row.get("id"):
                with self.memory_store_provider()._conn() as conn:
                    conn.execute(
                        "UPDATE research_analysis_reports SET metadata=? WHERE id=?",
                        (json.dumps(metadata, ensure_ascii=False), int(report_row["id"])),
                    )
            result["analysis"] = synthesis
            result["paper_intelligence"] = {
                "quality": intelligence.get("quality") or {},
                "tables": list(intelligence.get("tables") or [])[:8],
                "formulas": list(intelligence.get("formulas") or [])[:8],
                "references": list(intelligence.get("references") or [])[:20],
            }
            result["report_content"] = grounded_markdown
            result["preview"] = synthesis.get("summary") or grounded_markdown[:1200]
            from services.workspace.reports import ReportsWorkspace
            result["library_document"] = await asyncio.to_thread(ReportsWorkspace._learning_report_document,library_document,metadata_reference='documents.metadata')
            report = result.get("report") or {}
            stamp = time.time_ns()
            run = RunRecord(
                f"academy-paper-report-{library_document_id}-{stamp}",
                "academy_paper_report",
                f"Academy paper report: {library_document.get('title') or library_document.get('filename') or library_document_id}",
                status="pass",
                actor="system",
                scenario="research",
                inputs={
                    "document_id": library_document_id,
                    "title": library_document.get("title"),
                    "report_style": data.get("report_style", "journal"),
                },
                outputs={"report": report, "preview": result.get("preview", "")},
                metrics={"question_count": data.get("question_count", 50), "depth": data.get("depth", 5)},
                tags=["academy", "paper", "report"],
            )
            markdown_path = str(report.get("markdown_path") or "")
            pdf_path = str(report.get("pdf_path") or "")
            if markdown_path:
                run.add_artifact("markdown_report", "Academy paper markdown report", markdown_path)
            if pdf_path:
                run.add_artifact("pdf_report", "Academy paper PDF report", pdf_path)
            if report.get('json_path'):
                run.add_artifact('structured_report', 'Structured paper reading report', report['json_path'])
            def register_report_artifacts():
                return [self.get_artifact_delivery_service().register(path, source_tool='academy_paper_report')
                        for path in [markdown_path, pdf_path, report.get('json_path')]
                        if path and Path(path).is_file()]
            result['artifacts'] = await asyncio.to_thread(register_report_artifacts)
            result['artifacts'] = [item for item in result['artifacts'] if item]
            report['metadata']['artifacts'] = result['artifacts']
            if report.get('id'):
                with self.memory_store_provider()._conn() as conn:
                    conn.execute('UPDATE research_analysis_reports SET metadata=? WHERE id=?',
                                 (json.dumps(report['metadata'],ensure_ascii=False),int(report['id'])))
            run.add_evidence("academy_paper_report", "Report is linked to the uploaded source document", citation=f"doc:{library_document_id}", document_id=library_document_id)
            result["run"] = self.memory_store_provider().save_run_record(run.to_dict())
        return JSONResponse(result)
