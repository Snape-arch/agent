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

    def test_server_loads_local_env_without_overriding_existing_values(self):
        import os
        import tempfile
        import clawos_server as server

        old_model_api_key = os.environ.pop("MODEL_API_KEY", None)
        old_model_name = os.environ.get("MODEL_NAME")
        old_memory_db = os.environ.pop("CLAWOS_MEMORY_DB", None)
        os.environ["MODEL_NAME"] = "existing-model"
        try:
            with tempfile.TemporaryDirectory() as td:
                env_path = Path(td) / ".env"
                env_path.write_text(
                    "\n".join([
                        "# local config",
                        "MODEL_API_KEY=local-test-key",
                        "MODEL_NAME=file-model",
                        "CLAWOS_MEMORY_DB=./data/memoryos.db",
                    ]),
                    encoding="utf-8",
                )
                server.load_local_env(env_path)

            self.assertEqual(os.environ.get("MODEL_API_KEY"), "local-test-key")
            self.assertEqual(os.environ.get("MODEL_NAME"), "existing-model")
            self.assertTrue(os.path.isabs(os.environ.get("CLAWOS_MEMORY_DB", "")))
            self.assertTrue(os.environ.get("CLAWOS_MEMORY_DB", "").endswith(os.path.join("data", "memoryos.db")))
        finally:
            if old_model_api_key is None:
                os.environ.pop("MODEL_API_KEY", None)
            else:
                os.environ["MODEL_API_KEY"] = old_model_api_key
            if old_model_name is None:
                os.environ.pop("MODEL_NAME", None)
            else:
                os.environ["MODEL_NAME"] = old_model_name
            if old_memory_db is None:
                os.environ.pop("CLAWOS_MEMORY_DB", None)
            else:
                os.environ["CLAWOS_MEMORY_DB"] = old_memory_db

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

    def test_reflection_analyzer_uses_configured_model(self):
        import tempfile
        from memoryos.memory_store import MemoryStore
        from reflection.analyzer import ReflectionAnalyzer

        response = FakeResponse({
            "choices": [{
                "message": {
                    "content": '```json\n{"root_cause":"none","insights":["ok"],"improvements":[],"patterns":[]}\n```'
                }
            }]
        })
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            analyzer = ReflectionAnalyzer(
                store,
                client,
                {"base_url": "http://local/v1", "model": "local-qwen", "api_key": "local"},
            )
            result = asyncio.run(analyzer.analyze_with_llm(
                {"tool_calls": [], "key_events": []},
                {"outcome": "success", "reason": "ok", "errors": []},
                "demo",
                "task_completed",
            ))

        self.assertEqual(client.calls[0]["json"]["model"], "local-qwen")
        self.assertEqual(result["root_cause"], "none")


if __name__ == "__main__":
    unittest.main()
