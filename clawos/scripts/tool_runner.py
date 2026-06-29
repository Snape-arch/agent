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
    attempts = []
    for provider in providers:
        try:
            fn = {
                "tavily": _search_tavily,
                "serpapi": _search_serpapi,
                "bing": _search_bing,
                "duckduckgo": _search_duckduckgo,
            }.get(str(provider).lower())
            if not fn:
                continue
            rows, error_type = fn(query, limit)
            attempts.append({"provider": provider, "ok": bool(rows), "error_type": error_type})
            if rows:
                print(json.dumps({"query": query, "provider": provider, "results": rows[:limit], "attempts": attempts}, ensure_ascii=False))
                return
        except Exception as e:
            attempts.append({"provider": provider, "ok": False, "error_type": type(e).__name__, "message": str(e)[:200]})
    print(json.dumps({"error": "Search failed across providers", "error_type": "all_providers_failed", "query": query, "results": [], "attempts": attempts}, ensure_ascii=False)); sys.exit(1)


def tool_web_fetch():
    url = str(input_data.get("url", "")).strip()
    max_chars = int(input_data.get("max_chars", 4000) or 4000)
    ingest = bool(input_data.get("ingest", False))
    category = str(input_data.get("category", "web") or "web")
    if not url:
        print(json.dumps({"error": "missing url"})); sys.exit(1)
    if not re.match(r"^https?://", url, re.I):
        print(json.dumps({"error": "only http(s) URLs are supported"})); sys.exit(1)
    try:
        import urllib.request
        import urllib.parse
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
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title_match.group(1))).strip() if title_match else ""
        links = []
        for href, label in re.findall(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, re.I | re.S)[:80]:
            clean_label = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", label)).strip()
            abs_url = urllib.parse.urljoin(final_url, href)
            if clean_label and abs_url.startswith(("http://", "https://")):
                links.append({"text": clean_label[:120], "url": abs_url})
            if len(links) >= 20:
                break
        text = re.sub(r"<(script|style|noscript|svg|canvas)[\s\S]*?</\1>", " ", html_text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        import html as html_lib
        text = html_lib.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        result = {
            "url": url,
            "final_url": final_url,
            "status": status,
            "content_type": content_type,
            "title": title,
            "text": text[:max(500, min(max_chars, 12000))],
            "text_length": len(text),
            "links": links,
            "truncated": len(text) > max_chars,
        }
        if ingest:
            from pathlib import Path
            import hashlib
            from memoryos.memory_store import MemoryStore
            from memoryos.document_ingestion import ingest_file, safe_filename
            digest = hashlib.sha256(final_url.encode("utf-8")).hexdigest()[:12]
            upload_dir = Path(BASE_DIR) / "uploads" / "web"
            upload_dir.mkdir(parents=True, exist_ok=True)
            name = safe_filename((title or "web_page") + ".html")
            page_path = upload_dir / f"{digest}_{name}"
            page_path.write_text(html_text, encoding="utf-8", errors="replace")
            store = MemoryStore(_memory_db_path())
            doc = ingest_file(store, upload_dir, page_path, title=title or final_url, category=category)
            result["document"] = {
                "id": doc.get("id"),
                "title": doc.get("title"),
                "chunk_count": doc.get("chunk_count", 0),
                "citation_prefix": f"doc:{doc.get('id')}#",
            }
            result["ingested"] = True
        else:
            result["ingested"] = False
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": f"Fetch failed: {str(e)}"})); sys.exit(1)




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
    "web_search": tool_web_search, "web_fetch": tool_web_fetch, "tools_list": tool_tools_list,
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
