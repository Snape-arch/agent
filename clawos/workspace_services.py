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
from xml.sax.saxutils import escape as xml_escape

from office_artifacts import create_pptx, create_xlsx, edit_xlsx, replace_pptx_text


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
                CREATE TABLE IF NOT EXISTS meeting_audio_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    audio_path TEXT NOT NULL,
                    transcript_path TEXT DEFAULT '',
                    transcript_status TEXT NOT NULL DEFAULT 'registered',
                    diarization TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS meeting_connector_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meeting_id INTEGER NOT NULL,
                    connector_type TEXT NOT NULL,
                    target TEXT DEFAULT '',
                    draft_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'drafted',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
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
                CREATE TABLE IF NOT EXISTS research_repro_workflows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    question TEXT DEFAULT '',
                    output_path TEXT DEFAULT '',
                    manifest TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS research_analysis_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    markdown_path TEXT DEFAULT '',
                    pdf_path TEXT DEFAULT '',
                    question_count INTEGER NOT NULL DEFAULT 0,
                    depth INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(document_id) REFERENCES research_documents(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS office_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    file_path TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                );
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
                CREATE TABLE IF NOT EXISTS learning_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id INTEGER NOT NULL,
                    source_topic TEXT NOT NULL,
                    target_topic TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'depends_on',
                    evidence TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(goal_id) REFERENCES learning_goals(id) ON DELETE CASCADE
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
                    FOREIGN KEY(item_id) REFERENCES learning_items(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS git_change_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_path TEXT NOT NULL,
                    branch TEXT DEFAULT '',
                    message TEXT NOT NULL,
                    files TEXT NOT NULL DEFAULT '[]',
                    diff_preview TEXT NOT NULL DEFAULT '',
                    checkpoint_ref TEXT DEFAULT '',
                    after_ref TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending_approval',
                    created_by TEXT DEFAULT 'user',
                    approved_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
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

    # ---- OFFICE ARTIFACTS ----

    def create_spreadsheet(self, output_path, sheets=None, title=""):
        path = self.security.resolve_path(output_path)
        if path.suffix.lower() != ".xlsx":
            raise ValueError("output_path must end with .xlsx")
        artifact_path = create_xlsx(path, sheets or [{"name": "Sheet1", "rows": []}])
        return self._record_office_artifact(
            "spreadsheet", "create", title or path.stem, artifact_path,
            {"sheets": [sheet.get("name", "Sheet1") for sheet in (sheets or [])], "engine": "stdlib-openxml"},
        )

    def edit_spreadsheet(self, file_path, updates=None, output_path=""):
        path = self.security.resolve_path(file_path)
        if path.suffix.lower() != ".xlsx" or not path.is_file():
            raise ValueError("file_path must point to a readable .xlsx file")
        out = self.security.resolve_path(output_path) if output_path else path
        if out.suffix.lower() != ".xlsx":
            raise ValueError("output_path must end with .xlsx")
        artifact_path = edit_xlsx(path, updates or [], out)
        return self._record_office_artifact(
            "spreadsheet", "edit", out.stem, artifact_path,
            {"updates": updates or [], "engine": "stdlib-openxml"},
        )

    def create_presentation(self, output_path, title="", slides=None):
        path = self.security.resolve_path(output_path)
        if path.suffix.lower() != ".pptx":
            raise ValueError("output_path must end with .pptx")
        artifact_path = create_pptx(path, title=title or path.stem, slides=slides or [])
        return self._record_office_artifact(
            "presentation", "create", title or path.stem, artifact_path,
            {"slide_count": len(slides or []) or 1, "engine": "stdlib-openxml"},
        )

    def edit_presentation(self, file_path, replacements=None, output_path=""):
        path = self.security.resolve_path(file_path)
        if path.suffix.lower() != ".pptx" or not path.is_file():
            raise ValueError("file_path must point to a readable .pptx file")
        out = self.security.resolve_path(output_path) if output_path else path
        if out.suffix.lower() != ".pptx":
            raise ValueError("output_path must end with .pptx")
        artifact_path = replace_pptx_text(path, replacements or {}, out)
        return self._record_office_artifact(
            "presentation", "edit", out.stem, artifact_path,
            {"replacements": list((replacements or {}).keys()), "engine": "stdlib-openxml"},
        )

    def _record_office_artifact(self, artifact_type, action, title, path, metadata):
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO office_artifacts
                    (artifact_type, action, title, file_path, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(artifact_type), str(action), str(title), str(path),
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            row = c.execute(
                "SELECT * FROM office_artifacts WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
        item = dict(row)
        item["metadata"] = json.loads(item.get("metadata") or "{}")
        return item

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
            audio = c.execute(
                "SELECT * FROM meeting_audio_assets WHERE meeting_id=? ORDER BY id",
                (int(meeting_id),),
            ).fetchall()
            drafts = c.execute(
                "SELECT * FROM meeting_connector_drafts WHERE meeting_id=? ORDER BY id",
                (int(meeting_id),),
            ).fetchall()
            item["actions"] = [dict(action) for action in actions]
            item["audio_assets"] = [self._decode_record(row, ("diarization", "metadata")) for row in audio]
            item["connector_drafts"] = [self._decode_record(row, ("metadata",)) for row in drafts]
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
            speaker_line = re.match(r"^(?:\[[^\]]+\]\s*)?[^:：]{1,40}[:：]\s*(.+)$", line)
            if speaker_line:
                inner = speaker_line.group(1).strip()
                if re.match(r"^(decision|risk|action|决定|决议|风险|行动项|待办)\s*[:：]", inner, re.I):
                    line = inner
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

    def import_meeting_audio(self, audio_path, transcript_path="", transcript="", title="", meeting_id=None):
        audio = self.security.resolve_path(audio_path)
        if audio.suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"} or not audio.is_file():
            raise ValueError("a readable local audio file is required")
        transcript_text = str(transcript or "")
        transcript_file = ""
        if transcript_path:
            path = self.security.resolve_path(transcript_path)
            if path.suffix.lower() not in {".txt", ".md", ".srt", ".vtt"} or not path.is_file():
                raise ValueError("transcript_path must point to a readable text transcript")
            transcript_text = path.read_text(encoding="utf-8", errors="replace")
            transcript_file = str(path)
        if meeting_id:
            meeting = self.get_meeting(meeting_id)
            if not meeting:
                raise ValueError("meeting not found")
        else:
            meeting = self.create_meeting(title or audio.stem)
        diarization = self._parse_speaker_turns(transcript_text)
        status = "transcript_imported" if transcript_text.strip() else "audio_registered_requires_transcription"
        with self.store._conn() as c:
            c.execute(
                """
                INSERT INTO meeting_audio_assets
                    (meeting_id, audio_path, transcript_path, transcript_status, diarization, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(meeting["id"]), str(audio), transcript_file, status,
                    json.dumps(diarization, ensure_ascii=False),
                    json.dumps({
                        "size_bytes": audio.stat().st_size,
                        "speaker_count": len({turn["speaker"] for turn in diarization}),
                        "transcription_engine": "external_or_sidecar",
                    }, ensure_ascii=False),
                ),
            )
        if transcript_text.strip():
            meeting = self.process_meeting_transcript(meeting["id"], transcript_text)
        return {
            "meeting": self.get_meeting(meeting["id"]),
            "audio_path": str(audio),
            "transcript_status": status,
            "diarization": diarization,
            "capabilities": {
                "audio_registered": True,
                "sidecar_transcript_supported": True,
                "speaker_separation": "label_based",
                "local_whisper": shutil.which("whisper") is not None,
            },
        }

    def draft_meeting_connectors(self, meeting_id, output_dir, calendar=True, email=True, recipients=None):
        meeting = self.get_meeting(meeting_id)
        if not meeting:
            raise ValueError("meeting not found")
        out = self.security.resolve_path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        created = []
        if calendar:
            ics = out / f"meeting-{meeting_id}.ics"
            ics.write_text(self._build_ics(meeting), encoding="utf-8")
            created.append(self._record_connector_draft(meeting_id, "calendar_ics", ics, {"recipients": recipients or []}))
        if email:
            eml = out / f"meeting-{meeting_id}-followup.eml"
            eml.write_text(self._build_meeting_email(meeting, recipients or []), encoding="utf-8")
            created.append(self._record_connector_draft(meeting_id, "email_eml", eml, {"recipients": recipients or []}))
        return {"meeting_id": int(meeting_id), "drafts": created, "sent": False}

    def _record_connector_draft(self, meeting_id, connector_type, path, metadata):
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO meeting_connector_drafts
                    (meeting_id, connector_type, draft_path, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (int(meeting_id), connector_type, str(path), json.dumps(metadata, ensure_ascii=False)),
            )
            row = c.execute(
                "SELECT * FROM meeting_connector_drafts WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return self._decode_record(row, ("metadata",))

    # ---- RESEARCH PDF ----

    def import_research_pdf(self, file_path, title=""):
        path = self.security.resolve_path(file_path)
        if path.suffix.lower() != ".pdf" or not path.is_file():
            raise ValueError("a readable PDF file is required")
        text, extractor = self._extract_pdf_text(path)
        pages = text.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        digest = self._file_hash(path)
        ocr_pages = [
            index for index, page in enumerate(pages, 1)
            if len(page.strip()) < 20
        ]
        ocr_status = "ocr_required" if ocr_pages else "text_extracted"
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
                        json.dumps({
                            "extractor": extractor,
                            "ocr_status": ocr_status,
                            "ocr_pages": ocr_pages,
                        }, ensure_ascii=False),
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
                        json.dumps({
                            "extractor": extractor,
                            "ocr_status": ocr_status,
                            "ocr_pages": ocr_pages,
                        }, ensure_ascii=False),
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
            document["metadata"] = json.loads(document.get("metadata") or "{}")
        for page_number, chunk_index, chunk in knowledge_entries:
            self.store.add_knowledge(
                title=f"{title or path.stem} p.{page_number} #{chunk_index}",
                content=chunk,
                category="research_pdf",
                source=f"{path}#page={page_number}",
                confidence=0.9,
            )
        return document

    def validate_citations(self, citations):
        results = []
        with self.store._conn() as c:
            docs = {
                row["file_path"]: dict(row)
                for row in c.execute("SELECT * FROM research_documents").fetchall()
            }
            for citation in citations or []:
                raw = citation.get("source_ref") if isinstance(citation, dict) else str(citation)
                match = re.search(r"(.+?)#page=(\d+)", str(raw))
                valid = False
                reason = "citation must include #page=N"
                if match:
                    file_path, page = match.group(1), int(match.group(2))
                    doc = docs.get(str(Path(file_path).resolve(strict=False))) or docs.get(file_path)
                    if not doc:
                        reason = "document not imported"
                    elif page < 1 or page > int(doc["page_count"] or 0):
                        reason = "page out of range"
                    else:
                        valid, reason = True, "ok"
                results.append({"citation": raw, "valid": valid, "reason": reason})
        return {"valid": all(item["valid"] for item in results), "results": results}

    def research_compare_matrix(self, document_ids=None, query_terms=None):
        terms = [str(term).strip() for term in (query_terms or []) if str(term).strip()]
        with self.store._conn() as c:
            params = []
            where = ""
            if document_ids:
                ids = [int(item) for item in document_ids]
                where = "WHERE rd.id IN ({})".format(",".join("?" for _ in ids))
                params.extend(ids)
            docs = c.execute(f"SELECT * FROM research_documents rd {where} ORDER BY rd.id", params).fetchall()
            matrix = []
            for doc in docs:
                chunks = c.execute(
                    "SELECT content FROM research_chunks WHERE document_id=?",
                    (int(doc["id"]),),
                ).fetchall()
                text = "\n".join(row["content"] for row in chunks).lower()
                if not terms:
                    terms = sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", text)))[:8]
                matrix.append({
                    "document_id": int(doc["id"]),
                    "title": doc["title"],
                    "coverage": {term: text.count(term.lower()) for term in terms},
                })
        return {"terms": terms, "matrix": matrix}

    def create_repro_workflow(self, title, question="", steps=None, output_path=""):
        steps = steps or [
            "Record data provenance",
            "Run deterministic preprocessing",
            "Execute experiment script",
            "Export metrics and figures",
        ]
        manifest = {
            "title": str(title),
            "question": str(question or ""),
            "steps": steps,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": ["README.md", "experiment_plan.json", "notebooks/README.md"],
        }
        resolved_output = ""
        if output_path:
            out = self.security.resolve_path(output_path)
            if out.exists():
                raise ValueError("output_path already exists")
            out.mkdir(parents=True)
            (out / "notebooks").mkdir()
            (out / "README.md").write_text(
                f"# {title}\n\n## Question\n{question}\n\n## Reproduce\n" +
                "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps)) + "\n",
                encoding="utf-8",
            )
            (out / "experiment_plan.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (out / "notebooks" / "README.md").write_text("Place reproducible notebooks here.\n", encoding="utf-8")
            resolved_output = str(out)
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO research_repro_workflows
                    (title, question, output_path, manifest)
                VALUES (?, ?, ?, ?)
                """,
                (str(title), str(question or ""), resolved_output, json.dumps(manifest, ensure_ascii=False)),
            )
            row = c.execute(
                "SELECT * FROM research_repro_workflows WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            item = dict(row)
            item["manifest"] = json.loads(item["manifest"])
            return item

    def generate_research_learning_analysis(
        self,
        document_id=None,
        file_path="",
        title="",
        output_dir="",
        formats=None,
        depth=5,
        question_count=50,
        report_style="journal",
    ):
        """Generate an editable self-questioning paper study report."""
        formats = formats or ["markdown", "pdf"]
        formats = [str(item).lower() for item in formats]
        if not output_dir:
            raise ValueError("output_dir is required")
        out = self.security.resolve_path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        document = self._resolve_research_document(document_id, file_path, title)
        chunks = self._research_document_chunks(document["id"])
        if not chunks:
            raise ValueError("document has no extracted text chunks")
        pages = {}
        for chunk in chunks:
            pages.setdefault(int(chunk["page_number"]), []).append(chunk["content"])
        page_text = {page: "\n".join(parts) for page, parts in pages.items()}
        full_text = "\n".join(page_text[page] for page in sorted(page_text))
        max_depth = max(1, min(int(depth or 5), 5))
        max_questions = max(6, min(int(question_count or 50), 80))
        report_styles = {"journal", "learning_notes", "business_brief", "compact"}
        report_style = str(report_style or "journal").lower()
        if report_style not in report_styles:
            report_style = "journal"
        outline = self._paper_outline(full_text)
        topics = self._analysis_topics(outline, full_text, max(3, min(8, max_questions // max_depth)))
        questions = self._analysis_questions(topics, page_text, max_depth, max_questions)
        concepts = self._paper_concepts(full_text, limit=14)
        report = self._render_learning_analysis_markdown(document, outline, questions, concepts, max_depth, report_style)
        safe_name = self._safe_filename(f"{document['title']}_learning_analysis")
        markdown_path = ""
        pdf_path = ""
        if "markdown" in formats or "md" in formats:
            markdown = out / f"{safe_name}.md"
            markdown.write_text(report, encoding="utf-8")
            markdown_path = str(markdown)
        if "pdf" in formats:
            pdf = out / f"{safe_name}.pdf"
            self._write_learning_analysis_pdf(pdf, document["title"], report)
            pdf_path = str(pdf)
        metadata = {
            "formats": formats,
            "source_file": document["file_path"],
            "page_count": document["page_count"],
            "outline_count": len(outline),
            "concept_count": len(concepts),
            "mode": "deterministic_evidence_based",
            "report_style": report_style,
        }
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO research_analysis_reports
                    (document_id, title, output_dir, markdown_path, pdf_path, question_count, depth, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(document["id"]), document["title"], str(out), markdown_path, pdf_path,
                    len(questions), max_depth, json.dumps(metadata, ensure_ascii=False),
                ),
            )
            row = c.execute(
                "SELECT * FROM research_analysis_reports WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"] or "{}")
        return {"report": item, "document": document, "preview": report[:1200]}

    def _resolve_research_document(self, document_id=None, file_path="", title=""):
        with self.store._conn() as c:
            if document_id:
                row = c.execute(
                    "SELECT * FROM research_documents WHERE id=?",
                    (int(document_id),),
                ).fetchone()
                if not row:
                    raise ValueError("research document not found")
                return dict(row)
            if file_path:
                path = self.security.resolve_path(file_path)
                row = c.execute(
                    "SELECT * FROM research_documents WHERE file_path=?",
                    (str(path),),
                ).fetchone()
                if row:
                    return dict(row)
        if file_path:
            return self.import_research_pdf(file_path, title)
        raise ValueError("document_id or file_path is required")

    def _research_document_chunks(self, document_id):
        with self.store._conn() as c:
            return [dict(row) for row in c.execute(
                """
                SELECT page_number, chunk_index, content
                FROM research_chunks
                WHERE document_id=?
                ORDER BY page_number, chunk_index
                """,
                (int(document_id),),
            ).fetchall()]

    def _paper_outline(self, text):
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        outline = []
        for line in lines:
            compact = re.sub(r"\s+", " ", line)
            if len(compact) > 90:
                continue
            if self._is_outline_noise(compact):
                continue
            if re.match(r"^(\d+(\.\d+)*|[一二三四五六七八九十]+[、.．]|第.+[章节部分]|[A-Z][A-Za-z ]{4,})", compact):
                outline.append(compact)
            if len(outline) >= 18:
                break
        return outline or [line[:80] for line in lines[:8]]

    def _analysis_topics(self, outline, text, target_count):
        topics = []
        for item in outline:
            clean = re.sub(r"^[\d.．、\s]+", "", item).strip()
            if clean and len(clean) <= 55 and not self._is_outline_noise(clean) and clean not in topics:
                topics.append(clean)
            if len(topics) >= target_count:
                break
        for concept in self._paper_concepts(text, limit=target_count * 2):
            if concept not in topics:
                topics.append(concept)
            if len(topics) >= target_count:
                break
        return topics or ["研究问题", "方法框架", "实验设计"]

    def _analysis_questions(self, topics, page_text, depth, question_count):
        pages = sorted(page_text)
        questions = []
        templates = [
            "这篇论文围绕“{topic}”到底想解决什么核心问题？",
            "作者为什么认为“{topic}”是必要的，而不是可选优化？",
            "论文中支撑“{topic}”的关键方法、系统模块或假设是什么？",
            "如果从实验和证据角度追问，“{topic}”的结论由哪些结果支撑？",
            "继续深挖，“{topic}”还有哪些局限、适用边界和可复现风险？",
        ]
        cursor = 0
        while len(questions) < question_count and topics:
            for topic_index, topic in enumerate(topics, 1):
                for level in range(1, depth + 1):
                    if len(questions) >= question_count:
                        break
                    page = pages[(len(questions) + cursor) % len(pages)]
                    evidence = self._best_evidence_for_topic(page_text, topic, page)
                    template = templates[min(level - 1, len(templates) - 1)]
                    questions.append({
                        "topic_index": topic_index,
                        "topic": topic,
                        "level": level,
                        "question": template.format(topic=topic),
                        "answer": self._evidence_answer(topic, evidence, level),
                        "evidence": evidence,
                        "page": evidence["page"],
                    })
                if len(questions) >= question_count:
                    break
            cursor += 1
        return questions

    @staticmethod
    def _is_outline_noise(text):
        compact = str(text or "").strip()
        if not compact:
            return True
        lowered = compact.lower()
        if lowered in {"contents", "references", "acknowledgements"}:
            return True
        if re.fullmatch(r"第[一二三四五六七八九十]+部分[·：:].*", compact):
            return True
        if compact in {"总览", "关键概念名词表", "局限性与可改进方向"}:
            return True
        if re.fullmatch(r"\d+", compact):
            return True
        if re.search(r"\.{4,}", compact):
            return True
        if len(compact) <= 2:
            return True
        return False

    def _best_evidence_for_topic(self, page_text, topic, fallback_page):
        topic_terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", str(topic))[:4]]
        best = (0, fallback_page, page_text.get(fallback_page, ""))
        for page, text in page_text.items():
            lowered = text.lower()
            score = sum(lowered.count(term) for term in topic_terms)
            if score > best[0]:
                best = (score, page, text)
        sentences = re.split(r"(?<=[。！？.!?])\s+", best[2].strip())
        snippet = next((
            s.strip() for s in sentences
            if len(s.strip()) > 30
            and not self._is_outline_noise(s.strip())
            and not s.strip().lower().startswith("contents")
            and (not topic_terms or any(term in s.lower() for term in topic_terms))
        ), "")
        if not snippet:
            snippet = next((
                s.strip() for s in sentences
                if len(s.strip()) > 30
                and not self._is_outline_noise(s.strip())
                and not s.strip().lower().startswith("contents")
            ), best[2].strip()[:420])
        return {"page": best[1], "snippet": snippet[:520]}

    def _evidence_answer(self, topic, evidence, level):
        lead = [
            "先抓主线：",
            "继续追问动机：",
            "落到机制层：",
            "回到证据链：",
            "最后检查边界：",
        ][min(level - 1, 4)]
        return (
            f"{lead}围绕“{topic}”，报告应从论文原文证据出发解释其角色。"
            f"当前可引用第 {evidence['page']} 页片段：{evidence['snippet']}"
        )

    def _paper_concepts(self, text, limit=12):
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,8}", str(text))
        stop = {
            "the", "and", "with", "from", "this", "that", "contents",
            "研究", "论文", "方法", "系统", "结果", "总览", "主题", "解析报告",
        }
        counts = {}
        for word in words:
            key = word.strip()
            if key.lower() in stop or len(key) < 2:
                continue
            counts[key] = counts.get(key, 0) + 1
        return [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    def _paper_quality_insights(self, document, outline, questions, concepts):
        chunks = self._research_document_chunks(document["id"])
        text = "\n".join(chunk["content"] for chunk in chunks)
        lowered = text.lower()
        signals = {
            "method": ["method", "approach", "framework", "algorithm", "model", "architecture", "pipeline"],
            "experiment": ["experiment", "evaluation", "benchmark", "dataset", "metric", "result", "ablation"],
            "reproducibility": ["code", "implementation", "parameter", "hyperparameter", "environment", "github", "appendix"],
            "limitation": ["limitation", "future work", "threat", "risk", "failure", "error"],
        }
        signal_rows = []
        for name, terms in signals.items():
            hits = sum(lowered.count(term) for term in terms)
            signal_rows.append((name, hits, "strong" if hits >= 3 else "partial" if hits else "missing"))
        cited_pages = sorted({q["page"] for q in questions})
        evidence_density = round(len(questions) / max(len(cited_pages), 1), 2)
        top_concepts = ", ".join(concepts[:8]) or "not enough terms"
        outline_preview = " / ".join(outline[:5]) or "no explicit outline"
        return [
            "",
            "## Paper Intelligence Addendum",
            "",
            "### Contribution Reading",
            f"- Claimed focus: {self._one_sentence_summary(questions)}",
            f"- Outline signal: {outline_preview}",
            f"- Key concept cluster: {top_concepts}",
            "",
            "### Method And Evidence Signals",
            *[f"- {name}: {status} ({hits} keyword hits)" for name, hits, status in signal_rows],
            f"- Evidence density: {len(questions)} question nodes over {max(len(cited_pages), 1)} cited pages, about {evidence_density} nodes/page.",
            "",
            "### Reproducibility Checklist",
            "- Problem statement: verify that the target task, inputs, and expected outputs are explicit.",
            "- Method mechanism: trace each module to a cited sentence, figure, table, or experiment.",
            "- Evaluation protocol: confirm dataset, metric, baseline, ablation, and failure case coverage.",
            "- Rebuild plan: convert the strongest L3-L5 questions into implementation tasks before coding.",
            "",
            "### Reading Verdict",
            "- Treat strong signal sections as the first pass for presentation slides.",
            "- Treat missing signal sections as follow-up questions for manual reading or model-assisted re-query.",
        ]

    def _render_learning_analysis_markdown(self, document, outline, questions, concepts, depth, report_style="journal"):
        if report_style != "journal":
            return self._render_styled_learning_analysis_markdown(document, outline, questions, concepts, depth, report_style)
        lines = [
            f"# 《{document['title']}》论文深度解析报告",
            "",
            f"本报告由 ClawOS 论文学习工作流生成：先抽取论文结构，再以自我提问方式逐层追问，共形成 {len(questions)} 个问答节点（深度至 L{depth}）。",
            "",
            "## 第一部分 · 总览",
            "",
            "### 1. 论文一句话概述",
            self._one_sentence_summary(questions),
            "",
            "### 2. 论文框架目录",
        ]
        lines.extend(f"- {item}" for item in outline[:18])
        lines.extend([
            "",
            "### 3. 学习时必须回答的核心问题",
            "- 论文解决的对象、痛点和应用场景是什么？",
            "- 方法框架由哪些模块组成，模块之间的数据流是什么？",
            "- 作者用哪些实验、指标或案例支撑结论？",
            "- 哪些结论是强证据，哪些只是合理推断？",
            "- 如果要复现或改进，最先卡住的依赖是什么？",
            "",
            "## 第二部分 · 主题深度解析（按追问分支逐层展开）",
        ])
        grouped = {}
        for question in questions:
            grouped.setdefault(question["topic"], []).append(question)
        for idx, (topic, items) in enumerate(grouped.items(), 1):
            lines.extend(["", f"### 主题 {idx}：{topic}"])
            for item in items:
                lines.extend([
                    "",
                    f"#### L{item['level']} 自问：{item['question']}",
                    "",
                    item["answer"],
                    "",
                    f"证据：第 {item['page']} 页。",
                ])
        lines.extend([
            "",
            "## 第三部分 · 概念表、局限与学习建议",
            "",
            "### 关键概念名词表",
        ])
        lines.extend(f"- **{concept}**：需要结合论文上下文解释定义、作用、输入输出和与其他概念的关系。" for concept in concepts)
        lines.extend([
            "",
            "### 局限性与可改进方向",
            "- 检查论文是否给出足够的消融实验、误差分析和失败案例。",
            "- 检查数据集、硬件环境、超参数和评价指标是否足以复现。",
            "- 区分论文明确声明、实验支持结论和本报告自动生成的学习性推断。",
            "",
            "### 系统性学习建议",
            "- 第一遍只读标题、摘要、图表和结论，建立问题地图。",
            "- 第二遍按本报告问题树逐项回到原文定位证据。",
            "- 第三遍把每个 L4/L5 问题改写成自己的复现任务或讨论题。",
            "- 最后输出一页纸复盘：贡献、证据、局限、可复现计划。",
        ])
        lines.extend(self._paper_quality_insights(document, outline, questions, concepts))
        return "\n".join(lines) + "\n"

    def _render_styled_learning_analysis_markdown(self, document, outline, questions, concepts, depth, report_style):
        title = document["title"]
        summary = self._one_sentence_summary(questions)
        topics = []
        seen = set()
        for question in questions:
            topic = str(question.get("topic") or "General")
            if topic not in seen:
                topics.append(topic)
                seen.add(topic)
        cited_pages = sorted({int(q.get("page") or 1) for q in questions})
        first_questions = questions[: min(len(questions), 8)]
        concept_line = ", ".join(concepts[:10]) or "No dominant concepts detected"
        style_titles = {
            "learning_notes": "Learning Notes",
            "business_brief": "Business Brief",
            "compact": "Compact Report",
        }
        lines = [
            f"# {title} - {style_titles.get(report_style, 'Learning Report')}",
            "",
            f"Source pages: {len(cited_pages)} cited pages. Depth: L{depth}. Question nodes: {len(questions)}.",
            "",
        ]
        if report_style == "learning_notes":
            lines.extend([
                "## Learning Map",
                summary,
                "",
                "## Core Concepts",
                *[f"- {concept}" for concept in concepts[:12]],
                "",
                "## Guided Notes",
            ])
            for topic in topics[:8]:
                related = [q for q in questions if q.get("topic") == topic][:3]
                lines.extend(["", f"### {topic}"])
                for item in related:
                    lines.extend([
                        f"- Q{item['level']}: {item['question']}",
                        f"  Evidence: page {item['page']}. {item['answer']}",
                    ])
            lines.extend([
                "",
                "## Self Check",
                *[f"- Explain {q['topic']} without looking at the source, then verify page {q['page']}." for q in first_questions[:6]],
                "",
                "## Next Study Actions",
                "- Turn weak concepts into flashcards.",
                "- Re-read the cited pages before summarizing from memory.",
                "- Save unresolved questions back into the knowledge base.",
            ])
        elif report_style == "business_brief":
            lines.extend([
                "## Decision Snapshot",
                f"- Main point: {summary}",
                f"- Evidence base: {len(questions)} extracted question/evidence nodes across {len(cited_pages)} pages.",
                f"- Concept cluster: {concept_line}",
                "",
                "## Value And Use Cases",
                *[f"- {topic}" for topic in topics[:6]],
                "",
                "## Evidence To Cite",
                *[f"- Page {q['page']}: {q['answer']}" for q in first_questions[:5]],
                "",
                "## Risks And Open Questions",
                "- Validate whether the paper's assumptions match the target user, market, or deployment context.",
                "- Separate experimentally supported claims from plausible but untested extensions.",
                "- Check reproducibility before using the result as a product or investment claim.",
                "",
                "## Recommended Next Moves",
                "- Convert the strongest claim into one slide or one product requirement.",
                "- Ask follow-up questions against the cited pages before external sharing.",
            ])
        else:
            lines.extend([
                "## One Page Summary",
                summary,
                "",
                "## Key Points",
                *[f"- {topic}" for topic in topics[:5]],
                "",
                "## Evidence",
                *[f"- Page {q['page']}: {q['question']}" for q in first_questions[:6]],
                "",
                "## Concepts",
                concept_line,
                "",
                "## Actions",
                "- Keep the Markdown report as the editable source.",
                "- Use the PDF for review or sharing.",
                "- Save this report back to the knowledge base for later Q&A.",
            ])
        return "\n".join(lines) + "\n"

    def _one_sentence_summary(self, questions):
        if not questions:
            return "本文围绕一个具体研究问题提出方法并通过实验验证。"
        first = questions[0]
        return f"本文围绕“{first['topic']}”展开，核心学习路径应从问题动机、方法机制、实验支撑与边界局限四层理解。"

    def _write_learning_analysis_pdf(self, path, title, markdown):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.pdfbase.ttfonts import TTFont
        except Exception as exc:  # pragma: no cover - depends on local optional package
            raise RuntimeError(f"reportlab is required to generate PDF: {exc}") from exc
        font_name = "STSong-Light"
        for font_path in (
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/msyhbd.ttc"),
            Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
            Path("C:/Windows/Fonts/simsunb.ttf"),
            Path("C:/Windows/Fonts/simhei.ttf"),
        ):
            if font_path.is_file():
                font_name = "ClawOSCJK"
                pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
                break
        else:
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        page_width, page_height = A4
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=24 * mm,
            bottomMargin=22 * mm,
            title=title,
            author="ClawOS",
        )
        sample = getSampleStyleSheet()
        palette = {
            "ink": colors.HexColor("#07111f"),
            "muted": colors.HexColor("#172033"),
            "rule": colors.HexColor("#7f8ea3"),
            "accent": colors.HexColor("#0b3344"),
            "soft": colors.HexColor("#edf3f6"),
        }
        styles = {
            "Title": ParagraphStyle(
                "ClawOSTitle",
                parent=sample["Title"],
                fontName=font_name,
                fontSize=22,
                leading=29,
                textColor=palette["ink"],
                alignment=1,
                spaceAfter=12,
            ),
            "Kicker": ParagraphStyle(
                "ClawOSKicker",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=9,
                leading=13,
                textColor=palette["accent"],
                alignment=1,
                uppercase=True,
                spaceAfter=16,
            ),
            "Body": ParagraphStyle(
                "ClawOSBody",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=10.8,
                leading=17.2,
                firstLineIndent=12,
                textColor=palette["ink"],
                spaceAfter=5,
            ),
            "Lead": ParagraphStyle(
                "ClawOSLead",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=11.4,
                leading=18.4,
                textColor=palette["muted"],
                alignment=1,
                spaceAfter=16,
            ),
            "Heading1": ParagraphStyle(
                "ClawOSHeading1",
                parent=sample["Heading1"],
                fontName=font_name,
                fontSize=15.5,
                leading=21.5,
                textColor=palette["accent"],
                spaceBefore=14,
                spaceAfter=8,
                keepWithNext=True,
            ),
            "Heading2": ParagraphStyle(
                "ClawOSHeading2",
                parent=sample["Heading2"],
                fontName=font_name,
                fontSize=13,
                leading=18.5,
                textColor=palette["ink"],
                spaceBefore=10,
                spaceAfter=6,
                keepWithNext=True,
            ),
            "Heading3": ParagraphStyle(
                "ClawOSHeading3",
                parent=sample["Heading3"],
                fontName=font_name,
                fontSize=10.8,
                leading=16,
                textColor=palette["accent"],
                spaceBefore=8,
                spaceAfter=4,
                keepWithNext=True,
            ),
            "Bullet": ParagraphStyle(
                "ClawOSBullet",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=10.4,
                leading=16,
                leftIndent=13,
                firstLineIndent=-8,
                textColor=palette["ink"],
                bulletIndent=0,
                spaceAfter=4,
            ),
            "Evidence": ParagraphStyle(
                "ClawOSEvidence",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=9.8,
                leading=14.6,
                leftIndent=10,
                rightIndent=10,
                borderColor=palette["rule"],
                borderWidth=0.9,
                borderPadding=6,
                backColor=palette["soft"],
                textColor=palette["ink"],
                spaceBefore=4,
                spaceAfter=8,
            ),
        }

        def header_footer(canvas, _doc):
            canvas.saveState()
            canvas.setStrokeColor(palette["rule"])
            canvas.setLineWidth(0.65)
            canvas.line(doc.leftMargin, page_height - 16 * mm, page_width - doc.rightMargin, page_height - 16 * mm)
            canvas.setFont(font_name, 8.8)
            canvas.setFillColor(palette["muted"])
            canvas.drawString(doc.leftMargin, page_height - 12 * mm, "ClawOS Research Learning Analysis")
            canvas.drawRightString(page_width - doc.rightMargin, page_height - 12 * mm, str(title)[:70])
            canvas.line(doc.leftMargin, 14 * mm, page_width - doc.rightMargin, 14 * mm)
            canvas.drawString(doc.leftMargin, 9 * mm, datetime.now(timezone.utc).strftime("Generated %Y-%m-%d UTC"))
            canvas.drawRightString(page_width - doc.rightMargin, 9 * mm, f"Page {canvas.getPageNumber()}")
            canvas.restoreState()

        def md_inline(text):
            escaped = xml_escape(str(text))
            return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)

        story = []
        story.append(Spacer(1, 10))
        story.append(Paragraph("Journal-style paper reading dossier", styles["Kicker"]))
        story.append(Paragraph(md_inline(title), styles["Title"]))
        story.append(HRFlowable(width="45%", thickness=1.0, color=palette["accent"], spaceBefore=2, spaceAfter=14, hAlign="CENTER"))
        story.append(Paragraph("Structured parsing, self-questioning, evidence tracing, concepts, limits, and follow-up reading plan.", styles["Lead"]))
        story.append(PageBreak())
        for raw in markdown.splitlines():
            line = raw.strip()
            if not line:
                story.append(Spacer(1, 5))
                continue
            if line.startswith("# "):
                story.append(Paragraph(md_inline(line[2:]), styles["Heading1"]))
                story.append(HRFlowable(width="100%", thickness=0.6, color=palette["rule"], spaceBefore=0, spaceAfter=7))
            elif line.startswith("## "):
                story.append(Paragraph(md_inline(line[3:]), styles["Heading1"]))
            elif line.startswith("### "):
                story.append(Paragraph(md_inline(line[4:]), styles["Heading2"]))
            elif line.startswith("#### "):
                story.append(Paragraph(md_inline(line[5:]), styles["Heading3"]))
            elif line.startswith("- "):
                story.append(Paragraph(md_inline(line[2:]), styles["Bullet"], bulletText="-"))
            elif line.startswith("璇佹嵁") or line.startswith("证据") or line.lower().startswith("evidence"):
                story.append(KeepTogether([Paragraph(md_inline(line), styles["Evidence"])]))
            else:
                story.append(Paragraph(md_inline(line), styles["Body"]))
        doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)

    @staticmethod
    def _safe_filename(name):
        safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(name)).strip("._")
        return safe[:80] or f"report_{uuid.uuid4().hex[:8]}"

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

    def create_git_change_request(self, repo_path, message, files=None, created_by="user"):
        plan = self.prepare_commit_plan(repo_path, message, files)
        repo = Path(plan["repo"])
        selected = plan["files"]
        diff_args = ["diff", "--binary", "--", *selected] if selected else ["diff", "--binary"]
        diff_preview = self._git(repo, *diff_args)
        checkpoint = self._git(repo, "rev-parse", "HEAD").strip()
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO git_change_requests
                    (repo_path, branch, message, files, diff_preview, checkpoint_ref, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan["repo"], plan["branch"], plan["message"],
                    json.dumps(selected, ensure_ascii=False), diff_preview,
                    checkpoint, str(created_by or "user"),
                ),
            )
            row = c.execute("SELECT * FROM git_change_requests WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return self._git_request_from_row(row)

    def approve_git_change_request(self, request_id, approved_by="user"):
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)).fetchone()
            if not row:
                raise ValueError("change request not found")
            request = self._git_request_from_row(row)
            if request["status"] != "pending_approval":
                raise ValueError("change request is not pending approval")
        repo = self.security.resolve_path(request["repo_path"])
        self._git(repo, "add", "--", *request["files"])
        self._git(repo, "commit", "-m", request["message"])
        after = self._git(repo, "rev-parse", "HEAD").strip()
        with self.store._conn() as c:
            c.execute(
                """
                UPDATE git_change_requests
                SET status='committed', approved_by=?, after_ref=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (str(approved_by or "user"), after, int(request_id)),
            )
            return self._git_request_from_row(c.execute(
                "SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)
            ).fetchone())

    def rollback_git_change_request(self, request_id, actor_id="user"):
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)).fetchone()
            if not row:
                raise ValueError("change request not found")
            request = self._git_request_from_row(row)
            if request["status"] != "committed" or not request["after_ref"]:
                raise ValueError("only committed change requests can be rolled back")
        repo = self.security.resolve_path(request["repo_path"])
        self._git(repo, "revert", "--no-edit", request["after_ref"])
        with self.store._conn() as c:
            c.execute(
                """
                UPDATE git_change_requests
                SET status='rolled_back', approved_by=approved_by || '; rollback:' || ?, updated_at=datetime('now')
                WHERE id=?
                """,
                (str(actor_id or "user"), int(request_id)),
            )
            return self._git_request_from_row(c.execute(
                "SELECT * FROM git_change_requests WHERE id=?", (int(request_id),)
            ).fetchone())

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
        if executable:
            proc = subprocess.run(
                [executable, "-layout", str(path), "-"],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:500])
            return proc.stdout.decode("utf-8", errors="replace"), "pdftotext"
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pdftotext or pypdf is required for local PDF extraction") from exc
        reader = PdfReader(str(path))
        return "\f".join((page.extract_text() or "") for page in reader.pages), "pypdf"

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
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git command failed")
        return proc.stdout

    @staticmethod
    def _parse_speaker_turns(transcript):
        turns = []
        pattern = re.compile(r"^(?:\[(?P<time>[^\]]+)\]\s*)?(?P<speaker>[^:：\n]{1,40})[:：]\s*(?P<text>.+)$")
        for line in str(transcript or "").splitlines():
            match = pattern.match(line.strip())
            if match:
                speaker = match.group("speaker").strip()
                if speaker.lower() not in {"decision", "risk", "action"} and speaker not in {"决定", "风险", "行动项", "待办"}:
                    turns.append({
                        "time": match.group("time") or "",
                        "speaker": speaker,
                        "text": match.group("text").strip(),
                    })
        return turns

    @staticmethod
    def _build_ics(meeting):
        uid = f"clawos-meeting-{meeting['id']}@local"
        date = re.sub(r"[^0-9]", "", meeting.get("meeting_date") or "")[:8] or datetime.now(timezone.utc).strftime("%Y%m%d")
        return "\n".join([
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//ClawOS//Meeting Draft//CN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART;VALUE=DATE:{date}",
            f"SUMMARY:{meeting['title']}",
            f"DESCRIPTION:{meeting.get('summary','')}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ])

    @staticmethod
    def _build_meeting_email(meeting, recipients):
        actions = "\n".join(
            f"- {a['description']} ({a.get('owner') or 'unassigned'}, {a.get('due_date') or 'no due date'})"
            for a in meeting.get("actions", [])
        ) or "- No action items"
        return "\n".join([
            f"To: {', '.join(recipients)}",
            f"Subject: Meeting follow-up: {meeting['title']}",
            "",
            meeting.get("summary") or meeting["title"],
            "",
            "Actions:",
            actions,
            "",
        ])

    @staticmethod
    def _decode_record(row, json_keys):
        item = dict(row)
        for key in json_keys:
            item[key] = json.loads(item.get(key) or ("[]" if key == "diarization" else "{}"))
        return item

    @staticmethod
    def _git_request_from_row(row):
        item = dict(row)
        item["files"] = json.loads(item.get("files") or "[]")
        return item

    @staticmethod
    def _template_from_row(row):
        item = dict(row)
        item["files"] = json.loads(item.get("files") or "{}")
        return item
