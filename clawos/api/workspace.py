"""Workspace HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
import importlib.util
import os
import shutil


class WorkspaceAPI:
    def __init__(self, *,
        local_asr_capability: Callable[..., Any],
        security_policy_provider: Callable[[], Any],
        workspace_services_provider: Callable[[], Any],
    ):
        self.local_asr_capability = local_asr_capability
        self.security_policy_provider = security_policy_provider
        self.workspace_services_provider = workspace_services_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workspace/capabilities', self.api_workspace_capabilities, methods=['GET'])
        self.router.add_api_route('/api/workspace/templates', self.api_templates_list, methods=['GET'])
        self.router.add_api_route('/api/workspace/templates', self.api_template_register, methods=['POST'])
        self.router.add_api_route('/api/workspace/templates/{name}/instantiate', self.api_template_instantiate, methods=['POST'])

    async def api_workspace_capabilities(self):
        roots = [str(root) for root in (self.security_policy_provider().allowed_roots if self.security_policy_provider() else [])]
        templates = self.workspace_services_provider().list_templates() if self.workspace_services_provider() else []
        has = lambda package: importlib.util.find_spec(package) is not None
        grobid_url = os.environ.get("GROBID_BASE_URL", "").strip()
        return JSONResponse({
            "local_file_operations": {
                "allowed_roots": roots,
                "txt_read_write": True,
                "project_create": True,
                "template_create": True,
                "structured_file_generation": ["docx", "xlsx", "pptx", "pdf", "markdown", "json", "csv", "txt", "eml", "ics"],
                "requires_confirmation_for_writes": True,
            },
            "office_artifacts": {
                "docx": {"create": True, "replace_text": True, "inspect": True, "validate": True, "engine": "python-docx" if has("docx") else "stdlib-openxml"},
                "xlsx": {
                    "create": True,
                    "edit_cells": True,
                    "engine": "openpyxl" if has("openpyxl") else "stdlib-openxml",
                    "requires_microsoft_office": False,
                    "requires_extra_python_packages": not has("openpyxl"),
                },
                "pptx": {
                    "create": True,
                    "replace_text": True,
                    "engine": "python-pptx" if has("pptx") else "stdlib-openxml",
                    "requires_microsoft_office": False,
                    "requires_extra_python_packages": not has("pptx"),
                },
                "pdf": {"create": True, "inspect": True, "validate": True, "engine": "reportlab", "generic_edit": False},
                "markdown_txt_json_csv": {"create": True, "edit": True, "inspect": True, "validate": True, "csv_formula_injection_guard": True},
                "quality_pipeline": ["create_or_edit", "reopen", "validate", "sha256", "run_record"],
            },
            "document_understanding": {
                "txt": True,
                "pdf_text": shutil.which("pdftotext") is not None or has("pypdf") or has("fitz"),
                "pdf_layout": {
                    "pymupdf": has("fitz"),
                    "pdfplumber": has("pdfplumber"),
                    "grobid": bool(grobid_url),
                    "grobid_base_url": grobid_url,
                },
                "pdf_ocr": "paddleocr" if has("paddleocr") else "worker_with_sidecar_or_local_tesseract",
                "paddleocr_available": has("paddleocr"),
                "typst_available": shutil.which("typst") is not None,
                "citation_validation": True,
                "paper_learning_analysis": ["markdown", "pdf"],
            },
            "web_research": {
                "provider_router": ["tavily", "serpapi", "bing", "duckduckgo"],
                "search_cache": True,
                "failure_retry": True,
                "rate_limit": True,
                "source_ranking": True,
                "credibility_scoring": True,
                "freshness_scoring": True,
                "citation_consistency_check": True,
                "anti_hallucination_gate": True,
                "search_acceptance_suite": "web_search_benchmark",
                "browser_render_fetch": {
                    "playwright_available": has("playwright"),
                    "mode": "optional_render_js",
                },
            },
            "meeting_audio": {
                "audio_file_registration": True,
                "sidecar_transcript_import": True,
                "vad_silence_splitting": True,
                "speaker_diarization": "provided_labels_or_unattributed",
                "structured_meeting_card": True,
                "knowledge_evidence_save": True,
                "local_asr": self.local_asr_capability(),
                "local_whisper_available": self.local_asr_capability()["available"],
                "auto_transcription": self.local_asr_capability()["available"],
            },
            "connectors": {
                "calendar": {"draft": "rfc5545_ics", "publish": "approval_gated_caldav", "credentials": "environment_reference"},
                "email": {"draft": "rfc5322_mime_eml", "send": "approval_gated_smtp", "credentials": "environment_reference"},
                "auto_send": False,
                "idempotency_required": True,
            },
            "git": {
                "snapshot": True,
                "patch_preview": True,
                "approval_commit": True,
                "rollback": "git_revert",
                "coding_workflow": ["inspect", "plan", "checkpoint", "patch", "test", "review", "retry", "rollback"],
                "coding_writes_require_confirmation": True,
            },
            "autonomous_subagents": {
                "execution_mode": "model_driven_autonomous",
                "isolated_context": True,
                "dependency_dag": True,
                "bounded_concurrency": True,
                "tool_allowlist": True,
                "budget_ledger": True,
                "checkpoint_resume": True,
                "hard_gates_override_judge": True,
            },
            "templates": {
                "count": len(templates),
                "names": [item["name"] for item in templates],
            },
        })


    async def api_templates_list(self):
        rows = self.workspace_services_provider().list_templates()
        return JSONResponse({"templates": rows, "count": len(rows)})


    async def api_template_register(self, request: Request):
        data = await request.json()
        try:
            template = self.workspace_services_provider().register_template(
                data.get("name", ""),
                data.get("description", ""),
                data.get("files", {}),
                data.get("version", 1),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"template": template})


    async def api_template_instantiate(self, name: str, request: Request):
        data = await request.json()
        try:
            result = self.workspace_services_provider().instantiate_template(
                name,
                data.get("target_path", ""),
                data.get("parameters", {}),
                data.get("version"),
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(result)
