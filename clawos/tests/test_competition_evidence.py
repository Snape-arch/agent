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
    stages = [
        {"id": stage, "status": "pass" if stage == "quality_gate" else "completed", "evidence": [f"trace:{stage}"]}
        for stage in REQUIRED_STAGES
    ]
    run = RunRecord(
        "real-1", "task_evidence", "Repair repository tests", status="passed", scenario=scenario,
        started_at="2026-07-14T01:00:00+00:00", completed_at="2026-07-14T01:00:03+00:00",
        metrics={"duration_ms": 3000}, workflow={"evidence_chain": stages}, tags=list(tags or ["real-task"]),
        provenance={"provider": provider, "execution_mode": "live", "input_origin": origin},
    )
    run.add_artifact("patch", "Reviewed patch", "private/path.diff", sha256="a" * 64, bytes=120)
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
