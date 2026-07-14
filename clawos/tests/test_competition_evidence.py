import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.competition_evidence_service import CompetitionEvidenceService, REQUIRED_STAGES
from services.runtime_records import RunRecord


def complete_run(*, provider="qwen", origin="repository", tags=None, scenario="coding"):
    started = "2026-07-14T01:00:00+00:00"
    completed = "2026-07-14T01:00:03+00:00"
    model_roles = [
        {
            "role_type": role, "role_id": role, "provider": provider, "model": "Qwen3.5-9B",
            "tokens": 120, "started_at": started, "completed_at": completed, "duration_ms": 700,
        }
        for role in ("planner", "executor", "reviewer")
    ]
    stages = []
    for stage in REQUIRED_STAGES:
        records = [{"source_ref": f"trace:{stage}"}]
        if stage == "subagent_delegation":
            records = model_roles
        elif stage == "tool_trace":
            records = [{
                "sequence": 1, "tool": "repository_test", "status": "passed",
                "arguments_hash": "b" * 64, "result_hash": "d" * 64, "started_at": started,
                "completed_at": completed, "duration_ms": 500,
            }]
        elif stage == "rework":
            records = [{
                "failure_id": "fc-001", "before_artifact_id": "art-001", "after_artifact_id": "art-002",
                "started_at": started, "completed_at": completed, "duration_ms": 800,
            }]
        elif stage == "knowledge_capture":
            records = [{
                "knowledge_id": "knowledge:1", "lookup_verified": True,
                "lookup_query": "repair repository tests", "retrieved_at": completed,
                "result_hash": "c" * 64, "lookup_artifact_id": "art-002",
            }]
        stages.append({"id": stage, "status": "pass" if stage == "quality_gate" else "completed", "records": records})
    run = RunRecord(
        "real-1", "task_evidence", "Repair repository tests", status="passed", scenario=scenario,
        started_at=started, completed_at=completed,
        metrics={"duration_ms": 3000}, workflow={"schema": "clawos.real-task-evidence.v1", "evidence_chain": stages}, tags=list(tags or ["real-task"]),
        provenance={"provider": provider, "model": "Qwen3.5-9B", "execution_mode": "live", "input_origin": origin},
    )
    run.add_artifact("draft", "Rejected draft", "private/v1.json", sha256="a" * 64, bytes=80)
    run.add_artifact("patch", "Reviewed patch", "private/path.diff", sha256="b" * 64, bytes=120)
    run.add_failure_case(
        "reviewer_disagreement", "Reviewer rejected the first result.",
        remediation="Executor revised the result and Reviewer re-ran the gate.",
    )
    return run.to_dict()


class CompetitionEvidenceTests(unittest.TestCase):
    def test_complete_live_chain_is_competition_eligible(self):
        result = CompetitionEvidenceService.validate(complete_run())
        self.assertTrue(result["eligible"], result)
        self.assertEqual(result["level"], "competition_verified")
        self.assertEqual(result["stage_count"], 8)

    def test_mock_fixture_cannot_be_shown_as_real_evidence(self):
        run = complete_run(provider="mock", origin="fixture", tags=["fixture", "mock"])
        result = CompetitionEvidenceService.validate(run)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["level"], "regression_only")
        self.assertIn("mock_or_fixture_provider", result["failures"])

    def test_missing_rework_or_artifact_hash_blocks_chain(self):
        run = complete_run()
        run["workflow"]["evidence_chain"] = [item for item in run["workflow"]["evidence_chain"] if item["id"] != "rework"]
        run["artifacts"][0]["metadata"].pop("sha256")
        result = CompetitionEvidenceService.validate(run)
        self.assertFalse(result["eligible"])
        self.assertTrue(any(item.startswith("missing_stages:rework") for item in result["failures"]))
        self.assertTrue(any(item.startswith("artifact_without_sha256") for item in result["failures"]))

    def test_truth_gate_rejects_unverifiable_trace_and_knowledge_claims(self):
        run = complete_run()
        by_id = {item["id"]: item for item in run["workflow"]["evidence_chain"]}
        by_id["tool_trace"]["records"][0].pop("arguments_hash")
        by_id["knowledge_capture"]["records"][0]["lookup_verified"] = False
        result = CompetitionEvidenceService.validate(run)
        self.assertFalse(result["eligible"])
        self.assertTrue(any(item.startswith("invalid_tool_trace_record") for item in result["failures"]))
        self.assertIn("missing_knowledge_lookup_evidence", result["failures"])

    def test_truth_gate_requires_schema_scenario_timestamps_roles_and_real_rework(self):
        run = complete_run()
        run["schema"] = "legacy.run"
        run["workflow"]["schema"] = "legacy.evidence"
        run["scenario"] = "unknown"
        run["completed_at"] = "2026-07-14T00:59:59+00:00"
        by_id = {item["id"]: item for item in run["workflow"]["evidence_chain"]}
        by_id["subagent_delegation"]["records"] = [
            item for item in by_id["subagent_delegation"]["records"] if item["role_type"] != "reviewer"
        ]
        by_id["rework"]["records"][0]["failure_id"] = "missing-failure"
        result = CompetitionEvidenceService.validate(run)
        self.assertFalse(result["eligible"])
        self.assertIn("invalid_run_schema", result["failures"])
        self.assertIn("invalid_evidence_schema", result["failures"])
        self.assertIn("invalid_scenario", result["failures"])
        self.assertIn("invalid_timestamp_order", result["failures"])
        self.assertIn("missing_model_roles:reviewer", result["failures"])
        self.assertIn("missing_verifiable_rework", result["failures"])

    def test_memory_store_round_trips_verified_chain_and_hydrates_children(self):
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            run = complete_run()
            run["verification"] = {"eligible": True, "schema": "clawos.real-task-evidence.v1"}
            store.save_run_record(run)
            loaded = store.list_run_records(limit=10)[0]
            catalog = CompetitionEvidenceService().catalog([loaded])

        self.assertEqual(loaded["provenance"]["provider"], "qwen")
        self.assertTrue(loaded["verification"]["eligible"])
        self.assertEqual(len(loaded["artifacts"]), 2)
        self.assertEqual(len(loaded["failure_cases"]), 1)
        self.assertEqual(catalog["verified_count"], 1)

    def test_catalog_keeps_five_truthful_empty_slots(self):
        catalog = CompetitionEvidenceService().catalog([complete_run(provider="mock", origin="fixture", tags=["fixture"])])
        self.assertEqual(catalog["required_count"], 5)
        self.assertEqual(catalog["verified_count"], 0)
        self.assertFalse(catalog["competition_ready"])
        self.assertTrue(all(item["state"] == "empty" for item in catalog["slots"]))
        self.assertEqual(catalog["regression_excluded"], 1)

    def test_api_exposes_empty_slots_without_fallback_examples(self):
        import clawos_server as server
        with tempfile.TemporaryDirectory() as td:
            from memoryos.memory_store import MemoryStore
            previous = server.g_memory_store
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            try:
                response = asyncio.run(server.api_runtime_evidence_chains())
                payload = json.loads(response.body.decode("utf-8"))
            finally:
                server.g_memory_store = previous
        self.assertEqual(payload["verified_count"], 0)
        self.assertEqual(len(payload["slots"]), 5)


if __name__ == "__main__":
    unittest.main()
