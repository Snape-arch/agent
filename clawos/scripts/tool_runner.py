import json, sys, os
from datetime import datetime, timezone, timedelta
import re
try:
    from . import scenario_tools
except ImportError:
    import scenario_tools

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
TODO_FILE = os.path.join(BASE_DIR, "clawos_todo.json")
NOTES_DIR = os.path.join(BASE_DIR, "notes")
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _memory_db_path():
    path = os.path.abspath(os.path.expanduser(
        os.environ.get("CLAWOS_MEMORY_DB", os.path.join(BASE_DIR, "memoryos.db"))
    ))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path

tool_name = os.path.splitext(os.path.basename(__file__))[0]
input_data = {}

SKILLS_DIR = os.path.join(BASE_DIR, "skills")
MEMORYOS_DIR = os.path.join(BASE_DIR, "memoryos")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
if SKILLS_DIR not in sys.path:
    sys.path.insert(0, SKILLS_DIR)
if MEMORYOS_DIR not in sys.path:
    sys.path.append(MEMORYOS_DIR)


def _scenario_tool(name):
    def _run():
        scenario_tools.print_result(name, input_data)
    return _run


def security_check(name, arguments):
    """Apply the same sandbox policy used by the API and MTClaw bridge."""
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    from security.policy import ToolSecurityPolicy
    result = ToolSecurityPolicy().evaluate(name, arguments)
    if result.get("allowed"):
        return result.get("normalized_arguments", arguments)
    raise PermissionError(result.get("reason", "Denied by security policy"))

