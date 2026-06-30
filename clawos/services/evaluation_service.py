from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime_records import run_from_acceptance_report


class EvaluationService:
    """Evaluation boundary for complex-task reports and failure-case capture."""

    def __init__(self, output_root: str | Path):
        self.output_root = Path(output_root).expanduser().resolve()

    def latest_deepseek_qwen(self) -> dict[str, Any]:
        report_path = (self.output_root / "deepseek_hybrid_rag_acceptance.json").resolve()
        if self.output_root != report_path and self.output_root not in report_path.parents:
            raise ValueError("Report path outside output root")
        if not report_path.exists():
            return {
                "found": False,
                "report_path": str(report_path),
                "message": "No DeepSeek+Qwen acceptance report found under output.",
                "run_record": None,
                "failure_library": [],
            }
        data = json.loads(report_path.read_text(encoding="utf-8"))
        benchmark = data.get("benchmark") or {}
        metrics = benchmark.get("metrics") or {}
        cases = []
        for case in data.get("cases") or []:
            cases.append({
                "scenario": case.get("scenario", ""),
                "name": case.get("name", ""),
                "pass": bool(case.get("pass")),
                "citation_hit": bool(case.get("citation_hit")),
                "latency_ms": case.get("latency_ms", 0),
                "vector_rank": case.get("vector_rank", 0),
                "rerank_rank": case.get("rerank_rank", 0),
                "failure_reason": case.get("failure_reason", ""),
            })
        run_record = run_from_acceptance_report(data, str(report_path))
        return {
            "found": True,
            "report_path": str(report_path),
            "ok": bool(data.get("ok")),
            "model": data.get("model", ""),
            "benchmark": {
                "name": benchmark.get("name", ""),
                "case_count": benchmark.get("case_count", len(cases)),
                "metrics": {
                    "pass_rate": metrics.get("pass_rate", 0),
                    "passed_count": metrics.get("passed_count", 0),
                    "failed_count": metrics.get("failed_count", 0),
                    "citation_hit_rate": metrics.get("citation_hit_rate", 0),
                    "judge_grounded_rate": metrics.get("judge_grounded_rate", 0),
                    "latency_p50_ms": metrics.get("latency_p50_ms", 0),
                    "latency_p95_ms": metrics.get("latency_p95_ms", 0),
                    "by_scenario": metrics.get("by_scenario") or {},
                },
            },
            "cases": cases,
            "run_record": run_record,
            "failure_library": run_record["failure_cases"],
        }
