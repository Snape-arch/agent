from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalized(value: Any) -> str:
    text = _clean(value).lower()
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff.%+-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(value: Any) -> set[str]:
    normalized = _normalized(value)
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_.%+-]*", normalized))
    for segment in re.findall(r"[\u4e00-\u9fff]+", normalized):
        tokens.add(segment)
        tokens.update(segment[index:index + 2] for index in range(max(0, len(segment) - 1)))
    return {token for token in tokens if token}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else (value if value is not None else fallback)
    except (TypeError, json.JSONDecodeError):
        return fallback


class KnowledgeCoreService:
    """Evidence-first knowledge layer that coexists with the legacy knowledge table."""

    SCHEMA_VERSION = 2

    def __init__(self, store):
        self.store = store
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.store._conn() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_records_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_key TEXT NOT NULL,
                    knowledge_type TEXT NOT NULL DEFAULT 'claim',
                    category TEXT NOT NULL DEFAULT 'domain',
                    title TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    normalized_statement TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    valid_from TEXT DEFAULT '',
                    valid_until TEXT DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    current_version INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    legacy_knowledge_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(canonical_key, owner_id, workspace_id)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_v2_scope_status
                    ON knowledge_records_v2(workspace_id, owner_id, status, category);
                CREATE INDEX IF NOT EXISTS idx_knowledge_v2_legacy
                    ON knowledge_records_v2(legacy_knowledge_id);
                CREATE TABLE IF NOT EXISTS knowledge_legacy_links_v2 (
                    legacy_knowledge_id INTEGER PRIMARY KEY,
                    knowledge_id INTEGER NOT NULL,
                    linked_at TEXT NOT NULL,
                    FOREIGN KEY(knowledge_id) REFERENCES knowledge_records_v2(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_legacy_links_v2_record
                    ON knowledge_legacy_links_v2(knowledge_id);
                CREATE TABLE IF NOT EXISTS knowledge_sources_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id INTEGER NOT NULL,
                    source_ref TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    excerpt TEXT NOT NULL DEFAULT '',
                    locator TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    authority REAL NOT NULL DEFAULT 0.5,
                    captured_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(knowledge_id) REFERENCES knowledge_records_v2(id) ON DELETE CASCADE,
                    UNIQUE(knowledge_id, source_ref, content_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_sources_v2_record
                    ON knowledge_sources_v2(knowledge_id, id);
                CREATE TABLE IF NOT EXISTS knowledge_entities_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'concept',
                    aliases TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    UNIQUE(canonical_name, entity_type)
                );
                CREATE TABLE IF NOT EXISTS knowledge_relations_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_kind TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    evidence_source_id INTEGER,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(source_kind, source_id, relation_type, target_kind, target_id)
                );
                CREATE TABLE IF NOT EXISTS knowledge_versions_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    statement TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    change_type TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    changed_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(knowledge_id) REFERENCES knowledge_records_v2(id) ON DELETE CASCADE,
                    UNIQUE(knowledge_id, version)
                );
                CREATE TABLE IF NOT EXISTS knowledge_conflicts_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id INTEGER NOT NULL,
                    existing_statement TEXT NOT NULL,
                    candidate_statement TEXT NOT NULL,
                    conflict_type TEXT NOT NULL,
                    candidate_source_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    resolution TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(knowledge_id) REFERENCES knowledge_records_v2(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_conflicts_v2_status
                    ON knowledge_conflicts_v2(status, id DESC);
                CREATE TABLE IF NOT EXISTS knowledge_usage_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    usage_type TEXT NOT NULL DEFAULT 'retrieved',
                    outcome TEXT NOT NULL DEFAULT 'unknown',
                    query TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(knowledge_id) REFERENCES knowledge_records_v2(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS knowledge_vector_outbox_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    knowledge_id INTEGER NOT NULL,
                    operation TEXT NOT NULL,
                    payload_version INTEGER NOT NULL DEFAULT 1,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(knowledge_id) REFERENCES knowledge_records_v2(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_vector_outbox_pending
                    ON knowledge_vector_outbox_v2(processed_at,id);
                CREATE TABLE IF NOT EXISTS knowledge_vector_index_state_v2 (
                    index_name TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    embedding_fingerprint TEXT NOT NULL,
                    last_outbox_id INTEGER NOT NULL DEFAULT 0,
                    indexed_records INTEGER NOT NULL DEFAULT 0,
                    last_full_sync_at TEXT NOT NULL DEFAULT '',
                    last_incremental_sync_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def canonical_key(title: str, category: str = "domain", knowledge_type: str = "claim") -> str:
        subject = _normalized(title)
        raw = f"{knowledge_type}|{category}|{subject}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def infer_entities(title: str, statement: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
        candidates = list(tags or [])
        candidates.extend(re.findall(r"\b[A-Z][A-Za-z0-9_.+-]{1,30}\b", title))
        candidates.extend(re.findall(r"\b(?:[A-Z]{2,}[A-Z0-9_.+-]*|[A-Za-z]+\d+[A-Za-z0-9_.+-]*)\b", statement))
        candidates.extend(re.findall(r"[\u4e00-\u9fff]{2,12}", title))
        seen, rows = set(), []
        for value in candidates:
            name = _clean(value)
            key = _normalized(name)
            if not key or key in seen or key.isdigit():
                continue
            seen.add(key)
            rows.append({"name": name, "type": "concept", "confidence": 0.65, "metadata": {"origin": "inferred"}})
        return rows[:12]

    @staticmethod
    def extract_claims(text: str, *, max_claims: int = 12) -> list[str]:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        sentences = re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", clean)
        claims, seen = [], set()
        for sentence in sentences:
            claim = _clean(sentence).strip("-•* ")
            normalized = _normalized(claim)
            if len(claim) < 24 or len(claim) > 600 or normalized in seen:
                continue
            if not re.search(r"[A-Za-z\u4e00-\u9fff]", claim):
                continue
            seen.add(normalized)
            claims.append(claim)
            if len(claims) >= max(1, min(int(max_claims), 50)):
                break
        if not claims and len(clean) >= 24:
            claims.append(clean[:600])
        return claims

    @staticmethod
    def classify_claim(statement: str) -> str:
        value = _normalized(statement)
        cues = (
            ("limitation", ("limitation", "limited by", "fails to", "cannot", "局限", "不足", "不能")),
            ("result", ("result", "achieved", "improved", "outperform", "we found", "结果", "提升", "达到", "优于")),
            ("method", ("method", "we use", "we propose", "algorithm", "architecture", "方法", "采用", "提出", "算法")),
            ("recommendation", ("should", "recommend", "建议", "应当", "需要")),
            ("definition", (" is defined as ", " refers to ", "定义为", "是指")),
        )
        padded = f" {value} "
        for claim_type, markers in cues:
            if any(marker in padded for marker in markers):
                return claim_type
        return "claim"

    @staticmethod
    def near_duplicate_score(left: str, right: str) -> float:
        left_value, right_value = _normalized(left), _normalized(right)
        if not left_value or not right_value:
            return 0.0
        left_numbers = set(re.findall(r"[-+]?\d+(?:\.\d+)?%?", left_value))
        right_numbers = set(re.findall(r"[-+]?\d+(?:\.\d+)?%?", right_value))
        if left_numbers != right_numbers:
            return 0.0
        negations = (" not ", " no ", "never", "cannot", "不", "未", "无", "不能")
        if any(token in f" {left_value} " for token in negations) != any(
            token in f" {right_value} " for token in negations
        ):
            return 0.0

        def grams(value: str) -> set[str]:
            compact = re.sub(r"\s+", "", value)
            return {compact[index:index + 3] for index in range(max(1, len(compact) - 2))}

        left_grams, right_grams = grams(left_value), grams(right_value)
        overlap = len(left_grams & right_grams) / max(1, min(len(left_grams), len(right_grams)))
        length_ratio = min(len(left_value), len(right_value)) / max(len(left_value), len(right_value))
        return overlap * 0.8 + length_ratio * 0.2

    @staticmethod
    def source_locator(source_ref: str) -> str:
        value = str(source_ref or "")
        return value.split("#", 1)[1] if "#" in value else ""

    @staticmethod
    def source_authority(source_ref: str, source_type: str = "manual") -> float:
        source_type = _normalized(source_type)
        if source_type in {"peer reviewed", "official", "official docs", "primary source"}:
            return 0.95
        host = (urlparse(str(source_ref or "")).hostname or "").lower()
        if host.endswith((".gov", ".edu")) or host in {
            "nature.com", "www.nature.com", "arxiv.org", "pubmed.ncbi.nlm.nih.gov",
            "developers.openai.com", "learn.chatgpt.com", "docs.anthropic.com", "code.claude.com",
        }:
            return 0.9
        if str(source_ref or "").startswith("doc:"):
            return 0.78
        if source_type in {"document", "document claim", "legacy backfill"}:
            return 0.72
        if source_type in {"user", "reviewer"}:
            return 0.7
        return 0.5

    @staticmethod
    def conflict_type(existing: str, candidate: str) -> str:
        left, right = _normalized(existing), _normalized(candidate)
        if left == right:
            return "none"
        left_numbers = set(re.findall(r"[-+]?\d+(?:\.\d+)?%?", left))
        right_numbers = set(re.findall(r"[-+]?\d+(?:\.\d+)?%?", right))
        if left_numbers and right_numbers and left_numbers != right_numbers:
            return "numeric_disagreement"
        negations = (" not ", " no ", "never", "cannot", "不", "未", "无", "不能")
        left_negative = any(token in f" {left} " for token in negations)
        right_negative = any(token in f" {right} " for token in negations)
        if left_negative != right_negative:
            return "polarity_disagreement"
        left_tokens, right_tokens = set(left.split()), set(right.split())
        overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
        return "value_disagreement" if overlap >= 0.35 else "distinct_claim"

    def absorb(
        self,
        *,
        title: str,
        statement: str,
        category: str = "domain",
        knowledge_type: str = "claim",
        source_ref: str = "manual",
        source_type: str = "manual",
        excerpt: str = "",
        locator: str = "",
        confidence: float = 0.7,
        authority: float | None = None,
        valid_from: str = "",
        valid_until: str = "",
        entities: list[dict[str, Any] | str] | None = None,
        relations: list[dict[str, Any]] | None = None,
        owner_id: str = "default",
        workspace_id: str = "default",
        metadata: dict[str, Any] | None = None,
        legacy_knowledge_id: int | None = None,
        changed_by: str = "system",
    ) -> dict[str, Any]:
        title, statement = _clean(title), _clean(statement)
        if not title or not statement:
            raise ValueError("title and statement are required")
        category = _clean(category) or "domain"
        key = self.canonical_key(title, category, knowledge_type)
        normalized = _normalized(statement)
        now = _iso_now()
        source_ref = _clean(source_ref) or "manual"
        authority = self.source_authority(source_ref, source_type) if authority is None else float(authority)
        excerpt = _clean(excerpt) or statement[:1200]
        content_hash = hashlib.sha256(f"{source_ref}|{excerpt}".encode("utf-8")).hexdigest()
        outcome = "created"
        conflict: dict[str, Any] | None = None
        with self.store._conn() as connection:
            from .document_evidence_policy import source_usable
            if not source_usable(connection, source_ref):
                raise ValueError("Document source requires review before knowledge publication")
            existing = connection.execute(
                "SELECT * FROM knowledge_records_v2 WHERE canonical_key=? AND owner_id=? AND workspace_id=?",
                (key, owner_id, workspace_id),
            ).fetchone()
            near_duplicate = False
            if not existing:
                candidates = connection.execute(
                    """SELECT * FROM knowledge_records_v2
                       WHERE category=? AND knowledge_type=? AND owner_id=? AND workspace_id=? AND status='active'
                       ORDER BY updated_at DESC LIMIT 200""",
                    (category, knowledge_type, owner_id, workspace_id),
                ).fetchall()
                best_row, best_score = None, 0.0
                for candidate in candidates:
                    score = self.near_duplicate_score(candidate["statement"], statement)
                    if score > best_score:
                        best_row, best_score = candidate, score
                if best_row is not None and best_score >= 0.9:
                    existing = best_row
                    near_duplicate = True
            if existing:
                knowledge_id = int(existing["id"])
                if existing["status"] == "expired" and changed_by in {"legacy_update", "reviewer", "user"}:
                    version = int(existing["current_version"]) + 1
                    connection.execute(
                        """UPDATE knowledge_records_v2 SET statement=?,normalized_statement=?,status='active',
                           confidence=?,valid_from=?,valid_until=?,current_version=?,metadata=?,legacy_knowledge_id=?,updated_at=?
                           WHERE id=?""",
                        (statement, normalized, float(confidence), valid_from, valid_until, version,
                         _json(metadata or {}), legacy_knowledge_id, now, knowledge_id),
                    )
                    connection.execute(
                        """INSERT INTO knowledge_versions_v2
                           (knowledge_id,version,statement,status,confidence,change_type,reason,changed_by,created_at)
                           VALUES (?,?,?,'active',?,'update','explicit record update',?,?)""",
                        (knowledge_id, version, statement, float(confidence), changed_by, now),
                    )
                    outcome = "updated"
                elif existing["normalized_statement"] == normalized or near_duplicate:
                    if existing["status"] == "expired":
                        version = int(existing["current_version"]) + 1
                        connection.execute(
                            """UPDATE knowledge_records_v2 SET status='active',valid_until=?,confidence=MAX(confidence,?),
                               current_version=?,updated_at=? WHERE id=?""",
                            (valid_until, float(confidence), version, now, knowledge_id),
                        )
                        connection.execute(
                            """INSERT INTO knowledge_versions_v2
                               (knowledge_id,version,statement,status,confidence,change_type,reason,changed_by,created_at)
                               VALUES (?,?,?,'active',?,'reactivate','source observed again',?,?)""",
                            (knowledge_id, version, statement, float(confidence), changed_by, now),
                        )
                        outcome = "reactivated"
                    else:
                        outcome = "near_duplicate_merged" if near_duplicate else "source_merged"
                        connection.execute(
                            "UPDATE knowledge_records_v2 SET confidence=MAX(confidence, ?), updated_at=? WHERE id=?",
                            (float(confidence), now, knowledge_id),
                        )
                else:
                    kind = self.conflict_type(existing["statement"], statement)
                    if kind == "distinct_claim":
                        key = hashlib.sha256(f"{key}|{normalized}".encode("utf-8")).hexdigest()
                        existing = None
                    else:
                        cursor = connection.execute(
                            """INSERT INTO knowledge_conflicts_v2
                               (knowledge_id,existing_statement,candidate_statement,conflict_type,candidate_source_ref,created_at)
                               VALUES (?,?,?,?,?,?)""",
                            (knowledge_id, existing["statement"], statement, kind, source_ref, now),
                        )
                        connection.execute(
                            "UPDATE knowledge_records_v2 SET status='conflicted', updated_at=? WHERE id=?",
                            (now, knowledge_id),
                        )
                        conflict = {"id": int(cursor.lastrowid), "type": kind, "status": "pending"}
                        outcome = "conflict_recorded"
            if not existing:
                cursor = connection.execute(
                    """INSERT INTO knowledge_records_v2
                       (canonical_key,knowledge_type,category,title,statement,normalized_statement,status,confidence,
                        valid_from,valid_until,owner_id,workspace_id,current_version,metadata,legacy_knowledge_id,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,'active',?,?,?,?,?,1,?,?,?,?)""",
                    (key, knowledge_type, category, title, statement, normalized, float(confidence),
                     valid_from, valid_until, owner_id, workspace_id, _json(metadata or {}), legacy_knowledge_id, now, now),
                )
                knowledge_id = int(cursor.lastrowid)
                connection.execute(
                    """INSERT INTO knowledge_versions_v2
                       (knowledge_id,version,statement,status,confidence,change_type,changed_by,created_at)
                       VALUES (?,1,?,'active',?,'create',?,?)""",
                    (knowledge_id, statement, float(confidence), changed_by, now),
                )
                outcome = "created"
            source_cursor = connection.execute(
                """INSERT OR IGNORE INTO knowledge_sources_v2
                   (knowledge_id,source_ref,source_type,excerpt,locator,content_hash,authority,captured_at,metadata)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (knowledge_id, source_ref, source_type, excerpt, locator, content_hash,
                 float(authority), now, _json(metadata or {})),
            )
            source_row = connection.execute(
                "SELECT id FROM knowledge_sources_v2 WHERE knowledge_id=? AND source_ref=? AND content_hash=?",
                (knowledge_id, source_ref, content_hash),
            ).fetchone()
            source_id = int(source_row["id"]) if source_row else int(source_cursor.lastrowid or 0)
            if legacy_knowledge_id:
                connection.execute(
                    "INSERT OR REPLACE INTO knowledge_legacy_links_v2 (legacy_knowledge_id,knowledge_id,linked_at) VALUES (?,?,?)",
                    (int(legacy_knowledge_id), knowledge_id, now),
                )
            self._upsert_entities(connection, knowledge_id, source_id, entities or [], now)
            self._upsert_relations(connection, knowledge_id, source_id, relations or [], now)
            row = connection.execute("SELECT * FROM knowledge_records_v2 WHERE id=?", (knowledge_id,)).fetchone()
            self._enqueue_projection(
                connection, knowledge_id,
                "upsert" if row["status"] == "active" else "delete",
                int(row["current_version"]), now,
            )
        result = self._hydrate(dict(row))
        result.update({"absorption_outcome": outcome, "source_id": source_id, "conflict": conflict})
        return result

    @staticmethod
    def _enqueue_projection(connection, knowledge_id: int, operation: str, version: int, now: str) -> None:
        connection.execute(
            """INSERT INTO knowledge_vector_outbox_v2
               (knowledge_id,operation,payload_version,created_at) VALUES (?,?,?,?)""",
            (int(knowledge_id), operation, max(1, int(version)), now),
        )

    def _upsert_entities(self, connection, knowledge_id: int, source_id: int, entities: list[Any], now: str) -> None:
        for raw in entities:
            item = {"name": raw} if isinstance(raw, str) else dict(raw or {})
            name = _clean(item.get("name"))
            if not name:
                continue
            entity_type = _clean(item.get("type")) or "concept"
            canonical = _normalized(name)
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_entities_v2 (canonical_name,entity_type,aliases,metadata) VALUES (?,?,?,?)",
                (canonical, entity_type, _json(item.get("aliases") or [name]), _json(item.get("metadata") or {})),
            )
            entity = connection.execute(
                "SELECT id FROM knowledge_entities_v2 WHERE canonical_name=? AND entity_type=?",
                (canonical, entity_type),
            ).fetchone()
            connection.execute(
                """INSERT OR IGNORE INTO knowledge_relations_v2
                   (source_kind,source_id,relation_type,target_kind,target_id,confidence,evidence_source_id,metadata,created_at)
                   VALUES ('knowledge',?,'mentions','entity',?,?,?,?,?)""",
                (knowledge_id, int(entity["id"]), float(item.get("confidence", 0.8)), source_id or None,
                 _json(item.get("metadata") or {}), now),
            )

    def _upsert_relations(self, connection, knowledge_id: int, source_id: int, relations: list[dict[str, Any]], now: str) -> None:
        for item in relations:
            target_id = int(item.get("target_id") or 0)
            relation_type = _clean(item.get("type"))
            if not target_id or not relation_type:
                continue
            connection.execute(
                """INSERT OR IGNORE INTO knowledge_relations_v2
                   (source_kind,source_id,relation_type,target_kind,target_id,confidence,evidence_source_id,metadata,created_at)
                   VALUES ('knowledge',?,?,?, ?,?,?,?,?)""",
                (knowledge_id, relation_type, _clean(item.get("target_kind")) or "knowledge", target_id,
                 float(item.get("confidence", 0.7)), source_id or None, _json(item.get("metadata") or {}), now),
            )

    def expire(self, knowledge_id: int, reason: str, changed_by: str = "system") -> dict[str, Any] | None:
        now = _iso_now()
        with self.store._conn() as connection:
            row = connection.execute("SELECT * FROM knowledge_records_v2 WHERE id=?", (int(knowledge_id),)).fetchone()
            if not row:
                return None
            version = int(row["current_version"]) + 1
            connection.execute(
                "UPDATE knowledge_records_v2 SET status='expired',valid_until=?,current_version=?,updated_at=? WHERE id=?",
                (now, version, now, int(knowledge_id)),
            )
            connection.execute(
                """INSERT INTO knowledge_versions_v2
                   (knowledge_id,version,statement,status,confidence,change_type,reason,changed_by,created_at)
                   VALUES (?,?,?,'expired',?,'expire',?,?,?)""",
                (int(knowledge_id), version, row["statement"], float(row["confidence"]), reason, changed_by, now),
            )
            updated = connection.execute("SELECT * FROM knowledge_records_v2 WHERE id=?", (int(knowledge_id),)).fetchone()
            self._enqueue_projection(connection, int(knowledge_id), "delete", version, now)
        return self._hydrate(dict(updated))

    def expire_legacy(self, legacy_knowledge_id: int, reason: str, changed_by: str = "system") -> int:
        with self.store._conn() as connection:
            rows = connection.execute(
                """SELECT DISTINCT k.id FROM knowledge_records_v2 k
                   LEFT JOIN knowledge_legacy_links_v2 l ON l.knowledge_id=k.id
                   WHERE (k.legacy_knowledge_id=? OR l.legacy_knowledge_id=?) AND k.status<>'expired'""",
                (int(legacy_knowledge_id), int(legacy_knowledge_id)),
            ).fetchall()
        for row in rows:
            self.expire(int(row["id"]), reason, changed_by)
        return len(rows)

    def expire_source_prefix(self, prefix: str, reason: str = "source_replaced") -> int:
        with self.store._conn() as connection:
            rows = connection.execute(
                """SELECT DISTINCT k.id FROM knowledge_records_v2 k
                   JOIN knowledge_sources_v2 s ON s.knowledge_id=k.id
                   WHERE s.source_ref LIKE ? AND k.status<>'expired'""",
                (f"{prefix}%",),
            ).fetchall()
        for row in rows:
            self.expire(int(row["id"]), reason)
        return len(rows)

    def resolve_conflict(
        self, conflict_id: int, decision: str, *, reviewer: str = "system", reason: str = ""
    ) -> dict[str, Any]:
        if decision not in {"keep_existing", "accept_candidate", "keep_both"}:
            raise ValueError("decision must be keep_existing, accept_candidate, or keep_both")
        now = _iso_now()
        with self.store._conn() as connection:
            conflict = connection.execute(
                "SELECT * FROM knowledge_conflicts_v2 WHERE id=? AND status='pending'", (int(conflict_id),),
            ).fetchone()
            if not conflict:
                raise ValueError("pending conflict not found")
            record = connection.execute(
                "SELECT * FROM knowledge_records_v2 WHERE id=?", (int(conflict["knowledge_id"]),),
            ).fetchone()
            version = int(record["current_version"]) + 1
            statement = record["statement"]
            if decision == "accept_candidate":
                statement = conflict["candidate_statement"]
            connection.execute(
                """UPDATE knowledge_records_v2 SET statement=?,normalized_statement=?,status='active',
                   current_version=?,updated_at=? WHERE id=?""",
                (statement, _normalized(statement), version, now, int(record["id"])),
            )
            connection.execute(
                """INSERT INTO knowledge_versions_v2
                   (knowledge_id,version,statement,status,confidence,change_type,reason,changed_by,created_at)
                   VALUES (?,?,?,'active',?,'conflict_resolution',?,?,?)""",
                (int(record["id"]), version, statement, float(record["confidence"]), reason, reviewer, now),
            )
            connection.execute(
                "UPDATE knowledge_conflicts_v2 SET status='resolved',resolution=?,resolved_at=? WHERE id=?",
                (decision, now, int(conflict_id)),
            )
            updated = connection.execute("SELECT * FROM knowledge_records_v2 WHERE id=?", (int(record["id"]),)).fetchone()
            self._enqueue_projection(connection, int(record["id"]), "upsert", version, now)
        return self._hydrate(dict(updated))

    def search(
        self, query: str, *, category: str = "", limit: int = 10,
        owner_id: str = "default", workspace_id: str = "default",
        include_conflicted: bool = False,
    ) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        now = _iso_now()
        statuses = ("active", "conflicted") if include_conflicted else ("active",)
        placeholders = ",".join("?" for _ in statuses)
        with self.store._conn() as connection:
            params: list[Any] = [owner_id, workspace_id, *statuses, now]
            category_clause = ""
            if category:
                category_clause = " AND k.category=?"
                params.append(category)
            rows = connection.execute(
                f"""SELECT k.*,
                    (SELECT COUNT(*) FROM knowledge_sources_v2 s WHERE s.knowledge_id=k.id) AS source_count,
                    (SELECT MAX(authority) FROM knowledge_sources_v2 s WHERE s.knowledge_id=k.id) AS max_authority,
                    (SELECT COALESCE(AVG(CASE
                        WHEN u.outcome IN ('success','accepted','helpful','delivered') THEN 1.0
                        WHEN u.outcome IN ('failed','rejected','harmful') THEN -1.0
                        ELSE 0.0 END),0.0) FROM knowledge_usage_v2 u WHERE u.knowledge_id=k.id) AS utility
                    FROM knowledge_records_v2 k
                    WHERE k.owner_id=? AND k.workspace_id=? AND k.status IN ({placeholders})
                      AND (k.valid_until='' OR k.valid_until>?) {category_clause}
                    ORDER BY k.confidence DESC, k.updated_at DESC LIMIT 1000""",
                tuple(params),
            ).fetchall()
            scored = []
            for row in rows:
                item = dict(row)
                text_tokens = _tokens(f"{item['title']} {item['statement']}")
                lexical = len(query_tokens & text_tokens) / max(1, len(query_tokens))
                if query_tokens and lexical == 0:
                    continue
                try:
                    age_days = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(
                        str(item.get("updated_at") or "").replace("Z", "+00:00")
                    )).total_seconds() / 86400)
                except (TypeError, ValueError):
                    age_days = 365.0
                freshness = 1.0 / (1.0 + age_days / 180.0)
                utility = (float(item.get("utility") or 0.0) + 1.0) / 2.0
                item["retrieval_score"] = round(
                    lexical * 0.50 + float(item["confidence"]) * 0.18
                    + float(item.get("max_authority") or 0.5) * 0.12
                    + freshness * 0.10 + utility * 0.10,
                    4,
                )
                item["lexical_score"] = round(lexical, 4)
                item["freshness_score"] = round(freshness, 4)
                item["utility_score"] = round(utility, 4)
                sources = connection.execute(
                    "SELECT * FROM knowledge_sources_v2 WHERE knowledge_id=? ORDER BY authority DESC,id LIMIT 5",
                    (int(item["id"]),),
                ).fetchall()
                from .document_evidence_policy import source_usable
                if any(not source_usable(connection, source["source_ref"]) for source in sources):
                    continue
                item["sources"] = [self._source(dict(source)) for source in sources]
                scored.append(self._hydrate(item))
        return sorted(scored, key=lambda item: item["retrieval_score"], reverse=True)[:max(1, int(limit))]

    def task_context_pack(
        self, query: str, *, category: str = "", limit: int = 6, token_budget: int = 1600,
        owner_id: str = "default", workspace_id: str = "default",
    ) -> dict[str, Any]:
        results = self.search(
            query, category=category, limit=max(limit * 2, limit),
            owner_id=owner_id, workspace_id=workspace_id,
        )
        budget_chars = max(800, int(token_budget) * 4)
        selected, used = [], 0
        for item in results:
            sources = item.get("sources") or []
            citation = sources[0]["citation"] if sources else ""
            compact = {
                "knowledge_id": item["id"], "title": item["title"], "statement": item["statement"],
                "confidence": item["confidence"], "status": item["status"], "citation": citation,
                "source_count": item.get("source_count", len(sources)), "retrieval_score": item.get("retrieval_score", 0),
                "lexical_score": item.get("lexical_score", 0),
            }
            size = len(_json(compact))
            if selected and used + size > budget_chars:
                break
            selected.append(compact)
            used += size
            if len(selected) >= limit:
                break
        digest = hashlib.sha256(_json(selected).encode("utf-8")).hexdigest()
        evidence_sufficient = (
            bool(selected)
            and any(item["citation"] for item in selected)
            and float(selected[0].get("retrieval_score") or 0) >= 0.55
            and float(selected[0].get("lexical_score") or 0) >= 0.25
        )
        return {
            "schema": "clawos.knowledge-context.v1", "schema_version": 2, "query": query, "items": selected,
            "citation_count": sum(1 for item in selected if item["citation"]),
            "token_budget": token_budget, "estimated_tokens": (used + 3) // 4,
            "context_digest": digest, "evidence_sufficient": evidence_sufficient,
            "stop_retrieval": evidence_sufficient,
            "scope": {"owner_id": owner_id, "workspace_id": workspace_id},
        }

    def grounded_answer(
        self, query: str, *, category: str = "", limit: int = 6, token_budget: int = 1600,
        session_id: str = "", task_id: str = "", owner_id: str = "default", workspace_id: str = "default",
    ) -> dict[str, Any]:
        pack = self.task_context_pack(
            query, category=category, limit=limit, token_budget=token_budget,
            owner_id=owner_id, workspace_id=workspace_id,
        )
        claims = []
        for item in pack["items"] if pack["evidence_sufficient"] else []:
            claims.append({
                "text": item["statement"], "citation": item["citation"],
                "knowledge_id": item["knowledge_id"], "confidence": item["confidence"],
                "status": "supported" if item["citation"] else "missing_source",
            })
        used_ids = [int(item["knowledge_id"]) for item in claims if item["status"] == "supported"]
        if used_ids:
            self.record_usage(
                used_ids, query=query, session_id=session_id, task_id=task_id,
                usage_type="answer_cited", outcome="delivered",
            )
        answer = "\n".join(
            f"- {item['text']} [{item['citation']}]" for item in claims if item["status"] == "supported"
        )
        final_answer = answer or "现有知识库中没有找到带来源、可直接支持该问题的知识。"
        from services.answer_quality_service import ClaimEvidenceAnswerValidator
        answer_validation = ClaimEvidenceAnswerValidator.validate(
            query=query,
            answer=final_answer,
            evidence=[{
                "id": item["citation"], "citation": item["citation"], "text": item["statement"],
            } for item in pack["items"]],
            must_refuse=not bool(claims),
            claims=[{"text": item["text"], "citations": [item["citation"]]} for item in claims] if claims else None,
        )
        grounded = bool(claims) and all(item["status"] == "supported" for item in claims)
        if not answer_validation["valid"]:
            final_answer = "现有知识库证据未通过声明—证据校验，暂不生成结论。"
            grounded = False
        return {
            "schema": "clawos.knowledge-answer.v1", "query": query,
            "answer": final_answer,
            "claims": claims, "citations": sorted({item["citation"] for item in claims if item["citation"]}),
            "knowledge_ids": used_ids, "grounded": grounded,
            "answer_validation": answer_validation,
            "generation_mode": "deterministic_evidence_composition",
            "context_digest": pack["context_digest"], "truth_boundary": "Composes stored supported claims; it does not add unstored synthesis or model inference.",
        }

    def record_usage(self, knowledge_ids: list[int], *, query: str, session_id: str = "", task_id: str = "", usage_type: str = "used", outcome: str = "unknown") -> None:
        now = _iso_now()
        with self.store._conn() as connection:
            for knowledge_id in sorted({int(item) for item in knowledge_ids if int(item) > 0}):
                connection.execute(
                    "INSERT INTO knowledge_usage_v2 (knowledge_id,session_id,task_id,usage_type,outcome,query,created_at) VALUES (?,?,?,?,?,?,?)",
                    (knowledge_id, session_id, task_id, usage_type, outcome, query, now),
                )
                if outcome not in {"unknown", "pending"}:
                    row = connection.execute(
                        "SELECT current_version FROM knowledge_records_v2 WHERE id=?", (knowledge_id,),
                    ).fetchone()
                    if row:
                        self._enqueue_projection(connection, knowledge_id, "upsert", int(row["current_version"]), now)

    def list_conflicts(self, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        with self.store._conn() as connection:
            rows = connection.execute(
                """SELECT c.*,k.title,k.category,k.confidence FROM knowledge_conflicts_v2 c
                   JOIN knowledge_records_v2 k ON k.id=c.knowledge_id
                   WHERE (?='' OR c.status=?) ORDER BY c.id DESC LIMIT ?""",
                (status, status, max(1, min(int(limit), 500))),
            ).fetchall()
        return [dict(row) for row in rows]

    def backfill_legacy(self, *, limit: int = 10000) -> dict[str, Any]:
        with self.store._conn() as connection:
            rows = connection.execute(
                """SELECT k.* FROM knowledge k LEFT JOIN knowledge_legacy_links_v2 l
                   ON l.legacy_knowledge_id=k.id WHERE l.legacy_knowledge_id IS NULL ORDER BY k.id LIMIT ?""",
                (max(1, min(int(limit), 100000)),),
            ).fetchall()
        migrated = failed = 0
        failures = []
        for row in rows:
            item = dict(row)
            tags = _loads(item.get("tags"), [])
            try:
                self.absorb(
                    title=item["title"], statement=item["content"], category=item["category"],
                    source_ref=item.get("source") or f"legacy:knowledge:{item['id']}",
                    source_type="legacy_backfill", excerpt=str(item["content"])[:1200],
                    locator=self.source_locator(item.get("source", "")), confidence=float(item.get("confidence") or 0.5),
                    entities=self.infer_entities(item["title"], item["content"], tags),
                    metadata={"tags": tags, "backfilled": True}, legacy_knowledge_id=int(item["id"]),
                    changed_by="legacy_backfill",
                )
                migrated += 1
            except (OSError, ValueError, TypeError) as exc:
                failed += 1
                failures.append({"legacy_id": item["id"], "error": f"{type(exc).__name__}: {exc}"})
        return {"candidate_count": len(rows), "migrated": migrated, "failed": failed, "failures": failures[:20]}

    def stats(self) -> dict[str, Any]:
        with self.store._conn() as connection:
            counts = {
                "records": connection.execute("SELECT COUNT(*) FROM knowledge_records_v2").fetchone()[0],
                "active": connection.execute("SELECT COUNT(*) FROM knowledge_records_v2 WHERE status='active'").fetchone()[0],
                "conflicted": connection.execute("SELECT COUNT(*) FROM knowledge_records_v2 WHERE status='conflicted'").fetchone()[0],
                "expired": connection.execute("SELECT COUNT(*) FROM knowledge_records_v2 WHERE status='expired'").fetchone()[0],
                "sources": connection.execute("SELECT COUNT(*) FROM knowledge_sources_v2").fetchone()[0],
                "entities": connection.execute("SELECT COUNT(*) FROM knowledge_entities_v2").fetchone()[0],
                "relations": connection.execute("SELECT COUNT(*) FROM knowledge_relations_v2").fetchone()[0],
                "pending_conflicts": connection.execute("SELECT COUNT(*) FROM knowledge_conflicts_v2 WHERE status='pending'").fetchone()[0],
                "usage_events": connection.execute("SELECT COUNT(*) FROM knowledge_usage_v2").fetchone()[0],
                "vector_outbox_pending": connection.execute(
                    "SELECT COUNT(*) FROM knowledge_vector_outbox_v2 WHERE processed_at=''"
                ).fetchone()[0],
            }
        counts["schema_version"] = self.SCHEMA_VERSION
        return counts

    @staticmethod
    def _source(item: dict[str, Any]) -> dict[str, Any]:
        item["metadata"] = _loads(item.get("metadata"), {})
        source_ref = str(item.get("source_ref") or "")
        locator = str(item.get("locator") or "")
        item["citation"] = source_ref if not locator or "#" in source_ref else f"{source_ref}#{locator}"
        return item

    @staticmethod
    def _hydrate(item: dict[str, Any]) -> dict[str, Any]:
        item["metadata"] = _loads(item.get("metadata"), {})
        return item
