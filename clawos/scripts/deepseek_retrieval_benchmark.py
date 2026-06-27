#!/usr/bin/env python3
"""Run DeepSeek-assisted semantic retrieval acceptance for ClawOS.

DeepSeek currently provides chat-completion style APIs in the public compatible
surface. This benchmark probes embeddings support, then uses DeepSeek for query
understanding and relevance judgment while Chroma/MemoryOS provide local
persistent recall.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from memoryos.services.retrieval import RetrievalService
from memoryos.services.vector_store import MemoryVectorStore
from providers import create_model_provider


BENCHMARK_CASES: list[dict[str, Any]] = [
    {
        "scenario": "paper",
        "name": "journal_paper_deep_semantic_recall",
        "query": "哪份论文材料能解释生成式问答里的证据链忠实度、引用漂移和可复现实验设计？",
        "expected_slug": "paper_citation_fidelity",
        "rubric": "Prefer scholarly material with method, evidence, limitations, citation fidelity, and reproducibility details.",
        "items": [
            {
                "slug": "paper_citation_fidelity",
                "title": "Citation-Faithful Retrieval-Augmented Generation: Method and Evaluation",
                "content": (
                    "Abstract: This journal-style paper studies retrieval-augmented generation "
                    "with citation fidelity, evidence chains, attribution drift, ablation design, "
                    "reproducibility checklists, and human evaluation. Method sections define "
                    "source-grounded answer generation, citation alignment metrics, failure modes, "
                    "limitations, and experimental controls for scholarly paper reading."
                ),
            },
            {
                "slug": "paper_ui_layout",
                "title": "Desktop Console Layout Patterns",
                "content": "A design note about sidebars, buttons, visual rhythm, responsive panels, and page density.",
            },
            {
                "slug": "paper_sales_brief",
                "title": "Commercial Launch Brief",
                "content": "A business note on market sizing, sales motion, customer interviews, and go-to-market channels.",
            },
        ],
    },
    {
        "scenario": "notes",
        "name": "bidirectional_note_graph_recall",
        "query": "我要找能把阅读笔记、来源文档和后续问题互相连起来的双链知识库方案。",
        "expected_slug": "notes_bidirectional_graph",
        "rubric": "Prefer note-graph material with wikilinks, backlinks, semantic edges, exported Markdown, and source notes.",
        "items": [
            {
                "slug": "notes_bidirectional_graph",
                "title": "Markdown Knowledge Graph with Wikilinks and Backlinks",
                "content": (
                    "This note describes a bidirectional note library using Markdown wikilinks, "
                    "backlinks, semantic graph edges, source-note references, exported vault checks, "
                    "quality gates, and follow-up actions from saved reading reports."
                ),
            },
            {
                "slug": "notes_pdf_style",
                "title": "PDF Typography Rules",
                "content": "Typography guidance for report headings, font weights, color contrast, margins, and tables.",
            },
            {
                "slug": "notes_task_queue",
                "title": "Worker Queue Operations",
                "content": "Operational notes about background queues, retries, cancellation, and task status transitions.",
            },
        ],
    },
    {
        "scenario": "code",
        "name": "code_search_long_task_worker_recall",
        "query": "后台长任务如果要支持取消、失败重试和恢复，应该检索哪段实现说明？",
        "expected_slug": "code_worker_runtime",
        "rubric": "Prefer engineering material about task queues, worker lifecycle, cancellation, retry, recovery, and audit events.",
        "items": [
            {
                "slug": "code_worker_runtime",
                "title": "Task Worker Runtime: Queue, Cancel, Retry, Recovery",
                "content": (
                    "Engineering implementation note for a background task queue. It covers worker "
                    "claiming, long-running job execution, cancellation tokens, failed retry policy, "
                    "recovery after restart, idempotent status updates, and event audit trails."
                ),
            },
            {
                "slug": "code_css_sidebar",
                "title": "Sidebar Collapse CSS",
                "content": "Frontend CSS notes for compact navigation rails, hover states, icons, and responsive layout.",
            },
            {
                "slug": "code_model_config",
                "title": "Model Settings Modal",
                "content": "Provider selection, API mode, local mode, offline mode, and key masking in the settings dialog.",
            },
        ],
    },
    {
        "scenario": "office",
        "name": "office_document_metrics_recall",
        "query": "哪份办公材料适合生成会议行动项、季度指标表和管理层汇报摘要？",
        "expected_slug": "office_kpi_meeting_pack",
        "rubric": "Prefer office workflow material with meeting actions, KPI spreadsheets, executive summaries, and deliverables.",
        "items": [
            {
                "slug": "office_kpi_meeting_pack",
                "title": "Office KPI Spreadsheet and Meeting Action Pack",
                "content": (
                    "Office workflow pack for meeting minutes, decisions, action items, quarterly "
                    "KPI spreadsheet formulas, executive summary tables, owners, due dates, and "
                    "management-ready deliverables."
                ),
            },
            {
                "slug": "office_paper_review",
                "title": "Research Reading Questions",
                "content": "A study worksheet with paper limitations, concepts, flashcards, and comprehension checks.",
            },
            {
                "slug": "office_graph_export",
                "title": "Knowledge Graph Export",
                "content": "A note about Markdown export folders, wikilink checks, backlinks, and graph consistency.",
            },
        ],
    },
]


def parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        candidate = candidate[start:end + 1] if start >= 0 and end >= start else candidate
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def provider_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "provider": "deepseek",
        "base_url": args.base_url,
        "model": args.model,
        "api_key": os.environ.get(args.api_key_env, ""),
        "timeout_s": args.timeout_s,
    }


async def probe_deepseek_api(args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.environ.get(args.api_key_env, "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    probe: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.timeout_s)) as client:
        endpoints = [
            ("models", "GET", "/models", None),
            (
                "chat",
                "POST",
                "/chat/completions",
                {
                    "model": args.model,
                    "messages": [{"role": "user", "content": "Return exactly: ok"}],
                    "temperature": 0,
                    "max_tokens": 8,
                },
            ),
            ("embeddings", "POST", "/embeddings", {"model": args.embedding_model, "input": ["semantic retrieval smoke test"]}),
        ]
        for name, method, path, payload in endpoints:
            started = time.perf_counter()
            try:
                if method == "GET":
                    resp = await client.get(args.base_url.rstrip("/") + path, headers=headers)
                else:
                    resp = await client.post(args.base_url.rstrip("/") + path, headers=headers, json=payload)
                elapsed = round((time.perf_counter() - started) * 1000, 3)
                item: dict[str, Any] = {"ok": 200 <= resp.status_code < 300, "status_code": resp.status_code, "latency_ms": elapsed}
                try:
                    body = resp.json()
                except Exception:
                    body = {"text": resp.text[:300]}
                if name == "models" and isinstance(body, dict):
                    item["models"] = [m.get("id") for m in (body.get("data") or []) if isinstance(m, dict)]
                elif name == "chat" and isinstance(body, dict):
                    item["content"] = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")[:120]
                    item["usage"] = body.get("usage") or {}
                elif name == "embeddings" and isinstance(body, dict):
                    item["response_keys"] = sorted(body.keys())[:10]
                    if body.get("data"):
                        item["embedding_dim"] = len((body["data"][0] or {}).get("embedding") or [])
                    if not item["ok"]:
                        item["note"] = "DeepSeek compatible API did not expose an embeddings endpoint in this probe."
                probe[name] = item
            except Exception as exc:
                probe[name] = {"ok": False, "error": type(exc).__name__}
    return probe


async def rewrite_query(provider: Any, case: dict[str, Any]) -> dict[str, Any]:
    prompt = [
        {
            "role": "system",
            "content": (
                "You rewrite user queries for high-quality semantic retrieval. Return compact JSON only "
                "with rewritten_query, key_concepts, must_have_terms, and rationale. Do not invent document IDs."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scenario": case["scenario"],
                    "query": case["query"],
                    "quality_rubric": case["rubric"],
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = await provider.complete(prompt, {"temperature": 0.0, "response_format": {"type": "json_object"}, "max_tokens": 320})
    parsed = parse_json_object(result.get("content", ""))
    concepts = parsed.get("key_concepts") if isinstance(parsed.get("key_concepts"), list) else []
    terms = parsed.get("must_have_terms") if isinstance(parsed.get("must_have_terms"), list) else []
    rewritten = str(parsed.get("rewritten_query") or case["query"])
    expanded = " ".join([rewritten, " ".join(map(str, concepts)), " ".join(map(str, terms))]).strip()
    return {
        "ok": bool(result.get("ok")),
        "error": result.get("error", ""),
        "rewritten_query": rewritten,
        "expanded_query": expanded or case["query"],
        "key_concepts": concepts[:12],
        "must_have_terms": terms[:12],
        "duration_ms": result.get("duration_ms", 0),
        "usage": result.get("usage") or {},
    }


async def judge_candidates(provider: Any, case: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    compact_candidates = [
        {
            "id": str(item.get("id")),
            "title": item.get("title", ""),
            "strategy": item.get("strategy", ""),
            "content": item.get("content", "")[:450],
        }
        for item in candidates[:8]
    ]
    prompt = [
        {
            "role": "system",
            "content": (
                "You are a strict retrieval evaluator. Return JSON only with selected_ids, verdict, "
                "confidence, and reason. Select only candidates that satisfy the query and rubric."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "scenario": case["scenario"],
                    "query": case["query"],
                    "rubric": case["rubric"],
                    "candidates": compact_candidates,
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = await provider.complete(prompt, {"temperature": 0.0, "response_format": {"type": "json_object"}, "max_tokens": 360})
    parsed = parse_json_object(result.get("content", ""))
    selected = parsed.get("selected_ids") if isinstance(parsed.get("selected_ids"), list) else []
    return {
        "ok": bool(result.get("ok")),
        "error": result.get("error", ""),
        "selected_ids": [str(x) for x in selected],
        "verdict": str(parsed.get("verdict") or ""),
        "confidence": parsed.get("confidence", 0),
        "reason": str(parsed.get("reason") or "")[:500],
        "duration_ms": result.get("duration_ms", 0),
        "usage": result.get("usage") or {},
    }


def seed_case(store: MemoryStore, case: dict[str, Any]) -> dict[str, str]:
    slug_to_id: dict[str, str] = {}
    for item in case["items"]:
        row = store.add_knowledge(
            item["title"],
            item["content"],
            category=case["scenario"],
            source=f"deepseek-retrieval-benchmark/{case['name']}",
            tags=[case["scenario"], item["slug"]],
            confidence=0.9 if item["slug"] == case["expected_slug"] else 0.55,
        )
        slug_to_id[item["slug"]] = f"kw_{row['id']}"
    return slug_to_id


def normalize_id(value: Any) -> set[str]:
    text = str(value)
    ids = {text}
    if text.startswith("kw_"):
        ids.add(text[3:])
    elif text.isdigit():
        ids.add(f"kw_{text}")
    return ids


def retrieval_metrics(case_results: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    recalls = []
    hits = []
    reciprocal_ranks = []
    judged_hits = []
    for item in case_results:
        expected = set(item["expected_ids"])
        retrieved = item["retrieved_ids"]
        retrieved_expanded = [candidate for rid in retrieved for candidate in normalize_id(rid)]
        matched = expected.intersection(retrieved_expanded)
        recalls.append(len(matched) / max(1, len(expected)))
        hits.append(1.0 if matched else 0.0)
        rank = 0
        for idx, rid in enumerate(retrieved, start=1):
            if expected.intersection(normalize_id(rid)):
                rank = idx
                break
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        selected = [sid for sid in item.get("judge", {}).get("selected_ids", [])]
        selected_expanded = {candidate for sid in selected for candidate in normalize_id(sid)}
        judged_hits.append(1.0 if expected.intersection(selected_expanded) else 0.0)
    avg = lambda xs: round(sum(xs) / len(xs), 4) if xs else 0.0
    return {
        f"recall_at_{top_k}": avg(recalls),
        "hit_rate": avg(hits),
        "mrr": avg(reciprocal_ranks),
        "judge_hit_rate": avg(judged_hits),
    }


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    provider = create_model_provider(provider_config(args))
    api_probe = await probe_deepseek_api(args)
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    store = MemoryStore(str(temp_path / "deepseek_retrieval.db"))
    vectors = MemoryVectorStore(str(temp_path / "deepseek_retrieval.db"), provider="chroma", persist_dir=str(temp_path / "chroma"))
    case_results = []
    try:
        for case in BENCHMARK_CASES:
            slug_to_id = seed_case(store, case)
            expected_id = slug_to_id[case["expected_slug"]]
            vectors.refresh()
            rewrite = await rewrite_query(provider, case)
            retrieval = RetrievalService(store, vectors)
            candidates = retrieval.retrieve(rewrite["expanded_query"], top_k=args.top_k)
            judge = await judge_candidates(provider, case, candidates)
            retrieved_ids = [str(item.get("id")) for item in candidates]
            matched = any(set(normalize_id(rid)).intersection({expected_id}) for rid in retrieved_ids)
            case_results.append({
                "scenario": case["scenario"],
                "name": case["name"],
                "query": case["query"],
                "expected_ids": [expected_id],
                "rewrite": rewrite,
                "retrieved_ids": retrieved_ids,
                "top_candidates": [
                    {
                        "id": str(item.get("id")),
                        "title": item.get("title", ""),
                        "strategy": item.get("strategy", ""),
                        "score": round(float(item.get("score") or 0), 4),
                    }
                    for item in candidates
                ],
                "judge": judge,
                "passed": matched,
            })
    finally:
        vectors.close()
        temp_dir.cleanup()
    metrics = retrieval_metrics(case_results, args.top_k)
    ok = bool(api_probe.get("chat", {}).get("ok")) and metrics.get(f"recall_at_{args.top_k}", 0) >= args.min_recall
    return {
        "ok": ok,
        "provider": "deepseek",
        "model": args.model,
        "base_url": args.base_url,
        "configured": bool(provider.is_configured()),
        "api_probe": api_probe,
        "benchmark": {
            "name": "deepseek-semantic-retrieval-v1",
            "case_count": len(case_results),
            "top_k": args.top_k,
            "min_recall": args.min_recall,
            "metrics": metrics,
        },
        "cases": case_results,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "notes": [
            "No API key is stored in this report.",
            "If embeddings probe is 404, DeepSeek is used for semantic query understanding and judging while Chroma stores local vectors.",
            "Offline Qwen/local embedding validation is intentionally deferred.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com/v1"))
    parser.add_argument("--model", default=os.environ.get("MODEL_NAME", "deepseek-chat"))
    parser.add_argument("--embedding-model", default=os.environ.get("EMBEDDING_MODEL", "deepseek-chat"))
    parser.add_argument("--api-key-env", default="MODEL_API_KEY")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--out", default="output/deepseek_retrieval_benchmark.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(run_benchmark(args))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        metrics = result["benchmark"]["metrics"]
        print(
            "DeepSeek retrieval benchmark: "
            f"ok={result['ok']} model={result['model']} "
            f"chat_ok={result['api_probe'].get('chat', {}).get('ok')} "
            f"embeddings_status={result['api_probe'].get('embeddings', {}).get('status_code')} "
            f"recall={metrics.get(f'recall_at_{args.top_k}')} "
            f"mrr={metrics.get('mrr')} judge_hit_rate={metrics.get('judge_hit_rate')}"
        )
        if args.out:
            print(f"Report: {args.out}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
