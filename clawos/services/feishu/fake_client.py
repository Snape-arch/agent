"""In-memory Feishu client for tests and offline dry-runs.

Implements the same synchronous surface as FeishuClient but records every call
and lets tests script approval decisions and failure modes. No network is used.
"""
from __future__ import annotations

import uuid as _uuid

from .config import FeishuConfig
from .feishu_client import FeishuClientError, AUTH, PERMISSION, SCOPE, RATE_LIMIT, TIMEOUT, TERMINAL


class FakeFeishuClient:
    def __init__(self, config: FeishuConfig | None = None):
        self.config = config or FeishuConfig()
        self.token_ok = True
        # instance_code -> status ("PENDING" | "APPROVED" | "REJECTED")
        self.approval_states: dict[str, str] = {}
        self.approval_meta: dict[str, dict] = {}
        self.send_calls: list[dict] = []
        # Forced failure modes (category strings from feishu_client).
        self.fail_token: bool = False
        self.fail_approval_create: str | None = None  # category
        self.fail_send_with: str | None = None  # category
        self._closed = False

    # ---- scripting helpers --------------------------------------------
    def approve(self, instance_code: str) -> None:
        if instance_code in self.approval_states:
            self.approval_states[instance_code] = "APPROVED"
            self.approval_meta.setdefault(instance_code, {})["decided"] = True

    def reject(self, instance_code: str) -> None:
        if instance_code in self.approval_states:
            self.approval_states[instance_code] = "REJECTED"

    def set_expired(self, instance_code: str) -> None:
        self.approval_meta.setdefault(instance_code, {})["expired"] = True

    # ---- interface ------------------------------------------------------
    def _ensure_token(self) -> str:
        if self.fail_token:
            raise FeishuClientError("fake: bad app credentials", category=AUTH)
        return "fake-tenant-token"

    def close(self):
        self._closed = True

    def create_approval_instance(self, *, approval_code, form, title=None, user_id=None, open_id=None, uuid=None):
        if self.fail_approval_create:
            raise FeishuClientError(f"fake: approval create failed ({self.fail_approval_create})", category=self.fail_approval_create)
        code = f"inst-{_uuid.uuid4().hex[:12]}"
        self.approval_states[code] = "PENDING"
        self.approval_meta[code] = {
            "approval_code": approval_code,
            "title": title,
            "user_id": user_id,
            "open_id": open_id,
            "uuid": uuid,
            "form": form,
        }
        return {"instance_code": code, "status": "PENDING", "code": 0, "msg": "success"}

    def get_approval_instance(self, instance_code, *, user_id=None, open_id=None):
        if instance_code not in self.approval_states:
            raise FeishuClientError(f"unknown instance {instance_code}", category=TERMINAL)
        status = self.approval_states[instance_code]
        return {"instance_code": instance_code, "status": status, "code": 0, "msg": "success"}

    def send_message(self, *, receive_id_type, receive_id, msg_type, content, uuid):
        if self.fail_send_with:
            cat = self.fail_send_with
            if cat == AUTH:
                raise FeishuClientError("fake: auth failed", category=AUTH)
            if cat == PERMISSION:
                raise FeishuClientError("fake: permission denied", category=PERMISSION)
            if cat == SCOPE:
                raise FeishuClientError("fake: bot not in chat / no send permission", category=SCOPE)
            if cat == RATE_LIMIT:
                raise FeishuClientError("fake: rate limited", category=RATE_LIMIT)
            if cat == TIMEOUT:
                raise FeishuClientError("fake: send timeout", category=TIMEOUT)
            raise FeishuClientError(f"fake: terminal send failure ({cat})", category=TERMINAL)
        self.send_calls.append({
            "receive_id_type": receive_id_type,
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content,
            "uuid": uuid,
        })
        return {"message_id": f"om-{_uuid.uuid4().hex[:12]}", "code": 0, "msg": "success", "data": {"message_id": f"om-{_uuid.uuid4().hex[:12]}"}}

    def health_check(self):
        return {
            "configured": self.config.is_configured(),
            "live": self.config.live,
            "auth_ok": self.token_ok and not self.fail_token,
            "message_permission": "configured" if self.config.allowed_chat_ids else "unknown",
            "approval_configured": bool(self.config.approval_definition_code),
            "connection": "fake",
        }

    def start_long_connect(self, handler):
        raise FeishuClientError("long-connect is not supported in FakeFeishuClient", category=TERMINAL)
