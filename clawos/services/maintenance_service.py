from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MaintenanceService:
    """SQLite migrations, backup/restore, and startup configuration checks."""

    MIGRATIONS = [
        {
            "id": "2026_06_service_boundaries_and_ops",
            "description": "Track service-boundary split, config checks, and local backup support.",
        },
        {
            "id": "2026_07_feishu_connector",
            "description": "Feishu connector: feishu_messages, feishu_summaries, feishu_approvals, feishu_dispatches for an audited, approval-gated outbound loop.",
            "apply": "feishu_connector_schema",
        },
    ]

    # Migration apply handlers keyed by the migration "apply" tag. Each receives
    # the open migration transaction connection and must be idempotent.
    _APPLY_HANDLERS = {
        "feishu_connector_schema": "_apply_feishu_connector_schema",
    }

    def _apply_feishu_connector_schema(self, conn: sqlite3.Connection) -> None:
        from services.feishu.schema import create_feishu_tables

        create_feishu_tables(conn)

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
                handler_name = self._APPLY_HANDLERS.get(migration.get("apply", ""))
                if handler_name:
                    getattr(self, handler_name)(conn)
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
        safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in (label or "manual"))[:80]
        target = target_dir / f"memoryos-{stamp}-{safe_label}-{uuid.uuid4().hex[:12]}.db"
        source_conn = sqlite3.connect(str(self.db_path))
        try:
            dest_conn = sqlite3.connect(str(target))
            try:
                source_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source_conn.close()
        self._assert_sqlite_ok(target)
        meta = {
            "ok": True,
            "path": str(target),
            "bytes": target.stat().st_size,
            "source": str(self.db_path),
            "created_at": self._now(),
            "integrity": "ok",
            "scope": "sqlite_only; uploaded source files and external vector assets are not included",
        }
        (target.with_suffix(target.suffix + ".json")).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return meta

    def restore_database(self, backup_path: str, *, confirm: bool = False, label: str = "pre-restore") -> dict[str, Any]:
        if not confirm:
            raise ValueError("restore requires confirm=true")
        source = Path(backup_path or "").expanduser()
        if not source.is_absolute():
            source = (self.base_dir / source).resolve()
        if not source.exists() or not source.is_file():
            raise RuntimeError(f"backup file does not exist: {source}")
        if source.resolve() == self.db_path.resolve():
            raise ValueError("restore source must differ from the live database")
        if not self.store or getattr(self.store._transaction_state, 'connection', None) is not None:
            raise RuntimeError("restore requires an idle MemoryStore outside a transaction")
        self._assert_sqlite_ok(source)
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as check:
            tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'profiles', 'conversations', 'knowledge'}.issubset(tables):
            raise ValueError('backup is not a ClawOS memory database')
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        temp_target = self.db_path.with_name(f".{self.db_path.name}.{uuid.uuid4().hex}.restore_tmp")
        try:
            # SQLite backup includes committed WAL pages. File replacement can leave
            # live connections attached to a different database or replay stale WAL.
            with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src, closing(sqlite3.connect(temp_target)) as dst:
                src.backup(dst)
            from memoryos.memory_store import MemoryStore
            staged = MemoryStore(str(temp_target))
            MaintenanceService(store=staged, db_path=temp_target, base_dir=self.base_dir, config=self.config).apply_migrations()
            self._assert_sqlite_ok(temp_target)
            with self.store._lock:
                pre_restore = self.backup_database(label=label or "pre-restore")
                with closing(sqlite3.connect(temp_target)) as src, closing(sqlite3.connect(self.db_path, timeout=10)) as dst:
                    src.backup(dst)
        finally:
            for suffix in ('', '-wal', '-shm'):
                Path(str(temp_target) + suffix).unlink(missing_ok=True)
        return {
            "ok": True,
            "restored_from": str(source),
            "target": str(self.db_path),
            "bytes": self.db_path.stat().st_size,
            "pre_restore_backup": pre_restore,
            "restored_at": self._now(),
        }

    def database_health(self) -> dict[str, Any]:
        """Read-only inventory; reports counts, never stored user text or secrets."""
        with closing(sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.execute('BEGIN')
            integrity = [r[0] for r in conn.execute('PRAGMA integrity_check')]
            foreign_keys = [dict(table=r[0], rowid=r[1], parent=r[2]) for r in conn.execute('PRAGMA foreign_key_check')]
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            wanted = ('conversations', 'conversation_archive', 'knowledge', 'documents', 'document_chunks',
                      'knowledge_records_v2', 'academy_materials', 'academy_material_events', 'academy_recall_attempts', 'academy_documents')
            counts = {name: conn.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0] for name in wanted if name in names}
            unlinked = 0
            if {'knowledge', 'knowledge_legacy_links_v2'}.issubset(names):
                unlinked = conn.execute('SELECT COUNT(*) FROM knowledge k LEFT JOIN knowledge_legacy_links_v2 l ON l.legacy_knowledge_id=k.id WHERE l.knowledge_id IS NULL').fetchone()[0]
            missing_sources = 0
            if 'documents' in names:
                missing_sources = sum(1 for (path,) in conn.execute("SELECT file_path FROM documents WHERE file_path<>''") if not Path(path).is_file())
            missing_artifacts=0
            if 'run_artifacts' in names:
                missing_artifacts=sum(1 for (path,) in conn.execute("SELECT uri FROM run_artifacts WHERE uri<>''")
                    if '://' not in path and Path(path).is_absolute() and not Path(path).is_file())
            logical = {}
            for child, parent, key in [('document_chunks','documents','document_id'),
                                       ('academy_material_events','academy_materials','material_id'),
                                       ('academy_recall_attempts','academy_materials','material_id'),
                                       ('academy_document_versions','academy_documents','document_id'),
                                       ('knowledge_sources_v2','knowledge_records_v2','knowledge_id')]:
                if {child,parent}.issubset(names):
                    logical['orphan_'+child] = conn.execute(f'SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON p.id=c.{key} WHERE p.id IS NULL').fetchone()[0]
            vector = dict(available=False)
            if 'knowledge_vector_outbox_v2' in names:
                pending, failed = conn.execute("SELECT COUNT(*),COALESCE(SUM(error<>''),0) FROM knowledge_vector_outbox_v2 WHERE processed_at='' ").fetchone()
                vector=dict(available=True,pending=pending,failed=failed)
            warnings = []
            if missing_sources:
                warnings.append('document_source_files_missing')
            if missing_artifacts:
                warnings.append('registered_artifact_files_missing')
            if unlinked:
                warnings.append('legacy_knowledge_not_linked')
            if vector.get('failed'):
                warnings.append('vector_projection_failed')
            elif vector.get('pending'):
                warnings.append('vector_projection_pending')
        sqlite_ok=integrity==['ok'] and not foreign_keys
        links_ok=not any(logical.values())
        return dict(ok=sqlite_ok and links_ok and not missing_sources, sqlite_ok=sqlite_ok,
                    status='failed' if not sqlite_ok or not links_ok or missing_sources else 'degraded' if warnings else 'healthy',
                    logical_checks=logical, vector_projection=vector, warnings=warnings, integrity=integrity,
                    foreign_key_errors=foreign_keys, counts=counts, unlinked_legacy_knowledge=unlinked,
                    missing_document_files=missing_sources, missing_artifact_files=missing_artifacts, checked_at=self._now())

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
        local_model = self.local_model_assets()
        add(
            "local_qwen_runtime",
            bool(local_model["ready"]),
            local_model["summary"],
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

    def local_model_assets(self) -> dict[str, Any]:
        """Report whether local-first Qwen assets are present without downloading them."""
        repo_root = self.base_dir.parent
        models_dir = self.base_dir / "models"
        manifests = {
            "qwen_9b": models_dir / "qwen3_5_9b_q4_k_m.json",
            "embedding": models_dir / "qwen3_embedding_0_6b.json",
            "reranker": models_dir / "qwen3_reranker_0_6b.json",
        }
        assets: list[dict[str, Any]] = []
        assets.append(self._manifest_asset("qwen_9b", manifests["qwen_9b"], repo_root, size_key="size_bytes"))
        assets.append(self._manifest_asset("embedding", manifests["embedding"], repo_root, size_key="total_local_size_bytes", directory=True))
        assets.append(self._manifest_asset("reranker", manifests["reranker"], repo_root, size_key="total_local_size_bytes", directory=True))

        server_candidates = [
            repo_root / "tools" / "llama.cpp" / "llama-server.exe",
            repo_root / "tools" / "llama.cpp" / "runtime" / "llama-server.exe",
            repo_root / "tools" / "llama.cpp" / "build" / "bin" / "Release" / "llama-server.exe",
        ]
        found_server = next((path for path in server_candidates if path.exists()), None)
        assets.append({
            "id": "llama_server",
            "label": "llama.cpp OpenAI-compatible server",
            "path": str(found_server or server_candidates[0]),
            "exists": bool(found_server),
            "expected_bytes": 0,
            "actual_bytes": found_server.stat().st_size if found_server and found_server.is_file() else 0,
            "ok": bool(found_server),
            "required": True,
        })
        required = [item for item in assets if item.get("required", True)]
        ready = all(item["ok"] for item in required)
        missing = [item["id"] for item in required if not item["ok"]]
        return {
            "ready": ready,
            "mode": "local_qwen_gguf",
            "summary": "local Qwen assets ready" if ready else f"missing local assets: {', '.join(missing)}",
            "assets": assets,
            "start_script": str(self.base_dir / "scripts" / "start_qwen_llama_server.ps1"),
            "download_scripts": [
                str(self.base_dir / "scripts" / "download_qwen_model.ps1"),
                str(self.base_dir / "scripts" / "download_llama_cpp.ps1"),
            ],
        }

    def _manifest_asset(
        self,
        asset_id: str,
        manifest_path: Path,
        repo_root: Path,
        *,
        size_key: str = "",
        directory: bool = False,
    ) -> dict[str, Any]:
        if not manifest_path.exists():
            return {
                "id": asset_id,
                "label": asset_id,
                "path": str(manifest_path),
                "exists": False,
                "expected_bytes": 0,
                "actual_bytes": 0,
                "ok": False,
                "required": True,
                "error": "manifest_missing",
            }
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        local_path = Path(str(manifest.get("local_path") or ""))
        if not local_path.is_absolute():
            local_path = (repo_root / local_path).resolve()
        exists = local_path.exists()
        expected = int(manifest.get(size_key) or 0) if size_key else 0
        weight_path = local_path / "model.safetensors" if directory else local_path
        weight_expected = int(manifest.get("model_safetensors_size_bytes") or 0)
        if directory and weight_expected:
            expected = weight_expected
            actual = weight_path.stat().st_size if weight_path.is_file() else 0
        else:
            actual = self._directory_size(local_path) if exists and directory else (local_path.stat().st_size if exists and local_path.is_file() else 0)
        size_ok = expected <= 0 or actual == expected
        return {
            "id": asset_id,
            "label": manifest.get("model_name") or manifest.get("id") or asset_id,
            "path": str(local_path),
            "exists": exists,
            "expected_bytes": expected,
            "actual_bytes": actual,
            "ok": bool(exists and size_ok),
            "required": True,
            "source_url": manifest.get("source_url", ""),
        }

    @staticmethod
    def _directory_size(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    @staticmethod
    def _assert_sqlite_ok(path: Path) -> None:
        conn = sqlite3.connect(str(path))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if integrity != "ok":
            raise RuntimeError(f"sqlite integrity check failed: {integrity}")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
