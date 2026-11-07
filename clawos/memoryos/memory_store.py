"""Backward-compatible MemoryStore facade over domain repositories.

All repositories share one SQLite session, lock and nested transaction state.
New domain services may depend on the corresponding repository directly.
"""
from pathlib import Path
from typing import Any

from memoryos.persistence import Repository, SQLiteSession, AtomicConnection, atomic_workflow
from memoryos.schema import Schema
from memoryos.repositories.conversations import ConversationsRepository
from memoryos.repositories.evolution import EvolutionRepository
from memoryos.repositories.knowledge import KnowledgeRepository
from memoryos.repositories.learning import LearningRepository
from memoryos.repositories.memory import MemoryRepository
from memoryos.repositories.policies import PoliciesRepository
from memoryos.repositories.projects import ProjectsRepository
from memoryos.repositories.reflection import ReflectionRepository
from memoryos.repositories.runs import RunsRepository
from memoryos.repositories.security import SecurityRepository
from memoryos.repositories.tasks import TasksRepository
from memoryos.repositories.telemetry import TelemetryRepository


class MemoryStore(Repository):
    def __init__(self, db_path: str = ""):
        session = SQLiteSession(db_path)
        super().__init__(session)
        self._db_path = session._db_path
        self._lock = session._lock
        self.schema = Schema(session)
        self.memory = MemoryRepository(session)
        self.reflection = ReflectionRepository(session)
        self.evolution = EvolutionRepository(session, self.reflection)
        self.tasks = TasksRepository(session, self.evolution.record_self_evolution_quality_signal)
        self.projects = ProjectsRepository(session, self.memory)
        self.conversations = ConversationsRepository(session)
        self.knowledge = KnowledgeRepository(session)
        self.learning = LearningRepository(session)
        self.policies = PoliciesRepository(session)
        self.runs = RunsRepository(session)
        self.security = SecurityRepository(session)
        self.telemetry = TelemetryRepository(session)
        self._init_db()

    def _init_db(self):
        self.schema.initialize()

    def _memory_row_to_dict(self, row) -> dict:
        return self.memory._memory_row_to_dict(row)

    def _task_row_to_dict(self, row) -> dict:
        return self.tasks._task_row_to_dict(row)

    def _step_row_to_dict(self, row) -> dict:
        return self.tasks._step_row_to_dict(row)

    def _event_row_to_dict(self, row) -> dict:
        return self.tasks._event_row_to_dict(row)

    def start_task(self, session_id, title, source='', metadata=None, status='running', idempotency_key='', retry_of=None):
        return self.tasks.start_task(session_id, title, source, metadata, status, idempotency_key, retry_of)

    def finish_task(self, task_id, status, error='', result_payload=None):
        return self.tasks.finish_task(task_id, status, error, result_payload)

    def update_task_metadata(self, task_id, updates, event_type='task_metadata'):
        return self.tasks.update_task_metadata(task_id, updates, event_type)

    def _record_task_policy_signals(self, task):
        return self.tasks._record_task_policy_signals(task)

    def cancel_task(self, task_id, reason='', actor_id='user'):
        return self.tasks.cancel_task(task_id, reason, actor_id)

    def is_task_cancelled(self, task_id):
        return self.tasks.is_task_cancelled(task_id)

    def retry_task(self, task_id, actor_id='user', reason=''):
        return self.tasks.retry_task(task_id, actor_id, reason)

    def recover_interrupted_tasks(self, actor_id='system', create_retries=False):
        return self.tasks.recover_interrupted_tasks(actor_id, create_retries)

    def list_task_events(self, session_id='', after_id=0, limit=100):
        return self.tasks.list_task_events(session_id, after_id, limit)

    def prune_task_events(self, older_than_days=30, retain_latest_per_task=100, dry_run=False, actor_id='system'):
        return self.tasks.prune_task_events(older_than_days, retain_latest_per_task, dry_run, actor_id)

    def add_task_step(self, task_id, step_type, name, status='running', input_data=None):
        return self.tasks.add_task_step(task_id, step_type, name, status, input_data)

    def finish_task_step(self, step_id, status, output_data=None, error=''):
        return self.tasks.finish_task_step(step_id, status, output_data, error)

    def add_task_event(self, task_id, event_type, message='', step_id=None, data=None):
        return self.tasks.add_task_event(task_id, event_type, message, step_id, data)

    def transition_task(self, task_id, status, actor_id='system', reason='', checkpoint=None):
        return self.tasks.transition_task(task_id, status, actor_id, reason, checkpoint)

    def list_tasks(self, session_id='', status='', limit=50):
        return self.tasks.list_tasks(session_id, status, limit)

    def list_tasks_for_soak(self, session_id, limit=200000):
        return self.tasks.list_tasks_for_soak(session_id, limit)

    def list_task_queue(self, statuses=None, limit=50):
        return self.tasks.list_task_queue(statuses, limit)

    def claim_next_task(self, worker_id='worker', statuses=None):
        return self.tasks.claim_next_task(worker_id, statuses)

    def get_task(self, task_id):
        return self.tasks.get_task(task_id)

    def save_run_record(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.runs.save_run_record(record)

    def get_run_record(self, run_id: str) -> dict[str, Any]:
        return self.runs.get_run_record(run_id)

    def list_run_records(self, run_type='', status='', limit=50) -> list[dict[str, Any]]:
        return self.runs.list_run_records(run_type, status, limit)

    def list_failure_cases(self, category='', severity='', limit=50) -> list[dict[str, Any]]:
        return self.runs.list_failure_cases(category, severity, limit)

    def _run_record_from_rows(self, row, artifacts, evidence, failures) -> dict[str, Any]:
        return self.runs._run_record_from_rows(row, artifacts, evidence, failures)

    @staticmethod
    def _group_run_rows(rows) -> dict[str, list[Any]]:
        return RunsRepository._group_run_rows(rows)

    def _artifact_row_to_dict(self, row) -> dict[str, Any]:
        return self.runs._artifact_row_to_dict(row)

    def _run_evidence_row_to_dict(self, row) -> dict[str, Any]:
        return self.runs._run_evidence_row_to_dict(row)

    def _failure_case_row_to_dict(self, row) -> dict[str, Any]:
        return self.runs._failure_case_row_to_dict(row)

    def upsert_memory(self, memory_type, key, value, category='general', source='', confidence=0.5, enabled=True, actor_id='system', owner_id='default', workspace_id='default', evidence=None, change_reason='', conflict_policy='overwrite'):
        return self.memory.upsert_memory(memory_type, key, value, category, source, confidence, enabled, actor_id, owner_id, workspace_id, evidence, change_reason, conflict_policy)

    def _insert_memory_evidence(self, conn, memory_id, version_id, evidence, actor_id='system'):
        return self.memory._insert_memory_evidence(conn, memory_id, version_id, evidence, actor_id)

    def list_memory_versions(self, memory_id, limit=100):
        return self.memory.list_memory_versions(memory_id, limit)

    def list_memory_evidence(self, memory_id, limit=100):
        return self.memory.list_memory_evidence(memory_id, limit)

    def _version_row_to_dict(self, row):
        return self.memory._version_row_to_dict(row)

    def _evidence_row_to_dict(self, row):
        return self.memory._evidence_row_to_dict(row)

    def list_memory_reviews(self, status='pending', limit=100):
        return self.memory.list_memory_reviews(status, limit)

    def resolve_memory_review(self, review_id, decision, reviewer='system', notes=''):
        return self.memory.resolve_memory_review(review_id, decision, reviewer, notes)

    def grant_memory_acl(self, memory_id, principal_type, principal_id, permission, granted_by='system'):
        return self.memory.grant_memory_acl(memory_id, principal_type, principal_id, permission, granted_by)

    def list_memory_acl(self, memory_id):
        return self.memory.list_memory_acl(memory_id)

    def check_memory_access(self, memory_id, actor_id='default', roles=None, workspace_id='default', permission='read'):
        return self.memory.check_memory_access(memory_id, actor_id, roles, workspace_id, permission)

    def _check_memory_access(self, conn, memory, actor_id, roles, workspace_id, permission):
        return self.memory._check_memory_access(conn, memory, actor_id, roles, workspace_id, permission)

    def record_retrieval_evaluation(self, name, top_k, metrics, cases, created_by='system'):
        return self.memory.record_retrieval_evaluation(name, top_k, metrics, cases, created_by)

    def get_retrieval_evaluation(self, run_id, conn=None):
        return self.memory.get_retrieval_evaluation(run_id, conn)

    def create_reflection_card(self, card, improvements=None):
        return self.reflection.create_reflection_card(card, improvements)

    def list_reflection_cards(self, limit=20, session_id=''):
        return self.reflection.list_reflection_cards(limit, session_id)

    def get_reflection_card(self, card_id):
        return self.reflection.get_reflection_card(card_id)

    def update_reflection_feedback(self, card_id, feedback, actor_id='system'):
        return self.reflection.update_reflection_feedback(card_id, feedback, actor_id)

    def list_reflection_improvements(self, status='', limit=100):
        return self.reflection.list_reflection_improvements(status, limit)

    def get_reflection_improvement(self, improvement_id, conn=None):
        return self.reflection.get_reflection_improvement(improvement_id, conn)

    def update_reflection_improvement(self, improvement_id, from_status, to_status, actor_id='system', reason='', data=None, fields=None):
        return self.reflection.update_reflection_improvement(improvement_id, from_status, to_status, actor_id, reason, data, fields)

    def get_runtime_policy(self, target_type, target_key, conn=None):
        return self.reflection.get_runtime_policy(target_type, target_key, conn)

    def set_runtime_policy(self, target_type, target_key, payload, actor_id='system'):
        return self.reflection.set_runtime_policy(target_type, target_key, payload, actor_id)

    def create_evolution_experiment(self, definition, definition_digest, created_by='system'):
        return self.evolution.create_evolution_experiment(definition, definition_digest, created_by)

    def get_evolution_experiment(self, experiment_id):
        return self.evolution.get_evolution_experiment(experiment_id)

    def list_evolution_experiments(self, limit=50):
        return self.evolution.list_evolution_experiments(limit)

    def claim_evolution_experiment(self, experiment_id):
        return self.evolution.claim_evolution_experiment(experiment_id)

    def finish_evolution_experiment(self, experiment_id, report, failed=False, *, attempt_token=''):
        return self.evolution.finish_evolution_experiment(experiment_id, report, failed, attempt_token=attempt_token)

    def create_self_evolution_run(self, title, target_type, target_key, baseline_payload, candidate_payload, benchmarks=None, conclusion='', publish_decision='pending', status='candidate', gate_result=None, created_by='system'):
        return self.evolution.create_self_evolution_run(title, target_type, target_key, baseline_payload, candidate_payload, benchmarks, conclusion, publish_decision, status, gate_result, created_by)

    def list_self_evolution_runs(self, status='', limit=100):
        return self.evolution.list_self_evolution_runs(status, limit)

    def get_self_evolution_run(self, run_id, conn=None):
        return self.evolution.get_self_evolution_run(run_id, conn)

    def update_self_evolution_run(self, run_id, status=None, benchmarks=None, gate_result=None, conclusion=None, publish_decision=None, rollback_payload=None, published_by=None, published_at=None, release_stage=None, traffic_percent=None, quality_signals=None):
        return self.evolution.update_self_evolution_run(run_id, status, benchmarks, gate_result, conclusion, publish_decision, rollback_payload, published_by, published_at, release_stage, traffic_percent, quality_signals)

    def publish_self_evolution_run(self, run_id, actor_id='system', reason=''):
        return self.evolution.publish_self_evolution_run(run_id, actor_id, reason)

    def rollback_self_evolution_run(self, run_id, actor_id='user', reason=''):
        return self.evolution.rollback_self_evolution_run(run_id, actor_id, reason)

    def record_self_evolution_quality_signal(self, run_id, signal_type, value, metadata=None, created_by='system'):
        return self.evolution.record_self_evolution_quality_signal(run_id, signal_type, value, metadata, created_by)

    def list_self_evolution_quality_signals(self, run_id, limit=100):
        return self.evolution.list_self_evolution_quality_signals(run_id, limit)

    def runtime_quality_snapshot(self):
        return self.evolution.runtime_quality_snapshot()

    def _aggregate_self_evolution_quality_signals(self, run_id, conn=None):
        return self.evolution._aggregate_self_evolution_quality_signals(run_id, conn)

    def publish_reflection_improvement(self, improvement_id, actor_id='system', reason=''):
        return self.evolution.publish_reflection_improvement(improvement_id, actor_id, reason)

    def rollback_reflection_improvement(self, improvement_id, actor_id='system', reason=''):
        return self.evolution.rollback_reflection_improvement(improvement_id, actor_id, reason)

    def _reflection_card_from_row(self, row):
        return self.reflection._reflection_card_from_row(row)

    def _reflection_improvement_from_row(self, row):
        return self.reflection._reflection_improvement_from_row(row)

    def _self_evolution_run_from_row(self, row):
        return self.evolution._self_evolution_run_from_row(row)

    def _self_evolution_signal_from_row(self, row):
        return self.evolution._self_evolution_signal_from_row(row)

    def upsert_policy_group(self, name, optimizer_type='contextual_ucb', exploration_rate=0.1):
        return self.policies.upsert_policy_group(name, optimizer_type, exploration_rate)

    def upsert_policy_arm(self, group_name, name, arm_type, payload=None, contexts=None, status='active'):
        return self.policies.upsert_policy_arm(group_name, name, arm_type, payload, contexts, status)

    def list_policy_arms(self, group_name, include_inactive=False):
        return self.policies.list_policy_arms(group_name, include_inactive)

    def create_policy_selection(self, group_id, arm_id, context, score, exploration=False, task_id=None, session_id=''):
        return self.policies.create_policy_selection(group_id, arm_id, context, score, exploration, task_id, session_id)

    def get_policy_selection(self, selection_id, conn=None):
        return self.policies.get_policy_selection(selection_id, conn)

    def record_policy_reward(self, selection_id, success, satisfaction, latency_cost, resource_cost, reward, evidence=None):
        return self.policies.record_policy_reward(selection_id, success, satisfaction, latency_cost, resource_cost, reward, evidence)

    def policy_group_stats(self, group_name):
        return self.policies.policy_group_stats(group_name)

    def promote_policy_arm(self, group_id, arm_id, target_type, target_key, actor_id='system'):
        return self.policies.promote_policy_arm(group_id, arm_id, target_type, target_key, actor_id)

    def rollback_policy_promotion(self, promotion_id, actor_id='system'):
        return self.policies.rollback_policy_promotion(promotion_id, actor_id)

    def get_policy_promotion(self, promotion_id, conn=None):
        return self.policies.get_policy_promotion(promotion_id, conn)

    def _policy_arm_from_row(self, row):
        return self.policies._policy_arm_from_row(row)

    def ensure_agent_trajectory(self, task_id, scenario='general', task_context=None, user_context=None, environment_state=None, policy_version=''):
        return self.learning.ensure_agent_trajectory(task_id, scenario, task_context, user_context, environment_state, policy_version)

    def append_agent_trajectory_step(self, task_id, state, action_type, action_name, action_payload=None, observation=None, reward_components=None, step_reward=None, policy_selection_id=None, behavior_propensity=1.0, safety_violation=False):
        return self.learning.append_agent_trajectory_step(task_id, state, action_type, action_name, action_payload, observation, reward_components, step_reward, policy_selection_id, behavior_propensity, safety_violation)

    def complete_agent_trajectory_selection(self, selection_id, reward, reward_components=None, observation=None):
        return self.learning.complete_agent_trajectory_selection(selection_id, reward, reward_components, observation)

    def complete_agent_trajectory(self, task_id, outcome, reward_components, total_reward, gamma=0.95):
        return self.learning.complete_agent_trajectory(task_id, outcome, reward_components, total_reward, gamma)

    def get_agent_trajectory(self, trajectory_id=None, task_id=None):
        return self.learning.get_agent_trajectory(trajectory_id, task_id)

    def list_agent_trajectories(self, status='', scenario='', limit=100):
        return self.learning.list_agent_trajectories(status, scenario, limit)

    def list_agent_learning_examples(self, group_name='', limit=5000):
        return self.learning.list_agent_learning_examples(group_name, limit)

    def create_agent_preference_pair(self, task_context, chosen, rejected, owner_id='default', chosen_trajectory_id=None, rejected_trajectory_id=None, source='explicit_user', confidence=1.0, metadata=None):
        return self.learning.create_agent_preference_pair(task_context, chosen, rejected, owner_id, chosen_trajectory_id, rejected_trajectory_id, source, confidence, metadata)

    def list_agent_preference_pairs(self, owner_id='', limit=500):
        return self.learning.list_agent_preference_pairs(owner_id, limit)

    def create_agent_feedback(self, task_id, signal_type, score=None, owner_id='default', reason_category='', correction=None, metadata=None, explicit=True, idempotency_key=''):
        return self.learning.create_agent_feedback(task_id, signal_type, score, owner_id, reason_category, correction, metadata, explicit, idempotency_key)

    def list_agent_feedback(self, task_id=None, owner_id='', explicit_only=False, limit=1000):
        return self.learning.list_agent_feedback(task_id, owner_id, explicit_only, limit)

    def revise_policy_rewards_for_task(self, task_id, satisfaction, feedback_id):
        return self.learning.revise_policy_rewards_for_task(task_id, satisfaction, feedback_id)

    def agent_learning_data_quality(self):
        return self.learning.agent_learning_data_quality()

    def create_reward_calibration(self, weights, training_metrics, thresholds, data_digest, trained_by='system'):
        return self.learning.create_reward_calibration(weights, training_metrics, thresholds, data_digest, trained_by)

    def get_reward_calibration(self, calibration_id=None, status='', conn=None):
        return self.learning.get_reward_calibration(calibration_id, status, conn)

    def list_reward_calibrations(self, limit=100):
        return self.learning.list_reward_calibrations(limit)

    def evaluate_reward_calibration(self, calibration_id, metrics, passed):
        return self.learning.evaluate_reward_calibration(calibration_id, metrics, passed)

    def activate_reward_calibration(self, calibration_id):
        return self.learning.activate_reward_calibration(calibration_id)

    def create_preference_ranker_model(self, feature_dim, weights, training_metrics, data_digest, trained_by='system'):
        return self.learning.create_preference_ranker_model(feature_dim, weights, training_metrics, data_digest, trained_by)

    def get_preference_ranker_model(self, model_id=None, status='', conn=None):
        return self.learning.get_preference_ranker_model(model_id, status, conn)

    def list_preference_ranker_models(self, limit=100):
        return self.learning.list_preference_ranker_models(limit)

    def evaluate_preference_ranker_model(self, model_id, metrics, passed):
        return self.learning.evaluate_preference_ranker_model(model_id, metrics, passed)

    def activate_preference_ranker_model(self, model_id):
        return self.learning.activate_preference_ranker_model(model_id)

    def create_agent_policy_model(self, group_name, feature_dim, weights, training_metrics, data_digest, trained_by='system'):
        return self.learning.create_agent_policy_model(group_name, feature_dim, weights, training_metrics, data_digest, trained_by)

    def get_agent_policy_model(self, model_id=None, group_name='', status='', conn=None):
        return self.learning.get_agent_policy_model(model_id, group_name, status, conn)

    def list_agent_policy_models(self, group_name='', limit=100):
        return self.learning.list_agent_policy_models(group_name, limit)

    def evaluate_agent_policy_model(self, model_id, metrics, passed):
        return self.learning.evaluate_agent_policy_model(model_id, metrics, passed)

    def activate_agent_policy_model(self, model_id):
        return self.learning.activate_agent_policy_model(model_id)

    def rollback_agent_policy_model(self, model_id):
        return self.learning.rollback_agent_policy_model(model_id)

    def _agent_trajectory_from_row(self, row):
        return self.learning._agent_trajectory_from_row(row)

    def _agent_trajectory_step_from_row(self, row):
        return self.learning._agent_trajectory_step_from_row(row)

    def _agent_preference_from_row(self, row):
        return self.learning._agent_preference_from_row(row)

    def _agent_feedback_from_row(self, row):
        return self.learning._agent_feedback_from_row(row)

    def _reward_calibration_from_row(self, row):
        return self.learning._reward_calibration_from_row(row)

    def _preference_ranker_from_row(self, row):
        return self.learning._preference_ranker_from_row(row)

    def _agent_policy_model_from_row(self, row):
        return self.learning._agent_policy_model_from_row(row)

    def record_audit_event(self, action, decision='allow', actor_id='system', session_id='', task_id=None, resource_type='', resource_id='', reason='', details=None):
        return self.security.record_audit_event(action, decision, actor_id, session_id, task_id, resource_type, resource_id, reason, details)

    def list_audit_events(self, action='', decision='', limit=100):
        return self.security.list_audit_events(action, decision, limit)

    def register_secret_ref(self, name, env_var, purpose='', allowed_tools=None, created_by='system'):
        return self.security.register_secret_ref(name, env_var, purpose, allowed_tools, created_by)

    def get_secret_ref(self, name, conn=None):
        return self.security.get_secret_ref(name, conn)

    def list_secret_refs(self):
        return self.security.list_secret_refs()

    def _audit_row_to_dict(self, row):
        return self.security._audit_row_to_dict(row)

    def list_memories(self, memory_type='', include_disabled=False, limit=200, actor_id='system', roles=None, workspace_id='default'):
        return self.memory.list_memories(memory_type, include_disabled, limit, actor_id, roles, workspace_id)

    def get_memory(self, memory_id):
        return self.memory.get_memory(memory_id)

    def set_memory_enabled(self, memory_id, enabled, actor_id='system', change_reason=''):
        return self.memory.set_memory_enabled(memory_id, enabled, actor_id, change_reason)

    def search_memories(self, query, memory_type='', limit=20, include_disabled=False, actor_id='system', roles=None, workspace_id='default'):
        return self.memory.search_memories(query, memory_type, limit, include_disabled, actor_id, roles, workspace_id)

    def set_profile(self, key: str, value: str, category: str='general', importance: float=0.5, source: str='profile_ingestion', actor_id: str='system', evidence=None, conflict_policy: str='overwrite'):
        return self.memory.set_profile(key, value, category, importance, source, actor_id, evidence, conflict_policy)

    @staticmethod
    def _effective_legacy_memory(connection, row, memory_type):
        return MemoryRepository._effective_legacy_memory(connection, row, memory_type)

    def get_profile(self, key: str, category: str='general') -> dict | None:
        return self.memory.get_profile(key, category)

    def get_all_profiles(self) -> list[dict]:
        return self.memory.get_all_profiles()

    def set_preference(self, key: str, value: str, category: str='general', confidence: float=0.5, source: str='preference_ingestion', actor_id: str='system', evidence=None, conflict_policy: str='overwrite'):
        return self.memory.set_preference(key, value, category, confidence, source, actor_id, evidence, conflict_policy)

    def get_preference(self, key: str, category: str='general') -> dict | None:
        return self.memory.get_preference(key, category)

    def get_all_preferences(self) -> list[dict]:
        return self.memory.get_all_preferences()

    def add_message(self, session_id: str, role: str, content: str, tool_calls: str='', metadata: str=''):
        return self.conversations.add_message(session_id, role, content, tool_calls, metadata)

    def get_session_messages(self, session_id: str, limit: int=30) -> list[dict]:
        return self.conversations.get_session_messages(session_id, limit)

    def get_recent_messages(self, session_id: str, n: int=10) -> list[dict]:
        return self.conversations.get_recent_messages(session_id, n)

    def conversation_history(self, session_id, limit=50, before_id=0):
        return self.conversations.conversation_history(session_id, limit, before_id)

    def get_session_summary(self, session_id: str) -> str:
        return self.conversations.get_session_summary(session_id)

    def get_persisted_session_summary(self, session_id: str) -> str:
        return self.conversations.get_persisted_session_summary(session_id)

    def save_session_summary(self, session_id: str, summary: str, source_message_count: int) -> None:
        return self.conversations.save_session_summary(session_id, summary, source_message_count)

    def archive_session_messages(self, session_id, message_ids):
        return self.conversations.archive_session_messages(session_id, message_ids)

    def delete_oldest_session_messages(self, session_id: str, count: int) -> int:
        return self.conversations.delete_oldest_session_messages(session_id, count)

    def upsert_project(self, name: str, description: str='', goals: list | None=None, progress: str='', status: str='active', team: list | None=None):
        return self.projects.upsert_project(name, description, goals, progress, status, team)

    def get_project(self, name: str) -> dict | None:
        return self.projects.get_project(name)

    def list_projects(self, status: str='') -> list[dict]:
        return self.projects.list_projects(status)

    def add_experience(self, task, outcome, lesson='', context='', solution='', tags=None, importance=0.5):
        return self.projects.add_experience(task, outcome, lesson, context, solution, tags, importance)

    def get_recent_experiences(self, limit: int=20) -> list[dict]:
        return self.projects.get_recent_experiences(limit)

    def list_sessions(self, query='', limit=500) -> list[dict]:
        return self.projects.list_sessions(query, limit)

    def _summarize_session(self, rows, fallback: str) -> tuple[str, list[str]]:
        return self.projects._summarize_session(rows, fallback)

    def get_stats(self) -> dict:
        return self.telemetry.get_stats()

    def add_knowledge(self, title, content, category='domain', source='', tags=None, confidence=0.5, *, reviewed_chunk_id=None):
        return self.knowledge.add_knowledge(title, content, category, source, tags, confidence, reviewed_chunk_id=reviewed_chunk_id)

    def absorb_knowledge(self, **payload):
        return self.knowledge.absorb_knowledge(**payload)

    def search_knowledge_v2(self, query, category='', limit=10, **scope):
        return self.knowledge.search_knowledge_v2(query, category, limit, **scope)

    def knowledge_context_pack(self, query, category='', limit=6, token_budget=1600, **scope):
        return self.knowledge.knowledge_context_pack(query, category, limit, token_budget, **scope)

    def answer_from_knowledge(self, query, category='', limit=6, token_budget=1600, session_id='', task_id='', **scope):
        return self.knowledge.answer_from_knowledge(query, category, limit, token_budget, session_id, task_id, **scope)

    def knowledge_v2_stats(self):
        return self.knowledge.knowledge_v2_stats()

    def resolve_knowledge_conflict(self, conflict_id, decision, reviewer='system', reason=''):
        return self.knowledge.resolve_knowledge_conflict(conflict_id, decision, reviewer, reason)

    def list_knowledge_conflicts(self, status='pending', limit=100):
        return self.knowledge.list_knowledge_conflicts(status, limit)

    def backfill_knowledge_v2(self, limit=10000):
        return self.knowledge.backfill_knowledge_v2(limit)

    def record_knowledge_usage(self, knowledge_ids, **payload):
        return self.knowledge.record_knowledge_usage(knowledge_ids, **payload)

    def search_knowledge(self, query, category='', limit=10):
        return self.knowledge.search_knowledge(query, category, limit)

    def get_knowledge_by_id(self, kid):
        return self.knowledge.get_knowledge_by_id(kid)

    def update_knowledge(self, kid, title, content, category='domain', source='', tags=None, confidence=0.5):
        return self.knowledge.update_knowledge(kid, title, content, category, source, tags, confidence)

    def delete_knowledge(self, kid):
        return self.knowledge.delete_knowledge(kid)

    def delete_knowledge_by_source_prefix(self, prefix):
        return self.knowledge.delete_knowledge_by_source_prefix(prefix)

    def list_knowledge(self, category=''):
        return self.knowledge.list_knowledge(category)

    def document_source_usable(self, source, knowledge_id=None, version=None):
        return self.knowledge.document_source_usable(source, knowledge_id, version)

    def add_document(self, title, filename='', file_path='', file_hash='', mime_type='', category='domain', extractor='', status='ready', metadata=None, *, document_id=0):
        return self.knowledge.add_document(title, filename, file_path, file_hash, mime_type, category, extractor, status, metadata, document_id=document_id)

    def add_document_chunk(self, document_id, chunk_index, content, citation='', metadata=None):
        return self.knowledge.add_document_chunk(document_id, chunk_index, content, citation, metadata)

    def list_documents(self, category='', *, include_review=False):
        return self.knowledge.list_documents(category, include_review=include_review)

    def get_document(self, document_id, *, include_review=False):
        return self.knowledge.get_document(document_id, include_review=include_review)

    def get_document_chunks(self, document_id, limit=20, *, include_review=False, offset=0):
        return self.knowledge.get_document_chunks(document_id, limit, include_review=include_review, offset=offset)

    def iter_evidence_chunks(self, document_id=0, category=''):
        return self.knowledge.iter_evidence_chunks(document_id, category)

    def search_document_chunks(self, query, category='', limit=10):
        return self.knowledge.search_document_chunks(query, category, limit)

    def save_context_snapshot(self, session_id, task='', active_tools=None, environment='', user_intent=''):
        return self.telemetry.save_context_snapshot(session_id, task, active_tools, environment, user_intent)

    def get_latest_context(self, session_id):
        return self.telemetry.get_latest_context(session_id)

    def record_skill_usage(self, skill_name, success=True, duration_ms=0, feedback='', category='general'):
        return self.telemetry.record_skill_usage(skill_name, success, duration_ms, feedback, category)

    def get_skill_stats(self, skill_name=''):
        return self.telemetry.get_skill_stats(skill_name)

    def record_tool_execution(self, session_id, tool_name, arguments=None, result=None, status='success', duration_ms=0, requires_confirmation=False):
        return self.telemetry.record_tool_execution(session_id, tool_name, arguments, result, status, duration_ms, requires_confirmation)

    def list_tool_executions(self, session_id='', limit=50):
        return self.telemetry.list_tool_executions(session_id, limit)

    def record_mtclaw_trace(self, session_id, route_status, provider_url='', model='', duration_ms=0, tool_history=None, error=''):
        return self.telemetry.record_mtclaw_trace(session_id, route_status, provider_url, model, duration_ms, tool_history, error)

    def list_mtclaw_traces(self, session_id='', limit=50):
        return self.telemetry.list_mtclaw_traces(session_id, limit)

    def search_all_text(self, query, limit=20):
        return self.telemetry.search_all_text(query, limit)
