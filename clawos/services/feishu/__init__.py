"""ClawOS Feishu connector package.

A single, auditable outbound loop: receive whitelisted Feishu messages ->
summarize into traceable action items -> create a native Feishu approval that
freezes the send content -> send only after an approved, unexpired, unused,
hash-matching approval (at-most-once via a unique idempotency key).
"""
from __future__ import annotations

from .config import FeishuConfig, load_feishu_config
from .feishu_client import FeishuClient, FeishuClientError
from .fake_client import FakeFeishuClient
from .connector_service import (
    FeishuConnectorService,
    parse_message_event,
    APPROVAL_APPROVED,
    APPROVAL_REJECTED,
    APPROVAL_PENDING,
    DISP_SENT,
    DISP_FAILED_RETRYABLE,
    DISP_FAILED_TERMINAL,
)
from .schema import create_feishu_tables, FEISHU_TABLES

__all__ = [
    "FeishuConfig",
    "load_feishu_config",
    "FeishuClient",
    "FeishuClientError",
    "FakeFeishuClient",
    "FeishuConnectorService",
    "parse_message_event",
    "create_feishu_tables",
    "FEISHU_TABLES",
    "APPROVAL_APPROVED",
    "APPROVAL_REJECTED",
    "APPROVAL_PENDING",
    "DISP_SENT",
    "DISP_FAILED_RETRYABLE",
    "DISP_FAILED_TERMINAL",
]
