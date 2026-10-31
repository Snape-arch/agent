import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import database
import durable_queue
import server
from object_store import LocalObjectStore


class TrainingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.patches = [patch.object(database, "DB_PATH", root / "test.db"), patch.object(database, "DATABASE_URL", f"sqlite:///{root / 'test.db'}"), patch.dict(os.environ, {"CLAWVISION_OBJECT_DIR": str(root / "objects")})]
        for item in self.patches: item.start()
        database.init_database()
        self.store_patch = patch.object(server, "OBJECT_STORE", LocalObjectStore()); self.store_patch.start()
        with database.connect() as db:
            db.execute("INSERT INTO jobs(id,kind,status,payload,total_runs,concurrency,estimate_seconds,estimated_cost,created_at,updated_at,tenant_id) VALUES('job','single','running','{}',1,1,1,0,'now','now','default')")
            db.execute("INSERT INTO runs(id,name,status,source,params,created_at,updated_at,tenant_id) VALUES('run','recover','running','parameter-lab',?,'now','now','default')", (json.dumps({"epochs": 6, "_jobId": "job"}),))
            db.execute("INSERT INTO training_jobs(id,run_id,parent_job_id,provider,status,stage,progress,timeout_seconds,created_at,updated_at,tenant_id) VALUES('training','run','job','local-python','running','training',33,30,'now','now','default')")
        self.task = durable_queue.enqueue("default", "training", "training", {"runId": "run", "provider": "local-python"}, "training:training")

    def tearDown(self):
        self.store_patch.stop()
        for item in reversed(self.patches): item.stop()
        self.directory.cleanup()

    def checkpoint(self):
        key = server.OBJECT_STORE.put_json("tenants/default/runs/run/checkpoint.json", {"step": 2, "content": {"step": 2}})
        with database.connect() as db: db.execute("UPDATE training_jobs SET checkpoint_key=? WHERE id='training'", (key,))
        return key

    def execute(self):
        server.execute_real_training("training", "run", {"epochs": 6}, "job", "local-python", threading.Semaphore(1), 30)

    def test_standalone_retry_reads_checkpoint_and_completed_redelivery_is_idempotent(self):
        self.checkpoint()
        script = ROOT / "tests" / "fixtures" / "training_recovery.py"
        with patch.dict(os.environ, {"CLAWVISION_TRAINING_SCRIPT": str(script)}): self.execute()
        run = server.run_service().get("run", "default")
        self.assertEqual([point["step"] for point in run["metrics"]], [3, 4, 5, 6])
        self.assertEqual(run["status"], "completed")
        self.assertIn("从 checkpoint step 2 恢复训练", run["logs"])
        with database.connect() as db:
            result = json.loads(db.execute("SELECT result FROM training_jobs WHERE id='training'").fetchone()["result"])
            self.assertEqual(result["resumedFrom"], 2)
        with patch.object(server, "run_training_provider", side_effect=AssertionError("completed task ran twice")): self.execute()
        with database.connect() as db: self.assertEqual(db.execute("SELECT completed_runs FROM jobs WHERE id='job'").fetchone()[0], 1)

    def test_missing_saved_checkpoint_fails_instead_of_silently_restarting(self):
        self.checkpoint()
        with patch.object(server.OBJECT_STORE, "get_json", side_effect=FileNotFoundError("checkpoint missing")), patch.object(server, "run_training_provider") as trainer: self.execute()
        trainer.assert_not_called()
        run = server.run_service().get("run", "default")
        self.assertEqual(run["status"], "failed")
        self.assertIn("checkpoint missing", run["errorMessage"])

    def test_api_restart_leaves_live_worker_lease_and_run_state_unchanged(self):
        durable_queue.lease(self.task["id"], "live-worker", 30)
        with patch.object(server, "EMBEDDED_WORKERS", False), patch.object(server, "submit_durable") as submit:
            self.assertEqual(server.resume_pending_jobs(), 0)
        submit.assert_not_called()
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM runs WHERE id='run'").fetchone()[0], "running")
            self.assertEqual(db.execute("SELECT stage FROM training_jobs WHERE id='training'").fetchone()[0], "training")
            self.assertEqual(db.execute("SELECT lease_owner FROM durable_tasks WHERE id=?", (self.task["id"],)).fetchone()[0], "live-worker")


if __name__ == "__main__": unittest.main()
