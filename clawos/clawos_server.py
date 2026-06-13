#!/usr/bin/env python3
"""ClawOS Server - Self-contained AI Agent with DeepSeek + Function Router."""
from __future__ import annotations
import argparse, asyncio, json, logging, os, re, sys, time, subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from providers import create_model_provider

# ---- PATHS ----
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = BASE_DIR / "config.json"
SCRIPTS_DIR = BASE_DIR / "scripts"
NOTES_DIR = BASE_DIR / "notes"
TODO_FILE = BASE_DIR / "clawos_todo.json"

MEMORY_DB = Path(os.environ.get("CLAWOS_MEMORY_DB", str(BASE_DIR / "memoryos.db"))).expanduser().resolve()

g_memory_store: Any = None
g_reflection_engine: Any = None
g_context_builder: Any = None
g_vector_store: MemoryVectorStore | None = None
g_mtclaw_adapter: Any = None

SYSTEM_PROMPT = (
    "You are ClawOS, a personal AI assistant. Use the provided tools to "
    "handle user requests. If a request matches an available tool, call it "
    "immediately without asking. If no tool matches, answer directly. "
    "Always reply in the same language as the user (Chinese or English). "
    "Be concise and helpful. Do not use emojis. "
    "When a tool returns data, report it accurately without speculation."
)

# ---- GLOBAL STATE ----
config: dict[str, Any] = {}
tools_def: list[dict[str, Any]] = []
http_client: httpx.AsyncClient | None = None
logger: logging.Logger | None = None
g_routing_provider: Any = None
g_upstream_provider: Any = None

# ---- CONFIG ----
def load_config(cfg_path: Path) -> dict[str, Any]:
    with open(cfg_path, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    env_pattern = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")
    def _sub(v):
        if isinstance(v, str):
            return env_pattern.sub(lambda m: os.environ.get(m.group(1), m.group(2) or m.group(0)), v)
        if isinstance(v, dict):
            return {k: _sub(vv) for k, vv in v.items()}
        return v
    return normalize_config(_sub(cfg))


def normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    provider_cfg = dict(cfg.get("model_provider") or {})
    legacy_routing = dict(cfg.get("routing") or {})
    legacy_upstream = dict(cfg.get("upstream") or {})
    if not provider_cfg:
        provider_cfg = {
            "provider": legacy_routing.get("provider") or legacy_upstream.get("provider") or "deepseek",
            "base_url": legacy_routing.get("base_url") or legacy_upstream.get("base_url") or "",
            "model": legacy_routing.get("model") or legacy_upstream.get("model") or "deepseek-chat",
            "api_key": legacy_routing.get("api_key") or legacy_upstream.get("api_key") or "",
        }
    provider_cfg.setdefault("provider", "deepseek")
    provider_cfg.setdefault("model", "deepseek-chat")
    provider_cfg.setdefault("base_url", "https://api.deepseek.com/v1")
    provider_cfg.setdefault("api_key", "")
    if provider_cfg.get("provider") == "deepseek":
        if not provider_cfg.get("api_key"):
            provider_cfg["api_key"] = os.environ.get("DEEPSEEK_API_KEY", "")
        if provider_cfg.get("model") == "deepseek-chat" and os.environ.get("DEEPSEEK_MODEL"):
            provider_cfg["model"] = os.environ["DEEPSEEK_MODEL"]
        if provider_cfg.get("base_url") == "https://api.deepseek.com/v1" and os.environ.get("DEEPSEEK_BASE_URL"):
            provider_cfg["base_url"] = os.environ["DEEPSEEK_BASE_URL"]
    cfg["model_provider"] = provider_cfg

    routing_cfg = {**provider_cfg, **legacy_routing}
    upstream_cfg = {**provider_cfg, **legacy_upstream}
    cfg["routing"] = routing_cfg
    cfg["upstream"] = upstream_cfg
    return cfg


def model_provider_status(cfg: dict[str, Any]) -> dict[str, Any]:
    provider_cfg = cfg.get("model_provider") or cfg.get("upstream") or {}
    provider = create_model_provider(provider_cfg)
    is_configured = provider.is_configured() if hasattr(provider, "is_configured") else True
    return {
        "provider": getattr(provider, "name", provider_cfg.get("provider", "")),
        "model": getattr(provider, "model", provider_cfg.get("model", "")),
        "configured": bool(is_configured),
    }

def load_tools(func_path: Path) -> list[dict[str, Any]]:
    if not func_path.exists():
        logger.warning(f"Functions file not found: {func_path}")
        return []
    tools = []
    with open(func_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            obj = json.loads(line)
            tools.append({"type": "function", "function": obj})
    return tools

# ---- TOOL EXECUTION ----
_TOOL_CACHE: dict[str, Any] = {}
_runner_module = None
TOOLS_REQUIRING_CONFIRMATION = {
    "batch_rename",
    "file_organize",
    "file_write",
    "shell_exec",
    "skill_delete",
}

def execute_python_tool(name: str, args_str: str) -> dict[str, Any]:
    """Execute a Python tool via the tool_runner module."""
    global _runner_module
    # Always reload to pick up latest changes
    import importlib
    if _runner_module is not None:
        try:
            importlib.reload(_runner_module)
        except:
            _runner_module = None
    if _runner_module is None:
        import importlib.util
        sys.path.insert(0, str(SCRIPTS_DIR))
        spec = importlib.util.spec_from_file_location("tool_runner", SCRIPTS_DIR / "tool_runner.py")
        _runner_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_runner_module)

    handlers = getattr(_runner_module, "handlers", {})
    # Alias
    if name in ("bash", "exec", "sh"):
        name = "shell_exec"
    if name not in handlers:
        return {"error": f"Unknown tool: {name}"}

    try:
        args_obj = json.loads(args_str)
    except json.JSONDecodeError:
        args_obj = {}

    # Capture stdout
    import io
    old_stdout = sys.stdout
    old_stdin = sys.stdin
    sys.stdout = io.StringIO()
    sys.stdin = io.StringIO(json.dumps(args_obj))
    _runner_module.input_data = args_obj
    _runner_module.tool_name = name

    exit_code = 0
    try:
        handlers[name]()
    except SystemExit as e:
        exit_code = e.code or 0
    except Exception as e:
        result = {"error": str(e)}
        sys.stdout = old_stdout
        sys.stdin = old_stdin
        return result
    finally:
        output = sys.stdout.getvalue().strip()
        sys.stdout = old_stdout
        sys.stdin = old_stdin

    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"result": output[:2000]}
    return {"result": "ok", "exit_code": exit_code}


