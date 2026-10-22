from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


CLAWOS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLAWOS_ROOT.parent
if str(CLAWOS_ROOT) not in sys.path:
    sys.path.insert(0, str(CLAWOS_ROOT))

from scripts.search_live_acceptance import _provider_funcs
from services.search_provider_benchmark_service import DEFAULT_CORPUS, run_provider_benchmark


def answer_generator_from_env():
    from providers.openai_compatible import OpenAICompatibleProvider

    base_url = os.environ.get("CLAWOS_SEARCH_ANSWER_BASE_URL", "").strip()
    model = os.environ.get("CLAWOS_SEARCH_ANSWER_MODEL", "").strip()
    api_key = os.environ.get("CLAWOS_SEARCH_ANSWER_API_KEY", "").strip()
    if not (base_url and model and api_key):
        return None
    provider = OpenAICompatibleProvider({
        "provider": "search_answer_model", "base_url": base_url, "model": model,
        "api_key": api_key, "timeout_s": 90,
    })

    def generate(case, results):
        evidence = [{
            "title": item.get("title", ""), "url": item.get("url", ""),
            "snippet": str(item.get("snippet") or item.get("text") or "")[:700],
        } for item in results[:6]]
        messages = [
            {"role": "system", "content": "Answer only from supplied evidence. Write a concise natural answer with descriptive Markdown links immediately after supported claims. Do not mention searching."},
            {"role": "user", "content": json.dumps({"question": case["query"], "evidence": evidence}, ensure_ascii=False)},
        ]
        result = asyncio.run(provider.complete(messages, {"temperature": 0.0, "max_tokens": 900}))
        return {
            "ok": bool(result.get("ok")), "answer": result.get("content", ""),
            "provider": result.get("provider", ""), "model": result.get("model", ""),
            "error": result.get("error", ""), "duration_ms": result.get("duration_ms", 0),
        }
    return generate


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate ClawOS search decisions and live provider evidence quality.")
    parser.add_argument("--out", default=str(REPO_ROOT / "output" / "search_evidence"))
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--providers", default="tavily,serpapi,bing,duckduckgo")
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--offline-mock", action="store_true")
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    providers = [item.strip().lower() for item in args.providers.split(",") if item.strip()]
    report = run_provider_benchmark(
        args.out, providers=providers, provider_funcs={} if args.offline_mock else _provider_funcs(),
        corpus_path=args.corpus, limit_cases=args.limit_cases, offline_mock=args.offline_mock,
        retries=args.retries, use_cache=args.use_cache, answer_generator=answer_generator_from_env(),
    )
    print(json.dumps({
        "mode": report["mode"], "real_provider_evaluated": report["real_provider_evaluated"],
        "real_provider_usable": report["real_provider_usable"],
        "case_count": report["case_count"], "trigger_accuracy": report["search_trigger"]["accuracy"],
        "citation_hit_rate": report["citation_hit_rate"],
        "community_source_coverage_rate": report["community_source_coverage_rate"],
        "evidence_ready_answer_quality_pass_rate": report["evidence_ready_answer_quality_pass_rate"],
        "generated_answer_quality": report["generated_answer_quality"],
        "acceptance": report["acceptance"], "report_path": report["report_path"],
    }, ensure_ascii=False))
    return 1 if args.strict and not report["acceptance"]["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
