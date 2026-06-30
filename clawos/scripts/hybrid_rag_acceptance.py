#!/usr/bin/env python3
"""Full-chain Hybrid RAG acceptance: DeepSeek + Qwen3 Embedding + Qwen3 Reranker."""

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
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from memoryos.services.retrieval import CrossEncoderReranker, RetrievalService
from memoryos.services.vector_store import MemoryVectorStore
from providers import create_model_provider


CASES: list[dict[str, Any]] = [
    {
        "scenario": "research",
        "name": "citation_faithful_paper_brief",
        "user_task": "为论文阅读场景生成有证据链的评审摘要，说明引用漂移、复现实验和局限。",
        "query": "论文阅读里如何验证 RAG 答案的引用忠实度、引用漂移和可复现实验设计？",
        "expected_slug": "paper_citation_fidelity",
        "rubric": "Must retrieve paper material about citation fidelity, evidence chains, attribution drift, reproducibility, limitations, and evaluation.",
        "items": [
            {
                "slug": "paper_citation_fidelity",
                "title": "Citation-Faithful RAG Evaluation for Journal Papers",
                "content": (
                    "This journal-style paper defines citation-faithful retrieval augmented generation. "
                    "It measures evidence chain alignment, citation fidelity, attribution drift, "
                    "ablation controls, reproducible experiment protocols, human evaluation, "
                    "limitations, and failure modes for scholarly paper reading."
                ),
            },
            {
                "slug": "paper_layout",
                "title": "Journal PDF Layout and Typography",
                "content": "A design note about page margins, headers, footers, tables, fonts, and visual hierarchy.",
            },
            {
                "slug": "paper_market",
                "title": "Commercial Research Brief",
                "content": "Market sizing, user segmentation, pricing tiers, channels, and adoption risks.",
            },
        ],
    },
    {
        "scenario": "competition",
        "name": "enterprise_delivery_room_followup",
        "user_task": "基于项目交付包回答评委问题，说明技术证据、风险和下一步验收。",
        "query": "ClawOS 企业交付室生成的答辩包里，哪些证据能支撑技术可交付性和风险应对？",
        "expected_slug": "enterprise_delivery_package",
        "rubric": "Must retrieve delivery-room material with executive brief, technical evidence, demo runbook, judge Q&A, risk register, and MTTBook validation gap.",
        "items": [
            {
                "slug": "enterprise_delivery_package",
                "title": "ClawOS Enterprise Delivery Room Package",
                "content": (
                    "The enterprise delivery package contains delivery_index, executive_brief, "
                    "technical_evidence, demo_runbook, judge_qa, and risk_register. It summarizes "
                    "MTClaw traces, MemoryOS, Skill self-evolution, DeepSeek acceptance, Chroma/Qwen "
                    "retrieval, business-plan evidence, architecture assets, and the pending MTTBook "
                    "real-device validation risk."
                ),
            },
            {
                "slug": "enterprise_sidebar",
                "title": "Console Sidebar Polish",
                "content": "UI notes about sidebar collapse, navigation labels, responsive cards, and visual density.",
            },
            {
                "slug": "enterprise_finance",
                "title": "Quarterly Budget Sheet",
                "content": "Spreadsheet formulas, budget categories, spend forecast, and reporting cadence.",
            },
        ],
    },
    {
        "scenario": "code",
        "name": "durable_worker_runtime_review",
        "user_task": "审查长任务运行时是否支持取消、重试、恢复、幂等和事件审计。",
        "query": "后台复杂任务如何做到取消、失败重试、恢复、幂等状态更新和审计追踪？",
        "expected_slug": "worker_runtime",
        "rubric": "Must retrieve engineering material about worker queue claiming, cancellation tokens, retry policy, restart recovery, idempotency, and audit logs.",
        "items": [
            {
                "slug": "worker_runtime",
                "title": "Durable Task Worker Runtime",
                "content": (
                    "The worker runtime claims queued tasks, records step events, checks cancellation "
                    "tokens before tool execution, applies retry policy, recovers after process restart, "
                    "uses idempotent status updates, stores failure envelopes, and writes audit logs "
                    "for long-running jobs."
                ),
            },
            {
                "slug": "worker_css",
                "title": "Task Board CSS",
                "content": "Visual design rules for task cards, badges, table density, responsive overflow, and hover states.",
            },
            {
                "slug": "worker_model",
                "title": "Model Provider Presets",
                "content": "Configuration presets for API mode, local Qwen mode, GLM mode, and mock offline tests.",
            },
        ],
    },
    {
        "scenario": "office",
        "name": "office_meeting_kpi_pack",
        "user_task": "生成办公管理交付物：会议行动项、KPI 表、负责人、日期和管理层摘要。",
        "query": "哪份材料最适合生成会议行动项、季度 KPI 表、负责人截止日期和管理层摘要？",
        "expected_slug": "office_kpi_pack",
        "rubric": "Must retrieve office workflow material with meeting decisions, action items, KPI spreadsheet formulas, owners, due dates, and executive summary.",
        "items": [
            {
                "slug": "office_kpi_pack",
                "title": "Office Meeting Action and KPI Deliverable Pack",
                "content": (
                    "A management-ready office pack covering meeting minutes, decisions, action items, "
                    "owners, due dates, quarterly KPI spreadsheet formulas, executive summary tables, "
                    "risks, blockers, and follow-up deliverables."
                ),
            },
            {
                "slug": "office_rag",
                "title": "Embedding and Reranking Configuration",
                "content": "Technical notes about embedding providers, vector dimensions, reranker latency, and Chroma persistence.",
            },
            {
                "slug": "office_learning",
                "title": "Learning Self-Test Worksheet",
                "content": "Study questions, wrong-answer review, mastery score, spaced repetition, and concept dependencies.",
            },
        ],
    },
    {
        "scenario": "learning",
        "name": "learning_mastery_plan_with_mistake_review",
        "user_task": "为学习场景生成可复盘计划：目标、知识依赖、错题复盘、掌握度评分、间隔复习和下一步练习。",
        "query": "哪份材料最适合生成学习规划、知识依赖图、错题复盘、掌握度评分和间隔复习安排？",
        "expected_slug": "learning_mastery_plan",
        "rubric": "Must retrieve learning workflow material with goals, concept dependencies, mistake review, mastery score, spaced repetition, and next practice.",
        "items": [
            {
                "slug": "learning_mastery_plan",
                "title": "Learning Mastery Plan and Mistake Review Workflow",
                "content": (
                    "A learning workflow creates goals, concept dependency graphs, wrong-answer review, "
                    "mistake causes, corrected answers, mastery score, spaced repetition intervals, "
                    "self-test questions, and next practice tasks."
                ),
            },
            {
                "slug": "learning_delivery",
                "title": "Competition Delivery Checklist",
                "content": "Submission checklist, demo video, risk register, judge questions, and package export paths.",
            },
            {
                "slug": "learning_office",
                "title": "Office Management Weekly Brief",
                "content": "Weekly meeting summary, action owners, KPI notes, budget updates, and blockers.",
            },
        ],
    },
]


