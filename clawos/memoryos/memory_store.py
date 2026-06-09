"""MemoryStore — SQLite-backed persistent memory for ClawOS.

TABLES:
  profiles       — key-value profile info (name, interests, skills, etc.)
  preferences    — user preferences (style, tools, communication, risk)
  conversations  — multi-turn conversation history per session
  projects       — project tracking (goals, progress, team)
  experiences    — success/failure cases for reflection
"""

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MemoryStore:
    """Thread-safe SQLite memory store."""

    def __init__(self, db_path: str = ""):
        self._db_path = db_path or str(Path(__file__).parent.parent / "memoryos.db")
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'general',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(category, key)
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'general',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(category, key)
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, created_at);
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT DEFAULT '',
                    goals TEXT DEFAULT '[]',
                    progress TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    team_members TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('success','failure','partial')),
                    lesson TEXT DEFAULT '',
                    context TEXT DEFAULT '',
                    solution TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    importance REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'domain',
                    title TEXT NOT NULL, content TEXT NOT NULL,
                    source TEXT DEFAULT '', tags TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 0.5, access_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS context_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_description TEXT DEFAULT '',
                    active_tools TEXT DEFAULT '[]',
                    environment TEXT DEFAULT '',
                    user_intent TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS skill_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    usage_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
                    avg_duration_ms REAL DEFAULT 0, last_used TEXT DEFAULT '',
                    feedback TEXT DEFAULT '', quality_score REAL DEFAULT 0.5
                );
            """)
            self._ensure_columns(c, "experiences", {
                "solution": "TEXT DEFAULT ''",
                "tags": "TEXT DEFAULT '[]'",
                "importance": "REAL DEFAULT 0.5",
            })
            self._ensure_columns(c, "knowledge", {
                "source": "TEXT DEFAULT ''",
                "tags": "TEXT DEFAULT '[]'",
                "confidence": "REAL DEFAULT 0.5",
                "access_count": "INTEGER DEFAULT 0",
                "updated_at": "TEXT DEFAULT ''",
            })
            self._ensure_columns(c, "skill_records", {
                "feedback": "TEXT DEFAULT ''",
                "quality_score": "REAL DEFAULT 0.5",
            })

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, spec in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")

    # ── PROFILE ──

    def set_profile(self, key: str, value: str, category: str = "general", importance: float = 0.5):
        with self._conn() as c:
            c.execute("""
                INSERT INTO profiles (category, key, value, importance, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    importance = excluded.importance,
                    updated_at = datetime('now')
            """, (category, key, value, importance))

    def get_profile(self, key: str, category: str = "general") -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM profiles WHERE category=? AND key=?", (category, key)
            ).fetchone()
            return dict(row) if row else None

    def get_all_profiles(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM profiles ORDER BY importance DESC").fetchall()
            return [dict(r) for r in rows]

    # ── PREFERENCES ──

    def set_preference(self, key: str, value: str, category: str = "general", confidence: float = 0.5):
        with self._conn() as c:
            c.execute("""
                INSERT INTO preferences (category, key, value, confidence, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    updated_at = datetime('now')
            """, (category, key, value, confidence))

    def get_preference(self, key: str, category: str = "general") -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM preferences WHERE category=? AND key=?", (category, key)
            ).fetchone()
            return dict(row) if row else None

    def get_all_preferences(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM preferences ORDER BY confidence DESC").fetchall()
            return [dict(r) for r in rows]

    # ── CONVERSATIONS ──

    def add_message(self, session_id: str, role: str, content: str, tool_calls: str = "", metadata: str = ""):
        with self._conn() as c:
            # Auto-truncate: keep max 100 messages per session
            count = c.execute("SELECT COUNT(*) FROM conversations WHERE session_id=?", (session_id,)).fetchone()[0]
            if count >= 100:
                c.execute(
                    "DELETE FROM conversations WHERE id IN (SELECT id FROM conversations WHERE session_id=? ORDER BY created_at ASC LIMIT 10)",
                    (session_id,)
                )
            c.execute(
                "INSERT INTO conversations (session_id, role, content, tool_calls, metadata) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content[:8000], tool_calls, metadata)
            )

    def get_session_messages(self, session_id: str, limit: int = 30) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content, tool_calls, metadata, created_at FROM conversations WHERE session_id=? ORDER BY id ASC LIMIT ?",
                (session_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_messages(self, session_id: str, n: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, n)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_session_summary(self, session_id: str) -> str:
        """Generate a text summary of recent session activity."""
        msgs = self.get_recent_messages(session_id, 30)
        if not msgs:
            return "No previous conversation."
        summary_parts = []
        user_msgs = [m for m in msgs if m["role"] == "user"]
        for m in user_msgs[-5:]:
            content = m.get("content", "")
            summary_parts.append(f"user asked: {content[:200]}")
        return "Recent conversation:\n" + "\n".join(summary_parts)

    # ── PROJECTS ──

    def upsert_project(self, name: str, description: str = "", goals: list | None = None,
                        progress: str = "", status: str = "active", team: list | None = None):
        with self._conn() as c:
            c.execute("""
                INSERT INTO projects (name, description, goals, progress, status, team_members, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    goals = excluded.goals,
                    progress = excluded.progress,
                    status = excluded.status,
                    team_members = excluded.team_members,
                    updated_at = datetime('now')
            """, (name, description, json.dumps(goals or []), progress, status, json.dumps(team or [])))

    def get_project(self, name: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM projects WHERE name=?", (name,)).fetchone()
            return dict(row) if row else None

    def list_projects(self, status: str = "") -> list[dict]:
        with self._conn() as c:
            if status:
                rows = c.execute("SELECT * FROM projects WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
            return [dict(r) for r in rows]

    # ── EXPERIENCES ──

    def add_experience(self, task, outcome, lesson="", context="", solution="", tags=None, importance=0.5):
        with self._conn() as c:
            c.execute(
                "INSERT INTO experiences (task,outcome,lesson,context,solution,tags,importance) VALUES (?,?,?,?,?,?,?)",
                (task, outcome, lesson, context, solution, json.dumps(tags or []), importance)
            )

    def get_recent_experiences(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM experiences ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ── STATS ──

    def list_sessions(self) -> list[dict]:
        """List all conversation sessions with last message preview."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT session_id, MAX(id) AS last_id
                FROM conversations
                GROUP BY session_id
                ORDER BY last_id DESC
            """).fetchall()
            result = []
            for row in rows:
                sid = row["session_id"]
                msgs = c.execute("""SELECT role, content, created_at FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 1""", (sid,)).fetchone()
                result.append({
                    "session_id": sid,
                    "role": (str(dict(msgs).get("role", "")) if msgs else ""),
                    "last_message": (str(dict(msgs).get("content", ""))[:100] if msgs else ""),
                    "updated_at": (str(dict(msgs).get("created_at", "")) if msgs else ""),
                })
            return result

    def get_stats(self) -> dict:
        with self._conn() as c:
            return {
                "profiles": c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0],
                "preferences": c.execute("SELECT COUNT(*) FROM preferences").fetchone()[0],
                "conversations": c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                "projects": c.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "experiences": c.execute("SELECT COUNT(*) FROM experiences").fetchone()[0],
            }
    # ── KNOWLEDGE ──

    def add_knowledge(self, title, content, category="domain", source="", tags=None, confidence=0.5):
        with self._conn() as c:
            c.execute("INSERT INTO knowledge (category,title,content,source,tags,confidence) VALUES (?,?,?,?,?,?)",
                      (category, title, content, source, json.dumps(tags or []), confidence))

    def search_knowledge(self, query, category="", limit=10):
        with self._conn() as c:
            if category:
                rows = c.execute("SELECT * FROM knowledge WHERE category=? AND (title LIKE ? OR content LIKE ?) ORDER BY confidence DESC LIMIT ?",
                                 (category, f"%{query}%", f"%{query}%", limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM knowledge WHERE title LIKE ? OR content LIKE ? ORDER BY confidence DESC LIMIT ?",
                                 (f"%{query}%", f"%{query}%", limit)).fetchall()
            for r in rows:
                c.execute("UPDATE knowledge SET access_count=access_count+1 WHERE id=?", (r["id"],))
            return [dict(r) for r in rows]

    def get_knowledge_by_id(self, kid):
        with self._conn() as c:
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (kid,)).fetchone()
            if row: c.execute("UPDATE knowledge SET access_count=access_count+1 WHERE id=?", (kid,))
            return dict(row) if row else None

    def list_knowledge(self, category=""):
        with self._conn() as c:
            sql = "SELECT * FROM knowledge" + (" WHERE category=?" if category else "") + " ORDER BY access_count DESC"
            rows = c.execute(sql, (category,) if category else ()).fetchall()
            return [dict(r) for r in rows]

    # ── CONTEXT SNAPSHOTS ──

    def save_context_snapshot(self, session_id, task="", active_tools=None, environment="", user_intent=""):
        with self._conn() as c:
            c.execute("INSERT INTO context_snapshots (session_id,task_description,active_tools,environment,user_intent) VALUES (?,?,?,?,?)",
                      (session_id, task, json.dumps(active_tools or []), environment, user_intent))
            c.execute("DELETE FROM context_snapshots WHERE id NOT IN (SELECT id FROM context_snapshots WHERE session_id=? ORDER BY id DESC LIMIT 20)",
                      (session_id,))

    def get_latest_context(self, session_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM context_snapshots WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
            return dict(row) if row else None

    # ── SKILL RECORDS ──

    def record_skill_usage(self, skill_name, success=True, duration_ms=0, feedback="", category="general"):
        with self._conn() as c:
            row = c.execute("SELECT * FROM skill_records WHERE skill_name=?", (skill_name,)).fetchone()
            if row:
                total = row["usage_count"] + 1
                sc = row["success_count"] + (1 if success else 0)
                avg = (row["avg_duration_ms"] * row["usage_count"] + duration_ms) / total
                c.execute("UPDATE skill_records SET usage_count=?,success_count=?,avg_duration_ms=?,last_used=datetime('now'),feedback=?,quality_score=? WHERE skill_name=?",
                          (total, sc, avg, feedback, sc/total, skill_name))
            else:
                c.execute("INSERT INTO skill_records (skill_name,category,usage_count,success_count,avg_duration_ms,last_used,feedback,quality_score) VALUES (?,?,1,?,?,datetime('now'),?,?)",
                          (skill_name, category, 1 if success else 0, duration_ms, feedback, 1.0 if success else 0.3))

    def get_skill_stats(self, skill_name=""):
        with self._conn() as c:
            if skill_name:
                row = c.execute("SELECT * FROM skill_records WHERE skill_name=?", (skill_name,)).fetchone()
                return dict(row) if row else {}
            return [dict(r) for r in c.execute("SELECT * FROM skill_records ORDER BY usage_count DESC").fetchall()]

    # ── BULK SEARCH ──

    def search_all_text(self, query, limit=20):
        results = []
        with self._conn() as c:
            rows = c.execute("""
                SELECT id, title AS title, content AS body, category AS type, 'knowledge' AS _source, created_at
                FROM knowledge
                WHERE title LIKE ? OR content LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
            results.extend(dict(r) for r in rows)

            rows = c.execute("""
                SELECT id, task AS title, lesson || ' ' || context || ' ' || solution AS body,
                       outcome AS type, 'experiences' AS _source, created_at
                FROM experiences
                WHERE task LIKE ? OR lesson LIKE ? OR context LIKE ? OR solution LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
            results.extend(dict(r) for r in rows)
        return results
