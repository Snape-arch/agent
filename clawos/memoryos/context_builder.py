"""ContextBuilder — assembles rich system prompt from MemoryOS data."""

import json
from typing import Any

from .memory_store import MemoryStore
from .services.ingestion import IngestionService
from .services.retrieval import RetrievalService
from .services.evaluation import EvaluationService


class ContextBuilder:
    """Build contextual system prompt from full MemoryOS pipeline."""

    def __init__(self, store: MemoryStore):
        self._store = store
        self._ingestion = IngestionService(store)
        self._retrieval = RetrievalService(store)
        self._evaluation = EvaluationService(store)

    def build_system_prompt(self, session_id: str) -> str:
        """Construct system prompt enriched with 7 memory types and retrieved knowledge."""
        parts = ["You are ClawOS, a personal AI agent. Environment: Windows 11, user: 34712, desktop: C:/Users/34712/Desktop. ALWAYS use correct Windows paths. For file_write use desktop path unless user specifies otherwise."]

        # ── PROFILE ──
        profiles = self._store.get_all_profiles()
        if profiles:
            by_cat = {}
            for p in profiles:
                by_cat.setdefault(p.get("category", "general"), []).append(p)
            for cat, items in by_cat.items():
                lines = [f"  {i['key']}: {i['value']}" for i in items[:5]]
                parts.append(f"Profile ({cat}):\n" + "\n".join(lines))

        # ── PREFERENCES ──
        prefs = self._store.get_all_preferences()
        if prefs:
            high_conf = [p for p in prefs if p.get("confidence", 0) >= 0.5]
            if high_conf:
                lines = [f"  {p['key']}: {p['value']}" for p in high_conf[:8]]
                parts.append("Preferences:\n" + "\n".join(lines))

        # ── KNOWLEDGE ──
        knowledge = self._store.list_knowledge()
        if knowledge:
            top_k = sorted(knowledge, key=lambda k: k.get("access_count", 0), reverse=True)[:3]
            if top_k:
                klines = [f"  [{k.get('category','')}] {k.get('title','')}" for k in top_k]
                parts.append("Key Knowledge:\n" + "\n".join(klines))

        # ── EXPERIENCES ──
        exps = self._store.get_recent_experiences(3)
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
            "For file creation ALWAYS use file_write tool, NEVER describe creating a file in text. "
            "For running commands ALWAYS use shell_exec tool, NEVER fake command output. "
            "For memory operations ALWAYS use the tool, NEVER invent profile data. "
            "For skill operations ALWAYS use skill tools. "
            "Never claim to have done something unless you actually called the tool. "
            "Be concise. "
            "Reply ONLY in Chinese if user writes in Chinese, ONLY in English if English. "
            "Never mix languages in one response. Never invent tool names. "
            "If shell_exec fails, report it honestly. "
            "Follow stored preferences. Do not use emojis."
        )

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

    def build_messages(self, session_id: str, user_text: str, max_history: int = 12) -> list[dict[str, Any]]:
        """Build messages array with full memory pipeline: profile + knowledge + retrieval + history."""
        system = self.build_system_prompt(session_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

        # Inject conversation history
        history = self._store.get_recent_messages(session_id, max_history * 2)
        history = [m for m in history if m["role"] in ("user", "assistant")]
        history = history[-(max_history - 1):]
        for m in history:
            messages.append({"role": m["role"], "content": m.get("content", "")[:4000]})

        messages.append({"role": "user", "content": user_text})
        return messages

    def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """Run the full retrieval pipeline."""
        return self._retrieval.retrieve(query, top_k)
