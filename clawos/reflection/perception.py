"""PerceptionLayer - collects trajectory data and parses results."""
import json, re
from datetime import datetime, timezone

class PerceptionLayer:
    """Collects execution trajectory and parses success/failure signals."""

    def __init__(self, store):
        self._store = store

    def collect(self, session_id, tool_logs=None, task_description=""):
        """Collect execution trajectory from tool logs and conversation history."""
        trajectory = {
            "session_id": session_id,
            "task_description": task_description,
            "tool_calls": tool_logs or [],
            "conversation": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Fetch recent conversation context
        msgs = self._store.get_recent_messages(session_id, 10)
        trajectory["conversation"] = [
            {"role": m.get("role", ""), "content": (m.get("content", "") or "")[:300]}
            for m in (msgs or [])
        ]
        # Extract key events
        trajectory["key_events"] = self._extract_key_events(trajectory)
        return trajectory

    def _extract_key_events(self, trajectory):
        events = []
        for tc in trajectory.get("tool_calls", []):
            result = tc.get("result", {})
            if isinstance(result, str):
                try: result = json.loads(result)
                except: pass
            if isinstance(result, dict):
                if "error" in result:
                    events.append({"type": "tool_error", "tool": tc.get("name", ""), "detail": str(result["error"])[:200]})
                elif result.get("count", 0) > 0:
                    events.append({"type": "tool_result", "tool": tc.get("name", ""), "count": result.get("count", 1)})
        return events

    def parse_outcome(self, trajectory, user_feedback=""):
        """Determine success/failure/partial from trajectory."""
        tool_calls = trajectory.get("tool_calls", [])
        errors = []
        successes = []

        for tc in tool_calls:
            result = tc.get("result", {})
            if isinstance(result, str):
                try: result = json.loads(result)
                except: pass
            if isinstance(result, dict):
                if "error" in result:
                    errors.append(tc.get("name", "unknown"))
                else:
                    successes.append(tc.get("name", "unknown"))

        total = len(tool_calls)
        error_count = len(errors)

        if total == 0:
            return {"outcome": "partial", "reason": "No tools executed", "errors": [], "successes": []}

        if error_count == 0:
            outcome = "success"
            reason = f"All {total} tool(s) completed successfully"
        elif error_count == total:
            outcome = "failure"
            reason = f"All {total} tool(s) failed"
        else:
            outcome = "partial"
            reason = f"{error_count}/{total} tool(s) failed"

        return {
            "outcome": outcome,
            "reason": reason,
            "errors": errors,
            "successes": successes,
            "total_tools": total,
            "error_count": error_count,
            "user_feedback": user_feedback,
        }

    def aggregate_feedback(self, user_text="", tool_logs=None):
        """Aggregate user feedback and tool errors into structured signals."""
        signals = {"user_sentiment": "neutral", "error_signals": [], "success_signals": []}
        # Simple sentiment detection
        if user_text:
            positive = ["good", "great", "thanks", "perfect", "?", "??", "??", "??"]
            negative = ["wrong", "error", "bad", "not working", "??", "??", "??", "???"]
            for w in positive:
                if w.lower() in user_text.lower():
                    signals["user_sentiment"] = "positive"
                    break
            for w in negative:
                if w.lower() in user_text.lower():
                    signals["user_sentiment"] = "negative"
                    break
        if tool_logs:
            for tc in tool_logs:
                r = tc.get("result", {})
                if isinstance(r, dict) and "error" in r:
                    signals["error_signals"].append(tc.get("name", ""))
                else:
                    signals["success_signals"].append(tc.get("name", ""))
        return signals
