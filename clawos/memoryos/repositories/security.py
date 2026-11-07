from __future__ import annotations

import json

from memoryos.persistence import Repository


class SecurityRepository(Repository):
    """Persistence operations for security."""

    def record_audit_event(
        self, action, decision="allow", actor_id="system", session_id="",
        task_id=None, resource_type="", resource_id="", reason="", details=None,
    ):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO audit_events
                    (actor_id, session_id, task_id, action, resource_type,
                     resource_id, decision, reason, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(actor_id or "system"), str(session_id or ""),
                    int(task_id) if task_id else None, str(action),
                    str(resource_type or ""), str(resource_id or ""),
                    str(decision), str(reason or ""),
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM audit_events WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return self._audit_row_to_dict(row)


    def list_audit_events(self, action="", decision="", limit=100):
        with self._conn() as c:
            clauses = []
            params = []
            if action:
                clauses.append("action=?")
                params.append(str(action))
            if decision:
                clauses.append("decision=?")
                params.append(str(decision))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ?",
                [*params, max(1, min(int(limit or 100), 500))],
            ).fetchall()
            return [self._audit_row_to_dict(row) for row in rows]


    def register_secret_ref(self, name, env_var, purpose="", allowed_tools=None, created_by="system"):
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO secret_refs
                    (name, env_var, purpose, allowed_tools, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    env_var=excluded.env_var,
                    purpose=excluded.purpose,
                    allowed_tools=excluded.allowed_tools,
                    enabled=1,
                    updated_at=datetime('now')
                """,
                (
                    str(name), str(env_var), str(purpose or ""),
                    json.dumps(allowed_tools or [], ensure_ascii=False),
                    str(created_by or "system"),
                ),
            )
            return self.get_secret_ref(name, conn=c)


    def get_secret_ref(self, name, conn=None):
        def fetch(c):
            row = c.execute("SELECT * FROM secret_refs WHERE name=?", (str(name),)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["allowed_tools"] = self._json_loads(item.get("allowed_tools"), [])
            item["enabled"] = bool(item.get("enabled"))
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def list_secret_refs(self):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM secret_refs ORDER BY name").fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["allowed_tools"] = self._json_loads(item.get("allowed_tools"), [])
                item["enabled"] = bool(item.get("enabled"))
                items.append(item)
            return items


    def _audit_row_to_dict(self, row):
        item = dict(row)
        item["details"] = self._json_loads(item.get("details"), {})
        return item
