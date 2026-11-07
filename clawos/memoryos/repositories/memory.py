from __future__ import annotations

import json

from memoryos.persistence import Repository, atomic_workflow


class MemoryRepository(Repository):
    """Persistence operations for memory."""

    def _memory_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["confidence"] = float(item.get("confidence") or 0)
        item["current_version"] = int(item.get("current_version") or 1)
        return item


    def upsert_memory(
        self,
        memory_type,
        key,
        value,
        category="general",
        source="",
        confidence=0.5,
        enabled=True,
        actor_id="system",
        owner_id="default",
        workspace_id="default",
        evidence=None,
        change_reason="",
        conflict_policy="overwrite",
    ):
        memory_type = str(memory_type or "").strip().lower()
        if memory_type not in {"profile", "preference", "project", "experience", "skill"}:
            raise ValueError(f"Invalid memory_type: {memory_type}")
        key = str(key or "").strip()
        value = str(value or "").strip()
        if not key or not value:
            raise ValueError("key and value are required")
        with self._conn() as c:
            existing = c.execute(
                "SELECT * FROM memories WHERE memory_type=? AND category=? AND key=?",
                (memory_type, category, key),
            ).fetchone()
            if (
                existing
                and existing["value"] != value
                and str(conflict_policy or "").lower() == "review"
            ):
                conflict_cursor = c.execute(
                    """
                    INSERT INTO memory_conflicts
                        (memory_id, existing_value, candidate_value, source, evidence, submitted_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(existing["id"]),
                        existing["value"],
                        value,
                        source,
                        json.dumps(evidence or [], ensure_ascii=False),
                        str(actor_id or "system"),
                    ),
                )
                conflict_id = int(conflict_cursor.lastrowid)
                review_cursor = c.execute(
                    """
                    INSERT INTO memory_reviews (memory_id, conflict_id, submitted_by)
                    VALUES (?, ?, ?)
                    """,
                    (int(existing["id"]), conflict_id, str(actor_id or "system")),
                )
                item = self._memory_row_to_dict(existing)
                item.update({
                    "review_required": True,
                    "conflict_id": conflict_id,
                    "review_id": int(review_cursor.lastrowid),
                    "candidate_value": value,
                })
                return item

            changed = (
                existing is None
                or existing["value"] != value
                or existing["source"] != source
                or float(existing["confidence"] or 0) != float(confidence)
                or bool(existing["enabled"]) != bool(enabled)
            )
            next_version = int(existing["current_version"] or 1) + 1 if existing else 1
            c.execute("""
                INSERT INTO memories
                    (memory_type, category, key, value, source, confidence, enabled,
                     owner_id, workspace_id, current_version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(memory_type, category, key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    enabled = excluded.enabled,
                    owner_id = excluded.owner_id,
                    workspace_id = excluded.workspace_id,
                    current_version = excluded.current_version,
                    updated_at = datetime('now')
            """, (
                memory_type, category, key, value, source, float(confidence),
                1 if enabled else 0, owner_id, workspace_id,
                next_version if changed else int(existing["current_version"] or 1),
            ))
            row = c.execute(
                "SELECT * FROM memories WHERE memory_type=? AND category=? AND key=?",
                (memory_type, category, key),
            ).fetchone()
            version_id = None
            if changed:
                cursor = c.execute(
                    """
                    INSERT INTO memory_versions
                        (memory_id, version, value, source, confidence, enabled,
                         change_type, changed_by, change_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(row["id"]),
                        next_version,
                        value,
                        source,
                        float(confidence),
                        1 if enabled else 0,
                        "create" if existing is None else "update",
                        str(actor_id or "system"),
                        str(change_reason or ""),
                    ),
                )
                version_id = int(cursor.lastrowid)
            for item in evidence or []:
                self._insert_memory_evidence(c, int(row["id"]), version_id, item, actor_id)
            result = self._memory_row_to_dict(row)
            result["review_required"] = False
            return result


    def _insert_memory_evidence(self, conn, memory_id, version_id, evidence, actor_id="system"):
        item = evidence if isinstance(evidence, dict) else {"excerpt": str(evidence)}
        conn.execute(
            """
            INSERT INTO memory_evidence
                (memory_id, version_id, evidence_type, source_ref, excerpt, metadata, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(memory_id),
                int(version_id) if version_id else None,
                str(item.get("evidence_type", item.get("type", "manual")) or "manual"),
                str(item.get("source_ref", "") or ""),
                str(item.get("excerpt", "") or "")[:4000],
                json.dumps(item.get("metadata", {}), ensure_ascii=False),
                str(actor_id or "system"),
            ),
        )


    def list_memory_versions(self, memory_id, limit=100):
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM memory_versions
                WHERE memory_id=? ORDER BY version DESC LIMIT ?
                """,
                (int(memory_id), max(1, min(int(limit or 100), 500))),
            ).fetchall()
            return [self._version_row_to_dict(row) for row in rows]


    def list_memory_evidence(self, memory_id, limit=100):
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM memory_evidence
                WHERE memory_id=? ORDER BY id DESC LIMIT ?
                """,
                (int(memory_id), max(1, min(int(limit or 100), 500))),
            ).fetchall()
            return [self._evidence_row_to_dict(row) for row in rows]


    def _version_row_to_dict(self, row):
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["confidence"] = float(item.get("confidence") or 0)
        return item


    def _evidence_row_to_dict(self, row):
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        return item


    def list_memory_reviews(self, status="pending", limit=100):
        with self._conn() as c:
            clauses = []
            params = []
            if status:
                clauses.append("r.status=?")
                params.append(status)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = c.execute(
                f"""
                SELECT r.*, c.existing_value, c.candidate_value, c.conflict_type,
                       c.source AS conflict_source, c.evidence, m.memory_type,
                       m.category, m.key, m.value AS current_value
                FROM memory_reviews r
                JOIN memories m ON m.id=r.memory_id
                LEFT JOIN memory_conflicts c ON c.id=r.conflict_id
                {where}
                ORDER BY r.id DESC LIMIT ?
                """,
                [*params, max(1, min(int(limit or 100), 500))],
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["evidence"] = self._json_loads(item.get("evidence"), [])
                items.append(item)
            return items


    def resolve_memory_review(self, review_id, decision, reviewer="system", notes=""):
        decision = str(decision or "").lower()
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        with self._conn() as c:
            review = c.execute(
                """
                SELECT r.*, c.candidate_value, c.source, c.evidence
                FROM memory_reviews r
                LEFT JOIN memory_conflicts c ON c.id=r.conflict_id
                WHERE r.id=?
                """,
                (int(review_id),),
            ).fetchone()
            if not review:
                return None
            if review["status"] != "pending":
                raise ValueError("review is already resolved")
            status = "approved" if decision == "approve" else "rejected"
            if decision == "approve" and review["candidate_value"] is not None:
                memory = c.execute("SELECT * FROM memories WHERE id=?", (int(review["memory_id"]),)).fetchone()
                version = int(memory["current_version"] or 1) + 1
                c.execute(
                    """
                    UPDATE memories
                    SET value=?, source=?, current_version=?, updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (review["candidate_value"], review["source"], version, int(review["memory_id"])),
                )
                cursor = c.execute(
                    """
                    INSERT INTO memory_versions
                        (memory_id, version, value, source, confidence, enabled,
                         change_type, changed_by, change_reason)
                    VALUES (?, ?, ?, ?, ?, ?, 'conflict_resolution', ?, ?)
                    """,
                    (
                        int(review["memory_id"]), version, review["candidate_value"],
                        review["source"], float(memory["confidence"] or 0),
                        int(memory["enabled"] or 0), str(reviewer or "system"),
                        str(notes or "Approved from Review Inbox"),
                    ),
                )
                if memory["memory_type"] == "profile":
                    c.execute(
                        """
                        INSERT INTO profiles (category, key, value, importance, updated_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(category, key) DO UPDATE SET
                            value=excluded.value, updated_at=datetime('now')
                        """,
                        (
                            memory["category"], memory["key"], review["candidate_value"],
                            float(memory["confidence"] or 0.5),
                        ),
                    )
                elif memory["memory_type"] == "preference":
                    c.execute(
                        """
                        INSERT INTO preferences (category, key, value, confidence, updated_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(category, key) DO UPDATE SET
                            value=excluded.value, updated_at=datetime('now')
                        """,
                        (
                            memory["category"], memory["key"], review["candidate_value"],
                            float(memory["confidence"] or 0.5),
                        ),
                    )
                for evidence in self._json_loads(review["evidence"], []):
                    self._insert_memory_evidence(
                        c, int(review["memory_id"]), int(cursor.lastrowid), evidence, reviewer
                    )
            c.execute(
                """
                UPDATE memory_reviews
                SET status=?, reviewed_by=?, notes=?, resolved_at=datetime('now')
                WHERE id=?
                """,
                (status, str(reviewer or "system"), str(notes or ""), int(review_id)),
            )
            if review["conflict_id"]:
                c.execute(
                    """
                    UPDATE memory_conflicts
                    SET status=?, resolution=?, reviewed_by=?, resolved_at=datetime('now')
                    WHERE id=?
                    """,
                    (status, decision, str(reviewer or "system"), int(review["conflict_id"])),
                )
            return dict(c.execute("SELECT * FROM memory_reviews WHERE id=?", (int(review_id),)).fetchone())


    def grant_memory_acl(self, memory_id, principal_type, principal_id, permission, granted_by="system"):
        if principal_type not in {"user", "role", "workspace"}:
            raise ValueError("principal_type must be user, role, or workspace")
        if permission not in {"read", "write", "review", "admin"}:
            raise ValueError("permission must be read, write, review, or admin")
        if not str(principal_id or "").strip():
            raise ValueError("principal_id is required")
        with self._conn() as c:
            c.execute(
                """
                INSERT OR IGNORE INTO memory_acl
                    (memory_id, principal_type, principal_id, permission, granted_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(memory_id), str(principal_type), str(principal_id),
                    str(permission), str(granted_by or "system"),
                ),
            )
            rows = c.execute("SELECT * FROM memory_acl WHERE memory_id=? ORDER BY id", (int(memory_id),)).fetchall()
            return [dict(row) for row in rows]


    def list_memory_acl(self, memory_id):
        with self._conn() as c:
            return [
                dict(row) for row in c.execute(
                    "SELECT * FROM memory_acl WHERE memory_id=? ORDER BY id",
                    (int(memory_id),),
                ).fetchall()
            ]


    def check_memory_access(self, memory_id, actor_id="default", roles=None, workspace_id="default", permission="read"):
        with self._conn() as c:
            memory = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            if not memory:
                return False
            return self._check_memory_access(c, memory, actor_id, roles, workspace_id, permission)


    def _check_memory_access(self, conn, memory, actor_id, roles, workspace_id, permission):
        if str(actor_id) == "system":
            return True
        acl = conn.execute("SELECT * FROM memory_acl WHERE memory_id=?", (int(memory["id"]),)).fetchall()
        if not acl:
            return True
        if actor_id and str(actor_id) == str(memory["owner_id"]):
            return True
        accepted = {
            "read": {"read", "write", "review", "admin"},
            "write": {"write", "admin"},
            "review": {"review", "admin"},
            "admin": {"admin"},
        }.get(permission, {permission})
        role_set = {str(role) for role in (roles or [])}
        for entry in acl:
            principal_match = (
                (entry["principal_type"] == "user" and entry["principal_id"] == str(actor_id))
                or (entry["principal_type"] == "role" and entry["principal_id"] in role_set)
                or (
                    entry["principal_type"] == "workspace"
                    and entry["principal_id"] == str(workspace_id)
                )
            )
            if principal_match and entry["permission"] in accepted:
                return True
        return False


    def record_retrieval_evaluation(self, name, top_k, metrics, cases, created_by="system"):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO retrieval_evaluation_runs
                    (name, top_k, case_count, metrics, cases, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(name or "memory-retrieval"), int(top_k), len(cases or []),
                    json.dumps(metrics or {}, ensure_ascii=False),
                    json.dumps(cases or [], ensure_ascii=False),
                    str(created_by or "system"),
                ),
            )
            return self.get_retrieval_evaluation(int(cursor.lastrowid), conn=c)


    def get_retrieval_evaluation(self, run_id, conn=None):
        def convert(row):
            if not row:
                return None
            item = dict(row)
            item["metrics"] = self._json_loads(item.get("metrics"), {})
            item["cases"] = self._json_loads(item.get("cases"), [])
            return item
        if conn is not None:
            return convert(conn.execute("SELECT * FROM retrieval_evaluation_runs WHERE id=?", (int(run_id),)).fetchone())
        with self._conn() as c:
            return convert(c.execute("SELECT * FROM retrieval_evaluation_runs WHERE id=?", (int(run_id),)).fetchone())


    def list_memories(
        self, memory_type="", include_disabled=False, limit=200,
        actor_id="system", roles=None, workspace_id="default",
    ):
        with self._conn() as c:
            limit = max(1, min(int(limit or 200), 500))
            clauses = []
            params = []
            if memory_type:
                clauses.append("memory_type=?")
                params.append(str(memory_type))
            if not include_disabled:
                clauses.append("enabled=1")
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM memories{where} ORDER BY updated_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [
                self._memory_row_to_dict(r) for r in rows
                if self._check_memory_access(c, r, actor_id, roles, workspace_id, "read")
            ]


    def get_memory(self, memory_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            return self._memory_row_to_dict(row) if row else None


    def set_memory_enabled(self, memory_id, enabled, actor_id="system", change_reason=""):
        with self._conn() as c:
            existing = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            if not existing:
                return None
            version = int(existing["current_version"] or 1) + 1
            c.execute(
                """
                UPDATE memories
                SET enabled=?, current_version=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (1 if enabled else 0, version, int(memory_id)),
            )
            c.execute(
                """
                INSERT INTO memory_versions
                    (memory_id, version, value, source, confidence, enabled,
                     change_type, changed_by, change_reason)
                VALUES (?, ?, ?, ?, ?, ?, 'status_change', ?, ?)
                """,
                (
                    int(memory_id), version, existing["value"], existing["source"],
                    float(existing["confidence"] or 0), 1 if enabled else 0,
                    str(actor_id or "system"), str(change_reason or ""),
                ),
            )
            row = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            return self._memory_row_to_dict(row) if row else None


    def search_memories(
        self, query, memory_type="", limit=20, include_disabled=False,
        actor_id="system", roles=None, workspace_id="default",
    ):
        query = str(query or "").strip()
        if not query:
            return []
        with self._conn() as c:
            limit = max(1, min(int(limit or 20), 100))
            clauses = ["(key LIKE ? OR value LIKE ? OR category LIKE ? OR source LIKE ?)"]
            params = [f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"]
            if memory_type:
                clauses.append("memory_type=?")
                params.append(str(memory_type))
            if not include_disabled:
                clauses.append("enabled=1")
            rows = c.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY confidence DESC, updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [
                self._memory_row_to_dict(r) for r in rows
                if self._check_memory_access(c, r, actor_id, roles, workspace_id, "read")
            ]


    @atomic_workflow
    def set_profile(
        self, key: str, value: str, category: str = "general", importance: float = 0.5,
        source: str = "profile_ingestion", actor_id: str = "system",
        evidence=None, conflict_policy: str = "overwrite",
    ):
        result = self.upsert_memory(
            "profile", key, value, category, source, importance,
            actor_id=actor_id, evidence=evidence, conflict_policy=conflict_policy,
        )
        if result.get("review_required"):
            return result
        with self._conn() as c:
            c.execute("""
                INSERT INTO profiles (category, key, value, importance, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    importance = excluded.importance,
                    updated_at = datetime('now')
            """, (category, key, value, importance))
        return result


    @staticmethod
    def _effective_legacy_memory(connection, row, memory_type):
        if not row:
            return None
        result=dict(row)
        memory=connection.execute("SELECT * FROM memories WHERE memory_type=? AND category=? AND key=?",(memory_type,row['category'],row['key'])).fetchone()
        if memory:
            if not memory['enabled'] or memory['workspace_id']!='default' or memory['owner_id']!='default':
                return None
            result['value']=memory['value']
            result['confidence' if memory_type=='preference' else 'importance']=memory['confidence']
        return result


    def get_profile(self, key: str, category: str = "general") -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM profiles WHERE category=? AND key=?", (category, key)
            ).fetchone()
            return self._effective_legacy_memory(c,row,"profile")


    def get_all_profiles(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM profiles ORDER BY importance DESC").fetchall()
            return [item for row in rows if (item := self._effective_legacy_memory(c,row,"profile")) is not None]


    @atomic_workflow
    def set_preference(
        self, key: str, value: str, category: str = "general", confidence: float = 0.5,
        source: str = "preference_ingestion", actor_id: str = "system",
        evidence=None, conflict_policy: str = "overwrite",
    ):
        result = self.upsert_memory(
            "preference", key, value, category, source, confidence,
            actor_id=actor_id, evidence=evidence, conflict_policy=conflict_policy,
        )
        if result.get("review_required"):
            return result
        with self._conn() as c:
            c.execute("""
                INSERT INTO preferences (category, key, value, confidence, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    updated_at = datetime('now')
            """, (category, key, value, confidence))
        return result


    def get_preference(self, key: str, category: str = "general") -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM preferences WHERE category=? AND key=?", (category, key)
            ).fetchone()
            return self._effective_legacy_memory(c,row,"preference")


    def get_all_preferences(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM preferences ORDER BY confidence DESC").fetchall()
            return [item for row in rows if (item := self._effective_legacy_memory(c,row,"preference")) is not None]
