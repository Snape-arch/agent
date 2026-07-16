# 飞书连接器 v2 运维手册（Runbook）

> 适用范围：ClawOS 飞书连接器 v2（含 §13 资源式 API 与真实迁移）。
> 当前状态：**自动化门禁全绿，真实租户验收待用户授权**。`FEISHU_LIVE=false`，未连接真实租户，未做任何对外发送。

---

## 1. 这是什么

飞书连接器让 ClawOS 通过飞书接收消息事件、生成会议/对话摘要、走真实审批流后再对外发送，且所有对外写操作 **fail closed**（默认拒绝、需显式确认 + 白名单 + 授权审批人）。

关键事实（截至 2026-07-16）：

- v2 整改已完成至 **Phase 5**，计划书§3 列出的 12 个阻断缺陷全部关闭。
- **36/36** 飞书测试全绿：`test_feishu_api`(13) + `test_feishu_connector`(23) + `test_feishu_migration`(4)。
- **§13 架构性重构已完成**：废弃单一 `POST /api/feishu` action 路由，改为资源式端点；写操作强制严格 Pydantic 请求模型。
- 建表与升级已移入真实迁移（`MaintenanceService.apply_migrations()` → `2026_07_feishu_connector` → `services/feishu/schema.py`），幂等、可重跑。
- **真实租户验收尚未开始**：`FEISHU_LIVE` 必须为 `false`，直到全量回归通过且用户明确授权。

---

## 2. 配置

所有配置来自环境变量，模板见仓库根 `.env.example`（不可含真实密钥）。

| 变量 | 说明 | 备注 |
| --- | --- | --- |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_TENANT_ID` | 应用凭证与租户 | 三者齐备 `is_configured()` 才为真 |
| `FEISHU_EVENT_MODE` | `long_connection`（默认）或 `webhook` | 长连接由 SDK 鉴权；webhook 需校验 `verification_token` |
| `FEISHU_VERIFICATION_TOKEN` / `FEISHU_ENCRYPT_KEY` | webhook 校验/加密 | 仅 webhook 模式需要 |
| `FEISHU_ALLOWED_CHAT_IDS` | 入站白名单聊天 | 逗号分隔 |
| `FEISHU_ALLOWED_TARGET_OPEN_IDS` | 出站白名单目标 open_id | 逗号分隔；非白名单目标在审批创建即被拒（409） |
| `FEISHU_APPROVAL_CODE` | 审批定义码 | 缺失则 `approval_code_present=false` |
| `FEISHU_APPROVAL_FORM_CONTROL_ID` | 审批表单正文控件 id | 必须配置化，禁止非法纯文本标题 |
| `FEISHU_APPROVAL_INITIATOR_OPEN_ID` | 审批发起人 open_id | 缺失则 `approval_initiator_present=false` |
| `FEISHU_APPROVER_OPEN_IDS` | 授权审批人 open_id 列表 | 逗号分隔；发送前强制校验实际审批人 |
| `FEISHU_LIVE` | `true/false` | **当前必须 false** |
| `FEISHU_BASE_URL` | 固定为 `https://open.feishu.cn`，不可被 env 覆盖 | 防 SSRF |
| `FEISHU_MESSAGE_RETENTION_DAYS` | 消息留存天数 | 默认见 `config.py` |

`config.redacted()` 暴露给前端健康面板，**绝不**包含 `app_secret`。

### 健康检查响应形状

`GET /api/feishu/health` 返回：

```json
{
  "config": {
    "event_mode": "long_connection",
    "live": false,
    "configured": false,
    "approval_code_present": false,
    "approval_form_control_present": false,
    "approval_initiator_present": false,
    "whitelist_chats": 0,
    "whitelist_target_open_ids": 0,
    "approvers": 0,
    "message_retention_days": 30
  },
  "client": { "connection": "no_client", "configured": false }
}
```

---

## 3. 资源式 API（§13）

| 方法 & 路径 | 用途 | 关键请求模型 | 失败语义 |
| --- | --- | --- | --- |
| `GET /api/feishu/health` | 健康/配置快照 | — | 503 仅当服务缺失 |
| `POST /api/feishu/events` | webhook 事件接收（仅 webhook） | — | 400 非法负载；403 token 不符；URL 验证回显 challenge |
| `GET /api/feishu/messages?limit=50` | 已收消息列表 | — | — |
| `POST /api/feishu/summaries` | 由消息 id 生成摘要 | `FeishuSummaryCreate{message_ids:list[int]}` | 422 校验；404 无消息；400 格式 |
| `PATCH /api/feishu/summaries/{id}` | 编辑摘要（主题/结论/行动项/负责人候选/期限候选/待决问题） | `FeishuSummaryUpdate{...可选}` | 422/404 |
| `GET /api/feishu/summaries?limit=50` | 摘要列表 | — | — |
| `POST /api/feishu/approvals` | 创建审批 | `FeishuApprovalCreate{summary_id:int, target_type, target_id(非空), approver_id, outbound_msg_type, confirmed:bool}` | **409 非白名单/未确认/已占用**；422 校验；404 摘要不存在 |
| `POST /api/feishu/approvals/{id}/sync` | 同步远端审批状态 | — | 404/503 |
| `POST /api/feishu/approvals/{id}/send` | 审批后发送 | `FeishuApprovalSend{confirmed:bool, body?:str}` | 409 未批准/已用/过期/无授权审批人/内容变更；**504 超时且结果未知（outcome_unknown，不自动重发）** |
| `GET /api/feishu/approvals?limit=50` | 审批列表 | — | — |
| `GET /api/feishu/dispatches?limit=50` | 发送调度（含 attempts/feishu_message_id/api_code/api_msg/trace_id） | — | — |

