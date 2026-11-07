from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from memoryos.persistence import Repository


class RunsRepository(Repository):
    """Persistence operations for runs."""

    def save_run_record(self, record: dict[str, Any]) -> dict[str, Any]:
        run_id = str(record.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        artifacts = list(record.get("artifacts") or [])
        evidence = list(record.get("evidence") or [])
        failures = list(record.get("failure_cases") or [])
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO run_records
                    (run_id, schema, run_type, title, status, actor, scenario, started_at,
                     completed_at, inputs, outputs, metrics, workflow, provenance,
                     verification, parent_run_id, tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(run_id) DO UPDATE SET
                    schema=excluded.schema,
                    run_type=excluded.run_type,
                    title=excluded.title,
                    status=excluded.status,
                    actor=excluded.actor,
                    scenario=excluded.scenario,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    inputs=excluded.inputs,
                    outputs=excluded.outputs,
                    metrics=excluded.metrics,
                    workflow=excluded.workflow,
                    provenance=excluded.provenance,
                    verification=excluded.verification,
                    parent_run_id=excluded.parent_run_id,
                    tags=excluded.tags,
                    updated_at=datetime('now')
                """,
                (
                    run_id,
                    str(record.get("schema") or "clawos.run.v1"),
                    str(record.get("run_type") or "generic"),
                    str(record.get("title") or run_id),
                    str(record.get("status") or "created"),
                    str(record.get("actor") or "system"),
                    str(record.get("scenario") or ""),
                    str(record.get("started_at") or ""),
                    str(record.get("completed_at") or ""),
                    json.dumps(record.get("inputs") or {}, ensure_ascii=False),
                    json.dumps(record.get("outputs") or {}, ensure_ascii=False),
                    json.dumps(record.get("metrics") or {}, ensure_ascii=False),
                    json.dumps(record.get("workflow") or {}, ensure_ascii=False),
                    json.dumps(record.get("provenance") or {}, ensure_ascii=False),
                    json.dumps(record.get("verification") or {}, ensure_ascii=False),
                    str(record.get("parent_run_id") or ""),
                    json.dumps(record.get("tags") or [], ensure_ascii=False),
                ),
            )
            c.execute("DELETE FROM run_artifacts WHERE run_id=?", (run_id,))
            c.execute("DELETE FROM run_evidence WHERE run_id=?", (run_id,))
            c.execute("DELETE FROM run_failure_cases WHERE run_id=?", (run_id,))
            for index, item in enumerate(artifacts, 1):
                c.execute(
                    """
                    INSERT INTO run_artifacts
                        (run_id, artifact_id, kind, title, uri, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(item.get("artifact_id") or f"art-{index:03d}"),
                        str(item.get("kind") or "file"),
                        str(item.get("title") or ""),
                        str(item.get("uri") or item.get("path") or ""),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                        str(item.get("created_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
                    ),
                )
            for index, item in enumerate(evidence, 1):
                c.execute(
                    """
                    INSERT INTO run_evidence
                        (run_id, evidence_id, source, claim, citation, score, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        run_id,
                        str(item.get("evidence_id") or f"ev-{index:03d}"),
                        str(item.get("source") or ""),
                        str(item.get("claim") or ""),
                        str(item.get("citation") or ""),
                        item.get("score"),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                    ),
                )
            for index, item in enumerate(failures, 1):
                c.execute(
                    """
                    INSERT INTO run_failure_cases
                        (run_id, failure_id, category, reason, severity, input_summary,
                         output_summary, remediation, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(item.get("failure_id") or f"fc-{index:03d}"),
                        str(item.get("category") or ""),
                        str(item.get("reason") or ""),
                        str(item.get("severity") or "medium"),
                        str(item.get("input_summary") or ""),
                        str(item.get("output_summary") or ""),
                        str(item.get("remediation") or ""),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                        str(item.get("created_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
                    ),
                )
        return self.get_run_record(run_id)


    def get_run_record(self, run_id: str) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM run_records WHERE run_id=?", (str(run_id),)).fetchone()
            if not row:
                return {}
            artifacts = c.execute("SELECT * FROM run_artifacts WHERE run_id=? ORDER BY id", (str(run_id),)).fetchall()
            evidence = c.execute("SELECT * FROM run_evidence WHERE run_id=? ORDER BY id", (str(run_id),)).fetchall()
            failures = c.execute("SELECT * FROM run_failure_cases WHERE run_id=? ORDER BY id", (str(run_id),)).fetchall()
            return self._run_record_from_rows(row, artifacts, evidence, failures)


    def list_run_records(self, run_type="", status="", limit=50) -> list[dict[str, Any]]:
        where, params = [], []
        if run_type:
            where.append("run_type=?")
            params.append(str(run_type))
        if status:
            where.append("status=?")
            params.append(str(status))
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM run_records{clause} ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                (*params, max(1, min(int(limit or 50), 200))),
            ).fetchall()
            if not rows:
                return []
            run_ids = [str(row["run_id"]) for row in rows]
            placeholders = ",".join("?" for _ in run_ids)
            artifacts = c.execute(
                f"SELECT * FROM run_artifacts WHERE run_id IN ({placeholders}) ORDER BY id",
                run_ids,
            ).fetchall()
            evidence = c.execute(
                f"SELECT * FROM run_evidence WHERE run_id IN ({placeholders}) ORDER BY id",
                run_ids,
            ).fetchall()
            failures = c.execute(
                f"SELECT * FROM run_failure_cases WHERE run_id IN ({placeholders}) ORDER BY id",
                run_ids,
            ).fetchall()
            artifacts_by_run = self._group_run_rows(artifacts)
            evidence_by_run = self._group_run_rows(evidence)
            failures_by_run = self._group_run_rows(failures)
            return [
                self._run_record_from_rows(
                    row,
                    artifacts_by_run.get(str(row["run_id"]), []),
                    evidence_by_run.get(str(row["run_id"]), []),
                    failures_by_run.get(str(row["run_id"]), []),
                )
                for row in rows
            ]


    def list_failure_cases(self, category="", severity="", limit=50) -> list[dict[str, Any]]:
        where, params = [], []
        if category:
            where.append("category=?")
            params.append(str(category))
        if severity:
            where.append("severity=?")
            params.append(str(severity))
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM run_failure_cases{clause} ORDER BY id DESC LIMIT ?",
                (*params, max(1, min(int(limit or 50), 200))),
            ).fetchall()
            return [self._failure_case_row_to_dict(row) for row in rows]


    def _run_record_from_rows(self, row, artifacts, evidence, failures) -> dict[str, Any]:
        item = dict(row)
        for key, default in (
            ("inputs", {}),
            ("outputs", {}),
            ("metrics", {}),
            ("workflow", {}),
            ("provenance", {}),
            ("verification", {}),
            ("tags", []),
        ):
            item[key] = self._json_loads(item.get(key), default)
        item["artifacts"] = [self._artifact_row_to_dict(row) for row in artifacts]
        item["evidence"] = [self._run_evidence_row_to_dict(row) for row in evidence]
        item["failure_cases"] = [self._failure_case_row_to_dict(row) for row in failures]
        return item


    @staticmethod
    def _group_run_rows(rows) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = {}
        for row in rows:
            grouped.setdefault(str(row["run_id"]), []).append(row)
        return grouped


    def _artifact_row_to_dict(self, row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        return item


    def _run_evidence_row_to_dict(self, row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        return item


    def _failure_case_row_to_dict(self, row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        item["source_run_id"] = item.get("run_id", "")
        return item
