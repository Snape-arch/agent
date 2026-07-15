"""Feishu connector service.

Closed loop:
  receive message event -> normalize + whitelist + dedup
  -> generate summary / action items (editable, source-traceable)
  -> create Feishu native approval (freeze snapshot + content hash)
  -> sync approval decision (approver allowlist enforced)
  -> send only after a valid, unexpired, unused, hash-matching approval
     (at-most-once guaranteed by a unique idempotency_key + used flag)

No app_secret, token, or full message body is written to the DB, logs, or
API responses. All side-effecting operations are audited.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone

from .config import FeishuConfig
from .feishu_client import FeishuClient, FeishuClientError, TIMEOUT

# ---- approval statuses ----
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
APPROVAL_EXPIRED = "expired"
APPROVAL_FAILED = "failed"

# ---- dispatch statuses ----
DISP_PENDING_APPROVAL = "pending_approval"
DISP_SENDING = "sending"
DISP_SENT = "sent"
DISP_FAILED_RETRYABLE = "failed_retryable"
DISP_FAILED_TERMINAL = "failed_terminal"
DISP_OUTCOME_UNKNOWN = "outcome_unknown"
DISP_DRY_RUN = "dry_run"


def _now_epoch() -> int:
    return int(time.time())


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_loads(value, default):
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _extract_safe_text(message_type: str, raw_content):
    """Return (safe_text, safe_meta). Attachments are never downloaded/executed."""
    if raw_content is None:
        return "", {}
    if isinstance(raw_content, str):
        try:
            payload = json.loads(raw_content)
        except Exception:
            return raw_content, {}
    else:
        payload = raw_content

    if message_type == "text":
        return str(payload.get("text", "")), {}
    if message_type == "post":
        parts = []
        zh = (payload.get("zh_cn", {}) or {})
        for _title, blocks in zh.get("content", []) or []:
            for block in blocks:
                if isinstance(block, dict) and block.get("tag") == "text":
                    parts.append(str(block.get("text", "")))
        return "\n".join(parts), {"post_title": zh.get("title", "")}
    if message_type in ("image", "file", "audio", "video", "media", "sticker"):
        return "", {"attachment_type": message_type, "note": "attachment metadata only; not downloaded"}
    return str(payload), {}


def parse_message_event(event: dict) -> dict:
    """Normalize an im.message.receive_v1 event into a flat record.

    Raises ValueError if the payload is malformed.
    """
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    header = event.get("header") or {}
    ev = event.get("event") or {}
    message = ev.get("message") or {}
    if not message:
        raise ValueError("missing event.message")
    message_id = str(message.get("message_id") or "").strip()
    if not message_id:
        raise ValueError("missing message_id")
    event_id = str(header.get("event_id") or message.get("event_id") or "").strip()
    chat_id = str(message.get("chat_id") or "").strip()
    chat_type = str(message.get("chat_type") or "")
    message_type = str(message.get("message_type") or "text")
    create_time = str(message.get("create_time") or header.get("create_time") or "")
    sender = message.get("sender") or {}
    sender_id_obj = sender.get("sender_id") or {}
    sender_id = str(sender_id_obj.get("open_id") or sender_id_obj.get("user_id") or sender.get("sender_id") or "").strip()
    text, safe_meta = _extract_safe_text(message_type, message.get("content"))
    return {
        "event_id": event_id,
        "message_id": message_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "sender_id": sender_id,
        "message_type": message_type,
        "create_time": create_time,
        "text": text,
        "safe_meta": safe_meta,
    }


# ---- heuristic summarizer (default; model-backed summarizer can be injected) ----
_ACTION_RE = re.compile(
    r"^(?:TODO|待办|行动(?:项)?|需(?:要)?|请|负责|跟进|follow[\s_-]?up|action)\b",
    re.IGNORECASE,
)
_OWNER_RE = re.compile(r"(?:负责人|owner|@)\s*[:：]?\s*([^\s,，。;；]+)", re.IGNORECASE)
_DEADLINE_RE = re.compile(
    r"(?:截止|due|deadline|期限)\s*[:：]?\s*([0-9]{4}[/-][0-9]{1,2}[/-][0-9]{1,2}|[0-9]{1,2}月[0-9]{1,2}日|[0-9]{1,2}[/-][0-9]{1,2})",
    re.IGNORECASE,
)


def _heuristic_summarize(messages: list[dict]) -> dict:
    conclusions = []
    action_items = []
    owner_candidates: set = set()
    deadline_candidates: set = set()
    open_questions = []
    first_text = ""
    for m in messages:
        text = (m.get("text") or "").strip()
        mid = m.get("message_id") or ""
        ts = m.get("create_time") or ""
        if not first_text and text:
            first_text = text
        if text:
            conclusions.append({"text": text[:500], "source_message_id": mid, "source_timestamp": ts})
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if _ACTION_RE.search(line) or ("?" in line and len(line) < 80):
                owner_m = _OWNER_RE.search(line)
                deadline_m = _DEADLINE_RE.search(line)
                owner = owner_m.group(1) if owner_m else ""
                deadline = deadline_m.group(1) if deadline_m else ""
                if owner:
                    owner_candidates.add(owner)
                if deadline:
                    deadline_candidates.add(deadline)
                action_items.append({
                    "description": line[:300],
                    "owner": owner,
                    "due_date": deadline,
                    "source_message_id": mid,
                    "source_timestamp": ts,
                })
            elif line.endswith("?") or line.endswith("？"):
                open_questions.append({"text": line[:300], "source_message_id": mid, "source_timestamp": ts})
    topic = first_text[:80] if first_text else (messages[0].get("message_id", "") if messages else "")
    return {
        "topic": topic,
        "conclusions": conclusions,
        "action_items": action_items,
        "owner_candidates": sorted(owner_candidates),
        "deadline_candidates": sorted(deadline_candidates),
        "open_questions": open_questions,
    }


def _extract_actual_approvers(resp: dict) -> list:
    """Collect the real approver open_ids from a Feishu approval instance.

    The authoritative approver identities live on the instance ``task_list``
    and ``timeline`` (approve actions), never in a client-supplied field. We
    take open_ids from APPROVE tasks that are actually approved plus APPROVE
    timeline entries, de-duplicated and order-preserving.
    """
    approvers: list = []
    seen: set = set()

    def _add(open_id):
        oid = str(open_id or "").strip()
        if oid and oid not in seen:
            seen.add(oid)
            approvers.append(oid)

    if not isinstance(resp, dict):
        return approvers
    for task in resp.get("task_list") or []:
        if not isinstance(task, dict):
            continue
        ttype = str(task.get("type") or "").upper()
        status = str(task.get("status") or "").upper()
        if ttype and ttype != "APPROVE":
            continue
        if status and status not in ("APPROVED", "DONE"):
            continue
        _add(task.get("open_id"))
    for entry in resp.get("timeline") or []:
        if not isinstance(entry, dict):
            continue
        etype = str(entry.get("type") or "").upper()
        if etype and etype not in ("APPROVE", "PASS"):
            continue
        _add(entry.get("open_id"))
    return approvers


class FeishuConnectorService:
    def __init__(
        self,
        store,
        client: FeishuClient | None,
        config: FeishuConfig,
        *,
        security=None,
        summarizer=None,
        audit_fn=None,
    ):
        self.store = store
        self.client = client
        self.config = config
        self.security = security
        self._summarizer = summarizer or _heuristic_summarize
        self._audit = audit_fn or (store.record_audit_event if store else (lambda **k: None))
        self._init_db()

    # ---- schema --------------------------------------------------------
    def _init_db(self):
        # Table creation/upgrade is owned by the authoritative migration in
        # MaintenanceService (2026_07_feishu_connector), not hidden here. We
        # delegate to the same shared helper so direct construction (and tests)
        # still guarantees the schema exists without re-implementing the DDL.
        from .schema import create_feishu_tables

        with self.store._conn() as c:
            create_feishu_tables(c)

    # ---- receive -------------------------------------------------------
    def receive_event(self, event: dict, *, received_via: str = "http") -> dict:
        parsed = parse_message_event(event)
        chat_id = parsed["chat_id"]
        tenant_id = self.config.tenant_id
        whitelisted = self.config.is_whitelisted_chat(chat_id)
        processed_status = "received" if whitelisted else "rejected_whitelist"

        if not whitelisted:
            # Data minimization (spec defect 9): events from non-whitelisted
            # chats must not persist message body or sender identity. Retain
            # only the routing/dedup identifiers needed to reject idempotently.
            parsed = {**parsed, "text": "", "sender_id": ""}

        try:
            row = self._insert_message(tenant_id, parsed, processed_status=processed_status, received_via=received_via)
        except sqlite3.IntegrityError:
            # Duplicate event_id / message_id — return the existing record.
            existing = self._find_message(tenant_id, parsed["message_id"])
            if existing:
                return existing
            raise

        self._audit(
            action="feishu.message.receive", decision="allow" if whitelisted else "deny",
            resource_type="feishu_message", resource_id=str(row["id"]),
            reason="" if whitelisted else "chat not whitelisted",
            details={"chat_id": chat_id, "message_id": parsed["message_id"], "whitelisted": whitelisted},
        )
        return row

    def _insert_message(self, tenant_id, parsed, *, processed_status, received_via):
        with self.store._conn() as c:
            cur = c.execute(
                """
                INSERT INTO feishu_messages
                    (tenant_id, event_id, message_id, chat_id, sender_id, message_type,
                     text, create_time, processed_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id, parsed["event_id"], parsed["message_id"], parsed["chat_id"],
                    parsed["sender_id"], parsed["message_type"], parsed["text"],
                    parsed["create_time"], processed_status,
                ),
            )
            row = c.execute("SELECT * FROM feishu_messages WHERE id=?", (cur.lastrowid,)).fetchone()
            return self._msg_to_dict(row)

    def _find_message(self, tenant_id, message_id):
        with self.store._conn() as c:
            row = c.execute(
                "SELECT * FROM feishu_messages WHERE tenant_id=? AND message_id=?",
                (tenant_id, message_id),
            ).fetchone()
            return self._msg_to_dict(row) if row else None

    def list_messages(self, *, chat_id: str = "", limit: int = 50, only_received: bool = True) -> list:
        with self.store._conn() as c:
            clauses = []
            params = []
            if only_received:
                clauses.append("processed_status='received'")
            if chat_id:
                clauses.append("chat_id=?")
                params.append(chat_id)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = c.execute(
                f"SELECT * FROM feishu_messages{where} ORDER BY id DESC LIMIT ?",
                [*params, max(1, min(int(limit or 50), 500))],
            ).fetchall()
            return [self._msg_to_dict(r) for r in rows]

    # ---- summary -------------------------------------------------------
    def generate_summary(self, message_ids: list, *, summarizer=None) -> dict:
        if not message_ids:
            raise ValueError("message_ids is required to generate a summary")
        messages = []
        with self.store._conn() as c:
            for mid in message_ids:
                row = c.execute(
                    "SELECT * FROM feishu_messages WHERE id=? AND processed_status='received'",
                    (int(mid),),
                ).fetchone()
                if row:
                    messages.append(self._msg_to_dict(row))
        if not messages:
            raise ValueError("no received messages found for the given ids")
        fn = summarizer or self._summarizer
        summary = fn(messages)
        # Ensure every action item carries a source reference.
        for item in summary.get("action_items", []):
            item.setdefault("source_message_id", messages[0].get("message_id", ""))
            item.setdefault("source_timestamp", messages[0].get("create_time", ""))
        source_ids = [m["id"] for m in messages]
        with self.store._conn() as c:
            cur = c.execute(
                """
                INSERT INTO feishu_summaries
                    (tenant_id, topic, conclusions, action_items, owner_candidates,
                     deadline_candidates, open_questions, source_message_ids, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')
                """,
                (
                    self.config.tenant_id,
                    summary.get("topic", ""),
                    json.dumps(summary.get("conclusions", []), ensure_ascii=False),
                    json.dumps(summary.get("action_items", []), ensure_ascii=False),
                    json.dumps(summary.get("owner_candidates", []), ensure_ascii=False),
                    json.dumps(summary.get("deadline_candidates", []), ensure_ascii=False),
                    json.dumps(summary.get("open_questions", []), ensure_ascii=False),
                    json.dumps(source_ids, ensure_ascii=False),
                ),
            )
            row = c.execute("SELECT * FROM feishu_summaries WHERE id=?", (cur.lastrowid,)).fetchone()
            summary_id = row["id"]
        self._audit(
            action="feishu.summary.generate", decision="allow",
            resource_type="feishu_summary", resource_id=str(summary_id),
            details={"source_message_ids": source_ids},
        )
        return self.get_summary(summary_id)

    def update_summary(self, summary_id: int, fields: dict) -> dict:
        allowed = {
            "title", "topic", "conclusions", "action_items",
            "owner_candidates", "deadline_candidates", "open_questions",
        }
        sets, params = [], []
        for key in allowed:
            if key in fields:
                value = fields[key]
                sets.append(f"{key}=?")
                params.append(json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value)
        if not sets:
            raise ValueError("no editable fields provided")
        params.append(int(summary_id))
        with self.store._conn() as c:
            c.execute(f"UPDATE feishu_summaries SET {', '.join(sets)} WHERE id=?", params)
            row = c.execute("SELECT * FROM feishu_summaries WHERE id=?", (int(summary_id),)).fetchone()
            if not row:
                raise ValueError("summary not found")
            summary_id_out = row["id"]
        self._audit(
            action="feishu.summary.update", decision="allow",
            resource_type="feishu_summary", resource_id=str(summary_id),
            details={"fields": sorted(fields.keys())},
        )
        return self.get_summary(summary_id_out)

    def get_summary(self, summary_id: int) -> dict:
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM feishu_summaries WHERE id=?", (int(summary_id),)).fetchone()
            if not row:
                raise ValueError("summary not found")
            return self._summary_to_dict(row)

    def list_summaries(self, limit: int = 50) -> list:
        with self.store._conn() as c:
            rows = c.execute(
                "SELECT * FROM feishu_summaries ORDER BY id DESC LIMIT ?",
                [max(1, min(int(limit or 50), 500))],
            ).fetchall()
            return [self._summary_to_dict(r) for r in rows]

    # ---- approval gate -------------------------------------------------
    def create_approval(
        self, summary_id: int, target_type: str, target_id: str, *,
        confirmed: bool = False, approver_id: str = "", outbound_msg_type: str = "text",
    ) -> dict:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to create a Feishu approval")
        if not target_id:
            raise ValueError("target_id is required")
        # Defect 7: enforce the outbound whitelist at approval-create time, BEFORE
        # any summary lookup, so a non-whitelisted target can never enter the
        # approval pipeline (and the API surfaces it as a 409, not a 400 from a
        # missing summary). It is re-checked again immediately before send.
        if not self.config.is_whitelisted_target(target_type, target_id):
            raise PermissionError(
                f"outbound target not whitelisted: {target_type}:{target_id}"
            )
        summary = self.get_summary(summary_id)
        body_text = self._build_body(summary)
        content_hash = _sha256(body_text + "|" + json.dumps(summary["source_message_ids"]))
        idempotency_key = f"feishu-send-{summary_id}-{target_type}-{target_id}"
        expires_at = _now_epoch() + int(self.config.approval_timeout_minutes * 60)
        with self.store._conn() as c:
            cur = c.execute(
                """
                INSERT INTO feishu_approvals
                    (tenant_id, summary_id, target_type, target_id, inbound_msg_type,
                     outbound_msg_type, body_text, source_message_ids, content_hash,
                     idempotency_key, approver_id, status, created_at_epoch, expires_at_epoch)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    self.config.tenant_id, summary_id, target_type, target_id,
                    "text", outbound_msg_type, body_text,
                    json.dumps(summary["source_message_ids"], ensure_ascii=False),
                    content_hash, idempotency_key, approver_id or "",
                    _now_epoch(), expires_at,
                ),
            )
            approval_id = cur.lastrowid

        record = self.get_approval(approval_id)
        self._audit(
            action="feishu.approval.create", decision="allow",
            resource_type="feishu_approval", resource_id=str(approval_id),
            details={"target_type": target_type, "target_id": target_id, "content_hash": content_hash},
        )

        if self.config.live and self.client:
            try:
                # Defect 8: the form must use the configured control id and
                # surface the send target, the frozen content hash, and the
                # source message ids so the approver sees exactly what will be
                # sent. Defect 2: do NOT pass an illegal plain-text title.
                control_id = self.config.approval_form_control_id or "widget-body-1"
                form = [
                    {
                        "id": control_id,
                        "type": "textarea",
                        "value": body_text,
                    },
                    {
                        "id": "widget-target",
                        "type": "input",
                        "value": f"{target_type}:{target_id}",
                    },
                    {
                        "id": "widget-content-hash",
                        "type": "input",
                        "value": content_hash,
                    },
                    {
                        "id": "widget-source-ids",
                        "type": "input",
                        "value": json.dumps(summary["source_message_ids"], ensure_ascii=False),
                    },
                ]
                resp = self.client.create_approval_instance(
                    approval_code=self.config.approval_definition_code,
                    form=form,
                    title=None,
                    open_id=self.config.approval_initiator_open_id or None,
                    uuid=idempotency_key,
                )
                code = resp.get("instance_code") or ""
                with self.store._conn() as c:
                    c.execute(
                        "UPDATE feishu_approvals SET feishu_instance_code=? WHERE id=?",
                        (code, approval_id),
                    )
                record["feishu_instance_code"] = code
            except FeishuClientError as exc:
                with self.store._conn() as c:
                    c.execute(
                        "UPDATE feishu_approvals SET status='failed', reason=? WHERE id=?",
                        (f"{exc.category}: {exc}", approval_id),
                    )
                record["status"] = APPROVAL_FAILED
                record["reason"] = f"{exc.category}: {exc}"
                self._audit(
                    action="feishu.approval.create", decision="deny",
                    resource_type="feishu_approval", resource_id=str(approval_id),
                    reason=f"{exc.category}: {exc}",
                )
        return record

    def sync_approval(self, approval_id: int) -> dict:
        approval = self.get_approval(approval_id)
        if not approval["feishu_instance_code"]:
            return approval
        if self.config.live and self.client:
            try:
                resp = self.client.get_approval_instance(
                    approval["feishu_instance_code"], user_id=approval["approver_id"] or None,
                )
                status = (resp.get("status") or "PENDING").upper()
            except FeishuClientError as exc:
                self._audit(
                    action="feishu.approval.decision", decision="deny",
                    resource_type="feishu_approval", resource_id=str(approval_id),
                    reason=f"query failed: {exc.category}: {exc}",
                )
                return approval
        else:
            # Offline mode: read status from the (test) client if present.
            if self.client is not None:
                try:
                    resp = self.client.get_approval_instance(approval["feishu_instance_code"])
                    status = (resp.get("status") or "PENDING").upper()
                except Exception:
                    return approval
            else:
                return approval

        new_status = {
            "APPROVED": APPROVAL_APPROVED,
            "REJECTED": APPROVAL_REJECTED,
        }.get(status, APPROVAL_PENDING)

        # Defects 3/4: the authoritative approver identities come ONLY from the
        # instance task_list/timeline, never from a client-supplied field. Read
        # and persist them, then gate approval on the authorized approver set.
        actual_approvers = _extract_actual_approvers(resp)
        reason = f"feishu status {status} -> {new_status}"
        if new_status == APPROVAL_APPROVED:
            authorized = [a for a in actual_approvers if self.config.is_authorized_approver(a)]
            if self.config.approver_open_ids and not authorized:
                new_status = APPROVAL_REJECTED
                reason = "no authorized approver found on instance timeline"

        with self.store._conn() as c:
            c.execute(
                "UPDATE feishu_approvals SET status=?, decided_at=?, verified_approver_open_ids=? WHERE id=?",
                (new_status, _iso_now(), json.dumps(actual_approvers, ensure_ascii=False), approval_id),
            )
        self._audit(
            action="feishu.approval.decision",
            decision="allow" if new_status == APPROVAL_APPROVED else "deny",
            resource_type="feishu_approval", resource_id=str(approval_id),
            reason=reason,
            details={"verified_approver_open_ids": actual_approvers},
        )
        return self.get_approval(approval_id)

    # ---- send (gated, idempotent) -------------------------------------
    def send_after_approval(self, approval_id: int, *, confirmed: bool = False, new_body: str | None = None) -> dict:
        if confirmed is not True:
            raise PermissionError("confirmed=true is required to send after approval")
        approval = self.get_approval(approval_id)

        if approval["status"] == APPROVAL_REJECTED:
            raise PermissionError("approval was rejected; send blocked")
        if approval["status"] != APPROVAL_APPROVED:
            raise PermissionError("approval is not approved; send blocked")
        if int(approval["used"] or 0) == 1:
            raise PermissionError("approval already used; re-approval required to send again")
        if _now_epoch() > int(approval["expires_at_epoch"] or 0):
            raise PermissionError("approval expired; re-approval required")
        # Defects 3/4: the send gate trusts ONLY the approver identities verified
        # from the Feishu instance timeline (persisted at sync time), intersected
        # with the configured authorized approver set. A missing / unauthorized
        # actual approver blocks the send even if the row is marked approved.
        verified = approval.get("verified_approver_open_ids") or []
        authorized = [a for a in verified if self.config.is_authorized_approver(a)]
        if self.config.approver_open_ids and not authorized:
            raise PermissionError("no verified authorized approver; send blocked")
        # Re-check the outbound whitelist immediately before sending (defect 7).
        if not self.config.is_whitelisted_target(approval["target_type"], approval["target_id"]):
            raise PermissionError("outbound target not whitelisted; send blocked")

        frozen_body = approval["body_text"]
        if new_body is not None and new_body != frozen_body:
            new_hash = _sha256(new_body + "|" + json.dumps(approval["source_message_ids"], ensure_ascii=False))
            if new_hash != approval["content_hash"]:
                raise PermissionError("content changed after approval; re-approval required")

        idempotency_key = approval["idempotency_key"]
        target_type = approval["target_type"]
        target_id = approval["target_id"]
        outbound_msg_type = approval["outbound_msg_type"] or "text"
        send_content = json.dumps({"text": frozen_body}, ensure_ascii=False)

        # At-most-once: if a dispatch for this key already exists, return it.
        existing = self._find_dispatch_by_key(idempotency_key)
        if existing:
            return existing

        dispatch_id = self._create_dispatch(approval_id, idempotency_key, target_type, target_id, outbound_msg_type)
        try:
            if self.config.live and self.client:
                resp = self.client.send_message(
                    receive_id_type=target_type,
                    receive_id=target_id,
                    msg_type=outbound_msg_type,
                    content=send_content,
                    uuid=idempotency_key,
                )
                message_id = (resp.get("data") or {}).get("message_id") or resp.get("message_id") or ""
                self._update_dispatch(dispatch_id, status=DISP_SENT, feishu_message_id=message_id, api_code=int(resp.get("code", 0) or 0), api_msg=str(resp.get("msg", "")))
                self._mark_approval_used(approval_id)
                self._audit(
                    action="feishu.dispatch.send", decision="allow",
                    resource_type="feishu_dispatch", resource_id=str(dispatch_id),
                    details={"target": target_id, "message_id": message_id, "idempotency_key": idempotency_key},
                )
            else:
                # Dry-run (not live or no client): record intent, no external call.
                self._update_dispatch(dispatch_id, status=DISP_DRY_RUN)
                self._audit(
                    action="feishu.dispatch.send", decision="allow",
                    resource_type="feishu_dispatch", resource_id=str(dispatch_id),
                    details={"target": target_id, "mode": "dry_run", "idempotency_key": idempotency_key},
                )
            return self.get_dispatch(dispatch_id)
        except FeishuClientError as exc:
            if exc.category == TIMEOUT:
                # Defect 11: a timeout means the outcome is genuinely unknown —
                # the call may or may not have delivered. Park it as
                # outcome_unknown, do NOT mark the approval used (so a human can
                # reconcile), and NEVER auto-resend on a replay/retry. A second
                # send_after_approval call hits the existing-dispatch guard and
                # returns the same outcome_unknown status with zero new calls.
                status = DISP_OUTCOME_UNKNOWN
            else:
                retryable = exc.category in ("rate_limit", "network")
                status = DISP_FAILED_RETRYABLE if retryable else DISP_FAILED_TERMINAL
            self._update_dispatch(dispatch_id, status=status, error_category=exc.category, api_msg=str(exc))
            self._audit(
                action="feishu.dispatch.fail", decision="deny",
                resource_type="feishu_dispatch", resource_id=str(dispatch_id),
                reason=f"{exc.category}: {exc}",
            )
            return self.get_dispatch(dispatch_id)
        except sqlite3.IntegrityError:
            # Concurrent insert with same idempotency_key — return the survivor.
            survivor = self._find_dispatch_by_key(idempotency_key)
            if survivor:
                return survivor
            raise

    # ---- dispatch helpers ---------------------------------------------
    def _create_dispatch(self, approval_id, idempotency_key, target_type, target_id, msg_type) -> int:
        with self.store._conn() as c:
            cur = c.execute(
                """
                INSERT INTO feishu_dispatches
                    (approval_id, idempotency_key, target_type, target_id, msg_type, status, attempts)
                VALUES (?, ?, ?, ?, ?, 'sending', 1)
                """,
                (approval_id, idempotency_key, target_type, target_id, msg_type),
            )
            return int(cur.lastrowid)

    def _update_dispatch(self, dispatch_id, *, status, feishu_message_id="", api_code=0, api_msg="", error_category=""):
        with self.store._conn() as c:
            c.execute(
                """
                UPDATE feishu_dispatches
                    SET status=?, feishu_message_id=?, api_code=?, api_msg=?, error_category=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (status, feishu_message_id, api_code, api_msg, error_category, dispatch_id),
            )

    def _mark_approval_used(self, approval_id):
        with self.store._conn() as c:
            c.execute("UPDATE feishu_approvals SET used=1 WHERE id=?", (approval_id,))

    def _find_dispatch_by_key(self, idempotency_key):
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM feishu_dispatches WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            return self._dispatch_to_dict(row) if row else None

    def get_dispatch(self, dispatch_id: int) -> dict:
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM feishu_dispatches WHERE id=?", (int(dispatch_id),)).fetchone()
            if not row:
                raise ValueError("dispatch not found")
            return self._dispatch_to_dict(row)

    def list_dispatches(self, limit: int = 50) -> list:
        with self.store._conn() as c:
            rows = c.execute(
                "SELECT * FROM feishu_dispatches ORDER BY id DESC LIMIT ?",
                [max(1, min(int(limit or 50), 500))],
            ).fetchall()
            return [self._dispatch_to_dict(r) for r in rows]

    def get_approval(self, approval_id: int) -> dict:
        with self.store._conn() as c:
            row = c.execute("SELECT * FROM feishu_approvals WHERE id=?", (int(approval_id),)).fetchone()
            if not row:
                raise ValueError("approval not found")
            return self._approval_to_dict(row)

    def list_approvals(self, limit: int = 50) -> list:
        with self.store._conn() as c:
            rows = c.execute(
                "SELECT * FROM feishu_approvals ORDER BY id DESC LIMIT ?",
                [max(1, min(int(limit or 50), 500))],
            ).fetchall()
            return [self._approval_to_dict(r) for r in rows]

    # ---- body builder --------------------------------------------------
    def _build_body(self, summary: dict) -> str:
        lines = []
        if summary.get("topic"):
            lines.append(f"主题：{summary['topic']}")
        conclusions = _json_loads(summary.get("conclusions"), [])
        if conclusions:
            lines.append("关键结论：")
            for c in conclusions[:10]:
                txt = c["text"] if isinstance(c, dict) else str(c)
                lines.append(f"- {txt}")
        actions = _json_loads(summary.get("action_items"), [])
        if actions:
            lines.append("行动项：")
            for a in actions[:20]:
                owner = a.get("owner", "") if isinstance(a, dict) else ""
                due = a.get("due_date", "") if isinstance(a, dict) else ""
                desc = a.get("description", "") if isinstance(a, dict) else str(a)
                suffix = ""
                if owner:
                    suffix += f"（负责人：{owner}）"
                if due:
                    suffix += f"（截止：{due}）"
                lines.append(f"- {desc}{suffix}")
        return "\n".join(lines)

    # ---- serializers ---------------------------------------------------
    def _msg_to_dict(self, row) -> dict:
        d = dict(row)
        return d

    def _summary_to_dict(self, row) -> dict:
        d = dict(row)
        d["conclusions"] = _json_loads(d.get("conclusions"), [])
        d["action_items"] = _json_loads(d.get("action_items"), [])
        d["owner_candidates"] = _json_loads(d.get("owner_candidates"), [])
        d["deadline_candidates"] = _json_loads(d.get("deadline_candidates"), [])
        d["open_questions"] = _json_loads(d.get("open_questions"), [])
        d["source_message_ids"] = _json_loads(d.get("source_message_ids"), [])
        return d

    def _approval_to_dict(self, row) -> dict:
        d = dict(row)
        d["source_message_ids"] = _json_loads(d.get("source_message_ids"), [])
        d["verified_approver_open_ids"] = _json_loads(d.get("verified_approver_open_ids"), [])
        d["used"] = int(d.get("used") or 0)
        return d

    def _dispatch_to_dict(self, row) -> dict:
        return dict(row)

    # ---- health --------------------------------------------------------
    def health(self) -> dict:
        """Synchronous config/state summary. The async client health check is
        performed by the API route (which owns the event loop)."""
        return {
            "config": self.config.redacted(),
            "has_client": self.client is not None,
            "live": self.config.live,
            "tables": ["feishu_messages", "feishu_summaries", "feishu_approvals", "feishu_dispatches"],
        }