状态码约定：`400` 格式/配置，`401/403` 鉴权，`404` 资源不存在，`409` 冲突（白名单/审批/幂等），`422` 请求校验失败，`502` 上游失败，`503` 不可用，`504` 超时/结果未知。

---

## 4. 启动 / 关闭

### 启动

```powershell
# 仓库根（按需激活 venv）
cd clawos
.\.venv\Scripts\python.exe -m uvicorn clawos_server:app --host 127.0.0.1 --port 8000
```

- 连接器服务在应用启动时构建；`MaintenanceService.apply_migrations()` 在初始化阶段运行，按 `schema_migrations` 表记录**幂等**建表（`feishu_messages` / `feishu_summaries` / `feishu_approvals` / `feishu_dispatches`），并对 `feishu_approvals.verified_approver_open_ids` 做带 PRAGMA 守卫的列升级。
- 长连接模式下事件由 SDK 握手鉴权后入站；webhook 模式事件走 `POST /api/feishu/events`。

### 关闭

`Ctrl+C` 终止 uvicorn 即可。无外部会话需清理（飞书长连接由 SDK 自动断开）。

---

## 5. 故障恢复

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| `GET /api/feishu/health` 返回 503 | 连接器服务未注入/未启动 | 确认应用启动日志中连接器初始化成功；检查 `g_feishu_connector_service` |
| 事件被拒 403 | webhook 模式 token 不符 | 核对 `FEISHU_VERIFICATION_TOKEN`；确认事件体携带正确 token |
| 创建审批 409「outbound target not whitelisted」 | 目标不在 `FEISHU_ALLOWED_TARGET_OPEN_IDS` | 仅可向白名单目标发起；不要把 409 当 400 误修 |
| 发送 409「no verified authorized approver」 | 实际审批人不在 `FEISHU_APPROVER_OPEN_IDS` | 审批实例的实际审批人必须被授权；否则 fail closed |
| 发送 504「outcome_unknown」 | 飞书 API 超时，结果未知 | **不自动重发**。本地已记录 dispatch 供人工对账；按 `trace_id` 查 `feishu_dispatches` 确认远端是否实际送达 |
| 摘要/审批「not found」404 | id 不存在或已清理 | 核对该资源确已创建；检查留存天数是否过期 |
| 表缺失/列缺失 | 迁移未跑或被绕过 | 重跑 `MaintenanceService.apply_migrations()`（幂等，安全）；不要在服务构造函数里手写建表 |

所有事件接收与发送均在 `feishu_audit` 留痕，**不含任何密钥/正文原始凭据**，可用于事后对账与取证。

---

## 6. 真实租户验收（需用户明确授权后执行）

> 前置：全量回归通过、用户明确授权、且 `FEISHU_LIVE=true`（仅限独立测试租户）。以下步骤绝对不要在真实生产租户执行。

1. **拒绝路径**：向非白名单目标发起发送，确认被 409 阻断，且 `send_calls == 0`。
2. **越权审批**：用未授权 open_id 作为实际审批人，确认发送被 409 阻断。
3. **授权审批**：用授权审批人走完审批，确认状态变为 approved。
4. **单次发送**：审批后发送一次，确认 at-most-once（重放/重启不重复发送）。
5. **事件重放**：同一事件 id 重放，确认幂等去重。
6. **重启恢复**：发送中重启，确认不重复、不丢、状态可恢复对账。

任一对外动作（真实发送、日历发布、`git push`、PR、状态共享）均需用户单独明确授权。

---

## 7. 现状与护栏

- ✅ 自动化门禁全绿（36 飞书测试 + 聚焦验证）。
- ✅ §13 资源式 API 与严格模型已落地；迁移已归入真实 `MaintenanceService`。
- ⏳ 全量回归（~316）计划在本会话 Task 29 于当前现场复跑。
- ⛔ `FEISHU_LIVE=false`，未连接真实租户，未做对外发送。
- ⛔ 未提交 `.env`、凭据、数据库、日志、缓存、上传、模型、生成报告、浏览器证据。
- ⛔ 任何 `git push` / PR / 对外发送 / 共享状态变更，均需用户明确授权。