def _parse_tool_arguments(args_str: str) -> dict[str, Any]:
    try:
        parsed = json.loads(args_str or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _record_tool_execution(session_id: str, envelope: dict[str, Any]):
    if not g_memory_store:
        return
    try:
        g_memory_store.record_tool_execution(
            session_id=session_id,
            tool_name=envelope.get("tool", ""),
            arguments=envelope.get("arguments", {}),
            result=envelope,
            status=envelope.get("status", "unknown"),
            duration_ms=float(envelope.get("duration_ms", 0) or 0),
            requires_confirmation=bool(envelope.get("requires_confirmation")),
        )
    except Exception as e:
        if logger:
            logger.warning(f"Tool execution log failed: {e}")


def execute_tool_call(
    name: str,
    args_str: str,
    session_id: str = "default",
    confirmed_tools: set[str] | None = None,
) -> dict[str, Any]:
    """Execute a tool and return a stable envelope for tracing and reflection."""
    confirmed_tools = confirmed_tools or set()
    args_obj = _parse_tool_arguments(args_str)
    requires_confirmation = name in TOOLS_REQUIRING_CONFIRMATION
    started = time.perf_counter()

    if requires_confirmation and name not in confirmed_tools:
        envelope = {
            "ok": False,
            "status": "needs_confirmation",
            "tool": name,
            "arguments": args_obj,
            "data": None,
            "error": f"Tool '{name}' requires explicit confirmation before execution.",
            "duration_ms": 0,
            "requires_confirmation": True,
        }
        _record_tool_execution(session_id, envelope)
        return envelope

    raw = execute_python_tool(name, args_str)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    ok = not (isinstance(raw, dict) and raw.get("error"))
    envelope = {
        "ok": ok,
        "status": "success" if ok else "error",
        "tool": name,
        "arguments": args_obj,
        "data": raw if ok else None,
        "error": "" if ok else str(raw.get("error", raw)),
        "duration_ms": duration_ms,
        "requires_confirmation": requires_confirmation,
    }
    _record_tool_execution(session_id, envelope)
    return envelope

# ---- LLM ROUTING ----
async def call_routing_llm(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Call configured model provider for tool detection."""
    result = await g_routing_provider.complete(
        messages,
        {
        "tools": tools_def,
        "temperature": 0.0,
        },
        http_client=http_client,
    )
    if not result["ok"]:
        raise RuntimeError(result["error"])
    return result["raw"]


def has_api_key(section: str = "routing") -> bool:
    provider = g_routing_provider if section == "routing" else g_upstream_provider
    if provider and hasattr(provider, "is_configured"):
        return bool(provider.is_configured())
    key = str(config.get(section, {}).get("api_key", "") or "")
    return bool(key and "${" not in key and key != "YOUR_DEEPSEEK_API_KEY")


def rule_based_tool(user_text: str) -> tuple[str, dict[str, Any]] | None:
    """Small offline router for high-confidence local operations."""
    text = user_text.strip()
    low = text.lower()
    if any(k in low for k in ["current time", "what time", "time now"]) or any(k in text for k in ["现在几点", "当前时间", "今天几号"]):
        return "time_now", {}
    if low in {"list skills", "show skills", "skill list"} or any(k in text for k in ["列出技能", "查看技能", "技能列表"]):
        return "skill_list", {}
    if low in {"memory stats", "memory status"} or any(k in text for k in ["记忆统计", "memoryos统计"]):
        return "memory_stats", {}
    if low in {"memory history", "conversation history", "show history"} or any(k in text for k in ["记忆历史", "对话历史", "聊天历史", "查看历史"]):
        return "memory_history", {}
    if low in {"profiles", "profile memory", "show profile"} or any(k in text for k in ["查看画像", "用户画像", "我的画像", "个人资料"]):
        return "memory_profile_get", {}
    if low in {"preferences", "preference memory", "show preferences"} or any(k in text for k in ["查看偏好", "我的偏好", "偏好设置"]):
        return "memory_preference_get", {}
    if low in {"list tools", "show tools", "tool list"} or any(k in text for k in ["列出工具", "查看工具", "工具列表"]):
        return "tools_list", {}
    m = re.search(r"^set profile:\s*([^=：:]+)\s*[=：:]\s*(.+)$", text, re.I)
    if m:
        return "memory_profile_set", {"key": m.group(1).strip(), "value": m.group(2).strip()}
    m = re.search(r"^set preference:\s*([^=：:]+)\s*[=：:]\s*(.+)$", text, re.I)
    if m:
        return "memory_preference_set", {"key": m.group(1).strip(), "value": m.group(2).strip()}
    m = re.search(r"记住(?:我的)?(.{1,24}?)(?:是|为|:|：)(.+)", text)
    if m:
        return "memory_preference_set", {"key": m.group(1).strip(), "value": m.group(2).strip()}
    return None

async def run_tool_loop(
    user_text: str,
    session_id: str = "default",
    confirmed_tools: set[str] | None = None,
) -> dict[str, Any]:
    """Tool detection + execution loop."""
    confirmed_tools = confirmed_tools or set()
    # Fast path: known solidified skills should bypass the LLM router.
    try:
        from skills.skill_registry import match_skill_by_text
        matched_skill = match_skill_by_text(user_text)
        if matched_skill:
            args = json.dumps({"name": matched_skill["name"], "params": {}}, ensure_ascii=False)
            result = execute_tool_call("skill_execute", args, session_id, confirmed_tools)
            if result.get("ok"):
                return {
                    "used_tools": True,
                    "tool_calls": [{"name": "skill_execute", "arguments": args, "result": result}],
                    "final_text": "",
                    "routing_rounds": 0,
                    "matched_skill": matched_skill["name"],
                }
            if logger:
                logger.info("Skill fast path needs parameters or failed: %s", matched_skill["name"])
    except Exception as e:
        logger.debug(f"Skill fast path skipped: {e}")

    rb = rule_based_tool(user_text)
    if rb:
        fn_name, fn_args_obj = rb
        fn_args = json.dumps(fn_args_obj, ensure_ascii=False)
        result = execute_tool_call(fn_name, fn_args, session_id, confirmed_tools)
        return {
            "used_tools": True,
            "tool_calls": [{"name": fn_name, "arguments": fn_args, "result": result}],
            "final_text": "",
            "routing_rounds": 0,
            "matched_skill": "",
        }

    if not has_api_key("routing"):
        lang_zh = bool(re.search(r"[\u4e00-\u9fff]", user_text))
        text = "当前未配置 DEEPSEEK_API_KEY，复杂自然语言路由暂不可用；你仍可在 MemoryOS 页面维护记忆，或配置本地 OpenAI 兼容模型端点。" if lang_zh else "DEEPSEEK_API_KEY is not configured, so complex natural-language routing is unavailable. You can still manage MemoryOS in the UI or configure a local OpenAI-compatible model endpoint."
        return {"used_tools": False, "tool_calls": [], "final_text": text, "routing_rounds": 0}

    # Use MemoryOS to build messages with context
    if g_context_builder:
        messages = g_context_builder.build_messages(session_id, user_text)
    else:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_text}]
    max_rounds = config.get("max_tool_rounds", 6)
    tc_log: list[dict[str, Any]] = []
    used = False

    for ri in range(1, max_rounds + 1):
        try:
            resp = await call_routing_llm(messages)
        except Exception as e:
            logger.warning(f"Routing LLM error round {ri}: {e}")
            break
        choices = resp.get("choices", [])
        if not choices: break
        msg = choices[0].get("message", {})
        tcs = msg.get("tool_calls") or []
        content = msg.get("content", "")

        if not tcs:
            return {"used_tools": used, "tool_calls": tc_log, "final_text": content, "routing_rounds": ri}

        used = True
        tc_msgs = []
        tool_messages = []
        for tc in tcs:
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            fn_args = fn.get("arguments", "{}")
            tc_id = tc.get("id", f"call_{fn_name}_{ri}")
            tc_msgs.append({"id": tc_id, "type": "function", "function": {"name": fn_name, "arguments": fn_args}})
            logger.info(f"Tool: {fn_name}({fn_args[:150]})")
            result = execute_tool_call(fn_name, fn_args, session_id, confirmed_tools)
            tc_log.append({"name": fn_name, "arguments": fn_args, "result": result})
            tool_messages.append({"role": "tool", "tool_call_id": tc_id, "name": fn_name, "content": json.dumps(result, ensure_ascii=False)})
        assistant_msg = {"role": "assistant", "content": content or "", "tool_calls": tc_msgs}
        assistant_msg["tool_calls"] = tc_msgs
        messages.append(assistant_msg)
        messages.extend(tool_messages)

    return {"used_tools": used, "tool_calls": tc_log, "final_text": "", "routing_rounds": max_rounds}


def build_openai_response(content: str, model: str | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a small OpenAI-compatible chat completion response."""
    payload = {
        "id": f"chatcmpl-clawos-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or config.get("upstream", {}).get("model", "clawos-agent"),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content or ""},
            "finish_reason": "stop",
        }],
    }
    if extra:
        payload["clawos"] = extra
    return payload


