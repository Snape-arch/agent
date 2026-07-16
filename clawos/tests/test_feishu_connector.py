"""Tests for the ClawOS Feishu connector.

Default tests need no real network or credentials: a FakeFeishuClient is
injected, and the real client's error classification is unit-tested with
synthetic httpx.Response objects.
"""
import json
import tempfile
import unittest

import httpx

from memoryos.memory_store import MemoryStore
from services.feishu import (
    FeishuConfig,
    FeishuClient,
    FeishuClientError,
    FakeFeishuClient,
    FeishuConnectorService,
    parse_message_event,
)
from services.feishu.feishu_client import (
    AUTH, PERMISSION, SCOPE, RATE_LIMIT, APPROVAL_INVALID, TERMINAL,
)


def sample_event(message_id, *, chat_id="oc_test", text="hello", event_id=None, sender="ou_user1"):
    return {
        "header": {
            "event_id": event_id or f"evt-{message_id}",
            "event_type": "im.message.receive_v1",
            "create_time": "1700000000",
        },
        "event": {
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": "group",
                "message_type": "text",
                "content": json.dumps({"text": text}),
                "create_time": "1700000000",
                "sender": {"sender_id": {"open_id": sender}},
            }
        },
    }


def make_service(tmp_db, *, live=True, **cfg_kwargs):
    store = MemoryStore(str(tmp_db))
    cfg = FeishuConfig(
        tenant_id="tenant_1",
        allowed_chat_ids=["oc_test"],
        allowed_user_ids=["ou_approver"],
        approval_definition_code="APP1",
        app_secret="SUPER_SECRET_DO_NOT_LEAK",
        live=live,
        **cfg_kwargs,
    )
    fake = FakeFeishuClient(cfg)
    svc = FeishuConnectorService(store, fake, cfg)
    return svc, store, fake, cfg


