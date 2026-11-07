"""Feishu HTTP adapters with explicit application dependencies."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from fastapi import APIRouter
from services.academy_documents import AcademyDocuments
from api.request_models import FeishuApprovalCreate
from api.request_models import FeishuApprovalSend
from api.request_models import FeishuSummaryCreate
from api.request_models import FeishuSummaryUpdate
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi import Request
from pydantic import ValidationError


class FeishuAPI:
    def __init__(self, *,
        _collaboration: Callable[..., Any],
        _feishu_service: Callable[..., Any],
        _learning_product: Callable[..., Any],
    ):
        self._collaboration = _collaboration
        self._feishu_service = _feishu_service
        self._learning_product = _learning_product
        self.router = APIRouter()
        self.router.add_api_route('/api/feishu/health', self.api_feishu_health, methods=['GET'])
        self.router.add_api_route('/api/feishu/events', self.api_feishu_events, methods=['POST'])
        self.router.add_api_route('/api/feishu/messages', self.api_feishu_messages, methods=['GET'])
        self.router.add_api_route('/api/feishu/summaries', self.api_feishu_summaries_create, methods=['POST'])
        self.router.add_api_route('/api/feishu/summaries/{summary_id}', self.api_feishu_summaries_update, methods=['PATCH'])
        self.router.add_api_route('/api/feishu/summaries', self.api_feishu_summaries_list, methods=['GET'])
        self.router.add_api_route('/api/feishu/approvals', self.api_feishu_approvals_create, methods=['POST'])
        self.router.add_api_route('/api/feishu/approvals/{approval_id}/sync', self.api_feishu_approvals_sync, methods=['POST'])
        self.router.add_api_route('/api/feishu/approvals/{approval_id}/send', self.api_feishu_approvals_send, methods=['POST'])
        self.router.add_api_route('/api/feishu/dispatches', self.api_feishu_dispatches, methods=['GET'])
        self.router.add_api_route('/api/feishu/approvals', self.api_feishu_approvals_list, methods=['GET'])
        self.router.add_api_route('/api/feishu/permissions', self.feishu_permissions, methods=['GET'])
        self.router.add_api_route('/api/feishu/documents/{nid}/draft', self.feishu_document_draft, methods=['POST'])

    def _feishu_status_for(self, exc: Exception) -> int:
        """Map a service-level exception to a §13 HTTP status code."""
        if isinstance(exc, PermissionError):
            return 409  # approval status / hash / target / idempotency conflict
        if isinstance(exc, ValueError):
            msg = str(exc)
            if "not found" in msg or "no received messages" in msg:
                return 404  # resource does not exist
            return 400  # format or config error
        if isinstance(exc, RuntimeError):
            return 503  # connector unavailable
        return 400


    async def _feishu_validate(self, model, request):
        try:
            return model.model_validate(await request.json())
        except ValidationError as exc:
            raise HTTPException(422, f"invalid request: {exc}")


    async def api_feishu_health(self):
        service = self._feishu_service()
        if service.client is not None:
            client_health = service.client.health_check()
        else:
            client_health = {"connection": "no_client", "configured": service.config.is_configured()}
        return {"config": service.config.redacted(), "client": client_health}


    async def api_feishu_events(self, request: Request):
        # Webhook event ingestion (§8.2). Long-connection events arrive via the SDK
        # and are not posted here. Quick-ack then process.
        try:
            event = await request.json()
        except Exception:
            raise HTTPException(400, "invalid event payload")

        # 1) URL verification handshake: echo the challenge, store nothing.
        if isinstance(event, dict) and event.get("type") == "url_verification":
            return JSONResponse({"challenge": event.get("challenge", "")})

        service = self._feishu_service()
        cfg = service.config

        # 2) Webhook source verification (spec defect 5). In webhook mode with a
        #    configured verification token, reject any event whose token does not
        #    match BEFORE it can be parsed/stored. Long-connect events are already
        #    authenticated by the SDK handshake, so this gate is webhook-only.
        if getattr(cfg, "event_mode", "") == "webhook" and getattr(cfg, "verification_token", ""):
            header = event.get("header") if isinstance(event, dict) else None
            token = ""
            if isinstance(header, dict):
                token = str(header.get("token") or "")
            if not token:
                token = str(event.get("token") or "") if isinstance(event, dict) else ""
            if token != cfg.verification_token:
                raise HTTPException(403, "invalid verification token")

        try:
            record = service.receive_event(event, received_via="http")
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(self._feishu_status_for(exc), str(exc))
        return JSONResponse({
            "code": 0, "msg": "success",
            "data": {"message_id": record.get("message_id"), "status": record.get("processed_status")},
        })


    async def api_feishu_messages(self, chat_id: str = "", limit: int = 50):
        return self._feishu_service().list_messages(chat_id=chat_id, limit=limit)


    async def api_feishu_summaries_create(self, request: Request):
        service = self._feishu_service()
        body = await self._feishu_validate(FeishuSummaryCreate, request)
        try:
            return service.generate_summary(body.message_ids, summarizer=None)
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(self._feishu_status_for(exc), str(exc))


    async def api_feishu_summaries_update(self, summary_id: int, request: Request):
        service = self._feishu_service()
        body = await self._feishu_validate(FeishuSummaryUpdate, request)
        fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
        try:
            return service.update_summary(summary_id, fields)
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(self._feishu_status_for(exc), str(exc))


    async def api_feishu_summaries_list(self, limit: int = 50):
        return self._feishu_service().list_summaries(limit=limit)


    async def api_feishu_approvals_create(self, request: Request):
        service = self._feishu_service()
        body = await self._feishu_validate(FeishuApprovalCreate, request)
        try:
            return service.create_approval(
                body.summary_id, body.target_type, body.target_id,
                confirmed=body.confirmed, approver_id=body.approver_id,
                outbound_msg_type=body.outbound_msg_type,
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(self._feishu_status_for(exc), str(exc))


    async def api_feishu_approvals_sync(self, approval_id: int):
        service = self._feishu_service()
        try:
            return service.sync_approval(approval_id)
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(self._feishu_status_for(exc), str(exc))


    async def api_feishu_approvals_send(self, approval_id: int, request: Request):
        service = self._feishu_service()
        body = await self._feishu_validate(FeishuApprovalSend, request)
        try:
            dispatch = service.send_after_approval(
                approval_id, confirmed=body.confirmed, new_body=body.body,
            )
        except (ValueError, PermissionError, RuntimeError) as exc:
            raise HTTPException(self._feishu_status_for(exc), str(exc))
        # §13: a send timeout leaves the outcome unknown; surface 504 while still
        # recording the dispatch locally for manual reconciliation. Never auto-resend.
        if dispatch.get("status") == "outcome_unknown":
            return JSONResponse(dispatch, status_code=504)
        return dispatch


    async def api_feishu_dispatches(self, limit: int = 50):
        return self._feishu_service().list_dispatches(limit=limit)


    async def api_feishu_approvals_list(self, limit: int = 50):
        return self._feishu_service().list_approvals(limit=limit)


    async def feishu_permissions(self):
        cfg=self._feishu_service().config
        return {'config':cfg.redacted(),'targets':[{'type':'chat','id':x} for x in cfg.allowed_chat_ids]+[{'type':'user','id':x} for x in cfg.allowed_target_open_ids],
            'checks':[{'name':'消息接收','ready':bool(cfg.allowed_chat_ids),'detail':'群白名单 + 官方 SDK / 已验证 webhook；只读取白名单消息'},
                      {'name':'审批','ready':bool(cfg.approval_definition_code and cfg.approval_form_control_id and cfg.approval_initiator_open_id),'detail':'使用已配置的真实表单控件；正文、目标、内容摘要与来源一并展示'},
                      {'name':'审批人','ready':bool(cfg.approver_open_ids),'detail':'从原生审批 APPROVED 任务 / PASS 记录核验 open_id，发送前重新读取'},
                      {'name':'本地访问','ready':True,'detail':'仅本机所有者可操作连接器；文档邀请不会授予连接器或数据库权限'}],
            'boundary':'配置状态不等于飞书平台已授予 scope；原生 API 拒绝会返回权限类别。未进行云文档 ACL 同步。'}


    async def feishu_document_draft(self, nid:str,request:Request):
        uid=self._collaboration().identity(request)['id']
        self._collaboration().require(nid,uid,'owner')
        s=AcademyDocuments(self._learning_product().store);doc=s.get(nid,uid)
        text=s.markdown(doc)
        if len(text)>20000:raise HTTPException(400,'飞书草稿最多 20,000 字，请选择较短文档')
        return self._feishu_service().document_draft(doc['title'],text,f'document:{nid}#version={doc["version"]}')
