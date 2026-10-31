"""Migration 19: immutable classification test manifests and evaluation evidence."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_test_sets (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default', name TEXT NOT NULL,
  task TEXT NOT NULL, digest TEXT NOT NULL, classes_json TEXT NOT NULL,
  sample_count INTEGER NOT NULL, dataset_version_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evaluation_sets_tenant ON evaluation_test_sets(tenant_id,created_at,id);
CREATE TABLE IF NOT EXISTS evaluation_samples (
  test_set_id TEXT NOT NULL REFERENCES evaluation_test_sets(id) ON DELETE CASCADE,
  sample_id TEXT NOT NULL, label TEXT NOT NULL, image_uri TEXT, content_hash TEXT,
  conditions_json TEXT NOT NULL, PRIMARY KEY(test_set_id,sample_id)
);
CREATE TABLE IF NOT EXISTS evaluation_conditions (
  test_set_id TEXT NOT NULL, sample_id TEXT NOT NULL, dimension TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY(test_set_id,sample_id,dimension),
  FOREIGN KEY(test_set_id,sample_id) REFERENCES evaluation_samples(test_set_id,sample_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS evaluation_conditions_slice ON evaluation_conditions(test_set_id,dimension,value,sample_id);
CREATE TABLE IF NOT EXISTS evaluations (
  id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL DEFAULT 'default',
  test_set_id TEXT NOT NULL REFERENCES evaluation_test_sets(id),
  run_id TEXT NOT NULL REFERENCES runs(id), name TEXT NOT NULL, digest TEXT NOT NULL,
  summary_json TEXT NOT NULL, provenance_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS evaluations_tenant_set ON evaluations(tenant_id,test_set_id,created_at,id);
CREATE INDEX IF NOT EXISTS evaluations_run ON evaluations(run_id);
CREATE TABLE IF NOT EXISTS evaluation_predictions (
  evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
  sample_id TEXT NOT NULL, predicted_label TEXT NOT NULL, confidence REAL,
  correct INTEGER NOT NULL, PRIMARY KEY(evaluation_id,sample_id)
);
CREATE INDEX IF NOT EXISTS evaluation_failures ON evaluation_predictions(evaluation_id,correct,sample_id);
"""
