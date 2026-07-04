from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable


CLAWOS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLAWOS_ROOT.parent
if str(CLAWOS_ROOT) not in sys.path:
    sys.path.insert(0, str(CLAWOS_ROOT))

from services.artifact_storage import ArtifactStorage
from services.search_evidence import SearchEvidenceEngine, citation_consistency, provider_health_summary


def _case(name: str, scenario: str, query: str, domains: list[str], terms: list[str], render_js: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "scenario": scenario,
        "query": query,
        "expected_domains": domains,
        "expected_terms": terms,
        "render_js_required": render_js,
        "answer_claim": " ".join(terms[:4]) or query,
    }


LIVE_CASES: list[dict[str, Any]] = [
    _case("official_python_datetime", "official_docs", "Python datetime timezone official documentation", ["docs.python.org"], ["Python", "datetime", "timezone"]),
    _case("official_fastapi_upload", "official_docs", "FastAPI UploadFile official documentation", ["fastapi.tiangolo.com"], ["FastAPI", "UploadFile", "files"]),
    _case("official_node_fetch", "official_docs", "Node.js fetch official documentation", ["nodejs.org"], ["Node.js", "fetch", "global"]),
    _case("official_playwright_locators", "official_docs", "Playwright locators official documentation", ["playwright.dev"], ["Playwright", "locator", "page"]),
    _case("official_sqlite_wal", "official_docs", "SQLite write ahead log official documentation", ["sqlite.org"], ["SQLite", "write-ahead", "logging"]),
    _case("news_ai_policy", "news_freshness", "latest AI policy official update July 2026", ["gov", "europa.eu", "nist.gov", "whitehouse.gov"], ["AI", "policy", "official"]),
    _case("news_security_advisory", "news_freshness", "latest cybersecurity advisory official July 2026", ["cisa.gov", "cert.org"], ["cybersecurity", "advisory", "latest"]),
    _case("news_browser_release", "news_freshness", "latest Chrome release notes July 2026", ["developer.chrome.com", "chromereleases.googleblog.com"], ["Chrome", "release", "notes"]),
    _case("news_python_release", "news_freshness", "latest Python release notes July 2026", ["python.org"], ["Python", "release", "notes"]),
    _case("news_cloud_status", "news_freshness", "cloud status latest incident report", ["status"], ["status", "incident", "report"]),
    _case("paper_rag", "papers", "retrieval augmented generation citations paper", ["arxiv.org", "aclanthology.org"], ["retrieval", "augmented", "generation", "citation"]),
    _case("paper_multi_agent", "papers", "multi agent systems evaluation benchmark paper", ["arxiv.org", "aclanthology.org"], ["multi-agent", "evaluation", "benchmark"]),
    _case("paper_asr_meeting", "papers", "automatic speech recognition meeting diarization paper", ["arxiv.org", "ieee.org", "aclanthology.org"], ["speech", "recognition", "diarization"]),
    _case("paper_rerank", "papers", "neural reranking information retrieval paper", ["arxiv.org", "acm.org", "dl.acm.org"], ["reranking", "retrieval", "neural"]),
    _case("paper_agent_workflow", "papers", "LLM agent workflow orchestration evaluation paper", ["arxiv.org", "aclanthology.org"], ["agent", "workflow", "evaluation"]),
    _case("policy_nist_ai_rmf", "policy", "NIST AI risk management framework official", ["nist.gov"], ["AI", "Risk", "Management", "Framework"]),
    _case("policy_eu_ai_act", "policy", "EU AI Act official regulation text", ["europa.eu"], ["AI", "Act", "regulation"]),
    _case("policy_ftc_privacy", "policy", "FTC privacy security official business guidance", ["ftc.gov"], ["privacy", "security", "business"]),
    _case("policy_cisa_reporting", "policy", "CISA cyber incident reporting official rule", ["cisa.gov"], ["incident", "reporting", "cyber"]),
    _case("policy_china_gen_ai", "policy", "China generative AI interim measures official policy", ["gov.cn", "cac.gov.cn"], ["generative", "AI", "measures"]),
    _case("product_qwen_embedding", "product", "Qwen text embedding model official documentation", ["aliyun.com", "dashscope.aliyuncs.com"], ["Qwen", "embedding", "model"]),
    _case("product_deepseek_api", "product", "DeepSeek API official documentation", ["deepseek.com", "api-docs.deepseek.com"], ["DeepSeek", "API", "chat"]),
    _case("product_faster_whisper", "product", "faster-whisper GitHub documentation", ["github.com"], ["faster-whisper", "Whisper", "transcription"]),
    _case("product_whisper_cpp", "product", "whisper.cpp GitHub documentation", ["github.com"], ["whisper.cpp", "speech", "recognition"]),
    _case("product_playwright", "product", "Playwright browser rendering documentation", ["playwright.dev"], ["Playwright", "browser", "automation"]),
    _case("chinese_ai_learning", "chinese_web", "AI learning path official Chinese university", ["edu.cn", "moe.gov.cn"], ["AI", "learning", "course"]),
    _case("chinese_data_security", "chinese_web", "China data security law official interpretation", ["gov.cn", "npc.gov.cn"], ["data", "security", "law"]),
    _case("chinese_qwen_docs", "chinese_web", "Tongyi Qianwen embedding documentation Chinese", ["aliyun.com"], ["Tongyi", "Qianwen", "embedding"]),
    _case("chinese_asr_meeting", "chinese_web", "meeting speech recognition action items Chinese", ["baidu.com", "aliyun.com", "tencent.com"], ["meeting", "speech", "recognition"]),
    _case("chinese_rag_eval", "chinese_web", "RAG citation evaluation Chinese article", ["cnki.net", "zhihu.com", "csdn.net"], ["RAG", "citation", "evaluation"]),
    _case("js_vercel_pricing", "js_page", "Vercel pricing page enterprise", ["vercel.com"], ["pricing", "enterprise"], True),
    _case("js_github_status", "js_page", "GitHub status incident history", ["githubstatus.com"], ["status", "incident"], True),
    _case("js_openai_docs_search", "js_page", "OpenAI developer documentation search", ["platform.openai.com", "developers.openai.com"], ["OpenAI", "documentation"], True),
    _case("js_cloudflare_status", "js_page", "Cloudflare status incident history", ["cloudflarestatus.com"], ["status", "incident"], True),
    _case("js_npm_package", "js_page", "npm package react latest version page", ["npmjs.com"], ["npm", "react", "version"], True),
    _case("dev_fastapi", "developer_docs", "FastAPI dependency injection official docs", ["fastapi.tiangolo.com"], ["dependency", "injection"]),
    _case("dev_react", "developer_docs", "React useEffect official documentation", ["react.dev"], ["React", "useEffect"]),
    _case("dev_typescript", "developer_docs", "TypeScript handbook generics official", ["typescriptlang.org"], ["TypeScript", "generics"]),
    _case("security_owasp_llm", "security", "OWASP Top 10 for LLM applications official", ["owasp.org"], ["OWASP", "LLM", "Top 10"]),
    _case("education_ai_course", "education", "Stanford CS229 machine learning course official", ["stanford.edu"], ["machine", "learning", "course"]),
]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _domain_hit(result: dict[str, Any], expected_domains: list[str]) -> bool:
    domain = str(result.get("domain") or result.get("url") or "").lower()
    return any(expected.lower() in domain for expected in expected_domains)