def extract_assistant_text(resp: JSONResponse) -> str:
    try:
        body = json.loads(resp.body)
        for ch in body.get("choices", []):
            msg = ch.get("message", {})
            if msg.get("content"):
                return str(msg["content"])
    except Exception:
        pass
    return ""


def sse_from_text(text: str) -> StreamingResponse:
    async def gen():
        chunk = {"choices": [{"delta": {"content": text or ""}}]}
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


def _confirmed_tools_from_request(req_data: dict[str, Any]) -> set[str]:
    value = req_data.get("clawos_confirmed_tools", req_data.get("confirmed_tools", []))
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def save_memory_item(data: dict[str, Any]) -> dict[str, Any]:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    memory_type = str(data.get("memory_type", "") or data.get("type", "")).strip()
    key = str(data.get("key", "") or data.get("title", "")).strip()
    value = str(data.get("value", "") or data.get("content", "")).strip()
    if not memory_type or not key or not value:
        raise HTTPException(400, "memory_type, key, and value are required")
    try:
        item = g_memory_store.upsert_memory(
            memory_type=memory_type,
            key=key,
            value=value,
            category=str(data.get("category", "general") or "general"),
            source=str(data.get("source", "manual") or "manual"),
            confidence=float(data.get("confidence", 0.7)),
            enabled=bool(data.get("enabled", True)),
        )
        if g_vector_store:
            g_vector_store.refresh()
        return item
    except ValueError as e:
        raise HTTPException(400, str(e))


