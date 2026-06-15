"""Controlled self-evolution for Skill Registry artifacts."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timezone

from skills import skill_registry


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _row(row):
    if row is None:
        return None
    item = dict(row)
    for key, default in (
        ("definition", {}),
        ("cases", []),
        ("metrics", {}),
        ("case_results", []),
        ("thresholds", {}),
        ("previous_definition", None),
    ):
        if key in item:
            item[key] = _decode(item[key], default)
    return item


class SkillEvolutionManager:
    """Version, evaluate, promote, and roll back skills with evidence."""

    def __init__(self, store):
        self._store = store
        self._init_db()

    def _init_db(self):
        with self._store._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS skill_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    definition TEXT NOT NULL,
                    parent_version_id INTEGER,
                    change_reason TEXT DEFAULT '',
                    source_ref TEXT DEFAULT '',
                    created_by TEXT DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(skill_name, version)
                );
                CREATE INDEX IF NOT EXISTS idx_skill_versions_name
                    ON skill_versions(skill_name, version DESC);
                CREATE TABLE IF NOT EXISTS skill_eval_suites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    cases TEXT NOT NULL,
                    frozen INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(skill_name, name)
                );
                CREATE TABLE IF NOT EXISTS skill_eval_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id INTEGER NOT NULL,
                    suite_id INTEGER NOT NULL,
                    metrics TEXT NOT NULL,
                    case_results TEXT NOT NULL,
                    thresholds TEXT NOT NULL,
                    passed INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    from_version_id INTEGER,
                    to_version_id INTEGER NOT NULL,
                    previous_definition TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    promoted_by TEXT DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    rolled_back_at TEXT
                );
            """)

    def propose(
        self, skill_name, definition, change_reason="",
        source_ref="", created_by="system",
    ):
        definition = deepcopy(definition or {})
        safe_name = skill_registry._sanitize_name(skill_name)
        definition["name"] = safe_name
        definition.setdefault("display_name", skill_name)
        validation = skill_registry.validate_skill_steps(definition.get("steps"))
        if validation["errors"]:
            raise ValueError("; ".join(validation["errors"]))
        active = skill_registry.get_skill(safe_name)
        with self._store._conn() as c:
            latest = c.execute(
                "SELECT * FROM skill_versions WHERE skill_name=? ORDER BY version DESC LIMIT 1",
                (safe_name,),
            ).fetchone()
            version = max(
                int(active.get("version", 0)) if active else 0,
                int(latest["version"]) if latest else 0,
            ) + 1
            parent_id = int(latest["id"]) if latest else None
            definition["version"] = version
            definition["use_count"] = 0
            now = _now_iso()
            cursor = c.execute(
                """INSERT INTO skill_versions
                   (skill_name, version, status, definition, parent_version_id,
                    change_reason, source_ref, created_by, created_at, updated_at)
                   VALUES (?, ?, 'candidate', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    safe_name, version, json.dumps(definition, ensure_ascii=False),
                    parent_id, change_reason, source_ref, created_by, now, now,
                ),
            )
            result = c.execute(
                "SELECT * FROM skill_versions WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return _row(result)

    def create_suite(self, name, skill_name, cases, frozen=True):
        if not isinstance(cases, list) or not cases:
            raise ValueError("evaluation suite requires at least one case")
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                raise ValueError(f"case {index} must be an object")
            if str(case.get("mode", "plan")) not in {"plan", "execute"}:
                raise ValueError(f"case {index} mode must be plan or execute")
        now = _now_iso()
        with self._store._conn() as c:
            cursor = c.execute(
                """INSERT INTO skill_eval_suites
                   (name, skill_name, cases, frozen, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    name, skill_registry._sanitize_name(skill_name),
                    json.dumps(cases, ensure_ascii=False), int(bool(frozen)), now,
                ),
            )
            result = c.execute(
                "SELECT * FROM skill_eval_suites WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return _row(result)

    def evaluate(self, version_id, suite_id, thresholds=None):
        thresholds = {
            "min_pass_rate": 1.0,
            "max_p95_latency_ms": 5000.0,
            **(thresholds or {}),
        }
        with self._store._conn() as c:
            version = c.execute(
                "SELECT * FROM skill_versions WHERE id=?", (int(version_id),)
            ).fetchone()
            suite = c.execute(
                "SELECT * FROM skill_eval_suites WHERE id=?", (int(suite_id),)
            ).fetchone()
        version, suite = _row(version), _row(suite)
        if not version or not suite:
            raise ValueError("skill version or evaluation suite not found")
        if version["skill_name"] != suite["skill_name"]:
            raise ValueError("evaluation suite belongs to another skill")
        if version["status"] not in {"candidate", "validated", "rejected"}:
            raise ValueError(f"version cannot be evaluated from {version['status']}")

        results = []
        latencies = []
        for case in suite["cases"]:
            mode = str(case.get("mode", "plan"))
            result = skill_registry.execute_skill_definition(
                version["definition"],
                params=case.get("params") or {},
                plan_only=(mode == "plan"),
            )
            passed, reasons = self._check_case(case, result)
            latency = float(result.get("total_elapsed_ms", 0))
            latencies.append(latency)
            results.append({
                "name": str(case.get("name") or f"case-{len(results) + 1}"),
                "mode": mode,
                "passed": passed,
                "reasons": reasons,
                "result": result,
            })
        passed_count = sum(1 for result in results if result["passed"])
        pass_rate = passed_count / len(results)
        p95 = self._percentile(latencies, 0.95)
        metrics = {
            "case_count": len(results),
            "passed_count": passed_count,
            "pass_rate": round(pass_rate, 6),
            "p95_latency_ms": round(p95, 3),
        }
        passed = (
            pass_rate >= float(thresholds["min_pass_rate"])
            and p95 <= float(thresholds["max_p95_latency_ms"])
        )
        status = "validated" if passed else "rejected"
        now = _now_iso()
        with self._store._conn() as c:
            cursor = c.execute(
                """INSERT INTO skill_eval_runs
                   (version_id, suite_id, metrics, case_results, thresholds, passed, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(version_id), int(suite_id),
                    json.dumps(metrics, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False),
                    json.dumps(thresholds, ensure_ascii=False),
                    int(passed), now,
                ),
            )
            c.execute(
                "UPDATE skill_versions SET status=?, updated_at=? WHERE id=?",
                (status, now, int(version_id)),
            )
            run = c.execute(
                "SELECT * FROM skill_eval_runs WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return _row(run)

    def promote(self, version_id, actor="system"):
        with self._store._conn() as c:
            version = c.execute(
                "SELECT * FROM skill_versions WHERE id=?", (int(version_id),)
            ).fetchone()
        version = _row(version)
        if not version:
            raise ValueError("skill version not found")
        if version["status"] != "validated":
            raise ValueError("only validated skill versions can be promoted")
        current = skill_registry.get_skill(version["skill_name"])
        published = skill_registry.publish_skill_definition(version["definition"])
        if published.get("error"):
            raise ValueError(str(published["error"]))
        now = _now_iso()
        with self._store._conn() as c:
            previous = c.execute(
                """SELECT id FROM skill_versions
                   WHERE skill_name=? AND status='active' ORDER BY version DESC LIMIT 1""",
                (version["skill_name"],),
            ).fetchone()
            c.execute(
                """UPDATE skill_versions SET status='archived', updated_at=?
                   WHERE skill_name=? AND status='active'""",
                (now, version["skill_name"]),
            )
            c.execute(
                "UPDATE skill_versions SET status='active', updated_at=? WHERE id=?",
                (now, int(version_id)),
            )
            cursor = c.execute(
                """INSERT INTO skill_promotions
                   (skill_name, from_version_id, to_version_id, previous_definition,
                    promoted_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    version["skill_name"],
                    int(previous["id"]) if previous else None,
                    int(version_id),
                    json.dumps(current, ensure_ascii=False) if current else None,
                    actor, now,
                ),
            )
            promotion = c.execute(
                "SELECT * FROM skill_promotions WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return _row(promotion)

    def rollback(self, promotion_id):
        with self._store._conn() as c:
            promotion = c.execute(
                "SELECT * FROM skill_promotions WHERE id=?", (int(promotion_id),)
            ).fetchone()
        promotion = _row(promotion)
        if not promotion:
            raise ValueError("skill promotion not found")
        if promotion["status"] != "active":
            raise ValueError("skill promotion is not active")
        previous = promotion["previous_definition"]
        if previous:
            result = skill_registry.publish_skill_definition(previous)
            if result.get("error"):
                raise ValueError(str(result["error"]))
        else:
            skill_registry.delete_skill(promotion["skill_name"])
        now = _now_iso()
        with self._store._conn() as c:
            c.execute(
                "UPDATE skill_versions SET status='rolled_back', updated_at=? WHERE id=?",
                (now, promotion["to_version_id"]),
            )
            if promotion["from_version_id"]:
                c.execute(
                    "UPDATE skill_versions SET status='active', updated_at=? WHERE id=?",
                    (now, promotion["from_version_id"]),
                )
            c.execute(
                """UPDATE skill_promotions
                   SET status='rolled_back', rolled_back_at=? WHERE id=?""",
                (now, int(promotion_id)),
            )
            result = c.execute(
                "SELECT * FROM skill_promotions WHERE id=?", (int(promotion_id),)
            ).fetchone()
        return _row(result)

    def list_versions(self, skill_name="", limit=100):
        query = "SELECT * FROM skill_versions"
        params = []
        if skill_name:
            query += " WHERE skill_name=?"
            params.append(skill_registry._sanitize_name(skill_name))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 500))
        with self._store._conn() as c:
            rows = c.execute(query, params).fetchall()
        return [_row(row) for row in rows]

    def list_runs(self, version_id=0, limit=100):
        query = "SELECT * FROM skill_eval_runs"
        params = []
        if version_id:
            query += " WHERE version_id=?"
            params.append(int(version_id))
        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(max(int(limit), 1), 500))
        with self._store._conn() as c:
            rows = c.execute(query, params).fetchall()
        return [_row(row) for row in rows]

    @staticmethod
    def _check_case(case, result):
        expected = case.get("expected") or {}
        reasons = []
        if bool(result.get("ok")) != bool(expected.get("ok", True)):
            reasons.append("unexpected execution status")
        if "step_count" in expected and int(result.get("steps", -1)) != int(expected["step_count"]):
            reasons.append("unexpected step count")
        expected_tools = expected.get("tools")
        if expected_tools is not None:
            actual_tools = [item.get("tool") for item in result.get("outputs", [])]
            if actual_tools != list(expected_tools):
                reasons.append("unexpected tool sequence")
        max_latency = case.get("max_latency_ms")
        if max_latency is not None and float(result.get("total_elapsed_ms", 0)) > float(max_latency):
            reasons.append("case latency exceeded")
        return not reasons, reasons

    @staticmethod
    def _percentile(values, fraction):
        if not values:
            return 0.0
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
        return float(ordered[index])
