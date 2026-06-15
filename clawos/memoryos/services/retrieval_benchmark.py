"""Deterministic MemoryOS retrieval benchmark."""

from __future__ import annotations

import time


class RetrievalBenchmark:
    """Measure retrieval quality using frozen query/expected-id cases."""

    def __init__(self, store, retrieval_service):
        self._store = store
        self._retrieval = retrieval_service

    def run(self, cases, top_k=5, name="memory-retrieval", created_by="system"):
        top_k = max(1, min(int(top_k or 5), 50))
        evaluated = []
        reciprocal_ranks = []
        recalls = []
        precisions = []
        hits = []
        latencies = []

        for case in cases or []:
            query = str(case.get("query", "") or "").strip()
            expected = {str(item) for item in case.get("expected_ids", [])}
            if not query or not expected:
                continue
            started = time.perf_counter()
            results = self._retrieval.retrieve(query, top_k=top_k)
            latency_ms = round((time.perf_counter() - started) * 1000, 3)
            retrieved = [str(item.get("id")) for item in results]
            matched = [item for item in retrieved if item in expected]
            rank = next((index + 1 for index, item in enumerate(retrieved) if item in expected), 0)
            recall = len(set(matched)) / len(expected)
            precision = len(matched) / max(1, len(retrieved))
            reciprocal_rank = 1.0 / rank if rank else 0.0
            recalls.append(recall)
            precisions.append(precision)
            reciprocal_ranks.append(reciprocal_rank)
            hits.append(1.0 if rank else 0.0)
            latencies.append(latency_ms)
            evaluated.append({
                "query": query,
                "expected_ids": sorted(expected),
                "retrieved_ids": retrieved,
                "matched_ids": matched,
                "recall": round(recall, 4),
                "precision": round(precision, 4),
                "reciprocal_rank": round(reciprocal_rank, 4),
                "latency_ms": latency_ms,
            })

        metrics = {
            f"recall_at_{top_k}": self._average(recalls),
            f"precision_at_{top_k}": self._average(precisions),
            "mrr": self._average(reciprocal_ranks),
            "hit_rate": self._average(hits),
            "latency_p50_ms": self._percentile(latencies, 50),
            "latency_p95_ms": self._percentile(latencies, 95),
        }
        return self._store.record_retrieval_evaluation(
            name=name,
            top_k=top_k,
            metrics=metrics,
            cases=evaluated,
            created_by=created_by,
        )

    @staticmethod
    def _average(values):
        return round(sum(values) / len(values), 4) if values else 0.0

    @staticmethod
    def _percentile(values, percentile):
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((percentile / 100) * (len(ordered) - 1)))))
        return round(ordered[index], 3)
