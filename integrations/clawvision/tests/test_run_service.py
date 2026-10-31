"""Run service contracts independent of the HTTP handler and embedded workers."""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import database
from api_contract import Pagination
from errors import NotFoundError, ValidationError
from object_store import LocalObjectStore
from run_service import RunService


class RunServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.patches = [patch.object(database, "DB_PATH", root / "runs.db"), patch.object(database, "DATABASE_URL", f"sqlite:///{root / 'runs.db'}"), patch.dict(os.environ, {"CLAWVISION_OBJECT_DIR": str(root / "objects")})]
        for item in self.patches:
            item.start()
        database.init_database()
        self.store = LocalObjectStore()
        self.service = RunService(database.connect, self.store, threading.RLock())

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def create(self, name="training", run_id="run"):
        return self.service.create("default", {"id": run_id, "name": name, "params": {"epochs": 3}})

    def test_summary_pages_are_stable_tenant_scoped_and_never_load_history(self):
        for index in range(6):
            self.create("literal_%" if index == 2 else "training", f"run-{index}")
        self.service.mutate("run-2", "default", "metrics", {"points": [{"step": step, "accuracy": step / 100} for step in range(100)]})
        self.service.mutate("run-2", "default", "artifacts", {"name": "large", "content": list(range(1000))})
        with database.connect() as db:
            db.execute("UPDATE runs SET created_at='same-time'")
            db.execute("INSERT INTO tenants(id,name,created_at) VALUES('other','other','now')")
        self.service.create("other", {"id": "private", "params": {}})
        with patch.object(self.store, "get_json", side_effect=AssertionError("summary read object storage")):
            pages = [self.service.list("default", Pagination(page, 2), summary=True) for page in range(1, 4)]
            filtered = self.service.list("default", Pagination(1, 25), summary=True, search="_%")
        self.assertEqual([run["id"] for page in pages for run in page["data"]], [f"run-{index}" for index in reversed(range(6))])
        self.assertEqual(pages[0]["pagination"]["total"], 6)
        self.assertTrue(pages[0]["pagination"]["hasNext"])
        self.assertEqual(pages[0]["counts"], {"running": 6})
        self.assertEqual(filtered["data"][0]["id"], "run-2")
        summary = filtered["data"][0]
        self.assertEqual((summary["metricCount"], summary["artifactCount"], summary["latestMetric"]["step"]), (100, 1, 99))
        self.assertTrue({"metrics", "logs", "artifacts"}.isdisjoint(summary))
        for action in (lambda: self.service.get("run-2", "other"), lambda: self.service.changes("run-2", "other", 0), lambda: self.service.mutate("run-2", "other", "stop", {})):
            with self.assertRaises(NotFoundError):
                action()

    def test_worker_writes_and_old_step_corrections_survive_service_restart(self):
        self.create()
        self.service.mutate("run", "default", "metrics", {"points": [{"step": 1, "accuracy": .5}, {"step": 9, "accuracy": .9}]})
        snapshot = self.service.get("run", "default")
        # Standalone writers use their own connection without server.bump().
        with database.connect() as worker:
            worker.execute("UPDATE metrics SET accuracy=.7 WHERE run_id='run' AND step=1")
            worker.execute("INSERT INTO events(run_id,level,message,created_at) VALUES('run','info','worker','now')")
            worker.execute("UPDATE runs SET status='completed' WHERE id='run'")
        restarted = RunService(database.connect, self.store, threading.RLock())
        delta = restarted.changes("run", "default", snapshot["cursor"])
        self.assertEqual([point["step"] for point in delta["metrics"]], [1])
        self.assertEqual(delta["metrics"][0]["accuracy"], .7)
        self.assertEqual([event["message"] for event in delta["events"]], ["worker"])
        self.assertEqual(delta["run"]["status"], "completed")
        self.assertFalse(delta["hasMore"])
        idle = restarted.changes("run", "default", delta["cursor"])
        self.assertEqual(idle["metrics"], [])
        self.assertEqual(idle["cursor"], delta["cursor"])

    def test_bounded_deltas_drain_to_final_cursor_and_report_deletes(self):
        snapshot = self.create()
        self.service.mutate("run", "default", "metrics", {"points": [{"step": step, "accuracy": .5} for step in range(7)]})
        artifact = self.service.mutate("run", "default", "artifacts", {"content": {"real": True}})
        with database.connect() as worker:
            worker.execute("DELETE FROM metrics WHERE run_id='run' AND step=1")
            worker.execute("DELETE FROM artifacts WHERE id=?", (artifact["id"],))
        cursor, received, removed = snapshot["cursor"], {}, []
        while True:
            delta = self.service.changes("run", "default", cursor, limit=2)
            self.assertGreater(delta["cursor"], cursor)
            cursor = delta["cursor"]
            received.update({point["step"]: point for point in delta["metrics"]})
            for step in delta["removedMetrics"]:
                received.pop(step, None)
            removed.extend(delta["removedArtifacts"])
            if not delta["hasMore"]:
                break
        current = self.service.get("run", "default")
        self.assertEqual(cursor, current["cursor"])
        self.assertEqual(sorted(received), [0, 2, 3, 4, 5, 6])
        self.assertIn(artifact["id"], removed)
        for after, limit in ((-1, 100), (cursor + 1, 100), (0, 0), (0, 501)):
            with self.assertRaises(ValidationError):
                self.service.changes("run", "default", after, limit)

    def test_failed_batch_rolls_back_data_receipts_and_cursor(self):
        initial = self.create()
        with self.assertRaises(KeyError):
            self.service.mutate("run", "default", "batch", {"metrics": [{"eventId": "once", "step": 1, "accuracy": .3}, {"accuracy": .4}]})
        current = self.service.get("run", "default")
        self.assertEqual((current["metrics"], current["cursor"]), ([], initial["cursor"]))
        batch = {"metrics": [{"eventId": "once", "step": 1, "accuracy": .3}], "events": [{"eventId": "event", "message": "logged once"}], "params": {"learningRate": .01}}
        self.assertEqual(self.service.mutate("run", "default", "batch", batch)["metrics"], 1)
        self.assertEqual(self.service.mutate("run", "default", "batch", batch)["metrics"], 0)
        current = self.service.get("run", "default")
        self.assertEqual(current["logs"].count("logged once"), 1)
        self.assertEqual(current["params"]["learningRate"], .01)
        self.service.mutate("run", "default", "fail", {"error": "training failed"})
        resumed = self.service.mutate("run", "default", "resume", {"checkpointKey": "step-1"})["data"]
        self.assertEqual((resumed["status"], resumed["errorMessage"]), ("running", None))

    def test_detail_cursor_and_history_share_one_snapshot(self):
        self.create()
        original = self.service.serialize
        def write_between_reads(db, row):
            with database.connect() as worker:
                worker.execute("INSERT INTO metrics(run_id,step,accuracy,created_at) VALUES('run',1,.7,'now')")
            return original(db, row)
        with patch.object(self.service, "serialize", side_effect=write_between_reads):
            snapshot = self.service.get("run", "default")
        self.assertEqual(snapshot["metrics"], [])
        delta = self.service.changes("run", "default", snapshot["cursor"])
        self.assertEqual(delta["metrics"][0]["accuracy"], .7)
        self.assertGreater(delta["cursor"], snapshot["cursor"])


if __name__ == "__main__":
    unittest.main()