def _term_hit(results: list[dict[str, Any]], expected_terms: list[str]) -> bool:
    haystack = " ".join(
        f"{item.get('title', '')} {item.get('snippet', '')} {item.get('text', '')}"
        for item in results
    ).lower()
    return any(term.lower() in haystack for term in expected_terms)


def _mock_provider_for(case: dict[str, Any]) -> Callable[[str, int], tuple[list[dict[str, Any]], str]]:
    def provider(query: str, limit: int) -> tuple[list[dict[str, Any]], str]:
        domain = case["expected_domains"][0] if case.get("expected_domains") else "example.com"
        terms = " ".join(case.get("expected_terms") or [])
        return [
            {
                "title": f"{case['name']} official evidence",
                "url": f"https://{domain}/clawos-live-smoke/{case['name']}",
                "snippet": f"{case['answer_claim']} {terms} official documentation and evidence.",
                "source": "mock",
                "rank": 1,
                "published_at": "2026-07-01",
            }
        ][:limit], ""

    return provider


def _provider_funcs() -> dict[str, Callable[[str, int], tuple[list[dict[str, Any]], str]]]:
    from scripts import tool_runner

    return {
        "tavily": tool_runner._search_tavily,
        "serpapi": tool_runner._search_serpapi,
        "bing": tool_runner._search_bing,
        "duckduckgo": tool_runner._search_duckduckgo,
    }


def _case_failure_reasons(payload: dict[str, Any], citation: dict[str, Any], domain_hit: bool, term_hit: bool) -> list[str]:
    reasons = []
    if payload.get("error"):
        reasons.append(str(payload.get("error_type") or payload.get("error")))
    if not payload.get("results"):
        reasons.append("empty_results")
    if citation.get("status") != "pass":
        reasons.append("citation_consistency_failed")
    if not domain_hit and not term_hit:
        reasons.append("expected_domain_or_term_miss")
    return sorted(set(reasons))


