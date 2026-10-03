import asyncio
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)) if str(ROOT) not in sys.path else None

from memoryos.memory_store import MemoryStore
from services.evolution_experiments import EvolutionExperimentService, candidate_pool, digest
from services.learning_governance import paired_quality_report
from services.advanced_policy_learning import RobustOffPolicyEvaluator


def routing_cases(count=200):
    return [{"id": f"case-{i}", "group_id": f"group-{i}", "query": f"Read evidence case {i}",
             "reviewed_by": "test-fixture", "origin": "curated",
             "route": {"allowed_tools": ["file_read", "file_write", "shell_exec", "web_fetch", "web_search"]},
             "required_tools": ["file_read"], "forbidden_tools": ["file_write", "shell_exec", "web_fetch"]}
            for i in range(count)]


def paired_rows(count=30, control=0.8, candidate=0.9):
    return [{"signal_type": "quality_score", "value": value,
             "metadata": {"evidence_id": f"task-{i}", "task_id": i + 1, "session_id": f"s-{i}",
                          "variant": variant, "observed_stage": "shadow", "input_digest": f"input-{i}"}}
            for i in range(count) for variant, value in (("control", control), ("candidate", candidate))]


class PairedGovernanceTests(unittest.TestCase):
    def test_good_pairs_have_positive_heldout_lift(self):
        report = paired_quality_report(paired_rows())
        self.assertTrue(report["passed"])
        self.assertGreater(report["metrics"]["quality_score"]["confidence_lower"], 0)

    def test_different_metrics_do_not_form_a_pair(self):
        rows = paired_rows()
        for row in rows:
            if row["metadata"]["variant"] == "candidate":
                row["signal_type"] = "retrieval_hit_rate"
        self.assertEqual(paired_quality_report(rows)["matched_task_count"], 0)

    def test_repeated_rows_cannot_inflate_independence(self):
        self.assertFalse(paired_quality_report(paired_rows(1) * 40)["passed"])

    def test_conflicting_duplicate_is_rejected(self):
        rows = paired_rows()
        rows.append({**rows[0], "value": 0.1})
        self.assertIn("conflicting_duplicate", paired_quality_report(rows)["rejected"])

    def test_input_and_identity_mismatch_is_rejected(self):
        rows = paired_rows()
        rows[1]["metadata"]["input_digest"] = "different-input"
        self.assertFalse(paired_quality_report(rows)["passed"])

    def test_aggregate_and_offline_evidence_cannot_be_relabelled(self):
        for source in ("runtime_snapshot", "offline_replay", "policy_materialization"):
            rows = paired_rows()
            for row in rows:
                row["metadata"]["source"] = source
            self.assertEqual(paired_quality_report(rows)["matched_task_count"], 0)

    def test_shadow_is_not_canary_support(self):
        self.assertFalse(paired_quality_report(paired_rows(), stage="canary")["passed"])

    def test_many_rows_in_one_task_cluster_are_not_independent(self):
        rows = paired_rows()
        for row in rows:
            row["metadata"]["cluster_id"] = "same-task"
        self.assertFalse(paired_quality_report(rows)["passed"])

    def test_regression_is_blocked(self):
        self.assertFalse(paired_quality_report(paired_rows(control=0.9, candidate=0.7))["passed"])

    def test_non_finite_values_rejected(self):
        rows = paired_rows()
        rows[0]["value"] = float("nan")
        self.assertFalse(paired_quality_report(rows)["passed"])


class EvolutionExperimentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = MemoryStore(str(Path(self.directory.name) / "store.db"))
        self.service = EvolutionExperimentService(self.store)

    def tearDown(self):
        self.directory.cleanup()

    def freeze(self, cases=None):
        return self.service.freeze(target_type="tool_routing_policy", target_key="default",
                                   baseline_payload={}, cases=routing_cases() if cases is None else cases)

    def test_search_selects_then_replays_only_one_winner_on_holdout(self):
        experiment = self.freeze()
        completed = self.service.replay(experiment["id"])
        report = completed["report"]
        self.assertTrue(report["eligible_for_regression_queue"], report["gates"])
        self.assertGreaterEqual(report["holdout_groups"], 30)
        self.assertFalse(report["holdout_used_for_selection"])
        self.assertFalse(report["runtime_promotion_evidence"])
        self.assertEqual(report["candidate"]["quality"], 1)
        self.assertEqual(report["candidate"]["safety_violations"], 0)
        run = self.service.nominate(experiment["id"])
        self.assertEqual(run["status"], "candidate")
        self.assertEqual(self.service.nominate(experiment["id"])["id"], run["id"])
        self.assertIsNone(self.store.get_runtime_policy("tool_routing_policy", "default"))

    def test_freezing_is_idempotent_and_final_evidence_immutable(self):
        experiment = self.freeze()
        self.assertEqual(self.freeze()["id"], experiment["id"])
        self.service.replay(experiment["id"])
        with self.assertRaisesRegex(ValueError, "already claimed"):
            self.service.replay(experiment["id"])

    def test_only_one_process_can_claim_replay(self):
        experiment = self.freeze()
        def claim(_):
            store = MemoryStore(self.store._db_path)
            try:
                store.claim_evolution_experiment(experiment["id"])
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(claim, range(2))), 1)

    def test_duplicate_input_across_groups_is_rejected(self):
        cases = routing_cases(2)
        cases[1]["query"] = cases[0]["query"]
        with self.assertRaisesRegex(ValueError, "duplicate task input"):
            self.freeze(cases)

    def test_unreviewed_labels_cannot_be_frozen(self):
        cases = routing_cases(2)
        del cases[0]["reviewed_by"]
        with self.assertRaisesRegex(ValueError, "named reviewer"):
            self.freeze(cases)

    def test_stale_baseline_cannot_nominate(self):
        experiment = self.freeze()
        self.service.replay(experiment["id"])
        self.store.set_runtime_policy("tool_routing_policy", "default", {"deny_tools": ["file_write"]})
        with self.assertRaisesRegex(ValueError, "runtime policy changed"):
            self.service.nominate(experiment["id"])

    def test_loaded_executor_fingerprint_is_stable_after_replay(self):
        from services.evolution_experiments import loaded_executor_digest
        before = loaded_executor_digest()
        self.service.replay(self.freeze()["id"])
        self.assertEqual(before, loaded_executor_digest())

    def test_changed_source_or_loaded_executor_invalidates_evidence(self):
        from unittest.mock import patch
        experiment = self.freeze()
        with patch('services.evolution_experiments.source_fingerprints', return_value={}):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                self.service.replay(experiment['id'])
        self.assertEqual(self.store.get_evolution_experiment(experiment['id'])['status'], 'failed')

    def test_direct_legacy_publication_and_unbound_rollback_are_blocked(self):
        with self.assertRaisesRegex(ValueError, 'direct arm publication'):
            self.store.promote_policy_arm(1, 1, 'prompt', 'default')
        with self.assertRaisesRegex(ValueError, 'no bound publication version'):
            self.store.rollback_policy_promotion(1)

    def test_small_holdout_remains_blocked(self):
        report = self.service.replay(self.freeze(routing_cases(30))["id"])["report"]
        self.assertFalse(report["eligible_for_regression_queue"])
        self.assertFalse(report["paired_gate"]["passed"])

    def test_prompt_materialization_is_not_semantic_replay(self):
        with self.assertRaisesRegex(ValueError, "real model outputs"):
            self.service.freeze(target_type="prompt", target_key="default", baseline_payload={}, cases=routing_cases(2))

    def test_real_retrieval_functions_execute_against_frozen_corpus(self):
        documents = [{"source_ref": "fixture:alpha", "title": "memory", "content": "agent memory evidence retrieval"},
                     {"source_ref": "fixture:beta", "title": "policy", "content": "agent memory policy optimization"}]
        cases = [{"id": f"retrieval-{i}", "group_id": f"group-{i}", "query": f"agent memory question {i}",
                  "reviewed_by": "test-fixture", "expected_source_refs": ["fixture:alpha", "fixture:beta"]}
                 for i in range(40)]
        experiment = self.service.freeze(target_type="retrieval_params", target_key="default",
            baseline_payload={"top_k": 1, "citation_aware": True}, cases=cases, documents=documents)
        report = self.service.replay(experiment["id"])["report"]
        self.assertGreater(report["candidate"]["quality"], report["baseline"]["quality"])
        self.assertIn("Relevant knowledge from memory", report["holdout_pairs"][0]["candidate"]["output"])
        self.assertEqual(self.store.list_knowledge(), [])

    def test_candidate_pool_is_bounded_and_does_not_expand_tool_permissions(self):
        pool = candidate_pool("tool_routing_policy", {"allowed_tools": ["file_read"]}, [{"failure_category": "permission"}] * 3)
        self.assertLessEqual(len(pool), 3)
        for candidate in pool:
            self.assertEqual(candidate["payload"]["allowed_tools"], ["file_read"])
            self.assertFalse(candidate["evidence"]["verified_gain"])
        with self.assertRaises(ValueError):
            candidate_pool("python_code", {})

    def test_api_roundtrip_keeps_heldout_replay_separate_from_runtime_gate(self):
        import clawos_server as server
        from starlette.testclient import TestClient
        old = server.g_memory_store
        server.g_memory_store = self.store
        try:
            from fastapi import FastAPI
            app = FastAPI()
            app.middleware('http')(server.workbench_access)
            for route in server.app.routes:
                if route.path.startswith('/api/self-evolution/'):
                    app.router.routes.append(route)
            with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 45678)) as client:
                response = client.post("/api/self-evolution/experiments", json={
                    "target_type": "tool_routing_policy", "target_key": "default", "baseline_payload": {}, "cases": routing_cases()})
                self.assertEqual(response.status_code, 200, response.text)
                eid = response.json()["experiment"]["id"]
                replay = client.post(f"/api/self-evolution/experiments/{eid}/replay")
                self.assertEqual(replay.status_code, 200, replay.text)
                nomination = client.post(f"/api/self-evolution/experiments/{eid}/nominate", json={})
                self.assertEqual(nomination.status_code, 200, nomination.text)
                run = nomination.json()["run"]
                self.assertEqual(run["status"], "candidate")
                self.assertFalse(client.get("/api/self-evolution/board").json()["runs"][0]["paired_quality_evidence"]["passed"])
                self.assertEqual(client.post(f"/api/self-evolution/experiments/{eid}/replay").status_code, 409)
        finally:
            server.g_memory_store = old