def list_memory_items(memory_type: str = "", include_disabled: bool = False, limit: int = 200) -> list[dict[str, Any]]:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    return g_memory_store.list_memories(memory_type, include_disabled, limit)


def set_memory_item_enabled(memory_id: int, enabled: bool) -> dict[str, Any]:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    item = g_memory_store.set_memory_enabled(memory_id, enabled)
    if not item:
        raise HTTPException(404, "Memory item not found")
    if g_vector_store:
        g_vector_store.refresh()
    return item


async def store_assistant_response(session_id: str, resp: JSONResponse):
    if not g_memory_store:
        return
    text = extract_assistant_text(resp)
    if text:
        g_memory_store.add_message(session_id, "assistant", text[:4000])

# ---- UPSTREAM MODEL ----
async def proxy_upstream(req_data: dict, stream: bool, tool_context: str = "") -> JSONResponse:
    if stream:
        raise HTTPException(400, "Streaming is not implemented for ModelProvider yet")
    messages = req_data.get("messages", [])
    result = await g_upstream_provider.complete(
        messages,
        {
            "temperature": req_data.get("temperature", 0.7),
            "model": req_data.get("model") or config.get("upstream", {}).get("model"),
        },
        http_client=http_client,
    )
    if not result["ok"]:
        return JSONResponse(build_openai_response(
            f"模型调用失败：{result['error']}",
            model=result.get("model"),
            extra={"model_result": result},
        ))
    body = build_openai_response(result["content"], model=result["model"], extra={"model_result": result})
    body["usage"] = result.get("usage", {})
    return JSONResponse(body)

