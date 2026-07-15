"""Phase 5 / §12: Feishu schema must be created by a real, repeatable
MaintenanceService migration — not hidden in the connector service constructor.

These tests assert the migration genuinely creates the four feishu_* tables and
the v2 additive column, that it is idempotent on fresh / existing / re-run
databases, and that the connector service reuses the same shared helper.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from memoryos.memory_store import MemoryStore

from services.feishu.schema import create_feishu_tables, FEISHU_TABLES
from services.maintenance_service import MaintenanceService


def _table_names(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'feishu_%'"
    ).fetchall()
    return tuple(sorted(r["name"] for r in rows))


def _has_column(conn, table, column):
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    return column in cols


class FeishuMigrationTests(unittest.TestCase):
    def test_shared_helper_creates_all_tables_and_column_idempotently(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "m.db")
            with store._conn() as c:
                # First run creates everything.
                create_feishu_tables(c)
                self.assertEqual(set(FEISHU_TABLES), set(_table_names(c)))
                self.assertTrue(_has_column(c, "feishu_approvals", "verified_approver_open_ids"))
                # Second run must be a safe no-op (idempotent).
                create_feishu_tables(c)
                self.assertEqual(set(FEISHU_TABLES), set(_table_names(c)))
                self.assertTrue(_has_column(c, "feishu_approvals", "verified_approver_open_ids"))

    def test_maintenance_apply_creates_feishu_tables(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "m.db")
            db_path = Path(td) / "m.db"
            svc = MaintenanceService(store=store, db_path=db_path, base_dir=Path(td), config={})
            result = svc.apply_migrations()
            self.assertTrue(result["ok"])
            applied_ids = {m["id"] for m in result["applied"]}
            self.assertIn("2026_07_feishu_connector", applied_ids)
            with store._conn() as c:
                self.assertEqual(set(FEISHU_TABLES), set(_table_names(c)))
                self.assertTrue(_has_column(c, "feishu_approvals", "verified_approver_open_ids"))

    def test_maintenance_reapply_is_safe_and_records_once(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "m.db")
            db_path = Path(td) / "m.db"
            svc = MaintenanceService(store=store, db_path=db_path, base_dir=Path(td), config={})
            svc.apply_migrations()
            # Re-running must not error and must not re-apply the feishu migration.
            result = svc.apply_migrations()
            applied_ids = {m["id"] for m in result["applied"]}
            self.assertNotIn("2026_07_feishu_connector", applied_ids)
            with store._conn() as c:
                self.assertEqual(set(FEISHU_TABLES), set(_table_names(c)))

    def test_connector_service_reuses_migration_schema(self):
        # Constructing the connector (e.g. in a test) must still yield the
        # same schema that the migration would create, via the shared helper.
        from services.feishu import FeishuConfig, FeishuConnectorService, FakeFeishuClient

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "m.db")
            cfg = FeishuConfig(tenant_id="t1", allowed_chat_ids=["oc1"], approver_open_ids=["ou1"])
            fake = FakeFeishuClient(cfg)
            svc = FeishuConnectorService(store, fake, cfg)
            with store._conn() as c:
                self.assertEqual(set(FEISHU_TABLES), set(_table_names(c)))
                self.assertTrue(_has_column(c, "feishu_approvals", "verified_approver_open_ids"))
                # The service can actually write and read a message row.
            svc.receive_event({
                "header": {"event_id": "e1", "event_type": "im.message.receive_v1"},
                "event": {"message": {"message_id": "om1", "chat_id": "oc1",
                                      "message_type": "text", "content": '{"text":"hi"}'}},
            })
            self.assertEqual(len(svc.list_messages()), 1)


if __name__ == "__main__":
    unittest.main()
