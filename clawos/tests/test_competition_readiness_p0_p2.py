import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class CompetitionReadinessP0P2Tests(unittest.TestCase):
    def test_software_closure_is_separate_from_real_evidence(self):
        from competition_readiness import CompetitionReadinessService
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            service = CompetitionReadinessService(
                MemoryStore(str(Path(td) / "memory.db"))
            )
            snapshot = service.snapshot(architecture_report={
                "score": 95,
                "competition_architecture_ready": True,
                "checks": [],
            })

        self.assertTrue(snapshot["software_p0_p2_closed"])
        self.assertTrue(snapshot["p0"]["software_closed"])
        self.assertTrue(snapshot["p1"]["software_closed"])
        self.assertTrue(snapshot["p2"]["software_closed"])
        self.assertEqual(len(snapshot["p0"]["demo_contracts"]["flows"]), 4)
        self.assertTrue(
            snapshot["p0"]["demo_contracts"]["all_backed_by_frozen_cases"]
        )
        self.assertFalse(snapshot["p1"]["evidence_ready"])
        self.assertFalse(snapshot["p2"]["trajectory_rl"]["ready"])
        self.assertFalse(snapshot["hardware"]["ready"])
        self.assertFalse(snapshot["competition_release_ready"])
        self.assertFalse(snapshot["claims"]["online_rl"])
        self.assertFalse(snapshot["claims"]["target_hardware_validated"])

    def test_hardware_report_requires_real_metrics_and_benchmark(self):
        from competition_readiness import CompetitionReadinessService

        template = json.loads(
            (ROOT / "HARDWARE_ACCEPTANCE_TEMPLATE.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(
            CompetitionReadinessService.validate_hardware_evidence(
                template
            )["ready"]
        )
        malformed = {
            **template,
            "metrics": {
                "first_token_p95_ms": "unknown",
                "throughput_tokens_per_second": {},
                "peak_memory_mb": None,
            },
            "benchmark": {
                "sample_count": "not-a-number",
                "pass_rate": [],
            },
        }
        self.assertFalse(
            CompetitionReadinessService.validate_hardware_evidence(
                malformed
            )["ready"]
        )
        report = {
            "schema_version": "clawos.hardware-acceptance.v1",
            "target_device": "MTT AIBOOK test device",
            "local_model": "Qwen local checkpoint",
            "offline_mode": True,
            "mtclaw_required": True,
            "fallback_disabled": True,
            "metrics": {
                "first_token_p95_ms": 820,
                "throughput_tokens_per_second": 21.5,
                "peak_memory_mb": 16384,
            },
            "benchmark": {
                "sample_count": 30,
                "pass_rate": 0.93,
                "tool_accuracy": 0.95,
                "citation_accuracy": 0.91,
            },
        }
        validated = (
            CompetitionReadinessService.validate_hardware_evidence(report)
        )
        self.assertTrue(validated["ready"])
        self.assertTrue(all(validated["checks"].values()))
        self.assertEqual(len(validated["evidence_digest"]), 64)

    def test_markdown_report_preserves_claim_boundary(self):
        from competition_readiness import CompetitionReadinessService
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            service = CompetitionReadinessService(
                MemoryStore(str(Path(td) / "memory.db"))
            )
            snapshot = service.snapshot(architecture_report={
                "score": 95,
                "competition_architecture_ready": True,
            })
            report = service.to_markdown(snapshot)

        self.assertIn("Software P0-P2 closed: **True**", report)
        self.assertIn("Competition release ready: **False**", report)
        self.assertIn("Online RL claimed: **False**", report)
        self.assertIn("Software closure is not target-hardware acceptance", report)

    def test_server_control_plane_exports_only_with_confirmation(self):
        import clawos_server as server
        from fastapi import HTTPException
        from memoryos.memory_store import MemoryStore

        class JsonRequest:
            def __init__(self, payload):
                self.payload = payload

            async def json(self):
                return self.payload

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_output = server.OUTPUT_ROOT
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            server.OUTPUT_ROOT = Path(td) / "output"
            try:
                snapshot = json.loads(
                    asyncio.run(
                        server.api_competition_readiness()
                    ).body.decode("utf-8")
                )
                with self.assertRaises(HTTPException):
                    asyncio.run(
                        server.api_competition_readiness_export(
                            JsonRequest({"confirmed": False})
                        )
                    )
                exported = json.loads(
                    asyncio.run(
                        server.api_competition_readiness_export(
                            JsonRequest({"confirmed": True})
                        )
                    ).body.decode("utf-8")
                )
            finally:
                server.g_memory_store = old_store
                server.OUTPUT_ROOT = old_output

            self.assertTrue(Path(exported["json_path"]).exists())
            self.assertTrue(Path(exported["markdown_path"]).exists())

        self.assertIn("software_p0_p2_closed", snapshot)
        self.assertIn("competition_release_ready", snapshot)

    def test_console_and_cli_expose_p0_p2_readiness(self):
        html = (ROOT / "static" / "console.html").read_text(encoding="utf-8")
        script = (
            ROOT / "static" / "assets" / "console.js"
        ).read_text(encoding="utf-8")
        server = (ROOT / "clawos_server.py").read_text(encoding="utf-8")
        cli = (
            ROOT / "scripts" / "export_competition_readiness.py"
        ).read_text(encoding="utf-8")

        self.assertIn("Competition P0-P2 Readiness", html)
        self.assertIn("loadCompetitionReadiness", script)
        self.assertIn("/api/competition/readiness", script)
        self.assertIn("/api/competition/readiness", server)
        self.assertIn("competition_release_ready", cli)


if __name__ == "__main__":
    unittest.main()