def tool_weather():
    import urllib.request, urllib.parse
    city = input_data.get("city", "")
    if not city:
        print(json.dumps({"error": "missing city"})); sys.exit(1)
    try:
        city_coords = {"beijing": (39.9, 116.4), "shanghai": (31.2, 121.5), "guangzhou": (23.1, 113.3), "shenzhen": (22.5, 114.1), "chengdu": (30.6, 104.1), "hangzhou": (30.3, 120.2), "nanjing": (32.1, 118.8), "wuhan": (30.6, 114.3)}
        lat, lon = city_coords.get(city.lower().strip(), (39.9, 116.4))
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code,wind_speed_10m&timezone=auto"
        req = urllib.request.Request(url, headers={"User-Agent": "ClawOS/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            wmo = {0:"Clear",1:"Mainly clear",2:"Partly cloudy",3:"Overcast",45:"Fog",51:"Light drizzle",53:"Moderate drizzle",55:"Dense drizzle",61:"Slight rain",63:"Moderate rain",65:"Heavy rain",71:"Slight snow",73:"Moderate snow",75:"Heavy snow",80:"Rain showers",95:"Thunderstorm"}
            code = data["current"]["weather_code"]
            t = data["current"]["temperature_2m"]
            ws = data["current"]["wind_speed_10m"]
            wdesc = wmo.get(code, f"Code {code}")
            print(json.dumps({"city": city, "temperature_c": t, "weather": wdesc, "wind_speed_kmh": ws}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)

def tool_time_now():
    now = datetime.now()
    print(json.dumps({"datetime": now.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "Asia/Shanghai", "weekday": now.strftime("%A"), "timestamp_iso": now.isoformat()}))

def tool_calc():
    expr = input_data.get("expression", "")
    import math
    for func in ["sqrt","sin","cos","tan","log","log10","abs","ceil","floor","pow","pi","e"]:
        expr = expr.replace(f"math.{func}", f"__{func}__")
    for c in set(expr):
        if c not in "0123456789+-*/.() e_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ":
            print(json.dumps({"error": f"Unsafe character: {c}"})); sys.exit(1)
    try:
        code = expr
        for func in ["sqrt","sin","cos","tan","log10","abs","ceil","floor"]:
            code = code.replace(f"__{func}__", f"math.{func}")
        code = code.replace("__log__", "math.log").replace("__pow__", "math.pow")
        code = code.replace("__pi__", "math.pi").replace("__e__", "math.e")
        result = eval(code, {"__builtins__": {}, "math": math})
        print(json.dumps({"expression": input_data.get("expression",""), "result": result}))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)

def tool_todo_list():
    if not os.path.exists(TODO_FILE):
        with open(TODO_FILE, "w", encoding="utf-8") as f: json.dump([], f)
    with open(TODO_FILE, "r", encoding="utf-8") as f: todos = json.load(f)
    action = input_data.get("action", "read")
    if action == "read":
        items = [{"index": i+1, "text": t["text"], "done": t.get("done", False)} for i, t in enumerate(todos)]
        print(json.dumps({"items": items, "total": len(items)}, ensure_ascii=False))
    elif action == "add":
        text = (input_data.get("item") or "").strip()
        if not text: print(json.dumps({"error": "missing item"})); sys.exit(1)
        todos.append({"text": text, "done": False})
        with open(TODO_FILE, "w", encoding="utf-8") as f: json.dump(todos, f, ensure_ascii=False)
        print(json.dumps({"added": text, "total": len(todos)}, ensure_ascii=False))
    elif action == "done":
        idx = input_data.get("index", 0) - 1
        if 0 <= idx < len(todos):
            todos[idx]["done"] = True
            with open(TODO_FILE, "w", encoding="utf-8") as f: json.dump(todos, f, ensure_ascii=False)
            print(json.dumps({"marked_done": todos[idx]["text"]}, ensure_ascii=False))
        else:
            print(json.dumps({"error": f"Invalid index: {idx+1}"})); sys.exit(1)
    elif action == "clear":
        with open(TODO_FILE, "w", encoding="utf-8") as f: json.dump([], f)
        print(json.dumps({"cleared": True}))

def tool_note_save():
    os.makedirs(NOTES_DIR, exist_ok=True)
    title = (input_data.get("title") or "").strip()
    content = input_data.get("content", "")
    if not title: print(json.dumps({"error": "missing title"})); sys.exit(1)
    path = os.path.join(NOTES_DIR, f"{title}.txt")
    with open(path, "w", encoding="utf-8") as f: f.write(content)
    print(json.dumps({"saved": title, "size_bytes": len(content)}, ensure_ascii=False))

def tool_note_read():
    title = (input_data.get("title") or "").strip()
    if not title: print(json.dumps({"error": "missing title"})); sys.exit(1)
    path = os.path.join(NOTES_DIR, f"{title}.txt")
    if not os.path.exists(path):
        print(json.dumps({"error": f"Note not found: {title}"})); sys.exit(1)
    with open(path, "r", encoding="utf-8") as f: content = f.read()
    print(json.dumps({"title": title, "content": content[:2000]}, ensure_ascii=False))

def tool_note_list():
    os.makedirs(NOTES_DIR, exist_ok=True)
    files = [f[:-4] for f in os.listdir(NOTES_DIR) if f.endswith(".txt")]
    print(json.dumps({"notes": files, "count": len(files)}, ensure_ascii=False))

def tool_tools_list():
    functions_path = os.path.join(BASE_DIR, "functions.jsonl")
    tools = []
    try:
        with open(functions_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                tools.append({
                    "name": obj.get("name", ""),
                    "description": obj.get("description", ""),
                })
        print(json.dumps({"tools": tools, "count": len(tools)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)

def _http_json(url, headers=None, timeout=12):
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ClawOS/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _clean_html_text(value):
    import html as html_lib
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    value = html_lib.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _search_engine():
    from services.search_evidence import SearchEvidenceEngine
    data_dir = os.path.join(BASE_DIR, "data", "search_evidence")
    os.makedirs(data_dir, exist_ok=True)
    return SearchEvidenceEngine(
        os.path.join(data_dir, "cache.json"),
        os.path.join(data_dir, "rate_limits.json"),
        cache_ttl_seconds=int(os.environ.get("CLAWOS_SEARCH_CACHE_TTL", "3600") or 3600),
        max_per_minute=int(os.environ.get("CLAWOS_SEARCH_RATE_PER_MINUTE", "30") or 30),
    )


def _save_web_run(kind, title, payload):
    try:
        from memoryos.memory_store import MemoryStore
        from services.runtime_records import RunRecord
        run_id = f"{kind}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        ok = not payload.get("error") and (bool(payload.get("results")) or bool(payload.get("text")) or payload.get("failed_count", 0) == 0)
        run = RunRecord(
            run_id=run_id,
            run_type="web_evidence",
            title=title,
            status="pass" if ok else "blocked",
            actor="search-evidence-engine",
            scenario="web_research",
            inputs={"kind": kind, "query": payload.get("query", ""), "url": payload.get("url", "")},
            outputs=payload,
            metrics={
                "result_count": len(payload.get("results", []) or []),
                "attempt_count": len(payload.get("attempts", []) or []),
                "cache_hit": bool(payload.get("cache_hit")),
                "pass_rate": payload.get("pass_rate", 1.0 if ok else 0.0),
            },
            tags=["web", "search", "evidence", kind],
        )
        for item in (payload.get("results") or [])[:8]:
            run.add_evidence(
                "web_source",
                item.get("title") or item.get("url") or "source",
                citation=item.get("url", ""),
                score=float(item.get("scores", {}).get("source_score", 0) or 0),
                metadata={"domain": item.get("domain", ""), "credibility": item.get("credibility", "")},
            )
        if payload.get("final_url"):
            run.add_evidence("web_fetch", payload.get("title") or payload.get("final_url"), citation=payload.get("final_url"), score=float((payload.get("source_quality") or {}).get("source_score", 0) or 0))
        for case in payload.get("cases", []) or []:
            if not case.get("pass", True):
                run.add_failure_case("web_search_acceptance_failure", case.get("failure_reason", "case failed"), severity="high", input_summary=case.get("name", ""))
        if payload.get("error"):
            run.add_failure_case("web_evidence_error", payload.get("error"), severity="medium", input_summary=title, remediation="Check provider keys, network policy, cache state, and rate limits.")
        saved = MemoryStore(_memory_db_path()).save_run_record(run.to_dict())
        return saved
    except Exception as exc:
        return {"error": f"run_record_save_failed: {str(exc)[:160]}"}


def _search_tavily(query, limit):
    import urllib.request
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return [], "missing_key"
    payload = json.dumps({"query": query, "max_results": limit, "include_answer": False}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    rows = []
    for rank, item in enumerate(data.get("results") or [], 1):
        rows.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
            "source": "tavily",
            "published_at": item.get("published_date", ""),
            "rank": rank,
            "error_type": "",
        })
    return rows, ""


def _search_serpapi(query, limit):
    import urllib.parse
    key = os.environ.get("SERPAPI_API_KEY", "")
    if not key:
        return [], "missing_key"
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode({
        "q": query, "engine": "google", "api_key": key, "num": limit
    })
    data = _http_json(url, timeout=15)
    rows = []
    for rank, item in enumerate(data.get("organic_results") or [], 1):
        rows.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
            "source": "serpapi",
            "published_at": item.get("date", ""),
            "rank": rank,
            "error_type": "",
        })
    return rows, ""


def _search_bing(query, limit):
    import urllib.parse
    key = os.environ.get("BING_SEARCH_API_KEY", "")
    if not key:
        return [], "missing_key"
    endpoint = os.environ.get("BING_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search")
    url = endpoint + "?" + urllib.parse.urlencode({"q": query, "count": limit, "responseFilter": "Webpages"})
    data = _http_json(url, headers={"Ocp-Apim-Subscription-Key": key, "User-Agent": "ClawOS/1.0"}, timeout=15)
    rows = []
    for rank, item in enumerate((data.get("webPages") or {}).get("value") or [], 1):
        rows.append({
            "title": item.get("name", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "source": "bing",
            "published_at": item.get("dateLastCrawled", ""),
            "rank": rank,
            "error_type": "",
        })
    return rows, ""


def _search_duckduckgo(query, limit):
    import urllib.request, urllib.parse
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ClawOS/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        page = resp.read().decode("utf-8", errors="replace")
    blocks = re.findall(r'<div class="result[^"]*"[\s\S]*?</div>\s*</div>', page)
    rows = []
    for rank, block in enumerate(blocks[:limit], 1):
        title_match = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        snippet_match = re.search(r'class="result__snippet"[^>]*>(.*?)</a>|class="result__snippet"[^>]*>(.*?)</div>', block, re.S)
        if not title_match:
            continue
        raw_url = title_match.group(1)
        parsed = urllib.parse.urlparse(raw_url)
        params = urllib.parse.parse_qs(parsed.query)
        result_url = (params.get("uddg") or [raw_url])[0]
        snippet = snippet_match.group(1) or snippet_match.group(2) if snippet_match else ""
        rows.append({
            "title": _clean_html_text(title_match.group(2)),
            "url": urllib.parse.unquote(result_url),
            "snippet": _clean_html_text(snippet)[:400],
            "source": "duckduckgo",
            "published_at": "",
            "rank": rank,
            "error_type": "",
        })
    return rows, "" if rows else "empty_results"


def tool_web_search():
    query = str(input_data.get("query", "")).strip()
    if not query: print(json.dumps({"error": "missing query"})); sys.exit(1)
    limit = max(1, min(int(input_data.get("limit", 5) or 5), 10))
    providers = input_data.get("providers") or ["tavily", "serpapi", "bing", "duckduckgo"]
    engine = _search_engine()
    payload = engine.search(
        query,
        limit,
        [str(item).lower() for item in providers],
        {
            "tavily": _search_tavily,
            "serpapi": _search_serpapi,
            "bing": _search_bing,
            "duckduckgo": _search_duckduckgo,
        },
        retries=max(1, min(int(input_data.get("retries", 2) or 2), 4)),
        use_cache=bool(input_data.get("use_cache", True)),
    )
    payload["run_record"] = _save_web_run("web_search", query, payload)
    print(json.dumps(payload, ensure_ascii=False))
    if payload.get("error"):
        sys.exit(1)


def tool_web_fetch():
    url = str(input_data.get("url", "")).strip()
    max_chars = int(input_data.get("max_chars", 4000) or 4000)
    ingest = bool(input_data.get("ingest", False))
    category = str(input_data.get("category", "web") or "web")
    render_js = bool(input_data.get("render_js", False))
    if not url:
        print(json.dumps({"error": "missing url"})); sys.exit(1)
    if not re.match(r"^https?://", url, re.I):
        print(json.dumps({"error": "only http(s) URLs are supported"})); sys.exit(1)
    try:
        engine = _search_engine()
        result = engine.fetch(
            url,
            max_chars=max_chars,
            render_js=render_js,
            use_cache=bool(input_data.get("use_cache", True)),
            retries=max(1, min(int(input_data.get("retries", 2) or 2), 4)),
        )
        if result.get("error"):
            print(json.dumps(result, ensure_ascii=False)); sys.exit(1)
        if ingest:
            from pathlib import Path
            import hashlib
            from memoryos.memory_store import MemoryStore
            from memoryos.document_ingestion import ingest_file, safe_filename
            final_url = result.get("final_url") or url
            digest = hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:12]
            upload_dir = Path(BASE_DIR) / "uploads" / "web"
            upload_dir.mkdir(parents=True, exist_ok=True)
            name = safe_filename((result.get("title") or "web_page") + ".html")
            page_path = upload_dir / f"{digest}_{name}"
            page_path.write_text(result.get("text", ""), encoding="utf-8", errors="replace")
            store = MemoryStore(_memory_db_path())
            doc = ingest_file(store, upload_dir, page_path, title=result.get("title") or final_url, category=category)
            result["document"] = {
                "id": doc.get("id"),
                "title": doc.get("title"),
                "chunk_count": doc.get("chunk_count", 0),
                "citation_prefix": f"doc:{doc.get('id')}#",
            }
            result["ingested"] = True
        else:
            result["ingested"] = False
        result["run_record"] = _save_web_run("web_fetch", url, result)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"Fetch failed: {str(e)}"})); sys.exit(1)


