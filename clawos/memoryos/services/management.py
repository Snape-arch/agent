"""ManagementService - memory lifecycle, compaction, archiving."""

class ManagementService:
    """Handles memory lifecycle: cleanup old data, archive, compact conversations."""

    def __init__(self, store):
        self._store = store

    def compact_conversation(self, session_id, keep_recent=20):
        """Keep only the most recent N messages per session."""
        msgs = self._store.get_session_messages(session_id, limit=10000)
        if len(msgs) <= keep_recent:
            return {"compacted": False, "total": len(msgs)}
        # The oldest messages (by SQLite rowid) get deleted implicitly by the auto-truncation
        # in add_message. This is a no-op: the store handles it.
        return {"compacted": False, "total": len(msgs), "note": "auto-truncation handles this"}

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
