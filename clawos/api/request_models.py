"""Validated request models shared by the Feishu HTTP adapters."""
from typing import Any
from pydantic import BaseModel, Field


class FeishuSummaryCreate(BaseModel):
    message_ids: list[int]


class FeishuSummaryUpdate(BaseModel):
    topic: str | None = None
    conclusions: Any | None = None
    action_items: Any | None = None
    owner_candidates: Any | None = None
    deadline_candidates: Any | None = None
    open_questions: Any | None = None


class FeishuApprovalCreate(BaseModel):
    summary_id: int
    target_type: str = "chat"
    target_id: str = Field(min_length=1)
    approver_id: str = ""
    outbound_msg_type: str = "text"
    confirmed: bool = False


class FeishuApprovalSend(BaseModel):
    confirmed: bool = False
    body: str | None = None
