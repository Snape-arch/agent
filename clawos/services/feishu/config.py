"""Feishu connector configuration (v2 contract).

All credentials are sourced from environment variables only. The connector never
persists app_secret, tokens, verification token, encrypt key, or full message
bodies into the database, logs, or API responses.

v2 changes vs the v1 draft:
- Adds initiator open_id, approval form control id, and three separate
  whitelists (chats, target open_ids, actual approver open_ids).
- Adds event_mode (long_connection|webhook) plus webhook verification token /
  encrypt key and a message retention policy.
- Pins base_url to https://open.feishu.cn for env-loaded config (an explicit
  override is only accepted via direct injection in tests).
- Removes the hand-rolled long-connect URL/token: the official SDK long
  connection is established from APP_ID / APP_SECRET.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

FEISHU_HOST = "https://open.feishu.cn"

EVENT_MODE_LONG_CONNECTION = "long_connection"
EVENT_MODE_WEBHOOK = "webhook"
_VALID_EVENT_MODES = {EVENT_MODE_LONG_CONNECTION, EVENT_MODE_WEBHOOK}


@dataclass
class FeishuConfig:
    # Credentials — only ever populated from the environment.
    app_id: str = ""
    app_secret: str = ""  # never written to disk/logs/API responses
    tenant_id: str = ""
    # Pinned to the Feishu host; only overridable via direct injection in tests.
    base_url: str = FEISHU_HOST

    # --- whitelists -----------------------------------------------------
    # Inbound receive + group (chat_id) outbound send.
    allowed_chat_ids: list[str] = field(default_factory=list)
    # Direct-message (open_id) outbound send.
    allowed_target_open_ids: list[str] = field(default_factory=list)
    # Users permitted to *actually* approve outbound sends (verified from the
    # Feishu approval instance task_list / timeline, never trusted from client).
    approver_open_ids: list[str] = field(default_factory=list)
    # Backward-compat alias retained for the v1 service/tests until Phase 3
    # migrates the send gate to verified approver open_ids.
    allowed_user_ids: list[str] = field(default_factory=list)

    # --- native approval gate ------------------------------------------
    approval_definition_code: str = ""
    approval_form_control_id: str = ""
    approval_initiator_open_id: str = ""
    approval_timeout_minutes: int = 1440
    send_timeout_seconds: int = 15
    sync_limit: int = 50
    message_retention_days: int = 30

    # --- event transport / webhook security ----------------------------
    event_mode: str = EVENT_MODE_LONG_CONNECTION
    verification_token: str = ""  # webhook source check; never echoed
    encrypt_key: str = ""  # webhook signature/decrypt; never echoed

    # Real writes to the Feishu tenant only happen when live is True AND the
    # target is whitelisted AND a valid, approver-verified approval exists.
    live: bool = False

    def __post_init__(self):
        # Keep the two approver lists mirrored so either name works while the
        # service is migrated to the verified-approver contract in Phase 3.
        if self.approver_open_ids and not self.allowed_user_ids:
            self.allowed_user_ids = list(self.approver_open_ids)
        elif self.allowed_user_ids and not self.approver_open_ids:
            self.approver_open_ids = list(self.allowed_user_ids)
        if self.event_mode not in _VALID_EVENT_MODES:
            self.event_mode = EVENT_MODE_LONG_CONNECTION

    # ---- predicates ----------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.tenant_id)

    def is_whitelisted_chat(self, chat_id: str) -> bool:
        return bool(chat_id) and chat_id in self.allowed_chat_ids

    def is_whitelisted_target(self, target_type: str, target_id: str) -> bool:
        """Enforce the outbound whitelist by target type.

        chat_id targets must be an allowed chat; open_id targets must be an
        allowed direct-message recipient. Unknown target types are rejected.
        """
        if not target_id:
            return False
        if target_type in ("chat", "chat_id"):
            return target_id in self.allowed_chat_ids
        if target_type in ("open_id", "user"):
            return target_id in self.allowed_target_open_ids
        return False

    def is_authorized_approver(self, open_id: str) -> bool:
        return bool(open_id) and open_id in self.approver_open_ids

    def live_readiness(self) -> tuple[bool, list[str]]:
        """Return (ready, missing) for enabling live writes.

        §6.3: when FEISHU_LIVE=true, any missing required config must make the
        connector unavailable — never silently degrade to a dry-run.
        """
        missing: list[str] = []
        required = {
            "FEISHU_APP_ID": self.app_id,
            "FEISHU_APP_SECRET": self.app_secret,
            "FEISHU_TENANT_ID": self.tenant_id,
            "FEISHU_APPROVAL_CODE": self.approval_definition_code,
            "FEISHU_APPROVAL_FORM_CONTROL_ID": self.approval_form_control_id,
            "FEISHU_APPROVAL_INITIATOR_OPEN_ID": self.approval_initiator_open_id,
        }
        for name, value in required.items():
            if not value:
                missing.append(name)
        if not self.approver_open_ids:
            missing.append("FEISHU_APPROVER_OPEN_IDS")
        if not self.allowed_chat_ids and not self.allowed_target_open_ids:
            missing.append("FEISHU_ALLOWED_CHAT_IDS|FEISHU_ALLOWED_TARGET_OPEN_IDS")
        if self.event_mode == EVENT_MODE_WEBHOOK and not (self.verification_token or self.encrypt_key):
            missing.append("FEISHU_VERIFICATION_TOKEN|FEISHU_ENCRYPT_KEY")
        return (len(missing) == 0, missing)

    def redacted(self) -> dict:
        """Safe representation for health/debug output — no secrets.

        The console health panel binds to these exact field names (see
        static/assets/console.js); keep them in sync.
        """
        ready, missing = self.live_readiness()
        return {
            "configured": self.is_configured(),
            "live": self.live,
            "live_ready": ready,
            "missing_config": missing,
            "event_mode": self.event_mode,
            "app_id_present": bool(self.app_id),
            "tenant_present": bool(self.tenant_id),
            "approval_code_present": bool(self.approval_definition_code),
            "approval_form_control_present": bool(self.approval_form_control_id),
            "approval_initiator_present": bool(self.approval_initiator_open_id),
            "verification_token_present": bool(self.verification_token),
            "encrypt_key_present": bool(self.encrypt_key),
            "whitelist_chats": len(self.allowed_chat_ids),
            "whitelist_target_open_ids": len(self.allowed_target_open_ids),
            "approvers": len(self.approver_open_ids),
            "message_retention_days": self.message_retention_days,
            "base_url": self.base_url,
        }


def _split_list(raw: str) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _int_env(env: dict, name: str, default: int) -> int:
    try:
        return int(env.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def load_feishu_config(env: dict | None = None) -> FeishuConfig:
    """Build a FeishuConfig from environment variables (v2 contract).

    Required for live mode:
      FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_TENANT_ID, FEISHU_APPROVAL_CODE,
      FEISHU_APPROVAL_FORM_CONTROL_ID, FEISHU_APPROVAL_INITIATOR_OPEN_ID,
      FEISHU_APPROVER_OPEN_IDS, and at least one outbound whitelist.
    Optional:
      FEISHU_ALLOWED_CHAT_IDS, FEISHU_ALLOWED_TARGET_OPEN_IDS,
      FEISHU_EVENT_MODE (long_connection|webhook),
      FEISHU_VERIFICATION_TOKEN, FEISHU_ENCRYPT_KEY,
      FEISHU_APPROVAL_TIMEOUT_MINUTES, FEISHU_SEND_TIMEOUT_SECONDS,
      FEISHU_SYNC_LIMIT, FEISHU_MESSAGE_RETENTION_DAYS,
      FEISHU_LIVE (1/true/yes/on).

    base_url is pinned to https://open.feishu.cn; FEISHU_BASE_URL is ignored so
    an app_secret can never be sent to a non-Feishu host.
    """
    env = env if env is not None else os.environ
    approver_open_ids = _split_list(
        env.get("FEISHU_APPROVER_OPEN_IDS", "") or env.get("FEISHU_APPROVER_USER_IDS", "")
    )
    return FeishuConfig(
        app_id=env.get("FEISHU_APP_ID", ""),
        app_secret=env.get("FEISHU_APP_SECRET", ""),
        tenant_id=env.get("FEISHU_TENANT_ID", ""),
        base_url=FEISHU_HOST,  # pinned; env override intentionally ignored
        allowed_chat_ids=_split_list(env.get("FEISHU_ALLOWED_CHAT_IDS", "")),
        allowed_target_open_ids=_split_list(env.get("FEISHU_ALLOWED_TARGET_OPEN_IDS", "")),
        approver_open_ids=approver_open_ids,
        approval_definition_code=env.get("FEISHU_APPROVAL_CODE", ""),
        approval_form_control_id=env.get("FEISHU_APPROVAL_FORM_CONTROL_ID", ""),
        approval_initiator_open_id=env.get("FEISHU_APPROVAL_INITIATOR_OPEN_ID", ""),
        approval_timeout_minutes=_int_env(env, "FEISHU_APPROVAL_TIMEOUT_MINUTES", 1440),
        send_timeout_seconds=_int_env(env, "FEISHU_SEND_TIMEOUT_SECONDS", 15),
        sync_limit=_int_env(env, "FEISHU_SYNC_LIMIT", 50),
        message_retention_days=_int_env(env, "FEISHU_MESSAGE_RETENTION_DAYS", 30),
        event_mode=env.get("FEISHU_EVENT_MODE", EVENT_MODE_LONG_CONNECTION),
        verification_token=env.get("FEISHU_VERIFICATION_TOKEN", ""),
        encrypt_key=env.get("FEISHU_ENCRYPT_KEY", ""),
        live=str(env.get("FEISHU_LIVE", "")).lower() in {"1", "true", "yes", "on"},
    )
