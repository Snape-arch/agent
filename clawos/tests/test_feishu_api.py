"""v2 RED-LIGHT SUITE (Phase 0) — API, event security, config & docs.

These tests encode the *target* behavior of WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md
(v2). They are EXPECTED TO FAIL against the current v1 draft; each pins one of
the 12 known blocking defects (plan §3, §6, §8, §13, §14). Do NOT weaken them to
make the gate pass — they go green only after the matching fix lands.

Repo convention: FastAPI route handlers are awaited directly via asyncio.run,
with server module globals swapped to a temp MemoryStore (see
test_operations_and_streaming.py).
"""
import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.feishu import FeishuConfig, load_feishu_config  # noqa: E402


class JsonRequest:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}

    async def json(self):
        return self._payload

    async def body(self):
        return json.dumps(self._payload).encode("utf-8")


class _ServerFixture:
    """Swap clawos_server globals to an isolated store for the duration."""

    def __init__(self, td, env=None):
        self.td = td
        self.env = env or {}

    def __enter__(self):
        self.server = importlib.import_module("clawos_server")
        from memoryos.memory_store import MemoryStore

        self._old_store = self.server.g_memory_store
        self._old_feishu = self.server.g_feishu_connector_service
        self.server.g_memory_store = MemoryStore(str(Path(self.td) / "memory.db"))
        self.server.g_feishu_connector_service = None
        return self.server

    def __exit__(self, *exc):
        self.server.g_memory_store = self._old_store
        self.server.g_feishu_connector_service = self._old_feishu
        return False


# ----------------------------------------------------------------------
# Defect 6 + §6.1/§6.2/§6.3: configuration contract
# ----------------------------------------------------------------------
class FeishuConfigContractTests(unittest.TestCase):
    def test_long_connect_fields_removed(self):
        cfg = load_feishu_config(env={})
        # v2 deletes the hand-rolled long-connect transport config.
        self.assertFalse(hasattr(cfg, "long_connect_url"))
        self.assertFalse(hasattr(cfg, "long_connect_token"))

    def test_event_mode_defaults_to_long_connection(self):
        cfg = load_feishu_config(env={})
        self.assertEqual(getattr(cfg, "event_mode", None), "long_connection")

    def test_v2_contract_fields_present(self):
        cfg = load_feishu_config(env={
            "FEISHU_APPROVAL_FORM_CONTROL_ID": "widget-1",
            "FEISHU_APPROVAL_INITIATOR_OPEN_ID": "ou_init",
            "FEISHU_APPROVER_OPEN_IDS": "ou_a,ou_b",
            "FEISHU_ALLOWED_TARGET_OPEN_IDS": "ou_t1",
        })
        self.assertEqual(cfg.approval_form_control_id, "widget-1")
        self.assertEqual(cfg.approval_initiator_open_id, "ou_init")
        self.assertEqual(cfg.approver_open_ids, ["ou_a", "ou_b"])
        self.assertEqual(cfg.allowed_target_open_ids, ["ou_t1"])

    def test_base_url_is_pinned_to_feishu(self):
        # §6.3: base_url must not be an arbitrary env-provided host.
        cfg = load_feishu_config(env={"FEISHU_BASE_URL": "https://evil.example.com"})
        self.assertEqual(cfg.base_url, "https://open.feishu.cn")

    def test_live_missing_required_config_is_unavailable(self):
        # §6.3: live with missing required config must be reported unavailable,
        # never silently degraded to a "looks-successful" dry-run.
        cfg = load_feishu_config(env={"FEISHU_LIVE": "true", "FEISHU_APP_ID": "cli"})
        ready, missing = cfg.live_readiness()
        self.assertFalse(ready)
        self.assertTrue(missing)


# ----------------------------------------------------------------------
# Defect 10 + §14: redacted health schema must match console fields
# ----------------------------------------------------------------------
class FeishuHealthSchemaTests(unittest.TestCase):
    def test_redacted_health_exposes_console_fields(self):
        cfg = FeishuConfig()
        red = cfg.redacted()
        for key in ("event_mode", "live", "configured", "approval_code_present",
                    "whitelist_chats", "approvers"):
            self.assertIn(key, red)

    def test_console_reads_backend_health_fields(self):
        console = (ROOT / "static" / "assets" / "console.js").read_text(encoding="utf-8")
        # The console health panel must reference the backend field names.
        self.assertIn("event_mode", console)

    def test_redacted_health_has_no_secrets(self):
        cfg = FeishuConfig(app_secret="SUPER_SECRET_DO_NOT_LEAK")
        blob = json.dumps(cfg.redacted())
        self.assertNotIn("SUPER_SECRET_DO_NOT_LEAK", blob)
        self.assertNotIn("app_secret", blob)


