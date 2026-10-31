"""Deterministic clean-install and legacy-database upgrade release gate."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"backend"))
import database  # noqa: E402


def versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as db: return [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")]


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        root=Path(directory);fresh=root/"fresh.db";legacy=root/"legacy.db"
        with patch.object(database,"DB_PATH",fresh),patch.object(database,"DATABASE_URL",f"sqlite:///{fresh}"):
            database.init_database();fresh_versions=versions(fresh)
            database.init_database();assert versions(fresh)==fresh_versions
        with sqlite3.connect(legacy) as db:
            db.executescript("""CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT);
            INSERT INTO schema_migrations VALUES(1,'baseline','legacy');
            CREATE TABLE text3d_jobs(id TEXT PRIMARY KEY,prompt TEXT,status TEXT,progress INTEGER,stage TEXT,asset_id TEXT,stats TEXT,error TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE agent_runs(id TEXT PRIMARY KEY,prompt TEXT,provider TEXT,model TEXT,status TEXT,cycle INTEGER,max_cycles INTEGER,total_tokens INTEGER,total_cost REAL,duration_ms INTEGER,result TEXT,error TEXT,created_at TEXT,updated_at TEXT);""")
        with patch.object(database,"DB_PATH",legacy),patch.object(database,"DATABASE_URL",f"sqlite:///{legacy}"):
            database.init_database();legacy_versions=versions(legacy)
            with database.connect() as db:
                tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        expected=set(fresh_versions);assert set(legacy_versions)==expected
        assert fresh_versions == list(range(1,23))
        assert {"model_scenes","model_scene_versions","studio_scene_versions","model_operation_jobs","asset_projects","run_asset_links","asset_components","asset_releases","scene_agent_runs","scene_agent_decisions","geometry_jobs","dataset_versions","dataset_lineage","analysis_queries","analysis_cache","ml_ingestion_receipts","three_telemetry","run_changes"}.issubset(tables)
        assert {"evaluation_test_sets", "evaluation_samples", "evaluation_conditions", "evaluations", "evaluation_predictions", "evaluation_scenarios", "synthesis_jobs", "synthesis_frames"}.issubset(tables)
        print(json.dumps({"ok":True,"freshMigrations":fresh_versions,"legacyMigrations":legacy_versions,"idempotent":True}))


if __name__=="__main__": main()