def run_live_suite(
    out_dir: Path | str = REPO_ROOT / "output" / "search_evidence",
    *,
    providers: list[str] | None = None,
    limit_cases: int | None = None,
    offline_mock: bool = False,
    retries: int = 1,
    use_cache: bool = True,
) -> dict[str, Any]:
    providers = [str(item).lower() for item in (providers or ["tavily", "serpapi", "bing", "duckduckgo"]) if str(item).strip()]
    cases = LIVE_CASES[: max(1, min(int(limit_cases or len(LIVE_CASES)), len(LIVE_CASES)))]
    runtime_dir = Path(out_dir) / "_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    engine = SearchEvidenceEngine(
        runtime_dir / "cache.json",
        runtime_dir / "rate.json",
        cache_ttl_seconds=3600,
        max_per_minute=500,
    )
    base_provider_funcs = _provider_funcs() if not offline_mock else {}
    results: list[dict[str, Any]] = []
    all_attempts: list[dict[str, Any]] = []

    for case in cases:
        started = time.perf_counter()
        provider_funcs = {"mock": _mock_provider_for(case)} if offline_mock else base_provider_funcs
        active_providers = ["mock"] if offline_mock else providers
        payload = engine.search(
            case["query"],
            5,
            active_providers,
            provider_funcs,
            retries=max(1, min(int(retries or 1), 4)),
            use_cache=use_cache and not offline_mock,
        )
        ranked = payload.get("results") or []
        all_attempts.extend(payload.get("attempts") or [])
        citation = citation_consistency(case["answer_claim"], ranked)
        domain_ok = any(_domain_hit(item, case.get("expected_domains") or []) for item in ranked[:3])
        terms_ok = _term_hit(ranked[:5], case.get("expected_terms") or [])
        reasons = _case_failure_reasons(payload, citation, domain_ok, terms_ok)
        passed = bool(ranked) and citation.get("status") == "pass" and (domain_ok or terms_ok)
        top = ranked[0] if ranked else {}
        results.append({
            "name": case["name"],
            "scenario": case["scenario"],
            "query": case["query"],
            "pass": passed,
            "citation_hit": citation.get("status") == "pass",
            "citation_status": citation.get("status"),
            "domain_hit": domain_ok,
            "term_hit": terms_ok,
            "provider": payload.get("provider") or "",
            "source_count": len(ranked),
            "top_url": top.get("url", ""),
            "top_domain": top.get("domain", ""),
            "render_js_required": bool(case.get("render_js_required")),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "failure_reason": ";".join(reasons),
            "attempts": payload.get("attempts") or [],
        })

    by_scenario: dict[str, dict[str, Any]] = {}
    for item in results:
        bucket = by_scenario.setdefault(item["scenario"], {"case_count": 0, "passed_count": 0, "failed_count": 0, "citation_hits": 0, "latencies": []})
        bucket["case_count"] += 1
        bucket["passed_count"] += 1 if item["pass"] else 0
        bucket["failed_count"] += 0 if item["pass"] else 1
        bucket["citation_hits"] += 1 if item["citation_hit"] else 0
        bucket["latencies"].append(float(item["latency_ms"]))
    for bucket in by_scenario.values():
        bucket["pass_rate"] = round(bucket["passed_count"] / max(1, bucket["case_count"]), 4)
        bucket["citation_hit_rate"] = round(bucket["citation_hits"] / max(1, bucket["case_count"]), 4)
        bucket["latency_p50_ms"] = _percentile(bucket.pop("latencies"), 0.50)

    latencies = [float(item["latency_ms"]) for item in results]
    passed_count = sum(1 for item in results if item["pass"])
    citation_hits = sum(1 for item in results if item["citation_hit"])
    provider_health = provider_health_summary(all_attempts, ["mock"] if offline_mock else providers)
    report = {
        "name": "search-live-acceptance-40case",
        "mode": "offline_mock" if offline_mock else "live",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "pass_rate": round(passed_count / max(1, len(results)), 4),
        "citation_hit_rate": round(citation_hits / max(1, len(results)), 4),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "provider_health": provider_health,
        "provider_success_rate": round(sum(item["ok_count"] for item in provider_health["providers"]) / max(1, sum(item["attempt_count"] for item in provider_health["providers"])), 4),
        "by_scenario": by_scenario,
        "cases": results,
        "reproducible": {
            "input_case_names": [item["name"] for item in cases],
            "providers": ["mock"] if offline_mock else providers,
            "retries": retries,
            "use_cache": use_cache and not offline_mock,
        },
    }
    artifact = ArtifactStorage(out_dir).write_json("live_search_report.json", report)
    report["artifact"] = artifact
    report["report_path"] = artifact.get("path", str(Path(out_dir) / "live_search_report.json"))
    Path(report["report_path"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ClawOS live web search acceptance and provider health smoke tests.")
    parser.add_argument("--out", default=str(REPO_ROOT / "output" / "search_evidence"))
    parser.add_argument("--providers", default="tavily,serpapi,bing,duckduckgo")
    parser.add_argument("--limit-cases", type=int, default=len(LIVE_CASES))
    parser.add_argument("--offline-mock", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any case fails.")
    args = parser.parse_args()
    report = run_live_suite(
        Path(args.out),
        providers=[item.strip() for item in args.providers.split(",") if item.strip()],
        limit_cases=args.limit_cases,
        offline_mock=args.offline_mock,
        retries=args.retries,
        use_cache=not args.no_cache,
    )
    print(json.dumps({
        "ok": report["failed_count"] == 0,
        "mode": report["mode"],
        "case_count": report["case_count"],
        "passed_count": report["passed_count"],
        "failed_count": report["failed_count"],
        "citation_hit_rate": report["citation_hit_rate"],
        "latency_p50_ms": report["latency_p50_ms"],
        "latency_p95_ms": report["latency_p95_ms"],
        "provider_success_rate": report["provider_success_rate"],
        "report_path": report["report_path"],
    }, ensure_ascii=False))
    return 1 if args.strict and report["failed_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
