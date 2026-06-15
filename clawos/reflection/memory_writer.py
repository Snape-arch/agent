"""ReflectionMemoryWriter - stores reflections in MemoryOS."""
import json
import uuid
from datetime import datetime, timezone

class ReflectionMemoryWriter:
    """Writes structured ReflectionCards into MemoryOS experiences table."""

    def __init__(self, store):
        self._store = store

    def store_reflection(
        self, task, outcome, analysis, trajectory, trigger="", session_id="",
        outcome_detail=None, user_feedback="",
    ):
        """Create and store a ReflectionCard in MemoryOS."""
        feedback = (
            user_feedback
            if isinstance(user_feedback, dict)
            else {"comment": str(user_feedback or "")}
        )
        evidence = []
        for call in trajectory.get("tool_calls", []):
            evidence.append({
                "evidence_type": "tool_execution",
                "tool": call.get("name", ""),
                "arguments": call.get("arguments", {}),
                "result": call.get("result", {}),
            })
        if feedback.get("comment") or feedback.get("rating") is not None:
            evidence.append({
                "evidence_type": "user_feedback",
                "feedback": feedback,
            })
        card = {
            "id": f"ref_{uuid.uuid4().hex}",
            "task": task,
            "outcome": outcome,
            "outcome_detail": outcome_detail or {},
            "root_cause": analysis.get("root_cause", ""),
            "failure_category": analysis.get("failure_category", ""),
            "insights": analysis.get("insights", []),
            "improvements": analysis.get("improvements", []),
            "patterns": analysis.get("patterns", []),
            "trigger": trigger,
            "session_id": session_id,
            "tool_sequence": [tc.get("name", "") for tc in trajectory.get("tool_calls", [])],
            "trajectory": trajectory,
            "evidence": evidence,
            "user_feedback": feedback,
            "status": "active",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        stored_card = self._store.create_reflection_card(
            card,
            improvements=analysis.get("improvements", []),
        )

        # Store in MemoryOS experiences table
        outcome_str = outcome if isinstance(outcome, str) else outcome.get("outcome", "partial")
        insight_texts = [
            str(item.get("detail", item.get("title", ""))) if isinstance(item, dict) else str(item)
            for item in analysis.get("insights", [])
        ]
        improvement_texts = [
            str(item.get("detail", item.get("title", ""))) if isinstance(item, dict) else str(item)
            for item in analysis.get("improvements", [])
        ]
        lesson = "; ".join(insight_texts)[:500]
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
            solution="; ".join(improvement_texts)[:300],
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
            if isinstance(result, dict) and "ok" in result:
                success = bool(result.get("ok"))
            else:
                success = isinstance(result, dict) and "error" not in result
            self._store.record_skill_usage(tool_name, success)

        return stored_card

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
        cards = self._store.list_reflection_cards(limit)
        if cards:
            return cards
        experiences = self._store.get_recent_experiences(limit)
        legacy_cards = []
        for exp in experiences:
            legacy_cards.append({
                "id": exp.get("id", ""),
                "task": exp.get("task", ""),
                "outcome": exp.get("outcome", ""),
                "lesson": exp.get("lesson", ""),
                "solution": exp.get("solution", ""),
                "importance": exp.get("importance", 0.5),
                "created_at": exp.get("created_at", ""),
            })
        return legacy_cards