# ---- LIFESPAN ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, tools_def, http_client, logger, g_routing_provider, g_upstream_provider
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("clawos")
    config = load_config(CONFIG_PATH)
    config.setdefault("max_tool_rounds", 6)
    func_path = Path(config.get("functions_file", BASE_DIR / "functions.jsonl"))
    tools_def = load_tools(func_path)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    g_routing_provider = create_model_provider(config.get("routing", {}))
    g_upstream_provider = create_model_provider(config.get("upstream", {}))
    global g_mtclaw_adapter
    from mtclaw import MTClawAdapter
    g_mtclaw_adapter = MTClawAdapter(config.get("mtclaw", {}), http_client=http_client)
    NOTES_DIR.mkdir(exist_ok=True)
    # Init MemoryOS
    global g_memory_store, g_context_builder, g_vector_store
    from memoryos.memory_store import MemoryStore
    from memoryos.context_builder import ContextBuilder
    from memoryos.services.vector_store import MemoryVectorStore
    g_memory_store = MemoryStore(str(MEMORY_DB))

    # Init VectorStore before ContextBuilder so retrieval uses the same live index.
    g_vector_store = MemoryVectorStore(str(MEMORY_DB))
    g_vector_store.refresh()  # Load existing data
    g_context_builder = ContextBuilder(g_memory_store, g_vector_store)
    logger.info(f"VectorStore initialized | dim=256 docs={g_vector_store.stats().get('vector_count', 0)}")
    logger.info(f"MemoryOS initialized | db={MEMORY_DB}")
    
    global g_reflection_engine
    try:
        from reflection.engine import ReflectionEngine
        g_reflection_engine = ReflectionEngine(g_memory_store, http_client, config.get("routing", {}))
        logger.info("Reflection Engine initialized")
    except Exception as e:
        logger.warning(f"Reflection Engine init skipped: {e}")
        g_reflection_engine = None

    provider_state = model_provider_status(config)
    if not provider_state["configured"]:
        logger.warning(
            "Model provider not fully configured | provider=%s model=%s",
            provider_state["provider"],
            provider_state["model"],
        )
    logger.info(
        "ClawOS ready | provider=%s model=%s configured=%s tools=%s mtclaw=%s",
        provider_state["provider"],
        provider_state["model"],
        provider_state["configured"],
        len(tools_def),
        g_mtclaw_adapter.enabled,
    )
    yield
    if http_client:
        await http_client.aclose()
    logger.info("ClawOS stopped")

app = FastAPI(title="ClawOS Agent", version="1.0.0", lifespan=lifespan)

# ---- ROUTES ----
@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/health")
async def health():
    provider_state = model_provider_status(config) if config else {"provider": "", "model": "", "configured": False}
    mtclaw_state = (
        await g_mtclaw_adapter.health()
        if g_mtclaw_adapter
        else {"enabled": False, "reachable": False, "status": "not_initialized"}
    )
    return {
        "status": "ok",
        "version": "1.0.0",
        "tools": len(tools_def),
        "memory": bool(g_memory_store),
        "reflection": bool(g_reflection_engine),
        "model_provider": provider_state,
        "routing_model": config.get("routing", {}).get("model", ""),
        "upstream_model": config.get("upstream", {}).get("model", ""),
        "mtclaw": mtclaw_state,
    }