class FeishuParseWhitelistDedupTests(unittest.TestCase):
    def test_parse_valid_event(self):
        parsed = parse_message_event(sample_event("om_1", text="决定：上线"))
        self.assertEqual(parsed["message_id"], "om_1")
        self.assertEqual(parsed["chat_id"], "oc_test")
        self.assertEqual(parsed["sender_id"], "ou_user1")
        self.assertEqual(parsed["text"], "决定：上线")

    def test_parse_rejects_malformed(self):
        with self.assertRaises(ValueError):
            parse_message_event({"header": {}})
        with self.assertRaises(ValueError):
            parse_message_event({"event": {"message": {"chat_id": "x"}}})

    def test_whitelist_and_dedup(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            # whitelisted
            r1 = svc.receive_event(sample_event("om_1"))
            self.assertEqual(r1["processed_status"], "received")
            # non-whitelisted chat -> rejected, never enters summary chain
            r2 = svc.receive_event(sample_event("om_2", chat_id="oc_other"))
            self.assertEqual(r2["processed_status"], "rejected_whitelist")
            msgs = svc.list_messages()
            self.assertEqual([m["message_id"] for m in msgs], ["om_1"])
            # duplicate event_id / message_id -> same row, no duplicate
            r3 = svc.receive_event(sample_event("om_1"))
            self.assertEqual(r3["id"], r1["id"])
            self.assertEqual(len(svc.list_messages()), 1)


class FeishuSummaryTests(unittest.TestCase):
    def test_summary_carries_source_refs(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="行动项：整理财报，负责人 Alice，截止 2026-08-01"))
            m2 = svc.receive_event(sample_event("om_2", text="普通结论一条"))
            summary = svc.generate_summary([m1["id"], m2["id"]])
            self.assertTrue(summary["action_items"])
            for item in summary["action_items"]:
                self.assertIn("source_message_id", item)
                self.assertTrue(item["source_message_id"])
            owners = summary["owner_candidates"]
            self.assertIn("Alice", owners)

    def test_summary_update_is_editable(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论A"))
            summary = svc.generate_summary([m1["id"]])
            updated = svc.update_summary(summary["id"], {"topic": "Edited topic"})
            self.assertEqual(updated["topic"], "Edited topic")


class FeishuApprovalGateTests(unittest.TestCase):
    def test_unconfirmed_writes_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            with self.assertRaises(PermissionError):
                svc.create_approval(summary["id"], "chat", "oc_test", confirmed=False)
            with self.assertRaises(PermissionError):
                svc.send_after_approval(999, confirmed=False)

    def test_send_blocked_before_approval(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
            with self.assertRaises(PermissionError):
                svc.send_after_approval(ap["id"], confirmed=True)

    def test_rejected_approval_blocks_send(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
            fake.reject(ap["feishu_instance_code"])
            svc.sync_approval(ap["id"])
            self.assertEqual(svc.get_approval(ap["id"])["status"], "rejected")
            with self.assertRaises(PermissionError):
                svc.send_after_approval(ap["id"], confirmed=True)

    def test_content_change_requires_reapproval(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
            fake.approve(ap["feishu_instance_code"])
            svc.sync_approval(ap["id"])
            with self.assertRaises(PermissionError):
                svc.send_after_approval(ap["id"], confirmed=True, new_body="changed body text")


class FeishuIdempotentSendTests(unittest.TestCase):
    def _full_loop(self, svc, fake):
        m1 = svc.receive_event(sample_event("om_1", text="结论一"))
        m2 = svc.receive_event(sample_event("om_2", text="行动项：发周报，负责人 Bob"))
        summary = svc.generate_summary([m1["id"], m2["id"]])
        ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
        fake.approve(ap["feishu_instance_code"])
        svc.sync_approval(ap["id"])
        self.assertEqual(svc.get_approval(ap["id"])["status"], "approved")
        dispatch = svc.send_after_approval(ap["id"], confirmed=True)
        return ap, dispatch

    def test_send_once_after_approval(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            ap, dispatch = self._full_loop(svc, fake)
            self.assertEqual(len(fake.send_calls), 1)
            self.assertEqual(dispatch["status"], "sent")
            self.assertTrue(dispatch["feishu_message_id"])
            # second send on same approval is blocked (used)
            with self.assertRaises(PermissionError):
                svc.send_after_approval(ap["id"], confirmed=True)
            self.assertEqual(len(fake.send_calls), 1)

    def test_at_most_once_across_replay_restart(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            ap, dispatch = self._full_loop(svc, fake)
            self.assertEqual(len(fake.send_calls), 1)
            # Simulate a restart that lost the in-memory `used` flag but the
            # dispatch row persisted: replay must NOT call send again.
            with store._conn() as c:
                c.execute("UPDATE feishu_approvals SET used=0 WHERE id=?", (ap["id"],))
            replayed = svc.send_after_approval(ap["id"], confirmed=True)
            self.assertEqual(replayed["id"], dispatch["id"])
            self.assertEqual(len(fake.send_calls), 1)


class FeishuFailureClassificationTests(unittest.TestCase):
    def test_retryable_vs_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
            fake.approve(ap["feishu_instance_code"])
            svc.sync_approval(ap["id"])

            fake.fail_send_with = RATE_LIMIT
            d = svc.send_after_approval(ap["id"], confirmed=True)
            self.assertEqual(d["status"], "failed_retryable")
            self.assertEqual(d["error_category"], RATE_LIMIT)

            # reset and try a terminal failure on a fresh approval
            m2 = svc.receive_event(sample_event("om_2", text="结论2"))
            summary2 = svc.generate_summary([m2["id"]])
            ap2 = svc.create_approval(summary2["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
            fake.fail_send_with = PERMISSION
            fake.approve(ap2["feishu_instance_code"])
            svc.sync_approval(ap2["id"])
            d2 = svc.send_after_approval(ap2["id"], confirmed=True)
            self.assertEqual(d2["status"], "failed_terminal")
            self.assertEqual(d2["error_category"], PERMISSION)


class FeishuAuditNoSecretsTests(unittest.TestCase):
    def test_audit_records_exist_and_hold_no_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
            fake.approve(ap["feishu_instance_code"])
            svc.sync_approval(ap["id"])
            svc.send_after_approval(ap["id"], confirmed=True)

            events = store.list_audit_events(action="feishu.message.receive")
            self.assertTrue(events)
            all_events = store.list_audit_events()
            feishu_events = [e for e in all_events if str(e.get("action", "")).startswith("feishu.")]
            self.assertGreaterEqual(len(feishu_events), 4)
            blob = json.dumps(feishu_events, ensure_ascii=False)
            self.assertNotIn("SUPER_SECRET_DO_NOT_LEAK", blob)

    def test_health_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            health = svc.health()
            self.assertNotIn("SUPER_SECRET_DO_NOT_LEAK", json.dumps(health))
            self.assertNotIn("app_secret", json.dumps(health))


class FeishuClientErrorClassificationTests(unittest.TestCase):
    def test_real_client_classifies_responses(self):
        cfg = FeishuConfig(app_id="a", app_secret="b", tenant_id="t")
        client = FeishuClient(cfg)
        cases = [
            (httpx.Response(401, json={"code": 0}), AUTH),
            (httpx.Response(403, json={"code": 0}), PERMISSION),
            (httpx.Response(429, json={"code": 0}), RATE_LIMIT),
            (httpx.Response(500, json={"code": 0}), TERMINAL),
            (httpx.Response(200, json={"code": 99991663, "msg": "x"}), AUTH),
            (httpx.Response(200, json={"code": 99991668, "msg": "x"}), SCOPE),
            (httpx.Response(200, json={"code": 60012, "msg": "x"}), APPROVAL_INVALID),
        ]
        for resp, expected in cases:
            with self.assertRaises(FeishuClientError) as ctx:
                client._unwrap(resp)
            self.assertEqual(ctx.exception.category, expected, resp)


class FeishuTokenSuccessResponseTests(unittest.TestCase):
    """Regression for the tenant_access_token success-code handling (W1).

    Guards the `2a660f4` fix: `_ensure_token` previously used
    `int(data.get("code", -1) or -1)`, which coerced a genuine ``code: 0``
    success to ``-1`` (0 is falsy) and mis-raised an AUTH error whose message
    was literally ``"ok"``. These tests pin the correct contract:
      * HTTP 200 + code 0 + token  -> auth_ok True, token cached.
      * response missing ``code``  -> fail closed (AUTH), no token cached.
      * non-zero auth error code   -> AUTH classification, no token cached.

    No real App ID / Secret / token / chat_id / open_id appears here — all
    values are obvious fakes so nothing sensitive can leak into the suite.
    """

    TOKEN_URL_SUFFIX = "/open-apis/auth/v3/tenant_access_token/internal"

    def _client_with_token_response(self, response: httpx.Response) -> FeishuClient:
        """Build a FeishuClient whose token endpoint returns ``response``.

        Any non-token URL fails loudly so a test can never accidentally hit a
        different endpoint and pass for the wrong reason.
        """
        cfg = FeishuConfig(app_id="cli_fake", app_secret="FAKE_SECRET_NOT_REAL", tenant_id="t_fake")

        def _handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith(self.TOKEN_URL_SUFFIX):
                return response
            return httpx.Response(500, json={"code": 1, "msg": "unexpected url"})

        http = httpx.Client(transport=httpx.MockTransport(_handler))
        return FeishuClient(cfg, http_client=http)

    def test_code_zero_success_is_authenticated_and_cached(self):
        client = self._client_with_token_response(
            httpx.Response(200, json={"code": 0, "expire": 7200, "tenant_access_token": "t-FAKE-TOKEN"})
        )
        # direct: _ensure_token returns the token and caches it (code 0 == success)
        self.assertEqual(client._ensure_token(), "t-FAKE-TOKEN")
        self.assertEqual(client._token, "t-FAKE-TOKEN")
        # end-to-end: health_check reports auth_ok True and a clean connection
        health = client.health_check()
        self.assertIs(health["auth_ok"], True)
        self.assertEqual(health["connection"], "ok")
        self.assertNotIn("error", health)

    def test_missing_code_fails_closed_without_caching_token(self):
        # A response with a token but NO ``code`` field must not be trusted.
        client = self._client_with_token_response(
            httpx.Response(200, json={"tenant_access_token": "t-SHOULD-NOT-CACHE"})
        )
        with self.assertRaises(FeishuClientError) as ctx:
            client._ensure_token()
        self.assertEqual(ctx.exception.category, AUTH)
        self.assertIsNone(client._token)
        # health_check surfaces the failure rather than a false positive
        health = client.health_check()
        self.assertIs(health["auth_ok"], False)
        self.assertEqual(health["connection"], "error")
        self.assertEqual(health["error_category"], AUTH)

    def test_nonzero_auth_error_code_stays_auth_and_uncached(self):
        client = self._client_with_token_response(
            httpx.Response(200, json={"code": 99991663, "msg": "app ticket invalid"})
        )
        with self.assertRaises(FeishuClientError) as ctx:
            client._ensure_token()
        self.assertEqual(ctx.exception.category, AUTH)
        self.assertIsNone(client._token)

    def test_no_real_identifiers_in_this_test_module(self):
        # Belt-and-suspenders: assert this suite never embeds real-looking creds.
        cfg = FeishuConfig(app_id="cli_fake", app_secret="FAKE_SECRET_NOT_REAL", tenant_id="t_fake")
        self.assertFalse(cfg.app_secret.startswith("REPLACE_"))
        self.assertTrue(cfg.app_id.endswith("_fake"))


class FeishuLongConnectHandshakeTests(unittest.TestCase):
    """W2: the manager must distinguish a live SDK thread from a real WS
    handshake. ``running`` (thread alive) must NOT imply ``connected``; only a
    genuine handshake (SDK ``_conn`` established or ``on_reconnected`` fired)
    may report connected, and a drop/infinite-reconnect must revert it.

    Uses a fake SDK client (no real network / credentials) injected via
    ``client_factory`` so the handshake lifecycle is driven deterministically.
    """

    def _fake_client(self):
        import threading as _t

        class _FakeWsClient:
            def __init__(self):
                self.on_reconnecting = lambda: None
                self.on_reconnected = lambda: None
                self._conn = None          # None until a real handshake completes
                self._auto_reconnect = True
                self._stop = _t.Event()

            def start(self):
                # Mimic the SDK: start() blocks on its loop until disconnected,
                # so the manager thread stays alive even before/without a
                # successful handshake (the exact trap W2 guards against).
                self._stop.wait()

        return _FakeWsClient()

    @staticmethod
    def _wait(pred, timeout=1.0):
        import time as _time

        deadline = _time.time() + timeout
        while _time.time() < deadline:
            if pred():
                return True
            _time.sleep(0.01)
        return pred()

    def test_running_thread_alone_is_not_connected(self):
        from services.feishu.long_connect import FeishuLongConnectManager

        fake = self._fake_client()
        cfg = FeishuConfig(app_id="cli_fake", app_secret="FAKE", tenant_id="t_fake",
                           event_mode="long_connection")
        mgr = FeishuLongConnectManager(cfg, lambda e: None, client_factory=lambda c, h: fake)
        mgr.start()
        try:
            # Thread is alive but the WS handshake has NOT happened yet.
            self.assertTrue(self._wait(lambda: mgr.running, 1.0))
            self.assertFalse(mgr.connected, "running thread must not imply connected")

            # A genuine handshake (SDK sets _conn) -> connected becomes True.
            fake._conn = object()
            self.assertTrue(self._wait(lambda: mgr.connected, 1.0))

            # Connection dropped / infinite reconnect -> connected reverts.
            fake._conn = None
            self.assertTrue(self._wait(lambda: not mgr.connected, 1.0))
        finally:
            fake._stop.set()
            mgr.stop(timeout=1.0)

    def test_on_reconnected_hook_marks_connected(self):
        from services.feishu.long_connect import FeishuLongConnectManager

        fake = self._fake_client()
        cfg = FeishuConfig(app_id="cli_fake", app_secret="FAKE", tenant_id="t_fake",
                           event_mode="long_connection")
        mgr = FeishuLongConnectManager(cfg, lambda e: None, client_factory=lambda c, h: fake)
        mgr.start()
        try:
            self.assertTrue(self._wait(lambda: mgr.running, 1.0))
            self.assertFalse(mgr.connected)
            # Reconnect path: SDK fires on_reconnected and (re)establishes _conn.
            fake._conn = object()
            fake.on_reconnected()
            self.assertTrue(self._wait(lambda: mgr.connected, 1.0))
        finally:
            fake._stop.set()
            mgr.stop(timeout=1.0)


# ======================================================================
# v2 RED-LIGHT SUITE (Phase 0)
#
# These tests encode the *target* behavior required by
# WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md (v2). They are EXPECTED TO FAIL
# against the current v1 draft — each one pins one of the 12 known blocking
# defects (plan §3). Do NOT weaken or delete them to make the gate pass;
# they turn green only after the corresponding fix lands in Phase 1–4.
# ======================================================================
import threading

from services.feishu.feishu_client import TIMEOUT


def _v2_config(td_db, **overrides):
    """Build a FeishuConfig using the v2 contract field names.

    Uses only kwargs the v2 config MUST expose. Until Phase 1 adds them this
    raises TypeError, which correctly fails (red) the tests that need them.
    """
    base = dict(
        app_id="cli_app",
        app_secret="SUPER_SECRET_DO_NOT_LEAK",
        tenant_id="tenant_1",
        allowed_chat_ids=["oc_test"],
        approval_definition_code="APP1",
        approval_form_control_id="widget-body-1",
        approval_initiator_open_id="ou_initiator",
        approver_open_ids=["ou_approver"],
        live=True,
    )
    base.update(overrides)
    return FeishuConfig(**base)


class FeishuV2ApprovalRequestContractTests(unittest.TestCase):
    """Defects 1, 2, 8: approval instance request must carry initiator open_id,
    the configured form control id, and a form body that exposes target /
    content hash / source ids — and must NOT send an illegal plain-text title."""

    def _make(self, td):
        cfg = _v2_config(td + "/m.db")
        store = MemoryStore(td + "/m.db")
        fake = FakeFeishuClient(cfg)
        svc = FeishuConnectorService(store, fake, cfg)
        return svc, store, fake, cfg

    def test_create_approval_passes_initiator_and_form_control(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = self._make(td)
            m1 = svc.receive_event(sample_event("om_1", text="行动项：发周报，负责人 Bob"))
            summary = svc.generate_summary([m1["id"]])
            ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True)
            code = ap["feishu_instance_code"]
            meta = fake.approval_meta[code]
            # Defect 1: initiator open_id must be forwarded.
            self.assertEqual(meta["open_id"], "ou_initiator")
            # Defect 2: no illegal non-i18n title in v1 scope.
            self.assertIsNone(meta["title"])
            # Defect 8: form must use the configured control id and surface the
            # send target, content hash, and source message ids.
            form = meta["form"]
            control_ids = {c.get("id") for c in form}
            self.assertIn("widget-body-1", control_ids)
            blob = json.dumps(form, ensure_ascii=False)
            self.assertIn("oc_test", blob)
            self.assertIn(ap["content_hash"], blob)


class FeishuV2ActualApproverTests(unittest.TestCase):
    """Defects 3, 4: the authorized approver must be read from the Feishu
    instance task_list/timeline, never trusted from the client; and a missing /
    empty verified approver must block the send."""

    def _make(self, td, **cfg_over):
        cfg = _v2_config(td + "/m.db", **cfg_over)
        store = MemoryStore(td + "/m.db")
        fake = FakeFeishuClient(cfg)
        svc = FeishuConnectorService(store, fake, cfg)
        return svc, store, fake, cfg

    def _approved_flow(self, svc, fake, approver_open_ids):
        m1 = svc.receive_event(sample_event("om_1", text="结论：上线"))
        summary = svc.generate_summary([m1["id"]])
        ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True)
        # v2 fake API: the ACTUAL approver(s) come from the instance timeline.
        fake.approve(ap["feishu_instance_code"], approver_open_ids=approver_open_ids)
        svc.sync_approval(ap["id"])
        return ap

    def test_unauthorized_actual_approver_blocks_send(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = self._make(td)
            ap = self._approved_flow(svc, fake, ["ou_hacker"])
            with self.assertRaises(PermissionError):
                svc.send_after_approval(ap["id"], confirmed=True)
            self.assertEqual(len(fake.send_calls), 0)

    def test_missing_actual_approver_blocks_send(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = self._make(td)
            ap = self._approved_flow(svc, fake, [])
            with self.assertRaises(PermissionError):
                svc.send_after_approval(ap["id"], confirmed=True)
            self.assertEqual(len(fake.send_calls), 0)

    def test_authorized_actual_approver_persisted(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = self._make(td)
            ap = self._approved_flow(svc, fake, ["ou_approver"])
            refreshed = svc.get_approval(ap["id"])
            self.assertIn("ou_approver", refreshed.get("verified_approver_open_ids", []))


class FeishuV2OutboundWhitelistTests(unittest.TestCase):
    """Defect 7: outbound target must be enforced against the whitelist at
    approval-create time (and again before send)."""

    def test_non_whitelisted_chat_target_rejected_at_create(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = _v2_config(td + "/m.db")
            store = MemoryStore(td + "/m.db")
            fake = FakeFeishuClient(cfg)
            svc = FeishuConnectorService(store, fake, cfg)
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            with self.assertRaises((PermissionError, ValueError)):
                svc.create_approval(summary["id"], "chat", "oc_not_whitelisted", confirmed=True)


class FeishuV2DataMinimizationTests(unittest.TestCase):
    """Defect 9: non-whitelisted inbound events must not persist body or sender."""

    def test_rejected_event_stores_no_body_or_sender(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            svc.receive_event(sample_event("om_x", chat_id="oc_other", text="secret body", sender="ou_secret"))
            with store._conn() as c:
                row = c.execute(
                    "SELECT text, sender_id, processed_status FROM feishu_messages WHERE message_id=?",
                    ("om_x",),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["processed_status"], "rejected_whitelist")
            self.assertEqual(row["text"], "")
            self.assertEqual(row["sender_id"], "")


class FeishuV2OutcomeUnknownTests(unittest.TestCase):
    """Defect 11: a send timeout must land in outcome_unknown and must never be
    auto-resent on a second call."""

    def _approved(self, svc, fake):
        m1 = svc.receive_event(sample_event("om_1", text="结论"))
        summary = svc.generate_summary([m1["id"]])
        ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
        fake.approve(ap["feishu_instance_code"])
        svc.sync_approval(ap["id"])
        return ap

    def test_timeout_marks_outcome_unknown_no_auto_resend(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            ap = self._approved(svc, fake)
            fake.fail_send_with = TIMEOUT
            d = svc.send_after_approval(ap["id"], confirmed=True)
            self.assertEqual(d["status"], "outcome_unknown")
            calls_after_first = len(fake.send_calls)
            # A retry must not silently re-send an outcome_unknown dispatch.
            fake.fail_send_with = None
            d2 = svc.send_after_approval(ap["id"], confirmed=True)
            self.assertEqual(d2["status"], "outcome_unknown")
            self.assertEqual(len(fake.send_calls), calls_after_first)


class FeishuV2ConcurrencyTests(unittest.TestCase):
    """Defect 11: two concurrent senders must produce exactly one client call."""

    def test_concurrent_send_calls_client_once(self):
        with tempfile.TemporaryDirectory() as td:
            svc, store, fake, cfg = make_service(td + "/m.db")
            m1 = svc.receive_event(sample_event("om_1", text="结论"))
            summary = svc.generate_summary([m1["id"]])
            ap = svc.create_approval(summary["id"], "chat", "oc_test", confirmed=True, approver_id="ou_approver")
            fake.approve(ap["feishu_instance_code"])
            svc.sync_approval(ap["id"])

            barrier = threading.Barrier(2)
            results = []

            def worker():
                barrier.wait()
                try:
                    results.append(svc.send_after_approval(ap["id"], confirmed=True))
                except Exception as exc:  # noqa: BLE001 - record for assertion
                    results.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(fake.send_calls), 1)
            dispatch_ids = {r["id"] for r in results if isinstance(r, dict)}
            self.assertEqual(len(dispatch_ids), 1)


if __name__ == "__main__":
    unittest.main()
