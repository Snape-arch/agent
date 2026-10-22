from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TRUSTED_DOMAIN_HINTS = (
    ".gov",
    ".edu",
    "who.int",
    "nih.gov",
    "nasa.gov",
    "docs.",
    "developer.",
    "arxiv.org",
    "acm.org",
    "ieee.org",
    "nature.com",
    "science.org",
    "openai.com",
    "microsoft.com",
    "google.com",
    "python.org",
)

COMMUNITY_DOMAIN_HINTS = (
    "stackoverflow.com",
    "stackexchange.com",
    "users.rust-lang.org",
    "zhihu.com",
    "juejin.cn",
    "csdn.net",
    "segmentfault.com",
    "v2ex.com",
    "reddit.com",
    "medium.com",
    "substack.com",
)

ACADEMIC_DOMAIN_HINTS = (
    "arxiv.org",
    "acm.org",
    "ieee.org",
    "nature.com",
    "science.org",
    "semanticscholar.org",
    "scholar.google.",
)

EXPLICIT_SEARCH_PATTERNS = (
    r"联网", r"搜索", r"检索", r"查一下", r"查证", r"核实", r"来源", r"网页链接",
    r"search\b", r"browse\b", r"look\s*up", r"verify", r"source(?:s)?\b", r"citation(?:s)?\b",
)
FRESHNESS_PATTERNS = (
    r"最新", r"最近", r"今天", r"当前", r"现在", r"实时", r"刚刚", r"近期",
    r"latest", r"recent", r"today", r"current", r"now", r"up[- ]to[- ]date",
)


SEARCH_EXPLICIT_PATTERNS = (
    r"联网", r"搜索", r"检索", r"查一下", r"查证", r"核实", r"来源", r"网页链接",
    r"search\b", r"browse\b", r"look\s*up", r"verify", r"source(?:s)?\b", r"citation(?:s)?\b",
)
SEARCH_FRESHNESS_PATTERNS = (
    r"最新", r"最近", r"今天", r"当前", r"现在", r"实时", r"刚刚", r"近期",
    r"latest", r"recent", r"today", r"current", r"now", r"up[- ]to[- ]date",
)
SEARCH_HIGH_RISK_PATTERNS = (
    r"诊断", r"治疗", r"用药", r"剂量", r"法律意见", r"是否合法", r"合同风险",
    r"税务", r"投资建议", r"保险理赔", r"合规要求", r"diagnos", r"treatment",
    r"medication", r"dosage", r"legal advice", r"tax law", r"investment advice",
    r"regulation", r"compliance requirement",
)
SEARCH_EXPERIENCE_PATTERNS = (
    r"经验", r"实践", r"踩坑", r"口碑", r"真实使用", r"社区观点", r"大家怎么",
    r"推荐", r"选型", r"对比", r"评测", r"值不值得", r"如何选择", r"experience",
    r"best practice", r"pitfall", r"community", r"real[- ]world", r"recommend",
    r"which should", r"compare", r"review",
)


