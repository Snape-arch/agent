from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memoryos.context_builder import ContextBuilder
from memoryos.memory_store import MemoryStore
from providers.base import model_result
from services.advanced_policy_learning import (
    AdaptationReadiness,
    RobustOffPolicyEvaluator,
)
from services.autonomous_coding_service import AutonomousCodingService
from services.coding_context_service import CodingContextService
from services.coding_quality_service import (
    CodingOutcomeBenchmark,
    CodingReviewGate,
    IDEContextContract,
)
from services.evidence_registry import (
    CapabilityEvidenceRegistry,
    LearningArtifactRegistry,
)
from services.execution_governance import CodingAgentReadiness
from services.lsp_bridge_service import LanguageServerBridge


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "AGENTS.md").write_text("Preserve truth boundaries.", encoding="utf-8")
    (repo / "maths.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (repo / "test_maths.py").write_text(
        "import unittest\nfrom maths import add\n\n"
        "class MathsTest(unittest.TestCase):\n"
        "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")
    return repo


class FakePatchProvider:
    async def complete(self, messages, options=None, **kwargs):
        payload = {
            "changes": [{
                "path": "maths.py",
                "operation": "replace",
                "old_text": "return a - b",
                "new_text": "return a + b",
            }],
            "test_commands": [
                [sys.executable, "-m", "unittest", "-q", "test_maths"]
            ],
            "explanation": "Fix addition.",
            "confidence": 0.99,
        }
        return model_result(
            ok=True, provider="fake", model="fake",
            content=json.dumps(payload), usage={"total_tokens": 100},
        )


