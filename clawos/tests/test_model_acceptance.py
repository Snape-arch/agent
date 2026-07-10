import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}, "timeout": timeout})
        return FakeResponse(self.payload)


class ModelAcceptanceScriptTests(unittest.TestCase):
    def test_model_acceptance_script_runs_with_mock_provider(self):
        script = ROOT / "scripts" / "evaluate_model_acceptance.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--provider",
                "mock",
                "--mock-response",
                "PASS: meeting tool evidence is sufficient.",
                "--limit",
                "2",
                "--json",
            ],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["provider"], "mock")
        self.assertTrue(payload["configured"])
        self.assertEqual(payload["benchmark"]["case_count"], 2)
        self.assertEqual(payload["evaluation"]["cases"], 2)
        self.assertEqual(payload["evaluation"]["score_rate"], 1.0)
        self.assertNotIn("api_key", result.stdout.lower())
        self.assertNotIn("sk-", result.stdout.lower())

    def test_model_acceptance_text_output_includes_counts(self):
        script = ROOT / "scripts" / "evaluate_model_acceptance.py"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--provider",
                "mock",
                "--mock-response",
                "PASS: meeting tool evidence is sufficient.",
                "--limit",
                "2",
            ],
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Model acceptance: ok=True", result.stdout)
        self.assertIn("passed_count=2", result.stdout)
        self.assertIn("failed_count=0", result.stdout)
        self.assertNotIn("api_key", result.stdout.lower())
        self.assertNotIn("sk-", result.stdout.lower())


    def test_qwen_provider_config_uses_local_defaults_without_empty_overrides(self):
        import argparse
        import os
        import sys

        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scripts.evaluate_model_acceptance import _provider_config

        old_provider = os.environ.pop("MODEL_PROVIDER", None)
        old_model = os.environ.pop("MODEL_NAME", None)
        old_base = os.environ.pop("MODEL_BASE_URL", None)
        old_key = os.environ.pop("MODEL_API_KEY", None)
        try:
            args = argparse.Namespace(
                provider="qwen",
                model="",
                base_url="",
                api_key_env="MODEL_API_KEY",
                timeout_s=60.0,
                mock_response="",
            )
            cfg = _provider_config(args)
        finally:
            if old_provider is not None:
                os.environ["MODEL_PROVIDER"] = old_provider
            if old_model is not None:
                os.environ["MODEL_NAME"] = old_model
            if old_base is not None:
                os.environ["MODEL_BASE_URL"] = old_base
            if old_key is not None:
                os.environ["MODEL_API_KEY"] = old_key

        self.assertEqual(cfg["provider"], "qwen")
        self.assertFalse(cfg["requires_api_key"])
        self.assertNotIn("model", cfg)
        self.assertNotIn("base_url", cfg)
        self.assertNotIn("api_key", cfg)


    def test_daily_local_acceptance_preset_runs_quick_mock_checks(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import clawos_server as server

        payload = asyncio.run(server._daily_local_acceptance_payload(limit=2, full_suite=False))

        self.assertEqual(payload["standard"], "daily local acceptance preset")
        self.assertEqual(payload["mode"], "quick")
        self.assertEqual(payload["limit"], 2)
        self.assertIn("workbench_readiness", payload)
        self.assertEqual(payload["frozen_benchmark"]["metrics"]["case_count"], 2)
        self.assertEqual(payload["model_acceptance"]["provider"], "mock")
        self.assertEqual(payload["model_acceptance"]["benchmark"]["case_count"], 2)
        self.assertIn("ClawOS Daily Local Acceptance", payload["summary"])
        self.assertNotIn("api_key", json.dumps(payload).lower())
        self.assertNotIn("sk-", json.dumps(payload).lower())

    def test_local_qwen_smoke_uses_local_endpoint_without_key(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import clawos_server as server

        client = FakeHttpClient({"choices": [{"message": {"content": "LOCAL_OK"}}]})
        payload = asyncio.run(server._local_qwen_smoke_check(http_client=client, timeout_s=3.0))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "qwen")
        self.assertEqual(payload["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(client.calls[0]["url"], "http://127.0.0.1:8000/v1/chat/completions")
        self.assertNotIn("Authorization", client.calls[0]["headers"])
        self.assertNotIn("api_key", json.dumps(payload).lower())

    def test_daily_local_acceptance_can_include_explicit_qwen_smoke(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import clawos_server as server

        old_smoke = server._local_qwen_smoke_check

        async def fake_smoke():
            return {
                "ok": True,
                "provider": "qwen",
                "model": "Qwen3.5-9B-Q4_K_M",
                "base_url": "http://127.0.0.1:8000/v1",
                "configured": True,
                "assets_ready": True,
                "assets_summary": "local Qwen assets ready",
                "duration_ms": 1,
                "error": "",
                "content_preview": "LOCAL_OK",
            }

        server._local_qwen_smoke_check = fake_smoke
        try:
            payload = asyncio.run(server._daily_local_acceptance_payload(limit=2, full_suite=False, include_qwen_smoke=True))
        finally:
            server._local_qwen_smoke_check = old_smoke

        self.assertIn("local_qwen_smoke", payload)
        self.assertTrue(payload["local_qwen_smoke"]["ok"])
        self.assertIn("Local Qwen smoke: ok", payload["summary"])
        self.assertNotIn("api_key", json.dumps(payload).lower())
        self.assertNotIn("sk-", json.dumps(payload).lower())


    def test_local_acceptance_history_persists_daily_and_qwen_runs(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_smoke = server._local_qwen_smoke_check

            async def fake_smoke():
                return {
                    "ok": True,
                    "provider": "qwen",
                    "model": "Qwen3.5-9B-Q4_K_M",
                    "base_url": "http://127.0.0.1:8000/v1",
                    "configured": True,
                    "assets_ready": True,
                    "assets_summary": "local Qwen assets ready",
                    "duration_ms": 1,
                    "error": "",
                    "content_preview": "LOCAL_OK",
                }

            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            server._local_qwen_smoke_check = fake_smoke
            try:
                daily = asyncio.run(server._daily_local_acceptance_payload(limit=2, full_suite=False, include_qwen_smoke=True))
                server._save_daily_acceptance_run(daily, {"limit": 2, "include_qwen_smoke": True})
                qwen = asyncio.run(server._local_qwen_smoke_check())
                server._save_qwen_smoke_run(qwen)
                history = json.loads(asyncio.run(server.api_workbench_local_acceptance_history(limit=10)).body)
                trends = json.loads(asyncio.run(server.api_workbench_local_acceptance_trends(limit=10)).body)
                remediation = json.loads(asyncio.run(server.api_workbench_local_remediation_guide(limit=10)).body)
                action = remediation["actions"][0]
                class RemediationRequest:
                    async def json(self):
                        return {"action_id": action["action_id"], "action": action, "status": "resolved"}
                saved_action = json.loads(asyncio.run(server.api_workbench_local_remediation_action(RemediationRequest())).body)
                class RecheckRequest:
                    async def json(self):
                        return {"action_id": action["action_id"], "action": action}
                recheck = json.loads(asyncio.run(server.api_workbench_local_remediation_recheck(RecheckRequest())).body)
                remediation_after = json.loads(asyncio.run(server.api_workbench_local_remediation_guide(limit=10)).body)
            finally:
                server.g_memory_store = old_store
                server._local_qwen_smoke_check = old_smoke

        self.assertEqual(history["count"], 2)
        self.assertTrue(history["durable"])
        self.assertEqual({item["run_type"] for item in history["runs"]}, {"workbench_daily_acceptance", "workbench_qwen_smoke"})
        self.assertTrue(any(item["qwen_ok"] for item in history["runs"]))
        self.assertTrue(trends["durable"])
        self.assertEqual(trends["count"], 2)
        self.assertEqual(trends["trend"]["window"], 2)
        self.assertEqual(trends["trend"]["qwen_failure_streak"], 0)
        self.assertIn("daily_pass_rate", trends["trend"])
        self.assertIn("top_readiness_gaps", trends["trend"])
        self.assertTrue(remediation["durable"])
        self.assertGreaterEqual(remediation["count"], 1)
        self.assertIn("actions", remediation)
        self.assertTrue(any("checks" in item and "action" in item for item in remediation["actions"]))
        self.assertTrue(recheck["saved"])
        self.assertIn("results", recheck["recheck"])
        self.assertTrue(saved_action["saved"])
        self.assertEqual(saved_action["action"]["status"], "resolved")
        self.assertTrue(any(item.get("last_recheck", {}).get("checked_at") for item in remediation_after["actions"]))
        self.assertEqual(remediation_after["resolved_count"], 1)
        self.assertTrue(any(item["status"] == "resolved" for item in remediation_after["actions"]))
        self.assertNotIn("api_key", json.dumps(remediation).lower())
        self.assertNotIn("sk-", json.dumps(remediation).lower())
        self.assertNotIn("api_key", json.dumps(trends).lower())
        self.assertNotIn("sk-", json.dumps(trends).lower())
        self.assertNotIn("api_key", json.dumps(history).lower())
        self.assertNotIn("sk-", json.dumps(history).lower())


    def test_local_maintenance_report_exports_markdown_json_and_run_record(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as td:
            old_store = server.g_memory_store
            old_base = server.BASE_DIR
            base = Path(td) / "clawos"
            base.mkdir()
            server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
            server.BASE_DIR = base
            try:
                payload = server._export_local_maintenance_report(limit=5)
                json_path = Path(payload["artifacts"]["json"]["path"])
                markdown_path = Path(payload["artifacts"]["markdown"]["path"])
                saved_run = server.g_memory_store.get_run_record(payload["run"]["run_id"])
                reports = json.loads(asyncio.run(server.api_workbench_local_maintenance_reports(limit=5)).body)
                detail = json.loads(asyncio.run(server.api_workbench_local_maintenance_report_detail(payload["run"]["run_id"])).body)
                self.assertTrue(payload["exported"])
                self.assertTrue(json_path.exists())
                self.assertTrue(markdown_path.exists())
                self.assertEqual(saved_run["run_type"], "workbench_maintenance_report")
                self.assertEqual(reports["count"], 1)
                self.assertEqual(reports["reports"][0]["run_id"], payload["run"]["run_id"])
                self.assertIn("markdown_path", reports["reports"][0])
                self.assertIn("ClawOS Local Maintenance Report", detail["markdown"])
                self.assertIn("Remediation Status", detail["markdown"])
                self.assertIn("report_remediation", detail)
                self.assertIn("current_remediation", detail)
                self.assertIn("actions", detail["current_remediation"])
                self.assertEqual(detail["summary"]["run_id"], payload["run"]["run_id"])
                self.assertIn("local-first maintenance report", json_path.read_text(encoding="utf-8"))
                self.assertIn("ClawOS Local Maintenance Report", markdown_path.read_text(encoding="utf-8"))
                self.assertNotIn("api_key", json.dumps(payload).lower())
                self.assertNotIn("sk-", json.dumps(payload).lower())
                self.assertNotIn("api_key", json.dumps(reports).lower())
                self.assertNotIn("sk-", json.dumps(detail).lower())
            finally:
                server.g_memory_store = old_store
                server.BASE_DIR = old_base
if __name__ == "__main__":
    unittest.main()
