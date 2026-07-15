"""Feishu connector database schema.

The authoritative table creation/upgrade lives HERE, not in the connector
service constructor. ``MaintenanceService`` runs ``create_feishu_tables`` as
part of the ``2026_07_feishu_connector`` migration so the schema is created by
a real, repeatable migration. The connector service delegates to the same
helper for standalone/test robustness (idempotent ``CREATE TABLE IF NOT
EXISTS`` + guarded column additions), so there is a single source of truth and
re-running the migration on an existing database is safe.
"""
from __future__ import annotations

import sqlite3


FEISHU_DDL = """
CREATE TABLE IF NOT EXISTS feishu_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT '',
    event_id TEXT NOT NULL DEFAULT '',
    message_id TEXT NOT NULL DEFAULT '',
    chat_id TEXT NOT NULL DEFAULT '',
    sender_id TEXT NOT NULL DEFAULT '',
    message_type TEXT NOT NULL DEFAULT 'text',
    text TEXT NOT NULL DEFAULT '',
    create_time TEXT NOT NULL DEFAULT '',
    processed_status TEXT NOT NULL DEFAULT 'received',
    summary_json TEXT NOT NULL DEFAULT '{}',
    received_at TEXT DEFAULT (datetime('now')),
    UNIQUE(tenant_id, event_id),
    UNIQUE(tenant_id, message_id)
);

CREATE TABLE IF NOT EXISTS feishu_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    topic TEXT NOT NULL DEFAULT '',
    conclusions TEXT NOT NULL DEFAULT '[]',
    action_items TEXT NOT NULL DEFAULT '[]',
    owner_candidates TEXT NOT NULL DEFAULT '[]',
    deadline_candidates TEXT NOT NULL DEFAULT '[]',
    open_questions TEXT NOT NULL DEFAULT '[]',
    source_message_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feishu_approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL DEFAULT '',
    summary_id INTEGER NOT NULL DEFAULT 0,
    feishu_instance_code TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT 'chat',
    target_id TEXT NOT NULL DEFAULT '',
    inbound_msg_type TEXT NOT NULL DEFAULT 'text',
    outbound_msg_type TEXT NOT NULL DEFAULT 'text',
    body_text TEXT NOT NULL DEFAULT '',
    source_message_ids TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL DEFAULT '',
    approver_id TEXT NOT NULL DEFAULT '',
    verified_approver_open_ids TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT NOT NULL DEFAULT '',
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    created_at_epoch INTEGER NOT NULL DEFAULT 0,
    decided_at TEXT DEFAULT '',
    expires_at_epoch INTEGER NOT NULL DEFAULT 0,
    UNIQUE(idempotency_key)
);

CREATE TABLE IF NOT EXISTS feishu_dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT NOT NULL DEFAULT '',
    target_type TEXT NOT NULL DEFAULT 'chat',
    target_id TEXT NOT NULL DEFAULT '',
    msg_type TEXT NOT NULL DEFAULT 'text',
    status TEXT NOT NULL DEFAULT 'pending_approval',
    attempts INTEGER NOT NULL DEFAULT 0,
    feishu_message_id TEXT NOT NULL DEFAULT '',
    api_code INTEGER NOT NULL DEFAULT 0,
    api_msg TEXT NOT NULL DEFAULT '',
    trace_id TEXT NOT NULL DEFAULT '',
    error_category TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(idempotency_key),
    FOREIGN KEY(approval_id) REFERENCES feishu_approvals(id)
);
"""


def create_feishu_tables(conn: sqlite3.Connection) -> None:
    """Idempotently create the four Feishu connector tables and any additive
    column upgrades. Safe to call repeatedly (migration + service guard both
    delegate here)."""
    conn.executescript(FEISHU_DDL)
    # Additive migration for DBs created before the v2 columns. Guarded by
    # PRAGMA table_info so it is a no-op on an already-current schema.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(feishu_approvals)").fetchall()}
    if "verified_approver_open_ids" not in cols:
        conn.execute(
            "ALTER TABLE feishu_approvals ADD COLUMN verified_approver_open_ids TEXT NOT NULL DEFAULT '[]'"
        )


FEISHU_TABLES = (
    "feishu_messages",
    "feishu_summaries",
    "feishu_approvals",
    "feishu_dispatches",
)