class ProductClosureTests(unittest.TestCase):
    def test_evidence_is_fail_closed_expiring_and_tamper_evident(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            registry = CapabilityEvidenceRegistry(path)
            self.assertEqual(registry.latest(), {})
            record = registry.record(
                "coding_context_kernel",
                status="verified",
                evidence_type="automated_test",
                source="pytest",
                expires_at=(
                    datetime.now(timezone.utc) + timedelta(days=1)
                ).isoformat(),
                confirmed=True,
            )
            self.assertTrue(registry.latest()["coding_context_kernel"]["verified"])
            value = json.loads(path.read_text(encoding="utf-8"))
            value["records"][0]["source"] = "tampered"
            path.write_text(json.dumps(value), encoding="utf-8")
            self.assertFalse(registry.latest()["coding_context_kernel"]["verified"])
            evidence = registry.latest()
            readiness = CodingAgentReadiness.report(evidence)
            self.assertFalse(readiness["software_p0_p2_closed"])
            self.assertTrue(record["record_digest"])

    def test_learning_registry_enforces_state_machine_and_activation_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = LearningArtifactRegistry(Path(tmp) / "learning.json")
            candidate = registry.create(
                "trajectory_ranker", {"weights": {"x": 1}},
                source_data_digest="abc", confirmed=True,
            )
            with self.assertRaises(ValueError):
                registry.transition(
                    candidate["id"], "active",
                    evidence={"passed": True, "human_approved": True, "sample_count": 30},
                    confirmed=True,
                )
            evaluated = registry.transition(
                candidate["id"], "evaluated",
                evidence={"passed": True}, confirmed=True,
            )
            self.assertEqual(evaluated["state"], "evaluated")
            registry.transition(
                candidate["id"], "shadow",
                evidence={"passed": True}, confirmed=True,
            )
            with self.assertRaises(ValueError):
                registry.transition(
                    candidate["id"], "active",
                    evidence={"passed": True, "human_approved": True, "sample_count": 29},
                    confirmed=True,
                )
            active = registry.transition(
                candidate["id"], "active",
                evidence={"passed": True, "human_approved": True, "sample_count": 30},
                confirmed=True,
            )
            self.assertEqual(active["state"], "active")

    def test_context_is_injected_and_incremental_index_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            cache = root / "index.json"
            service = CodingContextService(cache)
            first = service.build(repo, "fix add")
            second = service.build(repo, "fix add")
            self.assertGreater(first["incremental_index"]["misses"], 0)
            self.assertGreater(second["incremental_index"]["hits"], 0)
            store = MemoryStore(str(root / "memory.db"))
            messages = ContextBuilder(
                store, coding_context_service=service
            ).build_messages("s1", "fix add", repo_path=str(repo))
            coding = [
                item for item in messages
                if item.get("clawos_context")
            ]
            self.assertEqual(len(coding), 1)
            self.assertIn("maths.py", coding[0]["content"])

    def test_autonomous_loop_is_model_driven_confirmed_and_checkpointed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            service = AutonomousCodingService(
                FakePatchProvider(),
                workflow=__import__(
                    "services.coding_workflow_service",
                    fromlist=["CodingWorkflowService"],
                ).CodingWorkflowService(artifact_root=root / "runs"),
            )
            proposal = asyncio.run(service.run(repo, "fix add", confirmed=False))
            self.assertEqual(proposal["status"], "waiting_confirmation")
            self.assertIn("a - b", (repo / "maths.py").read_text(encoding="utf-8"))
            result = asyncio.run(service.run(repo, "fix add", confirmed=True))
            self.assertEqual(result["status"], "passed")
            workflow = result["attempts"][0]["workflow"]
            self.assertTrue(Path(workflow["rounds"][0]["checkpoint"]).is_file())
            self.assertIn("a + b", (repo / "maths.py").read_text(encoding="utf-8"))
            self.assertFalse(result["commit_created"])

    def test_real_lsp_stdio_handshake_and_symbol_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            server = root / "fake_lsp.py"
            server.write_text(
                "import json,sys\n"
                "def send(x):\n"
                " b=json.dumps(x,separators=(',',':')).encode();"
                " sys.stdout.buffer.write(f'Content-Length: {len(b)}\\r\\n\\r\\n'.encode()+b);"
                " sys.stdout.buffer.flush()\n"
                "while True:\n"
                " headers={}\n"
                " while True:\n"
                "  line=sys.stdin.buffer.readline()\n"
                "  if not line: raise SystemExit\n"
                "  if line in (b'\\r\\n',b'\\n'): break\n"
                "  k,_,v=line.decode().partition(':');headers[k.lower().strip()]=v.strip()\n"
                " msg=json.loads(sys.stdin.buffer.read(int(headers['content-length'])))\n"
                " if msg.get('method')=='initialize': send({'jsonrpc':'2.0','id':msg['id'],'result':{'capabilities':{'documentSymbolProvider':True}}})\n"
                " elif msg.get('method')=='textDocument/documentSymbol': send({'jsonrpc':'2.0','id':msg['id'],'result':[{'name':'add','kind':12}]})\n"
                " elif msg.get('method')=='shutdown': send({'jsonrpc':'2.0','id':msg['id'],'result':None})\n"
                " elif msg.get('method')=='exit': raise SystemExit\n",
                encoding="utf-8",
            )
            bridge = LanguageServerBridge([sys.executable, str(server)])
            status = bridge.start(repo)
            self.assertTrue(status["available"])
            symbols = bridge.document_symbols(repo / "maths.py", language_id="python")
            self.assertEqual(symbols[0]["name"], "add")
            bridge.stop()

    def test_behavioral_benchmark_rejects_small_or_synthetic_sets(self):
        run = {
            "completed": True,
            "hidden_tests_passed": 10,
            "hidden_tests_total": 10,
            "patch_digest": "patch",
            "test_evidence_digest": "tests",
        }
        cases = [{
            "id": str(index),
            "origin": "repository",
            "blinded": True,
            "hidden_test_digest": f"h{index}",
            "repository_id": f"r{index % 5}",
            "baseline": {**run, "hidden_tests_passed": 8},
            "candidate": run,
        } for index in range(30)]
        benchmark = CodingOutcomeBenchmark()
        self.assertTrue(benchmark.evaluate(cases)["passed"])
        self.assertFalse(benchmark.evaluate(cases[:29])["passed"])
        cases[0]["origin"] = "synthetic"
        self.assertFalse(benchmark.evaluate(cases)["passed"])

    def test_ide_ci_review_and_adaptation_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            ide = IDEContextContract.normalize(repo, {
                "open_files": ["maths.py", "../outside.py"],
                "selection": {"path": "maths.py", "start_line": 1, "text": "def add"},
                "diagnostics": [{"path": "maths.py"}],
                "editor": "vscode",
            })
            self.assertEqual(ide["focus_paths"], ["maths.py"])
        review = CodingReviewGate.evaluate(
            ["maths.py"],
            [{"command": "pytest", "exit_code": 0, "evidence_digest": "ci"}],
            [
                {"reviewer_id": "a", "decision": "approve", "findings": []},
                {"reviewer_id": "b", "decision": "approve", "findings": []},
            ],
        )
        self.assertTrue(review["passed"])
        readiness = AdaptationReadiness.report({})
        self.assertFalse(readiness["deep_training_ready"])
        self.assertFalse(readiness["adapter_training_claimed"])

    def test_ope_uses_per_record_policy_and_cross_fitted_reward_model(self):
        records = []
        for index in range(40):
            selected = "a" if index % 2 == 0 else "b"
            records.append({
                "id": index,
                "repository_id": f"repo-{index % 4}",
                "observed_reward": 1 if selected == "a" else 0,
                "candidate_probabilities": {"a": 0.5, "b": 0.5},
                "policy_trace": {
                    "candidate_set": ["a", "b"],
                    "candidate_scores": {"a": 1, "b": 1},
                    "selected_action": selected,
                    "selected_probability": 0.5,
                    "policy_version": "v1",
                },
            })
        result = RobustOffPolicyEvaluator().evaluate(
            records,
            lambda record, candidates: record["candidate_probabilities"],
            bootstrap_samples=200,
        )
        self.assertTrue(result["reward_model"]["cross_fitted"])
        self.assertEqual(result["reward_model"]["group_count"], 4)


if __name__ == "__main__":
    unittest.main()
