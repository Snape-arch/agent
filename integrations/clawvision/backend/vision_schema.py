"""Image catalog bindings and durable controlled training comparisons."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS vision_dataset_versions (
 version_id TEXT PRIMARY KEY REFERENCES dataset_versions(id), tenant_id TEXT NOT NULL,
 origin TEXT NOT NULL, purpose TEXT NOT NULL, digest TEXT NOT NULL, manifest_json TEXT NOT NULL,
 request_digest TEXT NOT NULL, source_job_id TEXT REFERENCES synthesis_jobs(id), created_at TEXT NOT NULL,
 UNIQUE(tenant_id,request_digest)
);
CREATE INDEX IF NOT EXISTS vision_versions_tenant ON vision_dataset_versions(tenant_id,created_at,version_id);
CREATE TABLE IF NOT EXISTS vision_experiments (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, task_id TEXT NOT NULL UNIQUE REFERENCES durable_tasks(id),
 real_train_version_id TEXT NOT NULL REFERENCES vision_dataset_versions(version_id),
 synthetic_version_id TEXT NOT NULL REFERENCES vision_dataset_versions(version_id),
 test_version_id TEXT NOT NULL REFERENCES vision_dataset_versions(version_id),
 test_set_id TEXT NOT NULL REFERENCES evaluation_test_sets(id),
 baseline_run_id TEXT NOT NULL REFERENCES runs(id), candidate_run_id TEXT NOT NULL REFERENCES runs(id),
 config_json TEXT NOT NULL, request_digest TEXT NOT NULL, status TEXT NOT NULL,
 state_json TEXT NOT NULL DEFAULT '{}', result_json TEXT, error TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(tenant_id,request_digest)
);
CREATE INDEX IF NOT EXISTS vision_experiments_tenant ON vision_experiments(tenant_id,created_at,id);
"""
