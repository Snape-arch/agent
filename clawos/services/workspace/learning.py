"""Learning workflows and their domain dependencies."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone


class LearningWorkspace:
    """Workspace learning responsibilities."""

    def __init__(self, store, security):
        self.store = store
        self.security = security

    def create_learning_goal(self, title, description="", target_date="", topics=None):
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO learning_goals (title, description, target_date)
                VALUES (?, ?, ?)
                """,
                (str(title), str(description or ""), str(target_date or "")),
            )
            goal_id = int(cursor.lastrowid)
            for topic in topics or []:
                c.execute(
                    """
                    INSERT INTO learning_items (goal_id, topic, next_review_at)
                    VALUES (?, ?, ?)
                    """,
                    (goal_id, str(topic), datetime.now(timezone.utc).isoformat()),
                )
            return self.get_learning_goal(goal_id, conn=c)


    def record_learning_review(self, item_id, score, evidence, notes=""):
        if not str(evidence or "").strip():
            raise ValueError("learning evidence is required")
        score = max(0.0, min(float(score), 1.0))
        with self.store._conn() as c:
            item = c.execute("SELECT * FROM learning_items WHERE id=?", (int(item_id),)).fetchone()
            if not item:
                raise ValueError("learning item not found")
            old_mastery = float(item["mastery"])
            mastery = round(old_mastery * 0.65 + score * 0.35, 4)
            interval = 1 if score < 0.6 else min(60, max(2, int(item["interval_days"]) * 2))
            next_review = datetime.now(timezone.utc) + timedelta(days=interval)
            c.execute(
                """
                INSERT INTO learning_reviews (item_id, score, evidence, notes)
                VALUES (?, ?, ?, ?)
                """,
                (int(item_id), score, str(evidence), str(notes or "")),
            )
            c.execute(
                """
                UPDATE learning_items
                SET mastery=?, interval_days=?, next_review_at=?,
                    evidence_count=evidence_count+1, updated_at=datetime('now')
                WHERE id=?
                """,
                (mastery, interval, next_review.isoformat(), int(item_id)),
            )
            return dict(c.execute("SELECT * FROM learning_items WHERE id=?", (int(item_id),)).fetchone())


    def get_learning_goal(self, goal_id, conn=None):
        def fetch(c):
            row = c.execute("SELECT * FROM learning_goals WHERE id=?", (int(goal_id),)).fetchone()
            if not row:
                return None
            goal = dict(row)
            items = c.execute(
                "SELECT * FROM learning_items WHERE goal_id=? ORDER BY id",
                (int(goal_id),),
            ).fetchall()
            goal["items"] = [dict(item) for item in items]
            edges = c.execute(
                "SELECT * FROM learning_edges WHERE goal_id=? ORDER BY id",
                (int(goal_id),),
            ).fetchall()
            goal["edges"] = [dict(edge) for edge in edges]
            return goal
        if conn is not None:
            return fetch(conn)
        with self.store._conn() as c:
            return fetch(c)


    def add_learning_dependency(self, goal_id, source_topic, target_topic, relation="depends_on", evidence=""):
        with self.store._conn() as c:
            if not c.execute("SELECT 1 FROM learning_goals WHERE id=?", (int(goal_id),)).fetchone():
                raise ValueError("learning goal not found")
            cursor = c.execute(
                """
                INSERT INTO learning_edges
                    (goal_id, source_topic, target_topic, relation, evidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(goal_id), str(source_topic), str(target_topic), str(relation or "depends_on"), str(evidence or "")),
            )
            return dict(c.execute("SELECT * FROM learning_edges WHERE id=?", (int(cursor.lastrowid),)).fetchone())


    def record_learning_mistake(self, item_id, prompt, wrong_answer, correct_answer, evidence):
        if not str(evidence or "").strip():
            raise ValueError("mistake evidence is required")
        with self.store._conn() as c:
            if not c.execute("SELECT 1 FROM learning_items WHERE id=?", (int(item_id),)).fetchone():
                raise ValueError("learning item not found")
            cursor = c.execute(
                """
                INSERT INTO learning_mistakes
                    (item_id, prompt, wrong_answer, correct_answer, evidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(item_id), str(prompt), str(wrong_answer or ""), str(correct_answer), str(evidence)),
            )
            return dict(c.execute("SELECT * FROM learning_mistakes WHERE id=?", (int(cursor.lastrowid),)).fetchone())


    def learning_graph(self, goal_id):
        goal = self.get_learning_goal(goal_id)
        if not goal:
            raise ValueError("learning goal not found")
        nodes = [
            {
                "id": item["topic"],
                "item_id": int(item["id"]),
                "mastery": float(item["mastery"]),
                "evidence_count": int(item["evidence_count"]),
                "next_review_at": item["next_review_at"],
            }
            for item in goal["items"]
        ]
        return {"goal": goal, "nodes": nodes, "edges": goal.get("edges", [])}


    def long_term_mastery(self, goal_id):
        with self.store._conn() as c:
            items = c.execute(
                "SELECT * FROM learning_items WHERE goal_id=?",
                (int(goal_id),),
            ).fetchall()
            if not items:
                return {"goal_id": int(goal_id), "mastery": 0, "items": [], "risk": "no_items"}
            now = datetime.now(timezone.utc).isoformat()
            mistake_counts = {
                int(row["item_id"]): int(row["count"])
                for row in c.execute(
                    """
                    SELECT item_id, COUNT(*) AS count
                    FROM learning_mistakes GROUP BY item_id
                    """
                ).fetchall()
            }
            rows = []
            for item in items:
                evidence_count = int(item["evidence_count"] or 0)
                mistakes = mistake_counts.get(int(item["id"]), 0)
                adjusted = max(0.0, float(item["mastery"]) - mistakes * 0.05)
                rows.append({
                    **dict(item),
                    "mistake_count": mistakes,
                    "adjusted_mastery": round(adjusted, 4),
                    "due": bool(item["next_review_at"] and item["next_review_at"] <= now),
                    "evidence_sufficient": evidence_count >= 2,
                })
            mastery = round(sum(row["adjusted_mastery"] for row in rows) / len(rows), 4)
            return {
                "goal_id": int(goal_id),
                "mastery": mastery,
                "due_count": sum(1 for row in rows if row["due"]),
                "items": rows,
            }
