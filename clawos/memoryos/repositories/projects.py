from __future__ import annotations

import json

from memoryos.persistence import Repository, atomic_workflow


class ProjectsRepository(Repository):
    """Persistence operations for projects."""

    def __init__(self, session, memories):
        super().__init__(session)
        self._memories = memories

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


    @atomic_workflow
    def add_experience(self, task, outcome, lesson="", context="", solution="", tags=None, importance=0.5):
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO experiences (task,outcome,lesson,context,solution,tags,importance) VALUES (?,?,?,?,?,?,?)",
                (task, outcome, lesson, context, solution, json.dumps(tags or []), importance)
            )
            experience_id = int(cursor.lastrowid)
        self._memories.upsert_memory(
            "experience",
            f"reflection:{experience_id}",
            lesson or solution or task,
            category=outcome,
            source="reflection_engine",
            confidence=importance,
        )
        return experience_id


    def get_recent_experiences(self, limit: int = 20) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM experiences e WHERE NOT EXISTS (SELECT 1 FROM memories m WHERE m.memory_type='experience' AND m.key='reflection:'||e.id AND m.enabled=0) ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]


    def list_sessions(self, query="", limit=500) -> list[dict]:
        """List all conversation sessions with last message preview."""
        with self._conn() as c:
            source = """WITH history AS (
                SELECT id,session_id,role,content,created_at FROM conversations
                UNION ALL SELECT original_id,session_id,role,content,created_at FROM conversation_archive
                WHERE NOT EXISTS (SELECT 1 FROM conversations WHERE id=conversation_archive.original_id)) """
            rows = c.execute(source + """
                SELECT session_id, MAX(id) AS last_id
                FROM history WHERE role IN ('user','assistant')
                AND (?='' OR instr(lower(session_id),lower(?))>0 OR session_id IN (SELECT session_id FROM history
                    WHERE role IN ('user','assistant') AND instr(lower(content),lower(?))>0))
                GROUP BY session_id
                ORDER BY last_id DESC LIMIT ?
            """, (query,query,query,max(1,min(int(limit),500)))).fetchall()
            result = []
            for row in rows:
                sid = row["session_id"]
                msgs = c.execute(source + """SELECT role, content, created_at FROM history WHERE session_id=? AND role IN ('user','assistant') ORDER BY id DESC LIMIT 1""", (sid,)).fetchone()
                first_msgs = c.execute(
                    source + "SELECT role, content FROM history WHERE session_id=? AND role IN ('user','assistant') ORDER BY id ASC LIMIT 6",
                    (sid,),
                ).fetchall()
                title, tags = self._summarize_session(first_msgs, sid)
                result.append({
                    "session_id": sid,
                    "title": title,
                    "topic": title,
                    "tags": tags,
                    "role": (str(dict(msgs).get("role", "")) if msgs else ""),
                    "last_message": (str(dict(msgs).get("content", ""))[:100] if msgs else ""),
                    "updated_at": (str(dict(msgs).get("created_at", "")) if msgs else ""),
                })
            return result


    def _summarize_session(self, rows, fallback: str) -> tuple[str, list[str]]:
        text = " ".join(str(dict(r).get("content", "")) for r in rows)
        first_user = next((str(dict(r).get("content", "")) for r in rows if dict(r).get("role") == "user"), "")
        title = first_user.strip().replace("\n", " ") or fallback
        title = title[:34] + ("..." if len(title) > 34 else "")
        keywords = [
            ("项目", ["项目", "代码", "repo", "git", "测试", "前端", "后端"]),
            ("科研", ["论文", "科研", "实验", "文献", "paper", "research"]),
            ("学习", ["学习", "课程", "考试", "题", "复习"]),
            ("会议", ["会议", "纪要", "action", "待办"]),
            ("知识库", ["知识库", "rag", "资料", "文档"]),
            ("配置", ["模型", "api", "deepseek", "配置"]),
        ]
        lowered = text.lower()
        tags = [label for label, keys in keywords if any(k.lower() in lowered for k in keys)]
        return (title, tags[:4] or ["对话"])
