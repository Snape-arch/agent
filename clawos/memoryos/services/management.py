"""ManagementService - memory lifecycle, compaction, archiving."""

class ManagementService:
    """Handles memory lifecycle: cleanup old data, archive, compact conversations."""

    def __init__(self, store):
        self._store = store

    def compact_conversation(self, session_id, keep_recent=20):
        """Persist a bounded semantic summary, then delete compacted messages."""
        msgs = self._store.get_session_messages(session_id, limit=10000)
        if len(msgs) <= keep_recent:
            return {"compacted": False, "total": len(msgs)}
        compacted = msgs[:-max(1, int(keep_recent))]
        lines = []
        for item in compacted:
            role = str(item.get("role") or "unknown")
            content = " ".join(str(item.get("content") or "").split())
            if content:
                lines.append(f"{role}: {content[:400]}")
        previous = self._store.get_persisted_session_summary(session_id)
        summary = "\n".join([
            previous,
            *lines[-40:],
        ]).strip()
        self._store.save_session_summary(session_id, summary, len(compacted))
        deleted = self._store.delete_oldest_session_messages(
            session_id, len(compacted)
        )
        return {
            "compacted": True,
            "total": len(msgs),
            "deleted": deleted,
            "kept": len(msgs) - deleted,
            "summary_chars": len(summary),
        }

    def update_preference_confidence(self, key, value, increment=0.1):
        """Increase confidence in a preference when user confirms it."""
        pref = self._store.get_preference(key)
        if pref:
            new_conf = min(1.0, pref.get("confidence", 0.5) + increment)
            self._store.set_preference(key, pref.get("value", value), pref.get("category", "general"), new_conf)
            return {"updated": True, "key": key, "new_confidence": new_conf}
        return {"updated": False, "key": key}

    def suggest_forgetting(self, min_age_days=30, max_items=10):
        """Suggest old knowledge items that could be pruned."""
        items = self._store.list_knowledge()
        import datetime
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=min_age_days)).isoformat()
        old = [i for i in items if i.get("created_at", "") < cutoff and i.get("access_count", 0) == 0]
        return old[:max_items]
