#!/usr/bin/env python3
"""Deterministic enterprise acceptance for paper intelligence and citation gates."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from services.paper_intelligence_service import PaperIntelligenceService


def evaluate(dataset: dict) -> dict:
    with tempfile.TemporaryDirectory() as td:
        store = MemoryStore(str(Path(td) / "acceptance.db"))
        ids = {}
        for paper in dataset["papers"]:
            document = store.add_document(
                title=paper["title"],
                filename=f"{paper['key']}.pdf",
                file_hash=paper["key"],
                category="research",
                metadata={"structure": {"references": paper.get("references", [])}},
            )
            ids[paper["key"]] = int(document["id"])
            for index, content in enumerate(paper["chunks"], 1):
                store.add_document_chunk(document["id"], index, content, f"doc:{document['id']}#page={index}&chunk=1")

        service = PaperIntelligenceService(store)
        claim_rows = []
        for item in dataset["claims"]:
            document_id = ids[item["paper"]]
            result = service.align_claims([item["claim"]], [document_id], threshold=0.30)
            alignment = result["alignments"][0]
            expected = f"doc:{document_id}#page={item['chunk']}&chunk=1"
            claim_rows.append({
                "paper": item["paper"],
                "claim": item["claim"],
                "expected": expected,
                "actual": alignment.get("citation", ""),
                "top1_correct": alignment.get("citation") == expected,
                "supported": alignment.get("status") == "supported",
                "support_score": alignment.get("support_score", 0),
            })

        analyses = [service.analyze_document(document_id) for document_id in ids.values()]
        comparison = service.compare_documents(list(ids.values()))
        top1_accuracy = sum(item["top1_correct"] for item in claim_rows) / len(claim_rows)
        supported_rate = sum(item["supported"] for item in claim_rows) / len(claim_rows)
        structure_checks = []
        for analysis in analyses:
            checks = analysis["quality"]["checks"]
            structure_checks.extend([
                checks["has_methodology"], checks["has_experiments"], checks["has_findings"],
                checks["has_limitations"], checks["has_references"],
                analysis["quality"]["table_count"] > 0,
                analysis["quality"]["formula_count"] > 0,
            ])
        structure_accuracy = sum(structure_checks) / len(structure_checks)
        contradiction_recall = 1.0 if comparison["potential_contradictions"] else 0.0
        page_traceability = sum("#page=" in item["actual"] and "&chunk=" in item["actual"] for item in claim_rows) / len(claim_rows)
        metrics = {
            "claim_to_citation_top1_accuracy": round(top1_accuracy, 4),
            "supported_claim_rate": round(supported_rate, 4),
            "structured_extraction_accuracy": round(structure_accuracy, 4),
            "contradiction_candidate_recall": contradiction_recall,
            "page_chunk_traceability": round(page_traceability, 4),
            "papers": len(analyses),
            "claims": len(claim_rows),
        }
        gates = {
            "claim_to_citation_accuracy_90": top1_accuracy >= 0.90,
            "supported_claim_rate_90": supported_rate >= 0.90,
            "structured_extraction_90": structure_accuracy >= 0.90,
            "contradiction_recall_90": contradiction_recall >= 0.90,
            "page_chunk_traceability_100": page_traceability == 1.0,
        }
        score = round(
            top1_accuracy * 35 + supported_rate * 20 + structure_accuracy * 20
            + contradiction_recall * 15 + page_traceability * 10,
            2,
        )
        return {
            "schema": "clawos.paper-intelligence-acceptance.v1",
            "dataset": dataset["schema"],
            "score": score,
            "enterprise_gate": score >= 90 and all(gates.values()),
            "metrics": metrics,
            "gates": gates,
            "claim_results": claim_rows,
            "contradiction_candidates": len(comparison["potential_contradictions"]),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "benchmarks" / "paper_claim_citation_gold_v1.json"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    started = time.perf_counter()
    payload = evaluate(dataset)
    payload["duration_seconds"] = round(time.perf_counter() - started, 3)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["enterprise_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
