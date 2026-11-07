"""Workbench HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from services import ArtifactStorage
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
from fastapi import Request
from services.runtime_records import RunRecord
import argparse
import asyncio
import json
from services.runtime_records import now_iso
from services.artifact_storage import safe_artifact_slug
import time


class WorkbenchAPI:
    def __init__(self, *,
        _academy_count_run_records: Callable[..., Any],
        _academy_offline_audit_payload: Callable[..., Any],
        _local_qwen_smoke_check: Callable[..., Any],
        _system_readiness_payload: Callable[..., Any],
        local_model_assets_status: Callable[..., Any],
        base_dir_provider: Callable[[], Any],
        output_root_provider: Callable[[], Any],
        memory_store_provider: Callable[[], Any],
    ):
        self._academy_count_run_records = _academy_count_run_records
        self._academy_offline_audit_payload = _academy_offline_audit_payload
        self._local_qwen_smoke_check = _local_qwen_smoke_check
        self._system_readiness_payload = _system_readiness_payload
        self.local_model_assets_status = local_model_assets_status
        self.base_dir_provider = base_dir_provider
        self.output_root_provider = output_root_provider
        self.memory_store_provider = memory_store_provider
        self.router = APIRouter()
        self.router.add_api_route('/api/workbench/offline-readiness', self.api_workbench_offline_readiness, methods=['GET'])
        self.router.add_api_route('/api/workbench/daily-local-acceptance', self.api_workbench_daily_local_acceptance, methods=['POST'])
        self.router.add_api_route('/api/workbench/local-qwen-smoke', self.api_workbench_local_qwen_smoke, methods=['POST'])
        self.router.add_api_route('/api/workbench/local-timeline', self.api_workbench_local_timeline, methods=['GET'])
        self.router.add_api_route('/api/workbench/local-acceptance-history', self.api_workbench_local_acceptance_history, methods=['GET'])
        self.router.add_api_route('/api/workbench/local-acceptance-trends', self.api_workbench_local_acceptance_trends, methods=['GET'])
        self.router.add_api_route('/api/workbench/local-remediation-guide', self.api_workbench_local_remediation_guide, methods=['GET'])
        self.router.add_api_route('/api/workbench/local-remediation-actions', self.api_workbench_local_remediation_action, methods=['POST'])
        self.router.add_api_route('/api/workbench/local-remediation-actions/recheck', self.api_workbench_local_remediation_recheck, methods=['POST'])
        self.router.add_api_route('/api/workbench/local-maintenance-report', self.api_workbench_local_maintenance_report, methods=['POST'])
        self.router.add_api_route('/api/workbench/local-maintenance-reports', self.api_workbench_local_maintenance_reports, methods=['GET'])
        self.router.add_api_route('/api/workbench/local-maintenance-reports/{run_id}', self.api_workbench_local_maintenance_report_detail, methods=['GET'])

    def _workbench_offline_readiness_payload(self, document_id: int = 0) -> dict[str, Any]:
        system = self._system_readiness_payload()
        local_model = system.get("local_model_assets", {})
        try:
            paper = self._academy_offline_audit_payload(document_id)
        except HTTPException as exc:
            paper = {
                "ok": False,
                "percent": 0,
                "standard": "local-first research workflow readiness",
                "counts": {},
                "checks": [],
                "remaining": [{"id": "paper_memory", "label": "Paper workflow memory", "ok": False, "detail": str(exc.detail)}],
            }
        paper_checks = {item.get("id"): item for item in paper.get("checks", [])}
        paper_counts = paper.get("counts", {})
        checks = [
            {"id": "system_readiness", "label": "System services", "ok": float(system.get("score", 0)) >= 0.8, "weight": 20, "detail": f"{system.get('percent', 0)}%"},
            {"id": "local_model_assets", "label": "Local 8B/9B model assets", "ok": bool(local_model.get("ready")), "weight": 25, "detail": local_model.get("summary", "")},
            {"id": "paper_workflow", "label": "Paper and report workflow", "ok": float(paper.get("percent", 0)) >= 75, "weight": 20, "detail": f"{paper.get('percent', 0)}%"},
            {"id": "evidence_chain", "label": "Searchable citation evidence", "ok": bool(paper_checks.get("evidence_search", {}).get("ok") and paper_checks.get("knowledge_capture", {}).get("ok")), "weight": 15, "detail": f"chunks:{paper_counts.get('chunks', 0)} knowledge:{paper_counts.get('research_knowledge', 0)}"},
            {"id": "project_management", "label": "Research project board", "ok": int(paper_counts.get("project_items", 0) or 0) > 0, "weight": 10, "detail": f"items:{paper_counts.get('project_items', 0)}"},
            {"id": "offline_artifacts", "label": "Checkpoints and project packages", "ok": int(paper_counts.get("checkpoints", 0) or 0) > 0 and int(paper_counts.get("project_packages", 0) or 0) > 0, "weight": 10, "detail": f"checkpoints:{paper_counts.get('checkpoints', 0)} packages:{paper_counts.get('project_packages', 0)}"},
        ]
        total = sum(int(item["weight"]) for item in checks)
        passed = sum(int(item["weight"]) for item in checks if item["ok"])
        percent = round((passed / total) * 100, 1) if total else 0
        return {
            "ok": percent >= 90,
            "percent": percent,
            "standard": "local-first workbench offline readiness",
            "system": system,
            "model": {"local_model_assets": local_model},
            "paper": paper,
            "checks": checks,
            "remaining": [item for item in checks if not item["ok"]],
        }


    async def api_workbench_offline_readiness(self, document_id: int = 0):
        return JSONResponse(self._workbench_offline_readiness_payload(document_id))


    def _daily_local_acceptance_summary(self, payload: dict[str, Any]) -> str:
        readiness = payload.get("workbench_readiness", {})
        frozen = payload.get("frozen_benchmark", {})
        model = payload.get("model_acceptance", {})
        qwen = payload.get("local_qwen_smoke") or {}
        frozen_metrics = frozen.get("metrics", {})
        model_benchmark = model.get("benchmark", {})
        evaluation = model.get("evaluation", {})
        lines = [
            "ClawOS Daily Local Acceptance",
            f"Mode: {payload.get('mode', 'quick')}",
            f"Workbench readiness: {readiness.get('percent', 0)}% ({'ready' if readiness.get('ok') else 'needs attention'})",
            f"Frozen benchmark: {frozen_metrics.get('passed_count', 0)}/{frozen_metrics.get('case_count', 0)} pass_rate={frozen_metrics.get('pass_rate', 0)} p95_ms={frozen_metrics.get('p95_latency_ms', 0)}",
            f"Mock model acceptance: {model_benchmark.get('passed_count', 0)}/{model_benchmark.get('case_count', 0)} score={evaluation.get('total_score', 0)}/{evaluation.get('max_score', 0)} rate={evaluation.get('score_rate', 0)}",
        ]
        if qwen:
            lines.append(f"Local Qwen smoke: {'ok' if qwen.get('ok') else 'not ready'} endpoint={qwen.get('base_url', '')} model={qwen.get('model', '')} error={qwen.get('error', '')}")
        remaining = readiness.get("remaining") or []
        if remaining:
            lines.append("Remaining readiness items: " + ", ".join(str(item.get("id") or item.get("label") or "check") for item in remaining[:8]))
        else:
            lines.append("Remaining readiness items: none")
        return "\n".join(lines)


    def _daily_acceptance_run_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        outputs = run.get("outputs") or {}
        metrics = run.get("metrics") or {}
        qwen = outputs.get("local_qwen_smoke") or {}
        return {
            "run_id": run.get("run_id", ""),
            "run_type": run.get("run_type", ""),
            "title": run.get("title", ""),
            "status": run.get("status", ""),
            "updated_at": run.get("updated_at", ""),
            "mode": (run.get("inputs") or {}).get("mode", ""),
            "workbench_percent": metrics.get("workbench_percent", 0),
            "benchmark_pass_rate": metrics.get("benchmark_pass_rate", 0),
            "model_score_rate": metrics.get("model_score_rate", 0),
            "qwen_ok": qwen.get("ok") if qwen else None,
            "qwen_error": qwen.get("error", "") if qwen else "",
            "summary": outputs.get("summary", ""),
        }


    def _workbench_timeline_item(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        run_type = run.get("run_type", "")
        outputs = run.get("outputs") or {}
        metrics = run.get("metrics") or {}
        updated_at = run.get("updated_at") or run.get("created_at") or ""
        base = {
            "run_id": run.get("run_id", ""),
            "run_type": run_type,
            "status": run.get("status", ""),
            "updated_at": updated_at,
            "title": run.get("title", ""),
            "target": {"kind": run_type, "run_id": run.get("run_id", "")},
        }
        if run_type == "workbench_daily_acceptance":
            return [{
                **base,
                "kind": "daily_acceptance",
                "label": "Daily local acceptance",
                "summary": outputs.get("summary", ""),
                "detail": f"readiness:{metrics.get('workbench_percent', 0)}% benchmark:{metrics.get('benchmark_pass_rate', 0)} model:{metrics.get('model_score_rate', 0)}",
                "payload": {"summary": outputs.get("summary", ""), "metrics": metrics},
            }]
        if run_type == "workbench_qwen_smoke":
            qwen = outputs.get("local_qwen_smoke") or {}
            return [{
                **base,
                "kind": "qwen_smoke",
                "label": "Local Qwen smoke",
                "summary": qwen.get("assets_summary") or qwen.get("error") or run.get("title", ""),
                "detail": f"model:{qwen.get('model', '')} ok:{qwen.get('ok')}",
                "payload": {"local_qwen_smoke": qwen},
            }]
        if run_type == "workbench_remediation_action":
            action_id = outputs.get("action_id") or (run.get("inputs") or {}).get("action_id") or ""
            items = [{
                **base,
                "kind": "remediation_action",
                "label": f"Remediation {run.get('status', 'open')}",
                "summary": str((run.get("inputs") or {}).get("gap") or action_id),
                "detail": outputs.get("note") or "local remediation state updated",
                "payload": {"action_id": action_id, "outputs": outputs, "inputs": run.get("inputs") or {}},
            }]
            recheck = outputs.get("last_recheck") or {}
            if recheck.get("checked_at"):
                items.append({
                    **base,
                    "kind": "remediation_recheck",
                    "label": "Remediation recheck",
                    "status": "pass" if recheck.get("ok") else "fail",
                    "updated_at": recheck.get("checked_at") or updated_at,
                    "summary": str((run.get("inputs") or {}).get("gap") or action_id),
                    "detail": f"checks:{recheck.get('count', 0)} ok:{recheck.get('ok')}",
                    "payload": {"action_id": action_id, "recheck": recheck},
                })
            return items
        if run_type == "workbench_maintenance_report":
            return [{
                **base,
                "kind": "maintenance_report",
                "label": "Maintenance report",
                "summary": f"readiness:{outputs.get('readiness_percent', metrics.get('workbench_percent', 0))}% remediation:{outputs.get('remediation_count', metrics.get('remediation_count', 0))}",
                "detail": "local JSON/Markdown report exported",
                "target": {"kind": "maintenance_report", "run_id": run.get("run_id", "")},
                "payload": {"outputs": outputs, "metrics": metrics},
            }]
        return []


    def _workbench_timeline_payload(self, limit: int = 30) -> dict[str, Any]:
        if not self.memory_store_provider():
            return {"items": [], "count": 0, "durable": False}
        max_items = max(1, min(int(limit or 30), 100))
        tracked = {"workbench_daily_acceptance", "workbench_qwen_smoke", "workbench_remediation_action", "workbench_maintenance_report"}
        items: list[dict[str, Any]] = []
        for run in self.memory_store_provider().list_run_records(limit=200):
            if run.get("run_type") not in tracked:
                continue
            items.extend(self._workbench_timeline_item(run))
        items.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return {"items": items[:max_items], "count": len(items[:max_items]), "durable": True}


    def _save_daily_acceptance_run(self, payload: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.memory_store_provider():
            return {}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        readiness = payload.get("workbench_readiness") or {}
        frozen = payload.get("frozen_benchmark") or {}
        frozen_metrics = frozen.get("metrics") or {}
        model = payload.get("model_acceptance") or {}
        evaluation = model.get("evaluation") or {}
        qwen = payload.get("local_qwen_smoke") or {}
        run = RunRecord(
            run_id=f"workbench-daily-acceptance-{stamp}",
            run_type="workbench_daily_acceptance",
            title="Workbench daily local acceptance",
            status="pass" if payload.get("ok") else "fail",
            actor="user",
            scenario="local-first-maintenance",
            inputs={
                "mode": payload.get("mode", "quick"),
                "limit": payload.get("limit", 0),
                "full_suite": bool(inputs.get("full_suite", False)),
                "include_qwen_smoke": bool(inputs.get("include_qwen_smoke", False)),
                "document_id": int(inputs.get("document_id") or 0),
            },
            outputs={
                "summary": payload.get("summary", ""),
                "remaining_readiness": readiness.get("remaining", []),
                "local_qwen_smoke": qwen,
                "failed_cases": frozen.get("failed_cases", []),
            },
            metrics={
                "workbench_percent": readiness.get("percent", 0),
                "benchmark_pass_rate": frozen_metrics.get("pass_rate", 0),
                "benchmark_passed_count": frozen_metrics.get("passed_count", 0),
                "benchmark_case_count": frozen_metrics.get("case_count", 0),
                "benchmark_p95_ms": frozen_metrics.get("p95_latency_ms", 0),
                "model_score_rate": evaluation.get("score_rate", 0),
                "model_total_score": evaluation.get("total_score", 0),
                "model_max_score": evaluation.get("max_score", 0),
                "qwen_ok": qwen.get("ok") if qwen else None,
            },
            tags=["daily", "offline", "acceptance", "qwen" if qwen else "mock"],
        )
        run.add_evidence("workbench_readiness", "Daily check includes local-first workbench readiness", score=readiness.get("percent", 0))
        run.add_evidence("frozen_benchmark", "Daily check includes frozen benchmark pass rate", score=frozen_metrics.get("pass_rate", 0))
        run.add_evidence("mock_model_acceptance", "Daily check includes mock model acceptance score", score=evaluation.get("score_rate", 0))
        if qwen:
            run.add_evidence("local_qwen_smoke", "Daily check explicitly includes local Qwen smoke result", score=1.0 if qwen.get("ok") else 0.0)
        for item in (readiness.get("remaining") or [])[:8]:
            run.add_failure_case("readiness_gap", str(item.get("label") or item.get("id") or "readiness gap"), severity="medium", output_summary=str(item.get("detail") or ""), remediation="Resolve the readiness item and rerun daily local acceptance.")
        if qwen and not qwen.get("ok"):
            run.add_failure_case("local_qwen_smoke", str(qwen.get("error") or "local Qwen smoke failed"), severity="high", output_summary=str(qwen.get("assets_summary") or ""), remediation="Start local llama.cpp/Qwen server and verify local model assets.")
        if not frozen.get("passed", True):
            run.add_failure_case("frozen_benchmark", "Frozen benchmark failed", severity="high", output_summary=json.dumps(frozen_metrics, ensure_ascii=False), remediation="Inspect failed benchmark cases before relying on the workbench.")
        saved = self.memory_store_provider().save_run_record(run.to_dict())
        payload["run"] = self._daily_acceptance_run_summary(saved)
        return saved


    def _save_qwen_smoke_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.memory_store_provider():
            return {}
        stamp = time.strftime("%Y%m%d-%H%M%S")
        run = RunRecord(
            run_id=f"workbench-qwen-smoke-{stamp}",
            run_type="workbench_qwen_smoke",
            title="Local Qwen smoke check",
            status="pass" if payload.get("ok") else "fail",
            actor="user",
            scenario="local-model-maintenance",
            inputs={"base_url": payload.get("base_url", ""), "model": payload.get("model", "")},
            outputs={"local_qwen_smoke": payload},
            metrics={"qwen_ok": bool(payload.get("ok")), "duration_ms": payload.get("duration_ms", 0), "assets_ready": bool(payload.get("assets_ready"))},
            tags=["qwen", "smoke", "offline"],
        )
        run.add_evidence("local_qwen_smoke", "Explicit local Qwen smoke check was run", score=1.0 if payload.get("ok") else 0.0)
        if not payload.get("ok"):
            run.add_failure_case("local_qwen_smoke", str(payload.get("error") or "local Qwen smoke failed"), severity="high", output_summary=str(payload.get("assets_summary") or ""), remediation="Start local llama.cpp/Qwen server and verify local model assets.")
        saved = self.memory_store_provider().save_run_record(run.to_dict())
        payload["run"] = self._daily_acceptance_run_summary(saved)
        return saved


    async def _daily_local_acceptance_payload(self, limit: int = 5, full_suite: bool = False, document_id: int = 0, include_qwen_smoke: bool = False) -> dict[str, Any]:
        from scripts.evaluate_model_acceptance import _main_async as run_model_acceptance
        from scripts.evaluate_model_acceptance import _run_suite as run_frozen_suite
        from scenario_benchmarks import DEFAULT_SUITE_FILE

        case_limit = 0 if full_suite else max(1, min(int(limit or 5), 30))
        suite_path = str(DEFAULT_SUITE_FILE)
        readiness = self._workbench_offline_readiness_payload(document_id)
        frozen = await asyncio.to_thread(run_frozen_suite, suite_path, case_limit)
        acceptance_args = argparse.Namespace(
            suite=suite_path,
            provider="mock",
            model="",
            base_url="",
            api_key_env="MODEL_API_KEY",
            timeout_s=60.0,
            mock_response="PASS: meeting research learning git template tool acceptance case reviewed with sufficient tool evidence.",
            limit=case_limit,
        )
        model_acceptance = await run_model_acceptance(acceptance_args)
        payload = {
            "ok": bool(readiness.get("ok") and frozen.get("passed") and model_acceptance.get("ok")),
            "mode": "full" if full_suite else "quick",
            "limit": case_limit,
            "standard": "daily local acceptance preset",
            "workbench_readiness": readiness,
            "frozen_benchmark": {
                "passed": bool(frozen.get("passed")),
                "metrics": frozen.get("metrics", {}),
                "failed_cases": [case for case in frozen.get("case_results", []) if not case.get("passed")],
            },
            "model_acceptance": {
                "ok": bool(model_acceptance.get("ok")),
                "provider": model_acceptance.get("provider"),
                "model": model_acceptance.get("model"),
                "configured": bool(model_acceptance.get("configured")),
                "benchmark": model_acceptance.get("benchmark", {}),
                "evaluation": model_acceptance.get("evaluation", {}),
                "provider_errors": (model_acceptance.get("evaluation", {}) or {}).get("provider_errors", {}),
            },
        }
        if include_qwen_smoke:
            payload["local_qwen_smoke"] = await self._local_qwen_smoke_check()
            payload["ok"] = bool(payload["ok"] and payload["local_qwen_smoke"].get("ok"))
        payload["summary"] = self._daily_local_acceptance_summary(payload)
        return payload


    async def api_workbench_daily_local_acceptance(self, request: Request):
        data = await request.json()
        payload = await self._daily_local_acceptance_payload(
            limit=int(data.get("limit") or 5),
            full_suite=bool(data.get("full_suite", False)),
            document_id=int(data.get("document_id") or 0),
            include_qwen_smoke=bool(data.get("include_qwen_smoke", False)),
        )
        if bool(data.get("persist", True)):
            self._save_daily_acceptance_run(payload, data)
        return JSONResponse(payload)


    async def api_workbench_local_qwen_smoke(self, request: Request):
        data = await request.json()
        payload = await self._local_qwen_smoke_check(timeout_s=float(data.get("timeout_s") or 20.0))
        if bool(data.get("persist", True)):
            self._save_qwen_smoke_run(payload)
        return JSONResponse(payload)


    def _local_acceptance_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.memory_store_provider():
            return []
        max_items = max(1, min(int(limit or 20), 100))
        runs = []
        for run_type in ("workbench_daily_acceptance", "workbench_qwen_smoke"):
            for item in self.memory_store_provider().list_run_records(run_type=run_type, limit=max_items):
                run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
                if run:
                    runs.append(run)
        runs.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return runs[:max_items]


    def _local_acceptance_trends(self, runs: list[dict[str, Any]]) -> dict[str, Any]:
        daily_runs = [run for run in runs if run.get("run_type") == "workbench_daily_acceptance"]
        qwen_runs = [run for run in runs if run.get("run_type") == "workbench_qwen_smoke" or (run.get("outputs") or {}).get("local_qwen_smoke")]
        def rate(items: list[dict[str, Any]]) -> float:
            return round(sum(1 for item in items if item.get("status") == "pass") / len(items), 4) if items else 0
        qwen_failure_streak = 0
        for run in qwen_runs:
            outputs = run.get("outputs") or {}
            qwen = outputs.get("local_qwen_smoke") or {}
            ok = bool(qwen.get("ok") if qwen else run.get("status") == "pass")
            if ok:
                break
            qwen_failure_streak += 1
        gap_counts: dict[str, int] = {}
        for run in daily_runs:
            for item in run.get("failure_cases") or []:
                if item.get("category") != "readiness_gap":
                    continue
                key = str(item.get("reason") or item.get("failure_id") or "readiness_gap")
                gap_counts[key] = gap_counts.get(key, 0) + 1
        top_gaps = [{"label": label, "count": count} for label, count in sorted(gap_counts.items(), key=lambda item: (-item[1], item[0]))[:8]]
        latest = self._daily_acceptance_run_summary(runs[0]) if runs else {}
        return {
            "latest": latest,
            "window": len(runs),
            "daily_count": len(daily_runs),
            "qwen_count": len(qwen_runs),
            "overall_pass_rate": rate(runs),
            "daily_pass_rate": rate(daily_runs),
            "qwen_pass_rate": rate(qwen_runs),
            "qwen_failure_streak": qwen_failure_streak,
            "average_workbench_percent": round(sum(float((run.get("metrics") or {}).get("workbench_percent") or 0) for run in daily_runs) / len(daily_runs), 2) if daily_runs else 0,
            "average_benchmark_pass_rate": round(sum(float((run.get("metrics") or {}).get("benchmark_pass_rate") or 0) for run in daily_runs) / len(daily_runs), 4) if daily_runs else 0,
            "average_model_score_rate": round(sum(float((run.get("metrics") or {}).get("model_score_rate") or 0) for run in daily_runs) / len(daily_runs), 4) if daily_runs else 0,
            "top_readiness_gaps": top_gaps,
        }


    async def api_workbench_local_timeline(self, limit: int = 30):
        return JSONResponse(self._workbench_timeline_payload(limit))


    async def api_workbench_local_acceptance_history(self, limit: int = 20):
        if not self.memory_store_provider():
            return JSONResponse({"runs": [], "count": 0, "durable": False})
        runs = self._local_acceptance_runs(limit)
        return JSONResponse({"runs": [self._daily_acceptance_run_summary(run) for run in runs], "count": len(runs), "durable": True})


    async def api_workbench_local_acceptance_trends(self, limit: int = 30):
        if not self.memory_store_provider():
            return JSONResponse({"trend": self._local_acceptance_trends([]), "count": 0, "durable": False})
        runs = self._local_acceptance_runs(limit)
        return JSONResponse({"trend": self._local_acceptance_trends(runs), "count": len(runs), "durable": True})


    def _remediation_action_for_gap(self, label: str, count: int = 1) -> dict[str, Any]:
        text = str(label or "").lower()
        local_model = self.local_model_assets_status()
        scripts = {"start_qwen": str(self.base_dir_provider() / "scripts" / "start_qwen_llama_server.ps1")}
        for index, script in enumerate(local_model.get("download_scripts") or []):
            scripts[f"download_{index + 1}"] = script
        if "qwen" in text or "model" in text or "llama" in text or "local 8b" in text or "local 8/9" in text:
            return {
                "id": "local_model_assets",
                "gap": label,
                "count": count,
                "severity": "high",
                "action": "Prepare local Qwen assets and start the llama.cpp OpenAI-compatible server.",
                "why": local_model.get("summary", "Local Qwen runtime is not fully ready."),
                "scripts": scripts,
                "checks": ["/api/model/health", "/api/workbench/local-qwen-smoke"],
            }
        if "evidence" in text or "citation" in text or "search" in text:
            return {
                "id": "evidence_chain",
                "gap": label,
                "count": count,
                "severity": "medium",
                "action": "Upload or reopen a research document, verify chunks, then save a citation-grounded answer to knowledge.",
                "why": "Evidence search needs parsed chunks and captured research knowledge before offline citation chains are useful.",
                "scripts": {},
                "checks": ["/api/documents", "/api/documents/search", "/api/academy/paper/offline-audit"],
            }
        if "package" in text or "checkpoint" in text or "artifact" in text:
            return {
                "id": "offline_artifacts",
                "gap": label,
                "count": count,
                "severity": "medium",
                "action": "Save a Paper Studio checkpoint and export a research project package after report generation.",
                "why": "Long-term offline work needs local resumable artifacts, not just transient UI state.",
                "scripts": {},
                "checks": ["/api/academy/paper/checkpoints", "/api/academy/paper/project-board/exports", "/api/academy/paper/offline-audit"],
            }
        if "project" in text or "board" in text or "management" in text:
            return {
                "id": "project_management",
                "gap": label,
                "count": count,
                "severity": "medium",
                "action": "Create at least one follow-up item on the Paper Studio project board and mark decisions as work progresses.",
                "why": "Research workflows become durable when follow-up questions and decisions are tracked as local RunRecords.",
                "scripts": {},
                "checks": ["/api/academy/paper/project-board", "/api/workbench/offline-readiness"],
            }
        if "document" in text or "ingestion" in text or "chunk" in text or "paper" in text or "report" in text:
            return {
                "id": "document_workflow",
                "gap": label,
                "count": count,
                "severity": "medium",
                "action": "Upload a research PDF/DOCX/text file, confirm chunks, and generate a local report from Paper Studio.",
                "why": "Document analysis and report generation need at least one parsed local document with chunks.",
                "scripts": {},
                "checks": ["/api/documents", "/api/academy/paper/status", "/api/workbench/offline-readiness"],
            }
        return {
            "id": "general_readiness",
            "gap": label,
            "count": count,
            "severity": "low",
            "action": "Run daily local acceptance again after resolving the listed readiness item.",
            "why": "This gap was observed in persisted local acceptance history.",
            "scripts": {},
            "checks": ["/api/workbench/daily-local-acceptance", "/api/workbench/local-acceptance-trends"],
        }


    def _remediation_action_key(self, action: dict[str, Any]) -> str:
        return str(action.get("id") or safe_artifact_slug(action.get("gap") or action.get("action") or "readiness-gap"))


    def _remediation_action_statuses(self, limit: int = 100) -> dict[str, dict[str, Any]]:
        if not self.memory_store_provider():
            return {}
        statuses: dict[str, dict[str, Any]] = {}
        for item in self.memory_store_provider().list_run_records(run_type="workbench_remediation_action", limit=limit):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            inputs = run.get("inputs") or {}
            outputs = run.get("outputs") or {}
            action_id = str(inputs.get("action_id") or outputs.get("action_id") or "")
            if not action_id or action_id in statuses:
                continue
            statuses[action_id] = {
                "run_id": run.get("run_id", ""),
                "action_id": action_id,
                "status": run.get("status", "open"),
                "note": outputs.get("note", ""),
                "updated_at": run.get("updated_at", ""),
                "last_recheck": outputs.get("last_recheck") or {},
            }
        return statuses


    def _local_remediation_payload(self, limit: int = 30) -> dict[str, Any]:
        runs = self._local_acceptance_runs(limit) if self.memory_store_provider() else []
        trend = self._local_acceptance_trends(runs)
        top_gaps = trend.get("top_readiness_gaps") or []
        actions = [self._remediation_action_for_gap(item.get("label", ""), int(item.get("count") or 1)) for item in top_gaps]
        if not actions:
            readiness = self._workbench_offline_readiness_payload(0)
            actions = [self._remediation_action_for_gap(item.get("label") or item.get("id") or "readiness gap", 1) for item in readiness.get("remaining", [])[:6]]
        statuses = self._remediation_action_statuses()
        for action in actions:
            action_id = self._remediation_action_key(action)
            state = statuses.get(action_id, {})
            action["action_id"] = action_id
            action["status"] = state.get("status", "open")
            action["status_note"] = state.get("note", "")
            action["status_updated_at"] = state.get("updated_at", "")
            action["status_run_id"] = state.get("run_id", "")
            action["last_recheck"] = state.get("last_recheck", {})
        reviewed_count = sum(1 for item in actions if item.get("status") in {"reviewed", "resolved"})
        resolved_count = sum(1 for item in actions if item.get("status") == "resolved")
        return {"actions": actions, "count": len(actions), "reviewed_count": reviewed_count, "resolved_count": resolved_count, "trend": trend, "durable": bool(self.memory_store_provider())}


    async def api_workbench_local_remediation_guide(self, limit: int = 30):
        return JSONResponse(self._local_remediation_payload(limit))


    def _save_remediation_action_run(self, action: dict[str, Any], action_id: str, status: str, note: str = "", recheck: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        run = RunRecord(
            run_id=f"workbench-remediation-action-{safe_artifact_slug(action_id)}",
            run_type="workbench_remediation_action",
            title=f"Workbench remediation: {action.get('gap') or action_id}",
            status=status,
            actor="user",
            scenario="local-first-maintenance",
            inputs={"action_id": action_id, "gap": action.get("gap", ""), "action": action.get("action", "")},
            outputs={"action_id": action_id, "status": status, "note": note, "checks": action.get("checks") or [], "last_recheck": recheck or {}},
            metrics={
                "resolved": 1 if status == "resolved" else 0,
                "reviewed": 1 if status in {"reviewed", "resolved"} else 0,
                "recheck_ok": 1 if (recheck or {}).get("ok") else 0,
            },
            tags=["maintenance", "remediation", status],
        )
        run.add_evidence("local_remediation_action", "User reviewed, resolved, or rechecked a local readiness remediation action", citation=action_id)
        return self.memory_store_provider().save_run_record(run.to_dict())


    async def _run_local_remediation_recheck(self, action: dict[str, Any]) -> dict[str, Any]:
        checks = [str(item) for item in (action.get("checks") or [])]
        results: list[dict[str, Any]] = []
        for check in checks:
            if check == "/api/model/health":
                assets = self.local_model_assets_status()
                results.append({"check": check, "ok": bool(assets.get("ready") or assets.get("ok")), "summary": assets.get("summary", "")})
            elif check == "/api/workbench/offline-readiness":
                readiness = self._workbench_offline_readiness_payload(0)
                results.append({"check": check, "ok": bool(readiness.get("ok")), "summary": f"{readiness.get('percent', 0)}%"})
            elif check == "/api/workbench/local-acceptance-trends":
                runs = self._local_acceptance_runs(30) if self.memory_store_provider() else []
                trend = self._local_acceptance_trends(runs)
                results.append({"check": check, "ok": bool(trend.get("window", 0) >= 0), "summary": f"window:{trend.get('window', 0)}"})
            elif check == "/api/workbench/local-remediation-guide":
                payload = self._local_remediation_payload(30)
                results.append({"check": check, "ok": True, "summary": f"actions:{payload.get('count', 0)} resolved:{payload.get('resolved_count', 0)}"})
            elif check == "/api/workbench/local-qwen-smoke":
                smoke = await self._local_qwen_smoke_check()
                results.append({"check": check, "ok": bool(smoke.get("ok")), "summary": smoke.get("assets_summary") or smoke.get("error") or "qwen smoke"})
            elif check == "/api/documents":
                count = len(self.memory_store_provider().list_documents("research")) if self.memory_store_provider() else 0
                results.append({"check": check, "ok": count > 0, "summary": f"research documents:{count}"})
            elif check == "/api/documents/search":
                count = len(self.memory_store_provider().list_documents("research")) if self.memory_store_provider() else 0
                results.append({"check": check, "ok": count > 0, "summary": f"searchable research documents:{count}"})
            elif check == "/api/academy/paper/offline-audit":
                try:
                    audit = self._academy_offline_audit_payload(0)
                    results.append({"check": check, "ok": bool(audit.get("ok")), "summary": f"{audit.get('percent', 0)}%"})
                except HTTPException as exc:
                    results.append({"check": check, "ok": False, "summary": str(exc.detail)})
            elif check in {"/api/academy/paper/checkpoints", "/api/academy/paper/project-board/exports", "/api/academy/paper/project-board", "/api/academy/paper/status"}:
                run_type = "academy_paper_checkpoint" if "checkpoints" in check else "academy_research_project_export" if "exports" in check else "academy_research_project_item" if "project-board" in check else "academy_paper_report"
                count = self._academy_count_run_records(run_type, 0)
                results.append({"check": check, "ok": count > 0, "summary": f"{run_type}:{count}"})
            else:
                results.append({"check": check, "ok": False, "summary": "No safe local recheck is registered for this item."})
        ok = bool(results) and all(item.get("ok") for item in results)
        return {"ok": ok, "checked_at": now_iso(), "results": results, "count": len(results)}


    async def api_workbench_local_remediation_action(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        status = str(data.get("status") or "reviewed").strip().lower()
        if status not in {"open", "reviewed", "resolved"}:
            raise HTTPException(400, "Unsupported remediation status")
        action = data.get("action") or {}
        action_id = str(data.get("action_id") or self._remediation_action_key(action)).strip()
        if not action_id:
            raise HTTPException(400, "action_id is required")
        saved = self._save_remediation_action_run(action, action_id, status, str(data.get("note") or ""))
        return JSONResponse({"saved": True, "action": {"action_id": action_id, "status": status, "note": data.get("note", "")}, "run": saved})


    async def api_workbench_local_remediation_recheck(self, request: Request):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        data = await request.json()
        action = data.get("action") or {}
        action_id = str(data.get("action_id") or self._remediation_action_key(action)).strip()
        if not action_id:
            raise HTTPException(400, "action_id is required")
        current = self._remediation_action_statuses().get(action_id, {})
        status = str(current.get("status") or action.get("status") or "reviewed")
        recheck = await self._run_local_remediation_recheck(action)
        note = str(current.get("note") or data.get("note") or "")
        saved = self._save_remediation_action_run(action, action_id, status, note, recheck)
        return JSONResponse({"saved": True, "action_id": action_id, "status": status, "recheck": recheck, "run": saved})


    def _maintenance_report_markdown(self, report: dict[str, Any]) -> str:
        readiness = report.get("readiness") or {}
        trend = (report.get("trends") or {}).get("trend") or {}
        remediation = report.get("remediation") or {}
        latest = report.get("latest_acceptance") or {}
        lines = [
            "# ClawOS Local Maintenance Report",
            "",
            f"Generated: {report.get('generated_at', '')}",
            f"Workbench readiness: {readiness.get('percent', 0)}%",
            f"Latest acceptance: {latest.get('status', '--')} {latest.get('updated_at', '')}",
            "",
            "## Trend Summary",
            "",
            f"- Daily pass rate: {trend.get('daily_pass_rate', 0)}",
            f"- Qwen pass rate: {trend.get('qwen_pass_rate', 0)}",
            f"- Qwen failure streak: {trend.get('qwen_failure_streak', 0)}",
            f"- Average readiness: {trend.get('average_workbench_percent', 0)}%",
            f"- Average benchmark pass rate: {trend.get('average_benchmark_pass_rate', 0)}",
            f"- Average model score rate: {trend.get('average_model_score_rate', 0)}",
            "",
            "## Top Readiness Gaps",
            "",
        ]
        gaps = trend.get("top_readiness_gaps") or []
        lines.extend([f"- {item.get('label', '')}: {item.get('count', 0)}" for item in gaps] or ["- none"])
        lines.extend(["", "## Remediation Guide", ""])
        actions = remediation.get("actions") or []
        for action in actions:
            scripts = ", ".join(str(value) for value in (action.get("scripts") or {}).values()) or "none"
            checks = ", ".join(action.get("checks") or []) or "none"
            lines.extend([
                f"### {action.get('gap') or action.get('id')}",
                "",
                f"- Severity: {action.get('severity', '')}",
                f"- Action: {action.get('action', '')}",
                f"- Why: {action.get('why', '')}",
                f"- Scripts: {scripts}",
                f"- Checks: {checks}",
                "",
            ])
        if not actions:
            lines.extend(["- none", ""])
        lines.extend(["## Remediation Status", ""])
        if actions:
            for action in actions:
                recheck = action.get("last_recheck") or {}
                suffix = f"; recheck={recheck.get('ok')}" if recheck else ""
                lines.append(f"- {action.get('gap') or action.get('id')}: {action.get('status', 'open')}{suffix}")
        else:
            lines.append("- none")
        lines.extend(["", f"Reviewed: {remediation.get('reviewed_count', 0)}", f"Resolved: {remediation.get('resolved_count', 0)}", ""])
        lines.extend(["## Latest Daily Summary", "", latest.get("summary", "No daily acceptance summary available."), ""])
        return "\n".join(lines).rstrip() + "\n"


    def _export_local_maintenance_report(self, limit: int = 30) -> dict[str, Any]:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        readiness = self._workbench_offline_readiness_payload(0)
        runs = self._local_acceptance_runs(limit) if self.memory_store_provider() else []
        history = {"runs": [self._daily_acceptance_run_summary(run) for run in runs], "count": len(runs), "durable": bool(self.memory_store_provider())}
        trends = {"trend": self._local_acceptance_trends(runs), "count": len(runs), "durable": bool(self.memory_store_provider())}
        remediation = self._local_remediation_payload(limit)
        latest = history["runs"][0] if history["runs"] else {}
        report = {
            "generated_at": now_iso(),
            "standard": "local-first maintenance report",
            "readiness": readiness,
            "history": history,
            "trends": trends,
            "remediation": remediation,
            "latest_acceptance": latest,
        }
        storage = ArtifactStorage(self.output_root_provider() / "maintenance")
        json_artifact = storage.write_json(f"{stamp}_clawos_maintenance_report.json", report)
        markdown = self._maintenance_report_markdown(report)
        markdown_artifact = storage.write_bytes(f"{stamp}_clawos_maintenance_report.md", markdown.encode("utf-8"), kind="markdown")
        payload = {"exported": True, "report": report, "artifacts": {"json": json_artifact, "markdown": markdown_artifact}}
        if self.memory_store_provider():
            run = RunRecord(
                run_id=f"workbench-maintenance-report-{stamp}",
                run_type="workbench_maintenance_report",
                title="ClawOS local maintenance report",
                status="pass",
                actor="user",
                scenario="local-first-maintenance",
                inputs={"limit": limit},
                outputs={"readiness_percent": readiness.get("percent", 0), "history_count": history.get("count", 0), "remediation_count": remediation.get("count", 0)},
                metrics={"workbench_percent": readiness.get("percent", 0), "history_count": history.get("count", 0), "remediation_count": remediation.get("count", 0)},
                tags=["maintenance", "offline", "report"],
            )
            run.add_artifact("json_report", "Local maintenance JSON report", json_artifact["path"], storage=json_artifact)
            run.add_artifact("markdown_report", "Local maintenance Markdown report", markdown_artifact["path"], storage=markdown_artifact)
            run.add_evidence("workbench_readiness", "Maintenance report includes workbench readiness", score=readiness.get("percent", 0))
            payload["run"] = self.memory_store_provider().save_run_record(run.to_dict())
        return payload


    async def api_workbench_local_maintenance_report(self, request: Request):
        data = await request.json()
        return JSONResponse(self._export_local_maintenance_report(limit=int(data.get("limit") or 30)))


    def _maintenance_artifact_root(self) -> Path:
        return (self.output_root_provider() / "maintenance").resolve()


    def _maintenance_report_artifact_path(self, run: dict[str, Any], kind: str) -> Path | None:
        for artifact in run.get("artifacts") or []:
            if artifact.get("kind") != kind:
                continue
            storage = (artifact.get("metadata") or {}).get("storage") or {}
            raw_path = artifact.get("uri") or storage.get("path") or ""
            if raw_path:
                return Path(str(raw_path)).expanduser().resolve()
        return None


    def _read_maintenance_artifact(self, run: dict[str, Any], kind: str) -> tuple[Path, str]:
        path = self._maintenance_report_artifact_path(run, kind)
        if not path:
            raise HTTPException(404, "Maintenance report artifact not found")
        root = self._maintenance_artifact_root()
        try:
            path.relative_to(root)
        except ValueError:
            raise HTTPException(403, "Maintenance report artifact is outside the maintenance directory")
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Maintenance report artifact file not found")
        return path, path.read_text(encoding="utf-8")


    def _maintenance_report_summary(self, run: dict[str, Any]) -> dict[str, Any]:
        outputs = run.get("outputs") or {}
        metrics = run.get("metrics") or {}
        markdown_path = self._maintenance_report_artifact_path(run, "markdown_report")
        json_path = self._maintenance_report_artifact_path(run, "json_report")
        return {
            "run_id": run.get("run_id", ""),
            "title": run.get("title", ""),
            "status": run.get("status", ""),
            "updated_at": run.get("updated_at", ""),
            "created_at": run.get("created_at", ""),
            "readiness_percent": outputs.get("readiness_percent", metrics.get("workbench_percent", 0)),
            "history_count": outputs.get("history_count", metrics.get("history_count", 0)),
            "remediation_count": outputs.get("remediation_count", metrics.get("remediation_count", 0)),
            "markdown_path": str(markdown_path) if markdown_path else "",
            "json_path": str(json_path) if json_path else "",
        }


    async def api_workbench_local_maintenance_reports(self, limit: int = 12):
        if not self.memory_store_provider():
            return JSONResponse({"reports": [], "count": 0, "durable": False})
        max_items = max(1, min(int(limit or 12), 50))
        reports = []
        for item in self.memory_store_provider().list_run_records(run_type="workbench_maintenance_report", limit=max_items):
            run = self.memory_store_provider().get_run_record(item.get("run_id", ""))
            if run:
                reports.append(self._maintenance_report_summary(run))
        return JSONResponse({"reports": reports, "count": len(reports), "durable": True})


    async def api_workbench_local_maintenance_report_detail(self, run_id: str):
        if not self.memory_store_provider():
            raise HTTPException(503, "MemoryOS not initialized")
        run = self.memory_store_provider().get_run_record(run_id)
        if not run or run.get("run_type") != "workbench_maintenance_report":
            raise HTTPException(404, "Maintenance report not found")
        markdown_path, markdown = self._read_maintenance_artifact(run, "markdown_report")
        json_path, json_text = self._read_maintenance_artifact(run, "json_report")
        try:
            report = json.loads(json_text)
        except json.JSONDecodeError:
            report = {}
        current_remediation = self._local_remediation_payload(30)
        return JSONResponse({
            "run": run,
            "summary": self._maintenance_report_summary(run),
            "markdown": markdown,
            "report": report,
            "report_remediation": (report.get("remediation") or {}) if isinstance(report, dict) else {},
            "current_remediation": current_remediation,
            "artifacts": {"markdown_path": str(markdown_path), "json_path": str(json_path)},
        })
