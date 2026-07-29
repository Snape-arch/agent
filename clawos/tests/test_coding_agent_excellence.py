import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reflection.evolution_runtime import ExecutedEvolutionBenchmarkRunner
from services.advanced_policy_learning import (
    CounterfactualTraceAudit,
    OfflinePolicySandbox,
    RobustOffPolicyEvaluator,
    TrajectoryPreferenceRanker,
)
from services.coding_context_service import CodingContextService
from services.coding_workflow_service import CodingWorkflowService
from services.coding_workspace_service import CodingWorkspaceService
from services.execution_governance import (
    CodingAgentReadiness,
    ExecutionBudget,
    GovernedExecutionContext,
    IdentityContext,
    NetworkEgressPolicy,
    PolicyHookRegistry,
)


class CodingAgentExcellenceTests(unittest.TestCase):
    def _repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
        (repo / "AGENTS.md").write_text("Run tests before delivery.\n", encoding="utf-8")
        (repo / "calc.py").write_text(
            "import math\n\ndef add(a, b):\n    return a - b\n",
            encoding="utf-8",
        )
        (repo / "test_calc.py").write_text(
            "import unittest\nfrom calc import add\n\n"
            "class CalcTests(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
        return repo

    def test_context_kernel_has_budget_sources_symbols_tests_git_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(Path(td))
            result = CodingContextService().build(
                repo,
                "fix add calculation",
                focus_paths=["calc.py"],
                token_budget=2000,
                diagnostics=[{
                    "path": "calc.py", "line": 4, "severity": "error",
                    "message": "wrong operator",
                }],
            )
        self.assertEqual(result["schema"], "clawos.coding-context.v1")
        self.assertTrue(result["context_digest"])
        self.assertEqual(result["instruction_hierarchy"][0]["path"], "AGENTS.md")
        calc = next(item for item in result["repo_map"]["files"] if item["path"] == "calc.py")
        self.assertIn("add", [item["name"] for item in calc["symbols"]])
        self.assertEqual(result["diagnostics"][0]["trust"], "tool_evidence")
        self.assertLessEqual(result["budget"]["estimated_tokens"], 2200)

    def test_structured_hunks_and_syntax_review_close_edit_loop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            service = CodingWorkflowService(artifact_root=root / "artifacts")
            inspection = service.inspect(repo, "fix add", token_budget=2000)
            result = service.execute(
                repo,
                "fix add",
                [{
                    "path": "calc.py",
                    "operation": "hunks",
                    "hunks": [{
                        "old_text": "return a - b",
                        "new_text": "return a + b",
                    }],
                }],
                [["python", "-m", "unittest", "test_calc.py"]],
                confirmed=True,
            )
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["rounds"][0]["review"]["syntax_review"][0]["passed"])
            self.assertEqual(
                inspection["context_pack"]["schema"],
                "clawos.coding-context.v1",
            )

    def test_worktree_and_commit_are_isolated_and_confirmation_gated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = self._repo(root)
            service = CodingWorkspaceService()
            target = root / "isolated"
            with self.assertRaises(PermissionError):
                service.create(repo, target, "codex/test-worktree")
            created = service.create(
                repo, target, "codex/test-worktree", confirmed=True
            )
            (target / "calc.py").write_text(
                "def add(a, b):\n    return a + b\n", encoding="utf-8"
            )
            committed = service.commit(
                target, ["calc.py"], "fix: addition", confirmed=True
            )
            self.assertTrue(created["isolated"])
            self.assertTrue(committed["committed"])
            self.assertFalse(committed["remote_mutation"])
            self.assertIn("return a - b", (repo / "calc.py").read_text(encoding="utf-8"))

    def test_counterfactual_audit_and_robust_ope(self):
        records = []
        for index in range(100):
            selected = "safe" if index % 2 == 0 else "fast"
            records.append({
                "id": index + 1,
                "action_name": selected,
                "observed_reward": 0.8,
                "behavior_propensity": 0.5,
                "created_at": f"2026-01-{(index % 28) + 1:02d}T00:00:00",
                "action_payload": {"_policy_trace": {
                    "candidate_set": ["safe", "fast"],
                    "candidate_scores": {"safe": 0.6, "fast": 0.4},
                    "selected_action": selected,
                    "selected_probability": 0.5,
                    "policy_version": "router-v1",
                }},
            })
        audit = CounterfactualTraceAudit.audit(records)
        result = RobustOffPolicyEvaluator().evaluate(
            records,
            lambda record, arms: {"safe": 0.5, "fast": 0.5},
        )
        self.assertTrue(audit["ready"])
        self.assertTrue(result["passed"])
        self.assertGreaterEqual(result["effective_sample_size"], 20)
        self.assertEqual(result["abort_reason"], "")

    def test_trajectory_ranker_and_offline_sandbox_respect_data_gates(self):
        pairs = [{
            "created_at": f"2026-01-{(index % 28) + 1:02d}",
            "chosen": {"success": 1, "explicit_feedback": 1, "safety_violation": 0},
            "rejected": {"success": 0, "explicit_feedback": 0, "safety_violation": 1},
        } for index in range(120)]
        model = TrajectoryPreferenceRanker().train(pairs)
        blocked = OfflinePolicySandbox.advantage_weights(
            [{"id": 1, "total_reward": 1, "steps": [{}]}]
        )
        self.assertEqual(model["status"], "shadow")
        self.assertFalse(model["online_rl_claimed"])
        self.assertEqual(blocked["status"], "blocked")
        self.assertFalse(blocked["runtime_policy_mutated"])

    def test_governance_identity_egress_budget_hooks_and_readiness(self):
        identity = IdentityContext(
            "u1", "w1", ("developer",), authenticated=True
        )
        identity.require("developer")
        egress = NetworkEgressPolicy(
            allowed_hosts=["api.example.com"], allowed_ports=[443]
        )
        self.assertTrue(egress.evaluate("https://api.example.com/v1")["allowed"])
        self.assertFalse(egress.evaluate("http://127.0.0.1")["allowed"])
        governed = GovernedExecutionContext(
            identity=identity, egress=egress,
            budget=ExecutionBudget(max_tool_calls=2),
        )
        self.assertEqual(
            governed.authorize_egress({"url": "https://api.example.com/v1"})[0][
                "host"
            ],
            "api.example.com",
        )
        with self.assertRaises(PermissionError):
            governed.authorize_egress({"url": "http://127.0.0.1/private"})
        budget = ExecutionBudget(max_tool_calls=2)
        self.assertEqual(budget.consume(tool_calls=1)["remaining"]["tool_calls"], 1)
        hooks = PolicyHookRegistry()
        hooks.register(
            "before_tool", "deny-delete",
            lambda payload: {"decision": "deny", "reason": "blocked"}
            if payload.get("tool") == "delete" else {"decision": "allow"},
        )
        self.assertFalse(hooks.run("before_tool", {"tool": "delete"})["allowed"])
        evidence = {
            name: {"verified": True}
            for requirements in CodingAgentReadiness.REQUIRED.values()
            for name in requirements
        }
        report = CodingAgentReadiness.report(evidence)
        self.assertTrue(report["software_p0_p2_closed"])
        self.assertFalse(report["production_learning_ready"])
        self.assertFalse(report["online_rl_claimed"])

    def test_policy_materialization_produces_distinct_execution_evidence(self):
        runner = ExecutedEvolutionBenchmarkRunner()
        baseline = runner._run_policy_probe(
            "prompt_policy", {"system": "be concise"}
        )
        candidate = runner._run_policy_probe(
            "prompt_policy", {"system": "cite evidence"}
        )
        pair = runner._pair(baseline, candidate)
        self.assertTrue(pair["metadata"]["baseline_materialized"])
        self.assertTrue(pair["metadata"]["candidate_materialized"])
        self.assertTrue(pair["metadata"]["causal_effect_observed"])


if __name__ == "__main__":
    unittest.main()