@app.get("/v1/models")
async def list_models():
    provider_state = model_provider_status(config) if config else {"model": "clawos-agent", "provider": "clawos"}
    return JSONResponse({"object":"list","data":[{"id":provider_state["model"],"object":"model","owned_by":provider_state["provider"]}]})

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.body()
        req_data = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    messages = req_data.get("messages", [])
    if not messages:
        raise HTTPException(400, "messages array required")

    user_text = ""
    session_id = req_data.get("session_id", "default")
    confirmed_tools = _confirmed_tools_from_request(req_data)
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            user_text = str(m["content"])
            break

    stream = req_data.get("stream", False)

    if not user_text:
        resp = await proxy_upstream(req_data, stream)
        if isinstance(resp, JSONResponse):
            await store_assistant_response(session_id, resp)
        return resp

    # --- TOOL ROUTING ---
    if g_context_builder:
        g_context_builder.ingest_and_store(session_id, "user", user_text)
    elif g_memory_store:
        g_memory_store.add_message(session_id, "user", user_text)

    if g_mtclaw_adapter and g_mtclaw_adapter.enabled and not stream:
        mtclaw_messages = (
            g_context_builder.build_messages(session_id, user_text)
            if g_context_builder
            else messages
        )
        mtclaw_result = await g_mtclaw_adapter.route(
            mtclaw_messages,
            session_id,
            {"temperature": req_data.get("temperature", 0.0)},
        )
        if g_memory_store:
            g_memory_store.record_mtclaw_trace(
                session_id=session_id,
                route_status="success" if mtclaw_result["ok"] else "fallback",
                provider_url=g_mtclaw_adapter.base_url,
                model=mtclaw_result.get("model", ""),
                duration_ms=mtclaw_result.get("duration_ms", 0),
                tool_history=mtclaw_result.get("trace", []),
                error=mtclaw_result.get("error", ""),
            )
        if mtclaw_result["ok"]:
            trace = mtclaw_result.get("trace", [])
            text = mtclaw_result.get("content", "")
            if g_memory_store and text:
                g_memory_store.add_message(session_id, "assistant", text[:4000])
            raw = mtclaw_result.get("raw") or build_openai_response(text)
            raw["clawos"] = {
                "mtclaw": {
                    "used": True,
                    "provider": g_mtclaw_adapter.base_url,
                    "duration_ms": mtclaw_result.get("duration_ms", 0),
                    "trace": trace,
                },
                "used_tools": bool(trace),
                "tool_calls": [
                    {
                        "name": item.get("function_name", ""),
                        "arguments": item.get("tool_input", {}),
                        "result": item.get("tool_result", {}),
                    }
                    for item in trace
                ],
            }
            return JSONResponse(raw)
        if not g_mtclaw_adapter.fallback_on_error:
            raise HTTPException(503, f"MTClaw unavailable: {mtclaw_result['error']}")

    tool_result = await run_tool_loop(user_text, session_id, confirmed_tools)
    confirmation_calls = [
        tc for tc in tool_result.get("tool_calls", [])
        if isinstance(tc.get("result"), dict) and tc["result"].get("status") == "needs_confirmation"
    ]
    if confirmation_calls:
        names = ", ".join(tc.get("name", "") for tc in confirmation_calls)
        text = f"需要你确认后才能执行高风险工具：{names}。确认后请重新发送请求，并在 clawos_confirmed_tools 中包含这些工具名。"
        extra = {
            "used_tools": True,
            "tool_calls": tool_result.get("tool_calls", []),
            "needs_confirmation": True,
            "routing_rounds": tool_result.get("routing_rounds", 0),
            "matched_skill": tool_result.get("matched_skill", ""),
        }
        if g_memory_store:
            g_memory_store.add_message(session_id, "assistant", text[:4000])
        if stream:
            return sse_from_text(text)
        return JSONResponse(build_openai_response(text, extra=extra))

    # Auto-trigger reflection after tool execution
    reflection_result = None
    if tool_result["used_tools"] and g_reflection_engine:
        try:
            trigger = g_reflection_engine.should_reflect(
                tool_result["tool_calls"], user_text)
            if trigger:
                reflection_result = g_reflection_engine.reflect(
                    trigger, session_id,
                    tool_result["tool_calls"],
                    "", user_text[:100])
                if g_vector_store:
                    g_vector_store.refresh()
        except Exception as e:
            logger.warning(f"Reflection failed: {e}")

    if tool_result["used_tools"]:
        tc_lines = ""
        for tc in tool_result["tool_calls"]:
            tc_lines += f"\n[Tool: {tc['name']}]\n{json.dumps(tc['result'], ensure_ascii=False, indent=2)}\n"

        upstream_msgs = [
            {"role": "system", "content": g_context_builder.build_system_prompt(session_id) if g_context_builder else SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": f"I executed these tools based on your request:\n{tc_lines}\n\nBased strictly on the tool results above and the conversation context, provide a concise and helpful answer. Address the user's original request directly."}
        ]
        # Store tool-call context in memory before returning
        if g_memory_store:
            for tc in tool_result["tool_calls"]:
                g_memory_store.add_message(session_id, "tool", json.dumps(tc.get("result", {}), ensure_ascii=False)[:4000])

        extra = {
            "used_tools": True,
            "tool_calls": tool_result["tool_calls"],
            "reflection": reflection_result,
            "routing_rounds": tool_result.get("routing_rounds", 0),
            "matched_skill": tool_result.get("matched_skill", ""),
        }
        if not has_api_key("upstream"):
            text = "已完成本地工具执行，结果如下：\n" + tc_lines.strip()
            body = build_openai_response(text, extra=extra)
            if g_memory_store:
                g_memory_store.add_message(session_id, "assistant", text[:4000])
            if stream:
                return sse_from_text(text)
            return JSONResponse(body)
        resp = await proxy_upstream({**req_data, "messages": upstream_msgs}, stream)
        if isinstance(resp, JSONResponse):
            text = extract_assistant_text(resp)
            body = json.loads(resp.body)
            body["clawos"] = extra
            if g_memory_store and text:
                g_memory_store.add_message(session_id, "assistant", text[:4000])
            return JSONResponse(body)
        return resp

    final_text = tool_result.get("final_text", "")
    if stream:
        if g_memory_store and final_text:
            g_memory_store.add_message(session_id, "assistant", final_text[:4000])
        return sse_from_text(final_text)

    resp_payload = build_openai_response(final_text, extra={
        "used_tools": False,
        "tool_calls": [],
        "routing_rounds": tool_result.get("routing_rounds", 0),
    })
    if g_memory_store and final_text:
        g_memory_store.add_message(session_id, "assistant", final_text[:4000])
    return JSONResponse(resp_payload)

# ---- MAIN ----

@app.post("/api/reflection/trigger")
async def trigger_reflection(request: Request):
    if not g_reflection_engine:
        raise HTTPException(503, "Reflection Engine not initialized")
    try:
        body = await request.body()
        req_data = json.loads(body) if body else {}
    except:
        req_data = {}
    sid = req_data.get("session_id", "default")
    task = req_data.get("task", "Manual reflection")
    fb = req_data.get("feedback", "")
    result = g_reflection_engine.reflect("user_triggered", sid, [], fb, task)
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse(result)

@app.get("/api/reflection/list")
async def list_reflections(limit: int = 20):
    if not g_reflection_engine:
        raise HTTPException(503, "Reflection Engine not initialized")
    from reflection.memory_writer import ReflectionMemoryWriter
    writer = ReflectionMemoryWriter(g_memory_store)
    cards = writer.get_reflection_cards(limit)
    return JSONResponse({"cards": cards, "count": len(cards)})

@app.get("/api/reflection/stats")
async def reflection_stats():
    if not g_reflection_engine:
        raise HTTPException(503, "Reflection Engine not initialized")
    from reflection.learning_loop import LearningLoop
    loop = LearningLoop(g_reflection_engine, g_memory_store)
    return JSONResponse(loop.get_cycle_stats())



@app.get("/api/memory/stats")
async def memory_stats():
    if g_memory_store:
        try:
            stats = g_memory_store.get_stats()
            if g_vector_store:
                stats["vectors"] = g_vector_store.stats().get("vector_count", 0)
            return JSONResponse(stats)
        except Exception as e:
            raise HTTPException(500, str(e))
    return JSONResponse({"error": "MemoryOS not initialized"}, status_code=503)

@app.get("/api/memory/items")
async def api_memory_items(memory_type: str = "", include_disabled: bool = False, limit: int = 200):
    rows = list_memory_items(memory_type, include_disabled, limit)
    return JSONResponse({"items": rows, "count": len(rows)})

@app.post("/api/memory/items")
async def api_memory_item_save(request: Request):
    data = await request.json()
    item = save_memory_item(data)
    return JSONResponse({"item": item, "saved": True})

@app.post("/api/memory/items/{memory_id}/enabled")
async def api_memory_item_enabled(memory_id: int, request: Request):
    data = await request.json()
    item = set_memory_item_enabled(memory_id, bool(data.get("enabled", True)))
    return JSONResponse({"item": item, "updated": True})

@app.get("/api/memory/items/search")
async def api_memory_items_search(q: str = "", memory_type: str = "", include_disabled: bool = False, limit: int = 20):
    if not g_memory_store:
        return JSONResponse({"items": [], "count": 0}, status_code=503)
    rows = g_memory_store.search_memories(q, memory_type, limit, include_disabled)
    return JSONResponse({"items": rows, "count": len(rows)})

@app.get("/api/memory/profiles")
async def api_memory_profiles():
    if not g_memory_store:
        return JSONResponse({"profiles": [], "count": 0}, status_code=503)
    profiles = g_memory_store.get_all_profiles()
    return JSONResponse({"profiles": profiles, "count": len(profiles)})

@app.post("/api/memory/profiles")
async def api_memory_profile_set(request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    data = await request.json()
    key = str(data.get("key", "")).strip()
    value = str(data.get("value", "")).strip()
    if not key or not value:
        raise HTTPException(400, "key and value are required")
    g_memory_store.set_profile(
        key,
        value,
        str(data.get("category", "general") or "general"),
        float(data.get("importance", 0.7)),
    )
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"set": True, "key": key, "value": value})

