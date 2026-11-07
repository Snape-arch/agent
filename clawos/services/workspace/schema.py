"""Workspace schema and compatible column upgrades."""
from __future__ import annotations


class WorkspaceSchema:
    def __init__(self, store):
        self.store = store

    def initialize(self):
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
