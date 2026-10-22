from __future__ import annotations

import json
import math
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from services.artifact_storage import ArtifactStorage
from services.search_evidence import (
    SearchEvidenceEngine,
    decide_search_need,
    provider_health_summary,
)


DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "benchmarks" / "search_evidence_policy_v1.json"


def load_corpus(path: str | Path = DEFAULT_CORPUS) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    if not isinstance(cases, list) or not cases:
        raise ValueError("search benchmark corpus must contain cases")
    names = [str(item.get("name") or "") for item in cases]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("search benchmark case names must be non-empty and unique")
    for case in cases:
        if not isinstance(case.get("should_search"), bool) or not str(case.get("query") or "").strip():
            raise ValueError(f"invalid search benchmark case: {case.get('name', '')}")
    return payload


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> dict[str, Any]:
    if total <= 0:
        return {"successes": int(successes), "total": 0, "rate": None, "low": None, "high": None}
    rate = successes / total
    denominator = 1 + (z * z / total)
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * total)) / total) / denominator
    return {
        "successes": int(successes), "total": int(total), "rate": round(rate, 4),
        "low": round(max(0.0, center - margin), 4), "high": round(min(1.0, center + margin), 4),
        "method": "wilson_95",
    }


def _host(value: str) -> str:
    return urllib.parse.urlparse(str(value or "")).netloc.lower()


def _domain_matches(value: str, expected: list[str]) -> bool:
    host = str(value or "").lower()
    return any(str(domain).lower() in host for domain in expected)


