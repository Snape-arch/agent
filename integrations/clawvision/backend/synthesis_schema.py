"""Rendered synthetic datasets and immutable per-frame artifacts."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS synthesis_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    scenario_id TEXT NOT NULL REFERENCES evaluation_scenarios(id),
    task_id TEXT NOT NULL UNIQUE REFERENCES durable_tasks(id),
    request_digest TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    total INTEGER NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    accepted INTEGER NOT NULL DEFAULT 0,
    result_digest TEXT,
    manifest_key TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tenant_id,request_digest)
);
CREATE INDEX IF NOT EXISTS synthesis_jobs_scenario ON synthesis_jobs(tenant_id,scenario_id,created_at,id);
CREATE TABLE IF NOT EXISTS synthesis_frames (
    job_id TEXT NOT NULL REFERENCES synthesis_jobs(id),
    variant_index INTEGER NOT NULL,
    accepted INTEGER NOT NULL,
    annotation_json TEXT NOT NULL,
    artifacts_json TEXT NOT NULL,
    PRIMARY KEY(job_id,variant_index)
);
"""
