from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from providers.base import model_result
from services.agentic_coding_loop_service import AgenticCodingLoopService
from services.coding_diagnostics_service import CodingDiagnosticsService, CodingEvidenceGate
from services.coding_trace_service import CodingTraceService
from services.coding_workflow_service import CodingWorkflowService


def make_repo(root: Path) -> Path:
    repo = root / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (repo / "test_calc.py").write_text(
        "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    return repo


class ReassessingProvider:
    def __init__(self):
        self.index = 0
        self.actions = [
            {"action": "read", "path": "calc.py", "start_line": 1, "end_line": 30},
            {
                "action": "propose_patch",
                "changes": [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a * b"}],
                "test_commands": [[sys.executable, "-m", "unittest", "test_calc.py"]],
                "hypothesis": {"claim": "multiplication implements add", "evidence_paths": ["calc.py"], "predicted_outcome": "test passes"},
                "acceptance_criteria": [{"id": "unit", "type": "tests_pass"}],
            },
            {"action": "read", "path": "test_calc.py", "start_line": 1, "end_line": 30},
            {
                "action": "propose_patch",
                "changes": [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a + b"}],
                "test_commands": [[sys.executable, "-m", "unittest", "test_calc.py"]],
                "hypothesis": {"claim": "addition operator satisfies the assertion", "evidence_paths": ["calc.py", "test_calc.py"], "predicted_outcome": "unit test passes"},
                "acceptance_criteria": [{"id": "unit", "type": "tests_pass"}],
            },
            {"action": "finish", "summary": "verified"},
        ]

    async def complete(self, messages, options=None, **kwargs):
        action = self.actions[min(self.index, len(self.actions) - 1)]
        self.index += 1
        return model_result(ok=True, provider="scripted", model="test", content=json.dumps(action), usage={"total_tokens": 10})


class CodingDiagnosticLoopTests(unittest.TestCase):
    def test_parses_test_trace_and_links_nearest_symbol(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(Path(td))
            output = 'Traceback (most recent call last):\n  File "' + str(repo / "calc.py") + '", line 2, in add\n    return missing\nNameError: missing\n'
            result = CodingDiagnosticsService().analyze(repo, [{"command": ["python"], "exit_code": 1, "stdout": "", "stderr": output}])
        self.assertEqual(result["failure_category"], "implementation_failure")
        self.assertEqual(result["diagnostics"][0]["path"], "calc.py")
        self.assertEqual(result["diagnostics"][0]["related_symbol"]["name"], "add")

    def test_distinguishes_environment_test_and_requirement_failures(self):
        service = CodingDiagnosticsService()
        self.assertEqual(service.classify("command not found", nonzero=True, timed_out=False)[0], "environment_failure")
        self.assertEqual(service.classify("AssertionError: expected 5", nonzero=True, timed_out=False)[0], "test_failure")
        self.assertEqual(service.classify("acceptance criteria missing", nonzero=True, timed_out=False)[0], "requirements_failure")

    def test_evidence_gate_stops_repeated_or_excess_retrieval(self):
        gate = CodingEvidenceGate({"code_evidence": [{"path": "calc.py"}]})
        first = gate.register({"action": "read", "path": "calc.py"}, {"type": "read", "path": "calc.py"})
        second = gate.register({"action": "read", "path": "calc.py"}, {"type": "read", "path": "calc.py"})
        self.assertTrue(first["sufficient"])
        self.assertFalse(first["continue_retrieval"])
        self.assertTrue(second["duplicate"])

    def test_loop_reassesses_failed_hypothesis_and_enforces_acceptance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = make_repo(root)
            result = asyncio.run(AgenticCodingLoopService(
                ReassessingProvider(),
                workflow=CodingWorkflowService(artifact_root=root / "runs"),
                trace=CodingTraceService(root / "trace.json"),
            ).run(repo, "fix add", confirmed=True, task_id="t1", session_id="s1", max_turns=8))
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual([item["status"] for item in result["hypothesis_history"]], ["invalidated", "confirmed"])
        self.assertEqual(result["hypothesis_history"][0]["failure_category"], "test_failure")
        self.assertTrue(result["acceptance"]["passed"])
        reads = [item for item in result["observations"] if item["type"] == "read"]
        self.assertEqual([item["path"] for item in reads], ["calc.py", "test_calc.py"])
        self.assertFalse(reads[-1]["evidence_gate"]["continue_retrieval"])

    def test_unknown_acceptance_criterion_blocks_completion_and_restores(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); repo = make_repo(root)
            result = CodingWorkflowService(artifact_root=root / "runs").execute(
                repo, "fix add",
                [{"path": "calc.py", "operation": "replace", "old_text": "return a - b", "new_text": "return a + b"}],
                [[sys.executable, "-m", "unittest", "test_calc.py"]],
                confirmed=True, acceptance_criteria=[{"id": "manual-product-review", "type": "manual_review"}],
            )
            text = (repo / "calc.py").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["acceptance"]["passed"])
        self.assertIn("return a - b", text)


if __name__ == "__main__":
    unittest.main()
