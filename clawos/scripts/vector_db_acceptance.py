#!/usr/bin/env python3
"""Enterprise acceptance for the ClawOS vector database layer."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from memoryos.services.retrieval import CrossEncoderReranker, RetrievalService
from memoryos.services.vector_store import MemoryVectorStore


CASES: list[dict[str, Any]] = [
    {
        "scenario": "paper",
        "name": "journal_paper_semantic_recall",
        "query": "scholarly evidence faithfulness citation drift reproducible RAG experiment",
        "expected_slug": "paper_fidelity",
        "items": [
            {
                "slug": "paper_fidelity",
                "title": "Citation-Faithful RAG Evaluation for Journal Papers",
                "content": (
                    "A journal-grade paper review on retrieval augmented generation, citation fidelity, "
                    "evidence chain alignment, attribution drift, ablation controls, reproducible "
                    "experimental protocol, limitations, and human evaluation."
                ),
            },
            {
                "slug": "paper_design",
                "title": "Console Typography and PDF Layout",
                "content": "Visual design notes about headings, fonts, margins, contrast, and report pagination.",
            },
            {
                "slug": "paper_market",
                "title": "Business Model Canvas",
                "content": "Commercial planning material about pricing, channels, users, and market entry.",
            },
        ],
    },
    {
        "scenario": "notes",
        "name": "bidirectional_note_graph_recall",
        "query": "connect source notes saved reports backlinks wikilinks semantic knowledge graph",
        "expected_slug": "note_graph",
        "items": [
            {
                "slug": "note_graph",
                "title": "Bidirectional Markdown Knowledge Graph",
                "content": (
                    "A note library design with Markdown wikilinks, backlinks, source-document references, "
                    "semantic graph edges, exported note checks, graph quality gates, and follow-up actions "
                    "from saved reading reports."
                ),
            },
            {
                "slug": "note_queue",
                "title": "Background Task Queue",
                "content": "Worker retries, cancellation flags, recovery, and audit events for long-running jobs.",
            },
            {
                "slug": "note_spreadsheet",
                "title": "Quarterly Spreadsheet Template",
                "content": "Spreadsheet formula templates and KPI tables for office reporting.",
            },
        ],
    },
    {
        "scenario": "code",
        "name": "code_worker_runtime_recall",
        "query": "implementation details for long running job cancellation retry recovery idempotent worker",
        "expected_slug": "worker_runtime",
        "items": [
            {
                "slug": "worker_runtime",
                "title": "Task Worker Runtime Implementation",
                "content": (
                    "Implementation design for a durable background worker: queue claiming, cancellation "
                    "tokens, retry policy, restart recovery, idempotent status updates, failure envelopes, "
                    "and event audit logs."
                ),
            },
            {
                "slug": "code_sidebar",
                "title": "Sidebar Interaction Styles",
                "content": "CSS behavior for compact navigation, icon buttons, hover states, and responsive widths.",
            },
            {
                "slug": "code_provider",
                "title": "Model Provider Settings",
                "content": "API mode, local mode, offline mode, model names, base URLs, and secret masking.",
            },
        ],
    },
    {
        "scenario": "office",
        "name": "office_document_recall",
        "query": "meeting action items executive summary quarterly KPI spreadsheet owners due dates",
        "expected_slug": "office_pack",
        "items": [
            {
                "slug": "office_pack",
                "title": "Office Meeting and KPI Deliverable Pack",
                "content": (
                    "A management-ready office pack covering meeting minutes, decisions, action items, "
                    "owners, due dates, quarterly KPI spreadsheet formulas, executive summary tables, "
                    "and follow-up deliverables."
                ),
            },
            {
                "slug": "office_embedding",
                "title": "Embedding Model Selection",
                "content": "Model notes about Qwen embeddings, rerankers, dimensions, and vector stores.",
            },
            {
                "slug": "office_paper",
                "title": "Paper Reading Worksheet",
                "content": "Research study questions, concepts, limitations, and comprehension checks.",
            },
        ],
    },
]


def model_file_report(model_path: Path, kind: str = "embedding") -> dict[str, Any]:
    required = [
        "config.json",
        "model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
    ]
    if kind == "embedding":
        required.extend(["modules.json", "config_sentence_transformers.json", "1_Pooling/config.json"])
    files = {name: (model_path / name).exists() for name in required}
    total_bytes = sum(item.stat().st_size for item in model_path.rglob("*") if item.is_file()) if model_path.exists() else 0
    return {"path": str(model_path), "required_files": files, "total_bytes": total_bytes, "complete": all(files.values())}


def seed_store(store: MemoryStore) -> dict[str, str]:
    slug_to_id: dict[str, str] = {}
    for case in CASES:
        for item in case["items"]:
            row = store.add_knowledge(
                item["title"],
                item["content"],
                category=case["scenario"],
                source=f"vector-db-acceptance/{case['name']}",
                tags=[case["scenario"], item["slug"]],
                confidence=0.95 if item["slug"] == case["expected_slug"] else 0.55,
            )
            slug_to_id[item["slug"]] = f"kw_{row['id']}"
    return slug_to_id


def normalize_id(value: str) -> set[str]:
    text = str(value)
    if text.startswith("kw_"):
        return {text, text[3:]}
    if text.isdigit():
        return {text, f"kw_{text}"}
    return {text}


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    model_path = Path(args.embedding_model_path).expanduser().resolve()
    reranker_path = Path(args.reranker_model_path).expanduser().resolve()
    model_files = model_file_report(model_path, "embedding")
    reranker_files = model_file_report(reranker_path, "reranker")
    if args.embedding_provider != "hash" and not model_files["complete"]:
        return {
            "ok": False,
            "error": "embedding_model_incomplete",
            "model_files": model_files,
        }
    if args.reranker_provider != "none" and not reranker_files["complete"]:
        return {
            "ok": False,
            "error": "reranker_model_incomplete",
            "model_files": model_files,
            "reranker_files": reranker_files,
        }

    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    db_path = temp_path / "memory.db"
    chroma_dir = temp_path / "chroma"
    case_results: list[dict[str, Any]] = []
    vectors = None
    try:
        store = MemoryStore(str(db_path))
        slug_to_id = seed_store(store)
        vectors = MemoryVectorStore(
            str(db_path),
            provider="chroma",
            persist_dir=str(chroma_dir),
            embedding_provider=args.embedding_provider,
            embedding_model_path=str(model_path),
            embedding_dim=args.embedding_dim,
        )
        vectors.refresh()
        stats = vectors.stats()
        reranker = None
        if args.reranker_provider != "none":
            reranker = CrossEncoderReranker(str(reranker_path), provider=args.reranker_provider)
        retrieval = RetrievalService(store, vectors, reranker=reranker)

        for case in CASES:
            expected_id = slug_to_id[case["expected_slug"]]
            started_case = time.perf_counter()
            direct = vectors.search(case["query"], top_k=args.recall_k, min_score=0.0)
            hybrid = retrieval.retrieve(case["query"], top_k=args.top_k)
            reranked = retrieval.semantic_rerank(case["query"], recall_k=args.recall_k, top_k=args.top_k, min_score=0.0)
            elapsed_ms = round((time.perf_counter() - started_case) * 1000, 3)
            direct_ids = [str(item.get("id")) for item in direct]
            hybrid_ids = [str(item.get("id")) for item in hybrid]
            rerank_ids = [str(item.get("id")) for item in reranked]
            direct_hit = any(normalize_id(item).intersection({expected_id}) for item in direct_ids)
            hybrid_hit = any(normalize_id(item).intersection({expected_id}) for item in hybrid_ids)
            rerank_hit = any(normalize_id(item).intersection({expected_id}) for item in rerank_ids)
            rank = next(
                (index + 1 for index, item in enumerate(direct_ids) if normalize_id(item).intersection({expected_id})),
                0,
            )
            rerank_rank = next(
                (index + 1 for index, item in enumerate(rerank_ids) if normalize_id(item).intersection({expected_id})),
                0,
            )
            case_results.append({
                "scenario": case["scenario"],
                "name": case["name"],
                "expected_id": expected_id,
                "direct_ids": direct_ids,
                "hybrid_ids": hybrid_ids,
                "rerank_ids": rerank_ids,
                "direct_hit": direct_hit,
                "hybrid_hit": hybrid_hit,
                "rerank_hit": rerank_hit,
                "direct_rank": rank,
                "rerank_rank": rerank_rank,
                "latency_ms": elapsed_ms,
                "top_direct": [
                    {
                        "id": item.get("id"),
                        "title": item.get("metadata", {}).get("title", ""),
                        "score": item.get("score"),
                    }
                    for item in direct[:5]
                ],
                "top_reranked": [
                    {
                        "id": item.get("id"),
                        "title": item.get("title", ""),
                        "score": item.get("score"),
                        "rerank_score": item.get("rerank_score"),
                    }
                    for item in reranked[:5]
                ],
            })
        vectors.close()
        vectors = MemoryVectorStore(
            str(db_path),
            provider="chroma",
            persist_dir=str(chroma_dir),
            embedding_provider=args.embedding_provider,
            embedding_model_path=str(model_path),
            embedding_dim=args.embedding_dim,
        )
        persisted_stats = vectors.stats()
        persisted_hits = vectors.search(CASES[0]["query"], top_k=args.top_k, min_score=0.0)
    finally:
        if vectors is not None:
            vectors.close()
        temp_dir.cleanup()

    direct_hits = [1.0 if item["direct_hit"] else 0.0 for item in case_results]
    hybrid_hits = [1.0 if item["hybrid_hit"] else 0.0 for item in case_results]
    rerank_hits = [1.0 if item["rerank_hit"] else 0.0 for item in case_results]
    reciprocal = [(1.0 / item["direct_rank"]) if item["direct_rank"] else 0.0 for item in case_results]
    rerank_reciprocal = [(1.0 / item["rerank_rank"]) if item["rerank_rank"] else 0.0 for item in case_results]
    latencies = sorted(item["latency_ms"] for item in case_results)
    metrics = {
        f"direct_recall_at_{args.recall_k}": round(sum(direct_hits) / len(direct_hits), 4),
        f"hybrid_recall_at_{args.top_k}": round(sum(hybrid_hits) / len(hybrid_hits), 4),
        f"rerank_recall_at_{args.top_k}": round(sum(rerank_hits) / len(rerank_hits), 4),
        "direct_mrr": round(sum(reciprocal) / len(reciprocal), 4),
        "rerank_mrr": round(sum(rerank_reciprocal) / len(rerank_reciprocal), 4),
        "latency_p50_ms": latencies[len(latencies) // 2],
        "latency_p95_ms": latencies[-1],
    }
    ok = (
        stats.get("provider") == "chroma"
        and stats.get("embedding_provider") == args.embedding_provider
        and stats.get("embedding_dim") == args.embedding_dim
        and metrics[f"direct_recall_at_{args.recall_k}"] >= args.min_recall
        and metrics[f"hybrid_recall_at_{args.top_k}"] >= args.min_recall
        and metrics[f"rerank_recall_at_{args.top_k}"] >= args.min_recall
        and persisted_stats.get("vector_count") == stats.get("vector_count")
        and bool(persisted_hits)
    )
    return {
        "ok": ok,
        "model_files": model_files,
        "reranker_files": reranker_files,
        "stats": stats,
        "persisted_stats": persisted_stats,
        "persisted_probe_ids": [item.get("id") for item in persisted_hits[:5]],
        "benchmark": {
            "name": "vector-db-qwen3-chroma-acceptance",
            "case_count": len(CASES),
            "top_k": args.top_k,
            "recall_k": args.recall_k,
            "min_recall": args.min_recall,
            "metrics": metrics,
        },
        "cases": case_results,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-provider", default="qwen3")
    parser.add_argument("--embedding-model-path", default=str(REPO_ROOT / "tools" / "models" / "qwen3-embedding-0.6b"))
    parser.add_argument("--embedding-dim", type=int, default=1024)
    parser.add_argument("--reranker-provider", default="qwen3")
    parser.add_argument("--reranker-model-path", default=str(REPO_ROOT / "tools" / "models" / "qwen3-reranker-0.6b"))
    parser.add_argument("--recall-k", type=int, default=30)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--out", default="output/reports/vector_db_acceptance.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_acceptance(args)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        metrics = result.get("benchmark", {}).get("metrics", {})
        print(
            "Vector DB acceptance: "
            f"ok={result.get('ok')} provider={result.get('stats', {}).get('provider')} "
            f"embedding={result.get('stats', {}).get('embedding_provider')} "
            f"dim={result.get('stats', {}).get('embedding_dim')} "
            f"direct_recall={metrics.get(f'direct_recall_at_{args.recall_k}')} "
            f"hybrid_recall={metrics.get(f'hybrid_recall_at_{args.top_k}')} "
            f"rerank_recall={metrics.get(f'rerank_recall_at_{args.top_k}')} "
            f"rerank_mrr={metrics.get('rerank_mrr')}"
        )
        if args.out:
            print(f"Report: {args.out}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
