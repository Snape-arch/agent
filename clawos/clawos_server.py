#!/usr/bin/env python3
"""ClawOS Server - Self-contained AI Agent with DeepSeek + Function Router."""
from __future__ import annotations
import argparse, asyncio, importlib.util, json, logging, os, re, sys, time, subprocess, shutil
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from providers import create_model_provider
from services import KnowledgeService, MaintenanceService, ModelService, SecurityService, TaskService, ToolService

# ---- PATHS ----
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = BASE_DIR / "config.json"
SCRIPTS_DIR = BASE_DIR / "scripts"
NOTES_DIR = BASE_DIR / "notes"
TODO_FILE = BASE_DIR / "clawos_todo.json"
UPLOAD_DIR = BASE_DIR / "uploads"


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key == "CLAWOS_MEMORY_DB" and value:
            db_path = Path(value).expanduser()
            if not db_path.is_absolute():
                value = str((env_path.parent / db_path).resolve())
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env(BASE_DIR / ".env")

MEMORY_DB = Path(os.environ.get("CLAWOS_MEMORY_DB", str(BASE_DIR / "memoryos.db"))).expanduser().resolve()

g_memory_store: Any = None
g_reflection_engine: Any = None
g_context_builder: Any = None
g_vector_store: MemoryVectorStore | None = None
g_mtclaw_adapter: Any = None
g_policy_optimizer: Any = None
g_security_policy: Any = None
g_secret_manager: Any = None
g_workspace_services: Any = None
g_skill_evolution: Any = None
g_scenario_benchmark: Any = None
g_knowledge_service: KnowledgeService | None = None
g_security_service: SecurityService | None = None
g_task_service: TaskService | None = None
g_maintenance_service: MaintenanceService | None = None
g_background_worker_task: asyncio.Task | None = None
g_background_worker_status: dict[str, Any] = {
    "running": False,
    "worker_id": "",
    "processed": 0,
    "last_result": None,
    "last_error": "",
}

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
mtclaw_http_client: httpx.AsyncClient | None = None
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
    provider_name = str(provider_cfg.get("provider") or "deepseek").lower()
    if provider_name == "qwen":
        if not provider_cfg.get("base_url") or provider_cfg.get("base_url") == "https://api.deepseek.com/v1":
            provider_cfg["base_url"] = os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8000/v1")
        if not provider_cfg.get("model") or provider_cfg.get("model") == "deepseek-chat":
            provider_cfg["model"] = os.environ.get("QWEN_MODEL", "Qwen3.5-9B-Q4_K_M")
        if "MODEL_REQUIRES_API_KEY" not in os.environ:
            provider_cfg["requires_api_key"] = False
    if provider_name == "qwen_api":
        if not provider_cfg.get("base_url") or provider_cfg.get("base_url") == "https://api.deepseek.com/v1":
            provider_cfg["base_url"] = os.environ.get("QWEN_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        if not provider_cfg.get("model") or provider_cfg.get("model") == "deepseek-chat":
            provider_cfg["model"] = os.environ.get("QWEN_API_MODEL", "qwen-plus")
    if provider_name in {"glm", "zhipu"}:
        if not provider_cfg.get("base_url") or provider_cfg.get("base_url") == "https://api.deepseek.com/v1":
            provider_cfg["base_url"] = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
        if not provider_cfg.get("model") or provider_cfg.get("model") == "deepseek-chat":
            provider_cfg["model"] = os.environ.get("GLM_MODEL", "glm-4-flash")
    if provider_name == "deepseek":
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


def _config_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def model_provider_status(cfg: dict[str, Any]) -> dict[str, Any]:
    return ModelService(cfg, create_model_provider).status()


MODEL_ENV_KEYS = {
    "provider": "MODEL_PROVIDER",
    "base_url": "MODEL_BASE_URL",
    "model": "MODEL_NAME",
    "api_key": "MODEL_API_KEY",
    "requires_api_key": "MODEL_REQUIRES_API_KEY",
}


def _mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    suffix = value[-4:] if len(value) > 4 else value[-1:]
    return f"set (...{suffix})"


def model_config_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    provider_cfg = dict((cfg or {}).get("model_provider") or {})
    status = model_provider_status(cfg) if cfg else {"provider": "", "model": "", "configured": False}
    api_key = str(provider_cfg.get("api_key") or "")
    return {
        "provider": str(provider_cfg.get("provider") or status.get("provider") or "deepseek"),
        "base_url": str(provider_cfg.get("base_url") or ""),
        "model": str(provider_cfg.get("model") or status.get("model") or ""),
        "configured": bool(status.get("configured")),
        "api_key_present": bool(api_key and "${" not in api_key),
        "api_key_hint": _mask_secret(api_key),
        "requires_api_key": _config_bool(provider_cfg.get("requires_api_key"), True),
        "mode": model_mode_label(status.get("provider", ""), bool(status.get("configured"))),
    }


def model_mode_label(provider: str, configured: bool) -> str:
    return ModelService.mode_label(provider, configured)


def write_model_env(env_path: Path, updates: dict[str, str]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    remaining: list[str] = []
    pending = {key: str(value) for key, value in updates.items()}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            remaining.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in pending:
            remaining.append(f"{key}={pending.pop(key)}")
        else:
            remaining.append(line)
    for key, value in pending.items():
        remaining.append(f"{key}={value}")
    env_path.write_text("\n".join(remaining).rstrip() + "\n", encoding="utf-8")


def apply_model_config_updates(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"deepseek", "openai_compatible", "openai-compatible", "local_openai", "qwen", "qwen_api", "glm", "zhipu", "mock"}
    provider = str(payload.get("provider") or "deepseek").strip()
    if provider not in allowed:
        raise ValueError(f"Unsupported model provider: {provider}")

    updates = {
        "MODEL_PROVIDER": provider,
        "MODEL_BASE_URL": str(payload.get("base_url") or "").strip(),
        "MODEL_NAME": str(payload.get("model") or "").strip(),
    }
    if "requires_api_key" in payload:
        updates["MODEL_REQUIRES_API_KEY"] = "true" if payload.get("requires_api_key") else "false"
    if "api_key" in payload:
        updates["MODEL_API_KEY"] = str(payload.get("api_key") or "").strip()

    write_model_env(BASE_DIR / ".env", updates)
    for key, value in updates.items():
        os.environ[key] = value

    global config, g_routing_provider, g_upstream_provider, g_reflection_engine
    config = load_config(CONFIG_PATH)
    config.setdefault("max_tool_rounds", 6)
    g_routing_provider = create_model_provider(config.get("routing", {}))
    g_upstream_provider = create_model_provider(config.get("upstream", {}))
    if g_memory_store and http_client:
        try:
            from reflection.engine import ReflectionEngine
            g_reflection_engine = ReflectionEngine(g_memory_store, http_client, config.get("routing", {}))
        except Exception as exc:
            if logger:
                logger.warning(f"Reflection Engine refresh skipped: {exc}")
    return model_config_payload(config)

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
    "template_instantiate",
}

def execute_python_tool(name: str, args_str: str) -> dict[str, Any]:
    """Execute a tool in a separate worker process with a hard timeout."""
    if name in ("bash", "exec", "sh"):
        name = "shell_exec"
    timeout_s = max(1, min(int(config.get("tool_exec_timeout_s", 30) if config else 30), 60))
    allowed_env = {
        key: value for key, value in os.environ.items()
        if key.upper() in {
            "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
            "USERPROFILE", "HOME", "TEMP", "TMP", "CLAWOS_MEMORY_DB",
            "CLAWOS_ALLOWED_ROOTS", "PYTHONPATH",
            "BING_SEARCH_API_KEY", "BING_SEARCH_ENDPOINT", "SERPAPI_API_KEY", "TAVILY_API_KEY",
        }
    }
    command = [sys.executable, str(SCRIPTS_DIR / "tool_worker.py"), name]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            command,
            input=args_str or "{}",
            cwd=str(BASE_DIR),
            env=allowed_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            creationflags=creationflags,
        )
        output = proc.stdout.strip()
        if not output:
            return {"error": proc.stderr.strip() or f"Tool worker exited with code {proc.returncode}"}
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            result = {"result": output[:2000]}
        if proc.returncode and not result.get("error"):
            result["error"] = proc.stderr.strip() or f"Tool worker exited with code {proc.returncode}"
        return result
    except subprocess.TimeoutExpired:
        return {"error": f"Tool worker timed out after {timeout_s}s"}


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


def _task_step_status(tool_status: str) -> str:
    return ToolService.task_step_status(tool_status)


def _tool_service() -> ToolService:
    return ToolService(
        python_executor=execute_python_tool,
        store_getter=lambda: g_memory_store,
        policy_getter=lambda: g_security_policy,
        vector_refresh=(lambda: g_vector_store.refresh()) if g_vector_store else None,
        logger=logger,
        confirmation_tools=TOOLS_REQUIRING_CONFIRMATION,
    )


def execute_tool_call(
    name: str,
    args_str: str,
    session_id: str = "default",
    confirmed_tools: set[str] | None = None,
    task_id: int | None = None,
) -> dict[str, Any]:
    """Execute a tool and return a stable envelope for tracing and reflection."""
    return _tool_service().execute(
        name,
        args_str,
        session_id=session_id,
        confirmed_tools=confirmed_tools or set(),
        task_id=task_id,
    )

# ---- LLM ROUTING ----
def _provider_candidates(section: str) -> list[Any]:
    primary = g_routing_provider if section == "routing" else g_upstream_provider
    configs = config.get(f"{section}_fallbacks", []) or config.get("model_fallbacks", [])
    candidates = [primary] if primary else []
    for cfg in configs:
        if isinstance(cfg, dict):
            candidates.append(create_model_provider(cfg))
    return candidates


