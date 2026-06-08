"""ReflectionMemoryWriter - stores reflections in MemoryOS."""
import json
from datetime import datetime, timezone

class ReflectionMemoryWriter:
    """Writes structured ReflectionCards into MemoryOS experiences table."""

    def __init__(self, store):
        self._store = store

    def store_reflection(self, task, outcome, analysis, trajectory, trigger="", session_id=""):
        """Create and store a ReflectionCard in MemoryOS."""
        card = {
            "id": f"ref_{int(datetime.now(timezone.utc).timestamp())}",
            "task": task,
            "outcome": outcome,
            "root_cause": analysis.get("root_cause", ""),
            "insights": analysis.get("insights", []),
            "improvements": analysis.get("improvements", []),
            "patterns": analysis.get("patterns", []),
            "trigger": trigger,
            "session_id": session_id,
            "tool_sequence": [tc.get("name", "") for tc in trajectory.get("tool_calls", [])],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Store in MemoryOS experiences table
        outcome_str = outcome if isinstance(outcome, str) else outcome.get("outcome", "partial")
        lesson = "; ".join(analysis.get("insights", []))[:500]
        context = json.dumps({
            "trajectory_summary": f"{len(trajectory.get('tool_calls', []))} tools",
            "trigger": trigger,
            "session_id": session_id,
        }, ensure_ascii=False)

        self._store.add_experience(
            task=task,
            outcome=outcome_str,
            lesson=lesson,
            context=context,
            solution="; ".join(analysis.get("improvements", []))[:300],
            tags=[trigger, outcome_str] if trigger else [outcome_str],
            importance=self._calculate_importance(outcome_str, trigger),
        )

        # Update skill records if tools were used
        for tc in trajectory.get("tool_calls", []):
            tool_name = tc.get("name", "")
            result = tc.get("result", {})
            if isinstance(result, str):
                try: result = json.loads(result)
                except: pass
            success = isinstance(result, dict) and "error" not in result
            self._store.record_skill_usage(tool_name, success)

        return card

    def _calculate_importance(self, outcome, trigger):
        """Calculate reflection importance based on outcome and trigger."""
        base = 0.5
        if trigger == "failure_detected":
            base = 0.9
        elif trigger == "user_triggered":
            base = 0.8
        elif outcome == "failure":
            base = 0.85
        elif outcome == "success":
            base = 0.6
        elif outcome == "partial":
            base = 0.7
        return base

    def get_reflection_cards(self, limit=20):
        """Retrieve recent reflection cards from MemoryOS."""
        experiences = self._store.get_recent_experiences(limit)
        cards = []
        for exp in experiences:
            cards.append({
                "id": exp.get("id", ""),
                "task": exp.get("task", ""),
                "outcome": exp.get("outcome", ""),
                "lesson": exp.get("lesson", ""),
                "solution": exp.get("solution", ""),
                "importance": exp.get("importance", 0.5),
                "created_at": exp.get("created_at", ""),
            })
        return cards
