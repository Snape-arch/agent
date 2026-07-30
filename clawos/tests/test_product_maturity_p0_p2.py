from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from api.product_readiness import create_product_readiness_router
from scripts.run_local_coding_evaluator import _prepare_repository
from services.coding_quality_service import CodingOutcomeBenchmark
from services.product_readiness_service import ProductReadinessService


ROOT = Path(__file__).resolve().parents[2]


def run_evidence(policy_id: str, passed: int) -> dict:
    return {
        "completed": True,
        "hidden_tests_passed": passed,
        "hidden_tests_total": 10,
        "patch_digest": f"patch-{policy_id}",
        "test_evidence_digest": f"tests-{policy_id}",
        "policy_id": policy_id,
        "duration_ms": 100,
        "regression_count": 0,
        "rollback_occurred": False,
        "human_intervention": False,
        "normalized_cost": 1.0,
    }


class ProductMaturityClosureTests(unittest.TestCase):
    def test_real_repository_evaluator_uses_isolated_detached_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=source, check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=source, check=True,
            )
            (source / "module.py").write_text("value = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=source, check=True)
            subprocess.run(
                ["git", "commit", "-m", "fixture"],
                cwd=source, check=True, capture_output=True,
            )
            output = root / "output"
            output.mkdir()
            repo, origin, objective, hidden = _prepare_repository(
                Namespace(
                    repo=str(source),
                    repository_id="repo-1",
                    objective="keep module valid",
                    hidden_test_json='["python","-m","py_compile","module.py"]',
                ),
                output,
            )
            self.assertEqual(origin, "repository")
            self.assertEqual(objective, "keep module valid")
            self.assertEqual(hidden[-1], "module.py")
            self.assertTrue((repo / "module.py").is_file())
            self.assertEqual(
                subprocess.run(
                    ["git", "symbolic-ref", "-q", "HEAD"],
                    cwd=repo, capture_output=True, text=True,
                ).returncode,
                1,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=source, capture_output=True, text=True, check=True,
                ).stdout,
                "",
            )

    def test_real_benchmark_requires_identity_diversity_and_complete_metrics(self):
        schema = json.loads(
            (
                ROOT / "clawos" / "benchmarks"
                / "coding_outcome_case.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn("policy_id", schema["$defs"]["run"]["required"])
        self.assertIn("duration_ms", schema["$defs"]["run"]["required"])
        cases = [{
            "id": f"case-{index}",
            "origin": "repository",
            "repository_id": f"repo-{index % 5}",
            "issue_digest": f"issue-{index}",
            "blinded": True,
            "hidden_test_digest": f"hidden-{index}",
            "baseline": run_evidence("baseline-v1", 8),
            "candidate": run_evidence("candidate-v2", 10),
        } for index in range(30)]
        benchmark = CodingOutcomeBenchmark()
        result = benchmark.evaluate(cases, bootstrap_samples=200)
        self.assertTrue(result["passed"])
        self.assertEqual(result["candidate_metrics"]["patch_success_rate"], 1.0)
        self.assertEqual(result["candidate_metrics"]["latency_p95_ms"], 100.0)

        duplicate = [dict(item) for item in cases]
        duplicate[1]["id"] = duplicate[0]["id"]
        self.assertFalse(benchmark.evaluate(duplicate)["passed"])
        incomplete = [dict(item) for item in cases]
        incomplete[0]["candidate"] = dict(incomplete[0]["candidate"])
        incomplete[0]["candidate"].pop("duration_ms")
        self.assertFalse(benchmark.evaluate(incomplete)["passed"])
        same_policy = [dict(item) for item in cases]
        same_policy[0]["candidate"] = {
            **same_policy[0]["candidate"], "policy_id": "baseline-v1"
        }
        self.assertFalse(benchmark.evaluate(same_policy)["passed"])

    def test_product_report_closes_software_but_not_missing_real_evidence(self):
        learning = {
            "quality": {
                "trajectory_count": 3,
                "grounded_feedback_count": 3,
                "reward_calibration_ready": False,
                "preference_ranker_ready": False,
            },
            "deep_router": {"ready": False},
            "trajectory_rl": {"ready": False},
            "behavior_lora": {"ready": False},
        }
        report = ProductReadinessService(ROOT).report(
            learning=learning,
            evaluator={
                "real_repository_case_count": 0,
                "controlled_fixture_count": 3,
                "independent_human_user_count": 0,
            },
        )
        self.assertTrue(report["software_contracts_closed"])
        self.assertTrue(
            report["phases"]["p1_product_engineering"]["software_closed"]
        )
        self.assertFalse(report["product_ready"])
        self.assertFalse(report["phases"]["p0_empirical"]["ready"])
        self.assertFalse(report["phases"]["p2_advanced_learning"]["ready"])
        self.assertFalse(report["online_rl_claimed"])

    def test_product_report_requires_signed_packaged_ide_evidence(self):
        report = ProductReadinessService(ROOT).report(
            ide_artifact={
                "signed": True,
                "artifact_digest": "digest",
                "compatibility_passed": True,
            }
        )
        checks = report["phases"]["p1_product_engineering"]["checks"]
        self.assertTrue(checks["signed_packaged_ide"])
        self.assertTrue(checks["hosted_ci_contract"])
        self.assertTrue(checks["deterministic_ci_dependencies"])
        self.assertTrue(checks["ide_preview_confirmation"])
        self.assertTrue(checks["ide_cancellation"])
        self.assertTrue(checks["modular_readiness_api"])

    def test_modular_router_exposes_read_only_product_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            summary = output / "coding-evaluator" / "summary.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(json.dumps({
                "real_repository_case_count": 0,
                "controlled_fixture_count": 3,
            }), encoding="utf-8")
            router = create_product_readiness_router(
                ROOT,
                output,
                learning_provider=lambda: {},
                hardware_provider=lambda: {},
            )
            paths = {route.path for route in router.routes}
            self.assertEqual(paths, {"/api/product/readiness"})


if __name__ == "__main__":
    unittest.main()
