"""Baseline schema and additive upgrades for existing databases."""
import sqlite3
from pathlib import Path

from memoryos.persistence import Repository

BASE_SCHEMA = Path(__file__).with_suffix('.sql').read_text(encoding='utf-8')


class Schema(Repository):
    def initialize(self):
        with self._conn() as c:
            c.executescript(BASE_SCHEMA)
            self._ensure_columns(c, "experiences", {
                "solution": "TEXT DEFAULT ''",
                "tags": "TEXT DEFAULT '[]'",
                "importance": "REAL DEFAULT 0.5",
            })
            self._ensure_columns(c, "knowledge", {
                "source": "TEXT DEFAULT ''",
                "tags": "TEXT DEFAULT '[]'",
                "confidence": "REAL DEFAULT 0.5",
                "access_count": "INTEGER DEFAULT 0",
                "updated_at": "TEXT DEFAULT ''",
            })
            self._ensure_columns(c, "skill_records", {
                "feedback": "TEXT DEFAULT ''",
                "quality_score": "REAL DEFAULT 0.5",
            })
            self._ensure_columns(c, "tool_executions", {
                "arguments": "TEXT DEFAULT '{}'",
                "result": "TEXT DEFAULT '{}'",
                "status": "TEXT NOT NULL DEFAULT 'success'",
                "duration_ms": "REAL DEFAULT 0",
                "requires_confirmation": "INTEGER DEFAULT 0",
            })
            self._ensure_columns(c, "tasks", {
                "source": "TEXT DEFAULT ''",
                "metadata": "TEXT DEFAULT '{}'",
                "idempotency_key": "TEXT DEFAULT ''",
                "retry_of": "INTEGER",
                "attempt": "INTEGER NOT NULL DEFAULT 1",
                "cancellation_requested": "INTEGER NOT NULL DEFAULT 0",
                "resume_state": "TEXT DEFAULT ''",
                "completed_at": "TEXT DEFAULT ''",
            })
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency "
                "ON tasks(idempotency_key) WHERE idempotency_key <> ''"
            )
            self._ensure_columns(c, "task_steps", {
                "input_data": "TEXT DEFAULT '{}'",
                "output_data": "TEXT DEFAULT '{}'",
                "error": "TEXT DEFAULT ''",
                "completed_at": "TEXT DEFAULT ''",
            })
            self._ensure_columns(c, "task_events", {
                "message": "TEXT DEFAULT ''",
                "data": "TEXT DEFAULT '{}'",
            })
            self._ensure_columns(c, "document_chunks", {
                "metadata": "TEXT DEFAULT '{}'",
            })
            self._ensure_columns(c, "run_records", {
                "schema": "TEXT NOT NULL DEFAULT 'clawos.run.v1'",
                "actor": "TEXT DEFAULT 'system'",
                "scenario": "TEXT DEFAULT ''",
                "started_at": "TEXT DEFAULT ''",
                "completed_at": "TEXT DEFAULT ''",
                "inputs": "TEXT NOT NULL DEFAULT '{}'",
                "outputs": "TEXT NOT NULL DEFAULT '{}'",
                "metrics": "TEXT NOT NULL DEFAULT '{}'",
                "workflow": "TEXT NOT NULL DEFAULT '{}'",
                "provenance": "TEXT NOT NULL DEFAULT '{}'",
                "verification": "TEXT NOT NULL DEFAULT '{}'",
                "parent_run_id": "TEXT DEFAULT ''",
                "tags": "TEXT NOT NULL DEFAULT '[]'",
                "updated_at": "TEXT DEFAULT ''",
            })
            self._ensure_columns(c, "self_evolution_runs", {
                "release_stage": "TEXT NOT NULL DEFAULT 'candidate'",
                "traffic_percent": "REAL NOT NULL DEFAULT 0",
                "quality_signals": "TEXT NOT NULL DEFAULT '{}'",
                "baseline_policy_version": "INTEGER NOT NULL DEFAULT -1",
            })
            self._ensure_columns(c, "memories", {
                "source": "TEXT DEFAULT ''",
                "confidence": "REAL DEFAULT 0.5",
                "enabled": "INTEGER DEFAULT 1",
                "owner_id": "TEXT NOT NULL DEFAULT 'default'",
                "workspace_id": "TEXT NOT NULL DEFAULT 'default'",
                "current_version": "INTEGER NOT NULL DEFAULT 1",
                "updated_at": "TEXT DEFAULT ''",
            })
            self._backfill_memory_versions(c)

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, spec in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")

    def _backfill_memory_versions(self, conn: sqlite3.Connection):
        rows = conn.execute(
            """
            SELECT m.* FROM memories m
            WHERE NOT EXISTS (
                SELECT 1 FROM memory_versions v WHERE v.memory_id=m.id
            )
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                """
                INSERT INTO memory_versions
                    (memory_id, version, value, source, confidence, enabled, change_type, changed_by, change_reason)
                VALUES (?, 1, ?, ?, ?, ?, 'create', 'migration', 'Backfilled existing memory')
                """,
                (
                    int(row["id"]),
                    row["value"],
                    row["source"],
                    float(row["confidence"] or 0),
                    int(row["enabled"] or 0),
                ),
            )
            conn.execute("UPDATE memories SET current_version=1 WHERE id=?", (int(row["id"]),))
