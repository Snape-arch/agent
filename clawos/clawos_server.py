#!/usr/bin/env python3
"""ClawOS Server - Self-contained AI Agent with DeepSeek + Function Router."""
from __future__ import annotations
import argparse, asyncio, base64, hashlib, importlib.util, json, logging, os, re, sys, time, subprocess, shutil
from dataclasses import asdict
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any, Annotated

# Bound the default numerical thread pools before importing NumPy/SciPy/Torch.
# Explicit operator settings are preserved. No machine/global environment edits.
for _thread_variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(_thread_variable,'2')

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from providers import create_model_provider
from memoryos.document_ingestion import ingest_file, safe_filename
from services import (
    AgentOrchestrationService,
    AutonomousSubagentService,
    ArtifactStorage,
    EvaluationService,
    KnowledgeService,
    MaintenanceService,
    ModelService,
    CodingWorkflowService,
    OfficeProductivityService,
    PaperIntelligenceService,
    ScholarlySearchService,
    SecurityService,
    TaskService,
    ToolService,
    WorkflowEngine,
)
from services.artifact_storage import safe_artifact_slug
from services.artifact_delivery_service import ArtifactDeliveryService
from services.competition_evidence_service import CompetitionEvidenceService, EVIDENCE_CHAIN_SCHEMA
from services.feishu import FeishuConnectorService, FeishuClient, load_feishu_config
from services.grounded_paper_report import GroundedPaperReport
from services.runtime_records import RUN_SCHEMA_VERSION, RunRecord, now_iso, run_from_task
from services.search_evidence import decide_search_need
from services.response_contract import SYSTEM_PROMPT, RESPONSE_STYLE, request_history

# ---- PATHS ----
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
from services.runtime_release import RuntimeRelease, core_ready
RUNTIME_RELEASE = RuntimeRelease(BASE_DIR)
CONFIG_PATH = BASE_DIR / "config.json"
SCRIPTS_DIR = BASE_DIR / "scripts"
DATA_DIR = Path(os.environ.get("CLAWOS_DATA_DIR", str(BASE_DIR))).expanduser().resolve()
OUTPUT_ROOT = Path(os.environ.get("CLAWOS_OUTPUT_DIR", str(BASE_DIR.parent / "output"))).expanduser().resolve()
ENV_PATH = Path(os.environ.get("CLAWOS_ENV_PATH", str(BASE_DIR / ".env"))).expanduser().resolve()
NOTES_DIR = DATA_DIR / "notes"
TODO_FILE = DATA_DIR / "clawos_todo.json"
UPLOAD_DIR = DATA_DIR / "uploads"


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


if os.environ.get('CLAWOS_SKIP_LOCAL_ENV') != '1':
    load_local_env(ENV_PATH)

CONFIG_PATH = Path(os.environ.get("CLAWOS_CONFIG_PATH", str(CONFIG_PATH))).expanduser().resolve()
MEMORY_DB = Path(os.environ.get("CLAWOS_MEMORY_DB", str(DATA_DIR / "memoryos.db"))).expanduser().resolve()

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
g_runtime_policy_controller: Any = None
g_knowledge_service: KnowledgeService | None = None
g_paper_intelligence_service: PaperIntelligenceService | None = None
g_scholarly_search_service: ScholarlySearchService | None = None
g_security_service: SecurityService | None = None
g_task_service: TaskService | None = None
g_maintenance_service: MaintenanceService | None = None
g_evaluation_service: EvaluationService | None = None
g_workflow_engine: WorkflowEngine | None = None
g_agent_orchestration_service: AgentOrchestrationService | None = None
g_coding_workflow_service: CodingWorkflowService | None = None
g_office_productivity_service: OfficeProductivityService | None = None
g_feishu_connector_service: Any = None
g_feishu_long_connect: Any = None  # FeishuLongConnectManager, started only when live
g_background_worker_task: asyncio.Task | None = None
g_document_index_worker = None
g_research_watch_service = None
g_research_watch_worker = None
g_research_ai_worker = None
g_background_worker_status: dict[str, Any] = {
    "running": False,
    "worker_id": "",
    "processed": 0,
    "last_result": None,
    "last_error": "",
}

WEB_RESEARCH_SYNTHESIS_PROMPT = (
    "When web research is enabled, use it only when freshness, external verification, "
    "or source coverage materially improves the answer. Prefer primary and authoritative "
    "sources for factual claims, while adding high-signal independent or community analysis "
    "when it contributes practical experience or a distinct perspective. Read the useful "
    "sources before concluding. Answer the user's question directly: synthesize evidence into "
    "natural prose, place links next to the claims they support, and do not dump search-result "
    "lists or narrate search mechanics unless asked. Separate supported facts, inference, and "
    "uncertainty."
)
WEB_RESEARCH_TOOLS = {"web_search", "web_fetch", "scholarly_search", "scholarly_download"}

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
    from services.config_environment import resolve_environment
    return normalize_config(resolve_environment(cfg))


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

    write_model_env(ENV_PATH, updates)
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
    allowed_env["CLAWOS_OUTPUT_DIR"] = str(OUTPUT_ROOT)
    allowed_env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, str(SCRIPTS_DIR / "tool_worker.py"), name]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        sandbox_evidence = {
            "backend": "subprocess-policy-boundary",
            "os_enforced": False,
            "filesystem_isolated": False,
            "network_isolated": False,
        }
        if os.name == "nt":
            from services.os_sandbox import WindowsJobSandbox
            executed = WindowsJobSandbox(max_processes=8, process_memory_mb=1024).run(
                command,
                BASE_DIR,
                input_text=args_str or "{}",
                environment=allowed_env,
                timeout_seconds=timeout_s,
            )
            output = str(executed.get("stdout") or "").strip()
            stderr = str(executed.get("stderr") or "")
            return_code = int(executed.get("exit_code") or 0)
            sandbox_evidence = executed.get("sandbox") or sandbox_evidence
        else:
            proc = subprocess.run(
                command,
                input=args_str or "{}",
                cwd=str(BASE_DIR),
                env=allowed_env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                creationflags=creationflags,
            )
            output = proc.stdout.strip()
            stderr = proc.stderr
            return_code = proc.returncode
        if not output:
            return {"error": stderr.strip() or f"Tool worker exited with code {return_code}", "sandbox": sandbox_evidence}
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            result = {"result": output[:2000]}
        if return_code and not result.get("error"):
            result["error"] = stderr.strip() or f"Tool worker exited with code {return_code}"
        result["sandbox"] = sandbox_evidence
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
    configs = config.get(f"{section}_fallbacks", config.get("model_fallbacks", [])) or []
    candidates = [primary] if primary else []
    for cfg in configs:
        if isinstance(cfg, dict):
            candidates.append(create_model_provider(cfg))
    return candidates


