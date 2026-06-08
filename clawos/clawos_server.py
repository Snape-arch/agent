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

# ---- PATHS ----
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = BASE_DIR / "config.json"
SCRIPTS_DIR = BASE_DIR / "scripts"
NOTES_DIR = BASE_DIR / "notes"
TODO_FILE = BASE_DIR / "clawos_todo.json"

MEMORY_DB = BASE_DIR / "memoryos.db"

g_memory_store: Any = None
g_reflection_engine: Any = None
g_context_builder: Any = None
g_vector_store: MemoryVectorStore | None = None

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
    return _sub(cfg)

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

# ---- LLM ROUTING ----
async def call_routing_llm(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Call DeepSeek for tool detection."""
    payload = {
        "model": config["routing"]["model"],
        "messages": messages,
        "tools": tools_def,
        "stream": False,
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {config['routing']['api_key']}",
        "Content-Type": "application/json",
    }
    url = f"{config['routing']['base_url'].rstrip('/')}/chat/completions"
    resp = await http_client.post(url, json=payload, headers=headers, timeout=15.0)
    resp.raise_for_status()
    return resp.json()

async def run_tool_loop(user_text: str, session_id: str = "default") -> dict[str, Any]:
    """Tool detection + execution loop."""
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
        assistant_msg = {"role": "assistant", "content": content}
        tc_msgs = []
        for tc in tcs:
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            fn_args = fn.get("arguments", "{}")
            tc_id = tc.get("id", f"call_{fn_name}_{ri}")
            tc_msgs.append({"id": tc_id, "type": "function", "function": {"name": fn_name, "arguments": fn_args}})
            logger.info(f"Tool: {fn_name}({fn_args[:150]})")
            result = execute_python_tool(fn_name, fn_args)
            tc_log.append({"name": fn_name, "arguments": fn_args, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc_id, "name": fn_name, "content": json.dumps(result, ensure_ascii=False)})
        assistant_msg["tool_calls"] = tc_msgs
        messages.append(assistant_msg)

    return {"used_tools": True, "tool_calls": tc_log, "final_text": "", "routing_rounds": max_rounds}

# ---- UPSTREAM PROXY ----
async def proxy_upstream(req_data: dict, stream: bool, tool_context: str = "") -> StreamingResponse:
    upstream = config["upstream"] if config else {}
    url = f"{upstream.get('base_url','').rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {upstream.get('api_key','')}", "Content-Type": "application/json"}
    req_data["model"] = upstream.get("model", "deepseek-chat")

    if not stream:
        try:
            resp = await http_client.post(url, json=req_data, headers=headers, timeout=120.0)
            resp.raise_for_status()
            return JSONResponse(resp.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(e.response.status_code, str(e))
    else:
        async def sse_stream():
            async with http_client.stream("POST", url, json=req_data, headers=headers, timeout=120.0) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    err = json.dumps({"error": body.decode("utf-8", errors="replace")[:200]})
                    yield f"data: {err}\n\ndata: [DONE]\n\n".encode()
                    return
                async for chunk in resp.aiter_bytes():
                    yield chunk
        return StreamingResponse(sse_stream(), media_type="text/event-stream")

# ---- LIFESPAN ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, tools_def, http_client, logger
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("clawos")
    config = load_config(CONFIG_PATH)
    config.setdefault("max_tool_rounds", 6)
    func_path = Path(config.get("functions_file", BASE_DIR / "functions.jsonl"))
    tools_def = load_tools(func_path)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    NOTES_DIR.mkdir(exist_ok=True)
    # Init MemoryOS
    global g_memory_store, g_context_builder
    from memoryos.memory_store import MemoryStore
    from memoryos.context_builder import ContextBuilder
    from memoryos.services.vector_store import MemoryVectorStore
    g_memory_store = MemoryStore(str(MEMORY_DB))
    g_context_builder = ContextBuilder(g_memory_store)
    
    # Init VectorStore for semantic memory search
    g_vector_store = MemoryVectorStore(str(MEMORY_DB))
    g_vector_store.refresh()  # Load existing data
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

    # Validate API key
    routing_key = config.get("routing", {}).get("api_key", "")
    if not routing_key or "${" in str(routing_key):
        logger.error("!!! DEEPSEEK_API_KEY not configured!")
        logger.error("!!! Set environment variable: set DEEPSEEK_API_KEY=sk-your-key")
        logger.error("!!! Or edit config.json to include your API key directly")
    else:
        logger.info(f"API key configured: {routing_key[:8]}...")
    
    logger.info(f"ClawOS ready | routing={config['routing']['model']} upstream={config['upstream']['model']} tools={len(tools_def)}")
    if config["routing"]["api_key"] == "YOUR_DEEPSEEK_API_KEY":
        logger.warning("!!! DEEPSEEK_API_KEY not configured! Set env DEEPSEEK_API_KEY or edit config.json")
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
    return {"status": "ok", "version": "1.0.0", "tools": len(tools_def)}

@app.get("/v1/models")
async def list_models():
    return JSONResponse({"object":"list","data":[{"id":config.get("upstream",{}).get("model","deepseek-chat"),"object":"model","owned_by":"clawos"}]})

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
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            user_text = str(m["content"])
            break

    stream = req_data.get("stream", False)

    if not user_text:
        resp = await proxy_upstream(req_data, stream)
    if g_memory_store and not stream:
        try:
            body = json.loads(resp.body)
            for ch in body.get("choices", []):
                m = ch.get("message", {})
                if m.get("content"):
                    g_memory_store.add_message(session_id, "assistant", m["content"][:4000])
        except Exception:
            pass
    return resp

    # --- TOOL ROUTING ---
    tool_result = await run_tool_loop(user_text, session_id)

    if g_memory_store:
        g_memory_store.add_message(session_id, "user", user_text)

    # Auto-trigger reflection after tool execution
    if tool_result["used_tools"] and g_reflection_engine:
        try:
            trigger = g_reflection_engine.should_reflect(
                tool_result["tool_calls"], user_text)
            if trigger:
                g_reflection_engine.reflect(
                    trigger, session_id,
                    tool_result["tool_calls"],
                    "", user_text[:100])
        except Exception:
            pass  # Don't block main flow

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

        return await proxy_upstream({**req_data, "messages": upstream_msgs}, stream)

    # Also store assistant responses when not using tools (plain chat)
    if not tool_result["used_tools"] and g_memory_store:
        # Store user query in memory for context
        pass

    resp = await proxy_upstream(req_data, stream)
    if g_memory_store and not stream:
        try:
            body = json.loads(resp.body)
            for ch in body.get("choices", []):
                m = ch.get("message", {})
                if m.get("content"):
                    g_memory_store.add_message(session_id, "assistant", m["content"][:4000])
        except Exception:
            pass
    return resp

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
            return JSONResponse(g_memory_store.get_stats())
        except Exception as e:
            raise HTTPException(500, str(e))
    return JSONResponse({"error": "MemoryOS not initialized"}, status_code=503)

@app.get("/api/skills/list")
async def skills_list():
    try:
        from skills.skill_registry import list_skills
        return JSONResponse({"skills": list_skills(), "count": len(list_skills())})
    except Exception as e:
        return JSONResponse({"skills": [], "count": 0, "error": str(e)})

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

