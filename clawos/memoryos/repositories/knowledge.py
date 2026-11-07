from __future__ import annotations

import json
import sqlite3

from memoryos.persistence import Repository, atomic_workflow


class KnowledgeRepository(Repository):
    """Persistence operations for knowledge."""

    @atomic_workflow
    def add_knowledge(self, title, content, category="domain", source="", tags=None, confidence=0.5, *, reviewed_chunk_id=None):
        with self._conn() as c:
            from services.document_evidence_policy import source_usable
            if not source_usable(c, source):
                raise ValueError("Document source requires review before knowledge publication")
            if reviewed_chunk_id is not None:
                evidence = c.execute("SELECT * FROM document_chunks WHERE id=? AND citation=?", (reviewed_chunk_id,source)).fetchone()
                if not evidence or evidence["content"] != content or self._json_loads(evidence["metadata"], {}).get("review_state") != "approved":
                    raise ValueError("Reviewed evidence changed before publication; reload")
                existing = c.execute("SELECT * FROM knowledge WHERE source=? AND content=?", (source,content)).fetchone()
                if existing:
                    return dict(existing)
            cursor = c.execute("INSERT INTO knowledge (category,title,content,source,tags,confidence) VALUES (?,?,?,?,?,?)",
                               (category, title, content, source, json.dumps(tags or []), confidence))
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            result = dict(row)
        try:
            from services.knowledge_core_service import KnowledgeCoreService
            absorbed = KnowledgeCoreService(self).absorb(
                title=title, statement=content, category=category, source_ref=source or "manual",
                source_type="document" if str(source).startswith("doc:") else "manual",
                excerpt=content[:1200], locator=KnowledgeCoreService.source_locator(source),
                confidence=confidence, metadata={"tags": tags or []},
                entities=KnowledgeCoreService.infer_entities(title, content, tags or []),
                legacy_knowledge_id=int(result["id"]),
            )
            result["knowledge_v2_id"] = absorbed["id"]
            result["absorption_outcome"] = absorbed["absorption_outcome"]
        except (ImportError, OSError, sqlite3.DatabaseError, ValueError):
            if getattr(self._transaction_state, "connection", None) is not None:
                raise
            result["knowledge_v2_id"] = None
        return result


    def absorb_knowledge(self, **payload):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).absorb(**payload)


    def search_knowledge_v2(self, query, category="", limit=10, **scope):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).search(query, category=category, limit=limit, **scope)


    def knowledge_context_pack(self, query, category="", limit=6, token_budget=1600, **scope):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).task_context_pack(
            query, category=category, limit=limit, token_budget=token_budget, **scope,
        )


    def answer_from_knowledge(
        self, query, category="", limit=6, token_budget=1600,
        session_id="", task_id="", **scope,
    ):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).grounded_answer(
            query, category=category, limit=limit, token_budget=token_budget,
            session_id=session_id, task_id=task_id, **scope,
        )


    def knowledge_v2_stats(self):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).stats()


    def resolve_knowledge_conflict(self, conflict_id, decision, reviewer="system", reason=""):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).resolve_conflict(
            conflict_id, decision, reviewer=reviewer, reason=reason,
        )


    def list_knowledge_conflicts(self, status="pending", limit=100):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).list_conflicts(status, limit)


    def backfill_knowledge_v2(self, limit=10000):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).backfill_legacy(limit=limit)


    def record_knowledge_usage(self, knowledge_ids, **payload):
        from services.knowledge_core_service import KnowledgeCoreService
        return KnowledgeCoreService(self).record_usage(knowledge_ids, **payload)


    def search_knowledge(self, query, category="", limit=10):
        with self._conn() as c:
            if category:
                rows = c.execute("SELECT * FROM knowledge WHERE category=? AND (title LIKE ? OR content LIKE ?) ORDER BY confidence DESC LIMIT ?",
                                 (category, f"%{query}%", f"%{query}%", limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM knowledge WHERE title LIKE ? OR content LIKE ? ORDER BY confidence DESC LIMIT ?",
                                 (f"%{query}%", f"%{query}%", limit)).fetchall()
            from services.document_evidence_policy import source_usable
            rows = [r for r in rows if source_usable(c, r["source"])]
            for r in rows:
                c.execute("UPDATE knowledge SET access_count=access_count+1 WHERE id=?", (r["id"],))
            return [dict(r) for r in rows]


    def get_knowledge_by_id(self, kid):
        with self._conn() as c:
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (kid,)).fetchone()
            from services.document_evidence_policy import source_usable
            if row and not source_usable(c, row["source"]):
                return None
            if row: c.execute("UPDATE knowledge SET access_count=access_count+1 WHERE id=?", (kid,))
            return dict(row) if row else None


    @atomic_workflow
    def update_knowledge(self, kid, title, content, category="domain", source="", tags=None, confidence=0.5):
        try:
            from services.knowledge_core_service import KnowledgeCoreService
            KnowledgeCoreService(self).expire_legacy(int(kid), "legacy_record_updated")
        except (ImportError, OSError, sqlite3.DatabaseError, ValueError):
            raise
        with self._conn() as c:
            c.execute(
                """
                UPDATE knowledge
                SET title=?, content=?, category=?, source=?, tags=?, confidence=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (title, content, category, source, json.dumps(tags or []), confidence, int(kid)),
            )
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (int(kid),)).fetchone()
            result = dict(row) if row else None
        if result:
            try:
                from services.knowledge_core_service import KnowledgeCoreService
                absorbed = KnowledgeCoreService(self).absorb(
                    title=title, statement=content, category=category, source_ref=source or "manual",
                    source_type="document" if str(source).startswith("doc:") else "manual",
                    excerpt=content[:1200], locator=KnowledgeCoreService.source_locator(source),
                    confidence=confidence, metadata={"tags": tags or []},
                    entities=KnowledgeCoreService.infer_entities(title, content, tags or []),
                    legacy_knowledge_id=int(kid), changed_by="legacy_update",
                )
                result["knowledge_v2_id"] = absorbed["id"]
            except (ImportError, OSError, sqlite3.DatabaseError, ValueError, TypeError):
                raise
        return result


    @atomic_workflow
    def delete_knowledge(self, kid):
        try:
            from services.knowledge_core_service import KnowledgeCoreService
            KnowledgeCoreService(self).expire_legacy(int(kid), "legacy_record_deleted")
        except (ImportError, OSError, sqlite3.DatabaseError, ValueError):
            raise
        with self._conn() as c:
            cursor = c.execute("DELETE FROM knowledge WHERE id=?", (int(kid),))
            return cursor.rowcount > 0


    @atomic_workflow
    def delete_knowledge_by_source_prefix(self, prefix):
        try:
            from services.knowledge_core_service import KnowledgeCoreService
            KnowledgeCoreService(self).expire_source_prefix(prefix)
        except (ImportError, OSError, sqlite3.DatabaseError, ValueError):
            if getattr(self._transaction_state, "connection", None) is not None:
                raise
        with self._conn() as c:
            cursor = c.execute("DELETE FROM knowledge WHERE source LIKE ?", (f"{prefix}%",))
            return cursor.rowcount


    def list_knowledge(self, category=""):
        with self._conn() as c:
            sql = "SELECT * FROM knowledge" + (" WHERE category=?" if category else "") + " ORDER BY access_count DESC"
            rows = c.execute(sql, (category,) if category else ()).fetchall()
            from services.document_evidence_policy import source_usable
            return [dict(r) for r in rows if source_usable(c, r["source"])]


    def document_source_usable(self, source, knowledge_id=None, version=None):
        from services.document_evidence_policy import source_usable
        with self._conn() as c:
            if str(source).startswith("doc:") and knowledge_id is not None:
                if not c.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_records_v2'").fetchone():
                    return False
                record = c.execute("SELECT status,current_version FROM knowledge_records_v2 WHERE id=?", (int(knowledge_id),)).fetchone()
                if not record or record["status"] != "active" or version is not None and int(version) != record["current_version"]:
                    return False
            return source_usable(c, source)


    def add_document(self, title, filename="", file_path="", file_hash="", mime_type="", category="domain", extractor="", status="ready", metadata=None, *, document_id=0):
        with self._conn() as c:
            existing = c.execute("SELECT id FROM documents WHERE file_hash=? AND file_hash<>''", (file_hash,)).fetchone() if not document_id else c.execute("SELECT id FROM documents WHERE id=?",(int(document_id),)).fetchone()
            if document_id and not existing:
                raise ValueError("Document not found")
            meta = json.dumps(metadata or {}, ensure_ascii=False)
            if existing:
                doc_id = int(existing["id"])
                c.execute("DELETE FROM document_chunks WHERE document_id=?", (doc_id,))
                c.execute(
                    """
                    UPDATE documents
                    SET title=?, filename=?, file_path=?, mime_type=?, category=?, extractor=?, status=?, metadata=?, updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (title, filename, file_path, mime_type, category, extractor, status, meta, doc_id),
                )
            else:
                cursor = c.execute(
                    """
                    INSERT INTO documents
                        (title, filename, file_path, file_hash, mime_type, category, extractor, status, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (title, filename, file_path, file_hash, mime_type, category, extractor, status, meta),
                )
                doc_id = int(cursor.lastrowid)
            row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            result = dict(row)
            try:
                result["metadata"] = json.loads(result.get("metadata") or "{}")
            except json.JSONDecodeError:
                result["metadata"] = {}
            return result


    def add_document_chunk(self, document_id, chunk_index, content, citation="", metadata=None):
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO document_chunks (document_id, chunk_index, content, citation, metadata) VALUES (?, ?, ?, ?, ?)",
                (int(document_id), int(chunk_index), content, citation, json.dumps(metadata or {}, ensure_ascii=False)),
            )
            row = c.execute("SELECT * FROM document_chunks WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            item = dict(row)
            item["metadata"] = self._json_loads(item.get("metadata"), {})
            return item


    def list_documents(self, category="", *, include_review=False):
        with self._conn() as c:
            sql = """
                SELECT d.*,
                       (SELECT COUNT(*) FROM document_chunks dc WHERE dc.document_id=d.id) AS chunk_count
                FROM documents d
            """ + (" WHERE d.category=?" if category else "") + " ORDER BY d.updated_at DESC, d.id DESC"
            rows = c.execute(sql, (category,) if category else ()).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(item.get("metadata") or "{}")
                except json.JSONDecodeError:
                    item["metadata"] = {}
                if not include_review:
                    from services.document_evidence_policy import safe_document
                    item = safe_document(item)
                items.append(item)
            return items


    def get_document(self, document_id, *, include_review=False):
        with self._conn() as c:
            row = c.execute("SELECT * FROM documents WHERE id=?", (int(document_id),)).fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            if not include_review:
                from services.document_evidence_policy import safe_document
                item = safe_document(item)
            return item


    def get_document_chunks(self, document_id, limit=20, *, include_review=False, offset=0):
        with self._conn() as c:
            gate = "" if include_review else " AND json_valid(metadata) AND COALESCE(json_extract(metadata, '$.review_required'), 0)=0"
            rows = c.execute(
                "SELECT * FROM document_chunks WHERE document_id=?" + gate + " ORDER BY chunk_index LIMIT ? OFFSET ?",
                (int(document_id), int(limit), max(0,int(offset))),
            ).fetchall()
            items = [dict(r) for r in rows]
            for item in items:
                item["metadata"] = self._json_loads(item.get("metadata"), {})
            return items


    def iter_evidence_chunks(self, document_id=0, category=""):
        """Stream all scoped candidates so late passages cannot be hidden by top-k."""
        with self._conn() as c:
            filters, params = [], []
            if document_id:
                filters.append("d.id=?")
                params.append(int(document_id))
            if category:
                filters.append("d.category=?")
                params.append(category)
            where = " WHERE " + " AND ".join(filters) if filters else ""
            cursor = c.execute("SELECT dc.*, d.title, d.filename, d.category FROM document_chunks dc JOIN documents d ON d.id=dc.document_id" + where + " ORDER BY d.id,dc.chunk_index", params)
            while True:
                rows = cursor.fetchmany(128)
                if not rows:
                    break
                for row in rows:
                    item = dict(row)
                    try:
                        item["metadata"] = json.loads(item.get("metadata") or "{}")
                        if not isinstance(item["metadata"], dict):
                            continue
                    except (TypeError, ValueError):
                        continue
                    yield item


    def search_document_chunks(self, query, category="", limit=10):
        with self._conn() as c:
            params = [f"%{query}%", f"%{query}%"]
            where = "(d.title LIKE ? OR dc.content LIKE ?)"
            where += " AND json_valid(dc.metadata) AND COALESCE(json_extract(dc.metadata, '$.review_required'), 0)=0"
            if category:
                where = "d.category=? AND " + where
                params.insert(0, category)
            rows = c.execute(
                f"""
                SELECT dc.*, d.title, d.filename, d.category
                FROM document_chunks dc
                JOIN documents d ON d.id=dc.document_id
                WHERE {where}
                ORDER BY d.updated_at DESC, dc.chunk_index
                LIMIT ?
                """,
                (*params, int(limit)),
            ).fetchall()
            items = [dict(r) for r in rows]
            for item in items:
                item["metadata"] = self._json_loads(item.get("metadata"), {})
            return items
