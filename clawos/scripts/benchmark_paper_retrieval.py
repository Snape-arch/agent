#!/usr/bin/env python3
"""Benchmark the real local embedding and reranker models on scholarly evidence retrieval."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.services.retrieval import CrossEncoderReranker
from memoryos.services.vector_store import SentenceTransformerEncoder


def _rank_embeddings(encoder, query: str, candidates: list[dict]) -> list[dict]:
    vectors = np.asarray(encoder.embed_many([query] + [item["text"] for item in candidates]), dtype=float)
    scores = vectors[1:] @ vectors[0]
    return sorted(
        [{**item, "embedding_score": round(float(score), 6)} for item, score in zip(candidates, scores)],
        key=lambda item: item["embedding_score"],
        reverse=True,
    )


def evaluate(dataset: dict, encoder, reranker) -> dict:
    cases = []
    embedding_latencies = []
    rerank_latencies = []
    for case in dataset["cases"]:
        started = time.perf_counter()
        embedded = _rank_embeddings(encoder, case["query"], case["candidates"])
        embedding_latencies.append((time.perf_counter() - started) * 1000)
        embed_rank = next(index for index, item in enumerate(embedded, 1) if item["id"] == case["gold"])

        started = time.perf_counter()
        reranked = reranker.rerank(case["query"], embedded, top_k=len(embedded))
        rerank_latencies.append((time.perf_counter() - started) * 1000)
        rerank_rank = next(index for index, item in enumerate(reranked, 1) if item["id"] == case["gold"])
        cases.append({
            "id": case["id"],
            "embedding_rank": embed_rank,
            "reranker_rank": rerank_rank,
            "embedding_top": embedded[0]["id"],
            "reranker_top": reranked[0]["id"],
        })
    count = len(cases)
    metrics = {
        "cases": count,
        "embedding_recall_at_3": round(sum(item["embedding_rank"] <= 3 for item in cases) / count, 4),
        "embedding_mrr": round(sum(1 / item["embedding_rank"] for item in cases) / count, 4),
        "embedding_ndcg_at_4": round(sum(1 / math.log2(item["embedding_rank"] + 1) for item in cases) / count, 4),
        "reranker_hit_at_1": round(sum(item["reranker_rank"] == 1 for item in cases) / count, 4),
        "reranker_mrr": round(sum(1 / item["reranker_rank"] for item in cases) / count, 4),
        "embedding_latency_p50_ms": round(statistics.median(embedding_latencies), 2),
        "embedding_latency_p95_ms": round(sorted(embedding_latencies)[max(0, math.ceil(count * 0.95) - 1)], 2),
        "reranker_latency_p50_ms": round(statistics.median(rerank_latencies), 2),
        "reranker_latency_p95_ms": round(sorted(rerank_latencies)[max(0, math.ceil(count * 0.95) - 1)], 2),
    }
    gates = {
        "embedding_recall_at_3_95": metrics["embedding_recall_at_3"] >= 0.95,
        "embedding_mrr_85": metrics["embedding_mrr"] >= 0.85,
        "reranker_hit_at_1_90": metrics["reranker_hit_at_1"] >= 0.90,
        "reranker_mrr_95": metrics["reranker_mrr"] >= 0.95,
    }
    return {"metrics": metrics, "gates": gates, "passed": all(gates.values()), "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "benchmarks" / "paper_retrieval_gold_v1.json"))
    parser.add_argument("--embedding-model", default=str(REPO_ROOT / "tools" / "models" / "qwen3-embedding-0.6b"))
    parser.add_argument("--reranker-model", default=str(REPO_ROOT / "tools" / "models" / "qwen3-reranker-0.6b"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    embedding_path = Path(args.embedding_model).resolve()
    reranker_path = Path(args.reranker_model).resolve()
    if not embedding_path.is_dir() or not reranker_path.is_dir():
        print(json.dumps({"passed": False, "error": "local model directory missing", "embedding_model": str(embedding_path), "reranker_model": str(reranker_path)}, ensure_ascii=False, indent=2))
        return 2
    started = time.perf_counter()
    result = evaluate(
        dataset,
        SentenceTransformerEncoder(str(embedding_path), device=args.device),
        CrossEncoderReranker(str(reranker_path), device=args.device),
    )
    payload = {
        "schema": "clawos.paper-retrieval-benchmark.v1",
        "dataset": dataset["schema"],
        "real_models": True,
        "embedding_model": embedding_path.name,
        "reranker_model": reranker_path.name,
        "device": args.device,
        "duration_seconds": round(time.perf_counter() - started, 2),
        **result,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
