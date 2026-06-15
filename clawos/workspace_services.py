"""Persistent personal-workspace services for meetings, research, learning, Git, and templates."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


class WorkspaceServices:
    """Application-layer workflows backed by the shared MemoryOS database."""

    def __init__(self, store, security_policy):
        self.store = store
        self.security = security_policy
        self._init_db()
        self._ensure_builtin_templates()

    def _init_db(self):
        with self.store._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    meeting_date TEXT DEFAULT '',
                    attendees TEXT NOT NULL DEFAULT '[]',
                    agenda TEXT NOT NULL DEFAULT '[]',
                    transcript TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    decisions TEXT NOT NULL DEFAULT '[]',
                    risks TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS meeting_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    owner TEXT DEFAULT '',
                    due_date TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    evidence TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS research_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    file_path TEXT NOT NULL UNIQUE,
                    file_hash TEXT NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS research_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    page_number INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(document_id) REFERENCES research_documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_research_chunks_doc ON research_chunks(document_id, page_number);
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
                    FOREIGN KEY(goal_id) REFERENCES learning_goals(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS learning_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    score REAL NOT NULL,
                    evidence TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(item_id) REFERENCES learning_items(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS project_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    description TEXT DEFAULT '',
                    files TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(name, version)
                );
                CREATE TABLE IF NOT EXISTS template_instantiations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL,
                    target_path TEXT NOT NULL,
                    parameters TEXT NOT NULL DEFAULT '{}',
                    created_files TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'succeeded',
                    error TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(template_id) REFERENCES project_templates(id)
                );
            """)

    # ---- MEETINGS ----

    def create_meeting(self, title, meeting_date="", attendees=None, agenda=None):
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO meetings (title, meeting_date, attendees, agenda)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(title), str(meeting_date or ""),
                    json.dumps(attendees or [], ensure_ascii=False),
                    json.dumps(agenda or [], ensure_ascii=False),
                ),
            )
            return self.get_meeting(int(cursor.lastrowid), conn=c)

    def process_meeting_transcript(self, meeting_id, transcript):
        decisions, risks, actions = self._extract_meeting_items(transcript)
        summary = self._summarize_text(transcript)
        with self.store._conn() as c:
            c.execute(
                """
                UPDATE meetings
                SET transcript=?, summary=?, decisions=?, risks=?,
                    status='completed', updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    str(transcript), summary,
                    json.dumps(decisions, ensure_ascii=False),
                    json.dumps(risks, ensure_ascii=False),
                    int(meeting_id),
                ),
            )
            c.execute("DELETE FROM meeting_actions WHERE meeting_id=?", (int(meeting_id),))
            for action in actions:
                c.execute(
                    """
                    INSERT INTO meeting_actions
                        (meeting_id, description, owner, due_date, evidence)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        int(meeting_id), action["description"], action["owner"],
                        action["due_date"], action["evidence"],
                    ),
                )
            meeting = self.get_meeting(meeting_id, conn=c)
        self.store.upsert_memory(
            "experience",
            f"meeting:{meeting_id}",
            summary or meeting["title"],
            category="meeting",
            source="meeting_workflow",
            confidence=0.8,
            evidence=[{
                "evidence_type": "meeting_transcript",
                "source_ref": f"meeting:{meeting_id}",
                "excerpt": transcript[:1000],
            }],
        )
        return meeting

    def get_meeting(self, meeting_id, conn=None):
        def fetch(c):
            row = c.execute("SELECT * FROM meetings WHERE id=?", (int(meeting_id),)).fetchone()
            if not row:
                return None
            item = dict(row)
            for key in ("attendees", "agenda", "decisions", "risks"):
                item[key] = json.loads(item.get(key) or "[]")
            actions = c.execute(
                "SELECT * FROM meeting_actions WHERE meeting_id=? ORDER BY id",
                (int(meeting_id),),
            ).fetchall()
            item["actions"] = [dict(action) for action in actions]
            return item
        if conn is not None:
            return fetch(conn)
        with self.store._conn() as c:
            return fetch(c)

    @staticmethod
    def _extract_meeting_items(transcript):
        decisions, risks, actions = [], [], []
        for raw in str(transcript or "").splitlines():
            line = raw.strip(" -*\t")
            if not line:
                continue
            lower = line.lower()
            if re.match(r"^(decision|决定|决议)\s*[:：]", lower):
                decisions.append(re.split(r"[:：]", line, maxsplit=1)[1].strip())
            elif re.match(r"^(risk|风险)\s*[:：]", lower):
                risks.append(re.split(r"[:：]", line, maxsplit=1)[1].strip())
            elif re.match(r"^(action|行动项|待办)\s*[:：]", lower):
                content = re.split(r"[:：]", line, maxsplit=1)[1].strip()
                parts = [part.strip() for part in re.split(r"\s*\|\s*", content)]
                actions.append({
                    "description": parts[1] if len(parts) > 1 else parts[0],
                    "owner": parts[0] if len(parts) > 1 else "",
                    "due_date": parts[2] if len(parts) > 2 else "",
                    "evidence": line,
                })
        return decisions, risks, actions

    # ---- RESEARCH PDF ----

    def import_research_pdf(self, file_path, title=""):
        path = self.security.resolve_path(file_path)
        if path.suffix.lower() != ".pdf" or not path.is_file():
            raise ValueError("a readable PDF file is required")
        text = self._extract_pdf_text(path)
        pages = text.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        digest = self._file_hash(path)
        knowledge_entries = []
        with self.store._conn() as c:
            existing = c.execute(
                "SELECT id FROM research_documents WHERE file_path=?", (str(path),)
            ).fetchone()
            if existing:
                c.execute("DELETE FROM research_chunks WHERE document_id=?", (int(existing["id"]),))
                document_id = int(existing["id"])
                c.execute(
                    """
                    UPDATE research_documents
                    SET title=?, file_hash=?, page_count=?, metadata=?
                    WHERE id=?
                    """,
                    (
                        title or path.stem, digest, len(pages),
                        json.dumps({"extractor": "pdftotext"}, ensure_ascii=False),
                        document_id,
                    ),
                )
            else:
                cursor = c.execute(
                    """
                    INSERT INTO research_documents
                        (title, file_path, file_hash, page_count, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        title or path.stem, str(path), digest, len(pages),
                        json.dumps({"extractor": "pdftotext"}, ensure_ascii=False),
                    ),
                )
                document_id = int(cursor.lastrowid)
            chunk_count = 0
            for page_number, page in enumerate(pages, 1):
                for chunk_index, chunk in enumerate(self._chunk_text(page), 1):
                    c.execute(
                        """
                        INSERT INTO research_chunks
                            (document_id, page_number, chunk_index, content)
                        VALUES (?, ?, ?, ?)
                        """,
                        (document_id, page_number, chunk_index, chunk),
                    )
                    chunk_count += 1
                    knowledge_entries.append((page_number, chunk_index, chunk))
            document = dict(c.execute(
                "SELECT * FROM research_documents WHERE id=?", (document_id,)
            ).fetchone())
            document["chunk_count"] = chunk_count
        for page_number, chunk_index, chunk in knowledge_entries:
            self.store.add_knowledge(
                title=f"{title or path.stem} p.{page_number} #{chunk_index}",
                content=chunk,
                category="research_pdf",
                source=f"{path}#page={page_number}",
                confidence=0.9,
            )
        return document

    def search_research(self, query, limit=10):
        terms = [term for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", str(query))][:6]
        if not terms:
            return []
        with self.store._conn() as c:
            clauses = " OR ".join("rc.content LIKE ?" for _ in terms)
            rows = c.execute(
                f"""
                SELECT rc.*, rd.title, rd.file_path
                FROM research_chunks rc
                JOIN research_documents rd ON rd.id=rc.document_id
                WHERE {clauses}
                ORDER BY rc.document_id DESC, rc.page_number, rc.chunk_index
                LIMIT ?
                """,
                [*(f"%{term}%" for term in terms), max(1, min(int(limit), 50))],
            ).fetchall()
            return [{
                **dict(row),
                "citation": f"{row['title']} (p.{row['page_number']})",
                "source_ref": f"{row['file_path']}#page={row['page_number']}",
            } for row in rows]

    # ---- LEARNING ----

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
            return goal
        if conn is not None:
            return fetch(conn)
        with self.store._conn() as c:
            return fetch(c)

    # ---- GIT COLLABORATION ----

    def git_snapshot(self, repo_path):
        repo = self.security.resolve_path(repo_path)
        if not (repo / ".git").exists():
            raise ValueError("path is not a Git repository")
        branch = self._git(repo, "branch", "--show-current").strip()
        status = self._git(repo, "status", "--short")
        diff = self._git(repo, "diff", "--stat")
        log = self._git(repo, "log", "-5", "--oneline")
        changed = [line for line in status.splitlines() if line.strip()]
        return {
            "repo": str(repo),
            "branch": branch,
            "status": changed,
            "diff_stat": diff.splitlines(),
            "recent_commits": log.splitlines(),
            "clean": not changed,
        }

    def prepare_commit_plan(self, repo_path, message, files=None):
        snapshot = self.git_snapshot(repo_path)
        selected = files or [line[3:] for line in snapshot["status"] if len(line) > 3]
        return {
            "repo": snapshot["repo"],
            "branch": snapshot["branch"],
            "message": str(message).strip(),
            "files": selected,
            "commands": [
                ["git", "add", "--", *selected],
                ["git", "commit", "-m", str(message).strip()],
            ],
            "dry_run": True,
            "requires_confirmation": True,
        }

    # ---- TEMPLATE CENTER ----

    def register_template(self, name, description, files, version=1):
        if not isinstance(files, dict) or not files:
            raise ValueError("template files must be a non-empty object")
        with self.store._conn() as c:
            c.execute(
                """
                INSERT INTO project_templates (name, version, description, files)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name, version) DO UPDATE SET
                    description=excluded.description,
                    files=excluded.files,
                    status='active'
                """,
                (str(name), int(version), str(description or ""), json.dumps(files, ensure_ascii=False)),
            )
            row = c.execute(
                "SELECT * FROM project_templates WHERE name=? AND version=?",
                (str(name), int(version)),
            ).fetchone()
            return self._template_from_row(row)

    def list_templates(self):
        with self.store._conn() as c:
            rows = c.execute(
                "SELECT * FROM project_templates WHERE status='active' ORDER BY name, version DESC"
            ).fetchall()
            return [self._template_from_row(row) for row in rows]

    def instantiate_template(self, name, target_path, parameters=None, version=None):
        target = self.security.resolve_path(target_path)
        if target.exists():
            raise ValueError("target path already exists")
        with self.store._conn() as c:
            if version is None:
                row = c.execute(
                    """
                    SELECT * FROM project_templates
                    WHERE name=? AND status='active' ORDER BY version DESC LIMIT 1
                    """,
                    (str(name),),
                ).fetchone()
            else:
                row = c.execute(
                    "SELECT * FROM project_templates WHERE name=? AND version=? AND status='active'",
                    (str(name), int(version)),
                ).fetchone()
            if not row:
                raise ValueError("template not found")
            template = self._template_from_row(row)
        params = {"project_name": target.name, **(parameters or {})}
        staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex[:8]}"
        created = []
        try:
            staging.mkdir(parents=True)
            for relative, content in template["files"].items():
                relative_path = Path(relative)
                if relative_path.is_absolute() or ".." in relative_path.parts:
                    raise ValueError(f"unsafe template path: {relative}")
                output = staging / relative_path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(self._render_template(str(content), params), encoding="utf-8")
                created.append(relative_path.as_posix())
            staging.replace(target)
            with self.store._conn() as c:
                c.execute(
                    """
                    INSERT INTO template_instantiations
                        (template_id, target_path, parameters, created_files)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        int(template["id"]), str(target),
                        json.dumps(params, ensure_ascii=False),
                        json.dumps(created, ensure_ascii=False),
                    ),
                )
            return {
                "template": template["name"],
                "version": template["version"],
                "target_path": str(target),
                "created_files": created,
            }
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise

    def _ensure_builtin_templates(self):
        builtins = {
            "python-service": {
                "description": "Python service with tests and documentation",
                "files": {
                    "README.md": "# {{project_name}}\n\nPython service generated by ClawOS.\n",
                    "src/__init__.py": "",
                    "src/main.py": "def main():\n    return 'ok'\n",
                    "tests/test_main.py": "from src.main import main\n\ndef test_main():\n    assert main() == 'ok'\n",
                    ".gitignore": "__pycache__/\n.venv/\n.env\n",
                },
            },
            "research-project": {
                "description": "Reproducible research workspace",
                "files": {
                    "README.md": "# {{project_name}}\n\n## Research question\n\n## Reproduction\n",
                    "data/README.md": "Document data provenance here.\n",
                    "notebooks/README.md": "Keep experiments reproducible.\n",
                    "references/README.md": "Store citation metadata here.\n",
                    ".gitignore": ".ipynb_checkpoints/\ndata/raw/\noutputs/\n",
                },
            },
        }
        for name, item in builtins.items():
            self.register_template(name, item["description"], item["files"], version=1)

    @staticmethod
    def _render_template(content, parameters):
        rendered = content
        for key, value in parameters.items():
            rendered = rendered.replace("{{" + str(key) + "}}", str(value))
        return rendered

    @staticmethod
    def _summarize_text(text):
        clean = " ".join(str(text or "").split())
        return clean[:600]

    @staticmethod
    def _chunk_text(text, size=1200, overlap=150):
        clean = "\n".join(line.rstrip() for line in str(text).splitlines()).strip()
        if not clean:
            return []
        chunks = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + size)
            chunks.append(clean[start:end])
            if end == len(clean):
                break
            start = max(start + 1, end - overlap)
        return chunks

    @staticmethod
    def _extract_pdf_text(path):
        executable = shutil.which("pdftotext")
        if not executable:
            raise RuntimeError("pdftotext is required for local PDF extraction")
        proc = subprocess.run(
            [executable, "-layout", str(path), "-"],
            capture_output=True,
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:500])
        return proc.stdout.decode("utf-8", errors="replace")

    @staticmethod
    def _file_hash(path):
        import hashlib
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _git(repo, *args):
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git command failed")
        return proc.stdout

    @staticmethod
    def _template_from_row(row):
        item = dict(row)
        item["files"] = json.loads(item.get("files") or "{}")
        return item