def tool_web_citation_check():
    from services.search_evidence import citation_consistency
    answer = str(input_data.get("answer", "") or "")
    sources = input_data.get("sources") or input_data.get("results") or []
    if not answer:
        print(json.dumps({"error": "missing answer"})); sys.exit(1)
    if not isinstance(sources, list) or not sources:
        print(json.dumps({"error": "sources must be a non-empty list"})); sys.exit(1)
    result = citation_consistency(answer, sources, min_overlap=float(input_data.get("min_overlap", 0.34) or 0.34))
    print(json.dumps(result, ensure_ascii=False))


def _search_benchmark_cases():
    specs = [
        ("official_docs_python_datetime", "official_docs", "Python datetime timezone official documentation", "docs.python.org", "https://docs.python.org/3/library/datetime.html", "Official Python documentation explains timezone aware datetime objects.", "2026-01-01"),
        ("official_docs_fastapi_upload", "official_docs", "FastAPI UploadFile official documentation", "fastapi.tiangolo.com", "https://fastapi.tiangolo.com/tutorial/request-files/", "FastAPI official documentation describes UploadFile request files.", "2026-02-01"),
        ("official_docs_node_fetch", "official_docs", "Node.js fetch official documentation", "nodejs.org", "https://nodejs.org/api/globals.html#fetch", "Node.js official documentation describes global fetch behavior.", "2026-03-01"),
        ("official_docs_playwright", "official_docs", "Playwright locator official documentation", "playwright.dev", "https://playwright.dev/docs/locators", "Playwright official documentation explains locators and page interactions.", "2026-04-01"),
        ("official_docs_sqlite", "official_docs", "SQLite write ahead log official documentation", "sqlite.org", "https://www.sqlite.org/wal.html", "SQLite official documentation explains write ahead logging.", "2025-12-01"),
        ("official_docs_pytorch", "official_docs", "PyTorch inference mode official documentation", "pytorch.org", "https://pytorch.org/docs/stable/generated/torch.inference_mode.html", "PyTorch official documentation explains inference mode.", "2026-01-15"),
        ("news_fresh_clawos", "news_freshness", "ClawOS July 2026 release news", "docs.clawos.local", "https://docs.clawos.local/news/2026-07-02", "July 2026 ClawOS release news covers search evidence and ASR updates.", "2026-07-02"),
        ("news_fresh_ai_policy", "news_freshness", "AI policy update July 2026 official news", "gov.example", "https://gov.example/news/ai-policy-2026-07", "July 2026 official AI policy news describes compliance updates.", "2026-07-01"),
        ("news_fresh_security", "news_freshness", "security advisory July 2026 latest bulletin", "cisa.gov", "https://www.cisa.gov/news-events/alerts/2026/07/security-advisory", "Latest July 2026 security advisory bulletin lists affected systems.", "2026-07-01"),
        ("news_fresh_model", "news_freshness", "model platform release July 2026 changelog", "developer.example.com", "https://developer.example.com/changelog/2026-07", "July 2026 model platform changelog explains new release behavior.", "2026-07-02"),
        ("news_fresh_browser", "news_freshness", "browser stable release July 2026 notes", "developer.chrome.com", "https://developer.chrome.com/release-notes/2026-07", "July 2026 browser release notes summarize stable features.", "2026-07-01"),
        ("papers_rag_citations", "papers", "retrieval augmented generation citations paper", "arxiv.org", "https://arxiv.org/abs/2401.00001", "Retrieval augmented generation requires citations and evidence grounding.", "2024-01-01"),
        ("papers_multi_agent_eval", "papers", "multi agent evaluation benchmark paper", "arxiv.org", "https://arxiv.org/abs/2502.11111", "Multi agent evaluation benchmarks compare planner builder reviewer judge roles.", "2025-02-10"),
        ("papers_asr_noise", "papers", "automatic speech recognition noisy meeting paper", "ieee.org", "https://ieeexplore.ieee.org/document/1234567", "Noisy meeting automatic speech recognition papers measure WER and diarization.", "2025-06-01"),
        ("papers_rerank_embedding", "papers", "embedding rerank retrieval paper", "acm.org", "https://dl.acm.org/doi/10.1145/123456", "Embedding rerank retrieval papers evaluate citation hit rate and relevance.", "2024-09-01"),
        ("papers_workflow_agents", "papers", "workflow agent orchestration state machine paper", "arxiv.org", "https://arxiv.org/abs/2510.00002", "Workflow agent orchestration research uses state machines and quality gates.", "2025-10-01"),
        ("policy_nist_ai_rmf", "policy", "NIST AI risk management framework official", "nist.gov", "https://www.nist.gov/itl/ai-risk-management-framework", "NIST AI Risk Management Framework is an official policy resource.", "2025-01-01"),
        ("policy_eu_ai_act", "policy", "EU AI Act official regulation text", "europa.eu", "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai", "EU official AI Act policy describes regulatory framework for AI.", "2025-08-01"),
        ("policy_us_privacy", "policy", "FTC privacy official business guidance", "ftc.gov", "https://www.ftc.gov/business-guidance/privacy-security", "FTC official privacy guidance explains business security responsibilities.", "2025-07-01"),
        ("policy_china_algo", "policy", "中国 生成式人工智能 服务 管理 官方 政策", "gov.cn", "https://www.gov.cn/zhengce/zhengceku/2023-07/13/content_6891752.htm", "中国官方政策说明生成式人工智能服务管理要求。", "2024-01-01"),
        ("policy_cybersecurity", "policy", "cybersecurity incident reporting official rule", "cisa.gov", "https://www.cisa.gov/topics/cyber-threats-and-advisories/information-sharing/cyber-incident-reporting", "CISA official rule explains cyber incident reporting requirements.", "2025-04-01"),
        ("product_qwen_embedding", "product", "Qwen embedding model product documentation", "dashscope.aliyuncs.com", "https://dashscope.aliyuncs.com/docs/qwen/embedding", "Qwen embedding product documentation explains text embedding usage.", "2026-01-01"),
        ("product_deepseek_api", "product", "DeepSeek API product documentation", "api-docs.deepseek.com", "https://api-docs.deepseek.com/", "DeepSeek API product documentation explains chat model endpoints.", "2026-01-01"),
        ("product_whisper_cpp", "product", "whisper cpp model product documentation", "github.com", "https://github.com/ggerganov/whisper.cpp", "whisper.cpp product repository documents local speech recognition models.", "2026-01-01"),
        ("product_faster_whisper", "product", "faster whisper product documentation", "github.com", "https://github.com/SYSTRAN/faster-whisper", "faster-whisper documentation explains efficient Whisper transcription.", "2026-01-01"),
        ("product_playwright_browser", "product", "Playwright browser rendering product documentation", "playwright.dev", "https://playwright.dev/python/docs/intro", "Playwright documentation explains browser rendering automation.", "2026-01-01"),
        ("chinese_ai_learning", "chinese_web", "人工智能 学习 路线 官方 文档", "edu.cn", "https://www.edu.cn/ai/learning-path", "人工智能学习路线包含基础知识、实践项目和前沿主题。", "2025-09-01"),
        ("chinese_policy_data", "chinese_web", "数据安全 法 官方 解读", "gov.cn", "https://www.gov.cn/zhengce/2025/data-security", "官方解读说明数据安全法和企业合规要求。", "2025-06-01"),
        ("chinese_product_qwen", "chinese_web", "通义千问 向量 模型 文档", "help.aliyun.com", "https://help.aliyun.com/zh/model-studio/text-embedding", "通义千问向量模型文档说明文本向量和检索用法。", "2026-01-01"),
        ("chinese_research_rag", "chinese_web", "检索增强生成 引用 评测", "cnki.net", "https://www.cnki.net/article/rag-citation", "检索增强生成评测关注引用命中率和证据一致性。", "2025-05-01"),
        ("chinese_meeting_asr", "chinese_web", "会议 语音识别 行动项 提取", "developer.baidu.com", "https://developer.baidu.com/article/asr-meeting-actions", "会议语音识别需要摘要、决策和行动项提取。", "2025-10-01"),
        ("js_dashboard_prices", "js_page", "JavaScript dashboard product pricing rendered page", "app.example.com", "https://app.example.com/pricing", "JavaScript rendered pricing dashboard lists enterprise plans.", "2026-06-01"),
        ("js_docs_search", "js_page", "JavaScript documentation search rendered content", "docs.example.com", "https://docs.example.com/app/search", "JavaScript rendered documentation search exposes API examples.", "2026-06-15"),
        ("js_policy_portal", "js_page", "JavaScript policy portal latest regulation", "portal.gov.example", "https://portal.gov.example/regulations/latest", "JavaScript policy portal renders latest regulation summaries.", "2026-07-01"),
        ("js_research_catalog", "js_page", "JavaScript research catalog citations", "papers.example.edu", "https://papers.example.edu/catalog", "JavaScript research catalog renders citation metadata and abstracts.", "2026-05-01"),
        ("js_product_status", "js_page", "JavaScript product status page incident history", "status.example.com", "https://status.example.com/history", "JavaScript product status page renders incident history and uptime.", "2026-07-02"),
    ]
    cases = []
    for name, category, query, domain, url, snippet, published_at in specs:
        cases.append({
            "name": name,
            "category": category,
            "query": query,
            "expected_domain": domain,
            "render_js_required": category == "js_page",
            "answer": snippet,
            "mock_results": [
                {"title": name.replace("_", " ").title(), "url": url, "snippet": snippet, "source": "mock", "rank": 1 if category != "news_freshness" else 2, "published_at": published_at},
                {"title": "Low quality mirror", "url": f"https://mirror.example.net/{name}", "snippet": "A copied page with stale and weakly relevant information.", "source": "mock", "rank": 1, "published_at": "2020-01-01"},
            ],
        })
    return cases