def _extra_case(
    scenario: str,
    name: str,
    user_task: str,
    query: str,
    expected_slug: str,
    rubric: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "name": name,
        "user_task": user_task,
        "query": query,
        "expected_slug": expected_slug,
        "rubric": rubric,
        "items": [
            {"slug": expected_slug, "title": title, "content": content},
            {
                "slug": f"{expected_slug}_distractor_ui",
                "title": f"{title} UI Distractor",
                "content": "Visual polish notes, spacing, color tokens, responsive layout, and navigation labels.",
            },
            {
                "slug": f"{expected_slug}_distractor_ops",
                "title": f"{title} Operations Distractor",
                "content": "Generic operations cadence, budget notes, team rituals, and status update templates.",
            },
        ],
    }


CASES.extend([
    _extra_case(
        "research",
        "systematic_review_evidence_matrix",
        "Build a reproducible systematic-review evidence matrix with inclusion criteria, quality scoring, and cited limitations.",
        "Which material supports a systematic review evidence matrix with inclusion criteria, quality scores, citations, and limitations?",
        "research_systematic_review_matrix",
        "Must retrieve evidence matrix material covering inclusion criteria, exclusion criteria, quality score, citations, limitations, and reproducibility.",
        "Systematic Review Evidence Matrix",
        "The systematic review matrix records inclusion criteria, exclusion criteria, study quality score, citation anchors, limitations, reproducibility notes, disagreement resolution, and final synthesis confidence.",
    ),
    _extra_case(
        "research",
        "dataset_methodology_audit",
        "Audit a dataset methodology section for sampling, annotation quality, leakage risk, and reproducible splits.",
        "Find evidence for dataset sampling, annotation quality, leakage risk, train test split reproducibility, and methodology audit.",
        "research_dataset_methodology_audit",
        "Must retrieve dataset methodology audit material with sampling, annotation quality, leakage, reproducible splits, and risk notes.",
        "Dataset Methodology Audit",
        "A dataset methodology audit checks sampling frame, annotation protocol, inter-annotator agreement, leakage risk, reproducible train validation test splits, metadata quality, and known bias limitations.",
    ),
    _extra_case(
        "research",
        "literature_gap_map",
        "Create a literature gap map that separates established findings, weak evidence, open questions, and next experiments.",
        "Which source explains literature gap mapping with established findings, weak evidence, open questions, and next experiments?",
        "research_literature_gap_map",
        "Must retrieve literature gap map material with established findings, weak evidence, open questions, and experiment proposals.",
        "Literature Gap Map",
        "The literature gap map separates established findings, weak evidence, contradicted claims, open questions, next experiments, confidence levels, and citation-backed rationale for every gap.",
    ),
    _extra_case(
        "research",
        "grant_proposal_risk_evidence",
        "Draft a grant proposal evidence section with novelty, feasibility, evaluation metrics, and risk mitigation.",
        "Retrieve grant proposal evidence for novelty, feasibility, evaluation metrics, risk mitigation, and cited prior work.",
        "research_grant_evidence",
        "Must retrieve grant proposal material with novelty, feasibility, metrics, mitigation, and prior work citations.",
        "Grant Proposal Evidence Pack",
        "A grant proposal evidence pack states novelty, feasibility, prior work citations, evaluation metrics, expected impact, risk mitigation, milestones, and reproducible validation artifacts.",
    ),
    _extra_case(
        "competition",
        "judge_cross_exam_packet",
        "Prepare a judge cross-examination packet with sharp questions, evidence-backed answers, and unresolved blockers.",
        "Find the competition packet for judge questions, evidence-backed answers, unresolved blockers, and owner-ready next steps.",
        "competition_judge_cross_exam",
        "Must retrieve judge cross-exam material with sharp questions, evidence-backed answers, blockers, owners, and next steps.",
        "Competition Judge Cross-Exam Packet",
        "The judge cross-exam packet lists adversarial judge questions, evidence-backed answers, unresolved blockers, owner-ready next steps, demo fallback paths, and final acceptance criteria.",
    ),
    _extra_case(
        "competition",
        "demo_failure_recovery_plan",
        "Create a competition demo failure recovery plan covering offline fallback, API fallback, screenshots, and timed rehearsal.",
        "Which evidence covers demo failure recovery with offline fallback, API fallback, screenshots, timing, and rehearsal?",
        "competition_demo_recovery",
        "Must retrieve demo recovery material with fallback modes, screenshots, rehearsal timing, and failure handling.",
        "Competition Demo Failure Recovery Plan",
        "The demo recovery plan defines offline mock fallback, DeepSeek API fallback, local model fallback, screenshot evidence, timed rehearsal checkpoints, failure handling, and spokesperson handoff.",
    ),
    _extra_case(
        "competition",
        "submission_hygiene_gate",
        "Check submission hygiene so ignored output, tmp, tools, secrets, and generated model artifacts do not enter Git.",
        "Find submission hygiene rules for tmp, tools, output, secrets, model artifacts, and Git staging safety.",
        "competition_submission_hygiene",
        "Must retrieve submission hygiene material covering tmp/tools/output exclusion, secrets, generated artifacts, and staging checks.",
        "Competition Submission Hygiene Gate",
        "The submission hygiene gate checks Git staged files, excludes tmp, tools, output, secrets, model weights, generated reports, local databases, and requires a final status audit before commit.",
    ),
    _extra_case(
        "competition",
        "business_plan_defense",
        "Defend the business plan with target users, pricing, moat, go-to-market, and measurable adoption evidence.",
        "Which material supports business plan defense with target users, pricing, moat, go to market, and adoption evidence?",
        "competition_business_defense",
        "Must retrieve business defense material with users, pricing, moat, GTM, adoption evidence, and risks.",
        "Competition Business Plan Defense",
        "The business plan defense covers target users, pricing model, technical moat, go-to-market channels, adoption metrics, commercial risks, investor objections, and evidence-backed responses.",
    ),
    _extra_case(
        "code",
        "security_policy_review",
        "Analyze a security policy module for grants, revocation, audit trail, high-risk tools, and least privilege.",
        "Retrieve code evidence about permission grants, revocation, audit trail, high risk tools, and least privilege enforcement.",
        "code_security_policy_review",
        "Must retrieve security policy code material with grants, revocation, audit logs, high-risk tools, and least privilege.",
        "Security Policy Review Notes",
        "The security policy review covers scoped grants, revocation, high-risk tool confirmation, audit trail persistence, least privilege defaults, path boundaries, and denied operation reporting.",
    ),
    _extra_case(
        "code",
        "rag_pipeline_debugging",
        "Debug a RAG pipeline with chunking, vector refresh, embedding provider selection, rerank thresholds, and citation IDs.",
        "Find engineering notes for chunking, vector refresh, embedding provider, rerank threshold, and citation ID debugging.",
        "code_rag_pipeline_debugging",
        "Must retrieve RAG pipeline code material with chunking, vector refresh, embeddings, rerank thresholds, and citation IDs.",
        "RAG Pipeline Debugging Notes",
        "RAG pipeline debugging checks document chunking, vector refresh, embedding provider selection, Chroma persistence, rerank threshold, citation ID normalization, and retrieval trace logging.",
    ),
    _extra_case(
        "code",
        "skill_runtime_contract",
        "Review skill runtime contracts for parameter references, cross-step outputs, plan-only mode, and replay scripts.",
        "Which code material explains skill runtime parameter references, cross-step outputs, plan-only execution, and replay scripts?",
        "code_skill_runtime_contract",
        "Must retrieve skill runtime contract material with parameters, cross-step references, plan-only, replay scripts, and validation.",
        "Skill Runtime Contract",
        "The skill runtime contract validates required parameters, resolves cross-step outputs, supports plan-only execution, records run metadata, generates replay scripts, and fails fast on unknown tools.",
    ),
    _extra_case(
        "code",
        "frontend_console_regression",
        "Analyze frontend console regression risk for static anchors, compact cards, timeline rendering, and responsive overflow.",
        "Find frontend regression evidence for static anchors, compact cards, timeline rendering, tables, and responsive overflow.",
        "code_frontend_console_regression",
        "Must retrieve frontend regression material with static anchors, report cards, timeline rendering, and responsive overflow.",
        "Frontend Console Regression Checklist",
        "The frontend console regression checklist protects static anchors, compact report cards, timeline rendering, table overflow, responsive breakpoints, copy labels, and button action wiring.",
    ),
    _extra_case(
        "office",
        "quarterly_business_review_pack",
        "Generate a quarterly business review pack with KPI narrative, risks, budget deltas, owners, and next actions.",
        "Which office material supports a quarterly business review with KPI narrative, budget deltas, risks, owners, and next actions?",
        "office_qbr_pack",
        "Must retrieve QBR material with KPI narrative, budget deltas, risks, owners, executive summary, and next actions.",
        "Quarterly Business Review Pack",
        "The quarterly business review pack includes KPI narrative, budget deltas, risk table, owner assignments, executive summary, decisions, blockers, and next action tracking.",
    ),
    _extra_case(
        "office",
        "board_memo_synthesis",
        "Draft a board memo from project evidence with decision asks, financial impact, operating risks, and appendix citations.",
        "Retrieve office memo material for board decision asks, financial impact, operating risks, appendix citations, and summary.",
        "office_board_memo",
        "Must retrieve board memo material with decision asks, financial impact, operating risks, appendix citations, and summary.",
        "Board Memo Synthesis Workflow",
        "The board memo workflow turns project evidence into decision asks, financial impact, operating risks, strategic options, appendix citations, executive summary, and follow-up owners.",
    ),
    _extra_case(
        "office",
        "contract_review_tracker",
        "Create a contract review tracker with clauses, owners, red flags, due dates, and escalation status.",
        "Which material supports contract clause tracking, owners, red flags, due dates, escalation, and status reporting?",
        "office_contract_tracker",
        "Must retrieve contract tracker material with clauses, owners, red flags, due dates, escalation, and reporting.",
        "Contract Review Tracker",
        "The contract review tracker records clause IDs, business owners, legal red flags, due dates, escalation status, negotiation notes, approval gates, and final signoff evidence.",
    ),
    _extra_case(
        "office",
        "customer_escalation_brief",
        "Build a customer escalation brief with timeline, impact, root cause, mitigation, accountable owner, and reply draft.",
        "Find office escalation material with timeline, customer impact, root cause, mitigation, owner, and reply draft.",
        "office_customer_escalation",
        "Must retrieve customer escalation material with timeline, impact, root cause, mitigation, owner, and response draft.",
        "Customer Escalation Brief",
        "The customer escalation brief includes incident timeline, customer impact, root cause, mitigation plan, accountable owner, communication draft, SLA risk, and follow-up checkpoint.",
    ),
    _extra_case(
        "learning",
        "exam_cram_strategy",
        "Create an exam cram strategy with topic triage, practice schedule, weak points, and timed self-tests.",
        "Which learning material supports exam cram strategy, topic triage, practice schedule, weak points, and timed self tests?",
        "learning_exam_cram",
        "Must retrieve exam cram material with topic triage, schedule, weak points, timed tests, and review loop.",
        "Exam Cram Strategy",
        "The exam cram strategy prioritizes topic triage, weak point diagnosis, timed self-tests, practice schedule, formula review, error log, and final-day confidence checks.",
    ),
    _extra_case(
        "learning",
        "course_project_roadmap",
        "Plan a course project roadmap with milestones, dependencies, rubric mapping, peer feedback, and demo checklist.",
        "Retrieve learning project material for milestones, dependencies, rubric mapping, peer feedback, and demo checklist.",
        "learning_course_project_roadmap",
        "Must retrieve course project roadmap material with milestones, dependencies, rubric mapping, feedback, and demo checklist.",
        "Course Project Roadmap",
        "The course project roadmap defines milestones, dependency map, rubric mapping, peer feedback checkpoints, demo checklist, reflection notes, and final submission evidence.",
    ),
    _extra_case(
        "learning",
        "language_learning_feedback_loop",
        "Design a language learning feedback loop with vocabulary, speaking drills, correction notes, and spaced review.",
        "Find learning evidence for vocabulary, speaking drills, correction notes, spaced review, and progress scoring.",
        "learning_language_feedback",
        "Must retrieve language feedback material with vocabulary, speaking drills, corrections, spaced review, and progress scoring.",
        "Language Learning Feedback Loop",
        "The language learning feedback loop tracks vocabulary clusters, speaking drills, correction notes, pronunciation issues, spaced review intervals, progress score, and next practice prompts.",
    ),
    _extra_case(
        "learning",
        "career_skill_gap_plan",
        "Create a career skill gap plan with target role, missing skills, practice projects, evidence portfolio, and weekly review.",
        "Which material supports career skill gap planning with target role, missing skills, projects, portfolio evidence, and weekly review?",
        "learning_career_skill_gap",
        "Must retrieve career skill gap material with target role, missing skills, projects, evidence portfolio, and weekly review.",
        "Career Skill Gap Plan",
        "The career skill gap plan maps target role requirements, missing skills, practice projects, evidence portfolio, weekly review cadence, mentor feedback, and measurable readiness score.",
    ),
])


