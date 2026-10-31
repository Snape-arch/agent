import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "sdk"))

import asgi
import database
import durable_queue
import security
import clawvision
from api_contract import Pagination
from domain_services import CollectionService


class DatabaseMigrationCoverageTests(unittest.TestCase):
    def test_collection_count_supports_postgres_dictionary_rows(self):
        db = Mock()
        count, rows = Mock(), Mock()
        count.fetchone.return_value = {"count": 26}
        rows.fetchall.return_value = [{"id": "asset"}]
        db.execute.side_effect = [count, rows]
        page = CollectionService.list(db, "model_assets", Pagination(2, 25), values=("tenant",))
        self.assertEqual(page.rows, [{"id": "asset"}])
        self.assertEqual(page.pagination["total"], 26)
        self.assertIn("COUNT(*) AS count", db.execute.call_args_list[0].args[0])

    def test_postgres_adapter_commit_rollback_and_placeholder_rewrite(self):
        connection = Mock(); adapter = database.PostgresConnection(connection)
        self.assertIs(adapter.__enter__(), adapter)
        adapter.execute("SELECT ?", (1,)); connection.execute.assert_called_with("SELECT %s", (1,))
        adapter.__exit__(None, None, None); connection.commit.assert_called_once(); connection.close.assert_called_once()
        connection = Mock(); adapter = database.PostgresConnection(connection)
        adapter.__exit__(RuntimeError, RuntimeError("failed"), None)
        connection.rollback.assert_called_once(); connection.close.assert_called_once()

    def test_all_migrations_are_idempotent_and_preserve_existing_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "migration.db"
            with patch.object(database, "DB_PATH", path), patch.object(database, "DATABASE_URL", f"sqlite:///{path}"):
                database.init_database()
                with database.connect() as db:
                    db.execute("INSERT INTO runs(id,name,status,source,params,created_at,updated_at,tenant_id) VALUES(?,?,?,?,?,?,?,?)", ("legacy", "kept", "completed", "migration-test", "{}", "now", "now", "default"))
                database.init_database()
                with database.connect() as db:
                    versions = [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
                    self.assertEqual(versions, list(range(1, 23)))
                    self.assertEqual(db.execute("SELECT name FROM runs WHERE id='legacy'").fetchone()[0], "kept")
                    self.assertIn("tenant_id", {row[1] for row in db.execute("PRAGMA table_info(runs)")})
                    self.assertTrue(db.execute("SELECT 1 FROM sqlite_master WHERE name='durable_tasks'").fetchone())
                self.assertEqual(database.database_label(), str(path))
                self.assertIn("+00:00", database._now_iso())
                import sqlite3
                self.assertTrue(database.is_integrity_error(sqlite3.IntegrityError("duplicate")))
                self.assertFalse(database.is_integrity_error(ValueError("other")))
                with patch.object(database, "DATABASE_URL", "postgresql://example/test"):
                    self.assertTrue(database.is_postgres())
                    self.assertEqual(database.database_label(), "PostgreSQL")

    def test_sqlite_connection_rolls_back_failed_transactions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollback.db"
            with patch.object(database, "DB_PATH", path), patch.object(database, "DATABASE_URL", f"sqlite:///{path}"):
                database.init_database()
                with self.assertRaises(RuntimeError):
                    with database.connect() as db:
                        db.execute("INSERT INTO tenants(id,name,created_at) VALUES(?,?,?)", ("rollback", "rollback", "now"))
                        raise RuntimeError("force rollback")
                with database.connect() as db:
                    self.assertIsNone(db.execute("SELECT id FROM tenants WHERE id='rollback'").fetchone())


class SecurityCoverageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "security.db"
        self.db_patch = patch.object(database, "DB_PATH", self.path)
        self.url_patch = patch.object(database, "DATABASE_URL", f"sqlite:///{self.path}")
        self.db_patch.start(); self.url_patch.start(); database.init_database()
        self.connect_patch = patch.object(security, "connect", database.connect); self.connect_patch.start()

    def tearDown(self):
        self.connect_patch.stop(); self.url_patch.stop(); self.db_patch.stop(); self.directory.cleanup()

    def test_invalid_auth_roles_tokens_and_quota_paths(self):
        owner, token = security.bootstrap("owner@example.com", "correct horse battery staple", "Lab")
        self.assertFalse(security.verify_password("bad", "invalid"))
        with self.assertRaises(ValueError): security.bootstrap("x@y.z", "short", "Other")
        with self.assertRaises(ValueError): security.login("owner@example.com", "wrong password")
        with patch.dict(os.environ, {"CLAWVISION_AUTH_MODE": "enabled"}):
            self.assertIsNone(security.authenticate(None)); self.assertIsNone(security.authenticate("Basic nope"))
            self.assertEqual(security.authenticate("Bearer " + token).role, "owner")
        viewer = security.create_member(owner, "viewer@example.com", "another secure password", "viewer")
        with database.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (viewer["userId"],)).fetchone()
        viewer_principal = security.Principal(row["id"], owner.tenant_id, "viewer", ("runs:read",))
        self.assertFalse(viewer_principal.permits("researcher")); self.assertTrue(viewer_principal.permits_scope("runs:read"))
        with self.assertRaises(PermissionError): security.create_member(viewer_principal, "new@example.com", "another secure password", "researcher")
        issued = security.issue_token(owner, "temporary", ["runs:read"], 1)
        with patch.dict(os.environ, {"CLAWVISION_AUTH_MODE": "enabled"}): self.assertEqual(security.authenticate("Bearer " + issued).scopes, ("runs:read",))
        token_id = security.list_tokens(owner)[0]["id"]
        self.assertTrue(security.revoke_token(owner, token_id))
        status = security.quota_status(owner)
        self.assertEqual(status["usage"]["activeTasks"], 0)


class DurableTaskRecoveryCoverageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.path = Path(self.directory.name) / "queue.db"
        self.db_patch = patch.object(database, "DB_PATH", self.path); self.url_patch = patch.object(database, "DATABASE_URL", f"sqlite:///{self.path}")
        self.db_patch.start(); self.url_patch.start(); database.init_database()

    def tearDown(self):
        self.url_patch.stop(); self.db_patch.stop(); self.directory.cleanup()

    def test_reaper_preserves_a_lease_renewed_after_its_initial_read(self):
        task = durable_queue.enqueue("default", "training", "run", {}, "renew-race")
        durable_queue.claim("live-worker", lease_seconds=5)
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with database.connect() as db:
            db.execute("UPDATE durable_tasks SET lease_expires_at=? WHERE id=?", (expired, task["id"]))
        original_connect = database.connect

        class RenewBeforeUpdate:
            def __enter__(self):
                self.db = original_connect()
                self.db.__enter__()
                return self

            def execute(self, sql, values=()):
                if sql.startswith("UPDATE durable_tasks SET status=?"):
                    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
                    with original_connect() as other:
                        other.execute("UPDATE durable_tasks SET lease_expires_at=? WHERE id=?", (future, task["id"]))
                return self.db.execute(sql, values)

            def __exit__(self, *args):
                return self.db.__exit__(*args)

        with patch.object(durable_queue, "connect", RenewBeforeUpdate):
            self.assertEqual(durable_queue.reap_expired(), 0)
        remaining = durable_queue.list_tasks("default")[0]
        self.assertEqual(remaining["status"], "leased")
        self.assertEqual(remaining["leaseOwner"], "live-worker")

    def test_expired_leases_requeue_then_dead_letter_and_cancel_is_tenant_scoped(self):
        first = durable_queue.enqueue("tenant-a", "training", "run-a", {}, "recover", max_attempts=2)
        claimed = durable_queue.claim("worker-a", kinds=["training"], lease_seconds=5)
        self.assertEqual(claimed["id"], first["id"])
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with database.connect() as db: db.execute("UPDATE durable_tasks SET lease_expires_at=? WHERE id=?", (expired, first["id"]))
        self.assertEqual(durable_queue.reap_expired(), 1)
        recovered = durable_queue.claim("worker-b", lease_seconds=5)
        self.assertEqual(recovered["attempts"], 2)
        with database.connect() as db: db.execute("UPDATE durable_tasks SET lease_expires_at=? WHERE id=?", (expired, first["id"]))
        self.assertEqual(durable_queue.reap_expired(), 1)
        self.assertEqual(durable_queue.list_tasks("tenant-a")[0]["status"], "dead-letter")
        queued = durable_queue.enqueue("tenant-a", "training", "run-b", {}, "cancel")
        self.assertFalse(durable_queue.cancel(queued["id"], "tenant-b")); self.assertTrue(durable_queue.cancel(queued["id"], "tenant-a"))