async def call_routing_llm(
    messages: list[dict[str, Any]],
    available_tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call configured model provider for tool detection."""
    result = await call_model_with_fallback(
        "routing",
        messages,
        {
        "tools": available_tools if available_tools is not None else tools_def,
        "temperature": 0.0,
        }
    )
    if not result["ok"]:
        raise RuntimeError(result["error"])
    raw = dict(result["raw"])
    raw["clawos_model"] = {key: result.get(key) for key in (
        "provider", "model", "usage", "duration_ms", "fallback_attempts"
    )}
    return raw


def has_api_key(section: str = "routing") -> bool:
    candidates = _provider_candidates(section)
    if candidates:
        return any(provider.is_configured() for provider in candidates
                   if hasattr(provider, "is_configured"))
    key = str(config.get(section, {}).get("api_key", "") or "")
    return bool(key and "${" not in key and key != "YOUR_DEEPSEEK_API_KEY")


SCENARIO_ROUTING_POLICY = {
    "research": {"tools": ["knowledge_search", "web_search", "web_fetch", "research_pdf", "paper_intelligence", "scholarly_search", "scholarly_download", "paper_deep_read", "research_experiment_plan", "office_productivity", "text_stats"], "risk": "medium", "model_profile": "deep_reasoning", "retrieval": "citations_required", "requires_confirmation": ["web_fetch", "scholarly_search", "scholarly_download", "office_productivity"], "description": "科研检索、开放获取下载、结构化论文解析、跨论文比较和可引用 RAG"},
    "learning": {"tools": ["knowledge_search", "learning_workspace", "web_fetch", "exam_practice_builder", "text_stats"], "risk": "medium", "model_profile": "tutor", "retrieval": "knowledge_first", "requires_confirmation": ["web_fetch"], "description": "学习目标、资料入库、练习题和掌握度"},
    "office": {"tools": ["knowledge_search", "meeting_action_items", "meeting_workflow", "office_artifact", "office_productivity", "autonomous_subagents", "work_brief_builder", "text_stats"], "risk": "medium", "model_profile": "structured_output", "retrieval": "workspace_context", "requires_confirmation": ["meeting_workflow", "office_artifact", "office_productivity", "autonomous_subagents"], "description": "会议、邮件、日历和多格式办公产物"},
    "project": {"tools": ["ls", "cat", "find_files", "grep_text", "file_info", "code_stats", "find_todos", "dir_tree", "coding_agent", "coding_workflow", "autonomous_subagents", "git_workspace", "shell_exec", "file_write"], "risk": "high", "model_profile": "code_agent", "retrieval": "repo_context", "requires_confirmation": ["coding_agent", "coding_workflow", "autonomous_subagents", "git_workspace", "shell_exec", "file_write"], "description": "项目分析、审批式编码循环、测试审查和 Git 操作"},
    "web": {"tools": ["web_search", "web_fetch"], "risk": "medium", "model_profile": "fresh_context", "retrieval": "web_then_rag", "requires_confirmation": ["web_fetch"], "description": "联网搜索和网页正文抓取"},
    "general": {"tools": ["weather", "time_now", "calc", "todo_list", "note_save", "note_read", "note_list", "text_stats", "knowledge_search", "memory_history", "memory_profile_get", "memory_preference_get", "memory_stats", "tools_list", "skill_list"], "risk": "low", "model_profile": "balanced", "retrieval": "memory_optional", "requires_confirmation": [], "description": "通用对话、记忆和轻量记录"},
}


SCENARIO_ROUTING_KEYWORDS = {
    "research": ["论文", "科研", "文献", "引用", "citation", "paper", "research", "zotero", "实验", "复现"],
    "learning": ["学习", "考试", "复习", "课程", "题目", "掌握", "exam", "learn", "quiz"],
    "office": ["会议", "纪要", "汇报", "报告", "ppt", "excel", "brief", "report", "meeting", "邮件", "表格", "办公", "文档", "docx", "calendar", "日历"],
    "project": ["代码", "项目", "git", "repo", "bug", "测试", "commit", "重构", "架构"],
    "web": ["搜索", "联网", "网页", "爬取", "url", "http", "search", "crawl", "fetch"],
}


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


def local_model_assets_status() -> dict[str, Any]:
    service = g_maintenance_service
    if not service:
        service = MaintenanceService(store=g_memory_store, db_path=MEMORY_DB, base_dir=BASE_DIR, config=config)
    return service.local_model_assets()


def get_workflow_engine() -> WorkflowEngine:
    global g_workflow_engine
    if not g_workflow_engine:
        g_workflow_engine = WorkflowEngine()
    return g_workflow_engine


def get_evaluation_service() -> EvaluationService:
    global g_evaluation_service
    output_root = OUTPUT_ROOT
    if (
        not g_evaluation_service
        or getattr(g_evaluation_service, "output_root", None) != output_root
        or getattr(g_evaluation_service, "store", None) is not g_memory_store
    ):
        g_evaluation_service = EvaluationService(output_root, g_memory_store)
    return g_evaluation_service


def get_agent_orchestration_service() -> AgentOrchestrationService:
    global g_agent_orchestration_service
    if (
        not g_agent_orchestration_service
        or getattr(g_agent_orchestration_service, "store", None) is not g_memory_store
    ):
        g_agent_orchestration_service = AgentOrchestrationService(get_workflow_engine(), g_memory_store)
    return g_agent_orchestration_service


def local_asr_capability() -> dict[str, Any]:
    model = os.environ.get("CLAWOS_ASR_MODEL", "small").strip() or "small"
    default_model_dir = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")) / "ClawOS" / "asr_models"
    model_dir = os.environ.get("CLAWOS_ASR_MODEL_DIR", str(default_model_dir)).strip()
    try:
        import faster_whisper  # noqa: F401
        faster_available = True
    except Exception:
        faster_available = False
    whisper_cli = shutil.which("whisper")
    whisper_cpp = shutil.which("whisper-cli") or shutil.which("main")
    return {
        "faster_whisper": faster_available,
        "whisper_cli": bool(whisper_cli),
        "whisper_cpp": bool(whisper_cpp),
        "available": bool(faster_available or whisper_cli or whisper_cpp),
        "preferred_engine": "faster-whisper" if faster_available else ("whisper.cpp" if whisper_cpp else ("whisper" if whisper_cli else "none")),
        "default_model": model,
        "model_dir": model_dir,
        "device": os.environ.get("CLAWOS_ASR_DEVICE", "cpu"),
        "compute_type": os.environ.get("CLAWOS_ASR_COMPUTE_TYPE", "int8"),
    }


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


def claim_runtime_task(worker_id: str = "worker", statuses: list[str] | None = None) -> dict[str, Any]:
    return get_task_service().claim(worker_id=worker_id, statuses=statuses)


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
    # Source review is a human decision, not a queue for repeated OCR. Even a
    # partially failed document may contain already-reviewed pages.
    queue = service.list_ocr_queue(category)
    pending = [doc for doc in queue if doc.get("status") not in {"needs_review", "ready_with_exclusions"}
               and not (doc.get("metadata") or {}).get("review_revision")][:limit]
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
        g_memory_store.add_message(session_id, "assistant", text)

# ---- UPSTREAM MODEL ----
async def proxy_upstream(req_data: dict, stream: bool, tool_context: str = "") -> JSONResponse:
    messages = req_data.get("messages", [])
    result = await call_model_with_fallback(
        "upstream",
        messages,
        {
            "temperature": req_data.get("temperature", 0.7),
            **({"model": req_data["model"]} if req_data.get("model") else {}),
            **({"max_tokens": req_data["max_tokens"]} if req_data.get("max_tokens") is not None else {}),
        }
    )
    public_result = {key: result.get(key) for key in (
        "ok", "provider", "model", "usage", "duration_ms", "error", "fallback_attempts"
    )}
    if not result["ok"]:
        body = build_openai_response(
            f"模型调用失败：{result['error']}",
            model=result.get("model"),
            extra={"model_result": public_result, "status": "failed"},
        )
        return sse_from_text(body["choices"][0]["message"]["content"], extra=body.get("clawos")) if stream else JSONResponse(body)
    body = build_openai_response(result["content"], model=result["model"], extra={"model_result": public_result})
    body["usage"] = result.get("usage", {})
    if stream:
        return sse_from_text(result["content"], extra=body.get("clawos"))
    return JSONResponse(body)

# ---- LIFESPAN ----
@asynccontextmanager
async def lifespan(app: FastAPI):
    from services.recovery_bundle import assert_workspace_complete
    assert_workspace_complete(DATA_DIR,MEMORY_DB)
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
    global g_runtime_policy_controller
    global g_paper_intelligence_service, g_scholarly_search_service
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
        chroma_dir = str((DATA_DIR / chroma_dir).resolve())
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
    g_vector_store.refresh(limit=8)  # Bound incremental work before serving HTTP.
    global g_document_index_worker
    from services.document_index_worker import DocumentIndexWorker
    g_document_index_worker = DocumentIndexWorker(g_memory_store,g_vector_store,batch_limit=32)
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
    from services.coding_context_service import CodingContextService
    g_context_builder = ContextBuilder(
        g_memory_store,
        g_vector_store,
        reranker=reranker,
        coding_context_service=CodingContextService(
            OUTPUT_ROOT / "coding" / "repository_index.json"
        ),
    )
    from policy_optimizer import PolicyOptimizer
    g_policy_optimizer = PolicyOptimizer(g_memory_store)
    from security import SecretManager, SecurityGrantStore, ToolSecurityPolicy
    g_security_policy = ToolSecurityPolicy(
        allowed_roots=[BASE_DIR.parent, DATA_DIR, OUTPUT_ROOT],
        grant_store=SecurityGrantStore(DATA_DIR / "security_policy.json"),
    )
    g_secret_manager = SecretManager(g_memory_store)
    g_security_service = SecurityService(g_security_policy, g_secret_manager, g_memory_store)
    g_task_service = TaskService(g_memory_store, action_handlers=worker_action_handlers())
    g_maintenance_service = MaintenanceService(store=g_memory_store, db_path=MEMORY_DB, base_dir=BASE_DIR, config=config)
    g_maintenance_service.apply_migrations()
    g_knowledge_service = KnowledgeService(g_memory_store, UPLOAD_DIR, lambda: g_vector_store.refresh() if g_vector_store else None)
    g_paper_intelligence_service = PaperIntelligenceService(g_memory_store)
    g_scholarly_search_service = ScholarlySearchService(DATA_DIR / "data" / "scholarly")
    from workspace_services import WorkspaceServices
    g_workspace_services = WorkspaceServices(g_memory_store, g_security_policy)
    from skills.skill_evolution import SkillEvolutionManager
    g_skill_evolution = SkillEvolutionManager(g_memory_store)
    from scenario_benchmarks import FrozenScenarioBenchmark
    g_scenario_benchmark = FrozenScenarioBenchmark(g_memory_store)
    from reflection.evolution_runtime import RuntimePolicyController
    g_runtime_policy_controller = RuntimePolicyController(g_memory_store)
    from services.sandbox_recovery import recover_pending
    sandbox_recovery = await asyncio.to_thread(recover_pending)
    logger.info('Sandbox restart recovery | recovered=%s blocked=%s active=%s',
                len(sandbox_recovery['recovered']),len(sandbox_recovery['blocked']),len(sandbox_recovery['active']))
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

    try:
        feishu_lc = start_feishu_long_connect()
        logger.info(
            "Feishu long-connect | started=%s reason=%s",
            feishu_lc.get("started"),
            feishu_lc.get("reason"),
        )
    except Exception as e:
        logger.warning(f"Feishu long-connect start skipped: {e}")

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
    g_document_index_worker.start()
    from services.research_watch import ResearchWatchWorker
    global g_research_watch_worker
    g_research_watch_worker = ResearchWatchWorker(_research_watch())
    g_research_watch_worker.start()
    from services.research_ai import ResearchAI, ResearchAIWorker
    global g_research_ai_worker
    g_research_ai_worker = ResearchAIWorker(ResearchAI(_research_watch()), _research_ai_model)
    g_research_ai_worker.start()
    global g_research_grounded_worker
    g_research_grounded_worker = ResearchAIWorker(_research_grounded(), _research_ai_model)
    g_research_grounded_worker.start()
    yield
    if g_vision_runtime is not None:
        await asyncio.to_thread(g_vision_runtime.close)
    await g_research_grounded_worker.close()
    await g_research_ai_worker.close()
    await g_research_watch_worker.close()
    await g_document_index_worker.close()
    try:
        stop_feishu_long_connect()
    except Exception:
        pass
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
    "/data-lab",
    "/meetings",
    "/assets/workbench.js",
    "/assets/workbench.css",
    "/",
    "/product",
    "/academy",
    "/academy/path",
    "/academy/paper",
    "/academy/code",
    "/academy/notes",
    "/academy/materials",
    "/academy/lab",
    "/assets/academy-lab.js",
    "/assets/academy-lab.css",
    "/academy/ingest",
    "/academy/quiz",
    "/console",
    "/assets/site.css",
    "/assets/site.js",
    "/assets/academy.js",
    "/assets/academy-documents.js",
    "/assets/academy-documents.css",
    "/assets/academy-pdf-pages.js",
    "/assets/academy-reader.css",
    "/assets/academy-materials.js",
    "/assets/academy-materials.css",
    "/assets/console.js",
}


@app.middleware("http")
async def no_cache_static_shell(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in NO_CACHE_STATIC_PATHS or request.url.path.startswith("/assets/console/") or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response

app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

# ---- ROUTES ----


# ---- MAIN ----


async def _evolution_json(request):
    if len(await request.body()) > 8 * 1024 * 1024:
        raise HTTPException(413, 'payload exceeds 8MiB')
    try:
        value = await request.json()
    except ValueError:
        raise HTTPException(400, 'valid JSON is required')
    if not isinstance(value, dict):
        raise HTTPException(400, 'JSON object is required')
    return value


def _competition_hardware_evidence() -> dict[str, Any]:
    path = OUTPUT_ROOT / "competition_hardware_acceptance.json"
    if not path.exists() or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _product_learning_readiness() -> dict[str, Any]:
    if not g_memory_store:
        return {}
    from agent_learning import AdvancedLearningReadiness
    return AdvancedLearningReadiness(g_memory_store).report()


from api.product_readiness import create_product_readiness_router

app.include_router(create_product_readiness_router(
    BASE_DIR.parent,
    OUTPUT_ROOT,
    learning_provider=_product_learning_readiness,
    hardware_provider=_competition_hardware_evidence,
))

from api.agent_product import create_agent_product_router

app.include_router(create_agent_product_router(
    lambda: g_memory_store,
    BASE_DIR.parent,
))


def _system_readiness_payload() -> dict[str, Any]:
    local_model = local_model_assets_status()
    checks = [
        {"id": "config_check", "label": "Configuration check API", "ok": bool(g_maintenance_service), "weight": 12},
        {"id": "migrations", "label": "SQLite migrations API", "ok": bool(g_maintenance_service), "weight": 10},
        {"id": "backup_restore", "label": "Backup and restore API", "ok": bool(g_maintenance_service), "weight": 14},
        {"id": "task_runtime", "label": "Task queue, cancel, retry, recover", "ok": bool(g_memory_store), "weight": 14},
        {"id": "worker_loop", "label": "Background worker control plane", "ok": bool(g_memory_store and get_task_service()), "weight": 12},
        {"id": "real_worker_jobs", "label": "Report, OCR queue, batch document jobs", "ok": set(worker_action_handlers()) >= {"generate_report", "process_ocr_queue", "batch_ingest_documents"}, "weight": 16},
        {"id": "security_audit", "label": "Security policy and audit center", "ok": bool(g_security_policy and g_memory_store), "weight": 10},
        {"id": "local_model_assets", "label": "Local Qwen model assets and llama.cpp runtime", "ok": bool(local_model.get("ready")), "weight": 12, "detail": local_model.get("summary", "")},
        {"id": "knowledge_ops", "label": "Knowledge graph, Obsidian, OCR operations", "ok": bool(g_memory_store and get_knowledge_service()), "weight": 12},
    ]
    total = sum(int(item["weight"]) for item in checks)
    passed = sum(int(item["weight"]) for item in checks if item["ok"])
    score = round(passed / total, 4) if total else 0
    return {
        "score": score,
        "percent": round(score * 100, 1),
        "standard": "single-user enterprise ops readiness",
        "enterprise_ready": score >= 0.9,
        "local_model_assets": local_model,
        "checks": checks,
        "remaining": [item for item in checks if not item["ok"]],
    }


# ==========================================================================
# §13 Feishu connector API — resource-style endpoints with strict Pydantic
# request models. Handlers keep the (request: Request) signature and validate
# the JSON body through the models internally, so the legacy direct-call test
# harness still works while the contract is strict (no loose dict.get on writes).
# ==========================================================================
from pydantic import ValidationError
from api.request_models import FeishuSummaryCreate, FeishuSummaryUpdate, FeishuApprovalCreate, FeishuApprovalSend
  # noqa: E402


def _feishu_service():
    """Resolve the connector service; 503 only if it is genuinely absent.

    We deliberately do NOT 503 on a merely-unconfigured connector: the
    whitelist / approval gates own their own 409 decisions, and the v2 red-light
    tests exercise those gates from an unconfigured-but-operational service.
    """
    svc = get_feishu_connector_service()
    if svc is None:
        raise HTTPException(503, "feishu connector not available")
    return svc


def _learning_product():
    from services.learning_product_service import LearningProductService

    if g_memory_store is None:
        raise HTTPException(503, "MemoryOS not initialized")
    return LearningProductService(g_memory_store)


def _academy_materials():
    from services.academy_materials import AcademyMaterials, digest
    profile=digest(dict(routing=config.get('routing',{}),llm=config.get('llm',{})))
    return AcademyMaterials(_learning_product().store, OUTPUT_ROOT / "academy-materials", profile)


async def _academy_material_model(messages, tools, **options):
    if options:
        result=await call_model_with_fallback('routing',messages,dict(options,tools=tools))
        if not result['ok']:raise RuntimeError(result['error'])
        raw=dict(result['raw'])
        raw['clawos_model']={k:result.get(k) for k in ('provider','model','usage','duration_ms','fallback_attempts')}
        return raw
    return await call_routing_llm(messages, tools)


from services.academy_material_api import materials_router
app.include_router(materials_router(_academy_materials, _academy_material_model))
from services.academy_learning_lab import AcademyLearningLab
from services.academy_lab_api import lab_router

def _academy_lab():
    return AcademyLearningLab(_academy_materials())

app.include_router(lab_router(_academy_lab, _academy_material_model))


from services.academy_documents import AcademyDocuments, documents_router
from starlette.concurrency import run_in_threadpool
from services.collaboration import Collaboration, collaboration_router, direct_owner
from services.data_lab import DataLab, data_lab_router
from services.meeting_workbench import MeetingWorkbench, meeting_router

_workbench_cache = {}
def _workbench_service(kind):
    store = _learning_product().store
    key = (kind,id(store))
    if key not in _workbench_cache:
        if kind == 'collaboration':
            AcademyDocuments(store)
            service = Collaboration(store)
        elif kind == 'data': service = DataLab(store)
        else: service = MeetingWorkbench(g_workspace_services)
        _workbench_cache[key] = service
    return _workbench_cache[key]

def _collaboration(): return _workbench_service('collaboration')
app.include_router(documents_router(lambda: AcademyDocuments(_learning_product().store), _academy_material_model, _collaboration))
app.include_router(collaboration_router(_collaboration))
app.include_router(data_lab_router(lambda: _workbench_service('data'), _collaboration))
app.include_router(meeting_router(lambda: _workbench_service('meeting'), _collaboration, lambda: _feishu_service()))

def _research_watch():
    from services.research_watch import ResearchWatch
    global g_research_watch_service
    if g_research_watch_service is None or g_research_watch_service.store is not g_memory_store:
        if not g_memory_store:
            raise HTTPException(503, '研究订阅存储尚未初始化')
        g_research_watch_service = ResearchWatch(g_memory_store)
    return g_research_watch_service

def _research_watch_worker_status():
    worker = g_research_watch_worker
    return {'running': bool(worker and worker.task and not worker.task.done()),
            'last_error': worker.last_error if worker else '', 'check_seconds': 15}

from services.research_watch_api import research_watch_router

def _research_ai_ready():
    from urllib.parse import urlsplit
    provider=g_routing_provider
    local=bool(provider and urlsplit(getattr(provider,'base_url','')).hostname in ('127.0.0.1','localhost','::1'))
    running=bool(g_research_ai_worker and g_research_ai_worker.task and not g_research_ai_worker.task.done())
    reason=('本地模型已配置，实际连通性在调用时验证。' if local and running else '当前未配置本地模型。' if not local else '后台综合服务未运行，请在正常启动应用后重试。')
    return dict(ready=bool(local and running and provider.is_configured()),local_only=True,worker_running=running,
                model=str(getattr(provider,'model','')).replace('\\','/').rsplit('/',1)[-1] if local else '',reason=reason+'不进行外部回退；不代表已通过学术质量验收。')

async def _research_ai_model(messages, tools, **options):
    if not _research_ai_ready()['ready']:raise RuntimeError('local_model_not_ready')
    provider=g_routing_provider
    result=await provider.complete(messages,dict(options,tools=[]),http_client=http_client)
    if not result['ok']:raise RuntimeError('local_model_request_failed')
    raw=dict(result['raw']);raw['clawos_model']={k:result.get(k) for k in ('provider','model','usage','duration_ms')}
    return raw

app.include_router(research_watch_router(_research_watch, _collaboration, _research_watch_worker_status, _research_ai_ready))


from services.vision_api import vision_router
g_vision_runtime = None

def _vision_runtime():
    global g_vision_runtime
    if g_vision_runtime is None:
        from services.vision_runtime import VisionRuntime
        g_vision_runtime = VisionRuntime(DATA_DIR / 'vision')
    return g_vision_runtime

from functools import lru_cache

@lru_cache(maxsize=1)
def _vision_teaching():
    from services.vision_teaching import VisionTeaching
    return VisionTeaching(DATA_DIR / 'vision' / 'teaching.sqlite', lab=_academy_lab)

def _research_learning():
    from services.research_learning import ResearchLearning
    return ResearchLearning(_research_watch(), DATA_DIR / 'research-learning')

g_research_grounded_worker = None

def _research_journey():
    from services.research_journey import ResearchJourney
    from services.research_journey_import import import_capture
    def importer(paper,raw):
        return import_capture(paper,raw,store=g_memory_store,upload_dir=UPLOAD_DIR,materials=_academy_materials(),
            staging=DATA_DIR/'research-learning'/'import-staging',refresh=g_vector_store.refresh if g_vector_store else None)
    return ResearchJourney(_research_learning(),importer=importer)

def _research_grounded():
    from services.research_grounded import ResearchGrounded
    return ResearchGrounded(_research_learning())

def _research_grounded_ready():
    status=_research_ai_ready()
    running=bool(g_research_grounded_worker and g_research_grounded_worker.task and not g_research_grounded_worker.task.done())
    return dict(status,ready=status['ready'] and running,worker_running=running)

app.include_router(vision_router(_vision_runtime, _collaboration, STATIC_DIR / 'vision', teaching=_vision_teaching,research=_research_learning,
    journey=_research_journey,grounded=_research_grounded,model_ready=_research_grounded_ready))

@app.middleware('http')
async def workbench_access(request: Request, call_next):
    path = request.url.path
    if path.startswith(('/api/','/v1/')) and path not in ('/api/collaboration/join','/api/academy/learning/lab/join','/api/academy/learning/lab/logout','/api/feishu/events'):
        try:
            uid = 'local-user' if direct_owner(request) else await run_in_threadpool(lambda: _collaboration().identity(request)['id'])
            if uid != 'local-user' and not path.startswith(('/api/collaboration/','/api/academy/learning/documents','/api/evolution-review/','/api/academy/learning/lab/','/api/research/watch')):
                raise HTTPException(403, '协作会话仅允许访问授权文档')
        except HTTPException as e:
            return JSONResponse({'detail':e.detail},status_code=e.status_code)
    if request.method not in ('GET','HEAD','OPTIONS') and path != '/api/feishu/events':
        origin = request.headers.get('origin')
        from urllib.parse import urlsplit
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and (urlsplit(origin).netloc != request.url.netloc or urlsplit(origin).scheme != request.url.scheme)):
            return JSONResponse({'detail':'拒绝跨站写入'},status_code=403)
    return await call_next(request)


def _rag_workshop():
    from services.academy_rag_workshop import RagWorkshop
    return RagWorkshop(_learning_product().store)


def get_document_index_worker():
    global g_document_index_worker
    if not g_memory_store or not g_vector_store:raise HTTPException(503,'Document index not initialized')
    if g_document_index_worker is None or g_document_index_worker.store is not g_memory_store or g_document_index_worker.vector is not g_vector_store:
        from services.document_index_worker import DocumentIndexWorker
        g_document_index_worker=DocumentIndexWorker(g_memory_store,g_vector_store,batch_limit=32)
    return g_document_index_worker


def get_knowledge_service() -> KnowledgeService:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    global g_knowledge_service
    if not g_knowledge_service or getattr(g_knowledge_service, "store", None) is not g_memory_store:
        g_knowledge_service = KnowledgeService(g_memory_store, UPLOAD_DIR, lambda: g_vector_store.refresh() if g_vector_store else None)
    return g_knowledge_service


def get_paper_intelligence_service() -> PaperIntelligenceService:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    global g_paper_intelligence_service
    if not g_paper_intelligence_service or getattr(g_paper_intelligence_service, "store", None) is not g_memory_store:
        g_paper_intelligence_service = PaperIntelligenceService(g_memory_store)
    return g_paper_intelligence_service


def get_scholarly_search_service() -> ScholarlySearchService:
    global g_scholarly_search_service
    if not g_scholarly_search_service:
        g_scholarly_search_service = ScholarlySearchService(DATA_DIR / "data" / "scholarly")
    return g_scholarly_search_service


def get_coding_workflow_service() -> CodingWorkflowService:
    global g_coding_workflow_service
    if not g_coding_workflow_service or getattr(g_coding_workflow_service, "store", None) is not g_memory_store:
        g_coding_workflow_service = CodingWorkflowService(g_memory_store, OUTPUT_ROOT / "coding")
    return g_coding_workflow_service


def get_office_productivity_service() -> OfficeProductivityService:
    global g_office_productivity_service
    if not g_office_productivity_service or getattr(g_office_productivity_service, "store", None) is not g_memory_store:
        roots = list(getattr(g_security_policy, "allowed_roots", ()) or [BASE_DIR.parent])
        g_office_productivity_service = OfficeProductivityService(g_memory_store, roots, preview_root=OUTPUT_ROOT)
    return g_office_productivity_service


def get_artifact_delivery_service() -> ArtifactDeliveryService:
    roots = list(getattr(g_security_policy, "allowed_roots", ()) or [])
    roots.extend([BASE_DIR.parent, DATA_DIR, OUTPUT_ROOT])
    return ArtifactDeliveryService(
        OUTPUT_ROOT / "artifact_delivery" / "index.json",
        list(dict.fromkeys(str(Path(item).resolve()) for item in roots)),
    )


def collect_deliverable_artifacts(tool_calls: list[dict[str, Any]], task_id: Any = None) -> list[dict[str, Any]]:
    try:
        return get_artifact_delivery_service().collect(tool_calls, task_id=task_id)
    except (OSError, ValueError) as exc:
        if logger:
            logger.warning("Artifact delivery collection failed: %s", exc)
        return []


def get_feishu_connector_service() -> Any:
    global g_feishu_connector_service
    if not g_feishu_connector_service or getattr(g_feishu_connector_service, "store", None) is not g_memory_store:
        cfg = load_feishu_config()
        client = FeishuClient(cfg) if cfg.live else None
        g_feishu_connector_service = FeishuConnectorService(g_memory_store, client, cfg)
    return g_feishu_connector_service


def start_feishu_long_connect() -> dict:
    """Start the official long-connection only when the connector is live and
    ready. With FEISHU_LIVE=false (default) this stays dormant and returns the
    reason, so no real tenant connection is ever opened without authorization.

    Returns a small status dict for logging / health.
    """
    global g_feishu_long_connect
    from services.feishu.config import EVENT_MODE_LONG_CONNECTION
    from services.feishu.long_connect import (
        FeishuLongConnectError,
        FeishuLongConnectManager,
    )

    service = get_feishu_connector_service()
    cfg = service.config
    if not cfg.live:
        return {"started": False, "reason": "FEISHU_LIVE is false (dormant)"}
    if cfg.event_mode != EVENT_MODE_LONG_CONNECTION:
        return {"started": False, "reason": f"event_mode={cfg.event_mode}"}
    ready, missing = cfg.live_readiness()
    if not ready:
        return {"started": False, "reason": f"missing config: {','.join(missing)}"}

    def _on_message(event: dict) -> None:
        try:
            service.receive_event(event, received_via="long_connect")
        except Exception:
            # Non-whitelist / duplicate / validation errors must not drop the link.
            pass

    if g_feishu_long_connect is None:
        g_feishu_long_connect = FeishuLongConnectManager(cfg, _on_message)
    try:
        g_feishu_long_connect.start()
    except FeishuLongConnectError as exc:
        return {"started": False, "reason": str(exc)}
    return {"started": g_feishu_long_connect.running, "reason": "ok"}


def stop_feishu_long_connect() -> None:
    global g_feishu_long_connect
    if g_feishu_long_connect is not None:
        try:
            g_feishu_long_connect.stop()
        except Exception:
            pass
        g_feishu_long_connect = None


def get_autonomous_subagent_service() -> AutonomousSubagentService:
    if not g_upstream_provider:
        raise HTTPException(503, "model provider is not initialized")

    async def execute(name: str, arguments: dict[str, Any], context: dict[str, Any]):
        confirmed = set(context.get("confirmed_tools") or [])
        return await asyncio.to_thread(
            execute_tool_call,
            name,
            json.dumps(arguments, ensure_ascii=False),
            f"subagent-{context.get('role_id', 'role')}",
            confirmed,
        )

    return AutonomousSubagentService(
        lambda _spec: g_upstream_provider,
        tool_executor=execute,
        tool_definitions=tools_def,
        store=g_memory_store,
        checkpoint_root=OUTPUT_ROOT / "subagents",
        max_concurrency=3,
    )


def get_reliable_collaboration_service(*, require_model=True):
    from services.reliable_collaboration import ReliableCollaborationService
    if require_model and not g_upstream_provider:
        raise HTTPException(503, "model provider is not initialized")
    return ReliableCollaborationService(lambda _spec: g_upstream_provider,
        root=OUTPUT_ROOT / "collaboration-runs", store=g_memory_store, max_concurrency=3)


def _academy_count_run_records(run_type: str, document_id: int = 0) -> int:
    if not g_memory_store:
        return 0
    count = 0
    for item in g_memory_store.list_run_records(run_type=run_type, limit=200):
        run = g_memory_store.get_run_record(item.get("run_id", ""))
        inputs = run.get("inputs") or {}
        if document_id and int(inputs.get("document_id") or 0) != int(document_id):
            continue
        count += 1
    return count


def _academy_offline_audit_payload(document_id: int = 0) -> dict[str, Any]:
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    documents = g_memory_store.list_documents("research")
    active_document = g_memory_store.get_document(document_id) if document_id else (documents[0] if documents else {})
    active_document_id = int((active_document or {}).get("id") or document_id or 0)
    chunk_count = len(g_memory_store.get_document_chunks(active_document_id, 100)) if active_document_id else 0
    knowledge_items = g_memory_store.list_knowledge("research")
    local_model = local_model_assets_status()
    report_count = _academy_count_run_records("academy_paper_report", active_document_id)
    checkpoint_count = _academy_count_run_records("academy_paper_checkpoint", active_document_id)
    project_item_count = _academy_count_run_records("academy_research_project_item", active_document_id)
    project_export_count = _academy_count_run_records("academy_research_project_export", active_document_id)
    checks = [
        {"id": "local_model_assets", "label": "Local 8B/9B model assets", "ok": bool(local_model.get("ready")), "detail": local_model.get("summary", "")},
        {"id": "document_ingestion", "label": "Research document ingestion", "ok": bool(active_document_id and chunk_count > 0), "detail": f"doc:{active_document_id or 0} chunks:{chunk_count}"},
        {"id": "report_generation", "label": "Local report run recorded", "ok": report_count > 0, "detail": f"reports:{report_count}"},
        {"id": "knowledge_capture", "label": "Research knowledge captured", "ok": len(knowledge_items) > 0, "detail": f"research knowledge:{len(knowledge_items)}"},
        {"id": "evidence_search", "label": "Citation evidence search ready", "ok": bool(get_knowledge_service() and chunk_count > 0), "detail": f"searchable chunks:{chunk_count}"},
        {"id": "checkpoints", "label": "Paper checkpoint available", "ok": checkpoint_count > 0, "detail": f"checkpoints:{checkpoint_count}"},
        {"id": "project_board", "label": "Project board items", "ok": project_item_count > 0, "detail": f"items:{project_item_count}"},
        {"id": "project_packages", "label": "Offline project package export", "ok": project_export_count > 0, "detail": f"packages:{project_export_count}"},
    ]
    passed = sum(1 for item in checks if item["ok"])
    return {
        "ok": passed == len(checks),
        "percent": round((passed / len(checks)) * 100, 1) if checks else 0,
        "standard": "local-first research workflow readiness",
        "document": active_document or {},
        "counts": {
            "research_documents": len(documents),
            "chunks": chunk_count,
            "research_knowledge": len(knowledge_items),
            "reports": report_count,
            "checkpoints": checkpoint_count,
            "project_items": project_item_count,
            "project_packages": project_export_count,
        },
        "local_model_assets": local_model,
        "checks": checks,
        "remaining": [item for item in checks if not item["ok"]],
    }


async def _local_qwen_smoke_check(http_client: Any = None, timeout_s: float = 20.0) -> dict[str, Any]:
    assets = local_model_assets_status()
    provider = create_model_provider({
        "provider": "qwen",
        "base_url": os.environ.get("QWEN_BASE_URL", "http://127.0.0.1:8000/v1"),
        "model": os.environ.get("QWEN_MODEL", "Qwen3.5-9B-Q4_K_M"),
        "requires_api_key": False,
        "timeout_s": timeout_s,
    })
    result = await provider.complete(
        [
            {"role": "system", "content": "You are a local ClawOS smoke-test model. Reply with exactly: LOCAL_OK"},
            {"role": "user", "content": "offline local model smoke check"},
        ],
        {"temperature": 0.0, "max_tokens": 16},
        http_client=http_client,
    )
    content = str(result.get("content") or "").strip()
    ok = bool(result.get("ok") and content)
    return {
        "ok": ok,
        "provider": "qwen",
        "model": getattr(provider, "model", ""),
        "base_url": getattr(provider, "base_url", ""),
        "configured": bool(provider.is_configured()) if hasattr(provider, "is_configured") else True,
        "assets_ready": bool(assets.get("ready")),
        "assets_summary": assets.get("summary", ""),
        "duration_ms": result.get("duration_ms", 0),
        "error": "" if ok else str(result.get("error") or "empty_response"),
        "content_preview": content[:80],
    }


def get_document_review_service():
    from services.document_review_service import DocumentReviewService
    if not g_memory_store:
        raise HTTPException(503, "MemoryOS not initialized")
    return DocumentReviewService(g_memory_store, [UPLOAD_DIR, DATA_DIR, OUTPUT_ROOT])


from services.pdf_page_renderer import PdfPageRenderer
_pdf_page_renderer=PdfPageRenderer()


def resolve_obsidian_output_dir(requested: str = "", category: str = "") -> Path:
    output_root = (OUTPUT_ROOT / "obsidian").resolve()
    requested = str(requested or "").strip()
    if requested:
        raw = Path(requested).expanduser()
        if raw.is_absolute():
            output_dir = raw.resolve()
        elif raw.parts[:2] == ('output','obsidian'):
            output_dir = (output_root / Path(*raw.parts[2:])).resolve()
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


def background_worker_status() -> dict[str, Any]:
    task = g_background_worker_task
    state = dict(g_background_worker_status)
    state["running"] = bool(task and not task.done())
    state["done"] = bool(task.done()) if task else True
    return state


async def start_background_worker(data: dict[str, Any]):
    global g_background_worker_task
    if g_background_worker_task and not g_background_worker_task.done():
        return {"ok": True, "already_running": True, **g_background_worker_status}
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
    return {"ok": True, "started": True, "worker_id": worker_id}


async def stop_background_worker():
    global g_background_worker_task
    task = g_background_worker_task
    if not task or task.done():
        g_background_worker_status["running"] = False
        return {"ok": True, "stopped": False, **g_background_worker_status}
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    g_background_worker_task = None
    g_background_worker_status["running"] = False
    return {"ok": True, "stopped": True, **g_background_worker_status}


def main():
    parser = argparse.ArgumentParser(description="ClawOS Agent")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18790)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


# Legacy Python handler names remain available during the domain migration.
from application.routing import register_domain_routes
_domain_handlers = register_domain_routes(app, sys.modules[__name__])


def __getattr__(name):
    try:
        return _domain_handlers[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

_tool_service = _domain_handlers['_tool_service']
call_model_with_fallback = _domain_handlers['call_model_with_fallback']
classify_scenario = _domain_handlers['classify_scenario']
score_scenarios = _domain_handlers['score_scenarios']
build_routing_strategy = _domain_handlers['build_routing_strategy']
apply_web_search_policy = _domain_handlers['apply_web_search_policy']
web_search_prompt_policy = _domain_handlers['web_search_prompt_policy']
execute_coding_agent_call = _domain_handlers['execute_coding_agent_call']
tool_result_for_model = _domain_handlers['tool_result_for_model']
resolve_runtime_policies = _domain_handlers['resolve_runtime_policies']
runtime_policy_trace = _domain_handlers['runtime_policy_trace']
evaluate_shadow_policies = _domain_handlers['evaluate_shadow_policies']
tools_for_routing_strategy = _domain_handlers['tools_for_routing_strategy']
rule_based_tool = _domain_handlers['rule_based_tool']
run_tool_loop = _domain_handlers['run_tool_loop']
build_openai_response = _domain_handlers['build_openai_response']
extract_assistant_text = _domain_handlers['extract_assistant_text']


if __name__ == "__main__":
    main()
