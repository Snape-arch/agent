from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MaintenanceService:
    """SQLite migrations, backup/restore, and startup configuration checks."""

    MIGRATIONS = [
        {
            "id": "2026_06_service_boundaries_and_ops",
            "description": "Track service-boundary split, config checks, and local backup support.",
        }
    ]

    def __init__(self, *, store: Any, db_path: Path, base_dir: Path, config: dict[str, Any]):
        self.store = store
        self.db_path = Path(db_path)
        self.base_dir = Path(base_dir)
        self.config = config or {}

    def apply_migrations(self) -> dict[str, Any]:
        if not self.store:
            raise RuntimeError("MemoryOS not initialized")
        applied = []
        with self.store._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id TEXT PRIMARY KEY,
                    description TEXT DEFAULT '',
                    applied_at TEXT NOT NULL
                )
                """
            )
            existing = {
                row["id"]
                for row in conn.execute("SELECT id FROM schema_migrations").fetchall()
            }
            for migration in self.MIGRATIONS:
                if migration["id"] in existing:
                    continue
                conn.execute(
                    "INSERT INTO schema_migrations (id, description, applied_at) VALUES (?, ?, ?)",
                    (migration["id"], migration["description"], self._now()),
                )
                applied.append(migration)
            rows = conn.execute("SELECT * FROM schema_migrations ORDER BY applied_at, id").fetchall()
        return {
            "ok": True,
            "applied": applied,
            "applied_count": len(applied),
            "migrations": [dict(row) for row in rows],
        }

    def list_migrations(self) -> dict[str, Any]:
        if not self.store:
            raise RuntimeError("MemoryOS not initialized")
        with self.store._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id TEXT PRIMARY KEY,
                    description TEXT DEFAULT '',
                    applied_at TEXT NOT NULL
                )
                """
            )
            rows = conn.execute("SELECT * FROM schema_migrations ORDER BY applied_at, id").fetchall()
        return {"migrations": [dict(row) for row in rows], "count": len(rows)}

    def backup_database(self, output_dir: str = "", label: str = "") -> dict[str, Any]:
        if not self.db_path.exists():
            raise RuntimeError("database file does not exist")
        target_dir = Path(output_dir).expanduser() if output_dir else self.base_dir / "backups"
        if not target_dir.is_absolute():
            target_dir = (self.base_dir / target_dir).resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (label or "manual"))
        target = target_dir / f"memoryos-{stamp}-{safe_label}.db"
        source_conn = sqlite3.connect(str(self.db_path))
        try:
            dest_conn = sqlite3.connect(str(target))
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
        meta = {
            "ok": True,
            "path": str(target),
            "bytes": target.stat().st_size,
            "source": str(self.db_path),
            "created_at": self._now(),
        }
        (target.with_suffix(target.suffix + ".json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def config_check(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str, severity: str = "error"):
            checks.append({"name": name, "ok": bool(ok), "detail": detail, "severity": severity})

        add("config_file", (self.base_dir / "config.json").exists(), "config.json present")
        functions_file = Path(self.config.get("functions_file", self.base_dir / "functions.jsonl"))
        if not functions_file.is_absolute():
            functions_file = (self.base_dir / functions_file).resolve()
        add("functions_file", functions_file.exists(), str(functions_file))
        add("database_path", self.db_path.parent.exists(), str(self.db_path))
        add("uploads_dir", (self.base_dir / "uploads").exists() or self.base_dir.exists(), "uploads directory can be created")
        provider = self.config.get("model_provider") or {}
        requires_key = str(provider.get("requires_api_key", "true")).lower() not in {"0", "false", "no"}
        has_key = bool(str(provider.get("api_key") or "").strip()) and "${" not in str(provider.get("api_key") or "")
        add(
            "model_provider",
            bool(provider.get("provider") and provider.get("model") and (has_key or not requires_key or provider.get("provider") == "mock")),
            f"provider={provider.get('provider', '')} model={provider.get('model', '')} key_present={has_key}",
            severity="warning",
        )
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                try:
                    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                finally:
                    conn.close()
                add("sqlite_integrity", integrity == "ok", str(integrity))
            except Exception as exc:
                add("sqlite_integrity", False, type(exc).__name__)
        return {
            "ok": all(item["ok"] or item["severity"] == "warning" for item in checks),
            "checks": checks,
            "checked_at": self._now(),
        }

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