class SdkCoverageTests(unittest.TestCase):
    def test_batch_aliases_status_context_and_offline_replay(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"CLAWVISION_SPOOL_DIR": folder}):
            with patch.object(clawvision, "_request", return_value={"data": {}}) as request:
                run = clawvision.start_run("demo", params={"seed": 1}, buffer_size=50)
                run.log_param("batch", 8).log_metric("loss", 0.5, 1, val_loss=0.6).log_event("started").log_artifact("report", {"ok": True})
                run.log_point_cloud([[0, 0, 0]], 2).log_trajectory([[0, 0, 0]], 2).log_vector_field([], 2).log_simulation_frame([], 2)
                run.flush().resume("checkpoint").finish()
                payload = next(call.args[2] for call in request.call_args_list if call.args[1].endswith("/batch"))
                self.assertEqual(payload["metrics"][0]["trainLoss"], 0.5)
                self.assertEqual(payload["metrics"][0]["valLoss"], 0.6)
            with patch.object(clawvision, "_request", side_effect=clawvision.ClawVisionError("offline")):
                offline = clawvision.start_run("offline"); offline.log_metrics(1, accuracy=.8).flush(); offline.fail("lost")
                self.assertTrue(list(Path(folder).glob("*.jsonl")))
            with patch.object(clawvision, "_request", return_value={}):
                result = clawvision.sync_offline(folder)
                self.assertGreaterEqual(result["sent"], 3); self.assertEqual(result["remaining"], 0)

    def test_request_wraps_transport_and_invalid_json(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(clawvision.ClawVisionError): clawvision._request("http://local", "/api")


class AsgiCoverageTests(unittest.TestCase):
    def test_bridge_lifecycle_and_disconnect(self):
        application = asgi.ClawVisionASGI()
        fake_bridge = Mock()
        with patch.object(asgi.legacy, "initialize"), patch.object(asgi, "LegacyBridge", return_value=fake_bridge):
            self.assertIs(application._ensure_bridge(), fake_bridge)
            self.assertIs(application._ensure_bridge(), fake_bridge)

        application = asgi.ClawVisionASGI(); application._ensure_bridge = Mock()
        async def disconnect():
            sent=[]
            async def receive(): return {"type":"http.disconnect"}
            async def send(value): sent.append(value)
            await application({"type":"http","method":"GET","path":"/","headers":[]},receive,send)
            return sent
        self.assertEqual(asyncio.run(disconnect()), [])

    def test_http_stream_disconnect_unknown_scope_and_lifespan(self):
        application = asgi.ClawVisionASGI()
        bridge = Mock(port=1234); application._ensure_bridge = Mock(return_value=bridge)
        response = Mock(status=200); response.getheaders.return_value = [("Content-Type", "application/json"), ("Content-Length", "2")]; response.read1.side_effect = [b"{}", b""]
        connection = Mock(); connection.getresponse.return_value = response

        async def exercise_http():
            sent = []; messages = iter([{"type": "http.request", "body": b"{}", "more_body": False}])
            async def receive():
                try:
                    return next(messages)
                except StopIteration:
                    await asyncio.Future()
            async def send(message): sent.append(message)
            with patch.object(asgi.http.client, "HTTPConnection", return_value=connection):
                await application({"type": "http", "method": "POST", "path": "/api/test", "query_string": b"a=1", "headers": []}, receive, send)
            return sent
        sent = asyncio.run(exercise_http())
        self.assertEqual(sent[0]["status"], 200); self.assertEqual(sent[-1]["more_body"], False); connection.close.assert_called_once()

        async def unknown():
            sent=[]
            async def send(value): sent.append(value)
            await application({"type": "websocket"}, None, send); return sent
        self.assertEqual(asyncio.run(unknown())[0]["status"], 404)

        async def lifespan():
            sent=[]; messages=iter([{"type":"lifespan.startup"},{"type":"lifespan.shutdown"}])
            async def receive(): return next(messages)
            async def send(value): sent.append(value)
            application.bridge=bridge
            await application._lifespan(receive,send); return sent
        sent=asyncio.run(lifespan()); self.assertEqual(sent[-1]["type"],"lifespan.shutdown.complete"); bridge.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
