"""LearningLoop - Execute -> Collect -> Reflect -> Store -> Apply -> Evaluate -> Iterate."""
import time, json
from datetime import datetime, timezone

class LearningLoop:
    """Continuous improvement cycle for the agent."""

    def __init__(self, engine, memory_store):
        self._engine = engine
        self._store = memory_store
        self._cycle_count = 0

    async def run_cycle(self, session_id="default", task_description="",
                        tool_logs=None, user_feedback="") -> dict:
        """Run one full learning cycle."""
        self._cycle_count += 1
        cycle = {
            "cycle": self._cycle_count,
            "session_id": session_id,
            "task": task_description,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Reflect on the task outcome
        reflection = await self._engine.reflect_with_llm(
            trigger="task_completed",
            session_id=session_id,
            tool_logs=tool_logs,
            user_feedback=user_feedback,
            task_description=task_description,
        )
        cycle["reflection"] = reflection

        # 2. Improvements are queued for approval; none are applied automatically.
        cycle["applied_improvements"] = [
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "detail": item.get("detail", ""),
            }
            for item in reflection.get("card", {}).get("improvements", [])
        ]

        # 3. Evaluate the effect (simple heuristic)
        cycle["evaluation"] = self._evaluate_effect(reflection)

        # 4. Store cycle metadata
        self._store_cycle_metadata(cycle)

        return cycle

    def _evaluate_effect(self, reflection):
        """Evaluate how effective the reflection was."""
        outcome = reflection.get("outcome", {}).get("outcome", "partial")
        analysis = reflection.get("analysis", {})
        insights_count = len(analysis.get("insights", []))
        improvement_count = len(analysis.get("improvements", []))

        score = 0.0
        if outcome == "success": score += 0.4
        elif outcome == "partial": score += 0.2
        if insights_count > 0: score += min(insights_count * 0.15, 0.3)
        if improvement_count > 0: score += min(improvement_count * 0.15, 0.3)

        return {"effectiveness_score": round(score, 2), "insights_found": insights_count,
                "improvements_suggested": improvement_count, "outcome": outcome}

    def _store_cycle_metadata(self, cycle):
        """Persist cycle info as metadata (not a full experience)."""
        # Store as a context snapshot for traceability
        self._store.save_context_snapshot(
            session_id=cycle["session_id"],
            task=f"LearningCycle#{cycle['cycle']}: {cycle.get('task', '')[:100]}",
            environment=json.dumps({"cycle": cycle["cycle"], "effectiveness": cycle.get("evaluation", {})}),
        )

    def get_cycle_stats(self):
        """Get learning loop statistics."""
        stats = self._store.get_stats()
        return {
            "total_cycles": self._cycle_count,
            "total_experiences": stats.get("experiences", 0),
            "total_context_snapshots": stats.get("context_snapshots", 0),
        }
