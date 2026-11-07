from __future__ import annotations

import json

from memoryos.persistence import Repository, atomic_workflow
from memoryos.serialization import task_row_to_dict


class EvolutionRepository(Repository):
    """Persistence operations for evolution."""

    def __init__(self, session, reflection):
        super().__init__(session)
        self._reflection = reflection

    @atomic_workflow
    def create_evolution_experiment(self, definition, definition_digest, created_by="system"):
        with self._conn() as c:
            cursor = c.execute("INSERT INTO evolution_experiments (definition,definition_digest,created_by) VALUES (?,?,?)",
                               (json.dumps(definition, ensure_ascii=False), definition_digest, str(created_by)))
            return self.get_evolution_experiment(cursor.lastrowid)


    def get_evolution_experiment(self, experiment_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM evolution_experiments WHERE id=?", (int(experiment_id),)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["definition"] = self._json_loads(result["definition"], {})
            result["report"] = self._json_loads(result["report"], {})
            from services.evolution_jobs import EvolutionJobStore
            result["job"] = EvolutionJobStore(self).summary(int(experiment_id), conn=c)
            return result


    def list_evolution_experiments(self, limit=50):
        with self._conn() as c:
            rows = c.execute("SELECT id FROM evolution_experiments ORDER BY id DESC LIMIT ?",
                             (max(1, min(int(limit), 100)),)).fetchall()
            return [self.get_evolution_experiment(row["id"]) for row in rows]


    def claim_evolution_experiment(self, experiment_id):
        from services.evolution_jobs import EvolutionJobStore
        return EvolutionJobStore(self).claim(experiment_id)


    def finish_evolution_experiment(self, experiment_id, report, failed=False, *, attempt_token=""):
        from services.evolution_jobs import EvolutionJobStore
        return EvolutionJobStore(self).finish(experiment_id, attempt_token, report, failed=failed)


    @atomic_workflow
    def create_self_evolution_run(
        self, title, target_type, target_key, baseline_payload, candidate_payload,
        benchmarks=None, conclusion="", publish_decision="pending",
        status="candidate", gate_result=None, created_by="system",
    ):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO self_evolution_runs
                    (title, target_type, target_key, baseline_payload,
                     candidate_payload, benchmarks, gate_result, conclusion,
                     publish_decision, status, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(title or "Self-evolution run"),
                    str(target_type or ""),
                    str(target_key or ""),
                    json.dumps(baseline_payload or {}, ensure_ascii=False),
                    json.dumps(candidate_payload or {}, ensure_ascii=False),
                    json.dumps(benchmarks or {}, ensure_ascii=False),
                    json.dumps(gate_result or {}, ensure_ascii=False),
                    str(conclusion or ""),
                    str(publish_decision or "pending"),
                    str(status or "candidate"),
                    str(created_by or "system"),
                ),
            )
            current = self._reflection.get_runtime_policy(target_type, target_key, conn=c)
            if current and current.get('active') and current['payload'] != baseline_payload:
                raise ValueError('baseline payload must match the current runtime policy')
            c.execute("UPDATE self_evolution_runs SET baseline_policy_version=? WHERE id=?",
                      (int(current['version']) if current else 0, cursor.lastrowid))
            return self.get_self_evolution_run(int(cursor.lastrowid), conn=c)


    def list_self_evolution_runs(self, status="", limit=100):
        with self._conn() as c:
            limit = max(1, min(int(limit or 100), 500))
            if status:
                rows = c.execute(
                    "SELECT * FROM self_evolution_runs WHERE status=? ORDER BY id DESC LIMIT ?",
                    (str(status), limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM self_evolution_runs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._self_evolution_run_from_row(row) for row in rows]


    def get_self_evolution_run(self, run_id, conn=None):
        def fetch(c):
            row = c.execute(
                "SELECT * FROM self_evolution_runs WHERE id=?", (int(run_id),)
            ).fetchone()
            return self._self_evolution_run_from_row(row) if row else None
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def update_self_evolution_run(
        self, run_id, status=None, benchmarks=None, gate_result=None,
        conclusion=None, publish_decision=None, rollback_payload=None,
        published_by=None, published_at=None, release_stage=None,
        traffic_percent=None, quality_signals=None,
    ):
        allowed = {
            "status": status,
            "benchmarks": benchmarks,
            "gate_result": gate_result,
            "conclusion": conclusion,
            "publish_decision": publish_decision,
            "rollback_payload": rollback_payload,
            "published_by": published_by,
            "published_at": published_at,
            "release_stage": release_stage,
            "traffic_percent": traffic_percent,
            "quality_signals": quality_signals,
        }
        json_fields = {"benchmarks", "gate_result", "rollback_payload", "quality_signals"}
        assignments = ["updated_at=datetime('now')"]
        params = []
        for key, value in allowed.items():
            if value is None:
                continue
            assignments.append(f"{key}=?")
            params.append(
                json.dumps(value or {}, ensure_ascii=False)
                if key in json_fields else str(value)
            )
        params.append(int(run_id))
        with self._conn() as c:
            c.execute(
                f"UPDATE self_evolution_runs SET {', '.join(assignments)} WHERE id=?",
                params,
            )
            return self.get_self_evolution_run(run_id, conn=c)


    @atomic_workflow
    def publish_self_evolution_run(self, run_id, actor_id="system", reason=""):
        with self._conn() as c:
            run = self.get_self_evolution_run(run_id, conn=c)
            if not run:
                raise ValueError("self-evolution run not found")
            if run["status"] not in {"validated", "shadow", "canary"}:
                raise ValueError("only validated, shadow, or canary runs can be activated")
            if run["publish_decision"] not in {"publish", "shadow_required", "canary"}:
                raise ValueError("self-evolution run is not approved for activation")
            current = self._reflection.get_runtime_policy(run["target_type"], run["target_key"], conn=c)
            if run.get("baseline_policy_version", -1) != (int(current['version']) if current else 0):
                raise ValueError("runtime policy changed; create and benchmark a fresh candidate")
            rollback = {
                "existed": bool(current),
                "payload": current["payload"] if current else {},
                "active": bool(current and current.get('active')),
            }
            version = int(current["version"]) + 1 if current else 1
            c.execute(
                """
                INSERT INTO runtime_policies
                    (target_type, target_key, payload, version, active, updated_by, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, datetime('now'))
                ON CONFLICT(target_type, target_key) DO UPDATE SET
                    payload=excluded.payload,
                    version=excluded.version,
                    active=1,
                    updated_by=excluded.updated_by,
                    updated_at=datetime('now')
                """,
                (
                    run["target_type"], run["target_key"],
                    json.dumps(run["candidate_payload"], ensure_ascii=False),
                    version, str(actor_id or "system"),
                ),
            )
            c.execute(
                """
                UPDATE self_evolution_runs
                SET status='published', release_stage='active', traffic_percent=100,
                    rollback_payload=?, published_by=?,
                    published_at=datetime('now'), updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    json.dumps({
                        **rollback,
                        "reason": str(reason or "Regression-gated self-evolution publish"),
                        "policy_version": version,
                    }, ensure_ascii=False),
                    str(actor_id or "system"),
                    int(run_id),
                ),
            )
            return self.get_self_evolution_run(run_id, conn=c)


    @atomic_workflow
    def rollback_self_evolution_run(self, run_id, actor_id="user", reason=""):
        with self._conn() as c:
            run = self.get_self_evolution_run(run_id, conn=c)
            if not run or run['status'] != 'published':
                raise ValueError('only a published self-evolution run can be rolled back')
            current = self._reflection.get_runtime_policy(run['target_type'], run['target_key'], conn=c)
            rollback = run['rollback_payload']
            if (not current or current['version'] != rollback.get('policy_version')
                    or current['payload'] != run['candidate_payload']):
                raise ValueError('runtime policy changed; rollback cannot overwrite a newer policy')
            c.execute('''UPDATE runtime_policies SET payload=?,version=version+1,active=?,
                updated_by=?,updated_at=datetime('now') WHERE target_type=? AND target_key=?''',
                (json.dumps(rollback.get('payload', {}), ensure_ascii=False),
                 int(rollback.get('active', rollback.get('existed', False))), actor_id, run['target_type'], run['target_key']))
            c.execute('''UPDATE self_evolution_runs SET status='rolled_back',release_stage='stopped',
                traffic_percent=0,publish_decision='reject',conclusion=?,updated_at=datetime('now') WHERE id=?''',
                (str(reason or 'Explicit rollback to previous runtime policy'), int(run_id)))
            return self.get_self_evolution_run(run_id, conn=c)


    def record_self_evolution_quality_signal(
        self, run_id, signal_type, value, metadata=None, created_by="system",
    ):
        with self._conn() as c:
            stage_row = c.execute("SELECT release_stage FROM self_evolution_runs WHERE id=?", (int(run_id),)).fetchone()
            if not stage_row:
                raise ValueError("self-evolution run not found")
            import math
            if not math.isfinite(float(value)) or not 0 <= float(value) <= 1:
                raise ValueError("quality signal must be finite and between zero and one")
            metadata = {**(metadata or {}), "observed_stage": stage_row["release_stage"]}
            c.execute(
                """
                INSERT INTO self_evolution_quality_signals
                    (run_id, signal_type, value, metadata, created_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(run_id),
                    str(signal_type or "quality"),
                    float(value or 0),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    str(created_by or "system"),
                ),
            )
            aggregate = self._aggregate_self_evolution_quality_signals(run_id, conn=c)
            c.execute(
                """
                UPDATE self_evolution_runs
                SET quality_signals=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (json.dumps(aggregate, ensure_ascii=False), int(run_id)),
            )
            run_row = c.execute(
                "SELECT status FROM self_evolution_runs WHERE id=?", (int(run_id),)
            ).fetchone()
            limits = {
                "user_retry_rate": 0.20,
                "cancel_rate": 0.15,
                "long_task_failure_rate": 0.10,
            }
            live = metadata.get('variant') != 'control' and metadata.get('source') not in {
                'runtime_snapshot', 'offline_replay', 'policy_materialization'}
            unhealthy = live and (float(value) > limits.get(signal_type, 1)
                                 or (signal_type == 'retrieval_hit_rate' and float(value) < .80))
            if run_row and run_row["status"] == "canary" and unhealthy:
                c.execute(
                    """
                    UPDATE self_evolution_runs
                    SET status='rolled_back', release_stage='stopped',
                        traffic_percent=0, publish_decision='reject',
                        conclusion='Canary stopped automatically after unhealthy runtime signal.',
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (int(run_id),),
                )
            return self.get_self_evolution_run(run_id, conn=c)


    def list_self_evolution_quality_signals(self, run_id, limit=100):
        with self._conn() as c:
            limit = max(1, min(int(limit or 100), 50000))
            rows = c.execute(
                """
                SELECT * FROM self_evolution_quality_signals
                WHERE run_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (int(run_id), limit),
            ).fetchall()
            return [self._self_evolution_signal_from_row(row) for row in rows]


    def runtime_quality_snapshot(self):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM tasks").fetchall()
            tasks = [task_row_to_dict(row) for row in rows]
            total = max(1, len(tasks))
            retry_count = sum(1 for task in tasks if int(task.get("attempt") or 1) > 1 or task.get("retry_of"))
            cancel_count = sum(1 for task in tasks if str(task.get("status")) in {"cancel_requested", "canceled", "cancelled"})
            failed_count = sum(1 for task in tasks if str(task.get("status")) == "failed")
            long_task_count = sum(1 for task in tasks if str((task.get("metadata") or {}).get("worker_action", "")).strip())
            report_saved = sum(
                1 for task in tasks
                if (task.get("metadata") or {}).get("response_payload", {}).get("report")
            )
            citation_rows = c.execute(
                "SELECT COUNT(*) AS count FROM document_chunks WHERE citation<>''"
            ).fetchone()
            retrieval_rows = c.execute(
                "SELECT metrics FROM retrieval_evaluation_runs ORDER BY id DESC LIMIT 20"
            ).fetchall()
            hit_rates = []
            for row in retrieval_rows:
                metrics = self._json_loads(row["metrics"], {})
                if "hit_rate" in metrics:
                    try:
                        hit_rates.append(float(metrics["hit_rate"]))
                    except (TypeError, ValueError):
                        pass
            retrieval_hit_rate = round(sum(hit_rates) / len(hit_rates), 4) if hit_rates else 0.0
            return {
                "task_count": len(tasks),
                "user_retry_rate": round(retry_count / total, 4),
                "cancel_rate": round(cancel_count / total, 4),
                "long_task_failure_rate": round(failed_count / max(1, long_task_count or len(tasks)), 4),
                "report_save_count": report_saved,
                "citation_hit_count": int(citation_rows["count"] or 0) if citation_rows else 0,
                "retrieval_hit_rate": retrieval_hit_rate,
            }


    def _aggregate_self_evolution_quality_signals(self, run_id, conn=None):
        def aggregate(c):
            rows = c.execute(
                """
                SELECT signal_type, value, metadata
                FROM self_evolution_quality_signals WHERE run_id=?
                """,
                (int(run_id),),
            ).fetchall()
            grouped = {}
            for row in rows:
                metadata = self._json_loads(row["metadata"], {})
                if str(metadata.get("variant") or "") == "control":
                    continue
                grouped.setdefault(row["signal_type"], []).append(float(row["value"] or 0))
            return {
                key: {
                    "count": len(values),
                    "average": round(sum(values) / max(1, len(values)), 6),
                    "latest": round(values[-1], 6),
                }
                for key, values in grouped.items()
            }
        if conn is not None:
            return aggregate(conn)
        with self._conn() as c:
            return aggregate(c)


    def publish_reflection_improvement(self, improvement_id, actor_id="system", reason=""):
        with self._conn() as c:
            improvement = c.execute(
                "SELECT * FROM reflection_improvements WHERE id=?",
                (int(improvement_id),),
            ).fetchone()
            if not improvement:
                raise ValueError("improvement not found")
            if improvement["status"] != "validated":
                raise ValueError("only validated improvements can be published")
            current = self._reflection.get_runtime_policy(
                improvement["target_type"], improvement["target_key"], conn=c
            )
            rollback = {
                "existed": bool(current),
                "payload": current["payload"] if current else {},
            }
            version = int(current["version"]) + 1 if current else 1
            c.execute(
                """
                INSERT INTO runtime_policies
                    (target_type, target_key, payload, version, active, updated_by, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, datetime('now'))
                ON CONFLICT(target_type, target_key) DO UPDATE SET
                    payload=excluded.payload,
                    version=excluded.version,
                    active=1,
                    updated_by=excluded.updated_by,
                    updated_at=datetime('now')
                """,
                (
                    improvement["target_type"], improvement["target_key"],
                    improvement["candidate_payload"], version, str(actor_id or "system"),
                ),
            )
            c.execute(
                """
                UPDATE reflection_improvements
                SET status='published', rollback_payload=?, published_at=datetime('now'),
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (json.dumps(rollback, ensure_ascii=False), int(improvement_id)),
            )
            c.execute(
                """
                INSERT INTO reflection_improvement_events
                    (improvement_id, from_status, to_status, actor_id, reason, data)
                VALUES (?, 'validated', 'published', ?, ?, ?)
                """,
                (
                    int(improvement_id), str(actor_id or "system"),
                    str(reason or "Validated strategy published"),
                    json.dumps({"policy_version": version}, ensure_ascii=False),
                ),
            )
            return self._reflection.get_reflection_improvement(improvement_id, conn=c)


    def rollback_reflection_improvement(self, improvement_id, actor_id="system", reason=""):
        with self._conn() as c:
            improvement = c.execute(
                "SELECT * FROM reflection_improvements WHERE id=?",
                (int(improvement_id),),
            ).fetchone()
            if not improvement:
                raise ValueError("improvement not found")
            if improvement["status"] != "published":
                raise ValueError("only published improvements can be rolled back")
            rollback = self._json_loads(improvement["rollback_payload"], {})
            current = self._reflection.get_runtime_policy(
                improvement["target_type"], improvement["target_key"], conn=c
            )
            version = int(current["version"]) + 1 if current else 1
            if rollback.get("existed"):
                c.execute(
                    """
                    UPDATE runtime_policies
                    SET payload=?, version=?, active=1, updated_by=?, updated_at=datetime('now')
                    WHERE target_type=? AND target_key=?
                    """,
                    (
                        json.dumps(rollback.get("payload", {}), ensure_ascii=False),
                        version, str(actor_id or "system"),
                        improvement["target_type"], improvement["target_key"],
                    ),
                )
            else:
                c.execute(
                    """
                    UPDATE runtime_policies
                    SET payload='{}', version=?, active=0, updated_by=?, updated_at=datetime('now')
                    WHERE target_type=? AND target_key=?
                    """,
                    (
                        version, str(actor_id or "system"),
                        improvement["target_type"], improvement["target_key"],
                    ),
                )
            c.execute(
                """
                UPDATE reflection_improvements
                SET status='rolled_back', rolled_back_at=datetime('now'),
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (int(improvement_id),),
            )
            c.execute(
                """
                INSERT INTO reflection_improvement_events
                    (improvement_id, from_status, to_status, actor_id, reason, data)
                VALUES (?, 'published', 'rolled_back', ?, ?, ?)
                """,
                (
                    int(improvement_id), str(actor_id or "system"),
                    str(reason or "Published strategy rolled back"),
                    json.dumps({"policy_version": version}, ensure_ascii=False),
                ),
            )
            return self._reflection.get_reflection_improvement(improvement_id, conn=c)


    def _self_evolution_run_from_row(self, row):
        item = dict(row)
        for key, default in (
            ("baseline_payload", {}),
            ("candidate_payload", {}),
            ("benchmarks", {}),
            ("gate_result", {}),
            ("quality_signals", {}),
            ("rollback_payload", {}),
        ):
            item[key] = self._json_loads(item.get(key), default)
        item["traffic_percent"] = float(item.get("traffic_percent") or 0)
        return item


    def _self_evolution_signal_from_row(self, row):
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        item["value"] = float(item.get("value") or 0)
        return item
