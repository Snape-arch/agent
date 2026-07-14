"""Feishu connector configuration.

All credentials are sourced from environment variables only. The connector never
persists app_secret, tokens, or full message bodies into the database, logs, or
API responses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class FeishuConfig:
    # Credentials — only ever populated from the environment.
    app_id: str = ""
    app_secret: str = ""  # never written to disk/logs/API responses
    tenant_id: str = ""
    base_url: str = "https://open.feishu.cn"

    # Whitelist: the connector only touches these test groups / single chats.
    allowed_chat_ids: list[str] = field(default_factory=list)
    # Users permitted to approve outbound sends.
    allowed_user_ids: list[str] = field(default_factory=list)

    # Native Feishu approval definition used as the outbound send gate.
    approval_definition_code: str = ""
    approval_timeout_minutes: int = 1440
    send_timeout_seconds: int = 15
    sync_limit: int = 50

    # Real writes to the Feishu tenant only happen when live is True AND the
    # target is whitelisted AND a valid approval exists.
    live: bool = False

    # Optional long-connect transport (websocket). Supplied per tenant; the
    # connector connects and dispatches im.message.receive_v1 events.
    long_connect_url: str = ""
    long_connect_token: str = ""

    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.tenant_id)

    def is_whitelisted_chat(self, chat_id: str) -> bool:
        return bool(chat_id) and chat_id in self.allowed_chat_ids

    def is_authorized_approver(self, user_id: str) -> bool:
        return bool(user_id) and user_id in self.allowed_user_ids

    def redacted(self) -> dict:
        """Safe representation for health/debug output — no secrets."""
        return {
            "configured": self.is_configured(),
            "live": self.live,
            "app_id_present": bool(self.app_id),
            "tenant_present": bool(self.tenant_id),
            "approval_code_present": bool(self.approval_definition_code),
            "whitelist_chats": len(self.allowed_chat_ids),
            "approvers": len(self.allowed_user_ids),
            "base_url": self.base_url,
        }


def _split_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def load_feishu_config(env: dict | None = None) -> FeishuConfig:
    """Build a FeishuConfig from environment variables.

    Required for live mode:
      FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_TENANT_ID
    Optional:
      FEISHU_ALLOWED_CHAT_IDS (csv), FEISHU_APPROVER_USER_IDS (csv),
      FEISHU_APPROVAL_CODE, FEISHU_APPROVAL_TIMEOUT_MINUTES,
      FEISHU_SEND_TIMEOUT_SECONDS, FEISHU_SYNC_LIMIT, FEISHU_LIVE (1/true/yes/on),
      FEISHU_BASE_URL, FEISHU_LONG_CONNECT_URL, FEISHU_LONG_CONNECT_TOKEN
    """
    env = env if env is not None else os.environ
    return FeishuConfig(
        app_id=env.get("FEISHU_APP_ID", ""),
        app_secret=env.get("FEISHU_APP_SECRET", ""),
        tenant_id=env.get("FEISHU_TENANT_ID", ""),
        base_url=env.get("FEISHU_BASE_URL", "https://open.feishu.cn"),
        allowed_chat_ids=_split_list(env.get("FEISHU_ALLOWED_CHAT_IDS", "")),
        allowed_user_ids=_split_list(env.get("FEISHU_APPROVER_USER_IDS", "")),
        approval_definition_code=env.get("FEISHU_APPROVAL_CODE", ""),
        approval_timeout_minutes=int(env.get("FEISHU_APPROVAL_TIMEOUT_MINUTES", "1440") or 1440),
        send_timeout_seconds=int(env.get("FEISHU_SEND_TIMEOUT_SECONDS", "15") or 15),
        sync_limit=int(env.get("FEISHU_SYNC_LIMIT", "50") or 50),
        live=str(env.get("FEISHU_LIVE", "")).lower() in {"1", "true", "yes", "on"},
        long_connect_url=env.get("FEISHU_LONG_CONNECT_URL", ""),
        long_connect_token=env.get("FEISHU_LONG_CONNECT_TOKEN", ""),
    )
