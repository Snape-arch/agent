from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from services.knowledge_core_service import KnowledgeCoreService


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", _clean(value).lower())


class SensitiveMemoryScanner:
    PATTERNS = {
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
        "api_key": re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"),
        "credential_assignment": re.compile(
            r"\b(?:password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]{6,}", re.I
        ),
        "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
        "phone": re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)"),
    }

    @classmethod
    def scan(cls, value: str) -> dict[str, Any]:
        redacted = str(value or "")
        findings = []
        for name, pattern in cls.PATTERNS.items():
            matches = list(pattern.finditer(redacted))
            if matches:
                findings.append({"type": name, "count": len(matches)})
                redacted = pattern.sub(f"[REDACTED:{name}]", redacted)
        return {"sensitive": bool(findings), "findings": findings, "redacted": redacted}


class SelectiveMemoryService:
    TYPES = {"fact", "project_rule", "user_preference", "failure_experience"}
    TERMINAL_OUTCOMES = {"succeeded", "success", "resolved_failure", "failed_resolved"}

    def __init__(self, store):
        self.store = store
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.store._conn() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS selective_memory_candidates_v1 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    candidate_type TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    success_evidence TEXT NOT NULL DEFAULT '[]',
                    sensitivity TEXT NOT NULL DEFAULT '{}',
                    dedup_key TEXT NOT NULL,
                    duplicate_of INTEGER,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    user_control_required INTEGER NOT NULL DEFAULT 1,
                    promoted_target TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    reviewed_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_selective_memory_review_v1
                    ON selective_memory_candidates_v1(status,owner_id,workspace_id,id DESC);
                CREATE INDEX IF NOT EXISTS idx_selective_memory_dedup_v1
                    ON selective_memory_candidates_v1(dedup_key,owner_id,workspace_id);
            """)

    def propose_from_task(
        self,
        *,
        task_id: str | int,
        outcome: str,
        candidates: list[dict[str, Any]],
        success_evidence: list[dict[str, Any]] | None = None,
        session_id: str = "",
        owner_id: str = "default",
        workspace_id: str = "default",
    ) -> dict[str, Any]:
        normalized_outcome = str(outcome or "").strip().lower()
        evidence = [dict(item or {}) for item in success_evidence or []]
        evidence_ok = normalized_outcome in self.TERMINAL_OUTCOMES and self._evidence_sufficient(evidence)
        rows = []
        for raw in candidates or []:
            item = dict(raw or {})
            candidate_type = str(item.get("type") or item.get("candidate_type") or "").strip().lower()
            if candidate_type not in self.TYPES:
                raise ValueError(f"candidate type must be one of {sorted(self.TYPES)}")
            content = _clean(item.get("content") or item.get("value"))
            key = _clean(item.get("key") or content[:96])
            if not content or not key:
                raise ValueError("memory candidate key and content are required")
            scan = SensitiveMemoryScanner.scan(content)
            stored_content = scan["redacted"]
            dedup_key = hashlib.sha256(
                f"{candidate_type}|{_normalized(key)}|{_normalized(stored_content)}".encode("utf-8")
            ).hexdigest()
            duplicate = self._find_duplicate(candidate_type, stored_content, dedup_key, owner_id, workspace_id)
            explicit_preference = bool(item.get("explicit_user_statement"))
            eligible = evidence_ok and (candidate_type != "user_preference" or explicit_preference)
            if scan["sensitive"]:
                status = "blocked_sensitive"
            elif duplicate:
                status = "duplicate"
            elif not eligible:
                status = "rejected_insufficient_evidence"
            else:
                status = "pending_review"
            now = datetime.now(timezone.utc).isoformat()
            with self.store._conn() as connection:
                cursor = connection.execute(
                    """INSERT INTO selective_memory_candidates_v1
                       (task_id,session_id,owner_id,workspace_id,candidate_type,memory_key,content,
                        source_ref,success_evidence,sensitivity,dedup_key,duplicate_of,status,confidence,
                        user_control_required,metadata,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(task_id), str(session_id), str(owner_id), str(workspace_id), candidate_type,
                     key, stored_content, str(item.get("source_ref") or f"task:{task_id}"), _json(evidence),
                     _json({"sensitive": scan["sensitive"], "findings": scan["findings"]}), dedup_key,
                     int(duplicate["id"]) if duplicate else None, status,
                     max(0.0, min(float(item.get("confidence", 0.7)), 1.0)), 1,
                     _json(item.get("metadata") or {}), now, now),
                )
                row = connection.execute(
                    "SELECT * FROM selective_memory_candidates_v1 WHERE id=?", (int(cursor.lastrowid),)
                ).fetchone()
            rows.append(self._row(dict(row)))
        return {
            "schema": "clawos.selective-memory-proposal.v1", "task_id": str(task_id),
            "evidence_sufficient": evidence_ok, "candidates": rows,
            "review_required": sum(item["status"] == "pending_review" for item in rows),
            "blocked_sensitive": sum(item["status"] == "blocked_sensitive" for item in rows),
            "duplicates": sum(item["status"] == "duplicate" for item in rows),
        }

    def review(self, candidate_id: int, decision: str, *, reviewer: str, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("confirmed=true is required")
        decision = str(decision or "").strip().lower()
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        now = datetime.now(timezone.utc).isoformat()
        with self.store._conn() as connection:
            row = connection.execute(
                "SELECT * FROM selective_memory_candidates_v1 WHERE id=?", (int(candidate_id),)
            ).fetchone()
            if not row:
                raise ValueError("memory candidate not found")
            if row["status"] != "pending_review":
                raise ValueError("only pending_review candidates can be reviewed")
            status = "approved" if decision == "approve" else "rejected"
            connection.execute(
                """UPDATE selective_memory_candidates_v1
                   SET status=?,reviewed_by=?,reviewed_at=?,updated_at=? WHERE id=?""",
                (status, str(reviewer or "user"), now, now, int(candidate_id)),
            )
            updated = connection.execute(
                "SELECT * FROM selective_memory_candidates_v1 WHERE id=?", (int(candidate_id),)
            ).fetchone()
        return self._row(dict(updated))

    def promote(self, candidate_id: int, *, actor_id: str, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("confirmed=true is required")
        with self.store._conn() as connection:
            row = connection.execute(
                "SELECT * FROM selective_memory_candidates_v1 WHERE id=?", (int(candidate_id),)
            ).fetchone()
        if not row:
            raise ValueError("memory candidate not found")
        item = self._row(dict(row))
        if item["status"] != "approved":
            raise ValueError("candidate must be approved before promotion")
        if item["sensitivity"].get("sensitive"):
            raise ValueError("sensitive candidates cannot be promoted")
        evidence = item["success_evidence"]
        if item["candidate_type"] == "fact":
            promoted = KnowledgeCoreService(self.store).absorb(
                title=item["memory_key"], statement=item["content"], category="learned_fact",
                knowledge_type="fact", source_ref=item["source_ref"], source_type="task_evidence",
                confidence=item["confidence"], owner_id=item["owner_id"], workspace_id=item["workspace_id"],
                metadata={"memory_candidate_id": item["id"], "success_evidence": evidence},
                changed_by=actor_id,
            )
            target = {"kind": "knowledge_v2", "id": promoted["id"]}
        else:
            mapping = {
                "project_rule": "project", "user_preference": "preference",
                "failure_experience": "experience",
            }
            promoted = self.store.upsert_memory(
                mapping[item["candidate_type"]], item["memory_key"], item["content"],
                category="selective_learning", source=item["source_ref"], confidence=item["confidence"],
                actor_id=actor_id, owner_id=item["owner_id"], workspace_id=item["workspace_id"],
                evidence=evidence, change_reason=f"approved candidate {item['id']}", conflict_policy="review",
            )
            target = {"kind": "memory", "id": promoted["id"], "memory_type": mapping[item["candidate_type"]]}
        now = datetime.now(timezone.utc).isoformat()
        with self.store._conn() as connection:
            connection.execute(
                """UPDATE selective_memory_candidates_v1
                   SET status='promoted',promoted_target=?,updated_at=? WHERE id=?""",
                (_json(target), now, int(candidate_id)),
            )
            updated = connection.execute(
                "SELECT * FROM selective_memory_candidates_v1 WHERE id=?", (int(candidate_id),)
            ).fetchone()
        return self._row(dict(updated))

    def list(self, *, status: str = "", owner_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        clauses, params = [], []
        if status:
            clauses.append("status=?")
            params.append(status)
        if owner_id:
            clauses.append("owner_id=?")
            params.append(owner_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 2000)))
        with self.store._conn() as connection:
            rows = connection.execute(
                f"SELECT * FROM selective_memory_candidates_v1{where} ORDER BY id DESC LIMIT ?", params,
            ).fetchall()
        return [self._row(dict(row)) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.store._conn() as connection:
            rows = connection.execute(
                "SELECT status,COUNT(*) count FROM selective_memory_candidates_v1 GROUP BY status"
            ).fetchall()
        counts = {row["status"]: int(row["count"]) for row in rows}
        return {
            "count": sum(counts.values()), "status_counts": counts,
            "pending_review": counts.get("pending_review", 0),
            "blocked_sensitive": counts.get("blocked_sensitive", 0),
            "promoted": counts.get("promoted", 0),
        }

    def _find_duplicate(
        self, candidate_type: str, content: str, dedup_key: str, owner_id: str, workspace_id: str,
    ) -> dict[str, Any] | None:
        with self.store._conn() as connection:
            exact = connection.execute(
                """SELECT * FROM selective_memory_candidates_v1
                   WHERE dedup_key=? AND owner_id=? AND workspace_id=? ORDER BY id DESC LIMIT 1""",
                (dedup_key, owner_id, workspace_id),
            ).fetchone()
            if exact:
                return dict(exact)
            rows = connection.execute(
                """SELECT id,content FROM selective_memory_candidates_v1
                   WHERE candidate_type=? AND owner_id=? AND workspace_id=?
                     AND status IN ('pending_review','approved','promoted') ORDER BY id DESC LIMIT 300""",
                (candidate_type, owner_id, workspace_id),
            ).fetchall()
        normalized = _normalized(content)
        for row in rows:
            if SequenceMatcher(None, normalized, _normalized(row["content"])).ratio() >= 0.92:
                return dict(row)
        return None

    @staticmethod
    def _evidence_sufficient(evidence: list[dict[str, Any]]) -> bool:
        accepted = {"test_passed", "user_accepted", "delivered", "verified", "resolved"}
        return any(
            str(item.get("type") or "").lower() in accepted
            and bool(item.get("artifact") or item.get("digest") or item.get("reference"))
            for item in evidence
        )

    @staticmethod
    def _row(item: dict[str, Any]) -> dict[str, Any]:
        for key, fallback in (
            ("success_evidence", []), ("sensitivity", {}),
            ("promoted_target", {}), ("metadata", {}),
        ):
            item[key] = _loads(item.get(key), fallback)
        item["user_control_required"] = bool(item.get("user_control_required"))
        return item
