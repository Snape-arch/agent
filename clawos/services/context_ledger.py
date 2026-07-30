"""Persist explainable context snapshots and review evidence per TaskRun."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class ContextLedgerService:
    def __init__(self, store: Any):
        self.store = store
        with self.store._conn() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS context_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    context_digest TEXT NOT NULL,
                    objective TEXT NOT NULL DEFAULT '',
                    sources TEXT NOT NULL DEFAULT '[]',
                    budget TEXT NOT NULL DEFAULT '{}',
                    omitted_candidates TEXT NOT NULL DEFAULT '[]',
                    trust_policy TEXT NOT NULL DEFAULT '{}',
                    decision_dependencies TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(task_id, context_digest)
                );
                CREATE TABLE IF NOT EXISTS coding_review_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    scope TEXT NOT NULL,
                    target_ref TEXT NOT NULL DEFAULT '',
                    diff_digest TEXT NOT NULL,
                    findings TEXT NOT NULL DEFAULT '[]',
                    tests TEXT NOT NULL DEFAULT '[]',
                    reviewer TEXT NOT NULL DEFAULT '',
                    evidence_digest TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                """
            )

    def record_context(
        self, task_id: int, manifest: dict[str, Any],
        *, omitted_candidates: list[dict] | None = None,
        decision_dependencies: list[dict] | None = None,
    ) -> dict[str, Any]:
        detail = self.store.get_task(int(task_id))
        if not detail:
            raise ValueError("task run not found")
        digest = str(manifest.get("context_digest") or "").strip()
        if not digest:
            digest = hashlib.sha256(
                json.dumps(
                    manifest, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
        with self.store._conn() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO context_ledger
                    (task_id, context_digest, objective, sources, budget,
                     omitted_candidates, trust_policy, decision_dependencies)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(task_id), digest, str(manifest.get("objective") or ""),
                    json.dumps(manifest.get("sources") or []),
                    json.dumps(manifest.get("budget") or {}),
                    json.dumps(omitted_candidates or []),
                    json.dumps(manifest.get("trust_policy") or {}),
                    json.dumps(decision_dependencies or []),
                ),
            )
        self.store.add_task_event(
            int(task_id), "run.context", "Context snapshot recorded",
            data={
                "context_digest": digest,
                "source_count": len(manifest.get("sources") or []),
            },
        )
        return {
            "schema": "clawos.context-ledger-entry.v1",
            "task_id": int(task_id),
            "context_digest": digest,
        }

    def record_review(
        self, task_id: int, review: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.store.get_task(int(task_id)):
            raise ValueError("task run not found")
        validated = self.validate_review(review)
        if not validated["valid"]:
            raise ValueError(
                "invalid review evidence: "
                + ", ".join(validated["errors"])
            )
        payload = {
            "task_id": int(task_id),
            "scope": review["scope"],
            "target_ref": str(review.get("target_ref") or ""),
            "diff_digest": review["diff_digest"],
            "findings": review.get("findings") or [],
            "tests": review.get("tests") or [],
            "reviewer": str(review.get("reviewer") or ""),
        }
        digest = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        with self.store._conn() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO coding_review_evidence
                    (task_id, scope, target_ref, diff_digest, findings, tests,
                     reviewer, evidence_digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(task_id), payload["scope"], payload["target_ref"],
                    payload["diff_digest"], json.dumps(payload["findings"]),
                    json.dumps(payload["tests"]), payload["reviewer"], digest,
                ),
            )
        self.store.add_task_event(
            int(task_id), "run.review", "Coding review evidence recorded",
            data={
                "evidence_digest": digest,
                "scope": payload["scope"],
                "finding_count": len(payload["findings"]),
            },
        )
        return {
            "schema": "clawos.coding-review-evidence.v1",
            **payload,
            "evidence_digest": digest,
            "valid": True,
        }

    def task_ledger(self, task_id: int) -> dict[str, Any]:
        with self.store._conn() as connection:
            contexts = [
                self._decode_context(dict(row))
                for row in connection.execute(
                    """
                    SELECT * FROM context_ledger
                    WHERE task_id=? ORDER BY id
                    """,
                    (int(task_id),),
                ).fetchall()
            ]
            reviews = [
                self._decode_review(dict(row))
                for row in connection.execute(
                    """
                    SELECT * FROM coding_review_evidence
                    WHERE task_id=? ORDER BY id
                    """,
                    (int(task_id),),
                ).fetchall()
            ]
        return {
            "schema": "clawos.task-evidence-ledger.v1",
            "task_id": int(task_id),
            "contexts": contexts,
            "reviews": reviews,
        }

    @staticmethod
    def validate_review(review: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        scope = str(review.get("scope") or "")
        if scope not in {"working_tree", "base_branch", "commit", "pull_request"}:
            errors.append("unsupported review scope")
        digest = str(review.get("diff_digest") or "")
        if not (
            len(digest) == 64
            and all(value in "0123456789abcdef" for value in digest)
        ):
            errors.append("diff_digest must be SHA-256 hex")
        findings = review.get("findings") or []
        if not isinstance(findings, list):
            errors.append("findings must be a list")
            findings = []
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                errors.append(f"finding {index} must be an object")
                continue
            if not str(finding.get("file") or "").strip():
                errors.append(f"finding {index} requires file")
            if int(finding.get("line") or 0) < 1:
                errors.append(f"finding {index} requires a positive line")
            if finding.get("severity") not in {
                "critical", "high", "medium", "low", "info",
            }:
                errors.append(f"finding {index} has invalid severity")
            if not str(finding.get("reason") or "").strip():
                errors.append(f"finding {index} requires reason")
        return {
            "schema": "clawos.coding-review-validation.v1",
            "valid": not errors,
            "errors": errors,
        }

    @staticmethod
    def _decode_context(row: dict[str, Any]) -> dict[str, Any]:
        defaults = {
            "sources": "[]", "budget": "{}",
            "omitted_candidates": "[]", "trust_policy": "{}",
            "decision_dependencies": "[]",
        }
        for key, default in defaults.items():
            row[key] = json.loads(row.get(key) or default)
        return row

    @staticmethod
    def _decode_review(row: dict[str, Any]) -> dict[str, Any]:
        row["findings"] = json.loads(row.get("findings") or "[]")
        row["tests"] = json.loads(row.get("tests") or "[]")
        return row
