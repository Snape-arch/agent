import asyncio
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeResponse:
    def __init__(self, payload=None, status_error=None):
        self._payload = payload or {}
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


class ModelProviderTests(unittest.TestCase):
    def test_mock_provider_returns_model_result_envelope(self):
        from providers import create_model_provider

        provider = create_model_provider({"provider": "mock", "model": "mock-router", "mock_response": "hello"})
        result = asyncio.run(provider.complete([{"role": "user", "content": "hi"}]))

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "mock")
        self.assertEqual(result["model"], "mock-router")
        self.assertEqual(result["content"], "hello")
        self.assertIn("duration_ms", result)
        self.assertEqual(result["error"], "")

    def test_openai_compatible_missing_api_key_is_classified(self):
        from providers import create_model_provider

        provider = create_model_provider({
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:9999/v1",
            "model": "local-qwen",
            "api_key": "",
        })
        result = asyncio.run(provider.complete([{"role": "user", "content": "hi"}], http_client=FakeHttpClient()))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_api_key")

    def test_invalid_provider_response_is_classified(self):
        from providers import create_model_provider

        provider = create_model_provider({
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
        })
        result = asyncio.run(provider.complete(
            [{"role": "user", "content": "hi"}],
            http_client=FakeHttpClient(FakeResponse({"choices": []})),
        ))

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_response")

    def test_server_builds_provider_config_without_exposing_secret(self):
        import clawos_server as server

        cfg = server.normalize_config({
            "model_provider": {
                "provider": "mock",
                "model": "mock-model",
                "api_key": "secret",
                "mock_response": "ok",
            }
        })
        status = server.model_provider_status(cfg)

        self.assertEqual(cfg["routing"]["provider"], "mock")
        self.assertEqual(cfg["upstream"]["provider"], "mock")
        self.assertTrue(status["configured"])
        self.assertEqual(status["provider"], "mock")
        self.assertEqual(status["model"], "mock-model")
        self.assertNotIn("api_key", status)
        self.assertNotIn("secret", str(status))

    def test_server_proxy_upstream_uses_configured_mock_provider(self):
        import clawos_server as server
        from providers import create_model_provider

        old_config = server.config
        old_provider = server.g_upstream_provider
        server.config = server.normalize_config({
            "model_provider": {"provider": "mock", "model": "mock-chat", "mock_response": "plain answer"}
        })
        server.g_upstream_provider = create_model_provider(server.config["upstream"])
        try:
            resp = asyncio.run(server.proxy_upstream(
                {"messages": [{"role": "user", "content": "hi"}]},
                stream=False,
            ))
        finally:
            server.config = old_config
            server.g_upstream_provider = old_provider

        body = resp.body.decode("utf-8")
        self.assertIn("plain answer", body)
        self.assertIn("mock-chat", body)

    def test_server_proxy_upstream_returns_error_envelope_on_provider_failure(self):
        import clawos_server as server
        from providers import create_model_provider

        old_config = server.config
        old_provider = server.g_upstream_provider
        server.config = server.normalize_config({
            "model_provider": {
                "provider": "mock",
                "model": "mock-chat",
                "fail_with": "network_error",
            }
        })
        server.g_upstream_provider = create_model_provider(server.config["upstream"])
        try:
            resp = asyncio.run(server.proxy_upstream(
                {"messages": [{"role": "user", "content": "hi"}]},
                stream=False,
            ))
        finally:
            server.config = old_config
            server.g_upstream_provider = old_provider

        body = resp.body.decode("utf-8")
        self.assertIn("network_error", body)
        self.assertIn("model_result", body)


if __name__ == "__main__":
    unittest.main()