def parse_json_object(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
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


def normalize_id(value: Any) -> set[str]:
    text = str(value)
    if text.startswith("kw_"):
        return {text, text[3:]}
    if text.isdigit():
        return {text, f"kw_{text}"}
    return {text}


def model_file_report(model_path: Path, kind: str) -> dict[str, Any]:
    required = ["config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"]
    if kind == "embedding":
        required.extend(["modules.json", "config_sentence_transformers.json", "1_Pooling/config.json"])
    files = {name: (model_path / name).exists() for name in required}
    total_bytes = sum(item.stat().st_size for item in model_path.rglob("*") if item.is_file()) if model_path.exists() else 0
    return {
        "path": str(model_path),
        "kind": kind,
        "required_files": files,
        "total_bytes": total_bytes,
        "complete": all(files.values()),
    }


def provider_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "provider": "deepseek",
        "base_url": args.base_url,
        "model": args.model,
        "api_key": os.environ.get(args.api_key_env, ""),
        "timeout_s": args.timeout_s,
    }


async def probe_deepseek(args: argparse.Namespace) -> dict[str, Any]:
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
                {"model": args.model, "messages": [{"role": "user", "content": "Return exactly: ok"}], "temperature": 0, "max_tokens": 8},
            ),
            ("embeddings", "POST", "/embeddings", {"model": args.embedding_probe_model, "input": ["hybrid rag smoke test"]}),
        ]
        for name, method, path, payload in endpoints:
            started = time.perf_counter()
            try:
                url = args.base_url.rstrip("/") + path
                response = await (client.get(url, headers=headers) if method == "GET" else client.post(url, headers=headers, json=payload))
                elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
                item: dict[str, Any] = {"ok": 200 <= response.status_code < 300, "status_code": response.status_code, "latency_ms": elapsed_ms}
                try:
                    body = response.json()
                except Exception:
                    body = {"text": response.text[:300]}
                if name == "models" and isinstance(body, dict):
                    item["models"] = [row.get("id") for row in (body.get("data") or []) if isinstance(row, dict)]
                if name == "chat" and isinstance(body, dict):
                    item["content"] = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")[:120]
                    item["usage"] = body.get("usage") or {}
                if name == "embeddings" and isinstance(body, dict):
                    item["response_keys"] = sorted(body.keys())[:10]
                    if body.get("data"):
                        item["embedding_dim"] = len((body["data"][0] or {}).get("embedding") or [])
                    if not item["ok"]:
                        item["note"] = "DeepSeek compatible API did not expose embeddings; local Qwen embedding is used for recall."
                probe[name] = item
            except Exception as exc:
                probe[name] = {"ok": False, "error": type(exc).__name__}
    return probe


