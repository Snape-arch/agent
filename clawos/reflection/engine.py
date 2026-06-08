"""ReflectionEngine - orchestrates the entire reflection pipeline."""
import json, time, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class ReflectionEngine:
    """Orchestrates: Trigger -> Perceive -> Analyze -> Store -> Apply."""

    TRIGGERS = ["task_completed", "failure_detected", "user_triggered", "milestone_reached"]

    def __init__(self, memory_store, http_client=None, api_config=None):
        self._store = memory_store
        self._http = http_client
        self._config = api_config or {}
        from .perception import PerceptionLayer
        from .analyzer import ReflectionAnalyzer
        from .memory_writer import ReflectionMemoryWriter
        self._perception = PerceptionLayer(memory_store)
        self._analyzer = ReflectionAnalyzer(memory_store, http_client, api_config)
        self._writer = ReflectionMemoryWriter(memory_store)

    def reflect(self, trigger="user_triggered", session_id="default",
                tool_logs=None, user_feedback="", task_description="") -> dict:
        """Run the full reflection pipeline."""
        t0 = time.perf_counter()

        # Step 1: Perceive - collect trajectory
        trajectory = self._perception.collect(session_id, tool_logs, task_description)

        # Step 2: Parse result - success/failure/partial
        outcome = self._perception.parse_outcome(trajectory, user_feedback)

        # Step 3: Analyze - root cause + insights
        analysis = self._analyzer.analyze(trajectory, outcome, task_description, trigger)

        # Step 4: Store - write to MemoryOS
        card = self._writer.store_reflection(
            task=task_description or "Reflection",
            outcome=outcome["outcome"],
            analysis=analysis,
            trajectory=trajectory,
            trigger=trigger,
            session_id=session_id,
        )

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "card": card,
            "outcome": outcome,
            "analysis": analysis,
            "elapsed_ms": elapsed,
            "trigger": trigger,
        }

    async def reflect_with_llm(self, trigger="task_completed", session_id="default",
                                tool_logs=None, user_feedback="", task_description="") -> dict:
        """Full reflection with LLM-based root cause analysis."""
        t0 = time.perf_counter()
        trajectory = self._perception.collect(session_id, tool_logs, task_description)
        outcome = self._perception.parse_outcome(trajectory, user_feedback)
        analysis = await self._analyzer.analyze_with_llm(trajectory, outcome, task_description, trigger)
        card = self._writer.store_reflection(
            task=task_description or "Reflection",
            outcome=outcome["outcome"],
            analysis=analysis,
            trajectory=trajectory,
            trigger=trigger,
            session_id=session_id,
        )
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return {"card": card, "outcome": outcome, "analysis": analysis, "elapsed_ms": elapsed, "trigger": trigger}

    def should_reflect(self, tool_calls, user_text="") -> str | None:
        """Auto-detect if reflection should be triggered."""
        if not tool_calls:
            return None
        errors = [tc for tc in tool_calls if "error" in str(tc.get("result", {})).lower()]
        if errors:
            return "failure_detected"
        if len(tool_calls) >= 3:
            return "task_completed"
        if user_text and any(kw in user_text.lower() for kw in ["reflect", "review", "summarize", "??", "??"]):
            return "user_triggered"
        return None
