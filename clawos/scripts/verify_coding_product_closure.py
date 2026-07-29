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
