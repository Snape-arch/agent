"""MemoryStore — SQLite-backed persistent memory for ClawOS.

TABLES:
  profiles       — key-value profile info (name, interests, skills, etc.)
  preferences    — user preferences (style, tools, communication, risk)
  conversations  — multi-turn conversation history per session
  projects       — project tracking (goals, progress, team)
  experiences    — success/failure cases for reflection
"""

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MemoryStore:
    """Thread-safe SQLite memory store."""

    def __init__(self, db_path: str = ""):
        self._db_path = db_path or str(Path(__file__).parent.parent / "memoryos.db")
        self._lock = threading.Lock()
        self._init_db()

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = sqlite3.connect(self._db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'general',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(category, key)
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'general',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(category, key)
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('system','user','assistant','tool')),
                    content TEXT NOT NULL,
                    tool_calls TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id, created_at);
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT DEFAULT '',
                    goals TEXT DEFAULT '[]',
                    progress TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    team_members TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('success','failure','partial')),
                    lesson TEXT DEFAULT '',
                    context TEXT DEFAULT '',
                    solution TEXT DEFAULT '',
                    tags TEXT DEFAULT '[]',
                    importance REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'domain',
                    title TEXT NOT NULL, content TEXT NOT NULL,
                    source TEXT DEFAULT '', tags TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 0.5, access_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    filename TEXT DEFAULT '',
                    file_path TEXT DEFAULT '',
                    file_hash TEXT DEFAULT '',
                    mime_type TEXT DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'domain',
                    extractor TEXT DEFAULT '',
                    status TEXT DEFAULT 'ready',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    citation TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_document_chunks_doc ON document_chunks(document_id, chunk_index);
                CREATE TABLE IF NOT EXISTS context_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    task_description TEXT DEFAULT '',
                    active_tools TEXT DEFAULT '[]',
                    environment TEXT DEFAULT '',
                    user_intent TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS skill_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    usage_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
                    avg_duration_ms REAL DEFAULT 0, last_used TEXT DEFAULT '',
                    feedback TEXT DEFAULT '', quality_score REAL DEFAULT 0.5
                );
                CREATE TABLE IF NOT EXISTS tool_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments TEXT DEFAULT '{}',
                    result TEXT DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'success',
                    duration_ms REAL DEFAULT 0,
                    requires_confirmation INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_tool_exec_session ON tool_executions(session_id, id);
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    source TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    idempotency_key TEXT DEFAULT '',
                    retry_of INTEGER,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    cancellation_requested INTEGER NOT NULL DEFAULT 0,
                    resume_state TEXT DEFAULT '',
                    started_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id, id);
                CREATE TABLE IF NOT EXISTS task_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    step_type TEXT NOT NULL DEFAULT 'tool',
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    input_data TEXT DEFAULT '{}',
                    output_data TEXT DEFAULT '{}',
                    error TEXT DEFAULT '',
                    started_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT DEFAULT '',
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id, id);
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    step_id INTEGER,
                    event_type TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    data TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY(step_id) REFERENCES task_steps(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id, id);
                CREATE TABLE IF NOT EXISTS mtclaw_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    route_status TEXT NOT NULL,
                    provider_url TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    duration_ms REAL DEFAULT 0,
                    tool_history TEXT DEFAULT '[]',
                    error TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_mtclaw_trace_session ON mtclaw_traces(session_id, id);
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_type TEXT NOT NULL CHECK(memory_type IN ('profile','preference','project','experience','skill')),
                    category TEXT NOT NULL DEFAULT 'general',
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.5,
                    enabled INTEGER DEFAULT 1,
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    current_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(memory_type, category, key)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_lookup ON memories(memory_type, enabled, updated_at);
                CREATE TABLE IF NOT EXISTS memory_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.5,
                    enabled INTEGER DEFAULT 1,
                    change_type TEXT NOT NULL DEFAULT 'update',
                    changed_by TEXT NOT NULL DEFAULT 'system',
                    change_reason TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    UNIQUE(memory_id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_versions_memory ON memory_versions(memory_id, version DESC);
                CREATE TABLE IF NOT EXISTS memory_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    version_id INTEGER,
                    evidence_type TEXT NOT NULL DEFAULT 'manual',
                    source_ref TEXT DEFAULT '',
                    excerpt TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY(version_id) REFERENCES memory_versions(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memory_evidence_memory ON memory_evidence(memory_id, id DESC);
                CREATE TABLE IF NOT EXISTS memory_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    existing_value TEXT NOT NULL,
                    candidate_value TEXT NOT NULL,
                    conflict_type TEXT NOT NULL DEFAULT 'value_changed',
                    source TEXT DEFAULT '',
                    evidence TEXT DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    resolution TEXT DEFAULT '',
                    submitted_by TEXT NOT NULL DEFAULT 'system',
                    reviewed_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    resolved_at TEXT DEFAULT '',
                    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_conflicts_status ON memory_conflicts(status, id DESC);
                CREATE TABLE IF NOT EXISTS memory_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    conflict_id INTEGER,
                    review_type TEXT NOT NULL DEFAULT 'conflict',
                    status TEXT NOT NULL DEFAULT 'pending',
                    submitted_by TEXT NOT NULL DEFAULT 'system',
                    reviewed_by TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    resolved_at TEXT DEFAULT '',
                    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY(conflict_id) REFERENCES memory_conflicts(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_memory_reviews_status ON memory_reviews(status, id DESC);
                CREATE TABLE IF NOT EXISTS memory_acl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id INTEGER NOT NULL,
                    principal_type TEXT NOT NULL CHECK(principal_type IN ('user','role','workspace')),
                    principal_id TEXT NOT NULL,
                    permission TEXT NOT NULL CHECK(permission IN ('read','write','review','admin')),
                    granted_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    UNIQUE(memory_id, principal_type, principal_id, permission)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_acl_memory ON memory_acl(memory_id);
                CREATE TABLE IF NOT EXISTS retrieval_evaluation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL DEFAULT 'memory-retrieval',
                    top_k INTEGER NOT NULL DEFAULT 5,
                    case_count INTEGER NOT NULL DEFAULT 0,
                    metrics TEXT NOT NULL DEFAULT '{}',
                    cases TEXT NOT NULL DEFAULT '[]',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS reflection_cards (
                    id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    trigger_type TEXT NOT NULL DEFAULT 'user_triggered',
                    outcome TEXT NOT NULL DEFAULT 'partial',
                    outcome_detail TEXT NOT NULL DEFAULT '{}',
                    root_cause TEXT DEFAULT '',
                    failure_category TEXT DEFAULT '',
                    insights TEXT NOT NULL DEFAULT '[]',
                    patterns TEXT NOT NULL DEFAULT '[]',
                    trajectory TEXT NOT NULL DEFAULT '{}',
                    evidence TEXT NOT NULL DEFAULT '[]',
                    user_feedback TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_reflection_cards_session ON reflection_cards(session_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS reflection_improvements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    card_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT DEFAULT '',
                    action_type TEXT NOT NULL DEFAULT 'policy',
                    target_type TEXT NOT NULL DEFAULT 'agent_policy',
                    target_key TEXT NOT NULL,
                    candidate_payload TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'proposed',
                    baseline_metrics TEXT NOT NULL DEFAULT '{}',
                    candidate_metrics TEXT NOT NULL DEFAULT '{}',
                    regression_result TEXT NOT NULL DEFAULT '{}',
                    rollback_payload TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    published_at TEXT DEFAULT '',
                    rolled_back_at TEXT DEFAULT '',
                    FOREIGN KEY(card_id) REFERENCES reflection_cards(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_reflection_improvements_status ON reflection_improvements(status, id DESC);
                CREATE TABLE IF NOT EXISTS reflection_improvement_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    improvement_id INTEGER NOT NULL,
                    from_status TEXT DEFAULT '',
                    to_status TEXT NOT NULL,
                    actor_id TEXT NOT NULL DEFAULT 'system',
                    reason TEXT DEFAULT '',
                    data TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(improvement_id) REFERENCES reflection_improvements(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_reflection_events_improvement ON reflection_improvement_events(improvement_id, id);
                CREATE TABLE IF NOT EXISTS runtime_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    version INTEGER NOT NULL DEFAULT 1,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_by TEXT NOT NULL DEFAULT 'system',
                    updated_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(target_type, target_key)
                );
                CREATE TABLE IF NOT EXISTS self_evolution_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL DEFAULT 'Self-evolution run',
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    baseline_payload TEXT NOT NULL DEFAULT '{}',
                    candidate_payload TEXT NOT NULL DEFAULT '{}',
                    benchmarks TEXT NOT NULL DEFAULT '{}',
                    gate_result TEXT NOT NULL DEFAULT '{}',
                    conclusion TEXT NOT NULL DEFAULT '',
                    publish_decision TEXT NOT NULL DEFAULT 'pending',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    release_stage TEXT NOT NULL DEFAULT 'candidate',
                    traffic_percent REAL NOT NULL DEFAULT 0,
                    quality_signals TEXT NOT NULL DEFAULT '{}',
                    rollback_payload TEXT NOT NULL DEFAULT '{}',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    published_by TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    published_at TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_self_evolution_runs_status ON self_evolution_runs(status, id DESC);
                CREATE TABLE IF NOT EXISTS self_evolution_quality_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    signal_type TEXT NOT NULL,
                    value REAL NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(run_id) REFERENCES self_evolution_runs(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_self_evolution_signals_run ON self_evolution_quality_signals(run_id, id DESC);
                CREATE TABLE IF NOT EXISTS policy_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    optimizer_type TEXT NOT NULL DEFAULT 'contextual_ucb',
                    exploration_rate REAL NOT NULL DEFAULT 0.1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS policy_arms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    arm_type TEXT NOT NULL CHECK(arm_type IN ('tool','agent','prompt','workflow')),
                    payload TEXT NOT NULL DEFAULT '{}',
                    contexts TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    pull_count INTEGER NOT NULL DEFAULT 0,
                    reward_sum REAL NOT NULL DEFAULT 0,
                    reward_sq_sum REAL NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(group_id) REFERENCES policy_groups(id) ON DELETE CASCADE,
                    UNIQUE(group_id, name)
                );
                CREATE INDEX IF NOT EXISTS idx_policy_arms_group ON policy_arms(group_id, status);
                CREATE TABLE IF NOT EXISTS policy_selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    arm_id INTEGER NOT NULL,
                    context TEXT NOT NULL DEFAULT '{}',
                    score REAL NOT NULL DEFAULT 0,
                    exploration INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'selected',
                    task_id INTEGER,
                    session_id TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(group_id) REFERENCES policy_groups(id) ON DELETE CASCADE,
                    FOREIGN KEY(arm_id) REFERENCES policy_arms(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_policy_selections_group ON policy_selections(group_id, id DESC);
                CREATE TABLE IF NOT EXISTS policy_rewards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    selection_id INTEGER NOT NULL UNIQUE,
                    success REAL NOT NULL DEFAULT 0,
                    satisfaction REAL NOT NULL DEFAULT 0,
                    latency_cost REAL NOT NULL DEFAULT 0,
                    resource_cost REAL NOT NULL DEFAULT 0,
                    reward REAL NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(selection_id) REFERENCES policy_selections(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS policy_promotions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    arm_id INTEGER NOT NULL,
                    target_type TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    previous_payload TEXT NOT NULL DEFAULT '{}',
                    previous_existed INTEGER NOT NULL DEFAULT 0,
                    promoted_payload TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    promoted_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    rolled_back_at TEXT DEFAULT '',
                    FOREIGN KEY(group_id) REFERENCES policy_groups(id) ON DELETE CASCADE,
                    FOREIGN KEY(arm_id) REFERENCES policy_arms(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS agent_trajectories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL UNIQUE,
                    session_id TEXT NOT NULL DEFAULT '',
                    scenario TEXT NOT NULL DEFAULT 'general',
                    status TEXT NOT NULL DEFAULT 'running',
                    task_context TEXT NOT NULL DEFAULT '{}',
                    user_context TEXT NOT NULL DEFAULT '{}',
                    environment_state TEXT NOT NULL DEFAULT '{}',
                    outcome TEXT NOT NULL DEFAULT '{}',
                    reward_components TEXT NOT NULL DEFAULT '{}',
                    total_reward REAL,
                    policy_version TEXT DEFAULT '',
                    data_version TEXT NOT NULL DEFAULT 'clawos.trajectory.v1',
                    created_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT DEFAULT '',
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_agent_trajectories_status
                    ON agent_trajectories(status, id DESC);
                CREATE TABLE IF NOT EXISTS agent_trajectory_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trajectory_id INTEGER NOT NULL,
                    step_index INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT '{}',
                    action_type TEXT NOT NULL DEFAULT 'workflow',
                    action_name TEXT NOT NULL DEFAULT '',
                    action_payload TEXT NOT NULL DEFAULT '{}',
                    observation TEXT NOT NULL DEFAULT '{}',
                    reward_components TEXT NOT NULL DEFAULT '{}',
                    step_reward REAL,
                    discounted_return REAL,
                    policy_selection_id INTEGER,
                    behavior_propensity REAL NOT NULL DEFAULT 1,
                    safety_violation INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    completed_at TEXT DEFAULT '',
                    FOREIGN KEY(trajectory_id) REFERENCES agent_trajectories(id) ON DELETE CASCADE,
                    FOREIGN KEY(policy_selection_id) REFERENCES policy_selections(id) ON DELETE SET NULL,
                    UNIQUE(trajectory_id, step_index)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_trajectory_steps_trajectory
                    ON agent_trajectory_steps(trajectory_id, step_index);
                CREATE INDEX IF NOT EXISTS idx_agent_trajectory_steps_selection
                    ON agent_trajectory_steps(policy_selection_id);
                CREATE TABLE IF NOT EXISTS agent_preference_pairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    task_context TEXT NOT NULL DEFAULT '{}',
                    chosen TEXT NOT NULL DEFAULT '{}',
                    rejected TEXT NOT NULL DEFAULT '{}',
                    chosen_trajectory_id INTEGER,
                    rejected_trajectory_id INTEGER,
                    source TEXT NOT NULL DEFAULT 'explicit_user',
                    confidence REAL NOT NULL DEFAULT 1,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(chosen_trajectory_id) REFERENCES agent_trajectories(id) ON DELETE SET NULL,
                    FOREIGN KEY(rejected_trajectory_id) REFERENCES agent_trajectories(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_preference_pairs_owner
                    ON agent_preference_pairs(owner_id, id DESC);
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    trajectory_id INTEGER,
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    signal_type TEXT NOT NULL,
                    score REAL,
                    reason_category TEXT NOT NULL DEFAULT '',
                    correction TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    explicit INTEGER NOT NULL DEFAULT 1,
                    idempotency_key TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY(trajectory_id) REFERENCES agent_trajectories(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_feedback_task
                    ON agent_feedback(task_id, id DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_feedback_idempotency
                    ON agent_feedback(idempotency_key)
                    WHERE idempotency_key<>'';
                CREATE TABLE IF NOT EXISTS reward_calibrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    weights TEXT NOT NULL DEFAULT '{}',
                    training_metrics TEXT NOT NULL DEFAULT '{}',
                    evaluation_metrics TEXT NOT NULL DEFAULT '{}',
                    thresholds TEXT NOT NULL DEFAULT '{}',
                    data_digest TEXT NOT NULL DEFAULT '',
                    trained_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    evaluated_at TEXT DEFAULT '',
                    activated_at TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_reward_calibrations_status
                    ON reward_calibrations(status, version DESC);
                CREATE TABLE IF NOT EXISTS preference_ranker_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    feature_dim INTEGER NOT NULL DEFAULT 128,
                    weights TEXT NOT NULL DEFAULT '[]',
                    training_metrics TEXT NOT NULL DEFAULT '{}',
                    evaluation_metrics TEXT NOT NULL DEFAULT '{}',
                    data_digest TEXT NOT NULL DEFAULT '',
                    trained_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    evaluated_at TEXT DEFAULT '',
                    activated_at TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_preference_ranker_status
                    ON preference_ranker_models(status, version DESC);
                CREATE TABLE IF NOT EXISTS agent_policy_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_name TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'candidate',
                    feature_dim INTEGER NOT NULL DEFAULT 128,
                    weights TEXT NOT NULL DEFAULT '{}',
                    training_metrics TEXT NOT NULL DEFAULT '{}',
                    evaluation_metrics TEXT NOT NULL DEFAULT '{}',
                    data_digest TEXT NOT NULL DEFAULT '',
                    trained_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    evaluated_at TEXT DEFAULT '',
                    activated_at TEXT DEFAULT '',
                    UNIQUE(group_name, version)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_policy_models_group
                    ON agent_policy_models(group_name, status, version DESC);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_id TEXT NOT NULL DEFAULT 'system',
                    session_id TEXT DEFAULT '',
                    task_id INTEGER,
                    action TEXT NOT NULL,
                    resource_type TEXT DEFAULT '',
                    resource_id TEXT DEFAULT '',
                    decision TEXT NOT NULL DEFAULT 'allow',
                    reason TEXT DEFAULT '',
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events(action, id DESC);
                CREATE TABLE IF NOT EXISTS secret_refs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    env_var TEXT NOT NULL,
                    purpose TEXT DEFAULT '',
                    allowed_tools TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_by TEXT NOT NULL DEFAULT 'system',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS run_records (
                    run_id TEXT PRIMARY KEY,
                    schema TEXT NOT NULL DEFAULT 'clawos.run.v1',
                    run_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'created',
                    actor TEXT DEFAULT 'system',
                    scenario TEXT DEFAULT '',
                    started_at TEXT DEFAULT '',
                    completed_at TEXT DEFAULT '',
                    inputs TEXT NOT NULL DEFAULT '{}',
                    outputs TEXT NOT NULL DEFAULT '{}',
                    metrics TEXT NOT NULL DEFAULT '{}',
                    workflow TEXT NOT NULL DEFAULT '{}',
                    provenance TEXT NOT NULL DEFAULT '{}',
                    verification TEXT NOT NULL DEFAULT '{}',
                    parent_run_id TEXT DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_run_records_type_status ON run_records(run_type, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS run_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'file',
                    title TEXT NOT NULL DEFAULT '',
                    uri TEXT DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(run_id) REFERENCES run_records(run_id) ON DELETE CASCADE,
                    UNIQUE(run_id, artifact_id)
                );
                CREATE INDEX IF NOT EXISTS idx_run_artifacts_run ON run_artifacts(run_id, id);
                CREATE TABLE IF NOT EXISTS run_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    claim TEXT NOT NULL DEFAULT '',
                    citation TEXT DEFAULT '',
                    score REAL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(run_id) REFERENCES run_records(run_id) ON DELETE CASCADE,
                    UNIQUE(run_id, evidence_id)
                );
                CREATE INDEX IF NOT EXISTS idx_run_evidence_run ON run_evidence(run_id, id);
                CREATE TABLE IF NOT EXISTS run_failure_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    failure_id TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'medium',
                    input_summary TEXT DEFAULT '',
                    output_summary TEXT DEFAULT '',
                    remediation TEXT DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY(run_id) REFERENCES run_records(run_id) ON DELETE CASCADE,
                    UNIQUE(run_id, failure_id)
                );
                CREATE INDEX IF NOT EXISTS idx_run_failure_cases_category ON run_failure_cases(category, severity, id DESC);
            """)
            self._ensure_columns(c, "experiences", {
                "solution": "TEXT DEFAULT ''",
                "tags": "TEXT DEFAULT '[]'",
                "importance": "REAL DEFAULT 0.5",
            })
            self._ensure_columns(c, "knowledge", {
                "source": "TEXT DEFAULT ''",
                "tags": "TEXT DEFAULT '[]'",
                "confidence": "REAL DEFAULT 0.5",
                "access_count": "INTEGER DEFAULT 0",
                "updated_at": "TEXT DEFAULT ''",
            })
            self._ensure_columns(c, "skill_records", {
                "feedback": "TEXT DEFAULT ''",
                "quality_score": "REAL DEFAULT 0.5",
            })
            self._ensure_columns(c, "tool_executions", {
                "arguments": "TEXT DEFAULT '{}'",
                "result": "TEXT DEFAULT '{}'",
                "status": "TEXT NOT NULL DEFAULT 'success'",
                "duration_ms": "REAL DEFAULT 0",
                "requires_confirmation": "INTEGER DEFAULT 0",
            })
            self._ensure_columns(c, "tasks", {
                "source": "TEXT DEFAULT ''",
                "metadata": "TEXT DEFAULT '{}'",
                "idempotency_key": "TEXT DEFAULT ''",
                "retry_of": "INTEGER",
                "attempt": "INTEGER NOT NULL DEFAULT 1",
                "cancellation_requested": "INTEGER NOT NULL DEFAULT 0",
                "resume_state": "TEXT DEFAULT ''",
                "completed_at": "TEXT DEFAULT ''",
            })
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency "
                "ON tasks(idempotency_key) WHERE idempotency_key <> ''"
            )
            self._ensure_columns(c, "task_steps", {
                "input_data": "TEXT DEFAULT '{}'",
                "output_data": "TEXT DEFAULT '{}'",
                "error": "TEXT DEFAULT ''",
                "completed_at": "TEXT DEFAULT ''",
            })
            self._ensure_columns(c, "task_events", {
                "message": "TEXT DEFAULT ''",
                "data": "TEXT DEFAULT '{}'",
            })
            self._ensure_columns(c, "run_records", {
                "schema": "TEXT NOT NULL DEFAULT 'clawos.run.v1'",
                "actor": "TEXT DEFAULT 'system'",
                "scenario": "TEXT DEFAULT ''",
                "started_at": "TEXT DEFAULT ''",
                "completed_at": "TEXT DEFAULT ''",
                "inputs": "TEXT NOT NULL DEFAULT '{}'",
                "outputs": "TEXT NOT NULL DEFAULT '{}'",
                "metrics": "TEXT NOT NULL DEFAULT '{}'",
                "workflow": "TEXT NOT NULL DEFAULT '{}'",
                "provenance": "TEXT NOT NULL DEFAULT '{}'",
                "verification": "TEXT NOT NULL DEFAULT '{}'",
                "parent_run_id": "TEXT DEFAULT ''",
                "tags": "TEXT NOT NULL DEFAULT '[]'",
                "updated_at": "TEXT DEFAULT ''",
            })
            self._ensure_columns(c, "self_evolution_runs", {
                "release_stage": "TEXT NOT NULL DEFAULT 'candidate'",
                "traffic_percent": "REAL NOT NULL DEFAULT 0",
                "quality_signals": "TEXT NOT NULL DEFAULT '{}'",
            })
            self._ensure_columns(c, "memories", {
                "source": "TEXT DEFAULT ''",
                "confidence": "REAL DEFAULT 0.5",
                "enabled": "INTEGER DEFAULT 1",
                "owner_id": "TEXT NOT NULL DEFAULT 'default'",
                "workspace_id": "TEXT NOT NULL DEFAULT 'default'",
                "current_version": "INTEGER NOT NULL DEFAULT 1",
                "updated_at": "TEXT DEFAULT ''",
            })
            self._backfill_memory_versions(c)

    def _ensure_columns(self, conn: sqlite3.Connection, table: str, columns: dict[str, str]):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, spec in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {spec}")

    def _memory_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["confidence"] = float(item.get("confidence") or 0)
        item["current_version"] = int(item.get("current_version") or 1)
        return item

    def _backfill_memory_versions(self, conn: sqlite3.Connection):
        rows = conn.execute(
            """
            SELECT m.* FROM memories m
            WHERE NOT EXISTS (
                SELECT 1 FROM memory_versions v WHERE v.memory_id=m.id
            )
            """
        ).fetchall()
        for row in rows:
            conn.execute(
                """
                INSERT INTO memory_versions
                    (memory_id, version, value, source, confidence, enabled, change_type, changed_by, change_reason)
                VALUES (?, 1, ?, ?, ?, ?, 'create', 'migration', 'Backfilled existing memory')
                """,
                (
                    int(row["id"]),
                    row["value"],
                    row["source"],
                    float(row["confidence"] or 0),
                    int(row["enabled"] or 0),
                ),
            )
            conn.execute("UPDATE memories SET current_version=1 WHERE id=?", (int(row["id"]),))

    # ── UNIFIED MEMORIES ──

    def _json_loads(self, value, default):
        try:
            return json.loads(value or "")
        except Exception:
            return default

    def _task_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        item["attempt"] = int(item.get("attempt") or 1)
        item["cancellation_requested"] = bool(item.get("cancellation_requested"))
        return item

    def _step_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["input"] = self._json_loads(item.pop("input_data", "{}"), {})
        item["output"] = self._json_loads(item.pop("output_data", "{}"), {})
        return item

    def _event_row_to_dict(self, row) -> dict:
        item = dict(row)
        item["data"] = self._json_loads(item.get("data"), {})
        return item

    # ---- TASK RUNTIME ----

    def start_task(
        self, session_id, title, source="", metadata=None, status="running",
        idempotency_key="", retry_of=None,
    ):
        with self._conn() as c:
            key = str(idempotency_key or "").strip()
            if key:
                existing = c.execute(
                    "SELECT * FROM tasks WHERE idempotency_key=?",
                    (key,),
                ).fetchone()
                if existing:
                    item = self._task_row_to_dict(existing)
                    item["idempotent_replay"] = True
                    return item
            attempt = 1
            if retry_of:
                prior = c.execute(
                    "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM tasks WHERE id=? OR retry_of=?",
                    (int(retry_of), int(retry_of)),
                ).fetchone()
                attempt = int(prior["max_attempt"] or 0) + 1
            cursor = c.execute(
                """
                INSERT INTO tasks
                    (session_id, title, status, source, metadata, idempotency_key, retry_of, attempt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session_id or "default"),
                    str(title or "Untitled task")[:300],
                    status,
                    source,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    key,
                    int(retry_of) if retry_of else None,
                    attempt,
                ),
            )
            task_id = int(cursor.lastrowid)
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    task_id,
                    "task_started",
                    "Task started",
                    json.dumps({"idempotency_key": key, "retry_of": retry_of, "attempt": attempt}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            return self._task_row_to_dict(row)

    def finish_task(self, task_id, status, error="", result_payload=None):
        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            metadata = self._json_loads(row["metadata"], {}) if row else {}
            if result_payload is not None:
                metadata["response_payload"] = result_payload
            metadata["quality_outcome"] = {
                "success": str(status) == "succeeded",
                "failed": str(status) == "failed",
                "canceled": str(status) in {"canceled", "cancelled"},
                "has_response": result_payload is not None,
            }
            c.execute(
                "UPDATE tasks SET status=?, metadata=?, completed_at=datetime('now') WHERE id=?",
                (status, json.dumps(metadata, ensure_ascii=False), int(task_id)),
            )
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(task_id),
                    "task_finished",
                    status,
                    json.dumps({"error": error} if error else {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            result = self._task_row_to_dict(row) if row else {}
        self._record_task_policy_signals(result)
        return result

    def update_task_metadata(self, task_id, updates, event_type="task_metadata"):
        """Merge traceable runtime metadata into a task and emit an audit event."""

        with self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not row:
                return {}
            metadata = self._json_loads(row["metadata"], {})
            metadata.update(dict(updates or {}))
            c.execute(
                "UPDATE tasks SET metadata=? WHERE id=?",
                (json.dumps(metadata, ensure_ascii=False), int(task_id)),
            )
            c.execute(
                """
                INSERT INTO task_events (task_id, event_type, message, data)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(task_id),
                    str(event_type or "task_metadata"),
                    "Task runtime metadata updated",
                    json.dumps(updates or {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            return self._task_row_to_dict(row)

    def _record_task_policy_signals(self, task):
        metadata = (task or {}).get("metadata") or {}
        selections = metadata.get("runtime_policies") or []
        if isinstance(selections, dict):
            selections = list(selections.values())
        run_ids = {
            int(item.get("run_id"))
            for item in selections
            if isinstance(item, dict)
            and item.get("run_id")
            and item.get("exposure") == "candidate"
        }
        if not run_ids:
            return
        status = str((task or {}).get("status") or "")
        signals = {
            "user_retry_rate": float(
                int((task or {}).get("attempt") or 1) > 1 or bool((task or {}).get("retry_of"))
            ),
            "cancel_rate": float(status in {"canceled", "cancelled"}),
            "long_task_failure_rate": float(status == "failed"),
        }
        for run_id in run_ids:
            for signal_type, value in signals.items():
                self.record_self_evolution_quality_signal(
                    run_id,
                    signal_type,
                    value,
                    metadata={
                        "source": "task_outcome",
                        "task_id": int((task or {}).get("id") or 0),
                        "status": status,
                    },
                    created_by="runtime",
                )

    def cancel_task(self, task_id, reason="", actor_id="user"):
        with self._conn() as c:
            task = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not task:
                return {}
            terminal = str(task["status"]) in {"succeeded", "failed", "canceled", "cancelled"}
            status = str(task["status"]) if terminal else "cancel_requested"
            c.execute(
                "UPDATE tasks SET cancellation_requested=1, status=? WHERE id=?",
                (status, int(task_id)),
            )
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(task_id),
                    "task_cancel_requested",
                    reason or "Cancellation requested",
                    json.dumps({"actor_id": actor_id, "terminal": terminal}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            return self._task_row_to_dict(row)

    def is_task_cancelled(self, task_id):
        if not task_id:
            return False
        with self._conn() as c:
            row = c.execute(
                "SELECT cancellation_requested, status FROM tasks WHERE id=?",
                (int(task_id),),
            ).fetchone()
            return bool(row and (int(row["cancellation_requested"] or 0) or row["status"] in {"cancel_requested", "canceled"}))

    def retry_task(self, task_id, actor_id="user", reason=""):
        with self._conn() as c:
            task = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not task:
                return {}
            metadata = self._json_loads(task["metadata"], {})
            metadata["retry_reason"] = reason
            metadata["retry_actor"] = actor_id
            title = f"Retry: {task['title']}"[:300]
            previous_key = str(task["idempotency_key"] or "")
            retry_key = f"{previous_key}:retry:{int(time.time() * 1000)}" if previous_key else ""
            prior = c.execute(
                "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM tasks WHERE id=? OR retry_of=?",
                (int(task_id), int(task_id)),
            ).fetchone()
            attempt = int(prior["max_attempt"] or int(task["attempt"] or 1)) + 1
            cursor = c.execute(
                """
                INSERT INTO tasks
                    (session_id, title, status, source, metadata, idempotency_key, retry_of, attempt, resume_state)
                VALUES (?, ?, 'pending_retry', ?, ?, ?, ?, ?, 'ready_to_replay')
                """,
                (
                    task["session_id"], title, "retry",
                    json.dumps(metadata, ensure_ascii=False), retry_key,
                    int(task_id), attempt,
                ),
            )
            new_id = int(cursor.lastrowid)
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    new_id,
                    "task_retry_created",
                    reason or "Retry task created",
                    json.dumps({"retry_of": int(task_id), "actor_id": actor_id, "attempt": attempt}, ensure_ascii=False),
                ),
            )
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(task_id),
                    "task_retry_requested",
                    reason or "Retry requested",
                    json.dumps({"new_task_id": new_id, "actor_id": actor_id}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM tasks WHERE id=?", (new_id,)).fetchone()
            return self._task_row_to_dict(row)

    def recover_interrupted_tasks(self, actor_id="system", create_retries=False):
        recoverable = ("running", "pending", "cancel_requested", "waiting_confirmation")
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM tasks WHERE status IN ({','.join('?' for _ in recoverable)})",
                recoverable,
            ).fetchall()
            recovered = []
            retry_tasks = []
            for row in rows:
                status = "canceled" if row["status"] == "cancel_requested" else "interrupted"
                c.execute(
                    "UPDATE tasks SET status=?, resume_state='needs_retry', completed_at=datetime('now') WHERE id=?",
                    (status, int(row["id"])),
                )
                c.execute(
                    "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                    (
                        int(row["id"]),
                        "task_recovered",
                        "Recovered after process restart or manual recovery",
                        json.dumps({"actor_id": actor_id, "previous_status": row["status"]}, ensure_ascii=False),
                    ),
                )
                recovered.append(int(row["id"]))
                if create_retries and row["status"] in {"running", "pending"}:
                    metadata = self._json_loads(row["metadata"], {})
                    metadata["recovery_actor"] = actor_id
                    prior = c.execute(
                        "SELECT COALESCE(MAX(attempt), 0) AS max_attempt FROM tasks WHERE id=? OR retry_of=?",
                        (int(row["id"]), int(row["id"])),
                    ).fetchone()
                    attempt = int(prior["max_attempt"] or int(row["attempt"] or 1)) + 1
                    cursor = c.execute(
                        """
                        INSERT INTO tasks
                            (session_id, title, status, source, metadata, idempotency_key, retry_of, attempt, resume_state)
                        VALUES (?, ?, 'pending_retry', 'recovery', ?, '', ?, ?, 'ready_to_replay')
                        """,
                        (
                            row["session_id"], f"Replay: {row['title']}"[:300],
                            json.dumps(metadata, ensure_ascii=False),
                            int(row["id"]), attempt,
                        ),
                    )
                    retry_id = int(cursor.lastrowid)
                    c.execute(
                        "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                        (
                            retry_id,
                            "task_retry_created",
                            "Replay retry created during recovery",
                            json.dumps({"retry_of": int(row["id"]), "actor_id": actor_id, "attempt": attempt}, ensure_ascii=False),
                        ),
                    )
                    retry_row = c.execute("SELECT * FROM tasks WHERE id=?", (retry_id,)).fetchone()
                    retry_tasks.append(self._task_row_to_dict(retry_row))
            return {
                "recovered": recovered,
                "count": len(recovered),
                "retry_tasks": retry_tasks,
                "created_retry_count": len(retry_tasks),
            }

    def list_task_events(self, session_id="", after_id=0, limit=100):
        with self._conn() as c:
            limit = max(1, min(int(limit or 100), 500))
            clauses = ["e.id>?"]
            params = [int(after_id or 0)]
            if session_id:
                clauses.append("t.session_id=?")
                params.append(session_id)
            rows = c.execute(
                f"""
                SELECT e.*, t.session_id, t.status AS task_status, t.title AS task_title
                FROM task_events e JOIN tasks t ON t.id=e.task_id
                WHERE {' AND '.join(clauses)}
                ORDER BY e.id ASC LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
            return [self._event_row_to_dict(row) for row in rows]

    def prune_task_events(self, older_than_days=30, retain_latest_per_task=100, dry_run=False, actor_id="system"):
        lifecycle_events = {
            "task_started",
            "task_finished",
            "task_cancel_requested",
            "task_retry_created",
            "task_retry_requested",
            "task_recovered",
        }
        older_than_days = max(1, int(older_than_days or 30))
        retain_latest_per_task = max(0, min(int(retain_latest_per_task or 0), 1000))
        cutoff = f"-{older_than_days} days"
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT *
                FROM task_events
                WHERE created_at < datetime('now', ?)
                ORDER BY task_id ASC, id DESC
                """,
                (cutoff,),
            ).fetchall()
            detail_kept_by_task = {}
            delete_ids = []
            retained_lifecycle_count = 0
            retained_tail_count = 0
            for row in rows:
                if row["event_type"] in lifecycle_events:
                    retained_lifecycle_count += 1
                    continue
                task_id = int(row["task_id"])
                kept = detail_kept_by_task.get(task_id, 0)
                if kept < retain_latest_per_task:
                    detail_kept_by_task[task_id] = kept + 1
                    retained_tail_count += 1
                    continue
                delete_ids.append(int(row["id"]))
            if delete_ids and not dry_run:
                placeholders = ",".join("?" for _ in delete_ids)
                c.execute(f"DELETE FROM task_events WHERE id IN ({placeholders})", delete_ids)
        return {
            "older_than_days": older_than_days,
            "retain_latest_per_task": retain_latest_per_task,
            "dry_run": bool(dry_run),
            "actor_id": str(actor_id or "system"),
            "candidate_count": len(rows),
            "deleted_count": len(delete_ids),
            "retained_lifecycle_count": retained_lifecycle_count,
            "retained_tail_count": retained_tail_count,
        }

    def add_task_step(self, task_id, step_type, name, status="running", input_data=None):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO task_steps (task_id, step_type, name, status, input_data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(task_id),
                    str(step_type or "tool"),
                    str(name or "step"),
                    status,
                    json.dumps(input_data or {}, ensure_ascii=False),
                ),
            )
            step_id = int(cursor.lastrowid)
            c.execute(
                "INSERT INTO task_events (task_id, step_id, event_type, message, data) VALUES (?, ?, ?, ?, ?)",
                (int(task_id), step_id, "step_started", str(name or "step"), "{}"),
            )
            row = c.execute("SELECT * FROM task_steps WHERE id=?", (step_id,)).fetchone()
            return self._step_row_to_dict(row)

    def finish_task_step(self, step_id, status, output_data=None, error=""):
        with self._conn() as c:
            c.execute(
                """
                UPDATE task_steps
                SET status=?, output_data=?, error=?, completed_at=datetime('now')
                WHERE id=?
                """,
                (
                    status,
                    json.dumps(output_data or {}, ensure_ascii=False),
                    error,
                    int(step_id),
                ),
            )
            row = c.execute("SELECT * FROM task_steps WHERE id=?", (int(step_id),)).fetchone()
            if not row:
                return {}
            c.execute(
                "INSERT INTO task_events (task_id, step_id, event_type, message, data) VALUES (?, ?, ?, ?, ?)",
                (
                    int(row["task_id"]),
                    int(step_id),
                    "step_finished",
                    status,
                    json.dumps({"error": error} if error else {}, ensure_ascii=False),
                ),
            )
            return self._step_row_to_dict(row)

    def add_task_event(self, task_id, event_type, message="", step_id=None, data=None):
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO task_events (task_id, step_id, event_type, message, data) VALUES (?, ?, ?, ?, ?)",
                (
                    int(task_id),
                    int(step_id) if step_id else None,
                    str(event_type or "event"),
                    str(message or ""),
                    json.dumps(data or {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM task_events WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return self._event_row_to_dict(row)

    def list_tasks(self, session_id="", status="", limit=50):
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            clauses = []
            params = []
            if session_id:
                clauses.append("session_id=?")
                params.append(session_id)
            if status:
                clauses.append("status=?")
                params.append(status)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM tasks{where} ORDER BY id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
            return [self._task_row_to_dict(row) for row in rows]

    def list_task_queue(self, statuses=None, limit=50):
        statuses = statuses or ["pending_retry", "pending"]
        statuses = [str(status) for status in statuses if str(status or "").strip()]
        if not statuses:
            statuses = ["pending_retry", "pending"]
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            placeholders = ",".join("?" for _ in statuses)
            rows = c.execute(
                f"""
                SELECT *
                FROM tasks
                WHERE status IN ({placeholders}) AND cancellation_requested=0
                ORDER BY attempt ASC, id ASC
                LIMIT ?
                """,
                [*statuses, limit],
            ).fetchall()
            return [self._task_row_to_dict(row) for row in rows]

    def claim_next_task(self, worker_id="worker", statuses=None):
        statuses = statuses or ["pending_retry", "pending"]
        statuses = [str(status) for status in statuses if str(status or "").strip()]
        if not statuses:
            statuses = ["pending_retry", "pending"]
        with self._conn() as c:
            placeholders = ",".join("?" for _ in statuses)
            row = c.execute(
                f"""
                SELECT *
                FROM tasks
                WHERE status IN ({placeholders}) AND cancellation_requested=0
                ORDER BY attempt ASC, id ASC
                LIMIT 1
                """,
                statuses,
            ).fetchone()
            if not row:
                return {}
            metadata = self._json_loads(row["metadata"], {})
            metadata["claimed_by"] = str(worker_id or "worker")
            metadata["claimed_at"] = datetime.now(timezone.utc).isoformat()
            updated = c.execute(
                """
                UPDATE tasks
                SET status='running', resume_state='claimed', metadata=?
                WHERE id=? AND status=?
                """,
                (json.dumps(metadata, ensure_ascii=False), int(row["id"]), row["status"]),
            )
            if updated.rowcount != 1:
                return {}
            c.execute(
                "INSERT INTO task_events (task_id, event_type, message, data) VALUES (?, ?, ?, ?)",
                (
                    int(row["id"]),
                    "task_claimed",
                    "Task claimed by queue worker",
                    json.dumps({"worker_id": str(worker_id or "worker")}, ensure_ascii=False),
                ),
            )
            claimed = c.execute("SELECT * FROM tasks WHERE id=?", (int(row["id"]),)).fetchone()
            return self._task_row_to_dict(claimed)

    def get_task(self, task_id):
        with self._conn() as c:
            task = c.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()
            if not task:
                return {}
            steps = c.execute("SELECT * FROM task_steps WHERE task_id=? ORDER BY id", (int(task_id),)).fetchall()
            events = c.execute("SELECT * FROM task_events WHERE task_id=? ORDER BY id", (int(task_id),)).fetchall()
            return {
                "task": self._task_row_to_dict(task),
                "steps": [self._step_row_to_dict(row) for row in steps],
                "events": [self._event_row_to_dict(row) for row in events],
            }

    def save_run_record(self, record: dict[str, Any]) -> dict[str, Any]:
        run_id = str(record.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        artifacts = list(record.get("artifacts") or [])
        evidence = list(record.get("evidence") or [])
        failures = list(record.get("failure_cases") or [])
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO run_records
                    (run_id, schema, run_type, title, status, actor, scenario, started_at,
                     completed_at, inputs, outputs, metrics, workflow, provenance,
                     verification, parent_run_id, tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(run_id) DO UPDATE SET
                    schema=excluded.schema,
                    run_type=excluded.run_type,
                    title=excluded.title,
                    status=excluded.status,
                    actor=excluded.actor,
                    scenario=excluded.scenario,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at,
                    inputs=excluded.inputs,
                    outputs=excluded.outputs,
                    metrics=excluded.metrics,
                    workflow=excluded.workflow,
                    provenance=excluded.provenance,
                    verification=excluded.verification,
                    parent_run_id=excluded.parent_run_id,
                    tags=excluded.tags,
                    updated_at=datetime('now')
                """,
                (
                    run_id,
                    str(record.get("schema") or "clawos.run.v1"),
                    str(record.get("run_type") or "generic"),
                    str(record.get("title") or run_id),
                    str(record.get("status") or "created"),
                    str(record.get("actor") or "system"),
                    str(record.get("scenario") or ""),
                    str(record.get("started_at") or ""),
                    str(record.get("completed_at") or ""),
                    json.dumps(record.get("inputs") or {}, ensure_ascii=False),
                    json.dumps(record.get("outputs") or {}, ensure_ascii=False),
                    json.dumps(record.get("metrics") or {}, ensure_ascii=False),
                    json.dumps(record.get("workflow") or {}, ensure_ascii=False),
                    json.dumps(record.get("provenance") or {}, ensure_ascii=False),
                    json.dumps(record.get("verification") or {}, ensure_ascii=False),
                    str(record.get("parent_run_id") or ""),
                    json.dumps(record.get("tags") or [], ensure_ascii=False),
                ),
            )
            c.execute("DELETE FROM run_artifacts WHERE run_id=?", (run_id,))
            c.execute("DELETE FROM run_evidence WHERE run_id=?", (run_id,))
            c.execute("DELETE FROM run_failure_cases WHERE run_id=?", (run_id,))
            for index, item in enumerate(artifacts, 1):
                c.execute(
                    """
                    INSERT INTO run_artifacts
                        (run_id, artifact_id, kind, title, uri, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(item.get("artifact_id") or f"art-{index:03d}"),
                        str(item.get("kind") or "file"),
                        str(item.get("title") or ""),
                        str(item.get("uri") or item.get("path") or ""),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                        str(item.get("created_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
                    ),
                )
            for index, item in enumerate(evidence, 1):
                c.execute(
                    """
                    INSERT INTO run_evidence
                        (run_id, evidence_id, source, claim, citation, score, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        run_id,
                        str(item.get("evidence_id") or f"ev-{index:03d}"),
                        str(item.get("source") or ""),
                        str(item.get("claim") or ""),
                        str(item.get("citation") or ""),
                        item.get("score"),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                    ),
                )
            for index, item in enumerate(failures, 1):
                c.execute(
                    """
                    INSERT INTO run_failure_cases
                        (run_id, failure_id, category, reason, severity, input_summary,
                         output_summary, remediation, metadata, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(item.get("failure_id") or f"fc-{index:03d}"),
                        str(item.get("category") or ""),
                        str(item.get("reason") or ""),
                        str(item.get("severity") or "medium"),
                        str(item.get("input_summary") or ""),
                        str(item.get("output_summary") or ""),
                        str(item.get("remediation") or ""),
                        json.dumps(item.get("metadata") or {}, ensure_ascii=False),
                        str(item.get("created_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
                    ),
                )
        return self.get_run_record(run_id)

    def get_run_record(self, run_id: str) -> dict[str, Any]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM run_records WHERE run_id=?", (str(run_id),)).fetchone()
            if not row:
                return {}
            artifacts = c.execute("SELECT * FROM run_artifacts WHERE run_id=? ORDER BY id", (str(run_id),)).fetchall()
            evidence = c.execute("SELECT * FROM run_evidence WHERE run_id=? ORDER BY id", (str(run_id),)).fetchall()
            failures = c.execute("SELECT * FROM run_failure_cases WHERE run_id=? ORDER BY id", (str(run_id),)).fetchall()
            return self._run_record_from_rows(row, artifacts, evidence, failures)

    def list_run_records(self, run_type="", status="", limit=50) -> list[dict[str, Any]]:
        where, params = [], []
        if run_type:
            where.append("run_type=?")
            params.append(str(run_type))
        if status:
            where.append("status=?")
            params.append(str(status))
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM run_records{clause} ORDER BY updated_at DESC, created_at DESC LIMIT ?",
                (*params, max(1, min(int(limit or 50), 200))),
            ).fetchall()
            if not rows:
                return []
            run_ids = [str(row["run_id"]) for row in rows]
            placeholders = ",".join("?" for _ in run_ids)
            artifacts = c.execute(
                f"SELECT * FROM run_artifacts WHERE run_id IN ({placeholders}) ORDER BY id",
                run_ids,
            ).fetchall()
            evidence = c.execute(
                f"SELECT * FROM run_evidence WHERE run_id IN ({placeholders}) ORDER BY id",
                run_ids,
            ).fetchall()
            failures = c.execute(
                f"SELECT * FROM run_failure_cases WHERE run_id IN ({placeholders}) ORDER BY id",
                run_ids,
            ).fetchall()
            artifacts_by_run = self._group_run_rows(artifacts)
            evidence_by_run = self._group_run_rows(evidence)
            failures_by_run = self._group_run_rows(failures)
            return [
                self._run_record_from_rows(
                    row,
                    artifacts_by_run.get(str(row["run_id"]), []),
                    evidence_by_run.get(str(row["run_id"]), []),
                    failures_by_run.get(str(row["run_id"]), []),
                )
                for row in rows
            ]

    def list_failure_cases(self, category="", severity="", limit=50) -> list[dict[str, Any]]:
        where, params = [], []
        if category:
            where.append("category=?")
            params.append(str(category))
        if severity:
            where.append("severity=?")
            params.append(str(severity))
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM run_failure_cases{clause} ORDER BY id DESC LIMIT ?",
                (*params, max(1, min(int(limit or 50), 200))),
            ).fetchall()
            return [self._failure_case_row_to_dict(row) for row in rows]

    def _run_record_from_rows(self, row, artifacts, evidence, failures) -> dict[str, Any]:
        item = dict(row)
        for key, default in (
            ("inputs", {}),
            ("outputs", {}),
            ("metrics", {}),
            ("workflow", {}),
            ("provenance", {}),
            ("verification", {}),
            ("tags", []),
        ):
            item[key] = self._json_loads(item.get(key), default)
        item["artifacts"] = [self._artifact_row_to_dict(row) for row in artifacts]
        item["evidence"] = [self._run_evidence_row_to_dict(row) for row in evidence]
        item["failure_cases"] = [self._failure_case_row_to_dict(row) for row in failures]
        return item

    @staticmethod
    def _group_run_rows(rows) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = {}
        for row in rows:
            grouped.setdefault(str(row["run_id"]), []).append(row)
        return grouped

    def _artifact_row_to_dict(self, row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        return item

    def _run_evidence_row_to_dict(self, row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        return item

    def _failure_case_row_to_dict(self, row) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        item["source_run_id"] = item.get("run_id", "")
        return item

    def upsert_memory(
        self,
        memory_type,
        key,
        value,
        category="general",
        source="",
        confidence=0.5,
        enabled=True,
        actor_id="system",
        owner_id="default",
        workspace_id="default",
        evidence=None,
        change_reason="",
        conflict_policy="overwrite",
    ):
        memory_type = str(memory_type or "").strip().lower()
        if memory_type not in {"profile", "preference", "project", "experience", "skill"}:
            raise ValueError(f"Invalid memory_type: {memory_type}")
        key = str(key or "").strip()
        value = str(value or "").strip()
        if not key or not value:
            raise ValueError("key and value are required")
        with self._conn() as c:
            existing = c.execute(
                "SELECT * FROM memories WHERE memory_type=? AND category=? AND key=?",
                (memory_type, category, key),
            ).fetchone()
            if (
                existing
                and existing["value"] != value
                and str(conflict_policy or "").lower() == "review"
            ):
                conflict_cursor = c.execute(
                    """
                    INSERT INTO memory_conflicts
                        (memory_id, existing_value, candidate_value, source, evidence, submitted_by)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(existing["id"]),
                        existing["value"],
                        value,
                        source,
                        json.dumps(evidence or [], ensure_ascii=False),
                        str(actor_id or "system"),
                    ),
                )
                conflict_id = int(conflict_cursor.lastrowid)
                review_cursor = c.execute(
                    """
                    INSERT INTO memory_reviews (memory_id, conflict_id, submitted_by)
                    VALUES (?, ?, ?)
                    """,
                    (int(existing["id"]), conflict_id, str(actor_id or "system")),
                )
                item = self._memory_row_to_dict(existing)
                item.update({
                    "review_required": True,
                    "conflict_id": conflict_id,
                    "review_id": int(review_cursor.lastrowid),
                    "candidate_value": value,
                })
                return item

            changed = (
                existing is None
                or existing["value"] != value
                or existing["source"] != source
                or float(existing["confidence"] or 0) != float(confidence)
                or bool(existing["enabled"]) != bool(enabled)
            )
            next_version = int(existing["current_version"] or 1) + 1 if existing else 1
            c.execute("""
                INSERT INTO memories
                    (memory_type, category, key, value, source, confidence, enabled,
                     owner_id, workspace_id, current_version, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(memory_type, category, key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    confidence = excluded.confidence,
                    enabled = excluded.enabled,
                    owner_id = excluded.owner_id,
                    workspace_id = excluded.workspace_id,
                    current_version = excluded.current_version,
                    updated_at = datetime('now')
            """, (
                memory_type, category, key, value, source, float(confidence),
                1 if enabled else 0, owner_id, workspace_id,
                next_version if changed else int(existing["current_version"] or 1),
            ))
            row = c.execute(
                "SELECT * FROM memories WHERE memory_type=? AND category=? AND key=?",
                (memory_type, category, key),
            ).fetchone()
            version_id = None
            if changed:
                cursor = c.execute(
                    """
                    INSERT INTO memory_versions
                        (memory_id, version, value, source, confidence, enabled,
                         change_type, changed_by, change_reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(row["id"]),
                        next_version,
                        value,
                        source,
                        float(confidence),
                        1 if enabled else 0,
                        "create" if existing is None else "update",
                        str(actor_id or "system"),
                        str(change_reason or ""),
                    ),
                )
                version_id = int(cursor.lastrowid)
            for item in evidence or []:
                self._insert_memory_evidence(c, int(row["id"]), version_id, item, actor_id)
            result = self._memory_row_to_dict(row)
            result["review_required"] = False
            return result

    def _insert_memory_evidence(self, conn, memory_id, version_id, evidence, actor_id="system"):
        item = evidence if isinstance(evidence, dict) else {"excerpt": str(evidence)}
        conn.execute(
            """
            INSERT INTO memory_evidence
                (memory_id, version_id, evidence_type, source_ref, excerpt, metadata, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(memory_id),
                int(version_id) if version_id else None,
                str(item.get("evidence_type", item.get("type", "manual")) or "manual"),
                str(item.get("source_ref", "") or ""),
                str(item.get("excerpt", "") or "")[:4000],
                json.dumps(item.get("metadata", {}), ensure_ascii=False),
                str(actor_id or "system"),
            ),
        )

    def list_memory_versions(self, memory_id, limit=100):
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM memory_versions
                WHERE memory_id=? ORDER BY version DESC LIMIT ?
                """,
                (int(memory_id), max(1, min(int(limit or 100), 500))),
            ).fetchall()
            return [self._version_row_to_dict(row) for row in rows]

    def list_memory_evidence(self, memory_id, limit=100):
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT * FROM memory_evidence
                WHERE memory_id=? ORDER BY id DESC LIMIT ?
                """,
                (int(memory_id), max(1, min(int(limit or 100), 500))),
            ).fetchall()
            return [self._evidence_row_to_dict(row) for row in rows]

    def _version_row_to_dict(self, row):
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["confidence"] = float(item.get("confidence") or 0)
        return item

    def _evidence_row_to_dict(self, row):
        item = dict(row)
        item["metadata"] = self._json_loads(item.get("metadata"), {})
        return item

    def list_memory_reviews(self, status="pending", limit=100):
        with self._conn() as c:
            clauses = []
            params = []
            if status:
                clauses.append("r.status=?")
                params.append(status)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = c.execute(
                f"""
                SELECT r.*, c.existing_value, c.candidate_value, c.conflict_type,
                       c.source AS conflict_source, c.evidence, m.memory_type,
                       m.category, m.key, m.value AS current_value
                FROM memory_reviews r
                JOIN memories m ON m.id=r.memory_id
                LEFT JOIN memory_conflicts c ON c.id=r.conflict_id
                {where}
                ORDER BY r.id DESC LIMIT ?
                """,
                [*params, max(1, min(int(limit or 100), 500))],
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["evidence"] = self._json_loads(item.get("evidence"), [])
                items.append(item)
            return items

    def resolve_memory_review(self, review_id, decision, reviewer="system", notes=""):
        decision = str(decision or "").lower()
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        with self._conn() as c:
            review = c.execute(
                """
                SELECT r.*, c.candidate_value, c.source, c.evidence
                FROM memory_reviews r
                LEFT JOIN memory_conflicts c ON c.id=r.conflict_id
                WHERE r.id=?
                """,
                (int(review_id),),
            ).fetchone()
            if not review:
                return None
            if review["status"] != "pending":
                raise ValueError("review is already resolved")
            status = "approved" if decision == "approve" else "rejected"
            if decision == "approve" and review["candidate_value"] is not None:
                memory = c.execute("SELECT * FROM memories WHERE id=?", (int(review["memory_id"]),)).fetchone()
                version = int(memory["current_version"] or 1) + 1
                c.execute(
                    """
                    UPDATE memories
                    SET value=?, source=?, current_version=?, updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (review["candidate_value"], review["source"], version, int(review["memory_id"])),
                )
                cursor = c.execute(
                    """
                    INSERT INTO memory_versions
                        (memory_id, version, value, source, confidence, enabled,
                         change_type, changed_by, change_reason)
                    VALUES (?, ?, ?, ?, ?, ?, 'conflict_resolution', ?, ?)
                    """,
                    (
                        int(review["memory_id"]), version, review["candidate_value"],
                        review["source"], float(memory["confidence"] or 0),
                        int(memory["enabled"] or 0), str(reviewer or "system"),
                        str(notes or "Approved from Review Inbox"),
                    ),
                )
                if memory["memory_type"] == "profile":
                    c.execute(
                        """
                        INSERT INTO profiles (category, key, value, importance, updated_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(category, key) DO UPDATE SET
                            value=excluded.value, updated_at=datetime('now')
                        """,
                        (
                            memory["category"], memory["key"], review["candidate_value"],
                            float(memory["confidence"] or 0.5),
                        ),
                    )
                elif memory["memory_type"] == "preference":
                    c.execute(
                        """
                        INSERT INTO preferences (category, key, value, confidence, updated_at)
                        VALUES (?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(category, key) DO UPDATE SET
                            value=excluded.value, updated_at=datetime('now')
                        """,
                        (
                            memory["category"], memory["key"], review["candidate_value"],
                            float(memory["confidence"] or 0.5),
                        ),
                    )
                for evidence in self._json_loads(review["evidence"], []):
                    self._insert_memory_evidence(
                        c, int(review["memory_id"]), int(cursor.lastrowid), evidence, reviewer
                    )
            c.execute(
                """
                UPDATE memory_reviews
                SET status=?, reviewed_by=?, notes=?, resolved_at=datetime('now')
                WHERE id=?
                """,
                (status, str(reviewer or "system"), str(notes or ""), int(review_id)),
            )
            if review["conflict_id"]:
                c.execute(
                    """
                    UPDATE memory_conflicts
                    SET status=?, resolution=?, reviewed_by=?, resolved_at=datetime('now')
                    WHERE id=?
                    """,
                    (status, decision, str(reviewer or "system"), int(review["conflict_id"])),
                )
            return dict(c.execute("SELECT * FROM memory_reviews WHERE id=?", (int(review_id),)).fetchone())

    def grant_memory_acl(self, memory_id, principal_type, principal_id, permission, granted_by="system"):
        if principal_type not in {"user", "role", "workspace"}:
            raise ValueError("principal_type must be user, role, or workspace")
        if permission not in {"read", "write", "review", "admin"}:
            raise ValueError("permission must be read, write, review, or admin")
        if not str(principal_id or "").strip():
            raise ValueError("principal_id is required")
        with self._conn() as c:
            c.execute(
                """
                INSERT OR IGNORE INTO memory_acl
                    (memory_id, principal_type, principal_id, permission, granted_by)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    int(memory_id), str(principal_type), str(principal_id),
                    str(permission), str(granted_by or "system"),
                ),
            )
            rows = c.execute("SELECT * FROM memory_acl WHERE memory_id=? ORDER BY id", (int(memory_id),)).fetchall()
            return [dict(row) for row in rows]

    def list_memory_acl(self, memory_id):
        with self._conn() as c:
            return [
                dict(row) for row in c.execute(
                    "SELECT * FROM memory_acl WHERE memory_id=? ORDER BY id",
                    (int(memory_id),),
                ).fetchall()
            ]

    def check_memory_access(self, memory_id, actor_id="default", roles=None, workspace_id="default", permission="read"):
        with self._conn() as c:
            memory = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            if not memory:
                return False
            return self._check_memory_access(c, memory, actor_id, roles, workspace_id, permission)

    def _check_memory_access(self, conn, memory, actor_id, roles, workspace_id, permission):
        if str(actor_id) == "system":
            return True
        acl = conn.execute("SELECT * FROM memory_acl WHERE memory_id=?", (int(memory["id"]),)).fetchall()
        if not acl:
            return True
        if actor_id and str(actor_id) == str(memory["owner_id"]):
            return True
        accepted = {
            "read": {"read", "write", "review", "admin"},
            "write": {"write", "admin"},
            "review": {"review", "admin"},
            "admin": {"admin"},
        }.get(permission, {permission})
        role_set = {str(role) for role in (roles or [])}
        for entry in acl:
            principal_match = (
                (entry["principal_type"] == "user" and entry["principal_id"] == str(actor_id))
                or (entry["principal_type"] == "role" and entry["principal_id"] in role_set)
                or (
                    entry["principal_type"] == "workspace"
                    and entry["principal_id"] == str(workspace_id)
                )
            )
            if principal_match and entry["permission"] in accepted:
                return True
        return False

    def record_retrieval_evaluation(self, name, top_k, metrics, cases, created_by="system"):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO retrieval_evaluation_runs
                    (name, top_k, case_count, metrics, cases, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(name or "memory-retrieval"), int(top_k), len(cases or []),
                    json.dumps(metrics or {}, ensure_ascii=False),
                    json.dumps(cases or [], ensure_ascii=False),
                    str(created_by or "system"),
                ),
            )
            return self.get_retrieval_evaluation(int(cursor.lastrowid), conn=c)

    def get_retrieval_evaluation(self, run_id, conn=None):
        def convert(row):
            if not row:
                return None
            item = dict(row)
            item["metrics"] = self._json_loads(item.get("metrics"), {})
            item["cases"] = self._json_loads(item.get("cases"), [])
            return item
        if conn is not None:
            return convert(conn.execute("SELECT * FROM retrieval_evaluation_runs WHERE id=?", (int(run_id),)).fetchone())
        with self._conn() as c:
            return convert(c.execute("SELECT * FROM retrieval_evaluation_runs WHERE id=?", (int(run_id),)).fetchone())

    # ---- REFLECTION 2.0 ----

    def create_reflection_card(self, card, improvements=None):
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO reflection_cards
                    (id, task, session_id, trigger_type, outcome, outcome_detail,
                     root_cause, failure_category, insights, patterns, trajectory,
                     evidence, user_feedback, status, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    card["id"],
                    card.get("task", "Reflection"),
                    card.get("session_id", "default"),
                    card.get("trigger", "user_triggered"),
                    card.get("outcome", "partial"),
                    json.dumps(card.get("outcome_detail", {}), ensure_ascii=False),
                    card.get("root_cause", ""),
                    card.get("failure_category", ""),
                    json.dumps(card.get("insights", []), ensure_ascii=False),
                    json.dumps(card.get("patterns", []), ensure_ascii=False),
                    json.dumps(card.get("trajectory", {}), ensure_ascii=False),
                    json.dumps(card.get("evidence", []), ensure_ascii=False),
                    json.dumps(card.get("user_feedback", {}), ensure_ascii=False),
                    card.get("status", "active"),
                    int(card.get("version", 1)),
                ),
            )
            improvement_rows = []
            for index, improvement in enumerate(improvements or []):
                item = improvement if isinstance(improvement, dict) else {"detail": str(improvement)}
                detail = str(item.get("detail", item.get("title", "")) or "")
                title = str(item.get("title", detail) or f"Improvement {index + 1}")[:200]
                target_key = str(item.get("target_key", f"{card['id']}:{index + 1}"))
                cursor = c.execute(
                    """
                    INSERT INTO reflection_improvements
                        (card_id, title, detail, action_type, target_type, target_key,
                         candidate_payload, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed')
                    """,
                    (
                        card["id"], title, detail,
                        str(item.get("action_type", "policy")),
                        str(item.get("target_type", "agent_policy")),
                        target_key,
                        json.dumps(
                            item.get("candidate_payload", {"instruction": detail}),
                            ensure_ascii=False,
                        ),
                    ),
                )
                improvement_id = int(cursor.lastrowid)
                c.execute(
                    """
                    INSERT INTO reflection_improvement_events
                        (improvement_id, from_status, to_status, actor_id, reason)
                    VALUES (?, '', 'proposed', 'reflection_engine', 'Created from reflection card')
                    """,
                    (improvement_id,),
                )
                improvement_rows.append(self._reflection_improvement_from_row(
                    c.execute("SELECT * FROM reflection_improvements WHERE id=?", (improvement_id,)).fetchone()
                ))
            stored = self._reflection_card_from_row(
                c.execute("SELECT * FROM reflection_cards WHERE id=?", (card["id"],)).fetchone()
            )
            stored["improvements"] = improvement_rows
            return stored

    def list_reflection_cards(self, limit=20, session_id=""):
        with self._conn() as c:
            limit = max(1, min(int(limit or 20), 200))
            if session_id:
                rows = c.execute(
                    "SELECT * FROM reflection_cards WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM reflection_cards ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._reflection_card_from_row(row) for row in rows]

    def get_reflection_card(self, card_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM reflection_cards WHERE id=?", (str(card_id),)).fetchone()
            if not row:
                return None
            card = self._reflection_card_from_row(row)
            improvements = c.execute(
                "SELECT * FROM reflection_improvements WHERE card_id=? ORDER BY id",
                (str(card_id),),
            ).fetchall()
            card["improvements"] = [self._reflection_improvement_from_row(item) for item in improvements]
            return card

    def update_reflection_feedback(self, card_id, feedback, actor_id="system"):
        with self._conn() as c:
            row = c.execute("SELECT * FROM reflection_cards WHERE id=?", (str(card_id),)).fetchone()
            if not row:
                return None
            current = self._json_loads(row["user_feedback"], {})
            current.update(feedback or {})
            current["updated_by"] = str(actor_id or "system")
            c.execute(
                """
                UPDATE reflection_cards
                SET user_feedback=?, version=version+1, updated_at=datetime('now')
                WHERE id=?
                """,
                (json.dumps(current, ensure_ascii=False), str(card_id)),
            )
            return self._reflection_card_from_row(
                c.execute("SELECT * FROM reflection_cards WHERE id=?", (str(card_id),)).fetchone()
            )

    def list_reflection_improvements(self, status="", limit=100):
        with self._conn() as c:
            limit = max(1, min(int(limit or 100), 500))
            if status:
                rows = c.execute(
                    "SELECT * FROM reflection_improvements WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM reflection_improvements ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._reflection_improvement_from_row(row) for row in rows]

    def get_reflection_improvement(self, improvement_id, conn=None):
        def fetch(c):
            row = c.execute("SELECT * FROM reflection_improvements WHERE id=?", (int(improvement_id),)).fetchone()
            if not row:
                return None
            item = self._reflection_improvement_from_row(row)
            events = c.execute(
                "SELECT * FROM reflection_improvement_events WHERE improvement_id=? ORDER BY id",
                (int(improvement_id),),
            ).fetchall()
            item["events"] = [
                {**dict(event), "data": self._json_loads(event["data"], {})}
                for event in events
            ]
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)

    def update_reflection_improvement(
        self, improvement_id, from_status, to_status, actor_id="system",
        reason="", data=None, fields=None,
    ):
        allowed_fields = {
            "baseline_metrics", "candidate_metrics", "regression_result",
            "rollback_payload", "published_at", "rolled_back_at",
        }
        with self._conn() as c:
            current = c.execute(
                "SELECT * FROM reflection_improvements WHERE id=?",
                (int(improvement_id),),
            ).fetchone()
            if not current:
                return None
            if current["status"] != from_status:
                raise ValueError(f"expected status {from_status}, got {current['status']}")
            assignments = ["status=?", "updated_at=datetime('now')"]
            params = [to_status]
            for key, value in (fields or {}).items():
                if key not in allowed_fields:
                    continue
                assignments.append(f"{key}=?")
                params.append(
                    json.dumps(value, ensure_ascii=False)
                    if key.endswith("_metrics") or key.endswith("_result") or key == "rollback_payload"
                    else value
                )
            params.append(int(improvement_id))
            c.execute(
                f"UPDATE reflection_improvements SET {', '.join(assignments)} WHERE id=?",
                params,
            )
            c.execute(
                """
                INSERT INTO reflection_improvement_events
                    (improvement_id, from_status, to_status, actor_id, reason, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(improvement_id), from_status, to_status,
                    str(actor_id or "system"), str(reason or ""),
                    json.dumps(data or {}, ensure_ascii=False),
                ),
            )
            return self.get_reflection_improvement(improvement_id, conn=c)

    def get_runtime_policy(self, target_type, target_key, conn=None):
        def fetch(c):
            row = c.execute(
                "SELECT * FROM runtime_policies WHERE target_type=? AND target_key=?",
                (str(target_type), str(target_key)),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["payload"] = self._json_loads(item.get("payload"), {})
            item["active"] = bool(item.get("active"))
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)

    def set_runtime_policy(self, target_type, target_key, payload, actor_id="system"):
        with self._conn() as c:
            current = self.get_runtime_policy(target_type, target_key, conn=c)
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
                    str(target_type), str(target_key),
                    json.dumps(payload or {}, ensure_ascii=False),
                    version, str(actor_id or "system"),
                ),
            )
            return self.get_runtime_policy(target_type, target_key, conn=c)

    # ---- SELF-EVOLUTION RUNS ----

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

    def publish_self_evolution_run(self, run_id, actor_id="system", reason=""):
        with self._conn() as c:
            run = self.get_self_evolution_run(run_id, conn=c)
            if not run:
                raise ValueError("self-evolution run not found")
            if run["status"] not in {"validated", "shadow", "canary"}:
                raise ValueError("only validated, shadow, or canary runs can be activated")
            if run["publish_decision"] not in {"publish", "shadow_required", "canary"}:
                raise ValueError("self-evolution run is not approved for activation")
            current = self.get_runtime_policy(run["target_type"], run["target_key"], conn=c)
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

    def record_self_evolution_quality_signal(
        self, run_id, signal_type, value, metadata=None, created_by="system",
    ):
        with self._conn() as c:
            if not c.execute("SELECT id FROM self_evolution_runs WHERE id=?", (int(run_id),)).fetchone():
                raise ValueError("self-evolution run not found")
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
            unhealthy = any(
                float((aggregate.get(key) or {}).get("latest", 0) or 0) > limit
                for key, limit in limits.items()
            )
            retrieval = aggregate.get("retrieval_hit_rate") or {}
            if retrieval and float(retrieval.get("latest", 1) or 0) < 0.80:
                unhealthy = True
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
            limit = max(1, min(int(limit or 100), 500))
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
            tasks = [self._task_row_to_dict(row) for row in rows]
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
                "SELECT signal_type, value FROM self_evolution_quality_signals WHERE run_id=?",
                (int(run_id),),
            ).fetchall()
            grouped = {}
            for row in rows:
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
            current = self.get_runtime_policy(
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
            return self.get_reflection_improvement(improvement_id, conn=c)

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
            current = self.get_runtime_policy(
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
            return self.get_reflection_improvement(improvement_id, conn=c)

    def _reflection_card_from_row(self, row):
        item = dict(row)
        for key, default in (
            ("outcome_detail", {}), ("insights", []), ("patterns", []),
            ("trajectory", {}), ("evidence", []), ("user_feedback", {}),
        ):
            item[key] = self._json_loads(item.get(key), default)
        item["trigger"] = item.pop("trigger_type", "")
        return item

    def _reflection_improvement_from_row(self, row):
        item = dict(row)
        for key in (
            "candidate_payload", "baseline_metrics", "candidate_metrics",
            "regression_result", "rollback_payload",
        ):
            item[key] = self._json_loads(item.get(key), {})
        return item

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

    # ---- POLICY OPTIMIZER ----

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
        with self._conn() as c:
            arm = c.execute(
                "SELECT * FROM policy_arms WHERE id=? AND group_id=?",
                (int(arm_id), int(group_id)),
            ).fetchone()
            if not arm:
                raise ValueError("policy arm not found")
            current = self.get_runtime_policy(target_type, target_key, conn=c)
            previous_payload = current["payload"] if current else {}
            payload = self._json_loads(arm["payload"], {})
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
                    str(target_type), str(target_key),
                    json.dumps(payload, ensure_ascii=False),
                    version, str(actor_id or "system"),
                ),
            )
            cursor = c.execute(
                """
                INSERT INTO policy_promotions
                    (group_id, arm_id, target_type, target_key, previous_payload,
                     previous_existed, promoted_payload, promoted_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(group_id), int(arm_id), str(target_type), str(target_key),
                    json.dumps(previous_payload, ensure_ascii=False),
                    1 if current else 0,
                    json.dumps(payload, ensure_ascii=False),
                    str(actor_id or "system"),
                ),
            )
            return self.get_policy_promotion(int(cursor.lastrowid), conn=c)

    def rollback_policy_promotion(self, promotion_id, actor_id="system"):
        with self._conn() as c:
            promotion = c.execute(
                "SELECT * FROM policy_promotions WHERE id=?", (int(promotion_id),)
            ).fetchone()
            if not promotion:
                raise ValueError("policy promotion not found")
            if promotion["status"] != "active":
                raise ValueError("policy promotion is not active")
            current = self.get_runtime_policy(
                promotion["target_type"], promotion["target_key"], conn=c
            )
            version = int(current["version"]) + 1 if current else 1
            if promotion["previous_existed"]:
                c.execute(
                    """
                    UPDATE runtime_policies
                    SET payload=?, version=?, active=1, updated_by=?, updated_at=datetime('now')
                    WHERE target_type=? AND target_key=?
                    """,
                    (
                        promotion["previous_payload"], version, str(actor_id or "system"),
                        promotion["target_type"], promotion["target_key"],
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
                        promotion["target_type"], promotion["target_key"],
                    ),
                )
            c.execute(
                """
                UPDATE policy_promotions
                SET status='rolled_back', rolled_back_at=datetime('now')
                WHERE id=?
                """,
                (int(promotion_id),),
            )
            return self.get_policy_promotion(promotion_id, conn=c)

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

    # ---- AGENT LEARNING DATA PLANE ----

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
                    max(0.000001, min(float(behavior_propensity or 1), 1.0)),
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
                """
            ).fetchone()[0])
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
            item.get("behavior_propensity") or 0.000001
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

    # ---- AUDIT AND SECRET REFERENCES ----

    def record_audit_event(
        self, action, decision="allow", actor_id="system", session_id="",
        task_id=None, resource_type="", resource_id="", reason="", details=None,
    ):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO audit_events
                    (actor_id, session_id, task_id, action, resource_type,
                     resource_id, decision, reason, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(actor_id or "system"), str(session_id or ""),
                    int(task_id) if task_id else None, str(action),
                    str(resource_type or ""), str(resource_id or ""),
                    str(decision), str(reason or ""),
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM audit_events WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return self._audit_row_to_dict(row)

    def list_audit_events(self, action="", decision="", limit=100):
        with self._conn() as c:
            clauses = []
            params = []
            if action:
                clauses.append("action=?")
                params.append(str(action))
            if decision:
                clauses.append("decision=?")
                params.append(str(decision))
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM audit_events{where} ORDER BY id DESC LIMIT ?",
                [*params, max(1, min(int(limit or 100), 500))],
            ).fetchall()
            return [self._audit_row_to_dict(row) for row in rows]

    def register_secret_ref(self, name, env_var, purpose="", allowed_tools=None, created_by="system"):
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO secret_refs
                    (name, env_var, purpose, allowed_tools, created_by, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    env_var=excluded.env_var,
                    purpose=excluded.purpose,
                    allowed_tools=excluded.allowed_tools,
                    enabled=1,
                    updated_at=datetime('now')
                """,
                (
                    str(name), str(env_var), str(purpose or ""),
                    json.dumps(allowed_tools or [], ensure_ascii=False),
                    str(created_by or "system"),
                ),
            )
            return self.get_secret_ref(name, conn=c)

    def get_secret_ref(self, name, conn=None):
        def fetch(c):
            row = c.execute("SELECT * FROM secret_refs WHERE name=?", (str(name),)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["allowed_tools"] = self._json_loads(item.get("allowed_tools"), [])
            item["enabled"] = bool(item.get("enabled"))
            return item
        if conn is not None:
            return fetch(conn)
        with self._conn() as c:
            return fetch(c)

    def list_secret_refs(self):
        with self._conn() as c:
            rows = c.execute("SELECT * FROM secret_refs ORDER BY name").fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["allowed_tools"] = self._json_loads(item.get("allowed_tools"), [])
                item["enabled"] = bool(item.get("enabled"))
                items.append(item)
            return items

    def _audit_row_to_dict(self, row):
        item = dict(row)
        item["details"] = self._json_loads(item.get("details"), {})
        return item

    def list_memories(
        self, memory_type="", include_disabled=False, limit=200,
        actor_id="system", roles=None, workspace_id="default",
    ):
        with self._conn() as c:
            limit = max(1, min(int(limit or 200), 500))
            clauses = []
            params = []
            if memory_type:
                clauses.append("memory_type=?")
                params.append(str(memory_type))
            if not include_disabled:
                clauses.append("enabled=1")
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM memories{where} ORDER BY updated_at DESC, id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [
                self._memory_row_to_dict(r) for r in rows
                if self._check_memory_access(c, r, actor_id, roles, workspace_id, "read")
            ]

    def get_memory(self, memory_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            return self._memory_row_to_dict(row) if row else None

    def set_memory_enabled(self, memory_id, enabled, actor_id="system", change_reason=""):
        with self._conn() as c:
            existing = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            if not existing:
                return None
            version = int(existing["current_version"] or 1) + 1
            c.execute(
                """
                UPDATE memories
                SET enabled=?, current_version=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (1 if enabled else 0, version, int(memory_id)),
            )
            c.execute(
                """
                INSERT INTO memory_versions
                    (memory_id, version, value, source, confidence, enabled,
                     change_type, changed_by, change_reason)
                VALUES (?, ?, ?, ?, ?, ?, 'status_change', ?, ?)
                """,
                (
                    int(memory_id), version, existing["value"], existing["source"],
                    float(existing["confidence"] or 0), 1 if enabled else 0,
                    str(actor_id or "system"), str(change_reason or ""),
                ),
            )
            row = c.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
            return self._memory_row_to_dict(row) if row else None

    def search_memories(
        self, query, memory_type="", limit=20, include_disabled=False,
        actor_id="system", roles=None, workspace_id="default",
    ):
        query = str(query or "").strip()
        if not query:
            return []
        with self._conn() as c:
            limit = max(1, min(int(limit or 20), 100))
            clauses = ["(key LIKE ? OR value LIKE ? OR category LIKE ? OR source LIKE ?)"]
            params = [f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"]
            if memory_type:
                clauses.append("memory_type=?")
                params.append(str(memory_type))
            if not include_disabled:
                clauses.append("enabled=1")
            rows = c.execute(
                f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY confidence DESC, updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [
                self._memory_row_to_dict(r) for r in rows
                if self._check_memory_access(c, r, actor_id, roles, workspace_id, "read")
            ]

    # ── PROFILE ──

    def set_profile(
        self, key: str, value: str, category: str = "general", importance: float = 0.5,
        source: str = "profile_ingestion", actor_id: str = "system",
        evidence=None, conflict_policy: str = "overwrite",
    ):
        result = self.upsert_memory(
            "profile", key, value, category, source, importance,
            actor_id=actor_id, evidence=evidence, conflict_policy=conflict_policy,
        )
        if result.get("review_required"):
            return result
        with self._conn() as c:
            c.execute("""
                INSERT INTO profiles (category, key, value, importance, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    importance = excluded.importance,
                    updated_at = datetime('now')
            """, (category, key, value, importance))
        return result

    def get_profile(self, key: str, category: str = "general") -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM profiles WHERE category=? AND key=?", (category, key)
            ).fetchone()
            return dict(row) if row else None

    def get_all_profiles(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM profiles ORDER BY importance DESC").fetchall()
            return [dict(r) for r in rows]

    # ── PREFERENCES ──

    def set_preference(
        self, key: str, value: str, category: str = "general", confidence: float = 0.5,
        source: str = "preference_ingestion", actor_id: str = "system",
        evidence=None, conflict_policy: str = "overwrite",
    ):
        result = self.upsert_memory(
            "preference", key, value, category, source, confidence,
            actor_id=actor_id, evidence=evidence, conflict_policy=conflict_policy,
        )
        if result.get("review_required"):
            return result
        with self._conn() as c:
            c.execute("""
                INSERT INTO preferences (category, key, value, confidence, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(category, key) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    updated_at = datetime('now')
            """, (category, key, value, confidence))
        return result

    def get_preference(self, key: str, category: str = "general") -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM preferences WHERE category=? AND key=?", (category, key)
            ).fetchone()
            return dict(row) if row else None

    def get_all_preferences(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM preferences ORDER BY confidence DESC").fetchall()
            return [dict(r) for r in rows]

    # ── CONVERSATIONS ──

    def add_message(self, session_id: str, role: str, content: str, tool_calls: str = "", metadata: str = ""):
        with self._conn() as c:
            # Auto-truncate: keep max 100 messages per session
            count = c.execute("SELECT COUNT(*) FROM conversations WHERE session_id=?", (session_id,)).fetchone()[0]
            if count >= 100:
                c.execute(
                    "DELETE FROM conversations WHERE id IN (SELECT id FROM conversations WHERE session_id=? ORDER BY created_at ASC LIMIT 10)",
                    (session_id,)
                )
            c.execute(
                "INSERT INTO conversations (session_id, role, content, tool_calls, metadata) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content[:8000], tool_calls, metadata)
            )

    def get_session_messages(self, session_id: str, limit: int = 30) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content, tool_calls, metadata, created_at FROM conversations WHERE session_id=? ORDER BY id ASC LIMIT ?",
                (session_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_messages(self, session_id: str, n: int = 10) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?",
                (session_id, n)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def get_session_summary(self, session_id: str) -> str:
        """Generate a text summary of recent session activity."""
        msgs = self.get_recent_messages(session_id, 30)
        if not msgs:
            return "No previous conversation."
        summary_parts = []
        user_msgs = [m for m in msgs if m["role"] == "user"]
        for m in user_msgs[-5:]:
            content = m.get("content", "")
            summary_parts.append(f"user asked: {content[:200]}")
        return "Recent conversation:\n" + "\n".join(summary_parts)

    # ── PROJECTS ──

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

    # ── EXPERIENCES ──

    def add_experience(self, task, outcome, lesson="", context="", solution="", tags=None, importance=0.5):
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO experiences (task,outcome,lesson,context,solution,tags,importance) VALUES (?,?,?,?,?,?,?)",
                (task, outcome, lesson, context, solution, json.dumps(tags or []), importance)
            )
            experience_id = int(cursor.lastrowid)
        self.upsert_memory(
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
                "SELECT * FROM experiences ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ── STATS ──

    def list_sessions(self) -> list[dict]:
        """List all conversation sessions with last message preview."""
        with self._conn() as c:
            rows = c.execute("""
                SELECT session_id, MAX(id) AS last_id
                FROM conversations
                GROUP BY session_id
                ORDER BY last_id DESC
            """).fetchall()
            result = []
            for row in rows:
                sid = row["session_id"]
                msgs = c.execute("""SELECT role, content, created_at FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 1""", (sid,)).fetchone()
                first_msgs = c.execute(
                    "SELECT role, content FROM conversations WHERE session_id=? AND role IN ('user','assistant') ORDER BY id ASC LIMIT 6",
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

    def get_stats(self) -> dict:
        with self._conn() as c:
            return {
                "profiles": c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0],
                "preferences": c.execute("SELECT COUNT(*) FROM preferences").fetchone()[0],
                "conversations": c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                "projects": c.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "experiences": c.execute("SELECT COUNT(*) FROM experiences").fetchone()[0],
                "memories": c.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
                "context_snapshots": c.execute("SELECT COUNT(*) FROM context_snapshots").fetchone()[0],
                "tool_executions": c.execute("SELECT COUNT(*) FROM tool_executions").fetchone()[0],
                "mtclaw_traces": c.execute("SELECT COUNT(*) FROM mtclaw_traces").fetchone()[0],
                "memory_reviews_pending": c.execute(
                    "SELECT COUNT(*) FROM memory_reviews WHERE status='pending'"
                ).fetchone()[0],
                "reflection_cards": c.execute("SELECT COUNT(*) FROM reflection_cards").fetchone()[0],
                "reflection_improvements_pending": c.execute(
                    """
                    SELECT COUNT(*) FROM reflection_improvements
                    WHERE status IN ('proposed','approved','testing','validated')
                    """
                ).fetchone()[0],
            }
    # ── KNOWLEDGE ──

    def add_knowledge(self, title, content, category="domain", source="", tags=None, confidence=0.5):
        with self._conn() as c:
            cursor = c.execute("INSERT INTO knowledge (category,title,content,source,tags,confidence) VALUES (?,?,?,?,?,?)",
                               (category, title, content, source, json.dumps(tags or []), confidence))
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return dict(row)

    def search_knowledge(self, query, category="", limit=10):
        with self._conn() as c:
            if category:
                rows = c.execute("SELECT * FROM knowledge WHERE category=? AND (title LIKE ? OR content LIKE ?) ORDER BY confidence DESC LIMIT ?",
                                 (category, f"%{query}%", f"%{query}%", limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM knowledge WHERE title LIKE ? OR content LIKE ? ORDER BY confidence DESC LIMIT ?",
                                 (f"%{query}%", f"%{query}%", limit)).fetchall()
            for r in rows:
                c.execute("UPDATE knowledge SET access_count=access_count+1 WHERE id=?", (r["id"],))
            return [dict(r) for r in rows]

    def get_knowledge_by_id(self, kid):
        with self._conn() as c:
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (kid,)).fetchone()
            if row: c.execute("UPDATE knowledge SET access_count=access_count+1 WHERE id=?", (kid,))
            return dict(row) if row else None

    def update_knowledge(self, kid, title, content, category="domain", source="", tags=None, confidence=0.5):
        with self._conn() as c:
            c.execute(
                """
                UPDATE knowledge
                SET title=?, content=?, category=?, source=?, tags=?, confidence=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (title, content, category, source, json.dumps(tags or []), confidence, int(kid)),
            )
            row = c.execute("SELECT * FROM knowledge WHERE id=?", (int(kid),)).fetchone()
            return dict(row) if row else None

    def delete_knowledge(self, kid):
        with self._conn() as c:
            cursor = c.execute("DELETE FROM knowledge WHERE id=?", (int(kid),))
            return cursor.rowcount > 0

    def delete_knowledge_by_source_prefix(self, prefix):
        with self._conn() as c:
            cursor = c.execute("DELETE FROM knowledge WHERE source LIKE ?", (f"{prefix}%",))
            return cursor.rowcount

    def list_knowledge(self, category=""):
        with self._conn() as c:
            sql = "SELECT * FROM knowledge" + (" WHERE category=?" if category else "") + " ORDER BY access_count DESC"
            rows = c.execute(sql, (category,) if category else ()).fetchall()
            return [dict(r) for r in rows]

    # ── CONTEXT SNAPSHOTS ──

    def add_document(self, title, filename="", file_path="", file_hash="", mime_type="", category="domain", extractor="", status="ready", metadata=None):
        with self._conn() as c:
            existing = c.execute("SELECT id FROM documents WHERE file_hash=? AND file_hash<>''", (file_hash,)).fetchone()
            meta = json.dumps(metadata or {}, ensure_ascii=False)
            if existing:
                doc_id = int(existing["id"])
                c.execute("DELETE FROM document_chunks WHERE document_id=?", (doc_id,))
                c.execute(
                    """
                    UPDATE documents
                    SET title=?, filename=?, file_path=?, mime_type=?, category=?, extractor=?, status=?, metadata=?, updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (title, filename, file_path, mime_type, category, extractor, status, meta, doc_id),
                )
            else:
                cursor = c.execute(
                    """
                    INSERT INTO documents
                        (title, filename, file_path, file_hash, mime_type, category, extractor, status, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (title, filename, file_path, file_hash, mime_type, category, extractor, status, meta),
                )
                doc_id = int(cursor.lastrowid)
            row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            result = dict(row)
            try:
                result["metadata"] = json.loads(result.get("metadata") or "{}")
            except json.JSONDecodeError:
                result["metadata"] = {}
            return result

    def add_document_chunk(self, document_id, chunk_index, content, citation=""):
        with self._conn() as c:
            cursor = c.execute(
                "INSERT INTO document_chunks (document_id, chunk_index, content, citation) VALUES (?, ?, ?, ?)",
                (int(document_id), int(chunk_index), content, citation),
            )
            row = c.execute("SELECT * FROM document_chunks WHERE id=?", (int(cursor.lastrowid),)).fetchone()
            return dict(row)

    def list_documents(self, category=""):
        with self._conn() as c:
            sql = """
                SELECT d.*,
                       (SELECT COUNT(*) FROM document_chunks dc WHERE dc.document_id=d.id) AS chunk_count
                FROM documents d
            """ + (" WHERE d.category=?" if category else "") + " ORDER BY d.updated_at DESC, d.id DESC"
            rows = c.execute(sql, (category,) if category else ()).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(item.get("metadata") or "{}")
                except json.JSONDecodeError:
                    item["metadata"] = {}
                items.append(item)
            return items

    def get_document(self, document_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM documents WHERE id=?", (int(document_id),)).fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.get("metadata") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            return item

    def get_document_chunks(self, document_id, limit=20):
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM document_chunks WHERE document_id=? ORDER BY chunk_index LIMIT ?",
                (int(document_id), int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_document_chunks(self, query, category="", limit=10):
        with self._conn() as c:
            params = [f"%{query}%", f"%{query}%"]
            where = "(d.title LIKE ? OR dc.content LIKE ?)"
            if category:
                where = "d.category=? AND " + where
                params.insert(0, category)
            rows = c.execute(
                f"""
                SELECT dc.*, d.title, d.filename, d.category
                FROM document_chunks dc
                JOIN documents d ON d.id=dc.document_id
                WHERE {where}
                ORDER BY d.updated_at DESC, dc.chunk_index
                LIMIT ?
                """,
                (*params, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_context_snapshot(self, session_id, task="", active_tools=None, environment="", user_intent=""):
        with self._conn() as c:
            c.execute("INSERT INTO context_snapshots (session_id,task_description,active_tools,environment,user_intent) VALUES (?,?,?,?,?)",
                      (session_id, task, json.dumps(active_tools or []), environment, user_intent))
            c.execute("DELETE FROM context_snapshots WHERE id NOT IN (SELECT id FROM context_snapshots WHERE session_id=? ORDER BY id DESC LIMIT 20)",
                      (session_id,))

    def get_latest_context(self, session_id):
        with self._conn() as c:
            row = c.execute("SELECT * FROM context_snapshots WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
            return dict(row) if row else None

    # ── SKILL RECORDS ──

    def record_skill_usage(self, skill_name, success=True, duration_ms=0, feedback="", category="general"):
        with self._conn() as c:
            row = c.execute("SELECT * FROM skill_records WHERE skill_name=?", (skill_name,)).fetchone()
            if row:
                total = row["usage_count"] + 1
                sc = row["success_count"] + (1 if success else 0)
                avg = (row["avg_duration_ms"] * row["usage_count"] + duration_ms) / total
                c.execute("UPDATE skill_records SET usage_count=?,success_count=?,avg_duration_ms=?,last_used=datetime('now'),feedback=?,quality_score=? WHERE skill_name=?",
                          (total, sc, avg, feedback, sc/total, skill_name))
            else:
                c.execute("INSERT INTO skill_records (skill_name,category,usage_count,success_count,avg_duration_ms,last_used,feedback,quality_score) VALUES (?,?,1,?,?,datetime('now'),?,?)",
                          (skill_name, category, 1 if success else 0, duration_ms, feedback, 1.0 if success else 0.3))

    def get_skill_stats(self, skill_name=""):
        with self._conn() as c:
            if skill_name:
                row = c.execute("SELECT * FROM skill_records WHERE skill_name=?", (skill_name,)).fetchone()
                return dict(row) if row else {}
            return [dict(r) for r in c.execute("SELECT * FROM skill_records ORDER BY usage_count DESC").fetchall()]

    def record_tool_execution(self, session_id, tool_name, arguments=None, result=None,
                              status="success", duration_ms=0, requires_confirmation=False):
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO tool_executions
                    (session_id, tool_name, arguments, result, status, duration_ms, requires_confirmation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    tool_name,
                    json.dumps(arguments or {}, ensure_ascii=False),
                    json.dumps(result or {}, ensure_ascii=False),
                    status,
                    float(duration_ms or 0),
                    1 if requires_confirmation else 0,
                ),
            )

    def list_tool_executions(self, session_id="", limit=50):
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            if session_id:
                rows = c.execute(
                    "SELECT * FROM tool_executions WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM tool_executions ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                for key in ("arguments", "result"):
                    try:
                        item[key] = json.loads(item.get(key) or "{}")
                    except Exception:
                        item[key] = {}
                item["requires_confirmation"] = bool(item.get("requires_confirmation"))
                items.append(item)
            return items

    def record_mtclaw_trace(self, session_id, route_status, provider_url="", model="",
                            duration_ms=0, tool_history=None, error=""):
        with self._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO mtclaw_traces
                    (session_id, route_status, provider_url, model, duration_ms, tool_history, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    route_status,
                    provider_url,
                    model,
                    float(duration_ms or 0),
                    json.dumps(tool_history or [], ensure_ascii=False),
                    error,
                ),
            )
            return int(cursor.lastrowid)

    def list_mtclaw_traces(self, session_id="", limit=50):
        with self._conn() as c:
            limit = max(1, min(int(limit or 50), 200))
            if session_id:
                rows = c.execute(
                    "SELECT * FROM mtclaw_traces WHERE session_id=? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM mtclaw_traces ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                try:
                    item["tool_history"] = json.loads(item.get("tool_history") or "[]")
                except json.JSONDecodeError:
                    item["tool_history"] = []
                items.append(item)
            return items

    # ── BULK SEARCH ──

    def search_all_text(self, query, limit=20):
        results = []
        with self._conn() as c:
            rows = c.execute("""
                SELECT id, title AS title, content AS body, category AS type, 'knowledge' AS _source, created_at
                FROM knowledge
                WHERE title LIKE ? OR content LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit)).fetchall()
            results.extend(dict(r) for r in rows)

            rows = c.execute("""
                SELECT id, task AS title, lesson || ' ' || context || ' ' || solution AS body,
                       outcome AS type, 'experiences' AS _source, created_at
                FROM experiences
                WHERE task LIKE ? OR lesson LIKE ? OR context LIKE ? OR solution LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
            results.extend(dict(r) for r in rows)
        return results