def seed_corpus(store: MemoryStore) -> dict[str, str]:
    slug_to_id: dict[str, str] = {}
    for case in CASES:
        for item in case["items"]:
            row = store.add_knowledge(
                item["title"],
                item["content"],
                category=case["scenario"],
                source=f"hybrid-rag/{case['name']}",
                tags=[case["scenario"], item["slug"]],
                confidence=0.95 if item["slug"] == case["expected_slug"] else 0.55,
            )
            slug_to_id[item["slug"]] = f"kw_{row['id']}"
    return slug_to_id


async def rewrite_query(provider: Any, case: dict[str, Any]) -> dict[str, Any]:
    prompt = [
        {
            "role": "system",
            "content": (
                "Rewrite complex Chinese/English user tasks into a precise semantic retrieval query. "
                "Return JSON only: rewritten_query, key_concepts, must_have_terms, answer_plan."
            ),
        },
        {"role": "user", "content": json.dumps({"task": case["user_task"], "query": case["query"], "rubric": case["rubric"]}, ensure_ascii=False)},
    ]
    result = await provider.complete(prompt, {"temperature": 0.0, "response_format": {"type": "json_object"}, "max_tokens": 360})
    parsed = parse_json_object(result.get("content", ""))
    concepts = parsed.get("key_concepts") if isinstance(parsed.get("key_concepts"), list) else []
    terms = parsed.get("must_have_terms") if isinstance(parsed.get("must_have_terms"), list) else []
    rewritten = str(parsed.get("rewritten_query") or case["query"])
    expanded = " ".join([rewritten, " ".join(map(str, concepts)), " ".join(map(str, terms))]).strip()
    return {
        "ok": bool(result.get("ok")),
        "rewritten_query": rewritten,
        "expanded_query": expanded or case["query"],
        "key_concepts": concepts[:12],
        "must_have_terms": terms[:12],
        "answer_plan": parsed.get("answer_plan", ""),
        "duration_ms": result.get("duration_ms", 0),
        "usage": result.get("usage") or {},
        "error": result.get("error", ""),
    }