# ----------------------------------------------------------------------
# Defect 5 + §8.2: webhook event authenticity
# ----------------------------------------------------------------------
class FeishuEventSecurityTests(unittest.TestCase):
    def test_url_verification_challenge_is_echoed(self):
        with tempfile.TemporaryDirectory() as td:
            with _ServerFixture(td) as server:
                resp = asyncio.run(server.api_feishu_events(
                    JsonRequest({"type": "url_verification", "challenge": "chg-123"})
                ))
                payload = json.loads(resp.body)
                self.assertEqual(payload.get("challenge"), "chg-123")

    def test_forged_event_without_token_is_rejected_and_not_stored(self):
        with tempfile.TemporaryDirectory() as td:
            with _ServerFixture(td) as server:
                # webhook mode with a configured verification token; a forged
                # event carrying no/invalid token must be rejected (401/403)
                # and must not be written to the DB.
                cfg = load_feishu_config(env={
                    "FEISHU_TENANT_ID": "tenant_1",
                    "FEISHU_ALLOWED_CHAT_IDS": "oc_test",
                    "FEISHU_EVENT_MODE": "webhook",
                    "FEISHU_VERIFICATION_TOKEN": "the-real-token",
                })
                from services.feishu import FeishuConnectorService, FakeFeishuClient
                server.g_feishu_connector_service = FeishuConnectorService(
                    server.g_memory_store, FakeFeishuClient(cfg), cfg
                )
                forged = {
                    "header": {"event_id": "evt-forged", "token": "WRONG",
                               "event_type": "im.message.receive_v1"},
                    "event": {"message": {"message_id": "om_forged", "chat_id": "oc_test",
                                          "message_type": "text",
                                          "content": json.dumps({"text": "hi"})}},
                }
                from fastapi import HTTPException
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(server.api_feishu_events(JsonRequest(forged, headers={})))
                self.assertIn(ctx.exception.status_code, (401, 403))
                msgs = server.g_feishu_connector_service.list_messages(only_received=False)
                self.assertEqual([m for m in msgs if m["message_id"] == "om_forged"], [])


# ----------------------------------------------------------------------
# Defect 7 + §16.3: unapproved / non-whitelisted send returns 409, 0 calls
# ----------------------------------------------------------------------
class FeishuSendGateApiTests(unittest.TestCase):
    def _svc(self, server):
        from services.feishu import FeishuConnectorService, FakeFeishuClient
        cfg = FeishuConfig(
            tenant_id="tenant_1",
            allowed_chat_ids=["oc_test"],
            approval_definition_code="APP1",
            approval_form_control_id="widget-1",
            approval_initiator_open_id="ou_init",
            approver_open_ids=["ou_approver"],
            live=True,
        )
        fake = FakeFeishuClient(cfg)
        svc = FeishuConnectorService(server.g_memory_store, fake, cfg)
        server.g_feishu_connector_service = svc
        return svc, fake

    def test_non_whitelist_target_send_returns_409_zero_calls(self):
        with tempfile.TemporaryDirectory() as td:
            with _ServerFixture(td) as server:
                svc, fake = self._svc(server)
                from fastapi import HTTPException
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(server.api_feishu_approvals_create(JsonRequest({
                        "summary_id": 0,
                        "target_type": "chat",
                        "target_id": "oc_not_whitelisted",
                        "confirmed": True,
                    })))
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertEqual(len(fake.send_calls), 0)


# ----------------------------------------------------------------------
# Defect 12 + §5.2: .env.example completeness
# ----------------------------------------------------------------------
class FeishuEnvExampleTests(unittest.TestCase):
    def test_env_example_lists_required_feishu_vars(self):
        env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
        required = [
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "FEISHU_TENANT_ID",
            "FEISHU_APPROVAL_CODE",
            "FEISHU_APPROVAL_FORM_CONTROL_ID",
            "FEISHU_APPROVAL_INITIATOR_OPEN_ID",
            "FEISHU_ALLOWED_CHAT_IDS",
            "FEISHU_APPROVER_OPEN_IDS",
            "FEISHU_LIVE",
            "FEISHU_EVENT_MODE",
        ]
        for name in required:
            self.assertIn(name, env_text, f"{name} missing from .env.example")

    def test_env_example_has_no_real_secret_values(self):
        env_text = (ROOT / ".env.example").read_text(encoding="utf-8")
        # secrets must be placeholders only
        for line in env_text.splitlines():
            if line.startswith("FEISHU_APP_SECRET="):
                value = line.split("=", 1)[1].strip()
                self.assertFalse(value and not value.startswith(("replace", "your", "<", "changeme")),
                                 "FEISHU_APP_SECRET must be a placeholder")


if __name__ == "__main__":
    unittest.main()
