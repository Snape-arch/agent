import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RuntimeRecordTests(unittest.TestCase):
    def test_multi_agent_result_normalizes_to_run_record_with_failures(self):
        from services.agent_orchestration_service import AgentOrchestrationService

        result = {
            "project_name": "ClawOS",
            "focus": "final gate",
            "score": 78,
            "committee_report": "output/report.md",
            "execution_trace": [
                {"id": "T1", "agent": "BuilderAgent", "phase": "build", "output": "created runbook", "score": 90, "artifacts": ["output/runbook.md"]},
            ],
            "quality_gate": {"status": "revision_required", "failures": ["RiskAgent score 76 < 80"]},
            "rework_loop": {"rounds": [{"round": 1, "status": "blocked_external_dependency", "final_score": 84, "required_rework": ["attach hardware logs"]}]},
            "disagreement_log": [{"objector": "RiskAgent", "opposes": "missing hardware evidence", "requires_rework": True, "arbitration_decision": "sustain"}],
        }
        run = AgentOrchestrationService().normalize_committee_result(result)

        self.assertEqual(run["schema"], "clawos.run.v1")
        self.assertEqual(run["run_type"], "multi_agent")
        self.assertGreaterEqual(len(run["artifacts"]), 2)
        self.assertTrue(any(item["category"] == "quality_gate_failure" for item in run["failure_cases"]))
        self.assertEqual(run["workflow"]["state_machine"]["state"], "blocked")

    def test_acceptance_report_creates_failure_library(self):
        from services.runtime_records import run_from_acceptance_report

        report = {
            "ok": False,
            "model": "deepseek-chat",
            "benchmark": {"name": "acceptance", "case_count": 1, "metrics": {"pass_rate": 0}},
            "cases": [
                {
                    "scenario": "research",
                    "name": "citation miss",
                    "pass": False,
                    "citation_hit": False,
                    "failure_reason": "citation_not_hit",
                    "query": "find source",
                    "answer": "unsupported answer",
                }
            ],
        }
        run = run_from_acceptance_report(report, "output/deepseek_hybrid_rag_acceptance.json")

        self.assertEqual(run["run_type"], "evaluation")
        self.assertEqual(run["status"], "failed")
        self.assertEqual(len(run["failure_cases"]), 1)
        self.assertEqual(run["failure_cases"][0]["category"], "acceptance_case_failure")

    def test_workflow_engine_rework_then_pass(self):
        from services.workflow_engine import WorkflowEngine

        workflow = WorkflowEngine().gate_rework_until_done(
            workflow_id="wf-1",
            name="report_generation",
            gate_statuses=[
                {"name": "review", "status": "revision_required", "score": 72, "failures": ["thin evidence"]},
                {"name": "review", "status": "pass", "score": 91, "failures": []},
            ],
            artifact_saves=[{"path": "output/report.md"}],
        )

        self.assertEqual(workflow["state"], "passed")
        self.assertTrue(any(step["state"] == "rework_required" for step in workflow["steps"]))
        self.assertEqual(workflow["artifacts"][0]["path"], "output/report.md")

    def test_evaluation_service_latest_report_exposes_run_record_and_failures(self):
        from services.evaluation_service import EvaluationService

        with tempfile.TemporaryDirectory() as td:
            report = {
                "ok": False,
                "model": "deepseek-chat",
                "benchmark": {"name": "acceptance", "case_count": 1, "metrics": {"pass_rate": 0, "failed_count": 1}},
                "cases": [{"scenario": "code", "name": "case", "pass": False, "failure_reason": "judge_not_grounded"}],
            }
            Path(td, "deepseek_hybrid_rag_acceptance.json").write_text(json.dumps(report), encoding="utf-8")
            latest = EvaluationService(td).latest_deepseek_qwen()

        self.assertTrue(latest["found"])
        self.assertEqual(latest["benchmark"]["metrics"]["failed_count"], 1)
        self.assertEqual(latest["run_record"]["schema"], "clawos.run.v1")
        self.assertEqual(len(latest["failure_library"]), 1)

    def test_runtime_schema_api(self):
        import clawos_server as server

        response = asyncio.run(server.api_runtime_schema())
        payload = json.loads(response.body.decode("utf-8"))

        self.assertEqual(payload["schema"], "clawos.run.v1")
        self.assertIn("workflow_engine", payload["service_boundaries"])
        self.assertIn("FailureCase", payload["run_entities"])


if __name__ == "__main__":
    unittest.main()
