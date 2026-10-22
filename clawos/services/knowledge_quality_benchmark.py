from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from memoryos.memory_store import MemoryStore
from memoryos.services.retrieval import RetrievalService
from memoryos.services.vector_store import MemoryVectorStore
from services.knowledge_core_service import KnowledgeCoreService


DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "knowledge_quality_v1.json"


def _rate(successes: int, total: int) -> float:
    return round(successes / total, 4) if total else 0.0


def run_knowledge_quality_benchmark(corpus_path: str | Path = DEFAULT_CORPUS) -> dict[str, Any]:
    corpus = json.loads(Path(corpus_path).read_text(encoding="utf-8"))
    records = corpus.get("records") or []
    queries = corpus.get("queries") or []
    if len(records) < 30 or len(queries) < 30:
        raise ValueError("knowledge quality corpus requires at least 30 records and 30 queries")
    with tempfile.TemporaryDirectory() as td:
        store = MemoryStore(str(Path(td) / "benchmark.db"))
        core = KnowledgeCoreService(store)
        ids: dict[str, int] = {}
        completeness_scores = []
        for record in records:
            item = core.absorb(
                title=record["title"], statement=record["statement"], category=record["category"],
                source_ref=record["source_ref"], source_type="reviewed_corpus",
                excerpt=record["statement"], locator=KnowledgeCoreService.source_locator(record["source_ref"]),
                confidence=0.9, authority=0.9, entities=record.get("entities") or [],
                metadata={"corpus_id": record["id"], "reviewed": True},
            )
            ids[record["id"]] = int(item["id"])
            required = [
                item.get("title"), item.get("statement"), item.get("category"), item.get("status"),
                item.get("confidence"), record.get("source_ref"), record.get("entities"), item.get("current_version"),
            ]
            completeness_scores.append(sum(value not in (None, "", []) for value in required) / len(required))

        duplicate_hits = 0
        for duplicate in corpus.get("duplicates") or []:
            target_id = ids[duplicate["target"]]
            result = core.absorb(
                title=next(item["title"] for item in records if item["id"] == duplicate["target"]),
                statement=duplicate["statement"],
                category=next(item["category"] for item in records if item["id"] == duplicate["target"]),
                source_ref=duplicate["source_ref"], source_type="reviewed_duplicate", confidence=0.85,
            )
            duplicate_hits += int(result["id"] == target_id and result["absorption_outcome"] == "source_merged")

        true_positive = false_negative = false_positive = 0
        for conflict in corpus.get("conflicts") or []:
            target = next(item for item in records if item["id"] == conflict["target"])
            result = core.absorb(
                title=target["title"], statement=conflict["statement"], category=target["category"],
                source_ref=f"benchmark:conflict:{conflict['target']}", source_type="reviewed_conflict",
            )
            detected = result["absorption_outcome"] == "conflict_recorded"
            true_positive += int(detected)
            false_negative += int(not detected)
            if detected:
                core.resolve_conflict(result["conflict"]["id"], "keep_existing", reviewer="benchmark")
        for non_conflict in corpus.get("non_conflicts") or []:
            target = next(item for item in records if item["id"] == non_conflict["target"])
            result = core.absorb(
                title=non_conflict["title"], statement=non_conflict["statement"], category=target["category"],
                source_ref=f"benchmark:distinct:{non_conflict['target']}", source_type="reviewed_non_conflict",
            )
            false_positive += int(result["absorption_outcome"] == "conflict_recorded")

        vector = MemoryVectorStore(
            str(Path(td) / "benchmark.db"), provider="chroma",
            persist_dir=str(Path(td) / "chroma"), embedding_provider="hash", dim=128,
        )
        retrieval = RetrievalService(store, vector_store=vector)
        hard_queries = []
        for index, case in enumerate(queries):
            distractor = records[(index + 7) % len(records)]["title"]
            hard_queries.append({
                **case,
                "query": f"{case['query']} Distinguish this from: {distractor}.",
                "difficulty": "adversarial_distractor",
            })
        evaluation_queries = [{**case, "difficulty": "reviewed"} for case in queries] + hard_queries

        retrieval_hits = citation_hits = task_answer_hits = 0
        latencies_ms = []
        query_results = []
        for case in evaluation_queries:
            expected_id = ids[case["expected"]]
            started = time.perf_counter()
            results = retrieval.retrieve(case["query"], top_k=10, recall_k=20)
            latencies_ms.append((time.perf_counter() - started) * 1000)
            retrieved_ids = [int(item.get("knowledge_id") or 0) for item in results]
            retrieval_hit = expected_id in retrieved_ids
            expected = next((item for item in results if int(item.get("knowledge_id") or 0) == expected_id), None)
            citation_hit = bool(expected and expected.get("citation"))
            answer = core.grounded_answer(case["query"], limit=6, token_budget=1200, task_id="benchmark")
            answer_hit = (
                expected_id in answer["knowledge_ids"]
                and bool(answer["citations"])
                and answer["grounded"]
            )
            retrieval_hits += int(retrieval_hit)
            citation_hits += int(citation_hit)
            task_answer_hits += int(answer_hit)
            query_results.append({
                "query": case["query"], "expected": case["expected"], "retrieval_hit": retrieval_hit,
                "citation_hit": citation_hit, "task_answer_hit": answer_hit, "retrieved_ids": retrieved_ids,
                "difficulty": case["difficulty"], "answer_grounded": answer["grounded"],
                "answer_knowledge_ids": answer["knowledge_ids"],
                "answer_validation": answer.get("answer_validation", {}),
            })

        scoped = core.absorb(
            title="Private rotation", statement="Rotate the private workspace token every seven days.",
            category="operations", source_ref="doc:private", owner_id="alice", workspace_id="private",
        )
        public = core.absorb(
            title="Public rotation", statement="Rotate the public workspace token every thirty days.",
            category="operations", source_ref="doc:public", owner_id="alice", workspace_id="public",
        )
        private_hits = vector.search_knowledge(
            "rotate workspace token", top_k=10, owner_id="alice", workspace_id="private",
        )
        private_ids = {int(item["metadata"]["knowledge_id"]) for item in private_hits}
        scope_isolation = scoped["id"] in private_ids and public["id"] not in private_ids
        core.expire(scoped["id"], "benchmark lifecycle")
        expired_hits = vector.search_knowledge(
            "rotate private workspace token", top_k=10, owner_id="alice", workspace_id="private",
        )
        incremental_lifecycle = not expired_hits and vector.stats()["consistent"]

        absent_queries = [
            "zxq991lunarpayroll quasarobelisk", "violetenginecount neptuneforge",
            "火星紫罗兰引擎薪资鹦鹉", "quantumbanana auroraplatypus",
        ]
        abstentions = sum(
            not core.task_context_pack(query, limit=5)["evidence_sufficient"] for query in absent_queries
        )

        precision = true_positive / max(1, true_positive + false_positive)
        recall = true_positive / max(1, true_positive + false_negative)
        conflict_f1 = 2 * precision * recall / max(0.000001, precision + recall)
        metrics = {
            "ingestion_field_completeness": round(sum(completeness_scores) / len(completeness_scores), 4),
            "duplicate_merge_accuracy": _rate(duplicate_hits, len(corpus.get("duplicates") or [])),
            "retrieval_recall_at_10": _rate(retrieval_hits, len(evaluation_queries)),
            "citation_hit_rate": _rate(citation_hits, len(evaluation_queries)),
            "conflict_precision": round(precision, 4), "conflict_recall": round(recall, 4),
            "conflict_f1": round(conflict_f1, 4),
            "task_answer_success_rate": _rate(task_answer_hits, len(evaluation_queries)),
            "scope_isolation_rate": float(scope_isolation),
            "incremental_lifecycle_success": float(incremental_lifecycle),
            "unsupported_query_abstention_rate": _rate(abstentions, len(absent_queries)),
            "retrieval_p95_under_1500ms": float(
                (statistics.quantiles(latencies_ms, n=20)[18] if len(latencies_ms) >= 20 else max(latencies_ms)) < 1500
            ),
        }
        thresholds = {
            "ingestion_field_completeness": 0.95, "duplicate_merge_accuracy": 0.90,
            "retrieval_recall_at_10": 0.90, "citation_hit_rate": 0.90,
            "conflict_f1": 0.80, "task_answer_success_rate": 0.80,
            "scope_isolation_rate": 1.0, "incremental_lifecycle_success": 1.0,
            "unsupported_query_abstention_rate": 1.0, "retrieval_p95_under_1500ms": 1.0,
        }
        report = {
            "name": corpus["name"], "version": corpus.get("version"),
            "review_status": corpus.get("review_status", "unreviewed"),
            "mode": "reviewed_local_corpus_real_sqlite_chroma",
            "record_count": len(records), "query_count": len(evaluation_queries),
            "metrics": metrics, "thresholds": thresholds,
            "passed": all(metrics[name] >= threshold for name, threshold in thresholds.items()),
            "query_failures": [item for item in query_results if not item["task_answer_hit"]],
            "store_stats": core.stats(),
            "vector_stats": vector.stats(),
            "latency_ms": {
                "p50": round(statistics.median(latencies_ms), 2),
                "p95": round(statistics.quantiles(latencies_ms, n=20)[18], 2),
            },
            "truth_boundary": "Maintainer-reviewed deterministic corpus plus generated distractor variants over real SQLite and Chroma; not production user telemetry or model-graded answer preference.",
        }
        vector.close()
    return report