def decide_search_need(
    query: str,
    *,
    mode: str = "auto",
    has_attachments: bool = False,
    local_context_sufficient: bool = False,
) -> dict[str, Any]:
    """Decide whether web access adds material value to this request.

    Explicit user requests override the UI's proactive-search switch. Auto mode is
    deliberately conservative: stable explanations and attached-document reading
    stay local, while freshness and external verification trigger research.
    """
    text = str(query or "").strip().lower()
    normalized_mode = mode if mode in {"off", "auto", "force"} else "auto"
    explicit_terms = ("\u8054\u7f51", "\u641c\u7d22", "\u68c0\u7d22", "\u67e5\u4e00\u4e0b", "\u67e5\u8bc1", "\u6838\u5b9e", "\u6765\u6e90")
    freshness_terms = ("\u6700\u65b0", "\u6700\u8fd1", "\u4eca\u5929", "\u5f53\u524d", "\u73b0\u5728", "\u5b9e\u65f6", "\u8fd1\u671f")
    high_risk_terms = ("\u8bca\u65ad", "\u6cbb\u7597", "\u7528\u836f", "\u5242\u91cf", "\u6cd5\u5f8b", "\u5408\u6cd5", "\u5408\u540c\u98ce\u9669", "\u5408\u89c4", "\u7a0e\u52a1", "\u6295\u8d44\u5efa\u8bae", "\u4fdd\u9669\u7406\u8d54")
    experience_terms = ("\u7ecf\u9a8c", "\u5b9e\u8df5", "\u8e29\u5751", "\u53e3\u7891", "\u771f\u5b9e\u4f7f\u7528", "\u793e\u533a\u89c2\u70b9", "\u63a8\u8350", "\u9009\u578b", "\u5bf9\u6bd4", "\u8bc4\u6d4b", "\u503c\u4e0d\u503c\u5f97", "\u5982\u4f55\u9009\u62e9")
    explicit = any(term in text for term in explicit_terms) or any(re.search(pattern, text, re.I) for pattern in SEARCH_EXPLICIT_PATTERNS)
    freshness = any(term in text for term in freshness_terms) or any(re.search(pattern, text, re.I) for pattern in SEARCH_FRESHNESS_PATTERNS)
    high_risk = any(term in text for term in high_risk_terms) or any(re.search(pattern, text, re.I) for pattern in SEARCH_HIGH_RISK_PATTERNS)
    experiential = any(term in text for term in experience_terms) or any(re.search(pattern, text, re.I) for pattern in SEARCH_EXPERIENCE_PATTERNS)
    local_sufficient = bool(local_context_sufficient or has_attachments)
    if normalized_mode == "force":
        should_search, reason, confidence = True, "forced_by_request_mode", 1.0
    elif explicit:
        should_search, reason, confidence = True, "explicit_user_request", 0.98
    elif normalized_mode == "off":
        should_search, reason, confidence = False, "proactive_search_disabled", 0.98
    elif high_risk:
        should_search, reason, confidence = True, "high_stakes_verification_required", 0.95
    elif freshness:
        should_search, reason, confidence = True, "freshness_or_current_state_needed", 0.92
    elif local_sufficient:
        should_search, reason, confidence = False, "local_evidence_is_sufficient", 0.94
    elif experiential:
        should_search, reason, confidence = True, "independent_experience_adds_value", 0.84
    else:
        should_search, reason, confidence = False, "stable_answer_can_be_given_directly", 0.82
    if high_risk:
        source_policy, breadth = "authority_first", "deep"
        minimum_sources, minimum_domains, max_source_reads = 2, 2, 3
    elif experiential:
        source_policy, breadth = "authority_and_community", "balanced"
        minimum_sources, minimum_domains, max_source_reads = 3, 2, 3
    elif freshness:
        source_policy, breadth = "fresh_primary_sources", "balanced"
        minimum_sources, minimum_domains, max_source_reads = 2, 2, 2
    elif explicit or normalized_mode == "force":
        source_policy, breadth = "claim_appropriate_sources", "balanced"
        minimum_sources, minimum_domains, max_source_reads = 2, 1, 2
    else:
        source_policy, breadth = "local_first", "quick"
        minimum_sources, minimum_domains, max_source_reads = 0, 0, 0
    return {
        "should_search": should_search,
        "reason": reason,
        "confidence": confidence,
        "mode": normalized_mode,
        "explicit_request": explicit,
        "freshness_needed": freshness,
        "high_stakes": high_risk,
        "experiential": experiential,
        "local_context_sufficient": local_sufficient,
        "source_policy": source_policy,
        "breadth": breadth,
        "coverage": {
            "minimum_sources": minimum_sources,
            "minimum_domains": minimum_domains,
            "require_authoritative": bool(high_risk or freshness),
            "require_community": bool(experiential),
            "require_fresh": bool(freshness),
        },
        "max_source_reads": max_source_reads,
        "stop_when": "coverage requirements are met and remaining uncertainty is explicit",
    }


def classify_source_type(url: str) -> str:
    host = urllib.parse.urlparse(str(url or "")).netloc.lower()
    if any(hint in host for hint in COMMUNITY_DOMAIN_HINTS):
        return "community"
    if any(hint in host for hint in ACADEMIC_DOMAIN_HINTS) or host.endswith(".edu"):
        return "academic"
    if host.endswith(".gov") or ".gov." in host or any(hint in host for hint in ("who.int", "nih.gov", "docs.", "developer.")):
        return "official"
    return "other"