async def generate_grounded_answer(provider: Any, case: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    compact = [
        {
            "id": str(item.get("id")),
            "title": item.get("title", ""),
            "content": item.get("content", "")[:700],
            "score": item.get("score"),
            "rerank_score": item.get("rerank_score"),
        }
        for item in evidence[:5]
    ]
    prompt = [
        {
            "role": "system",
            "content": (
                "Answer using only the supplied evidence. Return JSON only with answer, citation_ids, "
                "risk_notes, next_actions, and grounded_confidence. citation_ids must be evidence ids."
            ),
        },
        {"role": "user", "content": json.dumps({"task": case["user_task"], "query": case["query"], "evidence": compact}, ensure_ascii=False)},
    ]
    result = await provider.complete(prompt, {"temperature": 0.0, "response_format": {"type": "json_object"}, "max_tokens": 700})
    parsed = parse_json_object(result.get("content", ""))
    citations = parsed.get("citation_ids") if isinstance(parsed.get("citation_ids"), list) else []
    return {
        "ok": bool(result.get("ok")),
        "answer": str(parsed.get("answer") or result.get("content") or "")[:1800],
        "citation_ids": [str(item) for item in citations],
        "risk_notes": parsed.get("risk_notes") if isinstance(parsed.get("risk_notes"), list) else [],
        "next_actions": parsed.get("next_actions") if isinstance(parsed.get("next_actions"), list) else [],
        "grounded_confidence": parsed.get("grounded_confidence", 0),
        "duration_ms": result.get("duration_ms", 0),
        "usage": result.get("usage") or {},
        "error": result.get("error", ""),
    }


async def judge_answer(provider: Any, case: dict[str, Any], answer: dict[str, Any], expected_id: str) -> dict[str, Any]:
    prompt = [
        {
            "role": "system",
            "content": (
                "Judge whether the answer is grounded and cites the expected evidence. Return JSON only "
                "with grounded, cites_expected, completeness, and reason."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": case["user_task"],
                    "rubric": case["rubric"],
                    "expected_evidence_id": expected_id,
                    "answer": answer,
                },
                ensure_ascii=False,
            ),
        },
    ]
    result = await provider.complete(prompt, {"temperature": 0.0, "response_format": {"type": "json_object"}, "max_tokens": 360})
    parsed = parse_json_object(result.get("content", ""))
    return {
        "ok": bool(result.get("ok")),
        "grounded": bool(parsed.get("grounded")),
        "cites_expected": bool(parsed.get("cites_expected")),
        "completeness": parsed.get("completeness", 0),
        "reason": str(parsed.get("reason") or "")[:500],
        "duration_ms": result.get("duration_ms", 0),
        "usage": result.get("usage") or {},
        "error": result.get("error", ""),
    }


