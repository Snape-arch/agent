"""Controlled self-evolution for Skill Registry artifacts."""

from __future__ import annotations

import json
import math
import hashlib
import hmac
import os
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from skills import skill_registry
from reflection.evolution_runtime import stable_bucket


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
        ("dependencies", []),
        ("manifest", {}),
    ):
        if key in item:
            item[key] = _decode(item[key], default)
    return item


class SkillEvolutionManager:
    """Version, evaluate, promote, and roll back skills with evidence."""

    HIGH_RISK_TOOLS = {
        "shell_exec", "file_write", "skill_delete", "git_workspace",
        "coding_workflow", "autonomous_subagents", "meeting_workflow",
        "office_artifact", "office_productivity", "web_fetch",
        "scholarly_download",
    }

    def __init__(self, store, signing_key_provider=None):
        self._store = store
        self._signing_key_provider = signing_key_provider or self._load_signing_key
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
                CREATE TABLE IF NOT EXISTS skill_review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    reviewer TEXT DEFAULT 'user',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_signatures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id INTEGER NOT NULL,
                    signature TEXT NOT NULL,
                    signer TEXT NOT NULL,
                    dependencies TEXT NOT NULL DEFAULT '[]',
                    signed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_audit_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id INTEGER NOT NULL,
                    suite_id INTEGER,
                    audit_type TEXT NOT NULL,
                    metrics TEXT NOT NULL DEFAULT '{}',
                    case_results TEXT NOT NULL DEFAULT '[]',
                    passed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_canaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_id INTEGER NOT NULL,
                    skill_name TEXT NOT NULL,
                    percent REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'running',
                    manifest TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
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
            "max_step_increase": 2,
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
        if version["status"] not in {"candidate", "validated", "rejected", "needs_changes"}:
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
        active = skill_registry.get_skill(version["skill_name"]) or {}
        baseline_steps = len(active.get("steps") or [])
        candidate_steps = len(version["definition"].get("steps") or [])
        metrics.update({
            "baseline_step_count": baseline_steps,
            "candidate_step_count": candidate_steps,
            "step_count_delta": candidate_steps - baseline_steps,
        })
        passed = (
            pass_rate >= float(thresholds["min_pass_rate"])
            and p95 <= float(thresholds["max_p95_latency_ms"])
            and candidate_steps - baseline_steps <= int(thresholds["max_step_increase"])
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
        if version["status"] not in {"validated", "canary"}:
            raise ValueError("only validated or canary skill versions can be promoted")
        if not self._latest_signature(version_id):
            raise ValueError("skill version must be signed before promotion")
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

    def review_inbox(self, status="", limit=100):
        inbox_statuses = ["candidate", "needs_changes", "rejected", "validated", "canary"]
        params = []
        query = "SELECT * FROM skill_versions"
        if status:
            query += " WHERE status=?"
            params.append(str(status))
        else:
            query += " WHERE status IN ({})".format(",".join("?" for _ in inbox_statuses))
            params.extend(inbox_statuses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(min(max(int(limit or 100), 1), 500))
        with self._store._conn() as c:
            rows = [_row(row) for row in c.execute(query, params).fetchall()]
            for version in rows:
                latest_run = c.execute(
                    "SELECT * FROM skill_eval_runs WHERE version_id=? ORDER BY id DESC LIMIT 1",
                    (int(version["id"]),),
                ).fetchone()
                events = c.execute(
                    "SELECT * FROM skill_review_events WHERE version_id=? ORDER BY id DESC LIMIT 5",
                    (int(version["id"]),),
                ).fetchall()
                version["latest_run"] = _row(latest_run)
                version["review_events"] = [dict(row) for row in events]
        return rows

    def review(self, version_id, action, reviewer="user", notes=""):
        allowed = {"needs_changes", "reject", "reopen"}
        action = str(action or "").strip()
        if action not in allowed:
            raise ValueError(f"review action must be one of: {', '.join(sorted(allowed))}")
        with self._store._conn() as c:
            version = c.execute(
                "SELECT * FROM skill_versions WHERE id=?", (int(version_id),)
            ).fetchone()
            if not version:
                raise ValueError("skill version not found")
            current = str(version["status"])
            if current in {"active", "archived", "rolled_back"}:
                raise ValueError(f"cannot review version from {current}")
            next_status = {
                "needs_changes": "needs_changes",
                "reject": "rejected",
                "reopen": "candidate",
            }[action]
            now = _now_iso()
            c.execute(
                "UPDATE skill_versions SET status=?, updated_at=? WHERE id=?",
                (next_status, now, int(version_id)),
            )
            c.execute(
                """INSERT INTO skill_review_events
                   (version_id, action, reviewer, notes, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (int(version_id), action, reviewer, notes, now),
            )
            row = c.execute(
                "SELECT * FROM skill_versions WHERE id=?", (int(version_id),)
            ).fetchone()
        return _row(row)

    def dependency_manifest(self, version_id):
        version = self._get_version(version_id)
        tools = []
        for step in version["definition"].get("steps", []):
            tool = str(step.get("tool", "")).strip()
            if tool and tool not in tools:
                tools.append(tool)
        manifest = {
            "skill_name": version["skill_name"],
            "version": version["version"],
            "tools": tools,
            "step_count": len(version["definition"].get("steps", [])),
            "requires_confirmation": any(tool in self.HIGH_RISK_TOOLS for tool in tools),
        }
        return manifest

    def sign_version(self, version_id, signer="system", secret=None):
        version = self._get_version(version_id)
        dependencies = self.dependency_manifest(version_id)
        secret = secret or self._signing_key_provider()
        if not secret:
            raise ValueError(
                "skill signing key is unavailable; configure OS keyring or CLAWOS_SKILL_SIGNING_KEY"
            )
        payload = json.dumps({
            "definition": version["definition"],
            "dependencies": dependencies,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")
        signature = hmac.new(str(secret).encode("utf-8"), payload, hashlib.sha256).hexdigest()
        now = _now_iso()
        with self._store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO skill_signatures
                    (version_id, signature, signer, dependencies, signed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(version_id), signature, str(signer or "system"),
                    json.dumps(dependencies, ensure_ascii=False), now,
                ),
            )
            row = c.execute(
                "SELECT * FROM skill_signatures WHERE id=?", (int(cursor.lastrowid),)
            ).fetchone()
            return _row(row)

    def verify_signature(self, version_id, signature):
        version = self._get_version(version_id)
        dependencies = self.dependency_manifest(version_id)
        secret = self._signing_key_provider()
        if not secret:
            raise ValueError("skill signing key is unavailable")
        payload = json.dumps({
            "definition": version["definition"],
            "dependencies": dependencies,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")
        expected = hmac.new(str(secret).encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(signature or ""))

    def fresh_agent_audit(self, version_id, suite_id=None):
        version = self._get_version(version_id)
        suite = None
        if suite_id:
            with self._store._conn() as c:
                suite = c.execute(
                    "SELECT * FROM skill_eval_suites WHERE id=?", (int(suite_id),)
                ).fetchone()
            suite = _row(suite)
            if not suite:
                raise ValueError("evaluation suite not found")
            if suite["skill_name"] != version["skill_name"]:
                raise ValueError("suite belongs to another skill")
            cases = suite["cases"]
        else:
            cases = [{
                "name": "fresh-agent-plan",
                "mode": "plan",
                "expected": {
                    "ok": True,
                    "step_count": len(version["definition"].get("steps", [])),
                    "tools": [step.get("tool") for step in version["definition"].get("steps", [])],
                },
            }]
        script = Path(__file__).resolve().parents[1] / "scripts" / "fresh_agent_skill_audit.py"
        audit_payload = {
            "definition": version["definition"],
            "cases": cases,
        }
        with tempfile.TemporaryDirectory() as td:
            env = {
                **os.environ,
                "CLAWOS_DATA_DIR": td,
                "CLAWOS_OUTPUT_DIR": str(Path(td) / "output"),
                "CLAWOS_FRESH_AGENT_AUDIT": "1",
            }
            completed = subprocess.run(
                [sys.executable, "-I", str(script)],
                input=json.dumps(audit_payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )
        if completed.returncode not in {0, 1}:
            raise ValueError(f"fresh-agent subprocess failed: {completed.stderr[-500:]}")
        try:
            isolated = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"fresh-agent subprocess returned invalid JSON: {exc}") from exc
        results = isolated.get("results") or []
        passed = all(item["passed"] and not item["silent_bypass"] for item in results)
        metrics = {
            "case_count": len(results),
            "passed_count": sum(1 for item in results if item["passed"]),
            "silent_bypass_count": sum(1 for item in results if item["silent_bypass"]),
            "isolated_process": True,
            "process_returncode": completed.returncode,
        }
        now = _now_iso()
        with self._store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO skill_audit_runs
                    (version_id, suite_id, audit_type, metrics, case_results, passed, created_at)
                VALUES (?, ?, 'fresh_agent', ?, ?, ?, ?)
                """,
                (
                    int(version_id), int(suite_id) if suite_id else None,
                    json.dumps(metrics, ensure_ascii=False),
                    json.dumps(results, ensure_ascii=False),
                    int(passed), now,
                ),
            )
            row = c.execute(
                "SELECT * FROM skill_audit_runs WHERE id=?", (int(cursor.lastrowid),)
            ).fetchone()
            return _row(row)

    def start_canary(self, version_id, percent=10, actor="system"):
        version = self._get_version(version_id)
        if version["status"] != "validated":
            raise ValueError("only validated versions can enter canary")
        if not self._latest_signature(version_id):
            raise ValueError("skill version must be signed before canary")
        dependencies = self.dependency_manifest(version_id)
        if dependencies["requires_confirmation"]:
            raise ValueError("high-risk skills cannot enter automatic canary")
        percent = max(0.0, min(float(percent), 100.0))
        manifest = {
            "actor": actor,
            "dependencies": dependencies,
            "note": "Stable task/session bucketing routes the configured percentage to this candidate.",
        }
        now = _now_iso()
        with self._store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO skill_canaries
                    (version_id, skill_name, percent, manifest, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(version_id), version["skill_name"], percent,
                    json.dumps(manifest, ensure_ascii=False), now,
                ),
            )
            c.execute(
                "UPDATE skill_versions SET status='canary', updated_at=? WHERE id=?",
                (now, int(version_id)),
            )
            row = c.execute(
                "SELECT * FROM skill_canaries WHERE id=?", (int(cursor.lastrowid),)
            ).fetchone()
            return _row(row)

    def select_runtime_definition(self, skill_name, identity=""):
        active = skill_registry.get_skill(skill_name)
        with self._store._conn() as c:
            row = c.execute(
                """
                SELECT c.*, v.definition, v.version
                FROM skill_canaries c
                JOIN skill_versions v ON v.id=c.version_id
                WHERE c.skill_name=? AND c.status='running' AND v.status='canary'
                ORDER BY c.id DESC LIMIT 1
                """,
                (skill_registry._sanitize_name(skill_name),),
            ).fetchone()
        if not row:
            return {
                "definition": active,
                "exposure": "baseline",
                "canary_id": None,
                "bucket": None,
            }
        item = _row(row)
        bucket = stable_bucket(identity, int(item["version_id"]))
        candidate = item["definition"] if bucket < float(item["percent"]) else active
        return {
            "definition": candidate,
            "exposure": "candidate" if candidate is item["definition"] else "baseline",
            "canary_id": int(item["id"]),
            "version_id": int(item["version_id"]),
            "bucket": bucket,
            "percent": float(item["percent"]),
        }

    def library_health(self):
        skills = skill_registry.list_skills()
        signatures = {}
        duplicates = []
        for skill in skills:
            signature = tuple(
                str(step.get("tool") or "") for step in skill.get("steps") or []
            )
            if signature in signatures:
                duplicates.append({
                    "skill": skill["name"],
                    "duplicate_of": signatures[signature],
                    "tool_sequence": list(signature),
                })
            else:
                signatures[signature] = skill["name"]
        stale = [
            {
                "skill": skill["name"],
                "use_count": int(skill.get("use_count") or 0),
                "last_used": skill.get("last_used") or "",
            }
            for skill in skills
            if int(skill.get("use_count") or 0) == 0
        ]
        complexity = [
            {
                "skill": skill["name"],
                "step_count": len(skill.get("steps") or []),
                "high_risk": self._manifest_for_definition(skill)["requires_confirmation"],
            }
            for skill in skills
        ]
        return {
            "skill_count": len(skills),
            "duplicate_sequences": duplicates,
            "stale_candidates": stale,
            "complexity": complexity,
            "recommendations_only": True,
        }

    def compact_library(self, dry_run=True, max_versions_per_skill=5, actor="system"):
        """Archive surplus non-active candidate history without deleting evidence."""

        keep = max(2, int(max_versions_per_skill))
        with self._store._conn() as c:
            names = [
                row["skill_name"]
                for row in c.execute(
                    "SELECT DISTINCT skill_name FROM skill_versions ORDER BY skill_name"
                ).fetchall()
            ]
            candidates = []
            for name in names:
                rows = c.execute(
                    """
                    SELECT id, version, status FROM skill_versions
                    WHERE skill_name=? ORDER BY version DESC
                    """,
                    (name,),
                ).fetchall()
                surplus = [
                    dict(row) for row in rows[keep:]
                    if row["status"] not in {"active", "canary"}
                ]
                candidates.extend({"skill_name": name, **item} for item in surplus)
            if not dry_run and candidates:
                ids = [int(item["id"]) for item in candidates]
                placeholders = ",".join("?" for _ in ids)
                c.execute(
                    f"""
                    UPDATE skill_versions
                    SET status='archived', updated_at=?
                    WHERE id IN ({placeholders})
                    """,
                    (_now_iso(), *ids),
                )
                for item in candidates:
                    c.execute(
                        """
                        INSERT INTO skill_review_events
                            (version_id, action, reviewer, notes, created_at)
                        VALUES (?, 'archive', ?, 'Library compaction', ?)
                        """,
                        (int(item["id"]), str(actor or "system"), _now_iso()),
                    )
        return {
            "dry_run": bool(dry_run),
            "archived_count": 0 if dry_run else len(candidates),
            "candidate_count": len(candidates),
            "versions": candidates,
            "evidence_deleted": False,
        }

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

    def _get_version(self, version_id):
        with self._store._conn() as c:
            row = c.execute(
                "SELECT * FROM skill_versions WHERE id=?", (int(version_id),)
            ).fetchone()
        version = _row(row)
        if not version:
            raise ValueError("skill version not found")
        return version

    def _latest_signature(self, version_id):
        with self._store._conn() as c:
            row = c.execute(
                """
                SELECT * FROM skill_signatures
                WHERE version_id=? ORDER BY id DESC LIMIT 1
                """,
                (int(version_id),),
            ).fetchone()
        return _row(row)

    @classmethod
    def _manifest_for_definition(cls, definition):
        tools = [
            str(step.get("tool") or "")
            for step in definition.get("steps") or []
            if step.get("tool")
        ]
        return {
            "tools": tools,
            "requires_confirmation": any(
                tool in cls.HIGH_RISK_TOOLS for tool in tools
            ),
        }

    @staticmethod
    def _load_signing_key():
        try:
            import keyring
            value = keyring.get_password("ClawOS", "skill-signing")
            if value:
                return value
        except Exception:
            pass
        return str(os.environ.get("CLAWOS_SKILL_SIGNING_KEY") or "")

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