def build_query_plan(
    query: str,
    *,
    breadth: str = "balanced",
    decision: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    plan = [{"query": str(query or "").strip(), "facet": "primary"}]
    if breadth == "quick" or not plan[0]["query"]:
        return plan
    text = plan[0]["query"]
    is_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
    decision = decision or decide_search_need(text, mode="auto")
    exploratory = bool(decision.get("experiential")) or any(key in text.lower() for key in (
        "如何", "怎么", "为什么", "对比", "评测", "经验", "推荐", "实践", "踩坑", "观点",
        "如何", "怎么", "为什么", "对比", "评测", "经验", "推荐", "实践", "踩坑", "观点",
        "how", "why", "compare", "review", "experience", "recommend", "practice",
    ))
    if is_chinese and exploratory:
        plan.append({
            "query": f"{text} (site:zhihu.com OR site:juejin.cn OR site:csdn.net)",
            "facet": "community",
        })
    elif exploratory:
        plan.append({
            "query": f"{text} (site:reddit.com OR site:stackoverflow.com OR site:medium.com)",
            "facet": "community",
        })
    if decision.get("freshness_needed"):
        plan.append({
            "query": f"{text} {datetime.now(timezone.utc).year} official",
            "facet": "fresh_primary",
        })
    elif decision.get("high_stakes"):
        plan.append({
            "query": f"{text} official guidance primary source",
            "facet": "authoritative",
        })
    if breadth == "deep" and any(key in text.lower() for key in ("论文", "研究", "paper", "research")):
        plan.append({"query": f"{text} (site:arxiv.org OR site:acm.org OR site:nature.com)", "facet": "academic"})
    return plan[:3]


def evidence_sufficiency(
    results: list[dict[str, Any]], decision: dict[str, Any]
) -> dict[str, Any]:
    """Return a deterministic stop signal for evidence acquisition."""
    coverage = decision.get("coverage") or {}
    credible = [
        item for item in results
        if item.get("credibility") in {"high", "medium"}
        and float((item.get("scores") or {}).get("relevance", 0)) >= 0.12
    ]
    domains = {str(item.get("domain") or "") for item in credible if item.get("domain")}
    authoritative = [item for item in credible if item.get("source_type") in {"official", "academic"}]
    community = [item for item in credible if item.get("source_type") == "community"]
    fresh = [item for item in credible if float((item.get("scores") or {}).get("freshness", 0)) >= 0.75]
    missing = []
    if len(credible) < int(coverage.get("minimum_sources") or 0):
        missing.append("source_count")
    if len(domains) < int(coverage.get("minimum_domains") or 0):
        missing.append("domain_diversity")
    if coverage.get("require_authoritative") and not authoritative:
        missing.append("authoritative_source")
    if coverage.get("require_community") and not community:
        missing.append("community_experience")
    if coverage.get("require_fresh") and not fresh:
        missing.append("fresh_source")
    enough = not missing
    return {
        "enough_to_stop_search": enough,
        "answer_ready": enough and bool(credible),
        "missing": missing,
        "credible_sources": len(credible),
        "domains": len(domains),
        "authoritative_sources": len(authoritative),
        "community_sources": len(community),
        "fresh_sources": len(fresh),
        "reason": "evidence_coverage_met" if enough else "additional_evidence_lane_needed",
    }


def select_diverse_results(
    results: list[dict[str, Any]],
    limit: int,
    *,
    require_community: bool = True,
    authority_first: bool = False,
) -> list[dict[str, Any]]:
    """Keep ranking quality while preventing one domain from filling the answer."""
    if authority_first:
        results = sorted(
            results,
            key=lambda item: (
                item.get("source_type") not in {"official", "academic"},
                -float((item.get("scores") or {}).get("source_score", 0)),
            ),
        )
    selected: list[dict[str, Any]] = []
    domain_counts: dict[str, int] = {}
    for item in results:
        domain = str(item.get("domain") or "")
        if domain and domain_counts.get(domain, 0) >= 2:
            continue
        selected.append(item)
        if domain:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if len(selected) >= limit:
            break
    if require_community and limit >= 4 and not any(item.get("source_type") == "community" for item in selected):
        community = next((item for item in results if item.get("source_type") == "community"), None)
        if community and float(community.get("scores", {}).get("relevance", 0)) >= 0.15:
            if len(selected) >= limit:
                selected[-1] = community
            else:
                selected.append(community)
    return selected[:limit]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tokens(value: str) -> set[str]:
    return {item for item in re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]{2,}", str(value or "").lower())}


def clean_html_text(value: str) -> str:
    value = re.sub(r"<(script|style|noscript|svg|canvas)[\s\S]*?</\1>", " ", str(value or ""), flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def safe_cache_key(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class JsonFileCache:
    def __init__(self, path: str | Path, ttl_seconds: int = 3600):
        self.path = Path(path)
        self.ttl_seconds = int(ttl_seconds)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get(self, key: str) -> Any:
        data = self._load()
        item = data.get(key)
        if not item:
            return None
        if time.time() - float(item.get("created_ts", 0)) > self.ttl_seconds:
            return None
        payload = item.get("payload")
        if isinstance(payload, dict):
            payload = dict(payload)
            payload["cache_hit"] = True
        return payload

    def set(self, key: str, payload: Any) -> None:
        data = self._load()
        data[key] = {"created_ts": time.time(), "created_at": _now_iso(), "payload": payload}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class FileRateLimiter:
    def __init__(self, path: str | Path, max_per_minute: int = 30):
        self.path = Path(path)
        self.max_per_minute = max(1, int(max_per_minute))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def check(self, bucket: str) -> dict[str, Any]:
        now = time.time()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except Exception:
            data = {}
        rows = [float(ts) for ts in data.get(bucket, []) if now - float(ts) < 60]
        allowed = len(rows) < self.max_per_minute
        if allowed:
            rows.append(now)
            data[bucket] = rows
            self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return {
            "allowed": allowed,
            "bucket": bucket,
            "remaining": max(0, self.max_per_minute - len(rows)),
            "reset_seconds": 60 if not rows else max(0, round(60 - (now - min(rows)), 2)),
        }


class SearchEvidenceEngine:
    def __init__(
        self,
        cache_path: str | Path,
        rate_path: str | Path,
        *,
        cache_ttl_seconds: int = 3600,
        max_per_minute: int = 30,
    ):
        self.cache = JsonFileCache(cache_path, cache_ttl_seconds)
        self.rate_limiter = FileRateLimiter(rate_path, max_per_minute)

    @staticmethod
    def score_source(query: str, item: dict[str, Any]) -> dict[str, Any]:
        url = str(item.get("url") or "")
        host = urllib.parse.urlparse(url).netloc.lower()
        text = " ".join([str(item.get("title", "")), str(item.get("snippet", "")), url])
        q_tokens = _tokens(query)
        t_tokens = _tokens(text)
        relevance = len(q_tokens & t_tokens) / max(1, len(q_tokens))
        authority = 0.45 if any(hint in host for hint in TRUSTED_DOMAIN_HINTS) else 0.18
        if host.endswith(".gov") or host.endswith(".edu"):
            authority += 0.2
        if str(item.get("source", "")).lower() in {"tavily", "bing", "serpapi"}:
            authority += 0.08
        rank = max(1, int(item.get("rank") or 1))
        rank_score = max(0.0, 1.0 - (rank - 1) * 0.08)
        freshness = SearchEvidenceEngine.freshness_score(item.get("published_at", ""))
        score = round(min(1.0, relevance * 0.42 + authority * 0.32 + rank_score * 0.16 + freshness * 0.10), 4)
        return {
            **item,
            "domain": host,
            "source_type": classify_source_type(url),
            "scores": {
                "source_score": score,
                "relevance": round(relevance, 4),
                "authority": round(min(authority, 1.0), 4),
                "freshness": freshness,
                "rank_prior": round(rank_score, 4),
            },
            "credibility": "high" if score >= 0.72 else ("medium" if score >= 0.45 else "low"),
        }

    @staticmethod
    def freshness_score(value: Any) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.25
        match = re.search(r"(20\d{2}|19\d{2})[-/年.]?(\d{1,2})?[-/月.]?(\d{1,2})?", text)
        if not match:
            return 0.35
        year = int(match.group(1))
        month = int(match.group(2) or 1)
        day = int(match.group(3) or 1)
        try:
            dt = datetime(year, month, day, tzinfo=timezone.utc)
            days = max(0, (datetime.now(timezone.utc) - dt).days)
        except Exception:
            return 0.35
        if days <= 30:
            return 1.0
        if days <= 365:
            return 0.75
        if days <= 1095:
            return 0.45
        return 0.2

    def search(
        self,
        query: str,
        limit: int,
        providers: list[str],
        provider_funcs: dict[str, Callable[[str, int], tuple[list[dict[str, Any]], str]]],
        *,
        retries: int = 2,
        use_cache: bool = True,
        breadth: str = "balanced",
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = decision or decide_search_need(query, mode="auto")
        effective_breadth = str(decision.get("breadth") or breadth)
        query_plan = build_query_plan(query, breadth=effective_breadth, decision=decision)
        key = safe_cache_key("search", query, limit, providers, query_plan)
        if use_cache:
            cached = self.cache.get(key)
            if cached:
                return cached
        rate = self.rate_limiter.check("web_search")
        if not rate["allowed"]:
            return {"error": "rate_limited", "error_type": "rate_limited", "query": query, "results": [], "rate_limit": rate}
        attempts: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = []
        successful_provider = ""
        for provider in providers:
            fn = provider_funcs.get(str(provider).lower())
            if not fn:
                continue
            for attempt in range(1, max(1, retries) + 1):
                started = time.perf_counter()
                try:
                    rows, error_type = fn(query, limit)
                    attempts.append({
                        "provider": provider,
                        "facet": "primary",
                        "attempt": attempt,
                        "ok": bool(rows),
                        "error_type": error_type,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    })
                    if rows:
                        all_rows.extend(rows)
                        successful_provider = str(provider).lower()
                        break
                except Exception as exc:
                    attempts.append({
                        "provider": provider,
                        "facet": "primary",
                        "attempt": attempt,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:200],
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    })
            if len(all_rows) >= limit:
                break
        preliminary_ranked = [self.score_source(query, row) for row in all_rows]
        preliminary_ranked.sort(
            key=lambda item: item.get("scores", {}).get("source_score", 0),
            reverse=True,
        )
        preliminary_coverage = decision.get("coverage") or {}
        preliminary_selected = select_diverse_results(
            preliminary_ranked,
            limit,
            require_community=bool(preliminary_coverage.get("require_community")),
            authority_first=bool(preliminary_coverage.get("require_authoritative")),
        )
        preliminary_sufficiency = evidence_sufficiency(preliminary_selected, decision)
        if (
            successful_provider
            and len(query_plan) > 1
            and not preliminary_sufficiency["enough_to_stop_search"]
        ):
            fn = provider_funcs.get(successful_provider)
            for query_variant in query_plan[1:]:
                started = time.perf_counter()
                try:
                    rows, error_type = fn(query_variant["query"], max(3, limit // 2)) if fn else ([], "provider_unavailable")
                    attempts.append({
                        "provider": successful_provider,
                        "facet": query_variant["facet"],
                        "attempt": 1,
                        "ok": bool(rows),
                        "error_type": error_type,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    })
                    for row in rows:
                        all_rows.append({**row, "query_facet": query_variant["facet"]})
                except Exception as exc:
                    attempts.append({
                        "provider": successful_provider,
                        "facet": query_variant["facet"],
                        "attempt": 1,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:200],
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    })
        deduped: dict[str, dict[str, Any]] = {}
        for row in all_rows:
            url = str(row.get("url") or "").split("#", 1)[0]
            if url and url not in deduped:
                deduped[url] = row
        ranked = [self.score_source(query, row) for row in deduped.values()]
        ranked.sort(key=lambda item: item.get("scores", {}).get("source_score", 0), reverse=True)
        coverage = decision.get("coverage") or {}
        selected = select_diverse_results(
            ranked,
            limit,
            require_community=bool(coverage.get("require_community")),
            authority_first=bool(coverage.get("require_authoritative")),
        )
        sufficiency = evidence_sufficiency(selected, decision)
        payload = {
            "query": query,
            "query_plan": query_plan,
            "provider": next((a["provider"] for a in attempts if a.get("ok")), ""),
            "results": selected,
            "attempts": attempts,
            "provider_health": provider_health_summary(attempts, providers),
            "cache_hit": False,
            "rate_limit": rate,
            "quality_summary": self.quality_summary(selected),
            "search_policy": decision,
            "evidence_sufficiency": sufficiency,
            "stop_search": sufficiency["enough_to_stop_search"],
            "expansion_skipped": bool(
                len(query_plan) > 1
                and preliminary_sufficiency["enough_to_stop_search"]
            ),
        }
        if ranked and use_cache:
            self.cache.set(key, payload)
        if not ranked:
            payload.update({"error": "Search failed across providers", "error_type": "all_providers_failed"})
        return payload

    @staticmethod
    def quality_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
        if not results:
            return {"source_count": 0, "high_credibility": 0, "avg_source_score": 0.0}
        scores = [float(item.get("scores", {}).get("source_score", 0)) for item in results]
        return {
            "source_count": len(results),
            "high_credibility": sum(1 for item in results if item.get("credibility") == "high"),
            "avg_source_score": round(sum(scores) / len(scores), 4),
            "domains": sorted({item.get("domain", "") for item in results if item.get("domain")})[:8],
            "source_types": sorted({item.get("source_type", "other") for item in results}),
            "community_count": sum(1 for item in results if item.get("source_type") == "community"),
        }

    def fetch(
        self,
        url: str,
        *,
        max_chars: int = 4000,
        render_js: bool = False,
        use_cache: bool = True,
        retries: int = 2,
    ) -> dict[str, Any]:
        key = safe_cache_key("fetch", url, max_chars, render_js)
        if use_cache:
            cached = self.cache.get(key)
            if cached:
                return cached
        rate = self.rate_limiter.check("web_fetch")
        if not rate["allowed"]:
            return {"error": "rate_limited", "error_type": "rate_limited", "url": url, "rate_limit": rate}
        last_error = ""
        for attempt in range(1, max(1, retries) + 1):
            try:
                payload = self.render_fetch(url, max_chars=max_chars) if render_js else self.http_fetch(url, max_chars=max_chars)
                payload.update({"cache_hit": False, "attempt": attempt, "rate_limit": rate})
                payload["source_quality"] = self.score_source(url, {
                    "url": payload.get("final_url") or url,
                    "title": payload.get("title", ""),
                    "snippet": payload.get("text", "")[:400],
                    "rank": 1,
                    "source": "browser" if render_js else "http",
                    "published_at": payload.get("published_at", ""),
                }).get("scores")
                if use_cache:
                    self.cache.set(key, payload)
                return payload
            except Exception as exc:
                last_error = str(exc)[:300]
        return {"error": f"Fetch failed: {last_error}", "error_type": "fetch_failed", "url": url, "rate_limit": rate}

    @staticmethod
    def http_fetch(url: str, *, max_chars: int = 4000) -> dict[str, Any]:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClawOS/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(2_000_000)
            final_url = resp.geturl()
            status = getattr(resp, "status", 200)
            content_type = resp.headers.get("content-type", "")
        charset_match = re.search(r"charset=([\w.-]+)", content_type, re.I)
        charset = charset_match.group(1) if charset_match else "utf-8"
        html_text = raw.decode(charset, errors="replace")
        return SearchEvidenceEngine.extract_page(url, final_url, status, content_type, html_text, max_chars, rendered=False)

    @staticmethod
    def render_fetch(url: str, *, max_chars: int = 4000) -> dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError(f"playwright_unavailable: {exc}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=20000)
            html_text = page.content()
            final_url = page.url
            title = page.title()
            browser.close()
        payload = SearchEvidenceEngine.extract_page(url, final_url, 200, "text/html; rendered=playwright", html_text, max_chars, rendered=True)
        if title:
            payload["title"] = title
        return payload

    @staticmethod
    def extract_page(url: str, final_url: str, status: int, content_type: str, html_text: str, max_chars: int, *, rendered: bool) -> dict[str, Any]:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
        title = clean_html_text(title_match.group(1)) if title_match else ""
        links = []
        for href, label in re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, re.I | re.S)[:80]:
            clean_label = clean_html_text(label)
            abs_url = urllib.parse.urljoin(final_url, href)
            if clean_label and abs_url.startswith(("http://", "https://")):
                links.append({"text": clean_label[:120], "url": abs_url})
            if len(links) >= 20:
                break
        text = clean_html_text(html_text)
        return {
            "url": url,
            "final_url": final_url,
            "status": status,
            "content_type": content_type,
            "title": title,
            "text": text[:max(500, min(max_chars, 12000))],
            "text_length": len(text),
            "links": links,
            "truncated": len(text) > max_chars,
            "rendered": rendered,
        }


def citation_consistency(answer: str, sources: list[dict[str, Any]], *, min_overlap: float = 0.34) -> dict[str, Any]:
    claims = [
        item.strip()
        for item in re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", str(answer or ""))
        if len(item.strip()) >= 12
    ]
    source_texts = [
        " ".join([str(item.get("title", "")), str(item.get("snippet", "")), str(item.get("text", ""))])
        for item in sources
    ]
    checked = []
    for claim in claims:
        c_tokens = _tokens(claim)
        best = {"overlap": 0.0, "source_index": -1, "url": ""}
        for idx, text in enumerate(source_texts):
            s_tokens = _tokens(text)
            overlap = len(c_tokens & s_tokens) / max(1, len(c_tokens))
            if overlap > best["overlap"]:
                best = {"overlap": round(overlap, 4), "source_index": idx, "url": sources[idx].get("url", "")}
        checked.append({
            "claim": claim,
            "supported": best["overlap"] >= min_overlap,
            **best,
        })
    unsupported = [item for item in checked if not item["supported"]]
    return {
        "status": "pass" if not unsupported and checked else "fail",
        "claim_count": len(checked),
        "supported_count": len(checked) - len(unsupported),
        "unsupported_count": len(unsupported),
        "claims": checked,
        "anti_hallucination_gate": {
            "status": "pass" if not unsupported and checked else "revision_required",
            "required_rework": [item["claim"] for item in unsupported],
        },
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def provider_health_summary(attempts: list[dict[str, Any]], providers: list[str] | None = None) -> dict[str, Any]:
    provider_names = [str(item).lower() for item in (providers or []) if str(item).strip()]
    buckets: dict[str, dict[str, Any]] = {
        name: {"provider": name, "attempt_count": 0, "ok_count": 0, "latencies": [], "error_types": {}}
        for name in provider_names
    }
    for attempt in attempts or []:
        provider = str(attempt.get("provider") or "unknown").lower()
        bucket = buckets.setdefault(provider, {"provider": provider, "attempt_count": 0, "ok_count": 0, "latencies": [], "error_types": {}})
        bucket["attempt_count"] += 1
        if attempt.get("ok"):
            bucket["ok_count"] += 1
        latency = attempt.get("latency_ms")
        if latency is not None:
            try:
                bucket["latencies"].append(float(latency))
            except (TypeError, ValueError):
                pass
        error_type = str(attempt.get("error_type") or "").strip()
        if error_type and error_type not in {"", "none"}:
            bucket["error_types"][error_type] = bucket["error_types"].get(error_type, 0) + 1

    rows = []
    for name in sorted(buckets):
        bucket = buckets[name]
        attempt_count = int(bucket["attempt_count"])
        ok_count = int(bucket["ok_count"])
        success_rate = round(ok_count / max(1, attempt_count), 4) if attempt_count else 0.0
        if not attempt_count:
            status = "untested"
        elif success_rate >= 0.8:
            status = "healthy"
        elif success_rate > 0:
            status = "degraded"
        else:
            status = "down"
        error_types = dict(sorted(bucket["error_types"].items(), key=lambda item: (-item[1], item[0])))
        rows.append({
            "provider": name,
            "status": status,
            "attempt_count": attempt_count,
            "ok_count": ok_count,
            "failed_count": max(0, attempt_count - ok_count),
            "success_rate": success_rate,
            "latency_p50_ms": _percentile(bucket["latencies"], 0.50),
            "latency_p95_ms": _percentile(bucket["latencies"], 0.95),
            "error_types": error_types,
            "last_error_type": next(iter(error_types.keys()), ""),
        })
    return {
        "providers": rows,
        "configured_count": len(provider_names),
        "attempt_count": sum(item["attempt_count"] for item in rows),
        "healthy_count": sum(1 for item in rows if item["status"] == "healthy"),
        "degraded_count": sum(1 for item in rows if item["status"] == "degraded"),
        "down_count": sum(1 for item in rows if item["status"] == "down"),
        "untested_count": sum(1 for item in rows if item["status"] == "untested"),
    }
