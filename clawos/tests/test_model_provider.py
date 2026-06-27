import asyncio
import json
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

    def test_qwen_provider_defaults_to_local_openai_endpoint_without_key(self):
        from providers import create_model_provider

        provider = create_model_provider({"provider": "qwen"})
        self.assertEqual(provider.name, "qwen")
        self.assertEqual(provider.base_url, "http://127.0.0.1:8000/v1")
        self.assertEqual(provider.model, "Qwen3.5-9B-Q4_K_M")
        self.assertFalse(provider.requires_api_key)
        self.assertTrue(provider.is_configured())

    def test_qwen_provider_does_not_send_empty_authorization_header(self):
        from providers import create_model_provider

        response = FakeResponse({
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"total_tokens": 1},
        })
        client = FakeHttpClient(response)
        provider = create_model_provider({
            "provider": "qwen",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "Qwen3.5-9B-Q4_K_M",
        })

        result = asyncio.run(provider.complete([{"role": "user", "content": "hi"}], http_client=client))

        self.assertTrue(result["ok"])
        self.assertEqual(client.calls[0]["url"], "http://127.0.0.1:8000/v1/chat/completions")
        self.assertNotIn("Authorization", client.calls[0]["headers"])

    def test_openai_provider_forwards_json_mode_grammar_and_limits(self):
        from providers import create_model_provider

        response = FakeResponse({
            "choices": [{"message": {"role": "assistant", "content": '{"ok":true}'}}],
            "usage": {"total_tokens": 1},
        })
        client = FakeHttpClient(response)
        provider = create_model_provider({
            "provider": "qwen",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "Qwen3.5-9B-Q4_K_M",
        })

        result = asyncio.run(provider.complete(
            [{"role": "user", "content": "json"}],
            {
                "response_format": {"type": "json_object"},
                "grammar": "root ::= object",
                "stop": ["</s>"],
                "max_tokens": 64,
            },
            http_client=client,
        ))

        self.assertTrue(result["ok"])
        payload = client.calls[0]["json"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["grammar"], "root ::= object")
        self.assertEqual(payload["stop"], ["</s>"])
        self.assertEqual(payload["max_tokens"], 64)

    def test_openai_provider_uses_reasoning_content_when_content_is_empty(self):
        from providers import create_model_provider

        response = FakeResponse({
            "choices": [{"message": {"role": "assistant", "content": "", "reasoning_content": '{"ok":true}'}}],
        })
        client = FakeHttpClient(response)
        provider = create_model_provider({
            "provider": "qwen",
            "base_url": "http://127.0.0.1:8000/v1",
            "model": "Qwen3.5-9B-Q4_K_M",
        })

        result = asyncio.run(provider.complete([{"role": "user", "content": "json"}], http_client=client))

        self.assertTrue(result["ok"])
        self.assertEqual(result["content"], '{"ok":true}')

    def test_qwen_api_and_glm_aliases_use_openai_compatible_contract(self):
        from providers import create_model_provider

        qwen_api = create_model_provider({
            "provider": "qwen_api",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-plus",
            "api_key": "sk-test",
        })
        glm = create_model_provider({
            "provider": "glm",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4-flash",
            "api_key": "sk-test",
        })

        self.assertEqual(qwen_api.name, "qwen_api")
        self.assertEqual(glm.name, "glm")
        self.assertTrue(qwen_api.is_configured())
        self.assertTrue(glm.is_configured())

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



    def test_default_config_declares_qwen_as_local_fallback(self):
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        fallback = config["model_fallbacks"][0]

        self.assertEqual(fallback["provider"], "qwen")
        self.assertEqual(fallback["base_url"], "${QWEN_BASE_URL:-http://127.0.0.1:8000/v1}")
        self.assertEqual(fallback["model"], "${QWEN_MODEL:-Qwen3.5-9B-Q4_K_M}")
        self.assertFalse(fallback["requires_api_key"])

    def test_default_config_declares_offline_vector_backend_options(self):
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        vector = config["vector_store"]

        self.assertEqual(vector["provider"], "${VECTOR_PROVIDER:-chroma}")
        self.assertEqual(vector["chroma_dir"], "${CHROMA_DIR:-./data/chroma}")
        self.assertEqual(vector["embedding_provider"], "${EMBEDDING_PROVIDER:-hash}")
        self.assertEqual(vector["embedding_model_path"], "${EMBEDDING_MODEL_PATH:-../tools/models/qwen3-embedding-0.6b}")
        self.assertEqual(vector["embedding_dim"], "${EMBEDDING_DIM:-1024}")

    def test_qwen_model_manifest_matches_provider_default(self):
        manifest_path = ROOT / "models" / "qwen3_5_9b_q4_k_m.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["provider"], "qwen")
        self.assertEqual(manifest["repo_id"], "unsloth/Qwen3.5-9B-GGUF")
        self.assertEqual(manifest["filename"], "Qwen3.5-9B-Q4_K_M.gguf")
        self.assertEqual(manifest["model_name"], "Qwen3.5-9B-Q4_K_M")
        self.assertEqual(manifest["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(manifest["size_bytes"], 5680522464)
        self.assertEqual(
            manifest["sha256"],
            "03B74727A860A56338E042C4420BB3F04B2FEC5734175F4CB9FA853DAF52B7E8",
        )

    def test_qwen3_embedding_manifest_matches_vector_defaults(self):
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        manifest = json.loads((ROOT / "models" / "qwen3_embedding_0_6b.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["provider"], "qwen3")
        self.assertEqual(manifest["repo_id"], "Qwen/Qwen3-Embedding-0.6B")
        self.assertEqual(manifest["local_path"], "tools/models/qwen3-embedding-0.6b")
        self.assertEqual(manifest["embedding_dim"], 1024)
        self.assertEqual(config["vector_store"]["embedding_model_path"], "${EMBEDDING_MODEL_PATH:-../tools/models/qwen3-embedding-0.6b}")
        self.assertEqual(config["vector_store"]["embedding_dim"], "${EMBEDDING_DIM:-1024}")

    def test_server_normalizes_qwen_defaults_for_local_endpoint(self):
        import os
        import clawos_server as server

        old_base = os.environ.pop("QWEN_BASE_URL", None)
        old_model = os.environ.pop("QWEN_MODEL", None)
        old_requires = os.environ.pop("MODEL_REQUIRES_API_KEY", None)
        try:
            cfg = server.normalize_config({"model_provider": {"provider": "qwen"}})
        finally:
            if old_base is not None:
                os.environ["QWEN_BASE_URL"] = old_base
            if old_model is not None:
                os.environ["QWEN_MODEL"] = old_model
            if old_requires is not None:
                os.environ["MODEL_REQUIRES_API_KEY"] = old_requires

        self.assertEqual(cfg["model_provider"]["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(cfg["model_provider"]["model"], "Qwen3.5-9B-Q4_K_M")
        self.assertFalse(cfg["model_provider"]["requires_api_key"])
        self.assertEqual(cfg["routing"]["provider"], "qwen")
        self.assertEqual(cfg["upstream"]["provider"], "qwen")

    def test_health_reports_model_mtclaw_and_database_state(self):
        import tempfile
        import clawos_server as server
        from memoryos.memory_store import MemoryStore

        class FakeMTClaw:
            async def health(self):
                return {"enabled": True, "reachable": True, "status": "ok"}

        old_config = server.config
        old_store = server.g_memory_store
        old_mtclaw = server.g_mtclaw_adapter
        old_tools = server.tools_def
        server.config = server.normalize_config({
            "model_provider": {"provider": "mock", "model": "mock-health", "mock_response": "ok"}
        })
        server.tools_def = [{"name": "time_now"}]
        server.g_mtclaw_adapter = FakeMTClaw()
        try:
            with tempfile.TemporaryDirectory() as td:
                server.g_memory_store = MemoryStore(str(Path(td) / "memory.db"))
                payload = asyncio.run(server.health())
        finally:
            server.config = old_config
            server.g_memory_store = old_store
            server.g_mtclaw_adapter = old_mtclaw
            server.tools_def = old_tools

        self.assertEqual(payload["model_provider"]["provider"], "mock")
        self.assertEqual(payload["model_provider"]["model"], "mock-health")
        self.assertTrue(payload["model_provider"]["configured"])
        self.assertTrue(payload["mtclaw"]["reachable"])
        self.assertEqual(payload["database"]["engine"], "sqlite")
        self.assertTrue(payload["database"]["configured"])
        self.assertTrue(payload["database"]["reachable"])

    def test_model_health_reports_fallback_strategy(self):
        import clawos_server as server
        from providers import create_model_provider

        old_config = server.config
        old_routing = server.g_routing_provider
        old_upstream = server.g_upstream_provider
        old_http = server.http_client
        try:
            server.config = {
                "routing": {"provider": "mock", "model": "router", "mock_response": "ok"},
                "upstream": {"provider": "mock", "model": "chat", "mock_response": "ok"},
                "routing_fallbacks": [{"provider": "mock", "model": "router-fallback", "mock_response": "ok"}],
            }
            server.g_routing_provider = create_model_provider(server.config["routing"])
            server.g_upstream_provider = create_model_provider(server.config["upstream"])
            server.http_client = None
            payload = json.loads(asyncio.run(server.api_model_health()).body)
        finally:
            server.config = old_config
            server.g_routing_provider = old_routing
            server.g_upstream_provider = old_upstream
            server.http_client = old_http

        self.assertEqual(payload["routing"]["primary"]["model"], "router")
        self.assertEqual(payload["routing"]["fallbacks"][0]["model"], "router-fallback")
        self.assertEqual(payload["routing"]["fallback_strategy"], "ordered_provider_fallback")

    def test_model_config_payload_masks_secret(self):
        import clawos_server as server

        cfg = server.normalize_config({
            "model_provider": {
                "provider": "deepseek",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "api_key": "sk-test-secret",
            }
        })
        payload = server.model_config_payload(cfg)

        self.assertTrue(payload["api_key_present"])
        self.assertEqual(payload["api_key_hint"], "set (...cret)")
        self.assertNotIn("sk-test-secret", str(payload))

    def test_write_model_env_preserves_unrelated_values(self):
        import tempfile
        import clawos_server as server

        with tempfile.TemporaryDirectory() as td:
            env_path = Path(td) / ".env"
            env_path.write_text(
                "\n".join([
                    "CLAWOS_MEMORY_DB=./data/memoryos.db",
                    "MODEL_PROVIDER=deepseek",
                    "MODEL_NAME=old-model",
                ]),
                encoding="utf-8",
            )
            server.write_model_env(env_path, {
                "MODEL_PROVIDER": "openai_compatible",
                "MODEL_NAME": "local-qwen",
                "MODEL_API_KEY": "local-key",
            })
            text = env_path.read_text(encoding="utf-8")

        self.assertIn("CLAWOS_MEMORY_DB=./data/memoryos.db", text)
        self.assertIn("MODEL_PROVIDER=openai_compatible", text)
        self.assertIn("MODEL_NAME=local-qwen", text)
        self.assertIn("MODEL_API_KEY=local-key", text)

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

    def test_json_repair_handles_qwen_thinking_fences_and_trailing_commas(self):
        from reflection.json_repair import loads_repaired_json

        parsed = loads_repaired_json(
            '<think>draft</think>\n```json\n{“root_cause”:“bad path”,'
            '"insights":["check"],"improvements":["validate"],"patterns":[],}\n```'
        )

        self.assertEqual(parsed["root_cause"], "bad path")
        self.assertEqual(parsed["insights"], ["check"])

    def test_qwen_reflection_uses_short_prompt_json_mode_and_repair(self):
        import tempfile
        from memoryos.memory_store import MemoryStore
        from reflection.analyzer import ReflectionAnalyzer

        response = FakeResponse({
            "choices": [{
                "message": {
                    "content": '<think>skip</think>{"root_cause":"missing path","failure_category":"environment","insights":["path missing"],"improvements":["validate path"],"patterns":[]}'
                }
            }]
        })
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            analyzer = ReflectionAnalyzer(
                store,
                client,
                {"provider": "qwen", "base_url": "http://127.0.0.1:8000/v1", "model": "Qwen3.5-9B-Q4_K_M"},
            )
            result = asyncio.run(analyzer.analyze_with_llm(
                {"tool_calls": [{"name": "read_file", "result": {"error": "not found"}}], "key_events": []},
                {"outcome": "failure", "reason": "tool error", "errors": ["not found"]},
                "read missing file",
                "failure_detected",
            ))

        payload = client.calls[0]["json"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertIn("grammar", payload)
        self.assertLessEqual(payload["max_tokens"], 320)
        self.assertIn("Return JSON only", payload["messages"][1]["content"])
        self.assertEqual(result["root_cause"], "missing path")


if __name__ == "__main__":
    unittest.main()