async def call_model_with_fallback(section: str, messages: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
    attempts = []
    for provider in _provider_candidates(section):
        if not provider:
            continue
        result = await provider.complete(messages, options, http_client=http_client)
        attempts.append({
            "provider": result.get("provider", getattr(provider, "name", "")),
            "model": result.get("model", getattr(provider, "model", "")),
            "ok": bool(result.get("ok")),
            "error": result.get("error", ""),
            "duration_ms": result.get("duration_ms", 0),
        })
        if result.get("ok"):
            result["fallback_attempts"] = attempts
            return result
    return {
        "ok": False,
        "provider": section,
        "model": "",
        "content": "",
        "raw": {},
        "usage": {},
        "duration_ms": 0,
        "error": attempts[-1]["error"] if attempts else "no_provider",
        "fallback_attempts": attempts,
    }


async def call_routing_llm(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Call configured model provider for tool detection."""
    result = await call_model_with_fallback(
        "routing",
        messages,
        {
        "tools": tools_def,
        "temperature": 0.0,
        }
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


SCENARIO_ROUTING_POLICY = {
    "research": {"tools": ["web_search", "web_fetch", "research_pdf"], "risk": "medium", "model_profile": "deep_reasoning", "retrieval": "citations_required", "requires_confirmation": ["web_fetch"], "description": "科研检索、网页抓取、论文解析和可引用 RAG"},
    "learning": {"tools": ["learning_workspace", "web_fetch", "exam_practice_builder"], "risk": "medium", "model_profile": "tutor", "retrieval": "knowledge_first", "requires_confirmation": ["web_fetch"], "description": "学习目标、资料入库、练习题和掌握度"},
    "office": {"tools": ["meeting_workflow", "office_artifact", "work_brief_builder"], "risk": "medium", "model_profile": "structured_output", "retrieval": "workspace_context", "requires_confirmation": ["office_artifact"], "description": "会议、简报、表格和演示文稿产物"},
    "project": {"tools": ["ls", "grep_text", "code_stats", "git_workspace"], "risk": "high", "model_profile": "code_agent", "retrieval": "repo_context", "requires_confirmation": ["git_workspace"], "description": "项目分析、代码检索和审批式 Git 操作"},
    "web": {"tools": ["web_search", "web_fetch"], "risk": "medium", "model_profile": "fresh_context", "retrieval": "web_then_rag", "requires_confirmation": ["web_fetch"], "description": "联网搜索和网页正文抓取"},
    "general": {"tools": ["memory_history", "tools_list", "note_save"], "risk": "low", "model_profile": "balanced", "retrieval": "memory_optional", "requires_confirmation": [], "description": "通用对话、记忆和轻量记录"},
}


SCENARIO_ROUTING_KEYWORDS = {
    "research": ["论文", "科研", "文献", "引用", "citation", "paper", "research", "zotero", "实验", "复现"],
    "learning": ["学习", "考试", "复习", "课程", "题目", "掌握", "exam", "learn", "quiz"],
    "office": ["会议", "纪要", "汇报", "ppt", "excel", "brief", "meeting", "邮件", "表格"],
    "project": ["代码", "项目", "git", "repo", "bug", "测试", "commit", "重构", "架构"],
    "web": ["搜索", "联网", "网页", "爬取", "url", "http", "search", "crawl", "fetch"],
}


def classify_scenario(text: str) -> str:
    low = str(text or "").lower()
    mapping = [
        ("research", ["论文", "科研", "文献", "paper", "research", "citation"]),
        ("learning", ["学习", "考试", "复习", "课程", "exam", "learn"]),
        ("office", ["会议", "纪要", "汇报", "ppt", "excel", "meeting", "brief"]),
        ("project", ["代码", "项目", "git", "repo", "bug", "测试", "commit"]),
        ("web", ["搜索", "联网", "网页", "url", "http", "search", "crawl"]),
    ]
    for scenario, keys in mapping:
        if any(k in low for k in keys):
            return scenario
    return "general"


def score_scenarios(text: str) -> list[dict[str, Any]]:
    low = str(text or "").lower()
    rows: list[dict[str, Any]] = []
    for scenario, policy in SCENARIO_ROUTING_POLICY.items():
        keys = SCENARIO_ROUTING_KEYWORDS.get(scenario, [])
        hits = [key for key in keys if key.lower() in low]
        score = 0.18 if scenario == "general" else 0.0
        score += min(0.62, 0.16 * len(hits))
        if scenario == "research" and any(k in low for k in ["pdf", "docx", "rag", "chunk", "引用", "文献"]):
            score += 0.16
        if scenario == "web" and any(k in low for k in ["http://", "https://", "url", "网页"]):
            score += 0.18
        if scenario == "project" and any(k in low for k in ["写入", "commit", "git", "文件", "shell"]):
            score += 0.12
        if scenario == "office" and any(k in low for k in ["xlsx", "pptx", "docx", "表格", "演示"]):
            score += 0.12
        if not low.strip() and scenario == "general":
            score = 0.52
        rows.append({
            "scenario": scenario,
            "score": round(min(score, 0.98), 4),
            "matched_keywords": hits[:8],
            "risk": policy.get("risk", "low"),
            "tools": policy.get("tools", []),
            "model_profile": policy.get("model_profile", "balanced"),
            "retrieval": policy.get("retrieval", "memory_optional"),
            "requires_confirmation": policy.get("requires_confirmation", []),
            "reason": "keyword_match" if hits else ("default_low_risk" if scenario == "general" else "available_capability"),
        })
    rows.sort(key=lambda item: (item["score"], -len(item.get("requires_confirmation", []))), reverse=True)
    if rows and rows[0]["score"] <= 0:
        rows = sorted(rows, key=lambda item: item["scenario"] != "general")
        rows[0]["score"] = 0.52
        rows[0]["reason"] = "default_low_risk"
    return rows


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
    task_id: int | None = None,
) -> dict[str, Any]:
    """Tool detection + execution loop."""
    confirmed_tools = confirmed_tools or set()
    # Fast path: known solidified skills should bypass the LLM router.
    try:
        from skills.skill_registry import match_skill_by_text
        matched_skill = match_skill_by_text(user_text)
        if matched_skill:
            args = json.dumps({"name": matched_skill["name"], "params": {}}, ensure_ascii=False)
            result = execute_tool_call("skill_execute", args, session_id, confirmed_tools, task_id=task_id)
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
        result = execute_tool_call(fn_name, fn_args, session_id, confirmed_tools, task_id=task_id)
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
            result = execute_tool_call(fn_name, fn_args, session_id, confirmed_tools, task_id=task_id)
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


def sse_from_text(text: str, task_id: int | None = None, extra: dict[str, Any] | None = None) -> StreamingResponse:
    async def gen():
        if extra:
            yield f"event: clawos_meta\ndata: {json.dumps(extra, ensure_ascii=False)}\n\n".encode("utf-8")
        content = text or ""
        if not content:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': ''}}]}, ensure_ascii=False)}\n\n".encode("utf-8")
        cursor = 0
        chunk_size = 80
        while cursor < len(content):
            if task_id and g_memory_store and g_memory_store.is_task_cancelled(task_id):
                cancel_payload = {
                    "choices": [{"delta": {"content": "\n\n任务已取消。"}}],
                    "clawos": {"task_id": task_id, "canceled": True},
                }
                yield f"event: canceled\ndata: {json.dumps(cancel_payload, ensure_ascii=False)}\n\n".encode("utf-8")
                finish_runtime_task(task_id, "canceled", "Canceled during stream")
                break
            piece = content[cursor: cursor + chunk_size]
            cursor += chunk_size
            chunk = {"choices": [{"delta": {"content": piece}}]}
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8")
            await asyncio.sleep(0)
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
            actor_id=str(data.get("actor_id", "system") or "system"),
            owner_id=str(data.get("owner_id", "default") or "default"),
            workspace_id=str(data.get("workspace_id", "default") or "default"),
            evidence=data.get("evidence", []),
            change_reason=str(data.get("change_reason", "") or ""),
            conflict_policy=str(data.get("conflict_policy", "overwrite") or "overwrite"),
        )
        if g_vector_store:
            g_vector_store.refresh()
        return item
    except ValueError as e:
        raise HTTPException(400, str(e))


def get_task_service() -> TaskService:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    global g_task_service
    if not g_task_service or getattr(g_task_service, "store", None) is not g_memory_store:
        g_task_service = TaskService(g_memory_store, action_handlers=worker_action_handlers())
    return g_task_service


def get_security_service() -> SecurityService:
    if not g_security_policy and not g_secret_manager and not g_memory_store:
        raise HTTPException(503, "Security service not initialized")
    global g_security_service
    if (
        not g_security_service
        or getattr(g_security_service, "policy", None) is not g_security_policy
        or getattr(g_security_service, "store", None) is not g_memory_store
    ):
        g_security_service = SecurityService(g_security_policy, g_secret_manager, g_memory_store)
    return g_security_service


def get_maintenance_service() -> MaintenanceService:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    global g_maintenance_service
    if (
        not g_maintenance_service
        or getattr(g_maintenance_service, "store", None) is not g_memory_store
        or Path(getattr(g_maintenance_service, "db_path", "")) != MEMORY_DB
    ):
        g_maintenance_service = MaintenanceService(store=g_memory_store, db_path=MEMORY_DB, base_dir=BASE_DIR, config=config)
    return g_maintenance_service


def list_memory_items(
    memory_type: str = "",
    include_disabled: bool = False,
    limit: int = 200,
    actor_id: str = "system",
    roles: list[str] | None = None,
    workspace_id: str = "default",
) -> list[dict[str, Any]]:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    return g_memory_store.list_memories(
        memory_type,
        include_disabled,
        limit,
        actor_id=actor_id,
        roles=roles or [],
        workspace_id=workspace_id,
    )


def set_memory_item_enabled(memory_id: int, enabled: bool) -> dict[str, Any]:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    item = g_memory_store.set_memory_enabled(memory_id, enabled)
    if not item:
        raise HTTPException(404, "Memory item not found")
    if g_vector_store:
            g_vector_store.refresh()
    return item


def create_runtime_task(session_id: str, title: str, source: str = "chat", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return get_task_service().create(session_id, title, source=source, metadata=metadata)


def enqueue_runtime_task(session_id: str, title: str, source: str = "worker_job", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return get_task_service().enqueue(session_id, title, source=source, metadata=metadata)


def list_runtime_tasks(session_id: str = "", status: str = "", limit: int = 50) -> list[dict[str, Any]]:
    return get_task_service().list(session_id=session_id, status=status, limit=limit)


def list_runtime_task_queue(statuses: list[str] | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return get_task_service().queue(statuses=statuses, limit=limit)


def claim_runtime_task(worker_id: str = "worker", statuses: list[str] | None = None) -> dict[str, Any]:
    return get_task_service().claim(worker_id=worker_id, statuses=statuses)


def get_runtime_task(task_id: int) -> dict[str, Any]:
    detail = get_task_service().detail(task_id)
    if not detail:
        raise HTTPException(404, "Task not found")
    return detail


def finish_runtime_task(task_id: int | None, status: str, error: str = "", result_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not task_id or not g_memory_store:
        return {}
    return get_task_service().finish(task_id, status, error=error, result_payload=result_payload)


def cancel_runtime_task(task_id: int, reason: str = "", actor_id: str = "user") -> dict[str, Any]:
    item = get_task_service().cancel(task_id, reason=reason, actor_id=actor_id)
    if not item:
        raise HTTPException(404, "Task not found")
    return item


def retry_runtime_task(task_id: int, reason: str = "", actor_id: str = "user") -> dict[str, Any]:
    item = get_task_service().retry(task_id, reason=reason, actor_id=actor_id)
    if not item:
        raise HTTPException(404, "Task not found")
    return item


def worker_action_handlers() -> dict[str, Any]:
    return {
        "generate_report": worker_generate_report,
        "batch_ingest_documents": worker_batch_ingest_documents,
        "process_ocr_queue": worker_process_ocr_queue,
        "self_evolution_benchmark": worker_self_evolution_benchmark,
    }


def _worker_require_not_cancelled(task_id: int) -> None:
    if get_task_service().is_cancelled(task_id):
        raise asyncio.CancelledError()


def worker_generate_report(task: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if not g_workspace_services:
        raise RuntimeError("Workspace services not initialized")
    if not g_memory_store:
        raise RuntimeError("MemoryOS not initialized")
    task_id = int(task["id"])
    document_id = int(metadata.get("library_document_id") or metadata.get("document_id") or 0)
    if not document_id:
        raise ValueError("library_document_id is required")
    library_document = g_memory_store.get_document(document_id)
    if not library_document:
        raise ValueError("Document not found")
    if library_document.get("status") != "ready":
        raise ValueError("Document is not ready for report generation")
    _worker_require_not_cancelled(task_id)
    result = g_workspace_services.generate_research_learning_analysis(
        document_id=metadata.get("research_document_id"),
        file_path=library_document.get("file_path", ""),
        title=metadata.get("title") or library_document.get("title", ""),
        output_dir=metadata.get("output_dir") or "output/reports",
        formats=metadata.get("formats") or ["markdown", "pdf"],
        depth=metadata.get("depth", 5),
        question_count=metadata.get("question_count", 40),
        report_style=metadata.get("report_style", "journal"),
    )
    result["library_document"] = library_document
    return {"action": "generate_report", **result}


def worker_batch_ingest_documents(task: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if not g_memory_store:
        raise RuntimeError("MemoryOS not initialized")
    from memoryos.document_ingestion import ingest_file

    task_id = int(task["id"])
    raw_files = metadata.get("files") or metadata.get("paths") or []
    if isinstance(raw_files, str):
        raw_files = [item.strip() for item in re.split(r"[\n,;]+", raw_files) if item.strip()]
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("files must be a non-empty list")
    category = str(metadata.get("category") or "domain")
    limit = max(1, min(int(metadata.get("limit") or 24), 100))
    documents, errors = [], []
    for raw_path in raw_files[:limit]:
        _worker_require_not_cancelled(task_id)
        try:
            source = g_security_policy.resolve_path(str(raw_path)) if g_security_policy else Path(str(raw_path)).expanduser().resolve()
            if not source.is_file():
                raise ValueError("file not found")
            documents.append(ingest_file(g_memory_store, UPLOAD_DIR, source, title=source.stem, category=category))
        except Exception as exc:
            errors.append({"file": str(raw_path), "error": str(exc)})
    if g_vector_store:
        g_vector_store.refresh()
    return {
        "action": "batch_ingest_documents",
        "category": category,
        "processed": len(documents),
        "failed": len(errors),
        "documents": documents,
        "errors": errors,
    }


def worker_process_ocr_queue(task: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    service = get_knowledge_service()
    task_id = int(task["id"])
    category = str(metadata.get("category") or "")
    limit = max(1, min(int(metadata.get("limit") or 12), 50))
    pending = service.list_ocr_queue(category)[:limit]
    results, errors = [], []
    for document in pending:
        _worker_require_not_cancelled(task_id)
        try:
            results.append(service.run_ocr(int(document["id"]), force=bool(metadata.get("force", True))))
        except Exception as exc:
            errors.append({"document_id": document.get("id"), "error": str(exc)})
    return {
        "action": "process_ocr_queue",
        "category": category or "all",
        "processed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


def worker_self_evolution_benchmark(task: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    if not g_memory_store:
        raise RuntimeError("MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager

    task_id = int(task["id"])
    run_id = int(metadata.get("run_id") or 0)
    if not run_id:
        raise ValueError("run_id is required")
    _worker_require_not_cancelled(task_id)
    manager = SelfEvolutionManager(g_memory_store)
    before = g_memory_store.get_self_evolution_run(run_id)
    if not before:
        raise ValueError("self-evolution run not found")
    if g_memory_store:
        g_memory_store.add_task_event(
            task_id,
            "self_evolution_benchmark_started",
            f"Running self-evolution benchmarks for run #{run_id}",
            data={"run_id": run_id, "target_type": before.get("target_type")},
        )
    after = manager.run_automatic_benchmarks(run_id)
    after = manager.attach_runtime_quality_snapshot(run_id, created_by="worker")
    _worker_require_not_cancelled(task_id)
    if g_memory_store:
        g_memory_store.add_task_event(
            task_id,
            "self_evolution_benchmark_finished",
            f"Self-evolution run #{run_id} evaluated",
            data={
                "run_id": run_id,
                "status": after.get("status"),
                "release_stage": after.get("release_stage"),
                "gate_passed": bool((after.get("gate_result") or {}).get("passed")),
            },
        )
    return {
        "action": "self_evolution_benchmark",
        "run_id": run_id,
        "status": after.get("status"),
        "release_stage": after.get("release_stage"),
        "publish_decision": after.get("publish_decision"),
        "gate_passed": bool((after.get("gate_result") or {}).get("passed")),
        "run": after,
    }


async def run_background_worker_once(worker_id: str = "background-worker", max_attempts: int = 3) -> dict[str, Any]:
    global g_background_worker_status
    result = await get_task_service().run_worker_once(
        worker_id=worker_id,
        max_attempts=max_attempts,
    )
    g_background_worker_status["worker_id"] = worker_id
    g_background_worker_status["last_result"] = result
    g_background_worker_status["last_error"] = "" if result.get("ok", True) else str(result.get("error", ""))
    if result.get("claimed"):
        g_background_worker_status["processed"] = int(g_background_worker_status.get("processed") or 0) + 1
    return result


async def background_worker_loop(worker_id: str = "background-worker", interval_s: float = 0.5, max_attempts: int = 3) -> None:
    global g_background_worker_status
    g_background_worker_status.update({"running": True, "worker_id": worker_id, "last_error": ""})
    try:
        get_task_service().recover(actor_id=worker_id, create_retries=True)
        while True:
            result = await run_background_worker_once(worker_id=worker_id, max_attempts=max_attempts)
            if not result.get("claimed"):
                await asyncio.sleep(max(0.1, float(interval_s or 0.5)))
    except asyncio.CancelledError:
        g_background_worker_status["last_error"] = "stopped"
        raise
    except Exception as exc:
        g_background_worker_status["last_error"] = str(exc)
        if logger:
            logger.warning("Background worker stopped after error: %s", exc)
    finally:
        g_background_worker_status["running"] = False


async def store_assistant_response(session_id: str, resp: JSONResponse):
    if not g_memory_store:
        return
    text = extract_assistant_text(resp)
    if text:
        g_memory_store.add_message(session_id, "assistant", text[:4000])

# ---- UPSTREAM MODEL ----
async def proxy_upstream(req_data: dict, stream: bool, tool_context: str = "") -> JSONResponse:
    messages = req_data.get("messages", [])
    result = await call_model_with_fallback(
        "upstream",
        messages,
        {
            "temperature": req_data.get("temperature", 0.7),
            "model": req_data.get("model") or config.get("upstream", {}).get("model"),
        }
    )
    if not result["ok"]:
        body = build_openai_response(
            f"模型调用失败：{result['error']}",
            model=result.get("model"),
            extra={"model_result": result},
        )
        return sse_from_text(body["choices"][0]["message"]["content"], extra=body.get("clawos")) if stream else JSONResponse(body)
    body = build_openai_response(result["content"], model=result["model"], extra={"model_result": result})
    body["usage"] = result.get("usage", {})
    if stream:
        return sse_from_text(result["content"], extra=body.get("clawos"))
    return JSONResponse(body)

# ---- LIFESPAN ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, tools_def, http_client, mtclaw_http_client, logger, g_routing_provider, g_upstream_provider
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("clawos")
    config = load_config(CONFIG_PATH)
    config.setdefault("max_tool_rounds", 6)
    func_path = Path(config.get("functions_file", BASE_DIR / "functions.jsonl"))
    tools_def = load_tools(func_path)
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    mtclaw_http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(120.0),
        trust_env=False,
    )
    g_routing_provider = create_model_provider(config.get("routing", {}))
    g_upstream_provider = create_model_provider(config.get("upstream", {}))
    global g_mtclaw_adapter
    from mtclaw import MTClawAdapter
    g_mtclaw_adapter = MTClawAdapter(config.get("mtclaw", {}), http_client=mtclaw_http_client)
    NOTES_DIR.mkdir(exist_ok=True)
    # Init MemoryOS
    global g_memory_store, g_context_builder, g_vector_store, g_policy_optimizer
    global g_security_policy, g_secret_manager
    global g_workspace_services, g_skill_evolution, g_scenario_benchmark, g_knowledge_service
    global g_security_service, g_task_service, g_maintenance_service
    from memoryos.memory_store import MemoryStore
    from memoryos.context_builder import ContextBuilder
    from memoryos.services.vector_store import MemoryVectorStore
    MEMORY_DB.parent.mkdir(parents=True, exist_ok=True)
    g_memory_store = MemoryStore(str(MEMORY_DB))

    # Init VectorStore before ContextBuilder so retrieval uses the same live index.
    vector_cfg = dict(config.get("vector_store") or {})
    chroma_dir = str(vector_cfg.get("chroma_dir") or "")
    if chroma_dir and not Path(chroma_dir).expanduser().is_absolute():
        chroma_dir = str((BASE_DIR / chroma_dir).resolve())
    embedding_model_path = str(vector_cfg.get("embedding_model_path") or "")
    if embedding_model_path and not Path(embedding_model_path).expanduser().is_absolute():
        embedding_model_path = str((BASE_DIR / embedding_model_path).resolve())
    g_vector_store = MemoryVectorStore(
        str(MEMORY_DB),
        provider=str(vector_cfg.get("provider") or ""),
        persist_dir=chroma_dir,
        embedding_provider=str(vector_cfg.get("embedding_provider") or ""),
        embedding_model_path=embedding_model_path,
        embedding_dim=int(vector_cfg.get("embedding_dim") or 0),
    )
    g_vector_store.refresh()  # Load existing data
    reranker = None
    reranker_provider = str(vector_cfg.get("reranker_provider") or "").strip().lower()
    if reranker_provider and reranker_provider not in {"none", "off", "false", "0"}:
        from memoryos.services.retrieval import CrossEncoderReranker
        reranker_model_path = str(vector_cfg.get("reranker_model_path") or "")
        if reranker_model_path and not Path(reranker_model_path).expanduser().is_absolute():
            reranker_model_path = str((BASE_DIR / reranker_model_path).resolve())
        reranker = CrossEncoderReranker(
            model_path=reranker_model_path,
            provider=reranker_provider,
        )
    g_context_builder = ContextBuilder(g_memory_store, g_vector_store, reranker=reranker)
    from policy_optimizer import PolicyOptimizer
    g_policy_optimizer = PolicyOptimizer(g_memory_store)
    from security import SecretManager, SecurityGrantStore, ToolSecurityPolicy
    g_security_policy = ToolSecurityPolicy(grant_store=SecurityGrantStore(BASE_DIR / "security_policy.json"))
    g_secret_manager = SecretManager(g_memory_store)
    g_security_service = SecurityService(g_security_policy, g_secret_manager, g_memory_store)
    g_task_service = TaskService(g_memory_store, action_handlers=worker_action_handlers())
    g_maintenance_service = MaintenanceService(store=g_memory_store, db_path=MEMORY_DB, base_dir=BASE_DIR, config=config)
    g_maintenance_service.apply_migrations()
    g_knowledge_service = KnowledgeService(g_memory_store, UPLOAD_DIR, lambda: g_vector_store.refresh() if g_vector_store else None)
    from workspace_services import WorkspaceServices
    g_workspace_services = WorkspaceServices(g_memory_store, g_security_policy)
    from skills.skill_evolution import SkillEvolutionManager
    g_skill_evolution = SkillEvolutionManager(g_memory_store)
    from scenario_benchmarks import FrozenScenarioBenchmark
    g_scenario_benchmark = FrozenScenarioBenchmark(g_memory_store)
    recovered = g_memory_store.recover_interrupted_tasks(actor_id="lifespan_startup")
    if recovered.get("count"):
        logger.info("Recovered interrupted tasks | count=%s ids=%s", recovered["count"], recovered["recovered"])
    vector_stats = g_vector_store.stats()
    logger.info(
        "VectorStore initialized | provider=%s requested=%s docs=%s fallback=%s",
        vector_stats.get("provider"),
        vector_stats.get("requested_provider"),
        vector_stats.get("vector_count", 0),
        vector_stats.get("fallback_reason") or "",
    )
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
    global g_background_worker_task
    if g_background_worker_task and not g_background_worker_task.done():
        g_background_worker_task.cancel()
        try:
            await g_background_worker_task
        except asyncio.CancelledError:
            pass
    g_background_worker_task = None
    if mtclaw_http_client:
        await mtclaw_http_client.aclose()
    if http_client:
        await http_client.aclose()
    logger.info("ClawOS stopped")

app = FastAPI(title="ClawOS Agent", version="1.0.0", lifespan=lifespan)

NO_CACHE_STATIC_PATHS = {
    "/",
    "/product",
    "/console",
    "/assets/site.css",
    "/assets/site.js",
    "/assets/console.js",
}


@app.middleware("http")
async def no_cache_static_shell(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in NO_CACHE_STATIC_PATHS or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

# ---- ROUTES ----
@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/product")
async def product_page():
    return FileResponse(STATIC_DIR / "product.html")

@app.get("/console")
async def console_page():
    return FileResponse(STATIC_DIR / "console.html")

@app.get("/health")
async def health():
    provider_state = model_provider_status(config) if config else {"provider": "", "model": "", "configured": False}
    mtclaw_state = (
        await g_mtclaw_adapter.health()
        if g_mtclaw_adapter
        else {"enabled": False, "reachable": False, "status": "not_initialized"}
    )
    database_state = {"configured": False, "reachable": False, "status": "not_initialized"}
    if g_memory_store:
        try:
            with g_memory_store._conn() as conn:
                conn.execute("SELECT 1").fetchone()
            database_state = {
                "configured": True,
                "reachable": True,
                "status": "ok",
                "engine": "sqlite",
            }
        except Exception as exc:
            database_state = {
                "configured": True,
                "reachable": False,
                "status": "error",
                "error": type(exc).__name__,
                "engine": "sqlite",
            }
    return {
        "status": "ok",
        "version": "1.0.0",
        "tools": len(tools_def),
        "memory": bool(g_memory_store),
        "database": database_state,
        "reflection": bool(g_reflection_engine),
        "policy_optimizer": bool(g_policy_optimizer),
        "security_policy": bool(g_security_policy),
        "secret_manager": bool(g_secret_manager),
        "workspace_services": bool(g_workspace_services),
        "skill_evolution": bool(g_skill_evolution),
        "model_provider": provider_state,
        "model_mode": model_mode_label(provider_state.get("provider", ""), bool(provider_state.get("configured"))),
        "routing_model": config.get("routing", {}).get("model", ""),
        "upstream_model": config.get("upstream", {}).get("model", ""),
        "mtclaw": mtclaw_state,
    }

@app.get("/api/config/model")
async def get_model_config():
    return model_config_payload(config)


@app.get("/api/model/health")
async def api_model_health(probe: bool = False):
    sections = {}
    for section in ("routing", "upstream"):
        attempts = []
        for provider in _provider_candidates(section):
            if not provider:
                continue
            configured = provider.is_configured() if hasattr(provider, "is_configured") else True
            item = {
                "provider": getattr(provider, "name", ""),
                "model": getattr(provider, "model", ""),
                "configured": bool(configured),
                "reachable": None,
                "error": "",
                "duration_ms": 0,
            }
            if probe and configured:
                result = await provider.complete(
                    [{"role": "user", "content": "health check: reply ok"}],
                    {"temperature": 0.0},
                    http_client=http_client,
                )
                item.update({
                    "reachable": bool(result.get("ok")),
                    "error": result.get("error", ""),
                    "duration_ms": result.get("duration_ms", 0),
                })
            attempts.append(item)
        sections[section] = {
            "primary": attempts[0] if attempts else {},
            "fallbacks": attempts[1:],
            "configured": any(a.get("configured") for a in attempts),
            "reachable": any(a.get("reachable") for a in attempts) if probe else None,
            "fallback_strategy": "ordered_provider_fallback",
        }
    return JSONResponse(sections)

@app.post("/api/config/model")
async def update_model_config(request: Request):
    try:
        payload = await request.json()
        updated = apply_model_config_updates(payload if isinstance(payload, dict) else {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Model config update failed: {e}")
    return updated

@app.get("/v1/models")
async def list_models():
    provider_state = model_provider_status(config) if config else {"model": "clawos-agent", "provider": "clawos"}
    return JSONResponse({"object":"list","data":[{"id":provider_state["model"],"object":"model","owned_by":provider_state["provider"]}]})

def _build_attachment_context(raw_attachments: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(raw_attachments, list):
        return "", []
    normalized: list[dict[str, Any]] = []
    blocks: list[str] = []
    total_chars = 0
    for idx, item in enumerate(raw_attachments[:8], start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"attachment-{idx}")[:180]
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        remaining = max(0, 60000 - total_chars)
        if remaining <= 0:
            break
        clipped = content[: min(30000, remaining)]
        total_chars += len(clipped)
        meta = {
            "name": name,
            "type": str(item.get("type") or "")[:80],
            "size": int(item.get("size") or 0) if str(item.get("size") or "").isdigit() else item.get("size", 0),
            "chars": len(clipped),
        }
        normalized.append(meta)
        blocks.append(
            f"[Attachment {idx}: {name}]\n"
            f"type={meta['type'] or 'unknown'} size={meta['size']}\n"
            f"{clipped}"
        )
    if not blocks:
        return "", normalized
    context = (
        "\n\n[ClawOS hidden attachment context]\n"
        "The user attached the following local files. Treat them as task context. "
        "Do not claim the user pasted this text, and only quote from it when useful.\n\n"
        + "\n\n---\n\n".join(blocks)
    )
    return context, normalized


def _build_uploaded_document_context(raw_attachments: Any, query: str) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(raw_attachments, list) or not g_memory_store:
        return _build_attachment_context(raw_attachments)
    normalized: list[dict[str, Any]] = []
    blocks: list[str] = []
    fallback_attachments: list[dict[str, Any]] = []
    for item in raw_attachments[:8]:
        if not isinstance(item, dict):
            continue
        doc_id = item.get("document_id") or item.get("id")
        if not doc_id:
            fallback_attachments.append(item)
            continue
        document = g_memory_store.get_document(int(doc_id))
        if not document:
            continue
        chunks = g_memory_store.search_document_chunks(query or document.get("title", ""), document.get("category", ""), 8)
        chunks = [c for c in chunks if int(c.get("document_id") or 0) == int(doc_id)]
        if not chunks:
            chunks = g_memory_store.get_document_chunks(int(doc_id), 8)
        meta = {
            "document_id": int(doc_id),
            "name": document.get("filename") or document.get("title"),
            "title": document.get("title"),
            "category": document.get("category"),
            "chunk_count": len(chunks),
        }
        normalized.append(meta)
        excerpt_parts = []
        for chunk in chunks[:6]:
            citation = chunk.get("citation") or f"doc:{doc_id}#chunk={chunk.get('chunk_index')}"
            excerpt_parts.append(f"[{citation}]\n{chunk.get('content', '')[:1800]}")
        excerpt = "\n\n".join(excerpt_parts)
        blocks.append(f"[Document: {meta['title']}]\n{excerpt}")
    fallback_context, fallback_meta = _build_attachment_context(fallback_attachments)
    normalized.extend(fallback_meta)
    if not blocks:
        return fallback_context, normalized
    context = (
        "\n\n[ClawOS hidden uploaded document context]\n"
        "The user attached indexed documents. Use these retrieved chunks as RAG context. "
        "When referring to evidence, cite doc:N#chunk=M where available.\n\n"
        + "\n\n---\n\n".join(blocks)
    )
    return context + fallback_context, normalized

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.body()
        req_data = json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")

    messages = req_data.get("messages", [])
    request_headers = getattr(request, "headers", {}) or {}
    if not messages:
        raise HTTPException(400, "messages array required")

    user_text = ""
    session_id = req_data.get("session_id", "default")
    confirmed_tools = _confirmed_tools_from_request(req_data)
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            user_text = str(m["content"])
            break

    attachment_context, attachment_meta = _build_uploaded_document_context(req_data.get("clawos_attachments", []), user_text)
    effective_user_text = user_text + attachment_context
    stream = req_data.get("stream", False)

    if not user_text:
        resp = await proxy_upstream(req_data, stream)
        if isinstance(resp, JSONResponse):
            await store_assistant_response(session_id, resp)
        return resp

    runtime_task = None
    task_id = None
    if g_memory_store:
        runtime_task = create_runtime_task(
            session_id,
            user_text[:120] or "Chat completion",
            metadata={
                "stream": bool(stream),
                "user_text": user_text,
                "attachments": attachment_meta,
                "idempotency_key": str(
                    req_data.get("clawos_idempotency_key")
                    or request_headers.get("Idempotency-Key", "")
                    or ""
                ),
            },
        )
        task_id = runtime_task.get("id")
        stored_payload = runtime_task.get("metadata", {}).get("response_payload")
        if runtime_task.get("idempotent_replay") and stored_payload and not stream:
            return JSONResponse(stored_payload)

    # --- TOOL ROUTING ---
    if g_context_builder:
        g_context_builder.ingest_and_store(session_id, "user", user_text)
    elif g_memory_store:
        g_memory_store.add_message(session_id, "user", user_text)

    if g_mtclaw_adapter and g_mtclaw_adapter.enabled and not stream:
        mtclaw_messages = (
            g_context_builder.build_messages(session_id, effective_user_text)
            if g_context_builder
            else [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": effective_user_text}]
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
                "task_id": task_id,
                "attachments": attachment_meta,
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
            finish_runtime_task(task_id, "succeeded", result_payload=raw)
            return JSONResponse(raw)
        if not g_mtclaw_adapter.fallback_on_error:
            finish_runtime_task(task_id, "failed", mtclaw_result["error"])
            raise HTTPException(503, f"MTClaw unavailable: {mtclaw_result['error']}")

    if task_id and g_memory_store and g_memory_store.is_task_cancelled(task_id):
        text = "任务已收到取消请求，未继续执行。"
        body = build_openai_response(text, extra={"task_id": task_id, "canceled": True})
        if g_memory_store:
            g_memory_store.add_message(session_id, "assistant", text[:4000])
        finish_runtime_task(task_id, "canceled", "Canceled before tool loop", result_payload=body)
        return JSONResponse(body)

    tool_result = await run_tool_loop(effective_user_text, session_id, confirmed_tools, task_id=task_id)
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
            "attachments": attachment_meta,
            "task_id": task_id,
        }
        if g_memory_store:
            g_memory_store.add_message(session_id, "assistant", text[:4000])
        finish_runtime_task(task_id, "waiting_confirmation")
        if stream:
            return sse_from_text(text, task_id=task_id, extra=extra)
        return JSONResponse(build_openai_response(text, extra=extra))

    # Auto-trigger reflection after tool execution
    reflection_result = None
    if tool_result["used_tools"] and g_reflection_engine:
        try:
            trigger = g_reflection_engine.should_reflect(
                tool_result["tool_calls"], effective_user_text)
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
            {"role": "user", "content": effective_user_text},
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
            "task_id": task_id,
        }
        if not has_api_key("upstream"):
            text = "已完成本地工具执行，结果如下：\n" + tc_lines.strip()
            body = build_openai_response(text, extra=extra)
            if g_memory_store:
                g_memory_store.add_message(session_id, "assistant", text[:4000])
            finish_runtime_task(task_id, "succeeded", result_payload=body)
            if stream:
                return sse_from_text(text, task_id=task_id, extra=extra)
            return JSONResponse(body)
        resp = await proxy_upstream({**req_data, "messages": upstream_msgs}, False if stream else stream)
        if isinstance(resp, JSONResponse):
            text = extract_assistant_text(resp)
            body = json.loads(resp.body)
            body["clawos"] = extra
            if g_memory_store and text:
                g_memory_store.add_message(session_id, "assistant", text[:4000])
            finish_runtime_task(task_id, "succeeded", result_payload=body)
            if stream:
                return sse_from_text(text, task_id=task_id, extra=extra)
            return JSONResponse(body)
        return resp

    final_text = tool_result.get("final_text", "")
    if stream:
        if g_memory_store and final_text:
            g_memory_store.add_message(session_id, "assistant", final_text[:4000])
        finish_runtime_task(task_id, "succeeded")
        return sse_from_text(final_text, task_id=task_id, extra={
            "used_tools": False,
            "tool_calls": [],
            "routing_rounds": tool_result.get("routing_rounds", 0),
            "attachments": attachment_meta,
            "task_id": task_id,
        })

    resp_payload = build_openai_response(final_text, extra={
        "used_tools": False,
        "tool_calls": [],
        "routing_rounds": tool_result.get("routing_rounds", 0),
        "attachments": attachment_meta,
        "task_id": task_id,
    })
    if g_memory_store and final_text:
        g_memory_store.add_message(session_id, "assistant", final_text[:4000])
    finish_runtime_task(task_id, "succeeded", result_payload=resp_payload)
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


@app.get("/api/reflection/cards/{card_id}")
async def reflection_card_detail(card_id: str):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    card = g_memory_store.get_reflection_card(card_id)
    if not card:
        raise HTTPException(404, "Reflection card not found")
    return JSONResponse({"card": card})


@app.post("/api/reflection/cards/{card_id}/feedback")
async def reflection_card_feedback(card_id: str, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    data = await request.json()
    card = g_memory_store.update_reflection_feedback(
        card_id,
        {
            "rating": data.get("rating"),
            "satisfied": data.get("satisfied"),
            "comment": str(data.get("comment", "") or ""),
            "correction": str(data.get("correction", "") or ""),
            "reason": str(data.get("reason", "") or ""),
        },
        actor_id=data.get("actor_id", "system"),
    )
    if not card:
        raise HTTPException(404, "Reflection card not found")
    return JSONResponse({"card": card, "updated": True})


@app.get("/api/reflection/improvements")
async def reflection_improvements(status: str = "", limit: int = 100):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    rows = g_memory_store.list_reflection_improvements(status, limit)
    return JSONResponse({"improvements": rows, "count": len(rows)})


@app.post("/api/reflection/improvements/{improvement_id}/transition")
async def reflection_improvement_transition(improvement_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.improvement_manager import ImprovementManager
    data = await request.json()
    try:
        item = ImprovementManager(g_memory_store).transition(
            improvement_id,
            str(data.get("to_status", "") or ""),
            actor_id=data.get("actor_id", "system"),
            reason=data.get("reason", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"improvement": item})


@app.post("/api/reflection/improvements/{improvement_id}/validate")
async def reflection_improvement_validate(improvement_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.improvement_manager import ImprovementManager
    data = await request.json()
    try:
        item = ImprovementManager(g_memory_store).validate(
            improvement_id,
            baseline=data.get("baseline", {}),
            candidate=data.get("candidate", {}),
            thresholds=data.get("thresholds", {}),
            actor_id=data.get("actor_id", "system"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"improvement": item})


@app.post("/api/reflection/improvements/{improvement_id}/publish")
async def reflection_improvement_publish(improvement_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.improvement_manager import ImprovementManager
    data = await request.json()
    try:
        item = ImprovementManager(g_memory_store).publish(
            improvement_id,
            actor_id=data.get("actor_id", "system"),
            reason=data.get("reason", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"improvement": item})


@app.post("/api/reflection/improvements/{improvement_id}/rollback")
async def reflection_improvement_rollback(improvement_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.improvement_manager import ImprovementManager
    data = await request.json()
    try:
        item = ImprovementManager(g_memory_store).rollback(
            improvement_id,
            actor_id=data.get("actor_id", "system"),
            reason=data.get("reason", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"improvement": item})


@app.get("/api/self-evolution/runs")
async def api_self_evolution_runs(status: str = "", limit: int = 100):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    rows = g_memory_store.list_self_evolution_runs(status=status, limit=limit)
    return JSONResponse({"runs": rows, "count": len(rows)})


@app.get("/api/self-evolution/board")
async def api_self_evolution_board(limit: int = 50):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    runs = g_memory_store.list_self_evolution_runs(limit=limit)
    snapshot = g_memory_store.runtime_quality_snapshot()
    stage_counts: dict[str, int] = {}
    for run in runs:
        stage = str(run.get("release_stage") or run.get("status") or "candidate")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    blocked = [
        run for run in runs
        if run.get("status") == "rejected"
        or not (run.get("gate_result") or {}).get("passed", True)
    ]
    active = [run for run in runs if run.get("release_stage") == "active"]
    score = 100
    if not runs:
        score -= 25
    if blocked:
        score -= min(30, len(blocked) * 5)
    if snapshot.get("cancel_rate", 0) > 0.15 or snapshot.get("long_task_failure_rate", 0) > 0.10:
        score -= 20
    score = max(0, min(100, score))
    return JSONResponse({
        "runs": runs,
        "stage_counts": stage_counts,
        "quality_snapshot": snapshot,
        "active_count": len(active),
        "blocked_count": len(blocked),
        "enterprise_score": score,
        "enterprise_ready": score >= 85 and bool(runs),
    })


@app.post("/api/self-evolution/runs")
async def api_self_evolution_create_run(request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        run = SelfEvolutionManager(g_memory_store).create_run(
            target_type=data.get("target_type", ""),
            target_key=data.get("target_key", ""),
            baseline_payload=data.get("baseline_payload", {}),
            candidate_payload=data.get("candidate_payload", {}),
            benchmarks=data.get("benchmarks", {}),
            title=data.get("title", ""),
            conclusion=data.get("conclusion", ""),
            created_by=data.get("actor_id", "system"),
        )
        queued = bool(data.get("auto_queue", True))
        task = {}
        if queued:
            task = enqueue_runtime_task(
                "self-evolution",
                f"Self-evolution benchmark run {run['id']}",
                source="self_evolution",
                metadata={
                    "worker_action": "self_evolution_benchmark",
                    "run_id": run["id"],
                    "idempotency_key": data.get("idempotency_key", ""),
                },
            )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"run": run, "queued": queued, "task": task})


@app.post("/api/self-evolution/candidates")
async def api_self_evolution_candidate(request: Request):
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        candidate = SelfEvolutionManager.generate_candidate(
            data.get("target_type", ""),
            data.get("baseline_payload", {}),
            strategy=data.get("strategy", "balanced"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"candidate_payload": candidate})


@app.post("/api/self-evolution/runs/{run_id}/evaluate")
async def api_self_evolution_evaluate(run_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        run = SelfEvolutionManager(g_memory_store).evaluate(
            run_id,
            benchmarks=data.get("benchmarks"),
            conclusion=data.get("conclusion", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"run": run})


@app.post("/api/self-evolution/runs/{run_id}/publish")
async def api_self_evolution_publish(run_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        run = SelfEvolutionManager(g_memory_store).start_shadow(run_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"run": run})


@app.post("/api/self-evolution/runs/{run_id}/quality-signal")
async def api_self_evolution_quality_signal(run_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        run = SelfEvolutionManager(g_memory_store).record_quality_signal(
            run_id,
            data.get("signal_type", "quality"),
            data.get("value", 0),
            metadata=data.get("metadata", {}),
            created_by=data.get("actor_id", "system"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"run": run})


@app.post("/api/self-evolution/runs/{run_id}/quality-snapshot")
async def api_self_evolution_quality_snapshot(run_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        run = SelfEvolutionManager(g_memory_store).attach_runtime_quality_snapshot(
            run_id,
            created_by=data.get("actor_id", "system"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"run": run})


@app.post("/api/self-evolution/runs/{run_id}/canary")
async def api_self_evolution_canary(run_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        run = SelfEvolutionManager(g_memory_store).promote_canary(
            run_id,
            traffic_percent=data.get("traffic_percent", 10),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"run": run})


@app.post("/api/self-evolution/runs/{run_id}/activate")
async def api_self_evolution_activate(run_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from reflection.self_evolution import SelfEvolutionManager
    data = await request.json()
    try:
        run = SelfEvolutionManager(g_memory_store).activate(
            run_id,
            actor_id=data.get("actor_id", "system"),
            reason=data.get("reason", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"run": run})


@app.get("/api/reflection/stats")
async def reflection_stats():
    if not g_reflection_engine:
        raise HTTPException(503, "Reflection Engine not initialized")
    from reflection.learning_loop import LearningLoop
    loop = LearningLoop(g_reflection_engine, g_memory_store)
    return JSONResponse(loop.get_cycle_stats())


@app.post("/api/policy/groups")
async def api_policy_group_register(request: Request):
    if not g_policy_optimizer:
        raise HTTPException(503, "Policy Optimizer not initialized")
    data = await request.json()
    name = str(data.get("name", "") or "").strip()
    arms = data.get("arms", [])
    if not name or not isinstance(arms, list) or not arms:
        raise HTTPException(400, "name and non-empty arms are required")
    try:
        result = g_policy_optimizer.register_group(
            name,
            arms,
            exploration_rate=data.get("exploration_rate", 0.1),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)


@app.post("/api/policy/groups/{group_name}/select")
async def api_policy_select(group_name: str, request: Request):
    if not g_policy_optimizer:
        raise HTTPException(503, "Policy Optimizer not initialized")
    data = await request.json()
    try:
        selection = g_policy_optimizer.select(
            group_name,
            context=data.get("context", {}),
            task_id=data.get("task_id"),
            session_id=data.get("session_id", ""),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return JSONResponse({"selection": selection})


@app.post("/api/policy/selections/{selection_id}/reward")
async def api_policy_reward(selection_id: int, request: Request):
    if not g_policy_optimizer:
        raise HTTPException(503, "Policy Optimizer not initialized")
    data = await request.json()
    try:
        result = g_policy_optimizer.reward(
            selection_id,
            success=data.get("success", 0),
            satisfaction=data.get("satisfaction", 0.5),
            latency_ms=data.get("latency_ms", 0),
            resource_cost=data.get("resource_cost", 0),
            latency_budget_ms=data.get("latency_budget_ms", 1000),
            evidence=data.get("evidence", {}),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)


@app.get("/api/policy/groups/{group_name}/stats")
async def api_policy_stats(group_name: str):
    if not g_policy_optimizer:
        raise HTTPException(503, "Policy Optimizer not initialized")
    stats = g_policy_optimizer.stats(group_name)
    if not stats:
        raise HTTPException(404, "Policy group not found")
    return JSONResponse(stats)


@app.post("/api/policy/groups/{group_name}/promote")
async def api_policy_promote(group_name: str, request: Request):
    data = await request.json()
    try:
        promotion = g_policy_optimizer.promote(
            group_name,
            data.get("target_type", "agent_policy"),
            data.get("target_key", group_name),
            min_pulls=data.get("min_pulls", 3),
            actor_id=data.get("actor_id", "system"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"promotion": promotion})


@app.post("/api/policy/promotions/{promotion_id}/rollback")
async def api_policy_promotion_rollback(promotion_id: int, request: Request):
    data = await request.json()
    try:
        promotion = g_policy_optimizer.rollback(
            promotion_id, actor_id=data.get("actor_id", "system")
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"promotion": promotion})


@app.get("/api/security/audit")
async def api_security_audit(action: str = "", decision: str = "", limit: int = 100):
    try:
        rows = get_security_service().audit(action, decision, limit)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return JSONResponse({"events": rows, "count": len(rows)})


@app.post("/api/security/secrets")
async def api_secret_register(request: Request):
    data = await request.json()
    try:
        item = get_security_service().register_secret(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return JSONResponse({"secret": item})


@app.get("/api/security/secrets")
async def api_secret_list():
    try:
        secrets = get_security_service().list_secrets()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return JSONResponse({"secrets": secrets})


@app.post("/api/security/policy/check")
async def api_security_policy_check(request: Request):
    data = await request.json()
    try:
        result = get_security_service().check_policy(str(data.get("tool", "") or ""), data.get("arguments", {}))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return JSONResponse(result)


@app.get("/api/security/policy/grants")
async def api_security_policy_grants(include_expired: bool = False):
    try:
        grants = get_security_service().list_grants(include_expired)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return JSONResponse({"grants": grants, "count": len(grants)})


@app.post("/api/security/policy/grants")
async def api_security_policy_grant_create(request: Request):
    data = await request.json()
    try:
        grant = get_security_service().create_grant(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return JSONResponse({"grant": grant})


@app.delete("/api/security/policy/grants/{grant_id}")
async def api_security_policy_grant_revoke(grant_id: str):
    try:
        revoked = get_security_service().revoke_grant(grant_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    return JSONResponse({"revoked": bool(revoked), "grant_id": grant_id})


@app.get("/api/system/config/check")
async def api_system_config_check():
    try:
        return JSONResponse(get_maintenance_service().config_check())
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.get("/api/system/migrations")
async def api_system_migrations():
    try:
        return JSONResponse(get_maintenance_service().list_migrations())
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/system/migrations/apply")
async def api_system_migrations_apply():
    try:
        return JSONResponse(get_maintenance_service().apply_migrations())
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/system/backup")
async def api_system_backup(request: Request):
    data = await request.json()
    try:
        result = get_maintenance_service().backup_database(
            output_dir=str(data.get("output_dir") or ""),
            label=str(data.get("label") or ""),
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)


@app.post("/api/system/restore")
async def api_system_restore(request: Request):
    data = await request.json()
    try:
        result = get_maintenance_service().restore_database(
            str(data.get("backup_path") or data.get("path") or ""),
            confirm=bool(data.get("confirm", False)),
            label=str(data.get("label") or "pre-restore"),
        )
        if g_vector_store:
            g_vector_store.refresh()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)


@app.get("/api/system/readiness")
async def api_system_readiness():
    checks = [
        {"id": "config_check", "label": "Configuration check API", "ok": bool(g_maintenance_service), "weight": 12},
        {"id": "migrations", "label": "SQLite migrations API", "ok": bool(g_maintenance_service), "weight": 10},
        {"id": "backup_restore", "label": "Backup and restore API", "ok": bool(g_maintenance_service), "weight": 14},
        {"id": "task_runtime", "label": "Task queue, cancel, retry, recover", "ok": bool(g_memory_store), "weight": 14},
        {"id": "worker_loop", "label": "Background worker control plane", "ok": bool(get_task_service()), "weight": 12},
        {"id": "real_worker_jobs", "label": "Report, OCR queue, batch document jobs", "ok": set(worker_action_handlers()) >= {"generate_report", "process_ocr_queue", "batch_ingest_documents"}, "weight": 16},
        {"id": "security_audit", "label": "Security policy and audit center", "ok": bool(g_security_policy and g_memory_store), "weight": 10},
        {"id": "knowledge_ops", "label": "Knowledge graph, Obsidian, OCR operations", "ok": bool(get_knowledge_service()), "weight": 12},
    ]
    total = sum(int(item["weight"]) for item in checks)
    passed = sum(int(item["weight"]) for item in checks if item["ok"])
    score = round(passed / total, 4) if total else 0
    return JSONResponse({
        "score": score,
        "percent": round(score * 100, 1),
        "standard": "single-user enterprise ops readiness",
        "enterprise_ready": score >= 0.9,
        "checks": checks,
        "remaining": [item for item in checks if not item["ok"]],
    })

@app.get("/api/workspace/capabilities")
async def api_workspace_capabilities():
    roots = [str(root) for root in (g_security_policy.allowed_roots if g_security_policy else [])]
    templates = g_workspace_services.list_templates() if g_workspace_services else []
    has = lambda package: importlib.util.find_spec(package) is not None
    grobid_url = os.environ.get("GROBID_BASE_URL", "").strip()
    return JSONResponse({
        "local_file_operations": {
            "allowed_roots": roots,
            "txt_read_write": True,
            "project_create": True,
            "template_create": True,
            "structured_file_generation": ["markdown", "pdf", "json", "txt", "xlsx", "pptx"],
            "requires_confirmation_for_writes": True,
        },
        "office_artifacts": {
            "xlsx": {
                "create": True,
                "edit_cells": True,
                "engine": "openpyxl" if has("openpyxl") else "stdlib-openxml",
                "requires_microsoft_office": False,
                "requires_extra_python_packages": not has("openpyxl"),
            },
            "pptx": {
                "create": True,
                "replace_text": True,
                "engine": "python-pptx" if has("pptx") else "stdlib-openxml",
                "requires_microsoft_office": False,
                "requires_extra_python_packages": not has("pptx"),
            },
        },
        "document_understanding": {
            "txt": True,
            "pdf_text": shutil.which("pdftotext") is not None or has("pypdf") or has("fitz"),
            "pdf_layout": {
                "pymupdf": has("fitz"),
                "pdfplumber": has("pdfplumber"),
                "grobid": bool(grobid_url),
                "grobid_base_url": grobid_url,
            },
            "pdf_ocr": "paddleocr" if has("paddleocr") else "worker_with_sidecar_or_local_tesseract",
            "paddleocr_available": has("paddleocr"),
            "typst_available": shutil.which("typst") is not None,
            "citation_validation": True,
            "paper_learning_analysis": ["markdown", "pdf"],
        },
        "meeting_audio": {
            "audio_file_registration": True,
            "sidecar_transcript_import": True,
            "speaker_diarization": "label_based",
            "local_whisper_available": shutil.which("whisper") is not None,
            "auto_transcription": shutil.which("whisper") is not None,
        },
        "connectors": {
            "calendar": "ics_draft",
            "email": "eml_draft",
            "auto_send": False,
        },
        "git": {
            "snapshot": True,
            "patch_preview": True,
            "approval_commit": True,
            "rollback": "git_revert",
        },
        "templates": {
            "count": len(templates),
            "names": [item["name"] for item in templates],
        },
    })


@app.post("/api/workspace/office/spreadsheets")
async def api_office_spreadsheet_create(request: Request):
    data = await request.json()
    try:
        artifact = g_workspace_services.create_spreadsheet(
            data.get("output_path", ""),
            sheets=data.get("sheets", []),
            title=data.get("title", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"artifact": artifact})


@app.post("/api/workspace/office/spreadsheets/edit")
async def api_office_spreadsheet_edit(request: Request):
    data = await request.json()
    try:
        artifact = g_workspace_services.edit_spreadsheet(
            data.get("file_path", ""),
            updates=data.get("updates", []),
            output_path=data.get("output_path", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"artifact": artifact})


@app.post("/api/workspace/office/presentations")
async def api_office_presentation_create(request: Request):
    data = await request.json()
    try:
        artifact = g_workspace_services.create_presentation(
            data.get("output_path", ""),
            title=data.get("title", ""),
            slides=data.get("slides", []),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"artifact": artifact})


@app.post("/api/workspace/office/presentations/edit")
async def api_office_presentation_edit(request: Request):
    data = await request.json()
    try:
        artifact = g_workspace_services.edit_presentation(
            data.get("file_path", ""),
            replacements=data.get("replacements", {}),
            output_path=data.get("output_path", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"artifact": artifact})


@app.post("/api/workspace/meetings")
async def api_meeting_create(request: Request):
    data = await request.json()
    meeting = g_workspace_services.create_meeting(
        data.get("title", "Untitled meeting"),
        data.get("meeting_date", ""),
        data.get("attendees", []),
        data.get("agenda", []),
    )
    return JSONResponse({"meeting": meeting})


@app.post("/api/workspace/meetings/{meeting_id}/transcript")
async def api_meeting_transcript(meeting_id: int, request: Request):
    data = await request.json()
    meeting = g_workspace_services.process_meeting_transcript(
        meeting_id, data.get("transcript", "")
    )
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"meeting": meeting})

@app.post("/api/workspace/meetings/audio")
async def api_meeting_audio_import(request: Request):
    data = await request.json()
    try:
        result = g_workspace_services.import_meeting_audio(
            data.get("audio_path", ""),
            transcript_path=data.get("transcript_path", ""),
            transcript=data.get("transcript", ""),
            title=data.get("title", ""),
            meeting_id=data.get("meeting_id"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse(result)

@app.post("/api/workspace/meetings/{meeting_id}/connector-drafts")
async def api_meeting_connector_drafts(meeting_id: int, request: Request):
    data = await request.json()
    try:
        result = g_workspace_services.draft_meeting_connectors(
            meeting_id,
            data.get("output_dir", ""),
            calendar=bool(data.get("calendar", True)),
            email=bool(data.get("email", True)),
            recipients=data.get("recipients", []),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)


@app.get("/api/workspace/meetings/{meeting_id}")
async def api_meeting_detail(meeting_id: int):
    meeting = g_workspace_services.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    return JSONResponse({"meeting": meeting})


@app.post("/api/workspace/research/import")
async def api_research_import(request: Request):
    data = await request.json()
    try:
        document = g_workspace_services.import_research_pdf(
            data.get("file_path", ""), data.get("title", "")
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"document": document})


@app.get("/api/workspace/research/search")
async def api_research_search(q: str, limit: int = 10):
    rows = g_workspace_services.search_research(q, limit)
    return JSONResponse({"results": rows, "count": len(rows)})

@app.post("/api/workspace/research/citations/validate")
async def api_research_citations_validate(request: Request):
    data = await request.json()
    return JSONResponse(g_workspace_services.validate_citations(data.get("citations", [])))

@app.post("/api/workspace/research/compare-matrix")
async def api_research_compare_matrix(request: Request):
    data = await request.json()
    return JSONResponse(g_workspace_services.research_compare_matrix(
        data.get("document_ids"),
        data.get("query_terms", []),
    ))

@app.post("/api/workspace/research/repro-workflows")
async def api_research_repro_workflow(request: Request):
    data = await request.json()
    try:
        workflow = g_workspace_services.create_repro_workflow(
            data.get("title", "Reproducible experiment"),
            question=data.get("question", ""),
            steps=data.get("steps"),
            output_path=data.get("output_path", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"workflow": workflow})


@app.post("/api/workspace/research/learning-analysis")
async def api_research_learning_analysis(request: Request):
    data = await request.json()
    library_document = None
    library_document_id = data.get("library_document_id")
    if library_document_id:
        if not g_memory_store:
            raise HTTPException(503, "MemoryOS not initialized")
        try:
            library_document_id = int(library_document_id)
        except (TypeError, ValueError):
            raise HTTPException(400, "Invalid document id")
        library_document = g_memory_store.get_document(library_document_id)
        if not library_document:
            raise HTTPException(404, "Document not found")
        if library_document.get("status") != "ready":
            raise HTTPException(400, "Document is not ready for report generation")
        if not library_document.get("file_path"):
            raise HTTPException(400, "Document has no source file path")
        data["file_path"] = library_document.get("file_path", "")
        data["title"] = data.get("title") or library_document.get("title", "")
    try:
        result = g_workspace_services.generate_research_learning_analysis(
            document_id=data.get("document_id"),
            file_path=data.get("file_path", ""),
            title=data.get("title", ""),
            output_dir=data.get("output_dir", ""),
            formats=data.get("formats"),
            depth=data.get("depth", 5),
            question_count=data.get("question_count", 50),
            report_style=data.get("report_style", "journal"),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    if library_document:
        result["library_document"] = library_document
    return JSONResponse(result)

@app.post("/api/workspace/learning/goals")
async def api_learning_goal_create(request: Request):
    data = await request.json()
    goal = g_workspace_services.create_learning_goal(
        data.get("title", "Learning goal"),
        data.get("description", ""),
        data.get("target_date", ""),
        data.get("topics", []),
    )
    return JSONResponse({"goal": goal})


@app.get("/api/workspace/learning/goals/{goal_id}")
async def api_learning_goal_detail(goal_id: int):
    goal = g_workspace_services.get_learning_goal(goal_id)
    if not goal:
        raise HTTPException(404, "Learning goal not found")
    return JSONResponse({"goal": goal})


@app.post("/api/workspace/learning/items/{item_id}/reviews")
async def api_learning_review(item_id: int, request: Request):
    data = await request.json()
    try:
        item = g_workspace_services.record_learning_review(
            item_id,
            data.get("score", 0),
            data.get("evidence", ""),
            data.get("notes", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"item": item})

@app.post("/api/workspace/learning/goals/{goal_id}/dependencies")
async def api_learning_dependency(goal_id: int, request: Request):
    data = await request.json()
    try:
        edge = g_workspace_services.add_learning_dependency(
            goal_id,
            data.get("source_topic", ""),
            data.get("target_topic", ""),
            data.get("relation", "depends_on"),
            data.get("evidence", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"edge": edge})

@app.post("/api/workspace/learning/items/{item_id}/mistakes")
async def api_learning_mistake(item_id: int, request: Request):
    data = await request.json()
    try:
        mistake = g_workspace_services.record_learning_mistake(
            item_id,
            data.get("prompt", ""),
            data.get("wrong_answer", ""),
            data.get("correct_answer", ""),
            data.get("evidence", ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"mistake": mistake})

@app.get("/api/workspace/learning/goals/{goal_id}/graph")
async def api_learning_graph(goal_id: int):
    try:
        return JSONResponse(g_workspace_services.learning_graph(goal_id))
    except ValueError as exc:
        raise HTTPException(404, str(exc))

@app.get("/api/workspace/learning/goals/{goal_id}/assessment")
async def api_learning_assessment(goal_id: int):
    return JSONResponse(g_workspace_services.long_term_mastery(goal_id))


@app.get("/api/workspace/git/snapshot")
async def api_git_snapshot(path: str):
    try:
        return JSONResponse(g_workspace_services.git_snapshot(path))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/workspace/git/commit-plan")
async def api_git_commit_plan(request: Request):
    data = await request.json()
    try:
        plan = g_workspace_services.prepare_commit_plan(
            data.get("path", ""),
            data.get("message", ""),
            data.get("files"),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"plan": plan})

@app.post("/api/workspace/git/change-requests")
async def api_git_change_request(request: Request):
    data = await request.json()
    try:
        item = g_workspace_services.create_git_change_request(
            data.get("path", ""),
            data.get("message", ""),
            data.get("files"),
            created_by=data.get("created_by", "user"),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"change_request": item})

@app.post("/api/workspace/git/change-requests/{request_id}/approve")
async def api_git_change_request_approve(request_id: int, request: Request):
    data = await request.json()
    try:
        item = g_workspace_services.approve_git_change_request(
            request_id,
            approved_by=data.get("approved_by", "user"),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"change_request": item})

@app.post("/api/workspace/git/change-requests/{request_id}/rollback")
async def api_git_change_request_rollback(request_id: int, request: Request):
    data = await request.json()
    try:
        item = g_workspace_services.rollback_git_change_request(
            request_id,
            actor_id=data.get("actor_id", "user"),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"change_request": item})


@app.get("/api/workspace/templates")
async def api_templates_list():
    rows = g_workspace_services.list_templates()
    return JSONResponse({"templates": rows, "count": len(rows)})


@app.post("/api/workspace/templates")
async def api_template_register(request: Request):
    data = await request.json()
    try:
        template = g_workspace_services.register_template(
            data.get("name", ""),
            data.get("description", ""),
            data.get("files", {}),
            data.get("version", 1),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"template": template})


@app.post("/api/workspace/templates/{name}/instantiate")
async def api_template_instantiate(name: str, request: Request):
    data = await request.json()
    try:
        result = g_workspace_services.instantiate_template(
            name,
            data.get("target_path", ""),
            data.get("parameters", {}),
            data.get("version"),
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)



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
async def api_memory_items(
    memory_type: str = "",
    include_disabled: bool = False,
    limit: int = 200,
    actor_id: str = "system",
    roles: str = "",
    workspace_id: str = "default",
):
    rows = list_memory_items(
        memory_type,
        include_disabled,
        limit,
        actor_id=actor_id,
        roles=[role for role in roles.split(",") if role],
        workspace_id=workspace_id,
    )
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
async def api_memory_items_search(
    q: str = "",
    memory_type: str = "",
    include_disabled: bool = False,
    limit: int = 20,
    actor_id: str = "system",
    roles: str = "",
    workspace_id: str = "default",
):
    if not g_memory_store:
        return JSONResponse({"items": [], "count": 0}, status_code=503)
    rows = g_memory_store.search_memories(
        q,
        memory_type,
        limit,
        include_disabled,
        actor_id=actor_id,
        roles=[role for role in roles.split(",") if role],
        workspace_id=workspace_id,
    )
    return JSONResponse({"items": rows, "count": len(rows)})


@app.get("/api/knowledge")
async def api_knowledge_list(category: str = ""):
    if not g_memory_store:
        return JSONResponse({"items": [], "count": 0}, status_code=503)
    rows = g_memory_store.list_knowledge(category)
    return JSONResponse({"items": rows, "count": len(rows)})


@app.post("/api/knowledge")
async def api_knowledge_save(request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    data = await request.json()
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    if not title or not content:
        raise HTTPException(400, "title and content are required")
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]
    item = g_memory_store.add_knowledge(
        title=title,
        content=content,
        category=str(data.get("category", "domain") or "domain").strip() or "domain",
        source=str(data.get("source", "manual") or "manual").strip(),
        tags=tags if isinstance(tags, list) else [],
        confidence=float(data.get("confidence", 0.7) or 0.7),
    )
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"item": item, "saved": True})


@app.put("/api/knowledge/{knowledge_id}")
async def api_knowledge_update(knowledge_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    data = await request.json()
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    if not title or not content:
        raise HTTPException(400, "title and content are required")
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]
    item = g_memory_store.update_knowledge(
        knowledge_id,
        title=title,
        content=content,
        category=str(data.get("category", "domain") or "domain").strip() or "domain",
        source=str(data.get("source", "manual") or "manual").strip(),
        tags=tags if isinstance(tags, list) else [],
        confidence=float(data.get("confidence", 0.7) or 0.7),
    )
    if not item:
        raise HTTPException(404, "Knowledge item not found")
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"item": item, "updated": True})


@app.delete("/api/knowledge/{knowledge_id}")
async def api_knowledge_delete(knowledge_id: int):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    deleted = g_memory_store.delete_knowledge(knowledge_id)
    if not deleted:
        raise HTTPException(404, "Knowledge item not found")
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"deleted": True, "id": knowledge_id})


@app.get("/api/knowledge/search")
async def api_knowledge_search(q: str = "", category: str = "", limit: int = 10):
    if not g_memory_store:
        return JSONResponse({"items": [], "count": 0}, status_code=503)
    if not q:
        return JSONResponse({"items": [], "count": 0})
    rows = g_memory_store.search_knowledge(q, category, max(1, min(int(limit or 10), 50)))
    return JSONResponse({"items": rows, "count": len(rows)})


@app.get("/api/acceptance/deepseek-qwen/latest")
async def api_latest_deepseek_qwen_acceptance():
    report_path = (BASE_DIR.parent / "output" / "deepseek_hybrid_rag_acceptance.json").resolve()
    output_root = (BASE_DIR.parent / "output").resolve()
    if output_root not in report_path.parents:
        raise HTTPException(status_code=403, detail="Report path outside output")
    if not report_path.exists():
        return JSONResponse({
            "found": False,
            "report_path": str(report_path),
            "message": "No DeepSeek+Qwen acceptance report found under output.",
        })
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {type(exc).__name__}") from exc
    benchmark = data.get("benchmark") or {}
    metrics = benchmark.get("metrics") or {}
    cases = []
    for case in data.get("cases") or []:
        cases.append({
            "scenario": case.get("scenario", ""),
            "name": case.get("name", ""),
            "pass": bool(case.get("pass")),
            "citation_hit": bool(case.get("citation_hit")),
            "latency_ms": case.get("latency_ms", 0),
            "vector_rank": case.get("vector_rank", 0),
            "rerank_rank": case.get("rerank_rank", 0),
        })
    return JSONResponse({
        "found": True,
        "report_path": str(report_path),
        "ok": bool(data.get("ok")),
        "model": data.get("model", ""),
        "benchmark": {
            "name": benchmark.get("name", ""),
            "case_count": benchmark.get("case_count", len(cases)),
            "metrics": {
                "pass_rate": metrics.get("pass_rate", 0),
                "passed_count": metrics.get("passed_count", 0),
                "failed_count": metrics.get("failed_count", 0),
                "citation_hit_rate": metrics.get("citation_hit_rate", 0),
                "judge_grounded_rate": metrics.get("judge_grounded_rate", 0),
                "latency_p50_ms": metrics.get("latency_p50_ms", 0),
                "latency_p95_ms": metrics.get("latency_p95_ms", 0),
            },
        },
        "cases": cases,
    })


@app.post("/api/documents/upload")
async def api_document_upload(
    files: list[UploadFile] = File(...),
    category: str = Form("domain"),
):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    from memoryos.document_ingestion import ingest_file, safe_filename

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    documents = []
    errors = []
    for file in files[:12]:
        raw = await file.read()
        if not raw:
            errors.append({"filename": file.filename, "error": "empty file"})
            continue
        if len(raw) > 50 * 1024 * 1024:
            errors.append({"filename": file.filename, "error": "file too large; max 50MB"})
            continue
        target = UPLOAD_DIR / f"{int(time.time() * 1000)}_{safe_filename(file.filename or 'upload')}"
        target.write_bytes(raw)
        try:
            doc = ingest_file(
                g_memory_store,
                UPLOAD_DIR,
                target,
                title=Path(file.filename or target.name).stem,
                category=str(category or "domain"),
            )
            documents.append(doc)
        except Exception as exc:
            errors.append({"filename": file.filename, "error": str(exc)})
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"documents": documents, "errors": errors, "count": len(documents)})


def get_knowledge_service() -> KnowledgeService:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    global g_knowledge_service
    if not g_knowledge_service or getattr(g_knowledge_service, "store", None) is not g_memory_store:
        g_knowledge_service = KnowledgeService(g_memory_store, UPLOAD_DIR, lambda: g_vector_store.refresh() if g_vector_store else None)
    return g_knowledge_service


@app.get("/api/documents")
async def api_documents(category: str = ""):
    if not g_memory_store:
        return JSONResponse({"documents": [], "count": 0}, status_code=503)
    docs = g_memory_store.list_documents(category)
    return JSONResponse({"documents": docs, "count": len(docs)})


@app.get("/api/documents/ocr-queue")
async def api_documents_ocr_queue(category: str = ""):
    service = get_knowledge_service()
    pending = service.list_ocr_queue(category)
    return JSONResponse({"documents": pending, "count": len(pending)})


@app.post("/api/documents/{document_id}/ocr")
async def api_document_run_ocr(document_id: int, request: Request):
    service = get_knowledge_service()
    data = await request.json()
    try:
        result = service.run_ocr(
            document_id,
            sidecar_text=str(data.get("sidecar_text") or ""),
            force=bool(data.get("force")),
        )
    except ValueError as exc:
        message = str(exc)
        if message == "Document not found":
            raise HTTPException(404, message)
        raise HTTPException(400, message)
    return JSONResponse(result)


@app.get("/api/documents/{document_id}/chunks")
async def api_document_chunks(document_id: int, limit: int = 20):
    if not g_memory_store:
        return JSONResponse({"chunks": [], "count": 0}, status_code=503)
    document = g_memory_store.get_document(document_id)
    if not document:
        raise HTTPException(404, "Document not found")
    chunks = g_memory_store.get_document_chunks(document_id, max(1, min(int(limit or 20), 100)))
    return JSONResponse({"document": document, "chunks": chunks, "count": len(chunks)})


@app.get("/api/documents/search")
async def api_document_search(q: str = "", category: str = "", limit: int = 10):
    if not g_memory_store:
        return JSONResponse({"chunks": [], "count": 0}, status_code=503)
    if not q:
        return JSONResponse({"chunks": [], "count": 0})
    chunks = g_memory_store.search_document_chunks(q, category, max(1, min(int(limit or 10), 50)))
    return JSONResponse({"chunks": chunks, "count": len(chunks)})


@app.get("/api/documents/citation-answer")
async def api_document_citation_answer(q: str = "", category: str = "", document_id: int = 0, limit: int = 5):
    service = get_knowledge_service()
    try:
        return JSONResponse(service.citation_answer(q, category, document_id, limit))
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/knowledge/graph")
async def api_knowledge_graph(category: str = "", limit: int = 80):
    service = get_knowledge_service()
    return JSONResponse(service.knowledge_graph(category, limit))


@app.get("/api/knowledge/obsidian/check")
async def api_knowledge_obsidian_check(category: str = "", limit: int = 120):
    service = get_knowledge_service()
    return JSONResponse(service.obsidian_check(category, limit))



def resolve_obsidian_output_dir(requested: str = "", category: str = "") -> Path:
    output_root = (BASE_DIR.parent / "output" / "obsidian").resolve()
    requested = str(requested or "").strip()
    if requested:
        raw = Path(requested).expanduser()
        if raw.is_absolute():
            output_dir = raw.resolve()
        else:
            repo_relative = (BASE_DIR.parent / raw).resolve()
            try:
                repo_relative.relative_to(output_root)
                output_dir = repo_relative
            except ValueError:
                output_dir = (output_root / raw).resolve()
        try:
            output_dir.relative_to(output_root)
        except ValueError:
            raise HTTPException(400, "output_dir must stay under output/obsidian")
        return output_dir
    slug = re.sub(r"[^\w.-]+", "_", category or "all").strip("._") or "all"
    return output_root / slug

@app.post("/api/knowledge/obsidian/export")
async def api_knowledge_obsidian_export(request: Request):
    service = get_knowledge_service()
    data = await request.json()
    category = str(data.get("category", "") or "")
    limit = max(1, min(int(data.get("limit", 300) or 300), 1000))
    output_dir = resolve_obsidian_output_dir(str(data.get("output_dir", "") or ""), category)
    return JSONResponse(service.export_obsidian_vault(output_dir, category=category, limit=limit))


@app.get("/api/memory/items/{memory_id}/versions")
async def api_memory_versions(memory_id: int, limit: int = 100):
    if not g_memory_store or not g_memory_store.get_memory(memory_id):
        raise HTTPException(404, "Memory item not found")
    rows = g_memory_store.list_memory_versions(memory_id, limit)
    return JSONResponse({"versions": rows, "count": len(rows)})


@app.get("/api/memory/items/{memory_id}/evidence")
async def api_memory_evidence(memory_id: int, limit: int = 100):
    if not g_memory_store or not g_memory_store.get_memory(memory_id):
        raise HTTPException(404, "Memory item not found")
    rows = g_memory_store.list_memory_evidence(memory_id, limit)
    return JSONResponse({"evidence": rows, "count": len(rows)})


@app.get("/api/memory/reviews")
async def api_memory_reviews(status: str = "pending", limit: int = 100):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    rows = g_memory_store.list_memory_reviews(status, limit)
    return JSONResponse({"reviews": rows, "count": len(rows)})


@app.post("/api/memory/reviews/{review_id}/resolve")
async def api_memory_review_resolve(review_id: int, request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    data = await request.json()
    try:
        review = g_memory_store.resolve_memory_review(
            review_id,
            data.get("decision", ""),
            reviewer=str(data.get("reviewer", "system") or "system"),
            notes=str(data.get("notes", "") or ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not review:
        raise HTTPException(404, "Review not found")
    if g_vector_store:
        g_vector_store.refresh()
    return JSONResponse({"review": review, "resolved": True})


@app.get("/api/memory/items/{memory_id}/acl")
async def api_memory_acl(memory_id: int):
    if not g_memory_store or not g_memory_store.get_memory(memory_id):
        raise HTTPException(404, "Memory item not found")
    rows = g_memory_store.list_memory_acl(memory_id)
    return JSONResponse({"acl": rows, "count": len(rows)})


@app.post("/api/memory/items/{memory_id}/acl")
async def api_memory_acl_grant(memory_id: int, request: Request):
    if not g_memory_store or not g_memory_store.get_memory(memory_id):
        raise HTTPException(404, "Memory item not found")
    data = await request.json()
    try:
        rows = g_memory_store.grant_memory_acl(
            memory_id,
            data.get("principal_type", ""),
            data.get("principal_id", ""),
            data.get("permission", ""),
            data.get("granted_by", "system"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"acl": rows, "count": len(rows)})


@app.post("/api/memory/evaluations/run")
async def api_memory_evaluation_run(request: Request):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    data = await request.json()
    cases = data.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise HTTPException(400, "cases must be a non-empty list")
    from memoryos.services.retrieval import RetrievalService
    from memoryos.services.retrieval_benchmark import RetrievalBenchmark
    retrieval = RetrievalService(g_memory_store, g_vector_store)
    run = RetrievalBenchmark(g_memory_store, retrieval).run(
        cases,
        top_k=data.get("top_k", 5),
        name=data.get("name", "memory-retrieval"),
        created_by=data.get("created_by", "system"),
    )
    return JSONResponse({"run": run})


@app.get("/api/tasks")
async def api_tasks(session_id: str = "", status: str = "", limit: int = 50):
    rows = list_runtime_tasks(session_id=session_id, status=status, limit=limit)
    return JSONResponse({"tasks": rows, "count": len(rows)})


@app.get("/api/tasks/queue")
async def api_tasks_queue(status: str = "", limit: int = 50):
    statuses = [item.strip() for item in status.split(",") if item.strip()] if status else None
    rows = list_runtime_task_queue(statuses=statuses, limit=limit)
    return JSONResponse({"tasks": rows, "count": len(rows)})


@app.post("/api/tasks/queue/claim")
async def api_tasks_queue_claim(request: Request):
    data = await request.json()
    statuses = data.get("statuses")
    if isinstance(statuses, str):
        statuses = [item.strip() for item in statuses.split(",") if item.strip()]
    elif not isinstance(statuses, list):
        statuses = None
    task = claim_runtime_task(
        worker_id=str(data.get("worker_id", "worker")),
        statuses=statuses,
    )
    return JSONResponse({"task": task, "claimed": bool(task)})


@app.post("/api/tasks/recover")
async def api_tasks_recover(request: Request):
    data = await request.json()
    result = get_task_service().recover(
        actor_id=str(data.get("actor_id", "user")),
        create_retries=bool(data.get("create_retries", False)),
    )
    return JSONResponse(result)


@app.get("/api/tasks/worker/status")
async def api_tasks_worker_status():
    task = g_background_worker_task
    state = dict(g_background_worker_status)
    state["running"] = bool(task and not task.done())
    state["done"] = bool(task.done()) if task else True
    return JSONResponse(state)


@app.post("/api/tasks/worker/tick")
async def api_tasks_worker_tick(request: Request):
    data = await request.json()
    result = await run_background_worker_once(
        worker_id=str(data.get("worker_id") or "api-worker"),
        max_attempts=int(data.get("max_attempts") or 3),
    )
    return JSONResponse(result)


@app.post("/api/tasks/worker/start")
async def api_tasks_worker_start(request: Request):
    global g_background_worker_task
    data = await request.json()
    if g_background_worker_task and not g_background_worker_task.done():
        return JSONResponse({"ok": True, "already_running": True, **g_background_worker_status})
    worker_id = str(data.get("worker_id") or "background-worker")
    interval_s = float(data.get("interval_s") or 0.5)
    max_attempts = int(data.get("max_attempts") or 3)
    g_background_worker_status.update({
        "running": True,
        "worker_id": worker_id,
        "last_error": "",
    })
    g_background_worker_task = asyncio.create_task(
        background_worker_loop(worker_id=worker_id, interval_s=interval_s, max_attempts=max_attempts)
    )
    return JSONResponse({"ok": True, "started": True, "worker_id": worker_id})


@app.post("/api/tasks/worker/stop")
async def api_tasks_worker_stop():
    global g_background_worker_task
    task = g_background_worker_task
    if not task or task.done():
        g_background_worker_status["running"] = False
        return JSONResponse({"ok": True, "stopped": False, **g_background_worker_status})
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    g_background_worker_task = None
    g_background_worker_status["running"] = False
    return JSONResponse({"ok": True, "stopped": True, **g_background_worker_status})


@app.post("/api/tasks/jobs/report")
async def api_tasks_job_report(request: Request):
    data = await request.json()
    document_id = int(data.get("library_document_id") or data.get("document_id") or 0)
    if not document_id:
        raise HTTPException(400, "library_document_id is required")
    metadata = {
        "worker_action": "generate_report",
        "library_document_id": document_id,
        "report_style": data.get("report_style", "journal"),
        "depth": data.get("depth", 5),
        "question_count": data.get("question_count", 40),
        "output_dir": data.get("output_dir", "output/reports"),
        "formats": data.get("formats") or ["markdown", "pdf"],
        "idempotency_key": data.get("idempotency_key", ""),
    }
    task = enqueue_runtime_task("worker-jobs", f"Generate report for document {document_id}", metadata=metadata)
    return JSONResponse({"queued": True, "task": task})


@app.post("/api/tasks/jobs/ocr-queue")
async def api_tasks_job_ocr_queue(request: Request):
    data = await request.json()
    metadata = {
        "worker_action": "process_ocr_queue",
        "category": data.get("category", ""),
        "limit": data.get("limit", 12),
        "force": bool(data.get("force", True)),
        "idempotency_key": data.get("idempotency_key", ""),
    }
    task = enqueue_runtime_task("worker-jobs", "Process OCR queue", metadata=metadata)
    return JSONResponse({"queued": True, "task": task})


@app.post("/api/tasks/jobs/batch-ingest")
async def api_tasks_job_batch_ingest(request: Request):
    data = await request.json()
    files = data.get("files") or data.get("paths") or []
    if isinstance(files, str):
        files = [item.strip() for item in re.split(r"[\n,;]+", files) if item.strip()]
    if not isinstance(files, list) or not files:
        raise HTTPException(400, "files must be a non-empty list")
    metadata = {
        "worker_action": "batch_ingest_documents",
        "files": files,
        "category": data.get("category", "domain"),
        "limit": data.get("limit", 24),
        "idempotency_key": data.get("idempotency_key", ""),
    }
    task = enqueue_runtime_task("worker-jobs", f"Batch ingest {len(files)} documents", metadata=metadata)
    return JSONResponse({"queued": True, "task": task})

@app.get("/api/tasks/events")
async def api_task_events(session_id: str = "", after_id: int = 0, limit: int = 100):
    if not g_task_service and not g_memory_store:
        return JSONResponse({"events": [], "count": 0}, status_code=503)
    rows = get_task_service().events(session_id=session_id, after_id=after_id, limit=limit)
    return JSONResponse({"events": rows, "count": len(rows)})

@app.post("/api/tasks/events/prune")
async def api_task_events_prune(request: Request):
    data = await request.json()
    result = get_task_service().prune_events(
        older_than_days=data.get("older_than_days", 30),
        retain_latest_per_task=data.get("retain_latest_per_task", 100),
        dry_run=bool(data.get("dry_run", False)),
        actor_id=str(data.get("actor_id", "user")),
    )
    return JSONResponse(result)

@app.get("/api/tasks/stream")
async def api_task_stream(session_id: str = "", after_id: int = 0):
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")

    async def gen():
        cursor = int(after_id or 0)
        for _ in range(180):
            rows = get_task_service().events(session_id=session_id, after_id=cursor, limit=50)
            if rows:
                cursor = max(int(row["id"]) for row in rows)
                yield f"event: task_events\ndata: {json.dumps(rows, ensure_ascii=False)}\n\n"
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.get("/api/tasks/{task_id}")
async def api_task_detail(task_id: int):
    return JSONResponse(get_runtime_task(task_id))

@app.post("/api/tasks/{task_id}/cancel")
async def api_task_cancel(task_id: int, request: Request):
    data = await request.json()
    item = cancel_runtime_task(
        task_id,
        reason=str(data.get("reason", "")),
        actor_id=str(data.get("actor_id", "user")),
    )
    return JSONResponse({"task": item})

@app.post("/api/tasks/{task_id}/retry")
async def api_task_retry(task_id: int, request: Request):
    data = await request.json()
    item = retry_runtime_task(
        task_id,
        reason=str(data.get("reason", "")),
        actor_id=str(data.get("actor_id", "user")),
    )
    return JSONResponse({"task": item})

@app.get("/api/benchmarks/scenarios/suites")
async def api_scenario_benchmark_suites():
    if not g_scenario_benchmark:
        return JSONResponse({"suites": [], "count": 0}, status_code=503)
    rows = g_scenario_benchmark.list_suites()
    return JSONResponse({"suites": rows, "count": len(rows)})

@app.post("/api/benchmarks/scenarios/suites")
async def api_scenario_benchmark_create_suite(request: Request):
    if not g_scenario_benchmark:
        raise HTTPException(503, "Scenario benchmark is unavailable")
    data = await request.json()
    try:
        suite = g_scenario_benchmark.create_suite(
            str(data.get("name", "")),
            data.get("cases") or [],
            description=str(data.get("description", "")),
            created_by=str(data.get("created_by", "user")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(suite)

@app.get("/api/benchmarks/scenarios/runs")
async def api_scenario_benchmark_runs(suite_id: int = 0, limit: int = 50):
    if not g_scenario_benchmark:
        return JSONResponse({"runs": [], "count": 0}, status_code=503)
    rows = g_scenario_benchmark.list_runs(suite_id=suite_id, limit=limit)
    return JSONResponse({"runs": rows, "count": len(rows)})

@app.post("/api/benchmarks/scenarios/run")
async def api_scenario_benchmark_run(request: Request):
    if not g_scenario_benchmark:
        raise HTTPException(503, "Scenario benchmark is unavailable")
    data = await request.json()
    suite_id = int(data.get("suite_id", 0) or 0)
    if not suite_id:
        suites = g_scenario_benchmark.list_suites()
        suite_id = int(suites[-1]["id"] if suites else 0)

    def runner(tool_name: str, args: dict[str, Any]):
        task = create_runtime_task(
            "benchmark",
            f"Benchmark: {tool_name}",
            source="scenario_benchmark",
            metadata={"tool": tool_name, "args": args},
        )
        result = execute_tool_call(
            tool_name,
            json.dumps(args or {}, ensure_ascii=False),
            session_id="benchmark",
            confirmed_tools=set(data.get("confirmed_tools") or []),
            task_id=task.get("id"),
        )
        finish_runtime_task(task.get("id"), "succeeded" if result.get("ok") else "failed")
        return result

    try:
        run = g_scenario_benchmark.run_suite(
            suite_id,
            runner,
            thresholds=data.get("thresholds") or {},
            created_by=str(data.get("created_by", "user")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(run)

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

@app.post("/api/skills/execute")
async def skills_execute(request: Request):
    try:
        from skills.skill_registry import execute_skill, execute_skill_definition, get_skill

        data = await request.json()
        name = str(data.get("name") or "").strip()
        params = data.get("params") or {}
        plan_only = bool(data.get("plan_only", True))
        if not name:
            raise HTTPException(400, "skill name is required")
        if not isinstance(params, dict):
            raise HTTPException(400, "params must be an object")
        if plan_only:
            skill = get_skill(name)
            if not skill:
                raise HTTPException(404, f"skill not found: {name}")
            result = execute_skill_definition(skill, params=params, plan_only=True)
        else:
            result = execute_skill(name, params)
        return JSONResponse({"mode": "plan" if plan_only else "execute", "result": result})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"skill execution failed: {e}")
@app.get("/api/skills/stats")
async def skills_stats():
    if not g_memory_store:
        return JSONResponse({"records": [], "count": 0})
    records = g_memory_store.get_skill_stats()
    return JSONResponse({"records": records, "count": len(records)})

@app.get("/api/skills/evolution/versions")
async def skill_evolution_versions(skill_name: str = "", limit: int = 100):
    if not g_skill_evolution:
        return JSONResponse({"versions": [], "count": 0}, status_code=503)
    rows = g_skill_evolution.list_versions(skill_name, limit)
    return JSONResponse({"versions": rows, "count": len(rows)})

@app.get("/api/skills/evolution/runs")
async def skill_evolution_runs(version_id: int = 0, limit: int = 100):
    if not g_skill_evolution:
        return JSONResponse({"runs": [], "count": 0}, status_code=503)
    rows = g_skill_evolution.list_runs(version_id, limit)
    return JSONResponse({"runs": rows, "count": len(rows)})

@app.get("/api/skills/evolution/review-inbox")
async def skill_evolution_review_inbox(status: str = "", limit: int = 100):
    if not g_skill_evolution:
        return JSONResponse({"items": [], "count": 0}, status_code=503)
    rows = g_skill_evolution.review_inbox(status=status, limit=limit)
    return JSONResponse({"items": rows, "count": len(rows)})

@app.post("/api/skills/evolution/candidates")
async def skill_evolution_candidate(request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.propose(
            str(data.get("skill_name", "")),
            data.get("definition") or {},
            change_reason=str(data.get("change_reason", "")),
            source_ref=str(data.get("source_ref", "")),
            created_by=str(data.get("created_by", "user")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/suites")
async def skill_evolution_suite(request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.create_suite(
            str(data.get("name", "")),
            str(data.get("skill_name", "")),
            data.get("cases") or [],
            frozen=bool(data.get("frozen", True)),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/versions/{version_id}/evaluate")
async def skill_evolution_evaluate(version_id: int, request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.evaluate(
            version_id, int(data.get("suite_id", 0)), data.get("thresholds") or {}
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/versions/{version_id}/promote")
async def skill_evolution_promote(version_id: int, request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.promote(
            version_id, actor=str(data.get("actor", "user"))
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/versions/{version_id}/review")
async def skill_evolution_review(version_id: int, request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.review(
            version_id,
            action=str(data.get("action", "")),
            reviewer=str(data.get("reviewer", "user")),
            notes=str(data.get("notes", "")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

@app.get("/api/skills/evolution/versions/{version_id}/manifest")
async def skill_evolution_manifest(version_id: int):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    try:
        result = g_skill_evolution.dependency_manifest(version_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/versions/{version_id}/sign")
async def skill_evolution_sign(version_id: int, request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.sign_version(
            version_id,
            signer=str(data.get("signer", "user")),
            secret=str(data.get("secret", "clawos-local-signing")),
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/versions/{version_id}/fresh-audit")
async def skill_evolution_fresh_audit(version_id: int, request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.fresh_agent_audit(
            version_id,
            suite_id=data.get("suite_id"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/versions/{version_id}/canary")
async def skill_evolution_canary(version_id: int, request: Request):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    data = await request.json()
    try:
        result = g_skill_evolution.start_canary(
            version_id,
            percent=data.get("percent", 10),
            actor=str(data.get("actor", "user")),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

@app.post("/api/skills/evolution/promotions/{promotion_id}/rollback")
async def skill_evolution_rollback(promotion_id: int):
    if not g_skill_evolution:
        raise HTTPException(503, "skill evolution is unavailable")
    try:
        result = g_skill_evolution.rollback(promotion_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(result)

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


@app.get("/api/tools/accuracy")
async def api_tools_accuracy(session_id: str = "", limit: int = 200):
    if not g_memory_store:
        return JSONResponse({"tools": [], "count": 0}, status_code=503)
    rows = g_memory_store.list_tool_executions(session_id, limit)
    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("tool_name") or "unknown"
        item = stats.setdefault(name, {"tool": name, "calls": 0, "success": 0, "errors": 0, "confirmations": 0, "duration_total": 0.0})
        item["calls"] += 1
        item["duration_total"] += float(row.get("duration_ms") or 0)
        if row.get("status") == "success":
            item["success"] += 1
        else:
            item["errors"] += 1
        if row.get("requires_confirmation"):
            item["confirmations"] += 1
    tools = []
    for item in stats.values():
        calls = max(1, int(item["calls"]))
        tools.append({
            "tool": item["tool"],
            "calls": item["calls"],
            "success": item["success"],
            "errors": item["errors"],
            "success_rate": round(item["success"] / calls, 4),
            "confirmation_rate": round(item["confirmations"] / calls, 4),
            "avg_duration_ms": round(item["duration_total"] / calls, 2),
        })
    tools.sort(key=lambda x: (-x["calls"], x["tool"]))
    return JSONResponse({"tools": tools, "count": len(tools)})


@app.get("/api/routing/policy")
async def api_routing_policy(q: str = ""):
    candidates = score_scenarios(q)
    scenario = candidates[0]["scenario"] if candidates else classify_scenario(q)
    selected = SCENARIO_ROUTING_POLICY[scenario]
    return JSONResponse({
        "scenario": scenario,
        "selected": selected,
        "candidates": candidates,
        "strategy": {
            "mode": "scored_policy_routing",
            "model_profile": selected.get("model_profile", "balanced"),
            "retrieval": selected.get("retrieval", "memory_optional"),
            "tools": selected.get("tools", []),
            "risk": selected.get("risk", "low"),
            "requires_confirmation": selected.get("requires_confirmation", []),
        },
        "policies": SCENARIO_ROUTING_POLICY,
    })

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