def hit_rank(ids: list[str], expected_id: str) -> int:
    for index, item in enumerate(ids, start=1):
        if normalize_id(item).intersection({expected_id}):
            return index
    return 0


def failure_reason(vector_rank: int, rerank_rank: int, citation_hit: bool, judge: dict[str, Any]) -> str:
    reasons = []
    if not vector_rank:
        reasons.append("expected evidence missing from vector recall")
    if not rerank_rank:
        reasons.append("expected evidence missing from rerank top-k")
    if not citation_hit:
        reasons.append("answer did not cite expected evidence")
    if not judge.get("grounded"):
        reasons.append("judge marked answer as not grounded")
    if not judge.get("cites_expected"):
        reasons.append("judge did not confirm expected citation")
    if judge.get("error"):
        reasons.append(f"judge_error={judge.get('error')}")
    return "; ".join(reasons) if reasons else ""


def aggregate(case_results: list[dict[str, Any]], recall_k: int, top_k: int) -> dict[str, Any]:
    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    vector_hits = [1.0 if item["vector_rank"] else 0.0 for item in case_results]
    rerank_hits = [1.0 if item["rerank_rank"] else 0.0 for item in case_results]
    rerank_rr = [(1.0 / item["rerank_rank"]) if item["rerank_rank"] else 0.0 for item in case_results]
    citation_hits = [1.0 if item["citation_hit"] else 0.0 for item in case_results]
    grounded = [1.0 if item.get("judge", {}).get("grounded") else 0.0 for item in case_results]
    judged_expected = [1.0 if item.get("judge", {}).get("cites_expected") else 0.0 for item in case_results]
    case_passes = [1.0 if item.get("pass") else 0.0 for item in case_results]
    latencies = sorted(float(item.get("latency_ms") or 0) for item in case_results)
    scenarios = sorted({str(item.get("scenario") or "") for item in case_results})
    by_scenario = {}
    for scenario in scenarios:
        rows = [item for item in case_results if str(item.get("scenario") or "") == scenario]
        passed = sum(1 for item in rows if item.get("pass"))
        by_scenario[scenario] = {
            "case_count": len(rows),
            "passed_count": passed,
            "failed_count": len(rows) - passed,
            "pass_rate": round(passed / len(rows), 4) if rows else 0,
        }
    return {
        "pass_rate": avg(case_passes),
        "passed_count": int(sum(case_passes)),
        "failed_count": len(case_results) - int(sum(case_passes)),
        f"vector_recall_at_{recall_k}": avg(vector_hits),
        f"rerank_recall_at_{top_k}": avg(rerank_hits),
        "rerank_mrr": avg(rerank_rr),
        "citation_hit_rate": avg(citation_hits),
        "judge_grounded_rate": avg(grounded),
        "judge_expected_citation_rate": avg(judged_expected),
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else 0,
        "latency_p95_ms": latencies[-1] if latencies else 0,
        "by_scenario": by_scenario,
    }


