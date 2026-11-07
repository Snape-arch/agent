from __future__ import annotations

import json

from memoryos.persistence import Repository


class TelemetryRepository(Repository):
    """Persistence operations for telemetry."""

    def get_stats(self) -> dict:
        with self._conn() as c:
            return {
                "profiles": c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0],
                "preferences": c.execute("SELECT COUNT(*) FROM preferences").fetchone()[0],
                "conversations": c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                "projects": c.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "experiences": c.execute("SELECT COUNT(*) FROM experiences").fetchone()[0],
                "memories": c.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
                "context_snapshots": c.execute("SELECT COUNT(*) FROM context_snapshots").fetchone()[0],
                "tool_executions": c.execute("SELECT COUNT(*) FROM tool_executions").fetchone()[0],
                "mtclaw_traces": c.execute("SELECT COUNT(*) FROM mtclaw_traces").fetchone()[0],
                "memory_reviews_pending": c.execute(
                    "SELECT COUNT(*) FROM memory_reviews WHERE status='pending'"
                ).fetchone()[0],
                "reflection_cards": c.execute("SELECT COUNT(*) FROM reflection_cards").fetchone()[0],
                "reflection_improvements_pending": c.execute(
                    """
                    SELECT COUNT(*) FROM reflection_improvements
                    WHERE status IN ('proposed','approved','testing','validated')
                    """
                ).fetchone()[0],
            }


    def save_context_snapshot(self, session_id, task="", active_tools=None, environment="", user_intent=""):
        with self._conn() as c:
            c.execute("INSERT INTO context_snapshots (session_id,task_description,active_tools,environment,user_intent) VALUES (?,?,?,?,?)",
                      (session_id, task, json.dumps(active_tools or []), environment, user_intent))
            c.execute("DELETE FROM context_snapshots WHERE session_id=? AND id NOT IN (SELECT id FROM context_snapshots WHERE session_id=? ORDER BY id DESC LIMIT 20)",
                      (session_id, session_id))


    def get_latest_context(self, session_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM context_snapshots WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
            return dict(row) if row else None


    def record_skill_usage(self, skill_name, success=True, duration_ms=0, feedback="", category="general"):
        with self._conn() as c:
            row = c.execute("SELECT * FROM skill_records WHERE skill_name=?", (skill_name,)).fetchone()
            if row:
                total = row["usage_count"] + 1
                sc = row["success_count"] + (1 if success else 0)
                avg = (row["avg_duration_ms"] * row["usage_count"] + duration_ms) / total
                c.execute("UPDATE skill_records SET usage_count=?,success_count=?,avg_duration_ms=?,last_used=datetime('now'),feedback=?,quality_score=? WHERE skill_name=?",
                          (total, sc, avg, feedback, sc/total, skill_name))
            else:
                c.execute("INSERT INTO skill_records (skill_name,category,usage_count,success_count,avg_duration_ms,last_used,feedback,quality_score) VALUES (?,?,1,?,?,datetime('now'),?,?)",
                          (skill_name, category, 1 if success else 0, duration_ms, feedback, 1.0 if success else 0.3))


    def get_skill_stats(self, skill_name=""):
        with self._conn() as c:
            if skill_name:
                row = c.execute("SELECT * FROM skill_records WHERE skill_name=?", (skill_name,)).fetchone()
                return dict(row) if row else {}
            return [dict(r) for r in c.execute("SELECT * FROM skill_records ORDER BY usage_count DESC").fetchall()]


    def record_tool_execution(self, session_id, tool_name, arguments=None, result=None,
                              status="success", duration_ms=0, requires_confirmation=False):
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO tool_executions
                    (session_id, tool_name, arguments, result, status, duration_ms, requires_confirmation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    tool_name,
                    json.dumps(arguments or {}, ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    status,
                    float(duration_ms or 0),
                    1 if requires_confirmation else 0,
                ),
            )


    def list_tool_executions(self, session_id="", limit=50):
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            if session_id:
                rows = c.execute(
                    "SELECT * FROM tool_executions WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM tool_executions ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                for key in ("arguments", "result"):
                    try:
                        item[key] = json.loads(item.get(key) or "{}")
                    except Exception:
                        item[key] = {}
                item["requires_confirmation"] = bool(item.get("requires_confirmation"))
                items.append(item)
            return items


    def record_mtclaw_trace(self, session_id, route_status, provider_url="", model="",
                            duration_ms=0, tool_history=None, error=""):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO mtclaw_traces
                    (session_id, route_status, provider_url, model, duration_ms, tool_history, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    route_status,
                    provider_url,
                    model,
                    float(duration_ms or 0),
                    json.dumps(tool_history or [], ensure_ascii=False),
                    error,
                ),
            )
            return int(cursor.lastrowid)


    def list_mtclaw_traces(self, session_id="", limit=50):
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            if session_id:
                rows = c.execute(
                    "SELECT * FROM mtclaw_traces WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM mtclaw_traces ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                try:
                    item["tool_history"] = json.loads(item.get("tool_history") or "[]")
                except json.JSONDecodeError:
                    item["tool_history"] = []
                items.append(item)
            return items


    def search_all_text(self, query, limit=20):
        results = []
        with self._conn() as c:
            rows = c.execute("""
                SELECT id, title AS title, content AS body, category AS type, 'knowledge' AS _source, source, created_at
                FROM knowledge
                WHERE title LIKE ? OR content LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
            from services.document_evidence_policy import source_usable
            results.extend(dict(r) for r in rows if source_usable(c, r["source"]))

            rows = c.execute("""
                SELECT id, task AS title, lesson || ' ' || context || ' ' || solution AS body,
                       outcome AS type, 'experiences' AS _source, created_at
                FROM experiences
                WHERE task LIKE ? OR lesson LIKE ? OR context LIKE ? OR solution LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
            results.extend(dict(r) for r in rows)
        return results
