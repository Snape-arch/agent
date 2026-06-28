#!/usr/bin/env python3
"""Long-paper RAG acceptance: PDF chunking, citation-aware rerank, and corpus stress."""

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

from memoryos.document_ingestion import ingest_file
from memoryos.memory_store import MemoryStore
from memoryos.services.retrieval import CrossEncoderReranker, RetrievalService
from memoryos.services.vector_store import MemoryVectorStore


TARGETS = [
    {
        "name": "citation_fidelity",
        "query": "Which page explains citation fidelity, attribution drift, evidence chain alignment, and reproducible RAG evaluation?",
        "page": 4,
        "must": ["citation fidelity", "attribution drift", "evidence chain alignment"],
    },
    {
        "name": "ablation_protocol",
        "query": "Find the paper section about ablation controls, reproducible protocol, baseline retriever, and generator evaluation.",
        "page": 8,
        "must": ["ablation controls", "reproducible protocol", "baseline retriever"],
    },
    {
        "name": "limitations_human_review",
        "query": "Where does the paper discuss limitations, human review, annotation disagreement, and evidence audit?",
        "page": 12,
        "must": ["limitations", "human review", "annotation disagreement"],
    },
]


def create_long_pdf(path: Path, pages: int = 16) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    target_text = {
        4: (
            "Citation fidelity section. This page defines citation fidelity, attribution drift, "
            "evidence chain alignment, source-grounded claims, and reproducible RAG evaluation. "
            "The method checks whether generated statements are supported by retrieved passages."
        ),
        8: (
            "Ablation protocol section. This page describes ablation controls, reproducible protocol, "
            "baseline retriever, generator evaluation, retrieval depth, reranker comparisons, and "
            "statistical reporting for journal-grade experiments."
        ),
        12: (
            "Limitations and human review section. This page discusses limitations, human review, "
            "annotation disagreement, evidence audit, citation verification, and failure taxonomy."
        ),
    }
    filler = (
        "This synthetic research page studies personal agent workbenches, long-term memory, "
        "document ingestion, vector indexing, note export, and workflow instrumentation. "
    )
    for page in range(1, pages + 1):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, height - 72, f"ClawOS Long RAG Paper - Page {page}")
        c.setFont("Helvetica", 9)
        text = target_text.get(page, filler * 3)
        lines = []
        paragraph = (text + " " + filler * 8).split()
        line = ""
        for word in paragraph:
            if len(line) + len(word) > 92:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)
        y = height - 100
        for line in lines[:48]:
            c.drawString(72, y, line)
            y -= 12
        c.showPage()
    c.save()


def add_distractors(store: MemoryStore, count: int) -> None:
    topics = [
        "office spreadsheet meeting minutes quarterly KPI owner due date",
        "frontend sidebar responsive layout icon button visual density",
        "background worker cancellation retry recovery audit queue",
        "business plan market channel pricing customer interview",
        "learning flashcards spaced repetition mastery evidence",
        "markdown backlinks graph export wikilinks note topology",
        "model provider api local mode qwen deepseek configuration",
    ]
    for index in range(count):
        topic = topics[index % len(topics)]
        store.add_knowledge(
            title=f"Distractor Corpus Note {index:04d}",
            content=(
                f"{topic}. This distractor is intentionally unrelated to the target journal "
                f"paper citation section. Corpus pressure item {index}. "
            ) * 3,
            category="stress",
            source=f"stress:distractor:{index}",
            tags=["stress", "distractor"],
            confidence=0.35,
        )


def normalize_id(value: Any) -> set[str]:
    text = str(value)
    if text.startswith("kw_"):
        return {text, text[3:]}
    if text.isdigit():
        return {text, f"kw_{text}"}
    return {text}