def tool_web_search_benchmark():
    from services.search_evidence import SearchEvidenceEngine, citation_consistency
    engine = _search_engine()
    cases = _search_benchmark_cases()
    results = []
    for case in cases:
        ranked = [engine.score_source(case["query"], item) for item in case["mock_results"]]
        ranked.sort(key=lambda item: item["scores"]["source_score"], reverse=True)
        top_domain = ranked[0]["domain"] if ranked else ""
        citation = citation_consistency(case.get("answer", ranked[0]["snippet"] if ranked else ""), ranked)
        passed = case["expected_domain"] in top_domain and citation["status"] == "pass"
        results.append({
            "name": case["name"],
            "category": case.get("category", "general"),
            "render_js_required": bool(case.get("render_js_required")),
            "pass": passed,
            "top_domain": top_domain,
            "source_score": ranked[0]["scores"]["source_score"] if ranked else 0,
            "citation_status": citation["status"],
            "supported_count": citation.get("supported_count", 0),
            "unsupported_count": citation.get("unsupported_count", 0),
            "failure_reason": "" if passed else "ranking_or_citation_gate_failed",
        })
    by_category = {}
    for item in results:
        bucket = by_category.setdefault(item["category"], {"case_count": 0, "passed_count": 0, "failed_count": 0})
        bucket["case_count"] += 1
        bucket["passed_count"] += 1 if item["pass"] else 0
        bucket["failed_count"] += 0 if item["pass"] else 1
    for bucket in by_category.values():
        bucket["pass_rate"] = round(bucket["passed_count"] / max(1, bucket["case_count"]), 4)
    report = {
        "name": "search-evidence-acceptance-v2-36case",
        "case_count": len(results),
        "passed_count": sum(1 for item in results if item["pass"]),
        "failed_count": sum(1 for item in results if not item["pass"]),
        "pass_rate": round(sum(1 for item in results if item["pass"]) / max(1, len(results)), 4),
        "coverage": {
            "categories": sorted(by_category.keys()),
            "js_render_cases": sum(1 for item in results if item["render_js_required"]),
            "offline_reproducible": True,
        },
        "by_category": by_category,
        "cases": results,
    }
    try:
        from services.artifact_storage import ArtifactStorage
        artifact = ArtifactStorage(os.path.join(BASE_DIR, "..", "output", "search_evidence")).write_json(
            "search_evidence_acceptance.json",
            report,
        )
        report["artifact"] = artifact
    except Exception as exc:
        report["artifact_error"] = str(exc)[:160]
    report["run_record"] = _save_web_run("web_search_benchmark", report["name"], report)
    print(json.dumps(report, ensure_ascii=False))


def tool_web_search_live_benchmark():
    from scripts.search_live_acceptance import run_live_suite
    raw_providers = input_data.get("providers") or ["tavily", "serpapi", "bing", "duckduckgo"]
    if isinstance(raw_providers, str):
        providers = [item.strip().lower() for item in raw_providers.split(",") if item.strip()]
    else:
        providers = [str(item).strip().lower() for item in raw_providers if str(item).strip()]
    report = run_live_suite(
        input_data.get("out") or os.path.join(BASE_DIR, "..", "output", "search_evidence"),
        providers=providers,
        limit_cases=int(input_data.get("limit_cases", 40) or 40),
        offline_mock=bool(input_data.get("offline_mock", False)),
        retries=max(1, min(int(input_data.get("retries", 1) or 1), 4)),
        use_cache=bool(input_data.get("use_cache", True)),
    )
    report["run_record"] = _save_web_run("web_search_live_benchmark", report["name"], report)
    print(json.dumps(report, ensure_ascii=False))




