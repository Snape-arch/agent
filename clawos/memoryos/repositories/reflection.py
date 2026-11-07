from __future__ import annotations

import json

from memoryos.persistence import Repository, atomic_workflow


class ReflectionRepository(Repository):
    """Persistence operations for reflection."""

    def create_reflection_card(self, card, improvements=None):
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO reflection_cards
                    (id, task, session_id, trigger_type, outcome, outcome_detail,
                     root_cause, failure_category, insights, patterns, trajectory,
                     evidence, user_feedback, status, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["id"],
                    card.get("task", "Reflection"),
                    card.get("session_id", "default"),
                    card.get("trigger", "user_triggered"),
                    card.get("outcome", "partial"),
                    json.dumps(card.get("outcome_detail", {}), ensure_ascii=False),
                    card.get("root_cause", ""),
                    card.get("failure_category", ""),
                    json.dumps(card.get("insights", []), ensure_ascii=False),
                    json.dumps(card.get("patterns", []), ensure_ascii=False),
                    json.dumps(card.get("trajectory", {}), ensure_ascii=False),
                    json.dumps(card.get("evidence", []), ensure_ascii=False),
                    json.dumps(card.get("user_feedback", {}), ensure_ascii=False),
                    card.get("status", "active"),
                    int(card.get("version", 1)),
                ),
            )
            improvement_rows = []
            for index, improvement in enumerate(improvements or []):
                item = improvement if isinstance(improvement, dict) else {"detail": str(improvement)}
                detail = str(item.get("detail", item.get("title", "")) or "")
                title = str(item.get("title", detail) or f"Improvement {index + 1}")[:200]
                target_key = str(item.get("target_key", f"{card['id']}:{index + 1}"))
                cursor = c.execute(
                    """
                    INSERT INTO reflection_improvements
                        (card_id, title, detail, action_type, target_type, target_key,
                         candidate_payload, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed')
                    """,
                    (
                        card["id"], title, detail,
                        str(item.get("action_type", "policy")),
                        str(item.get("target_type", "agent_policy")),
                        target_key,
                        json.dumps(
                            item.get("candidate_payload", {"instruction": detail}),
                            ensure_ascii=False,
                        ),
                    ),
                )
                improvement_id = int(cursor.lastrowid)
                c.execute(
                    """
                    INSERT INTO reflection_improvement_events
                        (improvement_id, from_status, to_status, actor_id, reason)
                    VALUES (?, '', 'proposed', 'reflection_engine', 'Created from reflection card')
                    """,
                    (improvement_id,),
                )
                improvement_rows.append(self._reflection_improvement_from_row(
                    c.execute("SELECT * FROM reflection_improvements WHERE id=?", (improvement_id,)).fetchone()
                ))
            stored = self._reflection_card_from_row(
                c.execute("SELECT * FROM reflection_cards WHERE id=?", (card["id"],)).fetchone()
            )
            stored["improvements"] = improvement_rows
            return stored


    def list_reflection_cards(self, limit=20, session_id=""):
        with self._conn() as c:
            limit = max(1, min(int(limit or 20), 200))
            if session_id:
                rows = c.execute(
                    "SELECT * FROM reflection_cards WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM reflection_cards ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._reflection_card_from_row(row) for row in rows]


    def get_reflection_card(self, card_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM reflection_cards WHERE id=?", (str(card_id),)).fetchone()
            if not row:
                return None
            card = self._reflection_card_from_row(row)
            improvements = c.execute(
                "SELECT * FROM reflection_improvements WHERE card_id=? ORDER BY id",
                (str(card_id),),
            ).fetchall()
            card["improvements"] = [self._reflection_improvement_from_row(item) for item in improvements]
            return card


    def update_reflection_feedback(self, card_id, feedback, actor_id="system"):
        with self._conn() as c:
            row = c.execute("SELECT * FROM reflection_cards WHERE id=?", (str(card_id),)).fetchone()
            if not row:
                return None
            current = self._json_loads(row["user_feedback"], {})
            current.update(feedback or {})
            current["updated_by"] = str(actor_id or "system")
            c.execute(
                """
                UPDATE reflection_cards
                SET user_feedback=?, version=version+1, updated_at=datetime('now')
                WHERE id=?
                """,
                (json.dumps(current, ensure_ascii=False), str(card_id)),
            )
            return self._reflection_card_from_row(
                c.execute("SELECT * FROM reflection_cards WHERE id=?", (str(card_id),)).fetchone()
            )


    def list_reflection_improvements(self, status="", limit=100):
        with self._conn() as c:
            limit = max(1, min(int(limit or 100), 500))
            if status:
                rows = c.execute(
                    "SELECT * FROM reflection_improvements WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM reflection_improvements ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._reflection_improvement_from_row(row) for row in rows]


    def get_reflection_improvement(self, improvement_id, conn=None):
        def fetch(c):
            row = c.execute("SELECT * FROM reflection_improvements WHERE id=?", (int(improvement_id),)).fetchone()
            if not row:
                return None
            item = self._reflection_improvement_from_row(row)
            events = c.execute(
                "SELECT * FROM reflection_improvement_events WHERE improvement_id=? ORDER BY id",
                (int(improvement_id),),
            ).fetchall()
            item["events"] = [
                {**dict(event), "data": self._json_loads(event["data"], {})}
                for event in events
            ]
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def update_reflection_improvement(
        self, improvement_id, from_status, to_status, actor_id="system",
        reason="", data=None, fields=None,
    ):
        allowed_fields = {
            "baseline_metrics", "candidate_metrics", "regression_result",
            "rollback_payload", "published_at", "rolled_back_at",
        }
        with self._conn() as c:
            current = c.execute(
                "SELECT * FROM reflection_improvements WHERE id=?",
                (int(improvement_id),),
            ).fetchone()
            if not current:
                return None
            if current["status"] != from_status:
                raise ValueError(f"expected status {from_status}, got {current['status']}")
            assignments = ["status=?", "updated_at=datetime('now')"]
            params = [to_status]
            for key, value in (fields or {}).items():
                if key not in allowed_fields:
                    continue
                assignments.append(f"{key}=?")
                params.append(
                    json.dumps(value, ensure_ascii=False)
                    if key.endswith("_metrics") or key.endswith("_result") or key == "rollback_payload"
                    else value
                )
            params.append(int(improvement_id))
            c.execute(
                f"UPDATE reflection_improvements SET {', '.join(assignments)} WHERE id=?",
                params,
            )
            c.execute(
                """
                INSERT INTO reflection_improvement_events
                    (improvement_id, from_status, to_status, actor_id, reason, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(improvement_id), from_status, to_status,
                    str(actor_id or "system"), str(reason or ""),
                    json.dumps(data or {}, ensure_ascii=False),
                ),
            )
            return self.get_reflection_improvement(improvement_id, conn=c)


    def get_runtime_policy(self, target_type, target_key, conn=None):
        def fetch(c):
            row = c.execute(
                "SELECT * FROM runtime_policies WHERE target_type=? AND target_key=?",
                (str(target_type), str(target_key)),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = self._json_loads(item.get("payload"), {})
            item["active"] = bool(item.get("active"))
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    @atomic_workflow
    def set_runtime_policy(self, target_type, target_key, payload, actor_id="system"):
        with self._conn() as c:
            current = self.get_runtime_policy(target_type, target_key, conn=c)
            version = int(current["version"]) + 1 if current else 1
            c.execute(
                """
                INSERT INTO runtime_policies
                    (target_type, target_key, payload, version, active, updated_by, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, datetime('now'))
                ON CONFLICT(target_type, target_key) DO UPDATE SET
                    payload=excluded.payload,
                    version=excluded.version,
                    active=1,
                    updated_by=excluded.updated_by,
                    updated_at=datetime('now')
                """,
                (
                    str(target_type), str(target_key),
                    json.dumps(payload or {}, ensure_ascii=False),
                    version, str(actor_id or "system"),
                ),
            )
            return self.get_runtime_policy(target_type, target_key, conn=c)


    def _reflection_card_from_row(self, row):
        item = dict(row)
        for key, default in (
            ("outcome_detail", {}), ("insights", []), ("patterns", []),
            ("trajectory", {}), ("evidence", []), ("user_feedback", {}),
        ):
            item[key] = self._json_loads(item.get(key), default)
        item["trigger"] = item.pop("trigger_type", "")
        return item


    def _reflection_improvement_from_row(self, row):
        item = dict(row)
        for key in (
            "candidate_payload", "baseline_metrics", "candidate_metrics",
            "regression_result", "rollback_payload",
        ):
            item[key] = self._json_loads(item.get(key), {})
        return item