@app.get("/api/memory/preferences")
async def api_memory_preferences():
    if not g_memory_store:
        return JSONResponse({"preferences": [], "count": 0}, status_code=503)
    prefs = g_memory_store.get_all_preferences()
    return JSONResponse({"preferences": prefs, "count": len(prefs)})

@app.post("/api/memory/preferences")
async def api_memory_preference_set(request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    data = await request.json()
    key = str(data.get("key", "")).strip()
    value = str(data.get("value", "")).strip()
    if not key or not value:
        raise HTTPException(400, "key and value are required")
    g_memory_store.set_preference(
        key,
        value,
        str(data.get("category", "general") or "general"),
        float(data.get("confidence", 0.8)),
    )
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"set": True, "key": key, "value": value})

@app.get("/api/memory/experiences")
async def api_memory_experiences(limit: int = 20):
    if not g_memory_store:
        return JSONResponse({"experiences": [], "count": 0}, status_code=503)
    experiences = g_memory_store.get_recent_experiences(min(limit, 100))
    return JSONResponse({"experiences": experiences, "count": len(experiences)})

@app.get("/api/skills/list")
async def skills_list():
    try:
        from skills.skill_registry import list_skills
        return JSONResponse({"skills": list_skills(), "count": len(list_skills())})
    except Exception as e:
        return JSONResponse({"skills": [], "count": 0, "error": str(e)})