# ---- SKILL MANAGEMENT TOOLS ----

def tool_skill_register():
    """Register a solidified skill from a workflow demonstration."""
    name = input_data.get("name", "")
    description = input_data.get("description", "")
    steps = input_data.get("steps", [])
    trigger_keywords = input_data.get("trigger_keywords", [])
    tags = input_data.get("tags", [])
    category = input_data.get("category", "general")
    if not name or not description or not steps:
        print(json.dumps({"error": "name, description, and steps are required"}))
        sys.exit(1)
    try:
        from skill_registry import register_skill
        result = register_skill(name, description, steps, trigger_keywords, tags, category)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"Skill registration failed: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)


def tool_skill_list():
    """List all solidified skills."""
    category = input_data.get("category", None)
    try:
        from skill_registry import list_skills
        skills = list_skills(category)
        print(json.dumps({"skills": skills, "count": len(skills)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


def tool_skill_execute():
    """Execute a solidified skill locally."""
    name = input_data.get("name", "")
    params = input_data.get("params", {})
    if not name:
        print(json.dumps({"error": "Skill name required"}))
        sys.exit(1)
    try:
        from skill_registry import execute_skill
        result = execute_skill(name, params)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"Skill execution failed: {str(e)}"}, ensure_ascii=False))
        sys.exit(1)


def tool_skill_delete():
    """Delete a solidified skill."""
    name = input_data.get("name", "")
    if not name:
        print(json.dumps({"error": "Skill name required"}))
        sys.exit(1)
    try:
        from skill_registry import delete_skill
        result = delete_skill(name)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)

# ---- SCENARIO TOOLS ----

def tool_file_organize():
    """Organize files in a directory by extension or pattern."""
    path = input_data.get("path", os.path.expanduser("~\\Desktop"))
    pattern = input_data.get("pattern", "*")
    organize_by = input_data.get("organize_by", "extension")
    dry_run = input_data.get("dry_run", False)
    if not os.path.isdir(path):
        print(json.dumps({"error": f"Directory not found: {path}"}))
        sys.exit(1)
    import glob as gl
    files = gl.glob(os.path.join(path, pattern))
    files = [f for f in files if os.path.isfile(f)]
    result = {"path": path, "files_found": len(files), "actions": []}
    for f in files:
        if organize_by == "extension":
            ext = os.path.splitext(f)[1].lower().lstrip(".") or "no_ext"
            dest_dir = os.path.join(path, ext)
        elif organize_by == "date":
            mtime = os.path.getmtime(f)
            date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m")
            dest_dir = os.path.join(path, date_str)
        else:
            dest_dir = os.path.join(path, "organized")
        if not dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(f))
            try:
                os.rename(f, dest)
                result["actions"].append({"from": f, "to": dest})
            except OSError as e:
                result["actions"].append({"from": f, "error": str(e)})
        else:
            result["actions"].append({"from": f, "would_move_to": os.path.join(dest_dir, os.path.basename(f))})
    result["moved_count"] = len(result["actions"])
    result["dry_run"] = dry_run
    print(json.dumps(result, ensure_ascii=False))


def tool_text_stats():
    """Analyze text statistics from a file or direct input."""
    text = input_data.get("text", "")
    file_path = input_data.get("file_path", "")
    if file_path and os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    if not text:
        print(json.dumps({"error": "No text provided"}))
        sys.exit(1)
    words = len(re.findall(r"[\w\u4e00-\u9fff]+", text))
    chars = len(text)
    chars_no_space = len(re.sub(r"\s", "", text))
    lines = text.count("\n") + 1
    sentences = len(re.findall(r"[.!?。！？]\s", text)) or 1
    import math
    words_per_minute = 238
    reading_time_min = max(1, math.ceil(words / words_per_minute))
    print(json.dumps({
        "words": words, "characters": chars, "chars_no_space": chars_no_space,
        "lines": lines, "sentences": sentences,
        "avg_word_per_sentence": round(words / sentences, 1),
        "estimated_reading_time_min": reading_time_min,
        "language": "zh" if sum(1 for c in text if "\u4e00" <= c <= "\u9fff") > chars * 0.3 else "en"
    }, ensure_ascii=False))


def tool_batch_rename():
    """Batch rename files in a directory with a pattern."""
    path = input_data.get("path", os.path.expanduser("~\\Desktop"))
    pattern = input_data.get("pattern", "*")
    rename_rule = input_data.get("rename_rule", "")  # prefix/suffix/replace
    prefix = input_data.get("prefix", "")
    suffix = input_data.get("suffix", "")
    replace_old = input_data.get("replace_old", "")
    replace_new = input_data.get("replace_new", "")
    dry_run = input_data.get("dry_run", True)
    if not os.path.isdir(path):
        print(json.dumps({"error": f"Directory not found: {path}"}))
        sys.exit(1)
    import glob as gl
    files = gl.glob(os.path.join(path, pattern))
    files = [f for f in files if os.path.isfile(f)]
    result = {"path": path, "files_found": len(files), "renames": []}
    for f in files:
        base, ext = os.path.splitext(os.path.basename(f))
        new_base = base
        if rename_rule == "prefix" and prefix:
            new_base = prefix + base
        elif rename_rule == "suffix" and suffix:
            new_base = base + suffix
        elif rename_rule == "replace" and replace_old:
            new_base = base.replace(replace_old, replace_new)
        elif rename_rule == "serial":
            idx = files.index(f) + 1
            new_base = f"{prefix}{idx:03d}" if prefix else f"file_{idx:03d}"
        new_name = new_base + ext
        new_path = os.path.join(path, new_name)
        if not dry_run and f != new_path:
            try:
                os.rename(f, new_path)
                result["renames"].append({"from": os.path.basename(f), "to": new_name, "ok": True})
            except OSError as e:
                result["renames"].append({"from": os.path.basename(f), "to": new_name, "error": str(e)})
        elif f != new_path:
            result["renames"].append({"from": os.path.basename(f), "to": new_name, "dry_run": True})
    result["renamed_count"] = len(result["renames"])
    result["dry_run"] = dry_run
    print(json.dumps(result, ensure_ascii=False))


def tool_project_init():
    """Scaffold a new project with standard directory structure."""
    name = input_data.get("name", "")
    proj_type = input_data.get("type", "python")  # python, web, research, competition
    root = input_data.get("root", os.path.expanduser("~\\Desktop"))
    if not name:
        print(json.dumps({"error": "Project name required"}))
        sys.exit(1)
    proj_path = os.path.join(root, name)
    if os.path.exists(proj_path):
        print(json.dumps({"error": f"Directory already exists: {proj_path}"}))
        sys.exit(1)
    templates = {
        "python": ["src", "tests", "docs", "data"],
        "web": ["src", "public", "tests", "docs"],
        "research": ["data", "outputs", "notebooks", "references", "figures"],
        "competition": ["submission", "data", "models", "notebooks", "outputs"],
    }
    dirs = templates.get(proj_type, ["src", "docs"])
    os.makedirs(proj_path, exist_ok=True)
    created = []
    for d in dirs:
        dp = os.path.join(proj_path, d)
        os.makedirs(dp, exist_ok=True)
        created.append(d)
    # Create README
    readme = os.path.join(proj_path, "README.md")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(f"# {name}\n\n{proj_type.capitalize()} project scaffolded by ClawOS.\n")
    created.append("README.md")
    # Create .gitignore
    gitignore = os.path.join(proj_path, ".gitignore")
    ignores = {"python": "__pycache__/\n*.pyc\n.env\nvenv/\n", "web": "node_modules/\ndist/\n.env\n",
               "research": "data/raw/\noutputs/\n*.ipynb_checkpoints/\n",
               "competition": "data/raw/\nsubmission/*.zip\n*.pkl\n"}
    with open(gitignore, "w", encoding="utf-8") as f:
        f.write(ignores.get(proj_type, ".env\n"))
    created.append(".gitignore")
    print(json.dumps({"project": name, "type": proj_type, "path": proj_path, "created": created}, ensure_ascii=False))


