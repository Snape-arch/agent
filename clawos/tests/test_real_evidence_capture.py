import tempfile
import unittest
from pathlib import Path

from services.real_evidence_capture import EvidenceRunBuilder
from services.competition_evidence_service import CompetitionEvidenceService


class RealEvidenceCaptureTests(unittest.TestCase):
    def test_builder_emits_a_strictly_verifiable_chain(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rejected = root / "rejected.diff"
            artifact = root / "accepted.diff"
            rejected.write_text("unsafe patch\n", encoding="utf-8")
            artifact.write_text("real patch\n", encoding="utf-8")
            builder = EvidenceRunBuilder(
                scenario="coding",
                title="Repair repository parser",
                actor="campaign-coordinator",
                provider="qwen",
                model="Qwen3.5-9B-Q4_K_M",
                input_origin="repository",
                source_uri="https://github.com/Snape-arch/agent",
            )
            builder.capture("user_goal", [{"request_id": "issue-1", "source_ref": "repository:issue-1"}])
            builder.capture("agent_plan", [{"plan_id": "plan-1", "risk_count": 1}])
            builder.capture("subagent_delegation", [{
                "run_id": "subagents-1", "role_type": role, "role_id": role,
                "provider": "qwen", "model": "Qwen3.5-9B-Q4_K_M", "tokens": 120,
                "started_at": "2026-07-14T10:00:00+00:00",
                "completed_at": "2026-07-14T10:00:01+00:00", "duration_ms": 900,
            } for role in ("planner", "executor", "reviewer")])
            builder.capture("tool_trace", [{
                "sequence": 1, "tool": "unittest", "timestamp": "2026-07-14T10:00:00+00:00",
                "completed_at": "2026-07-14T10:00:01+00:00", "duration_ms": 12,
                "status": "failed", "arguments_hash": "d" * 64, "result_hash": "e" * 64,
            }, {
                "sequence": 2, "tool": "unittest", "timestamp": "2026-07-14T10:01:00+00:00",
                "completed_at": "2026-07-14T10:01:01+00:00", "duration_ms": 14,
                "status": "passed", "arguments_hash": "f" * 64, "result_hash": "a" * 64,
            }])
            builder.add_failure(
                failure_id="review-rejected-v1",
                category="reviewer_disagreement",
                reason="Reviewer rejected the first implementation.",
                remediation="Refactor and rerun the gate.",
            )
            builder.add_artifact("rejected-diff", "patch", "Rejected diff", rejected)
            builder.add_artifact("accepted-diff", "patch", "Accepted diff", artifact)
            builder.capture("rework", [{
                "failure_id": "review-rejected-v1", "before_artifact_id": "rejected-diff",
                "after_artifact_id": "accepted-diff", "reviewer_decision": "released",
                "started_at": "2026-07-14T10:00:00+00:00",
                "completed_at": "2026-07-14T10:01:00+00:00", "duration_ms": 60000,
            }], status="reworked")
            builder.capture("quality_gate", [{
                "reviewer": "reviewer",
                "decision": "release",
                "checks": ["unit", "diff"],
            }], status="passed")
            builder.capture("final_artifacts", [{"artifact_id": "accepted-diff"}])
            builder.capture("knowledge_capture", [{
                "knowledge_id": "knowledge-1", "lookup_verified": True,
                "lookup_query": "repository parser repair", "retrieved_at": "2026-07-14T10:02:00+00:00",
                "result_hash": "b" * 64, "lookup_artifact_id": "accepted-diff",
            }])
            run = builder.finish()
            result = CompetitionEvidenceService.validate(run)
            self.assertTrue(result["eligible"], result["failures"])


if __name__ == "__main__":
    unittest.main()
