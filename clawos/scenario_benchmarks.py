"""Frozen scenario benchmark suites for competition-grade ClawOS validation."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode(value, default):
    try:
        return json.loads(value or "")
    except Exception:
        return default


def _row(row):
    if row is None:
        return None
    item = dict(row)
    for key, default in (
        ("cases", []),
        ("metrics", {}),
        ("case_results", []),
        ("thresholds", {}),
    ):
        if key in item:
            item[key] = _decode(item[key], default)
    return item


DEFAULT_SCENARIO_CASES = [
    {
        "name": "meeting_create",
        "scenario": "meeting",
        "tool": "meeting_workflow",
        "args": {
            "action": "create",
            "title": "Frozen benchmark weekly sync",
            "attendees": ["Alice", "Bob"],
            "agenda": ["progress", "risks"],
        },
        "expected": {"ok": True, "status": "success"},
        "max_latency_ms": 3000,
    },
    {
        "name": "learning_goal_create",
        "scenario": "learning",
        "tool": "learning_workspace",
        "args": {
            "action": "create_goal",
            "title": "Agent benchmark learning",
            "topics": ["MemoryOS", "Reflection"],
        },
        "expected": {"ok": True, "status": "success"},
        "max_latency_ms": 3000,
    },
    {
        "name": "template_catalog",
        "scenario": "project",
        "tool": "template_list",
        "args": {},
        "expected": {"ok": True, "status": "success"},
        "max_latency_ms": 2000,
    },
    {
        "name": "skill_catalog",
        "scenario": "skill",
        "tool": "skill_list",
        "args": {},
        "expected": {"ok": True, "status": "success"},
        "max_latency_ms": 2000,
    },
    {
        "name": "memory_stats",
        "scenario": "memory",
        "tool": "memory_stats",
        "args": {},
        "expected": {"ok": True, "status": "success"},
        "max_latency_ms": 1500,
    },
]


class FrozenScenarioBenchmark:
    """Persist and run frozen scenario suites through the same tool envelope."""

    def __init__(self, store):
        self._store = store
        self._init_db()
        self.ensure_default_suite()

    def _init_db(self):
        with self._store._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS scenario_benchmark_suites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT DEFAULT '',
                    cases TEXT NOT NULL,
                    frozen INTEGER NOT NULL DEFAULT 1,
                    created_by TEXT DEFAULT 'system',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS scenario_benchmark_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    suite_id INTEGER NOT NULL,
                    metrics TEXT NOT NULL,
                    case_results TEXT NOT NULL,
                    thresholds TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    created_by TEXT DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(suite_id) REFERENCES scenario_benchmark_suites(id)
                );
            """)

    def ensure_default_suite(self):
        with self._store._conn() as c:
            row = c.execute(
                "SELECT * FROM scenario_benchmark_suites WHERE name='competition-frozen-v1'"
            ).fetchone()
            if row:
                return _row(row)
            now = _now_iso()
            cursor = c.execute(
                """
                INSERT INTO scenario_benchmark_suites
                    (name, description, cases, frozen, created_by, created_at)
                VALUES (?, ?, ?, 1, 'system', ?)
                """,
                (
                    "competition-frozen-v1",
                    "Frozen multi-scenario acceptance suite for meeting, learning, project, skill, and memory flows.",
                    json.dumps(DEFAULT_SCENARIO_CASES, ensure_ascii=False),
                    now,
                ),
            )
            row = c.execute(
                "SELECT * FROM scenario_benchmark_suites WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            return _row(row)

    def create_suite(self, name, cases, description="", created_by="user"):
        if not isinstance(cases, list) or not cases:
            raise ValueError("cases must be a non-empty list")
        for index, case in enumerate(cases):
            if not case.get("tool"):
                raise ValueError(f"case {index} is missing tool")
        now = _now_iso()
        with self._store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO scenario_benchmark_suites
                    (name, description, cases, frozen, created_by, created_at)
                VALUES (?, ?, ?, 1, ?, ?)
                """,
                (
                    str(name or "custom-suite"),
                    str(description or ""),
                    json.dumps(cases, ensure_ascii=False),
                    str(created_by or "user"),
                    now,
                ),
            )
            row = c.execute(
                "SELECT * FROM scenario_benchmark_suites WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            return _row(row)

    def list_suites(self):
        with self._store._conn() as c:
            rows = c.execute(
                "SELECT * FROM scenario_benchmark_suites ORDER BY id DESC"
            ).fetchall()
            return [_row(row) for row in rows]

    def run_suite(self, suite_id, runner, thresholds=None, created_by="user"):
        thresholds = {
            "min_pass_rate": 1.0,
            "max_p95_latency_ms": 3000.0,
            **(thresholds or {}),
        }
        with self._store._conn() as c:
            suite = c.execute(
                "SELECT * FROM scenario_benchmark_suites WHERE id=?",
                (int(suite_id),),
            ).fetchone()
        suite = _row(suite)
        if not suite:
            raise ValueError("benchmark suite not found")
        case_results = []
        latencies = []
        for case in suite["cases"]:
            started = time.perf_counter()
            result = runner(case["tool"], case.get("args") or {})
            elapsed = float(result.get("duration_ms") or round((time.perf_counter() - started) * 1000, 3))
            latencies.append(elapsed)
            passed, reasons = self._check_case(case, result, elapsed)
            case_results.append({
                "name": case.get("name", case["tool"]),
                "scenario": case.get("scenario", "general"),
                "tool": case["tool"],
                "passed": passed,
                "reasons": reasons,
                "latency_ms": elapsed,
                "result": result,
            })
        passed_count = sum(1 for item in case_results if item["passed"])
        pass_rate = passed_count / len(case_results)
        p95 = self._percentile(latencies, 0.95)
        metrics = {
            "case_count": len(case_results),
            "passed_count": passed_count,
            "pass_rate": round(pass_rate, 6),
            "p95_latency_ms": round(p95, 3),
            "scenarios": sorted({item["scenario"] for item in case_results}),
        }
        passed = (
            pass_rate >= float(thresholds["min_pass_rate"])
            and p95 <= float(thresholds["max_p95_latency_ms"])
        )
        now = _now_iso()
        with self._store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO scenario_benchmark_runs
                    (suite_id, metrics, case_results, thresholds, passed, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(suite_id),
                    json.dumps(metrics, ensure_ascii=False),
                    json.dumps(case_results, ensure_ascii=False),
                    json.dumps(thresholds, ensure_ascii=False),
                    int(passed),
                    str(created_by or "user"),
                    now,
                ),
            )
            row = c.execute(
                "SELECT * FROM scenario_benchmark_runs WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
            return _row(row)

    def list_runs(self, suite_id=0, limit=50):
        params = []
        query = "SELECT * FROM scenario_benchmark_runs"
        if suite_id:
            query += " WHERE suite_id=?"
            params.append(int(suite_id))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(max(int(limit or 50), 1), 200))
        with self._store._conn() as c:
            rows = c.execute(query, params).fetchall()
            return [_row(row) for row in rows]

    @staticmethod
    def _check_case(case, result, latency_ms):
        expected = case.get("expected") or {}
        reasons = []
        if bool(result.get("ok")) != bool(expected.get("ok", True)):
            reasons.append("unexpected ok flag")
        if expected.get("status") and result.get("status") != expected["status"]:
            reasons.append("unexpected status")
        max_latency = case.get("max_latency_ms")
        if max_latency is not None and float(latency_ms) > float(max_latency):
            reasons.append("case latency exceeded")
        return not reasons, reasons

    @staticmethod
    def _percentile(values, fraction):
        if not values:
            return 0.0
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction)))
        return float(ordered[index])