def tool_timer():
    """Set a simple timer or pomodoro session."""
    action = input_data.get("action", "start")  # start, status
    duration_min = input_data.get("duration_min", 25)
    label = input_data.get("label", "Focus session")
    timer_file = os.path.join(BASE_DIR, "clawos_timer.json")
    if action == "status":
        if os.path.exists(timer_file):
            with open(timer_file, "r") as f: t = json.load(f)
            elapsed = (datetime.now() - datetime.fromisoformat(t["started_at"])).total_seconds() / 60
            remaining = max(0, t["duration_min"] - elapsed)
            print(json.dumps({"label": t["label"], "duration_min": t["duration_min"],
                              "elapsed_min": round(elapsed, 1), "remaining_min": round(remaining, 1),
                              "status": "running" if remaining > 0 else "done"}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "no_timer"}))
        return
    timer = {"label": label, "duration_min": duration_min, "started_at": datetime.now().isoformat()}
    with open(timer_file, "w") as f: json.dump(timer, f)
    print(json.dumps({"started": True, "label": label, "duration_min": duration_min,
                      "expected_end": (datetime.now() + timedelta(minutes=duration_min)).isoformat()}, ensure_ascii=False))


def tool_meeting_template():
    """Generate a meeting notes template and save it."""
    title = input_data.get("title", "Meeting Notes")
    attendees = input_data.get("attendees", [])
    date_str = input_data.get("date", datetime.now().strftime("%Y-%m-%d"))
    template = f"""# {title}
**Date:** {date_str}
**Attendees:** {", ".join(attendees) if attendees else "TBD"}

## Agenda
1. 
2. 
3. 

## Discussion Points

## Decisions Made

## Action Items
- [ ] 
- [ ] 

## Next Meeting
**Date:** TBD
"""
    filename = re.sub(r"\s+", "_", title.lower())[:50]
    path = os.path.join(NOTES_DIR, f"meeting_{filename}_{date_str}.md")
    os.makedirs(NOTES_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(template)
    print(json.dumps({"meeting_template": title, "saved_to": path, "preview": template[:300]}, ensure_ascii=False))
# --- Local File System Tools (Windows-native) ---

def tool_ls():
    path = input_data.get("path", os.path.expanduser("~\\Desktop"))
    pattern = input_data.get("pattern", "*")
    show_hidden = input_data.get("show_hidden", False)
    recursive = input_data.get("recursive", False)
    limit = input_data.get("limit", 100)
    sort_by = input_data.get("sort_by", "name")
    if not os.path.isdir(path):
        print(json.dumps({"error": f"Not found: {path}"})); sys.exit(1)
    results = []
    if recursive:
        for root, dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                if not show_hidden and os.path.basename(fp).startswith("."): continue
                st = os.stat(fp)
                results.append({"name": os.path.relpath(fp, path), "size": st.st_size, "is_dir": False, "modified": datetime.fromtimestamp(st.st_mtime).isoformat()})
            for d in dirs:
                if not show_hidden and d.startswith("."): continue
                dp = os.path.join(root, d); st = os.stat(dp)
                results.append({"name": os.path.relpath(dp, path), "size": st.st_size, "is_dir": True, "modified": datetime.fromtimestamp(st.st_mtime).isoformat()})
    else:
        for entry in os.listdir(path):
            if not show_hidden and entry.startswith("."): continue
            fp = os.path.join(path, entry); st = os.stat(fp)
            results.append({"name": entry, "size": st.st_size, "is_dir": os.path.isdir(fp), "modified": datetime.fromtimestamp(st.st_mtime).isoformat()})
    if pattern != "*":
        import fnmatch
        results = [r for r in results if fnmatch.fnmatch(os.path.basename(r["name"]), pattern)]
    if sort_by == "size": results.sort(key=lambda r: r["size"], reverse=True)
    elif sort_by == "modified": results.sort(key=lambda r: r["modified"], reverse=True)
    results = results[:limit]
    print(json.dumps({"path": path, "entries": results, "count": len(results)}, ensure_ascii=False))


def tool_cat():
    path = input_data.get("path", "")
    if not path or not os.path.exists(path):
        print(json.dumps({"error": f"File not found: {path}"})); sys.exit(1)
    if os.path.isdir(path):
        print(json.dumps({"error": f"Is a directory: {path}"})); sys.exit(1)
    start_line = input_data.get("start_line", 1); end_line = input_data.get("end_line", 0)
    max_lines = input_data.get("max_lines", 200)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    total = len(lines)
    if end_line == 0: end_line = min(start_line + max_lines - 1, total)
    s, e = max(0, start_line - 1), min(end_line, total)
    selected = lines[s:e]
    print(json.dumps({"path": path, "total_lines": total, "lines_shown": len(selected),
                      "start_line": start_line, "end_line": e, "content": "".join(selected).rstrip(),
                      "truncated": e < total}, ensure_ascii=False))


def tool_find_files():
    path = input_data.get("path", os.path.expanduser("~\\Desktop"))
    name_pattern = input_data.get("name_pattern", "*")
    entry_type = input_data.get("entry_type", "any")
    max_depth = input_data.get("max_depth", None); limit = input_data.get("limit", 100)
    case_insensitive = input_data.get("case_insensitive", True)
    if not os.path.isdir(path): print(json.dumps({"error": f"Not found: {path}"})); sys.exit(1)
    import fnmatch
    results = []
    for root, dirs, files in os.walk(path):
        depth = root[len(path):].count(os.sep)
        if max_depth is not None and depth >= max_depth: dirs.clear()
        entries = []
        if entry_type in ("any", "file"): entries.extend(files)
        if entry_type in ("any", "directory"): entries.extend(dirs)
        for name in entries:
            m = name.lower() if case_insensitive else name
            p = name_pattern.lower() if case_insensitive else name_pattern
            if fnmatch.fnmatch(m, p):
                fp = os.path.join(root, name); st = os.stat(fp)
                results.append({"name": os.path.relpath(fp, path), "path": fp, "size": st.st_size, "is_dir": os.path.isdir(fp), "modified": datetime.fromtimestamp(st.st_mtime).isoformat()})
                if len(results) >= limit: break
        if len(results) >= limit: break
    print(json.dumps({"path": path, "pattern": name_pattern, "matches": results, "count": len(results)}, ensure_ascii=False))


def tool_grep_text():
    path = input_data.get("path", os.path.expanduser("~\\Desktop")); pattern = input_data.get("pattern", "")
    file_pattern = input_data.get("file_pattern", "*"); recursive = input_data.get("recursive", True)
    ignore_case = input_data.get("ignore_case", True); max_depth = input_data.get("max_depth", None)
    limit = input_data.get("limit", 50)
    if not pattern: print(json.dumps({"error": "pattern required"})); sys.exit(1)
    import fnmatch, re as _re
    flags = _re.IGNORECASE if ignore_case else 0; rgx = _re.compile(_re.escape(pattern), flags)
    if os.path.isfile(path): files = [path]
    elif os.path.isdir(path):
        files = []
        for root, dirs, filenames in os.walk(path):
            depth = root[len(path):].count(os.sep)
            if max_depth is not None and depth >= max_depth: dirs.clear()
            if not recursive and depth > 0: dirs.clear()
            for f in filenames:
                if fnmatch.fnmatch(f, file_pattern): files.append(os.path.join(root, f))
    else: print(json.dumps({"error": f"Not found: {path}"})); sys.exit(1)
    results = []
    for fp in files:
        if len(results) >= limit: break
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                for li, line in enumerate(f, 1):
                    if rgx.search(line):
                        results.append({"file": fp, "line": li, "match": line.strip()[:200]})
                        if len(results) >= limit: break
        except: pass
    print(json.dumps({"pattern": pattern, "files_searched": len(files), "matches": results, "count": len(results)}, ensure_ascii=False))


def tool_file_info():
    path = input_data.get("path", "")
    if not path or not os.path.exists(path):
        print(json.dumps({"error": f"Not found: {path}"})); sys.exit(1)
    st = os.stat(path)
    info = {"path": path, "name": os.path.basename(path), "size_bytes": st.st_size,
            "size_human": _format_fsize(st.st_size), "is_dir": os.path.isdir(path),
            "extension": os.path.splitext(path)[1].lower(),
            "created": datetime.fromtimestamp(st.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat()}
    print(json.dumps(info, ensure_ascii=False))


def _format_fsize(b):
    for u in ["B","KB","MB","GB"]:
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"


def tool_code_stats():
    path = input_data.get("path", os.path.expanduser("~\\Desktop"))
    file_types = input_data.get("file_types", None)
    exclude = input_data.get("exclude_dirs", ["node_modules",".git","__pycache__","venv",".venv"])
    if not os.path.isdir(path): print(json.dumps({"error": f"Not found: {path}"})); sys.exit(1)
    lang_map = {".py":"Python",".js":"JavaScript",".ts":"TypeScript",".tsx":"TSX",".jsx":"JSX",".html":"HTML",".css":"CSS",".json":"JSON",".md":"Markdown",".txt":"Text",".c":"C",".cpp":"C++",".h":"Header",".java":"Java",".go":"Go",".rs":"Rust",".sh":"Shell",".bat":"Batch",".yml":"YAML",".yaml":"YAML",".xml":"XML",".sql":"SQL",".ipynb":"Jupyter"}
    stats = {}; total_l, total_f = 0, 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in exclude]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if file_types and ext not in file_types: continue
            lang = lang_map.get(ext, ext[1:] if ext else "other")
            try:
                with open(os.path.join(root, f), "r", encoding="utf-8", errors="replace") as fh:
                    n = sum(1 for _ in fh)
                stats.setdefault(lang, {"files":0,"lines":0})
                stats[lang]["files"] += 1; stats[lang]["lines"] += n; total_l += n; total_f += 1
            except: pass
    print(json.dumps({"path": path, "total_files": total_f, "total_lines": total_l, "by_language": stats}, ensure_ascii=False))


def tool_find_todos():
    path = input_data.get("path", os.path.expanduser("~\\Desktop"))
    tags = input_data.get("tags", ["TODO","FIXME","HACK","NOTE","XXX","BUG"])
    file_patterns = input_data.get("file_patterns", ["*.py","*.js","*.ts","*.jsx","*.tsx","*.java","*.go","*.rs","*.c","*.cpp","*.h","*.html","*.css","*.md"])
    limit = input_data.get("limit", 50)
    if os.path.isfile(path): files = [path]
    else:
        import fnmatch; files = []
        for root, dirs, filenames in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules","__pycache__","venv",".git")]
            for f in filenames:
                if any(fnmatch.fnmatch(f, p) for p in file_patterns): files.append(os.path.join(root, f))
    tag_rgx = re.compile("(" + "|".join(re.escape(t) for t in tags) + r")\b", re.IGNORECASE)
    results = []
    for fp in files:
        if len(results) >= limit: break
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as fh:
                for li, line in enumerate(fh, 1):
                    m = tag_rgx.search(line)
                    if m:
                        results.append({"file": fp, "line": li, "tag": m.group(1).upper(), "text": line.strip()[:150]})
                        if len(results) >= limit: break
        except: pass
    print(json.dumps({"path": path, "todos": results, "count": len(results), "files_scanned": len(files)}, ensure_ascii=False))


def tool_dir_tree():
    path = input_data.get("path", os.path.expanduser("~\\Desktop"))
    max_depth = input_data.get("max_depth", 4); show_hidden = input_data.get("show_hidden", False)
    max_entries = input_data.get("max_entries", 30)
    exclude = input_data.get("exclude_dirs", ["node_modules",".git","__pycache__","venv",".venv"])
    if not os.path.isdir(path): print(json.dumps({"error": f"Not found: {path}"})); sys.exit(1)
    lines = [os.path.basename(path) or path]
    def _walk(cur, prefix, depth):
        if depth >= max_depth: lines.append(prefix + "..."); return
        try:
            entries = [e for e in os.listdir(cur) if show_hidden or not e.startswith(".")]
            entries = [e for e in entries if not (os.path.isdir(os.path.join(cur, e)) and e in exclude)]
        except PermissionError: lines.append(prefix + "(no permission)"); return
        entries.sort(key=lambda x: (os.path.isfile(os.path.join(cur, x)), x.lower()))
        for i, entry in enumerate(entries[:max_entries]):
            is_last = i == min(len(entries), max_entries) - 1
            connector = "\\_ " if is_last else "|_ "
            fp = os.path.join(cur, entry); lines.append(prefix + connector + entry)
            if os.path.isdir(fp): _walk(fp, prefix + ("   " if is_last else "|  "), depth + 1)
        if len(entries) > max_entries: lines.append(prefix + f"... ({len(entries)-max_entries} more)")
    _walk(path, "", 0)
    print(json.dumps({"path": path, "tree": "\n".join(lines)}, ensure_ascii=False))
# ---- MEMORY MANAGEMENT TOOLS ----

def tool_memory_profile_set():
    """Set a user profile value in MemoryOS."""
    key = input_data.get("key", ""); value = input_data.get("value", "")
    category = input_data.get("category", "general")
    if not key: print(json.dumps({"error": "key required"})); sys.exit(1)
    try:
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        store.set_profile(key, value, category, importance=input_data.get("importance", 0.5))
        print(json.dumps({"set": True, "key": key, "value": value, "category": category}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)


def tool_memory_profile_get():
    """Get user profile info from MemoryOS."""
    key = input_data.get("key", ""); category = input_data.get("category", "general")
    try:
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        if key:
            result = store.get_profile(key, category)
            print(json.dumps(result or {"not_found": key}, ensure_ascii=False))
        else:
            profiles = store.get_all_profiles()
            print(json.dumps({"profiles": profiles, "count": len(profiles)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)


def tool_memory_preference_set():
    """Set a user preference in MemoryOS."""
    key = input_data.get("key", ""); value = input_data.get("value", "")
    category = input_data.get("category", "general")
    if not key: print(json.dumps({"error": "key required"})); sys.exit(1)
    try:
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        store.set_preference(key, value, category, confidence=input_data.get("confidence", 0.7))
        print(json.dumps({"set": True, "key": key, "value": value, "category": category}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)


def tool_memory_preference_get():
    """Get user preferences from MemoryOS."""
    key = input_data.get("key", ""); category = input_data.get("category", "general")
    try:
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        if key:
            result = store.get_preference(key, category)
            print(json.dumps(result or {"not_found": key}, ensure_ascii=False))
        else:
            prefs = store.get_all_preferences()
            print(json.dumps({"preferences": prefs, "count": len(prefs)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)


def tool_memory_stats():
    """Get MemoryOS statistics."""
    try:
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        stats = store.get_stats()
        print(json.dumps(stats, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)


def tool_memory_history():
    """Get recent conversation history from MemoryOS."""
    session_id = input_data.get("session_id", "default")
    limit = input_data.get("limit", 10)
    try:
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        msgs = store.get_recent_messages(session_id, limit)
        # Truncate content for readability
        for m in msgs:
            m["content"] = m.get("content", "")[:300]
        print(json.dumps({"session_id": session_id, "messages": msgs, "count": len(msgs)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)})); sys.exit(1)
REFLECTION_DIR = os.path.join(BASE_DIR, "reflection")
if REFLECTION_DIR not in sys.path:
    sys.path.insert(0, REFLECTION_DIR)
# ---- REFLECTION TOOLS ----

def tool_reflection_trigger():
    """Trigger a manual reflection cycle."""
    session_id = input_data.get("session_id", "default")
    task = input_data.get("task", "")
    feedback = input_data.get("feedback", "")
    try:
        from reflection.engine import ReflectionEngine
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        engine = ReflectionEngine(store)
        result = engine.reflect("user_triggered", session_id, [], feedback, task)
        print(json.dumps({"reflection": result, "status": "completed"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def tool_reflection_list():
    """List recent reflection cards."""
    limit = input_data.get("limit", 20)
    try:
        from reflection.memory_writer import ReflectionMemoryWriter
        from memoryos.memory_store import MemoryStore
        store = MemoryStore(_memory_db_path())
        writer = ReflectionMemoryWriter(store)
        cards = writer.get_reflection_cards(limit)
        print(json.dumps({"reflection_cards": cards, "count": len(cards)}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def tool_file_write():
    """Write content to a file on disk. Creates parent directories if needed."""
    path = input_data.get("path", "")
    content = input_data.get("content", "")
    append = input_data.get("append", False)
    if not path:
        print(json.dumps({"error": "path required"})); sys.exit(1)
    try:
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        mode = "a" if append else "w"
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        size = os.path.getsize(path)
        print(json.dumps({"written": True, "path": path, "size_bytes": size, "append": append}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"Write failed: {str(e)}"}))
        sys.exit(1)

def tool_shell_exec():
    """Execute a shell command and return output. Windows: uses PowerShell. Max execution: 30s."""
    command = input_data.get("command", "")
    workdir = input_data.get("workdir", os.getcwd())
    timeout_sec = min(input_data.get("timeout", 15), 60)
    if not command:
        print(json.dumps({"error": "command required"})); sys.exit(1)
    try:
        import subprocess
        # On Windows: try cmd first for simple commands (where, dir, cd), fallback to PowerShell
        if os.name == "nt":
            simple_cmds = ["where ", "dir ", "cd ", "echo ", "type ", "mkdir ", "copy ", "move ", "del ", "set ", "g++ ", "gcc ", "clang", "cl "]
            is_simple = any(command.strip().startswith(c) for c in simple_cmds)
            shell_cmd = ["cmd", "/c", command] if is_simple else ["powershell", "-NoProfile", "-Command", command]
        else:
            shell_cmd = ["bash", "-c", command]
        proc = subprocess.run(shell_cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout_sec)
        result = {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:2000],
            "command": command,
            "workdir": workdir,
        }
        print(json.dumps(result, ensure_ascii=False))
    except subprocess.TimeoutExpired:
        print(json.dumps({"error": f"Command timed out after {timeout_sec}s", "command": command}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Execution failed: {str(e)}", "command": command}))
        sys.exit(1)


handlers = {
    "weather": tool_weather, "time_now": tool_time_now, "calc": tool_calc,
    "todo_list": tool_todo_list, "note_save": tool_note_save,
    "note_read": tool_note_read, "note_list": tool_note_list,
    "web_search": tool_web_search, "web_fetch": tool_web_fetch,
    "web_citation_check": tool_web_citation_check, "web_search_benchmark": tool_web_search_benchmark,
    "web_search_live_benchmark": tool_web_search_live_benchmark,
    "tools_list": tool_tools_list,
    "skill_register": tool_skill_register, "skill_list": tool_skill_list,
    "skill_execute": tool_skill_execute, "skill_delete": tool_skill_delete,
    "file_organize": tool_file_organize, "text_stats": tool_text_stats,
    "meeting_action_items": _scenario_tool("meeting_action_items"),
    "paper_deep_read": _scenario_tool("paper_deep_read"),
    "exam_practice_builder": _scenario_tool("exam_practice_builder"),
    "work_brief_builder": _scenario_tool("work_brief_builder"),
    "research_experiment_plan": _scenario_tool("research_experiment_plan"),
    "batch_rename": tool_batch_rename, "project_init": tool_project_init,
    "timer": tool_timer, "meeting_template": tool_meeting_template,
    "ls": tool_ls, "cat": tool_cat, "find_files": tool_find_files,
    "grep_text": tool_grep_text, "file_info": tool_file_info,
    "code_stats": tool_code_stats, "find_todos": tool_find_todos,
    "dir_tree": tool_dir_tree,
    "memory_profile_set": tool_memory_profile_set,
    "memory_profile_get": tool_memory_profile_get,
    "memory_preference_set": tool_memory_preference_set,
    "memory_preference_get": tool_memory_preference_get,
    "memory_stats": tool_memory_stats,
    "memory_history": tool_memory_history,
    "reflection_trigger": tool_reflection_trigger,
    "reflection_list": tool_reflection_list,
    "file_write": tool_file_write,
    "shell_exec": tool_shell_exec,
    "meeting_workflow": _scenario_tool("meeting_workflow"),
    "research_pdf": _scenario_tool("research_pdf"),
    "learning_workspace": _scenario_tool("learning_workspace"),
    "office_artifact": _scenario_tool("office_artifact"),
    "git_workspace": _scenario_tool("git_workspace"),
    "skill_governance": _scenario_tool("skill_governance"),
    "competition_delivery_package": _scenario_tool("competition_delivery_package"),
    "multi_agent_review_committee": _scenario_tool("multi_agent_review_committee"),
    "template_list": _scenario_tool("template_list"),
    "template_instantiate": _scenario_tool("template_instantiate")
}

if __name__ == "__main__":
    if tool_name in handlers:
        try:
            input_data = security_check(tool_name, input_data)
            handlers[tool_name]()
        except PermissionError as exc:
            print(json.dumps({"error": str(exc), "status": "denied"}, ensure_ascii=False))
            raise SystemExit(3)
