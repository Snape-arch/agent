"""Curriculum-backed studio; reading state never writes mastery evidence."""
from __future__ import annotations

import json
from services.academy_curriculum import COURSE_KEY, LESSONS, PAPERS, PROJECTS, RESOURCES, TRACKS, track_nodes


class AcademyStudioService:
    def __init__(self, learning):
        self.learning = learning
        self.store = learning.store
        with self.store._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS academy_studio_records (
                learner_id TEXT NOT NULL, record_key TEXT NOT NULL, payload TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')), PRIMARY KEY(learner_id, record_key))""")
            conn.execute("""INSERT OR IGNORE INTO learning_courses
                (course_key,title,description,status,published_at) VALUES (?,? ,?,'published',datetime('now'))""",
                (COURSE_KEY, "AI 学习工作室", "从基础、原理到可检验的 AI 应用与论文复现"))
            self.course_id = conn.execute("SELECT id FROM learning_courses WHERE course_key=?", (COURSE_KEY,)).fetchone()["id"]
            for index, row in enumerate(LESSONS):
                source = next(r["url"] for r in RESOURCES if r["id"] == row["resource"])
                conn.execute("""INSERT OR IGNORE INTO learning_course_topics
                    (course_id,topic_key,title,prerequisite_keys,source_ref,position) VALUES (?,?,?,?,?,?)""",
                    (self.course_id, row["id"], row["title"], json.dumps(row["prerequisites"]), source, index))
                prompts = [
                    f"围绕「{row['title']}」，解释：{row['why']} 请用一个具体例子说明方法与失效条件。",
                    f"实践复盘「{row['title']}」：{row['exercise']} 请说明检查步骤、预期结果，以及一种失败原因。",
                ]
                for prompt in prompts:
                    conn.execute("""INSERT OR IGNORE INTO learning_questions
                        (course_id,topic_key,prompt,expected_concepts,cognitive_level,source_ref)
                        VALUES (?,?,?,?,'apply',?)""", (self.course_id, row["id"], prompt, json.dumps(row["concepts"], ensure_ascii=False), source))

    def state(self, learner_id="local-user"):
        with self.store._conn() as conn:
            records = {row["record_key"]: json.loads(row["payload"]) for row in conn.execute(
                "SELECT record_key,payload FROM academy_studio_records WHERE learner_id=?", (learner_id,))}
            has_materials = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='academy_materials'").fetchone()
            materials = [dict(row) for row in conn.execute('''SELECT id,title,status FROM academy_materials
                WHERE learner=? ORDER BY created_at DESC,id DESC LIMIT 4''', (learner_id,))] if has_materials else []
        dashboard = self.learning.dashboard(learner_id=learner_id)
        active = dashboard["course"]["id"] == self.course_id
        return dict(schema="clawos.academy-studio.v1", course_id=self.course_id,
                    lessons=LESSONS, papers=PAPERS, resources=RESOURCES, projects=PROJECTS,
                    tracks=[dict(t, nodes=track_nodes(t)) for t in TRACKS], records=records, materials=materials,
                    active=active, dashboard=dashboard if active else None,
                    active_course=dashboard["course"]["title"], checked_at="2026-09-10")

    def save(self, key, payload, learner_id="local-user"):
        if not isinstance(payload, dict):
            raise ValueError("record must be an object")
        kind, _, item_id = str(key).partition(":")
        if kind == "plan" and not item_id:
            if payload.get("track") not in {t["id"] for t in TRACKS} or type(payload.get("minutes")) is not int or payload["minutes"] not in (20, 40, 60):
                raise ValueError("choose a valid track and daily study budget")
            clean = dict(track=payload["track"], minutes=payload["minutes"])
        elif kind == "lesson" and item_id in {r["id"] for r in LESSONS}:
            if type(payload.get("read")) is not bool or not isinstance(payload.get("note", ""), str):
                raise ValueError("invalid lesson record")
            clean = dict(read=payload["read"], note=payload.get("note", "")[:12000])
        elif kind == "paper" and item_id in {r["id"] for r in PAPERS}:
            fields = ("problem", "method", "evidence", "limits", "experiment")
            if any(not isinstance(payload.get(f, ""), str) for f in fields):
                raise ValueError("paper notes must be text")
            clean = {f: payload.get(f, "")[:6000] for f in fields}
        elif kind == "project" and item_id in {r["id"] for r in PROJECTS}:
            steps = payload.get("steps")
            count = len(next(r["steps"] for r in PROJECTS if r["id"] == item_id))
            if not isinstance(steps, list) or len(steps) != count or any(type(s) is not bool for s in steps) or not isinstance(payload.get("note", ""), str):
                raise ValueError("invalid project checklist")
            clean = dict(steps=steps, note=payload.get("note", "")[:12000])
        else:
            raise ValueError("unknown studio record")
        with self.store._conn() as conn:
            conn.execute("""INSERT INTO academy_studio_records(learner_id,record_key,payload) VALUES (?,?,?)
                ON CONFLICT(learner_id,record_key) DO UPDATE SET payload=excluded.payload,updated_at=datetime('now')""",
                (learner_id, key, json.dumps(clean, ensure_ascii=False)))
        return dict(saved=True, key=key, record=clean)

    def start(self, track, minutes=40, learner_id="local-user"):
        self.save("plan", dict(track=track, minutes=minutes), learner_id)
        self.learning.enroll(self.course_id, learner_id=learner_id)
        return self.state(learner_id)
