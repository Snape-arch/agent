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
CREATE TABLE IF NOT EXISTS conversation_summaries (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    source_message_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);
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
    metadata TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_document_chunks_doc ON document_chunks(document_id, chunk_index);
CREATE TABLE IF NOT EXISTS document_review_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    revision TEXT NOT NULL,
    actor TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
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
CREATE TABLE IF NOT EXISTS conversation_archive (
    original_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    tool_calls TEXT, metadata TEXT, created_at TEXT,
    archived_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_conversation_archive_session ON conversation_archive(session_id,original_id);
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
CREATE TABLE IF NOT EXISTS evolution_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    definition TEXT NOT NULL,
    definition_digest TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'frozen',
    report TEXT NOT NULL DEFAULT '{}',
    created_by TEXT NOT NULL DEFAULT 'system',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS evolution_attempts (
    token TEXT PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES evolution_experiments(id),
    status TEXT NOT NULL,
    lease_until REAL NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evolution_attempts_exp ON evolution_attempts(experiment_id, started_at);
CREATE TABLE IF NOT EXISTS evolution_case_results (
    experiment_id INTEGER NOT NULL REFERENCES evolution_experiments(id),
    case_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    outcome_digest TEXT NOT NULL,
    attempt_token TEXT NOT NULL,
    PRIMARY KEY(experiment_id,case_id,candidate_id)
);
CREATE TABLE IF NOT EXISTS evolution_exposures (
    input_key TEXT NOT NULL,
    experiment_id INTEGER NOT NULL REFERENCES evolution_experiments(id),
    split TEXT NOT NULL,
    PRIMARY KEY(input_key,experiment_id)
);
CREATE TABLE IF NOT EXISTS evolution_review_packets (
    experiment_id INTEGER PRIMARY KEY REFERENCES evolution_experiments(id),
    packet_digest TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS evolution_reviews (
    experiment_id INTEGER NOT NULL REFERENCES evolution_review_packets(experiment_id),
    reviewer TEXT NOT NULL,
    submission TEXT NOT NULL,
    submission_digest TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(experiment_id,reviewer)
);
CREATE TABLE IF NOT EXISTS evolution_model_jobs (
    experiment_id INTEGER PRIMARY KEY REFERENCES evolution_experiments(id),
    token TEXT NOT NULL,
    status TEXT NOT NULL,
    lease_until REAL NOT NULL,
    specification TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS evolution_model_receipts (
    experiment_id INTEGER NOT NULL REFERENCES evolution_experiments(id),
    case_id TEXT NOT NULL,
    variant TEXT NOT NULL,
    receipt TEXT NOT NULL,
    receipt_digest TEXT NOT NULL,
    PRIMARY KEY(experiment_id,case_id,variant)
);
CREATE TABLE IF NOT EXISTS evolution_review_grants (
    experiment_id INTEGER NOT NULL REFERENCES evolution_review_packets(experiment_id),
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    granted_by TEXT NOT NULL,
    PRIMARY KEY(experiment_id,user_id)
);
CREATE TABLE IF NOT EXISTS evolution_adjudications (
    experiment_id INTEGER NOT NULL REFERENCES evolution_review_packets(experiment_id),
    entry_id TEXT NOT NULL,
    review_set_digest TEXT NOT NULL,
    adjudicator TEXT NOT NULL,
    decision TEXT NOT NULL,
    decision_digest TEXT NOT NULL,
    PRIMARY KEY(experiment_id,entry_id,review_set_digest)
);
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
