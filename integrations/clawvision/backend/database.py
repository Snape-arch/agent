"""Database adapter with zero-config SQLite and optional PostgreSQL support."""

from __future__ import annotations

from run_schema import postgres_statements as run_postgres_statements, sqlite_schema as run_sqlite_schema
from evaluation_schema import SCHEMA as EVALUATION_SCHEMA
from scenario_schema import SCHEMA as SCENARIO_SCHEMA
from synthesis_schema import SCHEMA as SYNTHESIS_SCHEMA
from vision_schema import SCHEMA as VISION_SCHEMA

import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CLAWVISION_DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "clawvision.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH}")


SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL,
  params TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error_message TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step INTEGER NOT NULL, train_loss REAL, val_loss REAL, accuracy REAL, learning_rate REAL, gpu REAL,
  created_at TEXT NOT NULL, UNIQUE(run_id, step)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  name TEXT NOT NULL, type TEXT NOT NULL, mime_type TEXT NOT NULL, step INTEGER,
  content TEXT, object_key TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, baseline_run_id TEXT,
  payload TEXT NOT NULL, total_runs INTEGER NOT NULL, completed_runs INTEGER NOT NULL DEFAULT 0,
  concurrency INTEGER NOT NULL, estimate_seconds REAL NOT NULL, estimated_cost REAL NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, schema_json TEXT NOT NULL,
  object_key TEXT NOT NULL, row_count INTEGER NOT NULL, created_at TEXT NOT NULL,
  storage_format TEXT NOT NULL DEFAULT 'json', columnar_key TEXT, byte_size INTEGER NOT NULL DEFAULT 0,
  current_version_id TEXT, schema_version INTEGER NOT NULL DEFAULT 1,
  partition_by TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS visualization_specs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT, spec TEXT NOT NULL,
  share_token TEXT NOT NULL UNIQUE, is_public INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_assets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, version INTEGER NOT NULL,
  parent_id TEXT, object_key TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(name, version)
);
CREATE TABLE IF NOT EXISTS studio_generations (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL, provider TEXT NOT NULL,
  plan TEXT NOT NULL, validation TEXT NOT NULL, asset_id TEXT,
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studio_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, generation_id TEXT NOT NULL REFERENCES studio_generations(id) ON DELETE CASCADE,
  rating INTEGER NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parameter_snapshots (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, run_id TEXT, params TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY, prompt TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
  status TEXT NOT NULL, cycle INTEGER NOT NULL DEFAULT 0, max_cycles INTEGER NOT NULL DEFAULT 2,
  total_tokens INTEGER NOT NULL DEFAULT 0, total_cost REAL NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_stages (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL,
  max_attempts INTEGER NOT NULL, input_artifact_id TEXT, output_artifact_id TEXT,
  tokens INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_artifacts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  stage TEXT NOT NULL, cycle INTEGER NOT NULL, kind TEXT NOT NULL, object_key TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS text3d_jobs (
  id TEXT PRIMARY KEY, prompt TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
  stage TEXT NOT NULL, asset_id TEXT, stats TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studio_scene_versions (
  id TEXT PRIMARY KEY, generation_id TEXT, version INTEGER NOT NULL, command TEXT NOT NULL,
  operations TEXT NOT NULL, plan TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_scenes (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, source_asset_id TEXT NOT NULL, current_asset_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, operations TEXT NOT NULL, scene_json TEXT NOT NULL, quality TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_scene_versions (
  id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, asset_id TEXT NOT NULL, operations TEXT NOT NULL, scene_json TEXT NOT NULL,
  quality TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(scene_id, version)
);
CREATE TABLE IF NOT EXISTS model_operation_jobs (
  id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
  status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL,
  operations TEXT NOT NULL, result TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS metrics_run_step ON metrics(run_id, step);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run_id, created_at);
CREATE INDEX IF NOT EXISTS agent_stages_run ON agent_stages(run_id, created_at);
CREATE INDEX IF NOT EXISTS agent_artifacts_run ON agent_artifacts(run_id, created_at);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL, source TEXT NOT NULL,
  params TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error_message TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
  id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step INTEGER NOT NULL, train_loss DOUBLE PRECISION, val_loss DOUBLE PRECISION,
  accuracy DOUBLE PRECISION, learning_rate DOUBLE PRECISION, gpu DOUBLE PRECISION,
  created_at TEXT NOT NULL, UNIQUE(run_id, step)
);
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  name TEXT NOT NULL, type TEXT NOT NULL, mime_type TEXT NOT NULL, step INTEGER,
  content TEXT, object_key TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, baseline_run_id TEXT,
  payload TEXT NOT NULL, total_runs INTEGER NOT NULL, completed_runs INTEGER NOT NULL DEFAULT 0,
  concurrency INTEGER NOT NULL, estimate_seconds DOUBLE PRECISION NOT NULL,
  estimated_cost DOUBLE PRECISION NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS datasets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, schema_json TEXT NOT NULL,
  object_key TEXT NOT NULL, row_count INTEGER NOT NULL, created_at TEXT NOT NULL,
  storage_format TEXT NOT NULL DEFAULT 'json', columnar_key TEXT, byte_size BIGINT NOT NULL DEFAULT 0,
  current_version_id TEXT, schema_version INTEGER NOT NULL DEFAULT 1,
  partition_by TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS visualization_specs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT, spec TEXT NOT NULL,
  share_token TEXT NOT NULL UNIQUE, is_public INTEGER NOT NULL DEFAULT 0,
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_assets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, version INTEGER NOT NULL,
  parent_id TEXT, object_key TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(name, version)
);
CREATE TABLE IF NOT EXISTS studio_generations (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, prompt TEXT NOT NULL, provider TEXT NOT NULL,
  plan TEXT NOT NULL, validation TEXT NOT NULL, asset_id TEXT,
  version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studio_feedback (
  id BIGSERIAL PRIMARY KEY, generation_id TEXT NOT NULL REFERENCES studio_generations(id) ON DELETE CASCADE,
  rating INTEGER NOT NULL, comment TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parameter_snapshots (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, run_id TEXT, params TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY, prompt TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
  status TEXT NOT NULL, cycle INTEGER NOT NULL DEFAULT 0, max_cycles INTEGER NOT NULL DEFAULT 2,
  total_tokens INTEGER NOT NULL DEFAULT 0, total_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_stages (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  cycle INTEGER NOT NULL, stage TEXT NOT NULL, status TEXT NOT NULL, attempt INTEGER NOT NULL,
  max_attempts INTEGER NOT NULL, input_artifact_id TEXT, output_artifact_id TEXT,
  tokens INTEGER NOT NULL DEFAULT 0, cost DOUBLE PRECISION NOT NULL DEFAULT 0, duration_ms INTEGER NOT NULL DEFAULT 0,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_artifacts (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  stage TEXT NOT NULL, cycle INTEGER NOT NULL, kind TEXT NOT NULL, object_key TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS text3d_jobs (
  id TEXT PRIMARY KEY, prompt TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
  stage TEXT NOT NULL, asset_id TEXT, stats TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studio_scene_versions (
  id TEXT PRIMARY KEY, generation_id TEXT, version INTEGER NOT NULL, command TEXT NOT NULL,
  operations TEXT NOT NULL, plan TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_scenes (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, source_asset_id TEXT NOT NULL, current_asset_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, operations TEXT NOT NULL, scene_json TEXT NOT NULL, quality TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_scene_versions (
  id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, asset_id TEXT NOT NULL, operations TEXT NOT NULL, scene_json TEXT NOT NULL,
  quality TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(scene_id, version)
);
CREATE TABLE IF NOT EXISTS model_operation_jobs (
  id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
  status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL,
  operations TEXT NOT NULL, result TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS metrics_run_step ON metrics(run_id, step);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
CREATE INDEX IF NOT EXISTS artifacts_run ON artifacts(run_id, created_at);
CREATE INDEX IF NOT EXISTS agent_stages_run ON agent_stages(run_id, created_at);
CREATE INDEX IF NOT EXISTS agent_artifacts_run ON agent_artifacts(run_id, created_at);
"""


from observability import gauge, inc, observe

_ACTIVE_CONNECTIONS = 0
_CONNECTION_LOCK = __import__("threading").Lock()


def _connection_opened(kind: str) -> None:
    global _ACTIVE_CONNECTIONS
    with _CONNECTION_LOCK: _ACTIVE_CONNECTIONS += 1; gauge("clawvision_db_connections_active", _ACTIVE_CONNECTIONS, kind=kind)
    inc("clawvision_db_connections_opened_total", kind=kind)
    gauge("clawvision_db_pool_configured", 0, kind=kind)


def _connection_closed(kind: str) -> None:
    global _ACTIVE_CONNECTIONS
    with _CONNECTION_LOCK: _ACTIVE_CONNECTIONS = max(0, _ACTIVE_CONNECTIONS - 1); gauge("clawvision_db_connections_active", _ACTIVE_CONNECTIONS, kind=kind)


def _operation(statement: str) -> str:
    return (statement.lstrip().split(None, 1) or ["unknown"])[0].lower()


class PostgresConnection:
    def __init__(self, connection):
        self.connection = connection
        self.kind = "postgresql"; _connection_opened(self.kind)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_value is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()
        _connection_closed(self.kind)

    def execute(self, statement: str, params=()):
        started = time.perf_counter()
        try: return self.connection.execute(statement.replace("?", "%s"), params)
        finally:
            elapsed=time.perf_counter()-started; operation=_operation(statement); observe("clawvision_db_query_duration_seconds",elapsed,kind=self.kind,operation=operation)
            inc("clawvision_db_queries_total",kind=self.kind,operation=operation)
            if elapsed >= float(os.environ.get("CLAWVISION_SLOW_QUERY_SECONDS", "0.25")): inc("clawvision_db_slow_queries_total",kind=self.kind,operation=operation)


class SQLiteConnection:
    def __init__(self, connection):
        self.connection = connection
        self.kind = "sqlite"; _connection_opened(self.kind)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_value is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()
        _connection_closed(self.kind)

    def execute(self, statement: str, params=()):
        started=time.perf_counter()
        try: return self.connection.execute(statement, params)
        finally:
            elapsed=time.perf_counter()-started;operation=_operation(statement);observe("clawvision_db_query_duration_seconds",elapsed,kind=self.kind,operation=operation);inc("clawvision_db_queries_total",kind=self.kind,operation=operation)
            if elapsed >= float(os.environ.get("CLAWVISION_SLOW_QUERY_SECONDS", "0.25")):inc("clawvision_db_slow_queries_total",kind=self.kind,operation=operation)

    def executescript(self, script: str):
        return self.connection.executescript(script)


def is_postgres() -> bool:
    return DATABASE_URL.startswith(("postgres://", "postgresql://"))


def connect():
    if is_postgres():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise RuntimeError("PostgreSQL requires: pip install 'psycopg[binary]'") from error
        return PostgresConnection(psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "5"))))
    connection = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return SQLiteConnection(connection)


def init_database() -> None:
    if is_postgres():
        with connect() as db:
            for statement in POSTGRES_SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
        _run_postgres_migrations()
        return
    with connect() as db:
        db.executescript(SQLITE_SCHEMA)
        columns = {row[1] for row in db.execute("PRAGMA table_info(artifacts)").fetchall()}
        if "object_key" not in columns:
            db.execute("ALTER TABLE artifacts ADD COLUMN object_key TEXT")
    _run_sqlite_migrations()


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


TEXT3D_COLUMNS = {
    "provider": "TEXT NOT NULL DEFAULT 'local-implicit'",
    "input_image_key": "TEXT",
    "preview_asset_id": "TEXT",
    "timeout_seconds": "INTEGER NOT NULL DEFAULT 600",
    "memory_budget_mb": "INTEGER NOT NULL DEFAULT 8192",
    "checkpoint_key": "TEXT",
    "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
}

AGENT_COLUMNS = {
    "timeout_seconds": "INTEGER NOT NULL DEFAULT 300",
    "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
}

ASSET_CATALOG_COLUMNS = {
    "project_id": "TEXT",
    "folder": "TEXT NOT NULL DEFAULT '/'",
    "stage": "TEXT NOT NULL DEFAULT 'raw'",
    "tags": "TEXT NOT NULL DEFAULT '[]'",
    "thumbnail_key": "TEXT",
    "archived_at": "TEXT",
    "deleted_at": "TEXT",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
}

ASSET_CATALOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_asset_links (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL REFERENCES model_assets(id), scene_id TEXT, role TEXT NOT NULL,
  step INTEGER, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
  UNIQUE(run_id, asset_id, role, step)
);
CREATE TABLE IF NOT EXISTS asset_components (
  id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES model_assets(id) ON DELETE CASCADE,
  component_type TEXT NOT NULL, version INTEGER NOT NULL, object_key TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
  UNIQUE(asset_id, component_type, version)
);
CREATE TABLE IF NOT EXISTS asset_releases (
  id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES model_assets(id) ON DELETE CASCADE,
  status TEXT NOT NULL, reviewer TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS model_assets_project_stage ON model_assets(project_id, stage, updated_at);
CREATE INDEX IF NOT EXISTS run_asset_links_timeline ON run_asset_links(run_id, step, created_at);
CREATE INDEX IF NOT EXISTS asset_components_asset_type ON asset_components(asset_id, component_type, version);
"""

INTELLIGENT_GEOMETRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS scene_agent_runs (
  id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
  command TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL, base_version INTEGER NOT NULL,
  operations TEXT NOT NULL DEFAULT '[]', analysis TEXT NOT NULL DEFAULT '{}', preview TEXT,
  result TEXT, error TEXT, risk_level TEXT NOT NULL DEFAULT 'low', estimated_cost REAL NOT NULL DEFAULT 0,
  estimated_seconds REAL NOT NULL DEFAULT 0, quality_cycles INTEGER NOT NULL DEFAULT 0,
  max_cycles INTEGER NOT NULL DEFAULT 2, cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scene_agent_decisions (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES scene_agent_runs(id) ON DELETE CASCADE,
  stage TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS geometry_jobs (
  id TEXT PRIMARY KEY, scene_id TEXT REFERENCES model_scenes(id) ON DELETE CASCADE,
  source_asset_id TEXT NOT NULL REFERENCES model_assets(id), provider TEXT NOT NULL,
  operation TEXT NOT NULL, status TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
  stage TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 50, preview_asset_id TEXT,
  result_asset_id TEXT, checkpoint_key TEXT, result TEXT, error TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0, timeout_seconds INTEGER NOT NULL DEFAULT 900,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS scene_agent_runs_scene ON scene_agent_runs(scene_id, created_at);
CREATE INDEX IF NOT EXISTS scene_agent_decisions_run ON scene_agent_decisions(run_id, created_at);
CREATE INDEX IF NOT EXISTS geometry_jobs_queue ON geometry_jobs(status, priority, created_at);
"""

TRAINING_SCHEMA = """
CREATE TABLE IF NOT EXISTS training_jobs (
  id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  parent_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, provider TEXT NOT NULL,
  status TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
  process_id INTEGER, checkpoint_key TEXT, result TEXT, error TEXT,
  cancel_requested INTEGER NOT NULL DEFAULT 0, timeout_seconds INTEGER NOT NULL DEFAULT 900,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS training_jobs_parent ON training_jobs(parent_job_id, status, created_at);
"""

SECURITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memberships (tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL, PRIMARY KEY(tenant_id,user_id));
CREATE TABLE IF NOT EXISTS api_tokens (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, scopes TEXT NOT NULL, expires_at TEXT, revoked_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tenant_quotas (tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE, max_runs INTEGER NOT NULL DEFAULT 10000, max_concurrent_jobs INTEGER NOT NULL DEFAULT 3, max_storage_bytes INTEGER NOT NULL DEFAULT 10737418240);
CREATE TABLE IF NOT EXISTS audit_logs (id TEXT PRIMARY KEY, tenant_id TEXT, user_id TEXT, method TEXT NOT NULL, path TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS credential_refs (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE, provider TEXT NOT NULL, name TEXT NOT NULL, ciphertext TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_logs_tenant_time ON audit_logs(tenant_id, created_at);
"""

# Root resources are tenant scoped. Child tables inherit their boundary through the
# parent foreign key, which keeps the migration small and makes legacy data belong
# to the compatibility tenant named ``default``.
TENANT_ROOT_TABLES = (
    "runs", "jobs", "datasets", "visualization_specs", "model_assets",
    "studio_generations", "studio_scene_versions", "parameter_snapshots", "agent_runs", "text3d_jobs",
    "model_scenes", "model_operation_jobs", "asset_projects", "scene_agent_runs",
    "geometry_jobs", "training_jobs",
)

DURABLE_TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS durable_tasks (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default', kind TEXT NOT NULL,
  resource_id TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 50, attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3, lease_owner TEXT, lease_expires_at TEXT,
  heartbeat_at TEXT, idempotency_key TEXT NOT NULL, result TEXT, error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(tenant_id,idempotency_key)
);
CREATE TABLE IF NOT EXISTS durable_task_events (
  id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES durable_tasks(id) ON DELETE CASCADE,
  event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS durable_tasks_claim ON durable_tasks(status,priority,created_at);
CREATE INDEX IF NOT EXISTS durable_tasks_tenant ON durable_tasks(tenant_id,updated_at);
"""

TRAINING_LINEAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS training_lineage (
  run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default', framework TEXT NOT NULL DEFAULT 'custom',
  code_ref TEXT, dataset_ref TEXT, environment TEXT NOT NULL DEFAULT '{}',
  parent_run_id TEXT, resume_checkpoint_key TEXT, world_size INTEGER NOT NULL DEFAULT 1,
  rank_count INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_resource_metrics (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step INTEGER NOT NULL, gpu_utilization REAL, gpu_memory_mb REAL, gpu_temperature REAL,
  samples_per_second REAL, oom INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  PRIMARY KEY(run_id,step)
);
CREATE INDEX IF NOT EXISTS training_lineage_tenant ON training_lineage(tenant_id,created_at);
"""

ML_INGESTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS ml_ingestion_receipts (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  event_id TEXT NOT NULL, tenant_id TEXT NOT NULL DEFAULT 'default',
  kind TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY(run_id,event_id)
);
CREATE INDEX IF NOT EXISTS ml_ingestion_receipts_tenant ON ml_ingestion_receipts(tenant_id,created_at);
"""

THREE_TELEMETRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS three_telemetry (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default', asset_id TEXT,
  label TEXT NOT NULL, session_id TEXT NOT NULL, frames INTEGER NOT NULL DEFAULT 0,
  average_frame_ms REAL NOT NULL DEFAULT 0, max_frame_ms REAL NOT NULL DEFAULT 0,
  gpu_frame_ms REAL, gpu_vendor TEXT, gpu_renderer TEXT, webgl_version TEXT,
  geometries INTEGER NOT NULL DEFAULT 0, textures INTEGER NOT NULL DEFAULT 0,
  draw_calls INTEGER NOT NULL DEFAULT 0, triangles INTEGER NOT NULL DEFAULT 0,
  heap_bytes INTEGER NOT NULL DEFAULT 0, transferred_bytes INTEGER NOT NULL DEFAULT 0,
  context_losses INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS three_telemetry_tenant_created ON three_telemetry(tenant_id,created_at);
CREATE INDEX IF NOT EXISTS three_telemetry_asset_created ON three_telemetry(asset_id,created_at);
"""

DATASET_COLUMNAR_COLUMNS = {
    "storage_format": "TEXT NOT NULL DEFAULT 'json'",
    "columnar_key": "TEXT",
    "byte_size": "INTEGER NOT NULL DEFAULT 0",
}

DATASET_CATALOG_COLUMNS = {
    "current_version_id": "TEXT",
    "schema_version": "INTEGER NOT NULL DEFAULT 1",
    "partition_by": "TEXT NOT NULL DEFAULT '[]'",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
}

ANALYTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset_versions (
  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default', version INTEGER NOT NULL,
  schema_json TEXT NOT NULL, manifest_json TEXT NOT NULL, partition_by TEXT NOT NULL DEFAULT '[]',
  row_count INTEGER NOT NULL, byte_size INTEGER NOT NULL DEFAULT 0,
  parent_version_id TEXT, change_summary TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
  UNIQUE(dataset_id,version)
);
CREATE TABLE IF NOT EXISTS dataset_lineage (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default',
  target_dataset_id TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  target_version_id TEXT NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
  source_dataset_id TEXT NOT NULL REFERENCES datasets(id),
  source_version_id TEXT REFERENCES dataset_versions(id),
  relation TEXT NOT NULL, transform_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_queries (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default', status TEXT NOT NULL,
  request_json TEXT NOT NULL, result_key TEXT, plan_json TEXT, error TEXT,
  cache_key TEXT, cached INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
  timeout_seconds INTEGER NOT NULL DEFAULT 30, started_at TEXT, finished_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_cache (
  cache_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default', result_key TEXT NOT NULL,
  row_count INTEGER NOT NULL DEFAULT 0, byte_size INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT NOT NULL, created_at TEXT NOT NULL, last_accessed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS dataset_versions_dataset ON dataset_versions(dataset_id,version);
CREATE INDEX IF NOT EXISTS dataset_lineage_target ON dataset_lineage(target_dataset_id,created_at);
CREATE INDEX IF NOT EXISTS dataset_lineage_source ON dataset_lineage(source_dataset_id,created_at);
CREATE INDEX IF NOT EXISTS analysis_queries_tenant ON analysis_queries(tenant_id,created_at);
CREATE INDEX IF NOT EXISTS analysis_cache_tenant ON analysis_cache(tenant_id,expires_at);
"""

TENANT_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenant_usage (
  tenant_id TEXT PRIMARY KEY, storage_bytes INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
);
"""


def _sqlite_add_tenant_columns(db) -> None:
    for table in TENANT_ROOT_TABLES:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            continue
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if "tenant_id" not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'")
        db.execute(f"CREATE INDEX IF NOT EXISTS {table}_tenant_idx ON {table}(tenant_id)")


def _postgres_add_tenant_columns(db) -> None:
    for table in TENANT_ROOT_TABLES:
        db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'")
        db.execute(f"CREATE INDEX IF NOT EXISTS {table}_tenant_idx ON {table}(tenant_id)")


def _run_sqlite_migrations() -> None:
    with connect() as db:
        applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations").fetchall()}
        if 1 not in applied:
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (1, "baseline-0.9.0", _now_iso()))
        if 2 not in applied:
            columns = {row[1] for row in db.execute("PRAGMA table_info(text3d_jobs)").fetchall()}
            for name, definition in TEXT3D_COLUMNS.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE text3d_jobs ADD COLUMN {name} {definition}")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (2, "text3d-provider-lifecycle", _now_iso()))
        if 3 not in applied:
            columns = {row[1] for row in db.execute("PRAGMA table_info(agent_runs)").fetchall()}
            for name, definition in AGENT_COLUMNS.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {definition}")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (3, "agent-cancel-timeout", _now_iso()))
        if 4 not in applied:
            db.execute("""CREATE TABLE IF NOT EXISTS studio_scene_versions (
                id TEXT PRIMARY KEY, generation_id TEXT, version INTEGER NOT NULL, command TEXT NOT NULL,
                operations TEXT NOT NULL, plan TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (4, "non-destructive-scene-history", _now_iso()))
        if 5 not in applied:
            db.execute("""CREATE TABLE IF NOT EXISTS model_scenes (
                id TEXT PRIMARY KEY,name TEXT NOT NULL,source_asset_id TEXT NOT NULL,current_asset_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,operations TEXT NOT NULL,scene_json TEXT NOT NULL,quality TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS model_scene_versions (
                id TEXT PRIMARY KEY,scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,asset_id TEXT NOT NULL,operations TEXT NOT NULL,scene_json TEXT NOT NULL,
                quality TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(scene_id,version))""")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(5,"editable-model-scenes",_now_iso()))
        if 6 not in applied:
            db.execute("""CREATE TABLE IF NOT EXISTS model_operation_jobs (
                id TEXT PRIMARY KEY,scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
                status TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,stage TEXT NOT NULL,operations TEXT NOT NULL,
                result TEXT,error TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(6,"async-model-operations",_now_iso()))
        if 7 not in applied:
            columns = {row[1] for row in db.execute("PRAGMA table_info(model_assets)").fetchall()}
            for name, definition in ASSET_CATALOG_COLUMNS.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE model_assets ADD COLUMN {name} {definition}")
            db.executescript(ASSET_CATALOG_SCHEMA)
            db.execute("UPDATE model_assets SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(7,"experiment-asset-catalog",_now_iso()))
        if 8 not in applied:
            db.executescript(INTELLIGENT_GEOMETRY_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(8,"semantic-agent-professional-geometry",_now_iso()))
        if 9 not in applied:
            db.executescript(TRAINING_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(9,"real-training-providers",_now_iso()))
        if 10 not in applied:
            db.executescript(SECURITY_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(10,"tenant-rbac-tokens-quotas-audit",_now_iso()))
        if 11 not in applied:
            _sqlite_add_tenant_columns(db)
            db.executescript(TENANT_USAGE_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(11,"tenant-resource-isolation",_now_iso()))
        if 12 not in applied:
            db.executescript(DURABLE_TASK_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(12,"durable-task-leases",_now_iso()))
        if 13 not in applied:
            db.executescript(TRAINING_LINEAGE_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(13,"training-framework-lineage",_now_iso()))
        if 14 not in applied:
            columns = {row[1] for row in db.execute("PRAGMA table_info(datasets)").fetchall()}
            for name, definition in DATASET_COLUMNAR_COLUMNS.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE datasets ADD COLUMN {name} {definition}")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(14,"columnar-dataset-storage",_now_iso()))
        if 15 not in applied:
            columns = {row[1] for row in db.execute("PRAGMA table_info(datasets)").fetchall()}
            for name, definition in DATASET_CATALOG_COLUMNS.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE datasets ADD COLUMN {name} {definition}")
            db.executescript(ANALYTICS_SCHEMA)
            db.execute("UPDATE datasets SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(15,"analytics-catalog-query-control",_now_iso()))
        if 16 not in applied:
            db.executescript(ML_INGESTION_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(16,"ml-ingestion-idempotency",_now_iso()))
        if 17 not in applied:
            db.executescript(THREE_TELEMETRY_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(17,"professional-3d-telemetry",_now_iso()))
        if 18 not in applied:
            columns = {row[1] for row in db.execute("PRAGMA table_info(runs)").fetchall()}
            if "revision" not in columns:
                db.execute("ALTER TABLE runs ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            db.executescript(run_sqlite_schema())
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(18,"run-incremental-cursors",_now_iso()))
        if 19 not in applied:
            db.executescript(EVALUATION_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (19, "classification-evaluation-evidence", _now_iso()))
        if 20 not in applied:
            db.executescript(SCENARIO_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (20, "failure-driven-scene-plans", _now_iso()))
        if 21 not in applied:
            db.executescript(SYNTHESIS_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (21, "rendered-synthetic-datasets", _now_iso()))
        if 22 not in applied:
            db.executescript(VISION_SCHEMA)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (22, "versioned-image-training", _now_iso()))


def _run_postgres_migrations() -> None:
    with connect() as db:
        applied = {row["version"] for row in db.execute("SELECT version FROM schema_migrations").fetchall()}
        if 1 not in applied:
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (1, "baseline-0.9.0", _now_iso()))
        if 2 not in applied:
            for name, definition in TEXT3D_COLUMNS.items():
                db.execute(f"ALTER TABLE text3d_jobs ADD COLUMN IF NOT EXISTS {name} {definition}")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (2, "text3d-provider-lifecycle", _now_iso()))
        if 3 not in applied:
            for name, definition in AGENT_COLUMNS.items():
                db.execute(f"ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS {name} {definition}")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (3, "agent-cancel-timeout", _now_iso()))
        if 4 not in applied:
            db.execute("""CREATE TABLE IF NOT EXISTS studio_scene_versions (
                id TEXT PRIMARY KEY, generation_id TEXT, version INTEGER NOT NULL, command TEXT NOT NULL,
                operations TEXT NOT NULL, plan TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (4, "non-destructive-scene-history", _now_iso()))
        if 5 not in applied:
            db.execute("""CREATE TABLE IF NOT EXISTS model_scenes (
                id TEXT PRIMARY KEY,name TEXT NOT NULL,source_asset_id TEXT NOT NULL,current_asset_id TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,operations TEXT NOT NULL,scene_json TEXT NOT NULL,quality TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS model_scene_versions (
                id TEXT PRIMARY KEY,scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,asset_id TEXT NOT NULL,operations TEXT NOT NULL,scene_json TEXT NOT NULL,
                quality TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(scene_id,version))""")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(5,"editable-model-scenes",_now_iso()))
        if 6 not in applied:
            db.execute("""CREATE TABLE IF NOT EXISTS model_operation_jobs (
                id TEXT PRIMARY KEY,scene_id TEXT NOT NULL REFERENCES model_scenes(id) ON DELETE CASCADE,
                status TEXT NOT NULL,progress INTEGER NOT NULL DEFAULT 0,stage TEXT NOT NULL,operations TEXT NOT NULL,
                result TEXT,error TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(6,"async-model-operations",_now_iso()))
        if 7 not in applied:
            for name, definition in ASSET_CATALOG_COLUMNS.items():
                db.execute(f"ALTER TABLE model_assets ADD COLUMN IF NOT EXISTS {name} {definition}")
            for statement in ASSET_CATALOG_SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            db.execute("UPDATE model_assets SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(7,"experiment-asset-catalog",_now_iso()))
        if 8 not in applied:
            for statement in INTELLIGENT_GEOMETRY_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(8,"semantic-agent-professional-geometry",_now_iso()))
        if 9 not in applied:
            for statement in TRAINING_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(9,"real-training-providers",_now_iso()))
        if 10 not in applied:
            for statement in SECURITY_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(10,"tenant-rbac-tokens-quotas-audit",_now_iso()))
        if 11 not in applied:
            _postgres_add_tenant_columns(db)
            for statement in TENANT_USAGE_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(11,"tenant-resource-isolation",_now_iso()))
        if 12 not in applied:
            for statement in DURABLE_TASK_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(12,"durable-task-leases",_now_iso()))
        if 13 not in applied:
            for statement in TRAINING_LINEAGE_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(13,"training-framework-lineage",_now_iso()))
        if 14 not in applied:
            for name, definition in DATASET_COLUMNAR_COLUMNS.items():
                db.execute(f"ALTER TABLE datasets ADD COLUMN IF NOT EXISTS {name} {definition}")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(14,"columnar-dataset-storage",_now_iso()))
        if 15 not in applied:
            for name, definition in DATASET_CATALOG_COLUMNS.items():
                db.execute(f"ALTER TABLE datasets ADD COLUMN IF NOT EXISTS {name} {definition}")
            for statement in ANALYTICS_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("UPDATE datasets SET updated_at=created_at WHERE updated_at='' OR updated_at IS NULL")
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(15,"analytics-catalog-query-control",_now_iso()))
        if 16 not in applied:
            for statement in ML_INGESTION_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(16,"ml-ingestion-idempotency",_now_iso()))
        if 17 not in applied:
            for statement in THREE_TELEMETRY_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(17,"professional-3d-telemetry",_now_iso()))
        if 18 not in applied:
            for statement in run_postgres_statements():
                db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",(18,"run-incremental-cursors",_now_iso()))
        if 19 not in applied:
            for statement in EVALUATION_SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (19, "classification-evaluation-evidence", _now_iso()))
        if 20 not in applied:
            for statement in SCENARIO_SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (20, "failure-driven-scene-plans", _now_iso()))
        if 21 not in applied:
            for statement in SYNTHESIS_SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (21, "rendered-synthetic-datasets", _now_iso()))
        if 22 not in applied:
            for statement in VISION_SCHEMA.split(";"):
                if statement.strip(): db.execute(statement)
            db.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)", (22, "versioned-image-training", _now_iso()))


def database_label() -> str:
    return "PostgreSQL" if is_postgres() else str(DB_PATH)


def is_integrity_error(error: Exception) -> bool:
    return isinstance(error, sqlite3.IntegrityError) or error.__class__.__name__ in {"UniqueViolation", "ForeignKeyViolation", "IntegrityError"}
