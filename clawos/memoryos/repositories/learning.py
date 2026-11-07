from __future__ import annotations

import json

from memoryos.persistence import Repository, atomic_workflow


class LearningRepository(Repository):
    """Persistence operations for learning."""

    def ensure_agent_trajectory(
        self, task_id, scenario="general", task_context=None, user_context=None,
        environment_state=None, policy_version="",
    ):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM agent_trajectories WHERE task_id=?",
                (int(task_id),),
            ).fetchone()
            if row:
                return self._agent_trajectory_from_row(row)
            task = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not task:
                raise ValueError("task not found")
            metadata = self._json_loads(task["metadata"], {})
            cursor = c.execute(
                """
                INSERT INTO agent_trajectories
                    (task_id, session_id, scenario, task_context, user_context,
                     environment_state, policy_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(task_id), str(task["session_id"] or ""),
                    str(scenario or metadata.get("scenario") or "general"),
                    json.dumps(task_context or {
                        "title": task["title"],
                        "source": task["source"],
                        "attempt": int(task["attempt"] or 1),
                    }, ensure_ascii=False),
                    json.dumps(user_context or {}, ensure_ascii=False),
                    json.dumps(environment_state or {}, ensure_ascii=False),
                    str(policy_version or metadata.get("policy_version") or ""),
                ),
            )
            row = c.execute(
                "SELECT * FROM agent_trajectories WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return self._agent_trajectory_from_row(row)


    def append_agent_trajectory_step(
        self, task_id, state, action_type, action_name, action_payload=None,
        observation=None, reward_components=None, step_reward=None,
        policy_selection_id=None, behavior_propensity=1.0,
        safety_violation=False,
    ):
        trajectory = self.ensure_agent_trajectory(task_id)
        with self._conn() as c:
            if policy_selection_id:
                existing = c.execute(
                    """
                    SELECT * FROM agent_trajectory_steps
                    WHERE policy_selection_id=?
                    """,
                    (int(policy_selection_id),),
                ).fetchone()
                if existing:
                    return self._agent_trajectory_step_from_row(existing)
            next_index = int(c.execute(
                """
                SELECT COALESCE(MAX(step_index), -1) + 1
                FROM agent_trajectory_steps WHERE trajectory_id=?
                """,
                (int(trajectory["id"]),),
            ).fetchone()[0])
            cursor = c.execute(
                """
                INSERT INTO agent_trajectory_steps
                    (trajectory_id, step_index, state, action_type, action_name,
                     action_payload, observation, reward_components, step_reward,
                     policy_selection_id, behavior_propensity, safety_violation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(trajectory["id"]), next_index,
                    json.dumps(state or {}, ensure_ascii=False),
                    str(action_type or "workflow"), str(action_name or ""),
                    json.dumps(action_payload or {}, ensure_ascii=False),
                    json.dumps(observation or {}, ensure_ascii=False),
                    json.dumps(reward_components or {}, ensure_ascii=False),
                    float(step_reward) if step_reward is not None else None,
                    int(policy_selection_id) if policy_selection_id else None,
                    max(
                        0.0,
                        min(
                            float(
                                1.0
                                if behavior_propensity is None
                                else behavior_propensity
                            ),
                            1.0,
                        ),
                    ),
                    1 if safety_violation else 0,
                ),
            )
            row = c.execute(
                "SELECT * FROM agent_trajectory_steps WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return self._agent_trajectory_step_from_row(row)


    def complete_agent_trajectory_selection(
        self, selection_id, reward, reward_components=None, observation=None,
    ):
        with self._conn() as c:
            row = c.execute(
                """
                SELECT * FROM agent_trajectory_steps
                WHERE policy_selection_id=?
                """,
                (int(selection_id),),
            ).fetchone()
            if not row:
                return None
            c.execute(
                """
                UPDATE agent_trajectory_steps
                SET step_reward=?, reward_components=?, observation=?,
                    completed_at=datetime('now')
                WHERE id=?
                """,
                (
                    float(reward),
                    json.dumps(reward_components or {}, ensure_ascii=False),
                    json.dumps(observation or {}, ensure_ascii=False),
                    int(row["id"]),
                ),
            )
            updated = c.execute(
                "SELECT * FROM agent_trajectory_steps WHERE id=?",
                (int(row["id"]),),
            ).fetchone()
            return self._agent_trajectory_step_from_row(updated)


    def complete_agent_trajectory(
        self, task_id, outcome, reward_components, total_reward, gamma=0.95,
    ):
        gamma = max(0.0, min(float(gamma), 1.0))
        with self._conn() as c:
            trajectory = c.execute(
                "SELECT * FROM agent_trajectories WHERE task_id=?",
                (int(task_id),),
            ).fetchone()
            if not trajectory:
                return None
            c.execute(
                """
                UPDATE agent_trajectories
                SET status='completed', outcome=?, reward_components=?,
                    total_reward=?, completed_at=datetime('now')
                WHERE id=?
                """,
                (
                    json.dumps(outcome or {}, ensure_ascii=False),
                    json.dumps(reward_components or {}, ensure_ascii=False),
                    float(total_reward), int(trajectory["id"]),
                ),
            )
            steps = c.execute(
                """
                SELECT * FROM agent_trajectory_steps
                WHERE trajectory_id=? ORDER BY step_index DESC
                """,
                (int(trajectory["id"]),),
            ).fetchall()
            running_return = 0.0
            for offset, step in enumerate(steps):
                local_reward = float(step["step_reward"] or 0)
                if offset == 0:
                    local_reward += float(total_reward)
                running_return = local_reward + gamma * running_return
                c.execute(
                    """
                    UPDATE agent_trajectory_steps
                    SET discounted_return=?,
                        completed_at=CASE WHEN completed_at='' THEN datetime('now') ELSE completed_at END
                    WHERE id=?
                    """,
                    (round(running_return, 8), int(step["id"])),
                )
            row = c.execute(
                "SELECT * FROM agent_trajectories WHERE id=?",
                (int(trajectory["id"]),),
            ).fetchone()
            return self._agent_trajectory_from_row(row)


    def get_agent_trajectory(self, trajectory_id=None, task_id=None):
        if trajectory_id is None and task_id is None:
            raise ValueError("trajectory_id or task_id is required")
        with self._conn() as c:
            if trajectory_id is not None:
                row = c.execute(
                    "SELECT * FROM agent_trajectories WHERE id=?",
                    (int(trajectory_id),),
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM agent_trajectories WHERE task_id=?",
                    (int(task_id),),
                ).fetchone()
            if not row:
                return None
            item = self._agent_trajectory_from_row(row)
            steps = c.execute(
                """
                SELECT * FROM agent_trajectory_steps
                WHERE trajectory_id=? ORDER BY step_index
                """,
                (int(row["id"]),),
            ).fetchall()
            item["steps"] = [
                self._agent_trajectory_step_from_row(step) for step in steps
            ]
            return item


    def list_agent_trajectories(self, status="", scenario="", limit=100):
        with self._conn() as c:
            clauses = []
            params = []
            if status:
                clauses.append("status=?")
                params.append(str(status))
            if scenario:
                clauses.append("scenario=?")
                params.append(str(scenario))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            params.append(max(1, min(int(limit or 100), 1000)))
            rows = c.execute(
                f"SELECT * FROM agent_trajectories{where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._agent_trajectory_from_row(row) for row in rows]


    def list_agent_learning_examples(self, group_name="", limit=5000):
        with self._conn() as c:
            params = []
            group_filter = ""
            if group_name:
                group_filter = " AND pg.name=?"
                params.append(str(group_name))
            params.append(max(1, min(int(limit or 5000), 50000)))
            rows = c.execute(
                f"""
                SELECT s.*, t.task_id, t.scenario, t.task_context,
                       t.user_context, t.environment_state, t.total_reward,
                       ps.context AS selection_context, pg.name AS group_name,
                       pr.reward AS observed_reward
                FROM agent_trajectory_steps s
                JOIN agent_trajectories t ON t.id=s.trajectory_id
                LEFT JOIN policy_selections ps ON ps.id=s.policy_selection_id
                LEFT JOIN policy_groups pg ON pg.id=ps.group_id
                LEFT JOIN policy_rewards pr ON pr.selection_id=ps.id
                WHERE t.status='completed'
                  AND s.action_name<>''
                  AND COALESCE(pr.reward, s.discounted_return) IS NOT NULL
                  {group_filter}
                ORDER BY s.id DESC LIMIT ?
                """,
                params,
            ).fetchall()
            examples = []
            for row in rows:
                item = self._agent_trajectory_step_from_row(row)
                for key in (
                    "task_context", "user_context", "environment_state",
                    "selection_context",
                ):
                    item[key] = self._json_loads(item.get(key), {})
                observed = item.get("observed_reward")
                if observed is None:
                    observed = item.get("discounted_return")
                item["observed_reward"] = float(observed or 0)
                item["total_reward"] = float(item.get("total_reward") or 0)
                examples.append(item)
            return examples


    def create_agent_preference_pair(
        self, task_context, chosen, rejected, owner_id="default",
        chosen_trajectory_id=None, rejected_trajectory_id=None,
        source="explicit_user", confidence=1.0, metadata=None,
    ):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO agent_preference_pairs
                    (owner_id, task_context, chosen, rejected,
                     chosen_trajectory_id, rejected_trajectory_id,
                     source, confidence, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(owner_id or "default"),
                    json.dumps(task_context or {}, ensure_ascii=False),
                    json.dumps(chosen or {}, ensure_ascii=False),
                    json.dumps(rejected or {}, ensure_ascii=False),
                    int(chosen_trajectory_id) if chosen_trajectory_id else None,
                    int(rejected_trajectory_id) if rejected_trajectory_id else None,
                    str(source or "explicit_user"),
                    max(0.0, min(float(confidence or 0), 1.0)),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            row = c.execute(
                "SELECT * FROM agent_preference_pairs WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return self._agent_preference_from_row(row)


    def list_agent_preference_pairs(self, owner_id="", limit=500):
        with self._conn() as c:
            if owner_id:
                rows = c.execute(
                    """
                    SELECT * FROM agent_preference_pairs
                    WHERE owner_id=? ORDER BY id DESC LIMIT ?
                    """,
                    (str(owner_id), max(1, min(int(limit or 500), 5000))),
                ).fetchall()
            else:
                rows = c.execute(
                    """
                    SELECT * FROM agent_preference_pairs
                    ORDER BY id DESC LIMIT ?
                    """,
                    (max(1, min(int(limit or 500), 5000)),),
                ).fetchall()
            return [self._agent_preference_from_row(row) for row in rows]


    def create_agent_feedback(
        self, task_id, signal_type, score=None, owner_id="default",
        reason_category="", correction=None, metadata=None, explicit=True,
        idempotency_key="",
    ):
        with self._conn() as c:
            task = c.execute(
                "SELECT * FROM tasks WHERE id=?", (int(task_id),)
            ).fetchone()
            if not task:
                raise ValueError("task not found")
            if str(task["status"]) not in {
                "succeeded", "failed", "canceled", "cancelled", "interrupted"
            }:
                raise ValueError("feedback requires a terminal task")
            key = str(idempotency_key or "")
            if key:
                existing = c.execute(
                    "SELECT * FROM agent_feedback WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                if existing:
                    return self._agent_feedback_from_row(existing)
            trajectory = c.execute(
                "SELECT id FROM agent_trajectories WHERE task_id=?",
                (int(task_id),),
            ).fetchone()
            cursor = c.execute(
                """
                INSERT INTO agent_feedback
                    (task_id, trajectory_id, owner_id, signal_type, score,
                     reason_category, correction, metadata, explicit,
                     idempotency_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(task_id),
                    int(trajectory["id"]) if trajectory else None,
                    str(owner_id or "default"), str(signal_type),
                    float(score) if score is not None else None,
                    str(reason_category or ""),
                    json.dumps(correction or {}, ensure_ascii=False),
                    json.dumps(metadata or {}, ensure_ascii=False),
                    1 if explicit else 0, key,
                ),
            )
            row = c.execute(
                "SELECT * FROM agent_feedback WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return self._agent_feedback_from_row(row)


    def list_agent_feedback(
        self, task_id=None, owner_id="", explicit_only=False, limit=1000,
    ):
        with self._conn() as c:
            clauses = []
            params = []
            if task_id is not None:
                clauses.append("task_id=?")
                params.append(int(task_id))
            if owner_id:
                clauses.append("owner_id=?")
                params.append(str(owner_id))
            if explicit_only:
                clauses.append("explicit=1")
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            params.append(max(1, min(int(limit or 1000), 10000)))
            rows = c.execute(
                f"SELECT * FROM agent_feedback{where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._agent_feedback_from_row(row) for row in rows]


    def revise_policy_rewards_for_task(self, task_id, satisfaction, feedback_id):
        satisfaction = max(0.0, min(float(satisfaction), 1.0))
        revised = []
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT pr.*, ps.arm_id
                FROM policy_rewards pr
                JOIN policy_selections ps ON ps.id=pr.selection_id
                WHERE ps.task_id=?
                """,
                (int(task_id),),
            ).fetchall()
            for row in rows:
                old_reward = float(row["reward"])
                new_reward = round(
                    0.4 * float(row["success"])
                    + 0.3 * satisfaction
                    - 0.2 * float(row["latency_cost"])
                    - 0.1 * float(row["resource_cost"]),
                    6,
                )
                evidence = self._json_loads(row["evidence"], {})
                evidence["explicit_feedback"] = {
                    "feedback_id": int(feedback_id),
                    "satisfaction": satisfaction,
                    "source": "agent_feedback",
                }
                c.execute(
                    """
                    UPDATE policy_rewards
                    SET satisfaction=?, reward=?, evidence=?
                    WHERE id=?
                    """,
                    (
                        satisfaction, new_reward,
                        json.dumps(evidence, ensure_ascii=False),
                        int(row["id"]),
                    ),
                )
                c.execute(
                    """
                    UPDATE policy_arms
                    SET reward_sum=reward_sum-?+?,
                        reward_sq_sum=reward_sq_sum-(?*?)+(?*?),
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (
                        old_reward, new_reward,
                        old_reward, old_reward, new_reward, new_reward,
                        int(row["arm_id"]),
                    ),
                )
                c.execute(
                    """
                    UPDATE agent_trajectory_steps
                    SET step_reward=?,
                        reward_components=json_set(
                            COALESCE(reward_components, '{}'),
                            '$.satisfaction', ?,
                            '$.feedback_id', ?
                        ),
                        completed_at=datetime('now')
                    WHERE policy_selection_id=?
                    """,
                    (
                        new_reward, satisfaction, int(feedback_id),
                        int(row["selection_id"]),
                    ),
                )
                revised.append({
                    "selection_id": int(row["selection_id"]),
                    "old_reward": old_reward,
                    "new_reward": new_reward,
                })
        return revised


    def agent_learning_data_quality(self):
        with self._conn() as c:
            trajectory_count = int(c.execute(
                "SELECT COUNT(*) FROM agent_trajectories WHERE status='completed'"
            ).fetchone()[0])
            step_count = int(c.execute(
                """
                SELECT COUNT(*) FROM agent_trajectory_steps s
                JOIN agent_trajectories t ON t.id=s.trajectory_id
                WHERE t.status='completed'
                """
            ).fetchone()[0])
            preference_count = int(c.execute(
                "SELECT COUNT(*) FROM agent_preference_pairs"
            ).fetchone()[0])
            explicit_feedback_count = int(c.execute(
                """
                SELECT COUNT(*) FROM agent_feedback
                WHERE explicit=1 AND score IS NOT NULL
                """
            ).fetchone()[0])
            feedback_task_count = int(c.execute(
                """
                SELECT COUNT(DISTINCT task_id) FROM agent_feedback
                WHERE explicit=1 AND score IS NOT NULL
                """
            ).fetchone()[0])
            valid_propensity_count = int(c.execute(
                """
                SELECT COUNT(*) FROM agent_trajectory_steps
                WHERE behavior_propensity>0 AND behavior_propensity<=1
                  AND json_extract(
                      action_payload, '$._policy_trace.complete'
                  ) = 1
                """
            ).fetchone()[0])
            feedback_rows = c.execute(
                """
                SELECT owner_id, metadata FROM agent_feedback
                WHERE explicit=1 AND score IS NOT NULL
                """
            ).fetchall()
            origin_counts = {
                "human_user": 0,
                "codex_evaluator": 0,
                "automated_test": 0,
            }
            human_owners = set()
            evaluator_owners = set()
            grounded_feedback_count = 0
            for row in feedback_rows:
                metadata = self._json_loads(row["metadata"], {})
                origin = str(
                    metadata.get("evaluator_origin") or "human_user"
                )
                if origin not in origin_counts:
                    origin = "automated_test"
                origin_counts[origin] += 1
                if origin == "human_user":
                    human_owners.add(str(row["owner_id"] or "default"))
                    grounded_feedback_count += 1
                elif (
                    origin == "codex_evaluator"
                    and metadata.get("evidence_digest")
                    and metadata.get("evaluation_method")
                ):
                    evaluator_owners.add(
                        str(row["owner_id"] or "codex-evaluator")
                    )
                    grounded_feedback_count += 1
            scenarios = {
                str(row["scenario"]): int(row["count"])
                for row in c.execute(
                    """
                    SELECT scenario, COUNT(*) AS count
                    FROM agent_trajectories WHERE status='completed'
                    GROUP BY scenario ORDER BY scenario
                    """
                ).fetchall()
            }
            arm_exposures = {
                str(row["action_name"]): int(row["count"])
                for row in c.execute(
                    """
                    SELECT action_name, COUNT(*) AS count
                    FROM agent_trajectory_steps s
                    JOIN agent_trajectories t ON t.id=s.trajectory_id
                    WHERE t.status='completed' AND action_name<>''
                    GROUP BY action_name ORDER BY action_name
                    """
                ).fetchall()
            }
            conflicting_tasks = int(c.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT task_id
                    FROM agent_feedback
                    WHERE explicit=1 AND score IS NOT NULL
                    GROUP BY task_id
                    HAVING COUNT(*)>1 AND MAX(score)-MIN(score)>=0.5
                )
                """
            ).fetchone()[0])
            return {
                "trajectory_count": trajectory_count,
                "decision_step_count": step_count,
                "preference_pair_count": preference_count,
                "explicit_feedback_count": explicit_feedback_count,
                "grounded_feedback_count": grounded_feedback_count,
                "feedback_origin_counts": origin_counts,
                "independent_human_owner_count": len(human_owners),
                "evaluator_owner_count": len(evaluator_owners),
                "feedback_task_count": feedback_task_count,
                "feedback_coverage": round(
                    feedback_task_count / trajectory_count, 6
                ) if trajectory_count else 0.0,
                "missing_feedback_count": max(
                    0, trajectory_count - feedback_task_count
                ),
                "valid_propensity_count": valid_propensity_count,
                "valid_propensity_rate": round(
                    valid_propensity_count / step_count, 6
                ) if step_count else 0.0,
                "conflicting_feedback_task_count": conflicting_tasks,
                "scenario_counts": scenarios,
                "arm_exposures": arm_exposures,
            }


    def create_reward_calibration(
        self, weights, training_metrics, thresholds, data_digest,
        trained_by="system",
    ):
        with self._conn() as c:
            version = int(c.execute(
                "SELECT COALESCE(MAX(version), 0)+1 FROM reward_calibrations"
            ).fetchone()[0])
            cursor = c.execute(
                """
                INSERT INTO reward_calibrations
                    (version, weights, training_metrics, thresholds,
                     data_digest, trained_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    version, json.dumps(weights or {}, ensure_ascii=False),
                    json.dumps(training_metrics or {}, ensure_ascii=False),
                    json.dumps(thresholds or {}, ensure_ascii=False),
                    str(data_digest or ""), str(trained_by or "system"),
                ),
            )
            return self.get_reward_calibration(int(cursor.lastrowid), conn=c)


    def get_reward_calibration(self, calibration_id=None, status="", conn=None):
        def fetch(c):
            if calibration_id is not None:
                row = c.execute(
                    "SELECT * FROM reward_calibrations WHERE id=?",
                    (int(calibration_id),),
                ).fetchone()
            else:
                row = c.execute(
                    """
                    SELECT * FROM reward_calibrations WHERE status=?
                    ORDER BY version DESC LIMIT 1
                    """,
                    (str(status or "active"),),
                ).fetchone()
            return self._reward_calibration_from_row(row) if row else None
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def list_reward_calibrations(self, limit=100):
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM reward_calibrations
                ORDER BY version DESC LIMIT ?
                """,
                (max(1, min(int(limit or 100), 1000)),),
            ).fetchall()
            return [self._reward_calibration_from_row(row) for row in rows]


    def evaluate_reward_calibration(self, calibration_id, metrics, passed):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM reward_calibrations WHERE id=?",
                (int(calibration_id),),
            ).fetchone()
            if not row or row["status"] != "candidate":
                raise ValueError("reward calibration candidate not found")
            c.execute(
                """
                UPDATE reward_calibrations
                SET status=?, evaluation_metrics=?, evaluated_at=datetime('now')
                WHERE id=?
                """,
                (
                    "shadow" if passed else "rejected",
                    json.dumps(metrics or {}, ensure_ascii=False),
                    int(calibration_id),
                ),
            )
            return self.get_reward_calibration(calibration_id, conn=c)


    def activate_reward_calibration(self, calibration_id):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM reward_calibrations WHERE id=?",
                (int(calibration_id),),
            ).fetchone()
            if not row or row["status"] != "shadow":
                raise ValueError("only a shadow reward calibration can be activated")
            c.execute(
                "UPDATE reward_calibrations SET status='retired' WHERE status='active'"
            )
            c.execute(
                """
                UPDATE reward_calibrations
                SET status='active', activated_at=datetime('now') WHERE id=?
                """,
                (int(calibration_id),),
            )
            return self.get_reward_calibration(calibration_id, conn=c)


    def create_preference_ranker_model(
        self, feature_dim, weights, training_metrics, data_digest,
        trained_by="system",
    ):
        with self._conn() as c:
            version = int(c.execute(
                "SELECT COALESCE(MAX(version), 0)+1 FROM preference_ranker_models"
            ).fetchone()[0])
            cursor = c.execute(
                """
                INSERT INTO preference_ranker_models
                    (version, feature_dim, weights, training_metrics,
                     data_digest, trained_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    version, int(feature_dim),
                    json.dumps(weights or [], ensure_ascii=False),
                    json.dumps(training_metrics or {}, ensure_ascii=False),
                    str(data_digest or ""), str(trained_by or "system"),
                ),
            )
            return self.get_preference_ranker_model(
                int(cursor.lastrowid), conn=c
            )


    def get_preference_ranker_model(self, model_id=None, status="", conn=None):
        def fetch(c):
            if model_id is not None:
                row = c.execute(
                    "SELECT * FROM preference_ranker_models WHERE id=?",
                    (int(model_id),),
                ).fetchone()
            else:
                row = c.execute(
                    """
                    SELECT * FROM preference_ranker_models WHERE status=?
                    ORDER BY version DESC LIMIT 1
                    """,
                    (str(status or "active"),),
                ).fetchone()
            return self._preference_ranker_from_row(row) if row else None
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def list_preference_ranker_models(self, limit=100):
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM preference_ranker_models
                ORDER BY version DESC LIMIT ?
                """,
                (max(1, min(int(limit or 100), 1000)),),
            ).fetchall()
            return [self._preference_ranker_from_row(row) for row in rows]


    def evaluate_preference_ranker_model(self, model_id, metrics, passed):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM preference_ranker_models WHERE id=?",
                (int(model_id),),
            ).fetchone()
            if not row or row["status"] != "candidate":
                raise ValueError("preference ranker candidate not found")
            c.execute(
                """
                UPDATE preference_ranker_models
                SET status=?, evaluation_metrics=?, evaluated_at=datetime('now')
                WHERE id=?
                """,
                (
                    "shadow" if passed else "rejected",
                    json.dumps(metrics or {}, ensure_ascii=False),
                    int(model_id),
                ),
            )
            return self.get_preference_ranker_model(model_id, conn=c)


    def activate_preference_ranker_model(self, model_id):
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM preference_ranker_models WHERE id=?",
                (int(model_id),),
            ).fetchone()
            if not row or row["status"] != "shadow":
                raise ValueError("only a shadow preference ranker can be activated")
            c.execute(
                """
                UPDATE preference_ranker_models
                SET status='retired' WHERE status='active'
                """
            )
            c.execute(
                """
                UPDATE preference_ranker_models
                SET status='active', activated_at=datetime('now') WHERE id=?
                """,
                (int(model_id),),
            )
            return self.get_preference_ranker_model(model_id, conn=c)


    def create_agent_policy_model(
        self, group_name, feature_dim, weights, training_metrics,
        data_digest, trained_by="system",
    ):
        with self._conn() as c:
            version = int(c.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM agent_policy_models WHERE group_name=?
                """,
                (str(group_name),),
            ).fetchone()[0])
            cursor = c.execute(
                """
                INSERT INTO agent_policy_models
                    (group_name, version, feature_dim, weights,
                     training_metrics, data_digest, trained_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(group_name), version, int(feature_dim),
                    json.dumps(weights or {}, ensure_ascii=False),
                    json.dumps(training_metrics or {}, ensure_ascii=False),
                    str(data_digest or ""), str(trained_by or "system"),
                ),
            )
            return self.get_agent_policy_model(int(cursor.lastrowid), conn=c)


    def get_agent_policy_model(
        self, model_id=None, group_name="", status="", conn=None,
    ):
        def fetch(c):
            if model_id is not None:
                row = c.execute(
                    "SELECT * FROM agent_policy_models WHERE id=?",
                    (int(model_id),),
                ).fetchone()
            else:
                row = c.execute(
                    """
                    SELECT * FROM agent_policy_models
                    WHERE group_name=? AND status=?
                    ORDER BY version DESC LIMIT 1
                    """,
                    (str(group_name), str(status or "active")),
                ).fetchone()
            return self._agent_policy_model_from_row(row) if row else None
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def list_agent_policy_models(self, group_name="", limit=100):
        with self._conn() as c:
            if group_name:
                rows = c.execute(
                    """
                    SELECT * FROM agent_policy_models
                    WHERE group_name=? ORDER BY version DESC LIMIT ?
                    """,
                    (str(group_name), max(1, min(int(limit or 100), 1000))),
                ).fetchall()
            else:
                rows = c.execute(
                    """
                    SELECT * FROM agent_policy_models
                    ORDER BY id DESC LIMIT ?
                    """,
                    (max(1, min(int(limit or 100), 1000)),),
                ).fetchall()
            return [self._agent_policy_model_from_row(row) for row in rows]


    def evaluate_agent_policy_model(self, model_id, metrics, passed):
        with self._conn() as c:
            model = c.execute(
                "SELECT * FROM agent_policy_models WHERE id=?",
                (int(model_id),),
            ).fetchone()
            if not model:
                raise ValueError("agent policy model not found")
            if model["status"] not in {"candidate", "shadow"}:
                raise ValueError("only candidate or shadow models can be evaluated")
            c.execute(
                """
                UPDATE agent_policy_models
                SET status=?, evaluation_metrics=?, evaluated_at=datetime('now')
                WHERE id=?
                """,
                (
                    "shadow" if passed else "rejected",
                    json.dumps(metrics or {}, ensure_ascii=False),
                    int(model_id),
                ),
            )
            return self.get_agent_policy_model(model_id, conn=c)


    @atomic_workflow
    def activate_agent_policy_model(self, model_id):
        with self._conn() as c:
            model = c.execute(
                "SELECT * FROM agent_policy_models WHERE id=?",
                (int(model_id),),
            ).fetchone()
            if not model:
                raise ValueError("agent policy model not found")
            if model["status"] != "shadow":
                raise ValueError("only a shadow-evaluated model can be activated")
            metrics = self._json_loads(model['evaluation_metrics'], {})
            if not metrics.get('passed') or metrics.get('schema') != 'clawos.router-promotion.v2':
                raise ValueError('common robust gate is required; legacy evaluations must be repeated')
            weights = self._json_loads(model['weights'], {})
            current = c.execute("SELECT id FROM agent_policy_models WHERE group_name=? AND status='active'",
                                (model['group_name'],)).fetchone()
            if weights.get('baseline_active_model_id', -1) != (current['id'] if current else 0):
                raise ValueError('active router changed; retrain before publication')
            c.execute(
                """
                UPDATE agent_policy_models SET status='retired'
                WHERE group_name=? AND status='active'
                """,
                (model["group_name"],),
            )
            c.execute(
                """
                UPDATE agent_policy_models
                SET status='active', activated_at=datetime('now')
                WHERE id=?
                """,
                (int(model_id),),
            )
            return self.get_agent_policy_model(model_id, conn=c)


    @atomic_workflow
    def rollback_agent_policy_model(self, model_id):
        with self._conn() as c:
            model = c.execute(
                "SELECT * FROM agent_policy_models WHERE id=?",
                (int(model_id),),
            ).fetchone()
            if not model:
                raise ValueError("agent policy model not found")
            if model["status"] != "active":
                raise ValueError("only the active model can be rolled back")
            previous = c.execute(
                """
                SELECT * FROM agent_policy_models
                WHERE group_name=? AND status='retired' AND id<>?
                ORDER BY version DESC LIMIT 1
                """,
                (model["group_name"], int(model_id)),
            ).fetchone()
            c.execute(
                """
                UPDATE agent_policy_models
                SET status='rolled_back' WHERE id=?
                """,
                (int(model_id),),
            )
            restored = None
            if previous:
                c.execute(
                    """
                    UPDATE agent_policy_models
                    SET status='active', activated_at=datetime('now')
                    WHERE id=?
                    """,
                    (int(previous["id"]),),
                )
                restored = self.get_agent_policy_model(
                    int(previous["id"]), conn=c
                )
            return {
                "rolled_back": self.get_agent_policy_model(model_id, conn=c),
                "restored": restored,
            }


    def _agent_trajectory_from_row(self, row):
        item = dict(row)
        for key in (
            "task_context", "user_context", "environment_state",
            "outcome", "reward_components",
        ):
            item[key] = self._json_loads(item.get(key), {})
        if item.get("total_reward") is not None:
            item["total_reward"] = float(item["total_reward"])
        return item


    def _agent_trajectory_step_from_row(self, row):
        item = dict(row)
        for key in (
            "state", "action_payload", "observation", "reward_components",
        ):
            item[key] = self._json_loads(item.get(key), {})
        item["behavior_propensity"] = float(
            0.0
            if item.get("behavior_propensity") is None
            else item["behavior_propensity"]
        )
        item["safety_violation"] = bool(item.get("safety_violation"))
        for key in ("step_reward", "discounted_return"):
            if item.get(key) is not None:
                item[key] = float(item[key])
        return item


    def _agent_preference_from_row(self, row):
        item = dict(row)
        for key in ("task_context", "chosen", "rejected", "metadata"):
            item[key] = self._json_loads(item.get(key), {})
        item["confidence"] = float(item.get("confidence") or 0)
        return item


    def _agent_feedback_from_row(self, row):
        item = dict(row)
        item["correction"] = self._json_loads(item.get("correction"), {})
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        item["explicit"] = bool(item.get("explicit"))
        if item.get("score") is not None:
            item["score"] = float(item["score"])
        return item


    def _reward_calibration_from_row(self, row):
        item = dict(row)
        for key in (
            "weights", "training_metrics", "evaluation_metrics", "thresholds",
        ):
            item[key] = self._json_loads(item.get(key), {})
        item["version"] = int(item.get("version") or 1)
        return item


    def _preference_ranker_from_row(self, row):
        item = dict(row)
        item["weights"] = self._json_loads(item.get("weights"), [])
        item["training_metrics"] = self._json_loads(
            item.get("training_metrics"), {}
        )
        item["evaluation_metrics"] = self._json_loads(
            item.get("evaluation_metrics"), {}
        )
        item["version"] = int(item.get("version") or 1)
        item["feature_dim"] = int(item.get("feature_dim") or 128)
        return item


    def _agent_policy_model_from_row(self, row):
        item = dict(row)
        for key in ("weights", "training_metrics", "evaluation_metrics"):
            item[key] = self._json_loads(item.get(key), {})
        item["feature_dim"] = int(item.get("feature_dim") or 128)
        item["version"] = int(item.get("version") or 1)
        return item