def page_from_citation(citation: str) -> int:
    marker = "#page="
    text = str(citation or "")
    if marker not in text:
        return 0
    tail = text.split(marker, 1)[1]
    digits = ""
    for char in tail:
        if char.isdigit():
            digits += char
        else:
            break
    return int(digits or 0)


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    embedding_path = Path(args.embedding_model_path).expanduser().resolve()
    reranker_path = Path(args.reranker_model_path).expanduser().resolve()
    temp_dir = tempfile.TemporaryDirectory()
    temp = Path(temp_dir.name)
    db_path = temp / "memory.db"
    upload_dir = temp / "uploads"
    pdf_path = temp / "long_rag_paper.pdf"
    vectors = None
    try:
        create_long_pdf(pdf_path, pages=args.pages)
        store = MemoryStore(str(db_path))
        imported = ingest_file(store, upload_dir, pdf_path, title="ClawOS Long RAG Paper", category="research")
        citation_sample = store.get_document_chunks(imported["id"], 1)[0].get("citation") if imported.get("chunk_count") else ""
        add_distractors(store, args.distractors)
        vectors = MemoryVectorStore(
            str(db_path),
            provider="chroma",
            persist_dir=str(temp / "chroma"),
            embedding_provider="qwen3",
            embedding_model_path=str(embedding_path),
            embedding_dim=1024,
        )
        vectors.refresh()
        reranker = CrossEncoderReranker(str(reranker_path), provider="qwen3")
        retrieval = RetrievalService(store, vectors, reranker=reranker)
        stats = vectors.stats()

        case_results = []
        for target in TARGETS:
            target_page = int(target["page"])
            vector_hits = [
                {
                    "id": item.get("id"),
                    "title": item.get("metadata", {}).get("title", ""),
                    "citation": item.get("metadata", {}).get("source", ""),
                    "score": item.get("score"),
                }
                for item in vectors.search(target["query"], top_k=args.recall_k, min_score=0.0)
            ]
            reranked = retrieval.semantic_rerank(target["query"], recall_k=args.recall_k, top_k=args.top_k, min_score=0.0)
            vector_pages = [page_from_citation(item.get("citation", "")) for item in vector_hits]
            rerank_pages = [page_from_citation(item.get("citation", "")) for item in reranked]
            case_results.append({
                "name": target["name"],
                "query": target["query"],
                "expected_page": target_page,
                "vector_pages": vector_pages,
                "rerank_pages": rerank_pages,
                "vector_hit": target_page in vector_pages,
                "rerank_hit": target_page in rerank_pages,
                "rerank_rank": (rerank_pages.index(target_page) + 1) if target_page in rerank_pages else 0,
                "top_reranked": [
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "citation": item.get("citation"),
                        "rerank_score": item.get("rerank_score"),
                    }
                    for item in reranked
                ],
            })
        vectors.close()
        vectors = MemoryVectorStore(
            str(db_path),
            provider="chroma",
            persist_dir=str(temp / "chroma"),
            embedding_provider="qwen3",
            embedding_model_path=str(embedding_path),
            embedding_dim=1024,
        )
        persisted = vectors.stats()
    finally:
        if vectors is not None:
            vectors.close()
        temp_dir.cleanup()

    vector_hits = [1.0 if item["vector_hit"] else 0.0 for item in case_results]
    rerank_hits = [1.0 if item["rerank_hit"] else 0.0 for item in case_results]
    rerank_rr = [(1.0 / item["rerank_rank"]) if item["rerank_rank"] else 0.0 for item in case_results]
    metrics = {
        f"vector_recall_at_{args.recall_k}": round(sum(vector_hits) / len(vector_hits), 4),
        f"rerank_recall_at_{args.top_k}": round(sum(rerank_hits) / len(rerank_hits), 4),
        "rerank_mrr": round(sum(rerank_rr) / len(rerank_rr), 4),
    }
    ok = (
        imported.get("chunk_count", 0) >= args.pages
        and stats.get("vector_count", 0) >= args.distractors + imported.get("chunk_count", 0)
        and persisted.get("vector_count") == stats.get("vector_count")
        and metrics[f"vector_recall_at_{args.recall_k}"] >= args.min_recall
        and metrics[f"rerank_recall_at_{args.top_k}"] >= args.min_recall
    )
    return {
        "ok": ok,
        "document": {
            "page_count": imported.get("metadata", {}).get("page_count"),
            "chunk_count": imported.get("chunk_count"),
            "citation_sample": citation_sample,
        },
        "corpus": {
            "distractors": args.distractors,
            "vector_count": stats.get("vector_count"),
            "persisted_vector_count": persisted.get("vector_count"),
        },
        "benchmark": {
            "name": "paper-rag-citation-rerank-stress",
            "pages": args.pages,
            "recall_k": args.recall_k,
            "top_k": args.top_k,
            "metrics": metrics,
        },
        "cases": case_results,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--embedding-model-path", default=str(REPO_ROOT / "tools" / "models" / "qwen3-embedding-0.6b"))
    parser.add_argument("--reranker-model-path", default=str(REPO_ROOT / "tools" / "models" / "qwen3-reranker-0.6b"))
    parser.add_argument("--pages", type=int, default=16)
    parser.add_argument("--distractors", type=int, default=320)
    parser.add_argument("--recall-k", type=int, default=30)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--out", default="output/reports/paper_rag_acceptance.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run(args)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        metrics = result.get("benchmark", {}).get("metrics", {})
        print(
            "Paper RAG acceptance: "
            f"ok={result.get('ok')} pages={result.get('document', {}).get('page_count')} "
            f"chunks={result.get('document', {}).get('chunk_count')} "
            f"vector_count={result.get('corpus', {}).get('vector_count')} "
            f"vector_recall={metrics.get(f'vector_recall_at_{args.recall_k}')} "
            f"rerank_recall={metrics.get(f'rerank_recall_at_{args.top_k}')} "
            f"rerank_mrr={metrics.get('rerank_mrr')}"
        )
        if args.out:
            print(f"Report: {args.out}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
