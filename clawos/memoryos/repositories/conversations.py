from __future__ import annotations


from memoryos.persistence import Repository, atomic_workflow


class ConversationsRepository(Repository):
    """Persistence operations for conversations."""

    @atomic_workflow
    def add_message(self, session_id: str, role: str, content: str, tool_calls: str = "", metadata: str = ""):
        with self._conn() as c:
            count = c.execute("SELECT COUNT(*) FROM conversations WHERE session_id=?", (session_id,)).fetchone()[0]
            if count >= 100:
                from memoryos.services.management import ManagementService
                ManagementService(self).compact_conversation(session_id, keep_recent=90)
            c.execute(
                "INSERT INTO conversations (session_id, role, content, tool_calls, metadata) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, tool_calls, metadata)
            )


    def get_session_messages(self, session_id: str, limit: int = 30) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT id, role, content, tool_calls, metadata, created_at FROM conversations WHERE session_id=? ORDER BY id ASC LIMIT ?",
                (session_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]


    def get_recent_messages(self, session_id: str, n: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, n)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]


    def conversation_history(self, session_id, limit=50, before_id=0):
        """Page full visible messages across compaction, using immutable IDs."""
        limit = max(1, min(int(limit), 200))
        before_id = max(0, int(before_id))
        with self._conn() as c:
            source = """WITH history AS (
                SELECT id,session_id,role,content,created_at,0 AS archived FROM conversations
                UNION ALL
                SELECT original_id AS id,session_id,role,content,created_at,1 AS archived
                FROM conversation_archive WHERE NOT EXISTS
                (SELECT 1 FROM conversations WHERE id=conversation_archive.original_id)) """
            rows = c.execute(source + """SELECT id,role,content,created_at,archived FROM history
                WHERE session_id=? AND role IN ('user','assistant') AND (?=0 OR id<?)
                ORDER BY id DESC LIMIT ?""", (session_id,before_id,before_id,limit+1)).fetchall()
            more = len(rows) > limit
            items = [dict(row) for row in reversed(rows[:limit])]
            total = c.execute(source + "SELECT COUNT(*) FROM history WHERE session_id=? AND role IN ('user','assistant')", (session_id,)).fetchone()[0]
            return dict(session_id=session_id, messages=items, count=len(items), total=total,
                        has_more=more, next_before_id=items[0]['id'] if items and more else None)


    def get_session_summary(self, session_id: str) -> str:
        """Return the persistent semantic summary plus recent activity."""
        persisted = self.get_persisted_session_summary(session_id)
        msgs = self.get_recent_messages(session_id, 30)
        if not msgs:
            return persisted or "No previous conversation."
        summary_parts = []
        user_msgs = [m for m in msgs if m["role"] == "user"]
        for m in user_msgs[-5:]:
            content = m.get("content", "")
            summary_parts.append(f"user asked: {content[:200]}")
        recent = "Recent conversation:\n" + "\n".join(summary_parts)
        return f"Persistent conversation summary:\n{persisted}\n\n{recent}" if persisted else recent


    def get_persisted_session_summary(self, session_id: str) -> str:
        with self._conn() as c:
            row = c.execute(
                "SELECT summary FROM conversation_summaries WHERE session_id=?",
                (session_id,),
            ).fetchone()
            return str(row["summary"]) if row else ""


    def save_session_summary(
        self, session_id: str, summary: str, source_message_count: int
    ) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO conversation_summaries
                    (session_id, summary, source_message_count, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(session_id) DO UPDATE SET
                    summary=excluded.summary,
                    source_message_count=excluded.source_message_count,
                    updated_at=datetime('now')
                """,
                (session_id, str(summary)[:20_000], int(source_message_count)),
            )


    def archive_session_messages(self, session_id, message_ids):
        ids=[int(value) for value in message_ids]
        with self._conn() as c:
            for message_id in ids:
                c.execute("""INSERT OR IGNORE INTO conversation_archive
                    (original_id,session_id,role,content,tool_calls,metadata,created_at)
                    SELECT id,session_id,role,content,tool_calls,metadata,created_at FROM conversations WHERE id=? AND session_id=?""",(message_id,session_id))
                c.execute("DELETE FROM conversations WHERE id=? AND session_id=? AND EXISTS (SELECT 1 FROM conversation_archive WHERE original_id=?)",(message_id,session_id,message_id))
        return len(ids)


    def delete_oldest_session_messages(self, session_id: str, count: int) -> int:
        with self._conn() as c:
            cursor = c.execute(
                """
                DELETE FROM conversations WHERE id IN (
                    SELECT id FROM conversations WHERE session_id=?
                    ORDER BY id ASC LIMIT ?
                )
                """,
                (session_id, max(0, int(count))),
            )
            return int(cursor.rowcount or 0)
