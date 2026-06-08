"""EvaluationService - score memory relevance, accuracy, timeliness."""
import math
from datetime import datetime, timezone

class EvaluationService:
    """Evaluates memory quality across multiple dimensions."""

    def __init__(self, store):
        self._store = store

    def score_relevance(self, memory_entry, user_intent):
        """Score how relevant a memory is to a user query (0-1)."""
        content = (memory_entry.get("content", "") or memory_entry.get("task", "") or "").lower()
        intent = user_intent.lower()
        if not intent or not content:
            return 0.0
        # Simple term overlap
        intent_terms = set(intent.split())
        content_terms = set(content.split())
        if not intent_terms:
            return 0.0
        overlap = len(intent_terms & content_terms)
        return min(1.0, overlap / len(intent_terms) * 2.0)

    def score_timeliness(self, created_at, half_life_days=30):
        """Score based on recency - newer entries score higher."""
        try:
            if isinstance(created_at, str):
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            else:
                created = created_at
            age_days = (datetime.now(timezone.utc) - created).total_seconds() / 86400
        except Exception:
            return 0.5
        return math.exp(-age_days * math.log(2) / half_life_days)

    def comprehensive_score(self, memory, intent, created_at):
        """Combined score: relevance (0.5) + timeliness (0.3) + confidence (0.2)."""
        r = self.score_relevance(memory, intent)
        t = self.score_timeliness(created_at)
        c = memory.get("confidence", memory.get("importance", 0.5))
        return round(r * 0.5 + t * 0.3 + c * 0.2, 3)
