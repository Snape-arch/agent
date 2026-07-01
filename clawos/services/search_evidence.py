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
    ) -> dict[str, Any]:
        key = safe_cache_key("search", query, limit, providers)
        if use_cache:
            cached = self.cache.get(key)
            if cached:
                return cached
        rate = self.rate_limiter.check("web_search")
        if not rate["allowed"]:
            return {"error": "rate_limited", "error_type": "rate_limited", "query": query, "results": [], "rate_limit": rate}
        attempts: list[dict[str, Any]] = []
        all_rows: list[dict[str, Any]] = []
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
                        "attempt": attempt,
                        "ok": bool(rows),
                        "error_type": error_type,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    })
                    if rows:
                        all_rows.extend(rows)
                        break
                except Exception as exc:
                    attempts.append({
                        "provider": provider,
                        "attempt": attempt,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:200],
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    })
            if len(all_rows) >= limit:
                break
        deduped: dict[str, dict[str, Any]] = {}
        for row in all_rows:
            url = str(row.get("url") or "").split("#", 1)[0]
            if url and url not in deduped:
                deduped[url] = row
        ranked = [self.score_source(query, row) for row in deduped.values()]
        ranked.sort(key=lambda item: item.get("scores", {}).get("source_score", 0), reverse=True)
        payload = {
            "query": query,
            "provider": next((a["provider"] for a in attempts if a.get("ok")), ""),
            "results": ranked[:limit],
            "attempts": attempts,
            "cache_hit": False,
            "rate_limit": rate,
            "quality_summary": self.quality_summary(ranked[:limit]),
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