class RobustGateTests(unittest.TestCase):
    def test_step_count_does_not_inflate_task_level_effective_support(self):
        records = [{"id": i + 1, "task_id": "one-matched-task" if i < 30 else f"other-{i}",
                    "action_name": "a" if i < 30 else "b", "observed_reward": .9,
                    "policy_trace": {"candidate_set": ["a","b"], "candidate_scores": {"a":1,"b":0},
                                     "selected_action": "a" if i < 30 else "b", "selected_probability": .5,
                                     "policy_version": "test-v1"}} for i in range(100)]
        report = RobustOffPolicyEvaluator().evaluate(records, lambda row, arms: {"a":1,"b":0})
        self.assertGreaterEqual(report['effective_sample_size'], 20)
        self.assertLess(report['cluster_effective_sample_size'], 20)
        self.assertFalse(report['passed'])

    def test_low_ess_cannot_promote_even_with_high_mean(self):
        records = [{"id": i + 1, "action_name": "a" if i == 0 else "b", "observed_reward": 0.9,
                    "policy_trace": {"candidate_set": ["a", "b"], "candidate_scores": {"a": 1, "b": 0},
                                     "selected_action": "a" if i == 0 else "b", "selected_probability": 0.01 if i == 0 else 0.99,
                                     "policy_version": "test-v1"}} for i in range(100)]
        report = RobustOffPolicyEvaluator().evaluate(records, lambda record, arms: {"a": 1, "b": 0})
        self.assertFalse(report["passed"])
        self.assertEqual(report["abort_reason"], "insufficient_support")
        self.assertLess(report["effective_sample_size"], 20)

    def test_missing_counterfactual_trace_is_not_fabricated(self):
        records = [{"id": i, "action_name": "a", "observed_reward": 1, "behavior_propensity": 1} for i in range(100)]
        report = RobustOffPolicyEvaluator().evaluate(records, lambda record, arms: {"a": 1})
        self.assertFalse(report["passed"])
        self.assertEqual(report["counterfactual_audit"]["valid_count"], 0)

    def test_repository_split_holds_out_whole_repository(self):
        from agent_learning import AgentSkillPolicyNetwork
        a = {"task_id": 1, "session_id": "a", "environment_state": {"repository_id": "repo"}}
        b = {"task_id": 2, "session_id": "b", "environment_state": {"repository_id": "repo"}}
        self.assertEqual(AgentSkillPolicyNetwork._split_group(a), AgentSkillPolicyNetwork._split_group(b))


if __name__ == "__main__":
    unittest.main()