@app.get("/api/skills/stats")
async def skills_stats():
    if not g_memory_store:
        return JSONResponse({"records": [], "count": 0})
    records = g_memory_store.get_skill_stats()
    return JSONResponse({"records": records, "count": len(records)})

@app.get("/api/tools/list")
async def api_tools_list():
    items = []
    for t in tools_def:
        fn = t.get("function", {})
        items.append({
            "name": fn.get("name", ""),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters", {}),
        })
    return JSONResponse({"tools": items, "count": len(items)})

@app.get("/api/tools/executions")
async def api_tool_executions(session_id: str = "", limit: int = 50):
    if not g_memory_store:
        return JSONResponse({"executions": [], "count": 0}, status_code=503)
    rows = g_memory_store.list_tool_executions(session_id, limit)
    return JSONResponse({"executions": rows, "count": len(rows)})

@app.get("/api/mtclaw/traces")
async def api_mtclaw_traces(session_id: str = "", limit: int = 50):
    if not g_memory_store:
        return JSONResponse({"traces": [], "count": 0}, status_code=503)
    rows = g_memory_store.list_mtclaw_traces(session_id, limit)
    return JSONResponse({"traces": rows, "count": len(rows)})

@app.get("/api/memory/context/{session_id}")
async def memory_context(session_id: str):
    if g_memory_store:
        try:
            msgs = g_memory_store.get_recent_messages(session_id, 20)
            return JSONResponse({"session_id": session_id, "messages": msgs, "count": len(msgs)})
        except Exception as e:
            raise HTTPException(500, str(e))
    return JSONResponse({"error": "MemoryOS not initialized"}, status_code=503)
@app.get("/api/history/{session_id}")
async def get_history(session_id: str, limit: int = 50):
    """Get conversation history for a session."""
    if g_memory_store:
        try:
            msgs = g_memory_store.get_recent_messages(session_id, limit)
            clean = [{"role": m["role"], "content": m.get("content", "")[:2000]} for m in msgs if m["role"] in ("user", "assistant")]
            return JSONResponse({"session_id": session_id, "messages": clean, "count": len(clean)})
        except Exception as e:
            raise HTTPException(500, str(e))
    return JSONResponse({"error": "MemoryOS not ready"}, status_code=503)
@app.get("/api/sessions")
async def api_list_sessions():
    if g_memory_store:
        try:
            sessions = g_memory_store.list_sessions()
            return JSONResponse({"sessions": sessions, "count": len(sessions)})
        except Exception as e:
            raise HTTPException(500, str(e))
    return JSONResponse({"sessions": [], "count": 0})

@app.get("/api/memory/search")
async def api_memory_search(q: str = "", top_k: int = 10):
    if not q or not g_vector_store:
        return JSONResponse({"results": []})
    try:
        results = g_vector_store.search(q, min(20, top_k))
        return JSONResponse({"results": results, "count": len(results)})
    except Exception as e:
        return JSONResponse({"results": [], "error": str(e)})

@app.get("/api/memory/refresh")
async def api_memory_refresh():
    if g_vector_store:
        try:
            g_vector_store.refresh()
            return JSONResponse({"refreshed": True, "stats": g_vector_store.stats()})
        except Exception as e:
            return JSONResponse({"refreshed": False, "error": str(e)})
    return JSONResponse({"refreshed": False, "error": "VectorStore not initialized"})


def main():
    parser = argparse.ArgumentParser(description="ClawOS Agent")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18790)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
if __name__ == "__main__":
    main()

