"""Immutable failure-driven scene plans, shared by SQLite and PostgreSQL."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_scenarios (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    report_id TEXT NOT NULL REFERENCES evaluations(id),
    asset_id TEXT NOT NULL REFERENCES model_assets(id),
    parent_id TEXT REFERENCES evaluation_scenarios(id),
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    digest TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evaluation_scenarios_report ON evaluation_scenarios(tenant_id,report_id,created_at,id);
CREATE INDEX IF NOT EXISTS evaluation_scenarios_asset ON evaluation_scenarios(asset_id);
"""
