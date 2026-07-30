"""Evidence-native learning product built on the shared MemoryOS database."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any


class LearningProductService:
    """Unify course, assessment, mastery, mistake, and review truth."""

    ALGORITHM_VERSION = "bkt-fsrs-lite.v1"
    DEFAULT_LEARNER = "local-user"

    def __init__(self, store: Any):
        self.store = store
        self._init_db()
        self._seed_builtin_course()

    def _init_db(self) -> None:
        with self.store._conn() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS learning_goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    target_date TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS learning_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    mastery REAL NOT NULL DEFAULT 0,
                    interval_days INTEGER NOT NULL DEFAULT 1,
                    next_review_at TEXT DEFAULT '',
                    evidence_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(goal_id) REFERENCES learning_goals(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS learning_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    score REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(item_id) REFERENCES learning_items(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS learning_mistakes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    prompt TEXT NOT NULL,
                    wrong_answer TEXT DEFAULT '',
                    correct_answer TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(item_id) REFERENCES learning_items(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS learning_courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    published_at TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS learning_course_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    topic_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    prerequisite_keys TEXT NOT NULL DEFAULT '[]',
                    mastery_threshold REAL NOT NULL DEFAULT 0.72,
                    source_ref TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(course_id, topic_key),
                    FOREIGN KEY(course_id) REFERENCES learning_courses(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS learning_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    topic_key TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    expected_concepts TEXT NOT NULL DEFAULT '[]',
                    cognitive_level TEXT NOT NULL DEFAULT 'explain',
                    difficulty REAL NOT NULL DEFAULT 0.5,
                    source_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(course_id, topic_key, prompt),
                    FOREIGN KEY(course_id) REFERENCES learning_courses(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS learning_enrollments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    learner_id TEXT NOT NULL,
                    course_id INTEGER NOT NULL,
                    goal_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(learner_id, course_id),
                    FOREIGN KEY(course_id) REFERENCES learning_courses(id)
                );
                CREATE TABLE IF NOT EXISTS learning_item_models (
                    item_id INTEGER PRIMARY KEY,
                    topic_key TEXT NOT NULL,
                    p_known REAL NOT NULL DEFAULT 0.05,
                    stability REAL NOT NULL DEFAULT 1,
                    difficulty REAL NOT NULL DEFAULT 0.5,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    last_review_at TEXT DEFAULT '',
                    algorithm_version TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(item_id) REFERENCES learning_items(id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS learning_assessment_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    learner_id TEXT NOT NULL,
                    enrollment_id INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    question_id INTEGER NOT NULL,
                    answer TEXT NOT NULL,
                    score REAL NOT NULL,
                    rubric_result TEXT NOT NULL DEFAULT '{}',
                    model_before TEXT NOT NULL DEFAULT '{}',
                    model_after TEXT NOT NULL DEFAULT '{}',
                    evidence_digest TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(enrollment_id) REFERENCES learning_enrollments(id),
                    FOREIGN KEY(item_id) REFERENCES learning_items(id),
                    FOREIGN KEY(question_id) REFERENCES learning_questions(id)
                );
                CREATE TABLE IF NOT EXISTS learning_project_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    learner_id TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    task_id TEXT NOT NULL,
                    artifact_digest TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    score REAL NOT NULL,
                    explanation TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(learner_id, item_id, task_id, artifact_digest),
                    FOREIGN KEY(item_id) REFERENCES learning_items(id)
                );
                """
            )

    def _seed_builtin_course(self) -> None:
        course = {
            "course_key": "clawos-ai-foundations-v1",
            "title": "ClawOS AI Foundations",
            "description": (
                "Evidence-based foundations for retrieval, agents, coding, "
                "evaluation, and governance."
            ),
        }
        topics = [
            ("rag", "Retrieval-Augmented Generation", [], "builtin:rag"),
            ("agent", "Agent Planning and Tools", ["rag"], "builtin:agent"),
            (
                "aicoding", "Agentic Coding", ["agent"],
                "builtin:agentic-coding",
            ),
            (
                "evaluation", "Evaluation and Evidence", ["aicoding"],
                "builtin:evaluation",
            ),
            (
                "governance", "Safety and Governance", ["evaluation"],
                "builtin:governance",
            ),
        ]
        questions = [
            (
                "rag",
                "Explain why retrieval evidence can improve an answer and "
                "name one failure mode.",
                ["retrieval", "evidence", "failure"],
                "analyze",
            ),
            (
                "agent",
                "Explain the difference between a plan, a tool action, and "
                "an observation in an agent loop.",
                ["plan", "tool", "observation"],
                "explain",
            ),
            (
                "aicoding",
                "Describe how a coding agent should protect user changes "
                "while editing and testing a repository.",
                ["checkpoint", "diff", "test"],
                "apply",
            ),
            (
                "evaluation",
                "Explain why a held-out evaluation and a regression gate are "
                "both needed before promotion.",
                ["holdout", "regression", "promotion"],
                "analyze",
            ),
            (
                "governance",
                "Explain why behavioral instructions are not a substitute "
                "for enforced permissions.",
                ["instruction", "permission", "enforcement"],
                "analyze",
            ),
        ]
        with self.store._conn() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO learning_courses
                    (course_key, title, description, status, published_at)
                VALUES (?, ?, ?, 'published', datetime('now'))
                """,
                (
                    course["course_key"], course["title"],
                    course["description"],
                ),
            )
            course_id = int(connection.execute(
                "SELECT id FROM learning_courses WHERE course_key=?",
                (course["course_key"],),
            ).fetchone()["id"])
            for position, (key, title, prerequisites, source) in enumerate(
                topics
            ):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO learning_course_topics
                        (course_id, topic_key, title, prerequisite_keys,
                         source_ref, position)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        course_id, key, title,
                        json.dumps(prerequisites), source, position,
                    ),
                )
            for topic, prompt, concepts, cognitive_level in questions:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO learning_questions
                        (course_id, topic_key, prompt, expected_concepts,
                         cognitive_level, source_ref)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        course_id, topic, prompt, json.dumps(concepts),
                        cognitive_level, f"builtin:{topic}",
                    ),
                )

    def list_courses(self, *, include_drafts: bool = False) -> list[dict]:
        with self.store._conn() as connection:
            where = "" if include_drafts else " WHERE status='published'"
            rows = connection.execute(
                f"SELECT * FROM learning_courses{where} ORDER BY id"
            ).fetchall()
            return [dict(row) for row in rows]

    def enroll(
        self, course_id: int, *, learner_id: str = DEFAULT_LEARNER
    ) -> dict:
        learner = str(learner_id or self.DEFAULT_LEARNER)
        with self.store._conn() as connection:
            course = connection.execute(
                "SELECT * FROM learning_courses WHERE id=? AND status='published'",
                (int(course_id),),
            ).fetchone()
            if not course:
                raise ValueError("published course not found")
            existing = connection.execute(
                """
                SELECT * FROM learning_enrollments
                WHERE learner_id=? AND course_id=?
                """,
                (learner, int(course_id)),
            ).fetchone()
            if existing:
                return dict(existing)
            cursor = connection.execute(
                """
                INSERT INTO learning_goals (title, description)
                VALUES (?, ?)
                """,
                (course["title"], course["description"]),
            )
            goal_id = int(cursor.lastrowid)
            topics = connection.execute(
                """
                SELECT * FROM learning_course_topics
                WHERE course_id=? ORDER BY position, id
                """,
                (int(course_id),),
            ).fetchall()
            now = datetime.now(timezone.utc).isoformat()
            for topic in topics:
                item_cursor = connection.execute(
                    """
                    INSERT INTO learning_items
                        (goal_id, topic, next_review_at)
                    VALUES (?, ?, ?)
                    """,
                    (goal_id, topic["title"], now),
                )
                connection.execute(
                    """
                    INSERT INTO learning_item_models
                        (item_id, topic_key, algorithm_version)
                    VALUES (?, ?, ?)
                    """,
                    (
                        int(item_cursor.lastrowid), topic["topic_key"],
                        self.ALGORITHM_VERSION,
                    ),
                )
            enrollment_cursor = connection.execute(
                """
                INSERT INTO learning_enrollments
                    (learner_id, course_id, goal_id)
                VALUES (?, ?, ?)
                """,
                (learner, int(course_id), goal_id),
            )
            return dict(connection.execute(
                "SELECT * FROM learning_enrollments WHERE id=?",
                (int(enrollment_cursor.lastrowid),),
            ).fetchone())

    def ensure_enrollment(
        self, *, learner_id: str = DEFAULT_LEARNER
    ) -> dict:
        courses = self.list_courses()
        if not courses:
            raise ValueError("no published course is available")
        return self.enroll(courses[0]["id"], learner_id=learner_id)

    def dashboard(
        self, *, learner_id: str = DEFAULT_LEARNER
    ) -> dict[str, Any]:
        enrollment = self.ensure_enrollment(learner_id=learner_id)
        with self.store._conn() as connection:
            course = dict(connection.execute(
                "SELECT * FROM learning_courses WHERE id=?",
                (int(enrollment["course_id"]),),
            ).fetchone())
            rows = connection.execute(
                """
                SELECT li.*, lm.topic_key, lm.p_known, lm.stability,
                       lm.difficulty, lm.review_count, lm.algorithm_version,
                       lct.prerequisite_keys, lct.mastery_threshold,
                       lct.source_ref
                FROM learning_items li
                JOIN learning_item_models lm ON lm.item_id=li.id
                JOIN learning_course_topics lct
                  ON lct.course_id=? AND lct.topic_key=lm.topic_key
                WHERE li.goal_id=?
                ORDER BY lct.position, li.id
                """,
                (int(enrollment["course_id"]), int(enrollment["goal_id"])),
            ).fetchall()
            now = datetime.now(timezone.utc).isoformat()
            topics = []
            mastery_by_key = {}
            for row in rows:
                item = dict(row)
                prerequisites = json.loads(item.pop("prerequisite_keys"))
                item["prerequisites"] = prerequisites
                item["due"] = bool(
                    item.get("next_review_at")
                    and item["next_review_at"] <= now
                )
                item["mastered"] = (
                    float(item["p_known"])
                    >= float(item["mastery_threshold"])
                    and int(item["evidence_count"]) >= 2
                )
                mastery_by_key[item["topic_key"]] = float(item["p_known"])
                topics.append(item)
            for item in topics:
                item["unlocked"] = all(
                    mastery_by_key.get(key, 0) >= 0.72
                    for key in item["prerequisites"]
                )
            return {
                "schema": "clawos.learning-dashboard.v1",
                "learner_id": str(learner_id),
                "course": course,
                "enrollment": enrollment,
                "topics": topics,
                "due_count": sum(item["due"] for item in topics),
                "mastered_count": sum(item["mastered"] for item in topics),
                "truth_boundary": (
                    "Mastery is derived from persisted assessment or project "
                    "evidence; UI clicks cannot directly change it."
                ),
            }

    def next_quiz(
        self, *, learner_id: str = DEFAULT_LEARNER
    ) -> dict[str, Any]:
        dashboard = self.dashboard(learner_id=learner_id)
        candidates = [
            item for item in dashboard["topics"]
            if item["unlocked"] and (item["due"] or not item["mastered"])
        ]
        if not candidates:
            candidates = [
                item for item in dashboard["topics"] if item["unlocked"]
            ]
        if not candidates:
            raise ValueError("no unlocked learning topic is available")
        item = sorted(
            candidates,
            key=lambda row: (
                not row["due"], float(row["p_known"]), int(row["id"])
            ),
        )[0]
        with self.store._conn() as connection:
            question = connection.execute(
                """
                SELECT id, topic_key, prompt, cognitive_level, difficulty,
                       source_ref
                FROM learning_questions
                WHERE course_id=? AND topic_key=? AND status='active'
                ORDER BY id LIMIT 1
                """,
                (
                    int(dashboard["enrollment"]["course_id"]),
                    item["topic_key"],
                ),
            ).fetchone()
        if not question:
            raise ValueError("unlocked topic has no active question")
        return {
            "schema": "clawos.learning-quiz.v1",
            "item_id": int(item["id"]),
            "question": dict(question),
            "answer_disclosed": False,
        }

    def submit_answer(
        self, question_id: int, answer: str, *,
        learner_id: str = DEFAULT_LEARNER,
    ) -> dict[str, Any]:
        response = str(answer or "").strip()
        if len(response) < 24:
            raise ValueError("answer must contain at least 24 characters")
        dashboard = self.dashboard(learner_id=learner_id)
        with self.store._conn() as connection:
            question = connection.execute(
                "SELECT * FROM learning_questions WHERE id=? AND status='active'",
                (int(question_id),),
            ).fetchone()
            if not question:
                raise ValueError("active question not found")
            item = next(
                (
                    row for row in dashboard["topics"]
                    if row["topic_key"] == question["topic_key"]
                ),
                None,
            )
            if not item or not item["unlocked"]:
                raise ValueError("question topic is not unlocked")
            concepts = [
                str(value).lower()
                for value in json.loads(question["expected_concepts"])
            ]
            normalized = response.lower()
            matched = [
                concept for concept in concepts if concept in normalized
            ]
            coverage = len(matched) / max(1, len(concepts))
            reasoning_markers = sum(
                bool(re.search(pattern, normalized))
                for pattern in (
                    r"\b(because|therefore|however|failure|risk)\b",
                    r"\b(example|such as|for instance)\b",
                )
            )
            reasoning = min(1.0, reasoning_markers / 2)
            score = round(coverage * 0.8 + reasoning * 0.2, 4)
            rubric = {
                "concept_coverage": round(coverage, 4),
                "matched_concepts": matched,
                "missing_concepts": [
                    value for value in concepts if value not in matched
                ],
                "reasoning_signal": round(reasoning, 4),
                "grader": "deterministic-concept-rubric.v1",
            }
            before = self._model_from_row(item)
            after = self._update_model(before, score)
            evidence_digest = hashlib.sha256(
                json.dumps(
                    {
                        "question_id": int(question_id),
                        "answer": response,
                        "rubric": rubric,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            now = datetime.now(timezone.utc)
            connection.execute(
                """
                INSERT INTO learning_assessment_attempts
                    (learner_id, enrollment_id, item_id, question_id, answer,
                     score, rubric_result, model_before, model_after,
                     evidence_digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(learner_id), int(dashboard["enrollment"]["id"]),
                    int(item["id"]), int(question_id), response, score,
                    json.dumps(rubric), json.dumps(before),
                    json.dumps(after), evidence_digest,
                ),
            )
            connection.execute(
                """
                INSERT INTO learning_reviews (item_id, score, evidence, notes)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(item["id"]), score,
                    f"assessment:{evidence_digest}",
                    json.dumps(rubric),
                ),
            )
            connection.execute(
                """
                UPDATE learning_item_models
                SET p_known=?, stability=?, difficulty=?, review_count=?,
                    last_review_at=?, algorithm_version=?,
                    updated_at=datetime('now')
                WHERE item_id=?
                """,
                (
                    after["p_known"], after["stability"],
                    after["difficulty"], after["review_count"],
                    now.isoformat(), self.ALGORITHM_VERSION, int(item["id"]),
                ),
            )
            interval = self._interval_days(after, score)
            connection.execute(
                """
                UPDATE learning_items
                SET mastery=?, interval_days=?, next_review_at=?,
                    evidence_count=evidence_count+1,
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    after["p_known"], interval,
                    (now + timedelta(days=interval)).isoformat(),
                    int(item["id"]),
                ),
            )
            if score < 0.6:
                connection.execute(
                    """
                    INSERT INTO learning_mistakes
                        (item_id, prompt, wrong_answer, correct_answer, evidence)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        int(item["id"]), question["prompt"], response,
                        "Expected concepts: " + ", ".join(concepts),
                        f"assessment:{evidence_digest}",
                    ),
                )
        return {
            "schema": "clawos.learning-assessment-result.v1",
            "score": score,
            "rubric": rubric,
            "model_before": before,
            "model_after": after,
            "next_review_days": self._interval_days(after, score),
            "evidence_digest": evidence_digest,
            "mastered": (
                after["p_known"] >= 0.72
                and int(item["evidence_count"]) + 1 >= 2
            ),
            "truth_boundary": (
                "This deterministic rubric measures declared concept coverage, "
                "not unrestricted semantic correctness. Low-confidence or "
                "high-stakes assessment requires reviewed evaluator evidence."
            ),
        }

    def record_project_evidence(
        self, *, learner_id: str, item_id: int, task_id: str,
        artifact_digest: str, evidence_type: str, score: float,
        explanation: str = "",
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9]{64}", str(artifact_digest or "")):
            raise ValueError("artifact_digest must be a SHA-256 hex digest")
        if not str(task_id or "").isdigit():
            raise ValueError("task_id must identify a canonical TaskRun")
        task_detail = self.store.get_task(int(task_id))
        task = dict(task_detail.get("task") or {})
        if not task or task.get("status") != "succeeded":
            raise ValueError("project evidence requires a succeeded TaskRun")
        if artifact_digest not in json.dumps(
            task_detail, sort_keys=True, default=str
        ):
            raise ValueError(
                "artifact_digest is not present in the TaskRun evidence"
            )
        bounded = max(0.0, min(float(score), 1.0))
        with self.store._conn() as connection:
            item = connection.execute(
                """
                SELECT li.*, lm.*
                FROM learning_items li
                JOIN learning_item_models lm ON lm.item_id=li.id
                WHERE li.id=?
                """,
                (int(item_id),),
            ).fetchone()
            if not item:
                raise ValueError("learning item not found")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO learning_project_evidence
                    (learner_id, item_id, task_id, artifact_digest,
                     evidence_type, score, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(learner_id), int(item_id), str(task_id),
                    artifact_digest, str(evidence_type), bounded,
                    str(explanation or ""),
                ),
            )
            accepted = cursor.rowcount == 1
            if accepted:
                before = self._model_from_row(dict(item))
                after = self._update_model(before, bounded, learn_rate=0.08)
                connection.execute(
                    """
                    UPDATE learning_item_models
                    SET p_known=?, stability=?, difficulty=?, review_count=?,
                        last_review_at=datetime('now'),
                        algorithm_version=?, updated_at=datetime('now')
                    WHERE item_id=?
                    """,
                    (
                        after["p_known"], after["stability"],
                        after["difficulty"], after["review_count"],
                        self.ALGORITHM_VERSION, int(item_id),
                    ),
                )
                connection.execute(
                    """
                    UPDATE learning_items
                    SET mastery=?, evidence_count=evidence_count+1,
                        updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (after["p_known"], int(item_id)),
                )
            else:
                after = self._model_from_row(dict(item))
        return {
            "schema": "clawos.learning-project-evidence.v1",
            "accepted": accepted,
            "item_id": int(item_id),
            "task_id": str(task_id),
            "artifact_digest": artifact_digest,
            "model_after": after,
        }

    def create_course(
        self, *, course_key: str, title: str, description: str,
        topics: list[dict[str, Any]], created_by: str,
    ) -> dict[str, Any]:
        key = str(course_key or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", key):
            raise ValueError("course_key must be a safe stable identifier")
        if len(str(title or "").strip()) < 3 or not topics:
            raise ValueError("course title and topics are required")
        normalized = []
        seen = set()
        for position, topic in enumerate(topics):
            topic_key = str(topic.get("topic_key") or "").strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,63}", topic_key):
                raise ValueError("each topic requires a safe topic_key")
            if topic_key in seen:
                raise ValueError("topic keys must be unique")
            seen.add(topic_key)
            source_ref = str(topic.get("source_ref") or "").strip()
            if not source_ref:
                raise ValueError("each topic requires source_ref")
            normalized.append({
                "topic_key": topic_key,
                "title": str(topic.get("title") or topic_key).strip(),
                "prerequisites": sorted({
                    str(value).strip().lower()
                    for value in topic.get("prerequisites") or []
                    if str(value).strip()
                }),
                "mastery_threshold": max(
                    0.5,
                    min(float(topic.get("mastery_threshold") or 0.72), 0.95),
                ),
                "source_ref": source_ref,
                "position": position,
            })
        with self.store._conn() as connection:
            cursor = connection.execute(
                """
                INSERT INTO learning_courses
                    (course_key, title, description, status, created_by)
                VALUES (?, ?, ?, 'draft', ?)
                """,
                (
                    key, str(title).strip(), str(description or ""),
                    str(created_by or "local-user"),
                ),
            )
            course_id = int(cursor.lastrowid)
            for topic in normalized:
                connection.execute(
                    """
                    INSERT INTO learning_course_topics
                        (course_id, topic_key, title, prerequisite_keys,
                         mastery_threshold, source_ref, position)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        course_id, topic["topic_key"], topic["title"],
                        json.dumps(topic["prerequisites"]),
                        topic["mastery_threshold"], topic["source_ref"],
                        topic["position"],
                    ),
                )
            return dict(connection.execute(
                "SELECT * FROM learning_courses WHERE id=?", (course_id,)
            ).fetchone())

    def publish_course(self, course_id: int) -> dict[str, Any]:
        validation = self.validate_course_for_publish(course_id)
        if not validation["valid"]:
            failed = [
                key for key, value in validation["checks"].items() if not value
            ]
            raise ValueError(
                "course publish gate failed: " + ", ".join(failed)
            )
        with self.store._conn() as connection:
            connection.execute(
                """
                UPDATE learning_courses
                SET status='published', published_at=datetime('now'),
                    updated_at=datetime('now')
                WHERE id=?
                """,
                (int(course_id),),
            )
            course = dict(connection.execute(
                "SELECT * FROM learning_courses WHERE id=?",
                (int(course_id),),
            ).fetchone())
        return {
            "schema": "clawos.learning-course-publication.v1",
            "course": course,
            "validation": validation,
        }

    def add_question(
        self, course_id: int, *, topic_key: str, prompt: str,
        expected_concepts: list[str], cognitive_level: str,
        difficulty: float, source_ref: str,
    ) -> dict:
        if not str(source_ref or "").strip():
            raise ValueError("source_ref is required")
        concepts = sorted({
            str(value).strip().lower()
            for value in expected_concepts if str(value).strip()
        })
        if len(str(prompt or "").strip()) < 20 or len(concepts) < 2:
            raise ValueError("question and at least two concepts are required")
        allowed_levels = {"remember", "explain", "apply", "analyze", "create"}
        if cognitive_level not in allowed_levels:
            raise ValueError("unsupported cognitive_level")
        with self.store._conn() as connection:
            if not connection.execute(
                """
                SELECT 1 FROM learning_course_topics
                WHERE course_id=? AND topic_key=?
                """,
                (int(course_id), str(topic_key)),
            ).fetchone():
                raise ValueError("course topic not found")
            cursor = connection.execute(
                """
                INSERT INTO learning_questions
                    (course_id, topic_key, prompt, expected_concepts,
                     cognitive_level, difficulty, source_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(course_id), str(topic_key), str(prompt).strip(),
                    json.dumps(concepts), cognitive_level,
                    max(0.0, min(float(difficulty), 1.0)), str(source_ref),
                ),
            )
            return dict(connection.execute(
                "SELECT * FROM learning_questions WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone())

    def mistake_queue(
        self, *, learner_id: str = DEFAULT_LEARNER
    ) -> dict[str, Any]:
        dashboard = self.dashboard(learner_id=learner_id)
        item_ids = [int(item["id"]) for item in dashboard["topics"]]
        if not item_ids:
            rows = []
        else:
            placeholders = ",".join("?" for _ in item_ids)
            with self.store._conn() as connection:
                rows = connection.execute(
                    f"""
                    SELECT lm.*, li.topic
                    FROM learning_mistakes lm
                    JOIN learning_items li ON li.id=lm.item_id
                    WHERE lm.item_id IN ({placeholders})
                      AND lm.status='open'
                    ORDER BY lm.id
                    """,
                    item_ids,
                ).fetchall()
        return {
            "schema": "clawos.learning-mistake-queue.v1",
            "learner_id": str(learner_id),
            "mistakes": [dict(row) for row in rows],
            "count": len(rows),
        }

    def resolve_mistake(
        self, mistake_id: int, *, resolution_evidence: str,
        learner_id: str = DEFAULT_LEARNER,
    ) -> dict[str, Any]:
        evidence = str(resolution_evidence or "").strip()
        if len(evidence) < 16:
            raise ValueError(
                "resolution_evidence must contain at least 16 characters"
            )
        queue = self.mistake_queue(learner_id=learner_id)
        if int(mistake_id) not in {
            int(item["id"]) for item in queue["mistakes"]
        }:
            raise ValueError("open learner mistake not found")
        with self.store._conn() as connection:
            connection.execute(
                """
                UPDATE learning_mistakes
                SET status='resolved',
                    evidence=evidence || ? || ?
                WHERE id=?
                """,
                (
                    "\nresolution:", evidence, int(mistake_id),
                ),
            )
            row = connection.execute(
                "SELECT * FROM learning_mistakes WHERE id=?",
                (int(mistake_id),),
            ).fetchone()
        return {
            "schema": "clawos.learning-mistake-resolution.v1",
            "mistake": dict(row),
            "mastery_changed": False,
            "truth_boundary": (
                "Resolving a mistake changes its workflow state only. A new "
                "assessment or project artifact is required to change mastery."
            ),
        }

    def explain_item(
        self, item_id: int, *, learner_id: str = DEFAULT_LEARNER
    ) -> dict[str, Any]:
        dashboard = self.dashboard(learner_id=learner_id)
        item = next(
            (
                value for value in dashboard["topics"]
                if int(value["id"]) == int(item_id)
            ),
            None,
        )
        if not item:
            raise ValueError("learner item not found")
        with self.store._conn() as connection:
            attempts = [
                dict(row) for row in connection.execute(
                    """
                    SELECT id, question_id, score, rubric_result,
                           model_before, model_after, evidence_digest,
                           created_at
                    FROM learning_assessment_attempts
                    WHERE learner_id=? AND item_id=? ORDER BY id
                    """,
                    (str(learner_id), int(item_id)),
                ).fetchall()
            ]
            projects = [
                dict(row) for row in connection.execute(
                    """
                    SELECT task_id, artifact_digest, evidence_type, score,
                           explanation, created_at
                    FROM learning_project_evidence
                    WHERE learner_id=? AND item_id=? ORDER BY id
                    """,
                    (str(learner_id), int(item_id)),
                ).fetchall()
            ]
        for attempt in attempts:
            for key in ("rubric_result", "model_before", "model_after"):
                attempt[key] = json.loads(attempt[key] or "{}")
        return {
            "schema": "clawos.learning-mastery-explanation.v1",
            "learner_id": str(learner_id),
            "item": item,
            "assessment_attempts": attempts,
            "project_evidence": projects,
            "decision": {
                "mastered": item["mastered"],
                "threshold": item["mastery_threshold"],
                "p_known": item["p_known"],
                "minimum_evidence": 2,
                "algorithm_version": item["algorithm_version"],
                "next_review_at": item["next_review_at"],
            },
        }

    def validate_course_for_publish(self, course_id: int) -> dict[str, Any]:
        with self.store._conn() as connection:
            course = connection.execute(
                "SELECT * FROM learning_courses WHERE id=?", (int(course_id),)
            ).fetchone()
            topics = connection.execute(
                "SELECT * FROM learning_course_topics WHERE course_id=?",
                (int(course_id),),
            ).fetchall()
            counts = {
                row["topic_key"]: int(row["count"])
                for row in connection.execute(
                    """
                    SELECT topic_key, COUNT(*) AS count
                    FROM learning_questions
                    WHERE course_id=? AND status='active'
                    GROUP BY topic_key
                    """,
                    (int(course_id),),
                ).fetchall()
            }
        topic_keys = {str(row["topic_key"]) for row in topics}
        edges = {
            str(row["topic_key"]): [
                str(value)
                for value in json.loads(row["prerequisite_keys"] or "[]")
            ]
            for row in topics
        }
        prerequisites_known = all(
            dependency in topic_keys
            for dependencies in edges.values()
            for dependency in dependencies
        )
        visiting: set[str] = set()
        visited: set[str] = set()

        def acyclic(node: str) -> bool:
            if node in visiting:
                return False
            if node in visited:
                return True
            visiting.add(node)
            if any(
                not acyclic(dependency)
                for dependency in edges.get(node, [])
                if dependency in topic_keys
            ):
                return False
            visiting.remove(node)
            visited.add(node)
            return True

        graph_acyclic = prerequisites_known and all(
            acyclic(node) for node in topic_keys
        )
        checks = {
            "course_exists": bool(course),
            "has_topics": bool(topics),
            "all_topics_sourced": bool(topics) and all(
                str(row["source_ref"] or "").strip() for row in topics
            ),
            "all_topics_assessed": bool(topics) and all(
                counts.get(row["topic_key"], 0) > 0 for row in topics
            ),
            "mastery_thresholds_valid": bool(topics) and all(
                0.5 <= float(row["mastery_threshold"]) <= 0.95
                for row in topics
            ),
            "prerequisites_known": prerequisites_known,
            "prerequisite_graph_acyclic": graph_acyclic,
        }
        return {
            "schema": "clawos.course-publish-validation.v1",
            "valid": all(checks.values()),
            "checks": checks,
            "course_id": int(course_id),
        }

    @staticmethod
    def _model_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "p_known": float(row.get("p_known") or 0.05),
            "stability": float(row.get("stability") or 1),
            "difficulty": float(row.get("difficulty") or 0.5),
            "review_count": int(row.get("review_count") or 0),
        }

    @staticmethod
    def _update_model(
        before: dict[str, Any], score: float, *, learn_rate: float = 0.12
    ) -> dict[str, Any]:
        prior = max(0.001, min(float(before["p_known"]), 0.999))
        observed = max(0.0, min(float(score), 1.0))
        guess, slip = 0.20, 0.10
        likelihood_known = observed * (1 - slip) + (1 - observed) * slip
        likelihood_unknown = observed * guess + (1 - observed) * (1 - guess)
        posterior = (
            prior * likelihood_known
            / max(
                1e-9,
                prior * likelihood_known
                + (1 - prior) * likelihood_unknown,
            )
        )
        learned = posterior + (1 - posterior) * learn_rate
        stability = max(
            1.0,
            float(before["stability"])
            * (0.8 if observed < 0.6 else 1.0 + observed),
        )
        difficulty = max(
            0.05,
            min(
                0.95,
                float(before["difficulty"]) + (0.5 - observed) * 0.15,
            ),
        )
        return {
            "p_known": round(min(0.999, learned), 6),
            "stability": round(stability, 4),
            "difficulty": round(difficulty, 4),
            "review_count": int(before["review_count"]) + 1,
            "algorithm_version": LearningProductService.ALGORITHM_VERSION,
        }

    @staticmethod
    def _interval_days(model: dict[str, Any], score: float) -> int:
        if score < 0.6:
            return 1
        value = (
            float(model["stability"])
            * (1 + float(model["p_known"]))
            * (1.2 - float(model["difficulty"]) / 2)
        )
        return max(2, min(90, int(math.ceil(value))))