async def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    embedding_path = Path(args.embedding_model_path).expanduser().resolve()
    reranker_path = Path(args.reranker_model_path).expanduser().resolve()
    embedding_files = model_file_report(embedding_path, "embedding")
    reranker_files = model_file_report(reranker_path, "reranker")
    if not embedding_files["complete"]:
        return {"ok": False, "error": "embedding_model_incomplete", "embedding_files": embedding_files}
    if args.reranker_provider != "none" and not reranker_files["complete"]:
        return {"ok": False, "error": "reranker_model_incomplete", "embedding_files": embedding_files, "reranker_files": reranker_files}

    provider = create_model_provider(provider_config(args))
    api_probe = await probe_deepseek(args)
    temp_dir = tempfile.TemporaryDirectory()
    vectors = None
    try:
        temp_path = Path(temp_dir.name)
        db_path = temp_path / "hybrid_rag.db"
        chroma_dir = temp_path / "chroma"
        store = MemoryStore(str(db_path))
        slug_to_id = seed_corpus(store)
        vectors = MemoryVectorStore(
            str(db_path),
            provider="chroma",
            persist_dir=str(chroma_dir),
            embedding_provider=args.embedding_provider,
            embedding_model_path=str(embedding_path),
            embedding_dim=args.embedding_dim,
        )
        vectors.refresh()
        reranker = None if args.reranker_provider == "none" else CrossEncoderReranker(str(reranker_path), provider=args.reranker_provider)
        retrieval = RetrievalService(store, vectors, reranker=reranker)
        vector_stats = vectors.stats()
        case_results: list[dict[str, Any]] = []
        for case in CASES:
            case_started = time.perf_counter()
            expected_id = slug_to_id[case["expected_slug"]]
            rewrite = await rewrite_query(provider, case)
            vector_hits = vectors.search(rewrite["expanded_query"], top_k=args.recall_k, min_score=0.0)
            reranked = retrieval.semantic_rerank(rewrite["expanded_query"], recall_k=args.recall_k, top_k=args.top_k, min_score=0.0)
            vector_ids = [str(item.get("id")) for item in vector_hits]
            rerank_ids = [str(item.get("id")) for item in reranked]
            answer = await generate_grounded_answer(provider, case, reranked)
            citation_hit = any(normalize_id(item).intersection({expected_id}) for item in answer.get("citation_ids", []))
            judge = await judge_answer(provider, case, answer, expected_id)
            vector_rank = hit_rank(vector_ids, expected_id)
            rerank_rank = hit_rank(rerank_ids, expected_id)
            case_pass = bool(vector_rank and rerank_rank and citation_hit and judge.get("grounded"))
            case_failure_reason = failure_reason(vector_rank, rerank_rank, citation_hit, judge)
            case_results.append({
                "scenario": case["scenario"],
                "name": case["name"],
                "expected_id": expected_id,
                "pass": case_pass,
                "rewrite": rewrite,
                "vector_ids": vector_ids[:args.recall_k],
                "rerank_ids": rerank_ids[:args.top_k],
                "vector_rank": vector_rank,
                "rerank_rank": rerank_rank,
                "citation_hit": citation_hit,
                "failure_reason": case_failure_reason,
                "answer": answer,
                "judge": judge,
                "latency_ms": round((time.perf_counter() - case_started) * 1000, 3),
                "reproducible_io": {
                    "input": {
                        "scenario": case["scenario"],
                        "task": case["user_task"],
                        "query": case["query"],
                        "expected_slug": case["expected_slug"],
                    },
                    "output": {
                        "rewritten_query": rewrite.get("rewritten_query", ""),
                        "citation_ids": answer.get("citation_ids", []),
                        "answer": answer.get("answer", ""),
                        "judge": judge,
                    },
                },
                "top_reranked": [
                    {
                        "id": str(item.get("id")),
                        "title": item.get("title", ""),
                        "score": item.get("score"),
                        "rerank_score": item.get("rerank_score"),
                    }
                    for item in reranked[:args.top_k]
                ],
            })
        metrics = aggregate(case_results, args.recall_k, args.top_k)
    finally:
        if vectors is not None:
            vectors.close()
        temp_dir.cleanup()

    ok = (
        bool(api_probe.get("chat", {}).get("ok"))
        and vector_stats.get("provider") == "chroma"
        and vector_stats.get("embedding_provider") == args.embedding_provider
        and metrics[f"vector_recall_at_{args.recall_k}"] >= args.min_recall
        and metrics[f"rerank_recall_at_{args.top_k}"] >= args.min_recall
        and metrics["citation_hit_rate"] >= args.min_citation_hit_rate
        and metrics["judge_grounded_rate"] >= args.min_grounded_rate
        and metrics["pass_rate"] >= args.min_pass_rate
    )
    return {
        "ok": ok,
        "provider": "deepseek",
        "model": args.model,
        "configured": bool(provider.is_configured()),
        "api_probe": api_probe,
        "embedding_files": embedding_files,
        "reranker_files": reranker_files,
        "vector_stats": vector_stats,
        "benchmark": {
            "name": "deepseek-qwen3-complex-task-acceptance-v2",
            "case_count": len(CASES),
            "recall_k": args.recall_k,
            "top_k": args.top_k,
            "thresholds": {
                "min_recall": args.min_recall,
                "min_citation_hit_rate": args.min_citation_hit_rate,
                "min_grounded_rate": args.min_grounded_rate,
                "min_pass_rate": args.min_pass_rate,
            },
            "metrics": metrics,
        },
        "cases": case_results,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "notes": [
            "API keys are read from environment only and are not written to this report.",
            "DeepSeek is used for query rewriting, final grounded answer generation, and answer judging.",
            "Qwen3-Embedding + Chroma handle local vector recall; Qwen3-Reranker handles top-k precision ranking.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com/v1"))
    parser.add_argument("--model", default=os.environ.get("MODEL_NAME", "deepseek-chat"))
    parser.add_argument("--api-key-env", default="MODEL_API_KEY")
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--embedding-probe-model", default=os.environ.get("EMBEDDING_MODEL", "deepseek-chat"))
    parser.add_argument("--embedding-provider", default="qwen3")
    parser.add_argument("--embedding-model-path", default=str(REPO_ROOT / "tools" / "models" / "qwen3-embedding-0.6b"))
    parser.add_argument("--embedding-dim", type=int, default=1024)
    parser.add_argument("--reranker-provider", default="qwen3")
    parser.add_argument("--reranker-model-path", default=str(REPO_ROOT / "tools" / "models" / "qwen3-reranker-0.6b"))
    parser.add_argument("--recall-k", type=int, default=30)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-recall", type=float, default=1.0)
    parser.add_argument("--min-citation-hit-rate", type=float, default=1.0)
    parser.add_argument("--min-grounded-rate", type=float, default=0.75)
    parser.add_argument("--min-pass-rate", type=float, default=1.0)
    parser.add_argument("--out", default="output/deepseek_hybrid_rag_acceptance.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(run_acceptance(args))
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        metrics = result.get("benchmark", {}).get("metrics", {})
        print(
            "Hybrid RAG acceptance: "
            f"ok={result.get('ok')} model={result.get('model')} "
            f"chat_ok={result.get('api_probe', {}).get('chat', {}).get('ok')} "
            f"embedding={result.get('vector_stats', {}).get('embedding_provider')} "
            f"vector_recall={metrics.get(f'vector_recall_at_{args.recall_k}')} "
            f"rerank_recall={metrics.get(f'rerank_recall_at_{args.top_k}')} "
            f"rerank_mrr={metrics.get('rerank_mrr')} "
            f"citation_hit_rate={metrics.get('citation_hit_rate')} "
            f"grounded_rate={metrics.get('judge_grounded_rate')} "
            f"pass_rate={metrics.get('pass_rate')}"
        )
        if args.out:
            print(f"Report: {args.out}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
