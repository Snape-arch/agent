"""Run closure acceptance and record expiring software evidence."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLAWOS = ROOT / "clawos"
sys.path.insert(0, str(CLAWOS))

from services.evidence_registry import CapabilityEvidenceRegistry
from services.execution_governance import CodingAgentReadiness


CAPABILITY_TESTS = {
    "causal_policy_benchmark": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_policy_materialization_produces_distinct_execution_evidence",
    ],
    "counterfactual_trace_audit": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_counterfactual_audit_and_robust_ope",
    ],
    "robust_ope": [
        "clawos.tests.test_coding_agent_product_p0_p2.ProductClosureTests.test_ope_uses_per_record_policy_and_cross_fitted_reward_model",
    ],
    "coding_context_kernel": [
        "clawos.tests.test_coding_agent_product_p0_p2.ProductClosureTests.test_context_is_injected_and_incremental_index_hits",
    ],
    "network_egress_policy": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_governance_identity_egress_budget_hooks_and_readiness",
    ],
    "production_trace_wiring": [
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_production_entrypoints_enforce_trace_identity_and_signatures",
    ],
    "signed_review_evidence": [
        "clawos.tests.test_coding_agent_product_p0_p2.ProductClosureTests.test_ide_ci_review_and_adaptation_gates",
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_production_entrypoints_enforce_trace_identity_and_signatures",
    ],
    "evaluator_feedback_provenance": [
        "clawos.tests.test_feedback_preference_learning.FeedbackPreferenceLearningTests.test_codex_evaluator_feedback_is_grounded_but_not_a_human_user",
    ],
    "real_repository_benchmark_contract": [
        "clawos.tests.test_product_maturity_p0_p2.ProductMaturityClosureTests.test_real_benchmark_requires_identity_diversity_and_complete_metrics",
        "clawos.tests.test_product_maturity_p0_p2.ProductMaturityClosureTests.test_real_repository_evaluator_uses_isolated_detached_checkout",
    ],
    "structured_patch_loop": [
        "clawos.tests.test_coding_agent_product_p0_p2.ProductClosureTests.test_autonomous_loop_is_model_driven_confirmed_and_checkpointed",
    ],
    "syntax_test_review": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_structured_hunks_and_syntax_review_close_edit_loop",
    ],
    "worktree_isolation": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_worktree_and_commit_are_isolated_and_confirmation_gated",
    ],
    "human_confirmed_commit": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_worktree_and_commit_are_isolated_and_confirmation_gated",
    ],
    "router_shadow_gate": [
        "clawos.tests.test_coding_agent_product_p0_p2.ProductClosureTests.test_learning_registry_enforces_state_machine_and_activation_gate",
    ],
    "agentic_action_loop": [
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_agentic_loop_observes_edits_tests_and_records_bound_trace",
    ],
    "persistent_lsp": [
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_language_server_manager_reuses_process_and_supports_rich_actions",
    ],
    "headless_ide_entry": [
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_production_entrypoints_enforce_trace_identity_and_signatures",
    ],
    "path_scoped_context": [
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_context_auto_compacts_and_applies_only_matching_rules",
    ],
    "recoverable_model_patch_errors": [
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_agentic_loop_repairs_invalid_proposal_inside_same_trajectory",
    ],
    "hosted_ci_reproducibility": [
        "clawos.tests.test_product_maturity_p0_p2.ProductMaturityClosureTests.test_product_report_requires_signed_packaged_ide_evidence",
    ],
    "ide_preview_cancel_contract": [
        "clawos.tests.test_product_maturity_p0_p2.ProductMaturityClosureTests.test_product_report_requires_signed_packaged_ide_evidence",
    ],
    "modular_product_readiness": [
        "clawos.tests.test_product_maturity_p0_p2.ProductMaturityClosureTests.test_modular_router_exposes_read_only_product_report",
    ],
    "trajectory_ranker": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_trajectory_ranker_and_offline_sandbox_respect_data_gates",
    ],
    "offline_policy_sandbox": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_trajectory_ranker_and_offline_sandbox_respect_data_gates",
    ],
    "identity_boundary": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_governance_identity_egress_budget_hooks_and_readiness",
    ],
    "resource_budget": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_governance_identity_egress_budget_hooks_and_readiness",
    ],
    "lifecycle_hooks": [
        "clawos.tests.test_coding_agent_excellence.CodingAgentExcellenceTests.test_governance_identity_egress_budget_hooks_and_readiness",
    ],
    "group_disjoint_policy_evaluation": [
        "clawos.tests.test_agent_learning.AgentLearningTests.test_train_evaluate_activate_and_route_with_policy_network",
    ],
    "paired_canary_control": [
        "clawos.tests.test_self_evolution.SelfEvolutionTests.test_run_moves_through_shadow_canary_before_activation",
    ],
    "unknown_propensity_exclusion": [
        "clawos.tests.test_coding_agent_competitive_p0_p2.CompetitiveClosureTests.test_agentic_actions_enter_learning_trace_without_fake_propensity",
    ],
    "advanced_learning_fail_closed": [
        "clawos.tests.test_product_maturity_p0_p2.ProductMaturityClosureTests.test_product_report_closes_software_but_not_missing_real_evidence",
    ],
}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        default=str(ROOT / "output" / "evidence" / "capabilities.json"),
    )
    parser.add_argument("--expires-days", type=int, default=30)
    args = parser.parse_args()
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(CLAWOS)
    if _git("status", "--porcelain"):
        print("refusing to record release evidence from a dirty worktree")
        return 3
    commit = _git("rev-parse", "HEAD")
    expiry = (
        datetime.now(timezone.utc)
        + timedelta(days=max(1, min(args.expires_days, 90)))
    ).isoformat()
    registry = CapabilityEvidenceRegistry(args.registry)
    capabilities = {
        item
        for requirements in CodingAgentReadiness.REQUIRED.values()
        for item in requirements
    }
    if capabilities != set(CAPABILITY_TESTS):
        print("capability-to-test mapping is incomplete")
        return 4
    digests = []
    for capability in sorted(capabilities):
        test_ids = CAPABILITY_TESTS[capability]
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "-v", *test_ids],
            cwd=ROOT, env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
        transcript = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            print(transcript)
            return result.returncode
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        digests.append(digest)
        registry.record(
            capability,
            status="verified",
            evidence_type="automated_acceptance",
            source="clawos.tests.test_coding_agent_product_p0_p2",
            metrics={"tests_passed": len(test_ids), "tests_failed": 0},
            artifact_digest=digest,
            commit=commit,
            environment=f"python-{sys.version_info.major}.{sys.version_info.minor}",
            expires_at=expiry,
            truth_scope="software",
            test_ids=test_ids,
            worktree_clean=True,
            confirmed=True,
        )
    evidence_digest = hashlib.sha256("".join(digests).encode()).hexdigest()
    report = CodingAgentReadiness.report(
        registry.latest(expected_commit=commit)
    )
    print(
        f"software_p0_p2_closed={report['software_p0_p2_closed']} "
        f"evidence_digest={evidence_digest} commit={commit} expires_at={expiry}"
    )
    return 0 if report["software_p0_p2_closed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
