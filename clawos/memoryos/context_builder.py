"""ContextBuilder — assembles rich system prompt from MemoryOS data."""

import json
import os
from pathlib import Path
from typing import Any

from .memory_store import MemoryStore
from .services.ingestion import IngestionService
from .services.retrieval import RetrievalService
from .services.evaluation import EvaluationService
from .services.management import ManagementService
from services.response_contract import SYSTEM_PROMPT, RESPONSE_STYLE, request_history


class ContextBuilder:
    """Build contextual system prompt from full MemoryOS pipeline."""

    def __init__(
        self, store: MemoryStore, vector_store=None, reranker=None,
        coding_context_service=None,
    ):
        self._store = store
        self._ingestion = IngestionService(store)
        self._retrieval = RetrievalService(store, vector_store, reranker=reranker)
        self._evaluation = EvaluationService(store)
        self._coding_context = coding_context_service

    def build_system_prompt(self, session_id: str, prompt_policy: dict | None = None, owner_id="default", workspace_id="default") -> str:
        """Construct system prompt enriched with 7 memory types and retrieved knowledge."""
        user_profile = os.environ.get("USERPROFILE", "")
        desktop = os.path.join(user_profile, "Desktop") if user_profile else ""
        parts = [
            SYSTEM_PROMPT + " "
            f"Environment: Windows, user_profile: {user_profile or 'unknown'}, desktop: {desktop or 'unknown'}. "
            "Use correct Windows paths and the configured output workspace unless the user supplies a permitted path."
        ]

        legacy_scope = owner_id == "default" and workspace_id == "default"
        memories = self._store.list_memories(include_disabled=False, limit=20, actor_id=owner_id, workspace_id=workspace_id)
        memories = [m for m in memories if m.get("owner_id", "default")==owner_id and m.get("workspace_id", "default")==workspace_id]
        if memories:
            by_type = {}
            for item in memories:
                by_type.setdefault(item.get("memory_type", "memory"), []).append(item)
            lines = []
            for memory_type in ("profile", "preference", "project", "experience", "skill"):
                for item in by_type.get(memory_type, [])[:5]:
                    lines.append(f"  [{memory_type}] {item.get('key','')}: {item.get('value','')}")
            if lines:
                parts.append("Long-term MemoryOS records:\n" + "\n".join(lines))

        # ── PROFILE ──
        profiles = self._store.get_all_profiles() if legacy_scope else []
        if profiles:
            by_cat = {}
            for p in profiles:
                by_cat.setdefault(p.get("category", "general"), []).append(p)
            for cat, items in by_cat.items():
                lines = [f"  {i['key']}: {i['value']}" for i in items[:5]]
                parts.append(f"Profile ({cat}):\n" + "\n".join(lines))

        # ── PREFERENCES ──
        prefs = self._store.get_all_preferences() if legacy_scope else []
        if prefs:
            high_conf = [p for p in prefs if p.get("confidence", 0) >= 0.5]
            if high_conf:
                lines = [f"  {p['key']}: {p['value']}" for p in high_conf[:8]]
                parts.append("Preferences:\n" + "\n".join(lines))

        # ── KNOWLEDGE ──
        knowledge = self._store.list_knowledge() if legacy_scope else []
        if knowledge:
            top_k = sorted(knowledge, key=lambda k: k.get("access_count", 0), reverse=True)[:3]
            if top_k:
                klines = [f"  [{k.get('category','')}] {k.get('title','')}" for k in top_k]
                parts.append("Key Knowledge:\n" + "\n".join(klines))

        # ── EXPERIENCES ──
        exps = self._store.get_recent_experiences(3) if legacy_scope else []
        if exps:
            elines = []
            for e in exps:
                elines.append(f"  {e.get('outcome','')}: {e.get('task','')[:80]} -> {e.get('lesson','')[:80]}")
            parts.append("Recent Experiences:\n" + "\n".join(elines))

        # ── SESSION CONTEXT ──
        summary = self._store.get_session_summary(session_id)
        ctx = self._store.get_latest_context(session_id)
        if ctx:
            task = ctx.get("task_description", "")
            intent = ctx.get("user_intent", "")
            if task or intent:
                parts.append(f"Current context: task='{task}', intent='{intent}'")
        if summary:
            parts.append(summary)

        # ── BEHAVIOR RULES ──
        parts.append(
            "IMPORTANT: You MUST call the appropriate tool for file operations, system commands, searches, and data management. "
            "For file creation use the appropriate artifact or file tool; do not merely describe creating a file. "
            "For running commands ALWAYS use shell_exec tool, NEVER fake command output. "
            "For memory operations ALWAYS use the tool, NEVER invent profile data. "
            "For skill operations ALWAYS use skill tools. "
            "Never claim to have done something unless you actually called the tool. "
            "Be concise. "
            "Reply ONLY in Chinese if user writes in Chinese, ONLY in English if English. "
            "Keep code, technical terms and source titles intact. Never invent tool names. "
            "If shell_exec fails, report it honestly. "
            "Follow stored preferences. Do not use emojis."
        )

        policy = dict(prompt_policy or {})
        addition = str(policy.get("system") or policy.get("prompt") or "").strip()
        if addition:
            parts.append("[Active runtime prompt policy]\n" + addition)
        parts.append(RESPONSE_STYLE)
        return "\n\n".join(parts)

    def ingest_and_store(self, session_id: str, role: str, content: str):
        """Ingest a conversation turn: store in DB + extract profiles/prefs."""
        self._store.add_message(session_id, role, content)
        extracted = self._ingestion.ingest_conversation(session_id, role, content)
        return extracted

    def save_context(self, session_id: str, task: str = "", tools: list | None = None,
                     environment: str = "", intent: str = ""):
        """Save a context snapshot for the current session."""
        self._store.save_context_snapshot(session_id, task, tools, environment, intent)

    def build_messages(
        self,
        session_id: str,
        user_text: str,
        max_history: int = 12,
        prompt_policy: dict | None = None,
        retrieval_policy: dict | None = None,
        repo_path: str = "",
        focus_paths: list[str] | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        coding_token_budget: int = 12000,
        total_token_budget: int = 32000,
        conversation_messages: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages array with full memory pipeline: profile + knowledge + retrieval + history."""
        message_count = len(
            self._store.get_session_messages(session_id, limit=101)
        )
        if message_count > max(40, max_history * 4):
            ManagementService(self._store).compact_conversation(
                session_id, keep_recent=max(20, max_history * 2)
            )
        scope = dict(retrieval_policy or {})
        system = self.build_system_prompt(session_id, prompt_policy=prompt_policy, owner_id=str(scope.get("owner_id") or "default"), workspace_id=str(scope.get("workspace_id") or "default"))
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

        context_retrieval_policy = dict(retrieval_policy or {})
        context_retrieval_policy.setdefault("session_id", session_id)
        retrieved = self._retrieval.retrieve_for_context(
            user_text, policy=context_retrieval_policy
        )
        if retrieved:
            messages.append({
                "role": "system",
                "content": retrieved + "\nUse only relevant records. Ignore stale or unrelated memory.",
            })

        resolved_repo = self._resolve_repo(repo_path, focus_paths or [])
        if resolved_repo:
            try:
                service = self._coding_context
                if service is None:
                    from services.coding_context_service import CodingContextService
                    service = CodingContextService()
                    self._coding_context = service
                context_pack = service.build(
                    resolved_repo,
                    user_text,
                    focus_paths=focus_paths,
                    diagnostics=diagnostics,
                    token_budget=coding_token_budget,
                )
                messages.append({
                    "role": "system",
                    "content": service.render_for_prompt(context_pack),
                    "clawos_context": {
                        "schema": context_pack.get("schema"),
                        "digest": context_pack.get("context_digest"),
                        "repo": context_pack.get("repo"),
                        "budget": context_pack.get("budget"),
                    },
                })
            except (OSError, RuntimeError, ValueError) as exc:
                messages.append({
                    "role": "system",
                    "content": (
                        "[ClawOS repository context unavailable]\n"
                        f"{type(exc).__name__}: {exc}\n"
                        "Do not assume repository state that was not provided."
                    ),
                })

        # Inject conversation history
        explicit = request_history(conversation_messages)
        history = explicit if explicit is not None else self._store.get_recent_messages(session_id, max_history * 2)
        history = [m for m in history if m["role"] in ("user", "assistant")]
        history = history[-(max_history - 1):]
        current_text = next((m.get("content") for m in reversed(conversation_messages or [])
                             if m.get("role") == "user"), user_text)
        if history and history[-1]["role"] == "user" and history[-1].get("content", "") in (user_text, current_text):
            history = history[:-1]
        for m in history:
            messages.append({"role": m["role"], "content": m.get("content", "")})

        messages.append({"role": "user", "content": user_text})
        return self._fit_global_budget(messages, total_token_budget)

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Run the full retrieval pipeline."""
        return self._retrieval.retrieve(query, top_k)

    @staticmethod
    def _resolve_repo(repo_path: str, focus_paths: list[str]) -> str:
        candidates = [repo_path, *focus_paths]
        for raw in candidates:
            if not raw:
                continue
            path = Path(raw).expanduser().resolve()
            if path.is_file():
                path = path.parent
            for candidate in (path, *path.parents):
                if (candidate / ".git").exists():
                    return str(candidate)
        return ""

    @staticmethod
    def _fit_global_budget(
        messages: list[dict[str, Any]], token_budget: int
    ) -> list[dict[str, Any]]:
        # Conservative four characters per token. Preserve the current user
        # request and trim oldest non-system history before trusted context.
        limit = max(4_000, min(int(token_budget), 128_000)) * 4
        result = [dict(item) for item in messages]
        while sum(len(str(item.get("content") or "")) for item in result) > limit:
            removable = next(
                (index for index, item in enumerate(result[1:-1], 1)
                 if item.get("role") != "system"),
                None,
            )
            if removable is not None:
                result.pop(removable)
                continue
            longest = max(
                range(len(result) - 1),
                key=lambda index: len(str(result[index].get("content") or "")),
            )
            content = str(result[longest].get("content") or "")
            if len(content) <= 1000:
                break
            result[longest]["content"] = content[: max(1000, len(content) // 2)]
        return result
