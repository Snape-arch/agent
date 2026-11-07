from __future__ import annotations

import json

from memoryos.persistence import Repository


class PoliciesRepository(Repository):
    """Persistence operations for policies."""

    def upsert_policy_group(self, name, optimizer_type="contextual_ucb", exploration_rate=0.1):
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO policy_groups (name, optimizer_type, exploration_rate, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    optimizer_type=excluded.optimizer_type,
                    exploration_rate=excluded.exploration_rate,
                    updated_at=datetime('now')
                """,
                (str(name), str(optimizer_type), float(exploration_rate)),
            )
            return dict(c.execute("SELECT * FROM policy_groups WHERE name=?", (str(name),)).fetchone())


    def upsert_policy_arm(self, group_name, name, arm_type, payload=None, contexts=None, status="active"):
        group = self.upsert_policy_group(group_name)
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO policy_arms
                    (group_id, name, arm_type, payload, contexts, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(group_id, name) DO UPDATE SET
                    arm_type=excluded.arm_type,
                    payload=excluded.payload,
                    contexts=excluded.contexts,
                    status=excluded.status,
                    updated_at=datetime('now')
                """,
                (
                    int(group["id"]), str(name), str(arm_type),
                    json.dumps(payload or {}, ensure_ascii=False),
                    json.dumps(contexts or [], ensure_ascii=False),
                    str(status),
                ),
            )
            row = c.execute(
                "SELECT * FROM policy_arms WHERE group_id=? AND name=?",
                (int(group["id"]), str(name)),
            ).fetchone()
            return self._policy_arm_from_row(row)


    def list_policy_arms(self, group_name, include_inactive=False):
        with self._conn() as c:
            group = c.execute("SELECT * FROM policy_groups WHERE name=?", (str(group_name),)).fetchone()
            if not group:
                return [], None
            sql = "SELECT * FROM policy_arms WHERE group_id=?"
            params = [int(group["id"])]
            if not include_inactive:
                sql += " AND status='active'"
            sql += " ORDER BY id"
            rows = c.execute(sql, params).fetchall()
            return [self._policy_arm_from_row(row) for row in rows], dict(group)


    def create_policy_selection(
        self, group_id, arm_id, context, score, exploration=False,
        task_id=None, session_id="",
    ):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO policy_selections
                    (group_id, arm_id, context, score, exploration, task_id, session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(group_id), int(arm_id),
                    json.dumps(context or {}, ensure_ascii=False),
                    float(score), 1 if exploration else 0,
                    int(task_id) if task_id else None, str(session_id or ""),
                ),
            )
            return self.get_policy_selection(int(cursor.lastrowid), conn=c)


    def get_policy_selection(self, selection_id, conn=None):
        def fetch(c):
            row = c.execute(
                """
                SELECT s.*, g.name AS group_name, a.name AS arm_name,
                       a.arm_type, a.payload, a.contexts
                FROM policy_selections s
                JOIN policy_groups g ON g.id=s.group_id
                JOIN policy_arms a ON a.id=s.arm_id
                WHERE s.id=?
                """,
                (int(selection_id),),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            for key, default in (("context", {}), ("payload", {}), ("contexts", [])):
                item[key] = self._json_loads(item.get(key), default)
            item["exploration"] = bool(item.get("exploration"))
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def record_policy_reward(
        self, selection_id, success, satisfaction, latency_cost,
        resource_cost, reward, evidence=None,
    ):
        with self._conn() as c:
            selection = c.execute(
                "SELECT * FROM policy_selections WHERE id=?", (int(selection_id),)
            ).fetchone()
            if not selection:
                raise ValueError("policy selection not found")
            if c.execute(
                "SELECT 1 FROM policy_rewards WHERE selection_id=?", (int(selection_id),)
            ).fetchone():
                raise ValueError("reward already recorded")
            c.execute(
                """
                INSERT INTO policy_rewards
                    (selection_id, success, satisfaction, latency_cost,
                     resource_cost, reward, evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(selection_id), float(success), float(satisfaction),
                    float(latency_cost), float(resource_cost), float(reward),
                    json.dumps(evidence or {}, ensure_ascii=False),
                ),
            )
            c.execute(
                """
                UPDATE policy_arms
                SET pull_count=pull_count+1,
                    reward_sum=reward_sum+?,
                    reward_sq_sum=reward_sq_sum+(? * ?),
                    success_count=success_count+?,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    float(reward), float(reward), float(reward),
                    1 if float(success) >= 0.5 else 0, int(selection["arm_id"]),
                ),
            )
            c.execute(
                "UPDATE policy_selections SET status='rewarded' WHERE id=?",
                (int(selection_id),),
            )
            return self.get_policy_selection(selection_id, conn=c)


    def policy_group_stats(self, group_name):
        arms, group = self.list_policy_arms(group_name, include_inactive=True)
        if not group:
            return None
        for arm in arms:
            pulls = int(arm["pull_count"])
            average = float(arm["reward_sum"]) / pulls if pulls else 0.0
            variance = max(
                0.0,
                (float(arm["reward_sq_sum"]) / pulls) - (average * average),
            ) if pulls else 0.0
            standard_error = (variance / pulls) ** 0.5 if pulls else 0.0
            arm["average_reward"] = round(average, 4)
            arm["success_rate"] = round(int(arm["success_count"]) / pulls, 4) if pulls else 0.0
            arm["standard_error"] = round(standard_error, 6)
            arm["confidence_lower_95"] = round(average - 1.96 * standard_error, 6)
            arm["confidence_upper_95"] = round(average + 1.96 * standard_error, 6)
        return {"group": group, "arms": arms}


    def promote_policy_arm(
        self, group_id, arm_id, target_type, target_key, actor_id="system",
    ):
        raise ValueError("direct arm publication is retired; nominate through SelfEvolutionManager and complete the shared release gates")


    def rollback_policy_promotion(self, promotion_id, actor_id="system"):
        raise ValueError("legacy arm promotions have no bound publication version; review the current policy before manual restoration")


    def get_policy_promotion(self, promotion_id, conn=None):
        def fetch(c):
            row = c.execute(
                """
                SELECT p.*, g.name AS group_name, a.name AS arm_name
                FROM policy_promotions p
                JOIN policy_groups g ON g.id=p.group_id
                JOIN policy_arms a ON a.id=p.arm_id
                WHERE p.id=?
                """,
                (int(promotion_id),),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["previous_payload"] = self._json_loads(item.get("previous_payload"), {})
            item["promoted_payload"] = self._json_loads(item.get("promoted_payload"), {})
            item["previous_existed"] = bool(item.get("previous_existed"))
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)


    def _policy_arm_from_row(self, row):
        item = dict(row)
        item["payload"] = self._json_loads(item.get("payload"), {})
        item["contexts"] = self._json_loads(item.get("contexts"), [])
        return item