def _term_coverage(text: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    value = str(text or "").lower()
    return round(sum(1 for term in terms if str(term).lower() in value) / len(terms), 4)


def synthesize_extractive_answer(query: str, results: list[dict[str, Any]]) -> str:
    paragraphs = []
    for item in results[:3]:
        title = str(item.get("title") or _host(item.get("url", "")) or "Source").strip()
        snippet = re.sub(r"\s+", " ", str(item.get("snippet") or item.get("text") or "")).strip()
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        supported = snippet[:420].rstrip(" .")
        paragraphs.append(f"{supported}. [{title}]({url})" if supported else f"[{title}]({url})")
    return "\n\n".join(paragraphs)


def score_answer(case: dict[str, Any], answer: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    cited_urls = re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", str(answer or ""))
    retrieved_urls = {str(item.get("url") or "").split("#", 1)[0] for item in results}
    valid_citations = [url for url in cited_urls if url.split("#", 1)[0] in retrieved_urls]
    citation_precision = len(valid_citations) / len(cited_urls) if cited_urls else 0.0
    expected_domains = case.get("expected_domains") or []
    expected_citation_hit = (
        any(_domain_matches(_host(url), expected_domains) for url in valid_citations)
        if expected_domains else bool(valid_citations)
    )
    term_coverage = _term_coverage(answer, case.get("expected_terms") or [])
    community_domains = case.get("community_domains") or []
    community_hit = any(
        item.get("source_type") == "community"
        or _domain_matches(item.get("domain") or _host(item.get("url", "")), community_domains)
        for item in results
    )
    source_policy_met = community_hit if case.get("require_community") else (
        any(_domain_matches(item.get("domain") or _host(item.get("url", "")), expected_domains) for item in results)
        if expected_domains else bool(results)
    )
    citation_score = citation_precision if expected_citation_hit else 0.0
    quality = round(term_coverage * 0.40 + citation_score * 0.35 + float(source_policy_met) * 0.25, 4)
    return {
        "quality_score": quality,
        "term_coverage": term_coverage,
        "citation_precision": round(citation_precision, 4),
        "citation_hit": bool(expected_citation_hit),
        "source_policy_met": bool(source_policy_met),
        "community_source_hit": bool(community_hit),
        "cited_urls": cited_urls,
        "valid_cited_urls": valid_citations,
        "scoring": "deterministic_extractive_v1",
    }


def _mock_provider(case: dict[str, Any]) -> Callable[[str, int], tuple[list[dict[str, Any]], str]]:
    def provider(_query: str, limit: int) -> tuple[list[dict[str, Any]], str]:
        domains = case.get("community_domains") if case.get("require_community") else case.get("expected_domains")
        domain = (domains or ["example.com"])[0]
        terms = " ".join(case.get("expected_terms") or [case.get("query", "")])
        return [{
            "title": f"{case['name']} evidence", "url": f"https://{domain}/benchmark/{case['name']}",
            "snippet": f"{terms}. Evidence relevant to {case['query']}", "source": "mock",
            "rank": 1, "published_at": "2026-08-01",
        }][:limit], ""
    return provider


def _confusion(cases: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(1 for item in cases if item["expected_search"] and item["predicted_search"])
    tn = sum(1 for item in cases if not item["expected_search"] and not item["predicted_search"])
    fp = sum(1 for item in cases if not item["expected_search"] and item["predicted_search"])
    fn = sum(1 for item in cases if item["expected_search"] and not item["predicted_search"])
    return {
        "true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn,
        "accuracy": wilson_interval(tp + tn, len(cases)),
        "precision": wilson_interval(tp, tp + fp), "recall": wilson_interval(tp, tp + fn),
        "specificity": wilson_interval(tn, tn + fp),
    }


def run_provider_benchmark(
    out_dir: str | Path,
    *,
    providers: list[str],
    provider_funcs: dict[str, Callable[[str, int], tuple[list[dict[str, Any]], str]]],
    corpus_path: str | Path = DEFAULT_CORPUS,
    limit_cases: int | None = None,
    offline_mock: bool = False,
    retries: int = 1,
    use_cache: bool = False,
    answer_generator: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    corpus = load_corpus(corpus_path)
    all_cases = corpus["cases"]
    cases = all_cases[:max(1, min(int(limit_cases or len(all_cases)), len(all_cases)))]
    out_path = Path(out_dir)
    runtime = out_path / "_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    engine = SearchEvidenceEngine(runtime / "policy-cache.json", runtime / "policy-rate.json", max_per_minute=500)
    rows: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    active_providers = ["mock"] if offline_mock else [str(item).lower() for item in providers]

    for case in cases:
        decision = decide_search_need(
            case["query"], mode="auto", has_attachments=bool(case.get("has_attachments")),
            local_context_sufficient=bool(case.get("local_context_sufficient")),
        )
        expected = bool(case["should_search"])
        predicted = bool(decision["should_search"])
        row: dict[str, Any] = {
            "name": case["name"], "scenario": case.get("scenario", "general"),
            "query": case["query"], "expected_search": expected, "predicted_search": predicted,
            "decision_correct": expected == predicted, "decision_reason": decision.get("reason", ""),
            "expected_reason": case.get("expected_reason", ""),
        }
        if expected and predicted:
            started = time.perf_counter()
            funcs = {"mock": _mock_provider(case)} if offline_mock else provider_funcs
            payload = engine.search(
                case["query"], 6, active_providers, funcs, retries=max(1, min(int(retries), 4)),
                use_cache=bool(use_cache and not offline_mock), decision=decision,
            )
            results = payload.get("results") or []
            attempts.extend(payload.get("attempts") or [])
            answer = synthesize_extractive_answer(case["query"], results)
            score = score_answer(case, answer, results)
            generated = answer_generator(case, results) if answer_generator else {"ok": False, "error": "not_configured"}
            generated_answer = str(generated.get("answer") or "") if generated.get("ok") else ""
            generated_score = score_answer(case, generated_answer, results) if generated_answer else {}
            minimum = float(case.get("minimum_answer_quality", 0.5))
            row.update({
                "provider": payload.get("provider", ""), "source_count": len(results),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "answer": answer, "answer_quality": score, "minimum_answer_quality": minimum,
                "generated_answer": generated_answer,
                "generated_answer_result": {
                    "ok": bool(generated.get("ok")), "provider": generated.get("provider", ""),
                    "model": generated.get("model", ""), "error": generated.get("error", ""),
                    "duration_ms": generated.get("duration_ms", 0), "quality": generated_score,
                },
                "retrieval_pass": bool(results) and score["source_policy_met"],
                "answer_quality_pass": score["quality_score"] >= minimum,
                "generated_answer_quality_pass": bool(generated_score and generated_score["quality_score"] >= minimum),
                "failure_reason": payload.get("error_type", "") if not results else "",
                "evidence_sufficiency": payload.get("evidence_sufficiency") or {},
            })
        else:
            row.update({"retrieval_pass": None, "answer_quality_pass": None, "answer": "", "answer_quality": {}})
        row["pass"] = bool(row["decision_correct"] and (not expected or (row.get("retrieval_pass") and row.get("answer_quality_pass"))))
        rows.append(row)

    searched = [item for item in rows if item["expected_search"]]
    community = [item for item in searched if item["scenario"] == "community"]
    citation_hits = sum(1 for item in searched if item.get("answer_quality", {}).get("citation_hit"))
    community_hits = sum(1 for item in community if item.get("answer_quality", {}).get("community_source_hit"))
    quality_passes = sum(1 for item in searched if item.get("answer_quality_pass"))
    generated_quality_passes = sum(1 for item in searched if item.get("generated_answer_quality_pass"))
    generated_successes = sum(1 for item in searched if item.get("generated_answer_result", {}).get("ok"))
    retrieval_passes = sum(1 for item in searched if item.get("retrieval_pass"))
    passed = sum(1 for item in rows if item["pass"])
    health = provider_health_summary(attempts, active_providers)
    evaluated_provider_attempts = sum(item["attempt_count"] for item in health["providers"])
    successful_provider_attempts = sum(item["ok_count"] for item in health["providers"])
    report = {
        "name": corpus["name"], "corpus_version": corpus.get("version"),
        "corpus_review_status": corpus.get("review_status", "unreviewed"),
        "mode": "simulation_only" if offline_mock else "live_provider",
        "real_provider_evaluated": bool(not offline_mock and evaluated_provider_attempts),
        "real_provider_usable": bool(not offline_mock and successful_provider_attempts),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "case_count": len(rows), "search_case_count": len(searched), "no_search_case_count": len(rows) - len(searched),
        "passed_count": passed, "failed_count": len(rows) - passed, "pass_rate": wilson_interval(passed, len(rows)),
        "search_trigger": _confusion(rows),
        "retrieval_success_rate": wilson_interval(retrieval_passes, len(searched)),
        "citation_hit_rate": wilson_interval(citation_hits, len(searched)),
        "community_source_coverage_rate": wilson_interval(community_hits, len(community)),
        "evidence_ready_answer_quality_pass_rate": wilson_interval(quality_passes, len(searched)),
        "evidence_ready_answer_quality_mean": round(sum(float(item.get("answer_quality", {}).get("quality_score", 0)) for item in searched) / max(1, len(searched)), 4),
        "generated_answer_quality": {
            "evaluated": bool(answer_generator),
            "generation_success_rate": wilson_interval(generated_successes, len(searched)) if answer_generator else None,
            "quality_pass_rate": wilson_interval(generated_quality_passes, len(searched)) if answer_generator else None,
            "reason": "evaluated_with_configured_answer_model" if answer_generator else "no_live_answer_model_configured",
            "required_for_product_acceptance": True,
        },
        "provider_health": health,
        "quality_method": {
            "name": "deterministic_extractive_v1", "weights": {"expected_term_coverage": 0.40, "valid_expected_citation": 0.35, "source_policy": 0.25},
            "limitation": "Measures evidence-backed extractive answer readiness; it is not generated-answer quality, a human preference score, or an LLM-as-judge score.",
        },
        "cases": rows,
        "reproducible": {"corpus_path": str(Path(corpus_path).resolve()), "providers": active_providers, "retries": retries, "use_cache": bool(use_cache and not offline_mock)},
    }
    report["acceptance"] = {
        "eligible": report["real_provider_usable"],
        "passed": bool(report["real_provider_usable"] and report["generated_answer_quality"]["evaluated"] and (report["generated_answer_quality"]["quality_pass_rate"] or {}).get("rate", 0) >= 0.75 and report["search_trigger"]["accuracy"]["rate"] >= 0.90 and report["citation_hit_rate"]["rate"] >= 0.80 and report["community_source_coverage_rate"]["rate"] >= 0.60 and report["evidence_ready_answer_quality_pass_rate"]["rate"] >= 0.75),
        "thresholds": {"trigger_accuracy": 0.90, "citation_hit_rate": 0.80, "community_coverage": 0.60, "evidence_ready_answer_quality_pass_rate": 0.75, "generated_answer_quality_pass_rate": 0.75},
    }
    artifact = ArtifactStorage(out_path).write_json("live_search_policy_report.json", report)
    report["artifact"] = artifact
    report["report_path"] = artifact.get("path", str(out_path / "live_search_policy_report.json"))
    Path(report["report_path"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
