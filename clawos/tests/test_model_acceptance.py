import asyncio
import json
import subprocess
import sys
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

if __name__ == "__main__":
    unittest.main()
