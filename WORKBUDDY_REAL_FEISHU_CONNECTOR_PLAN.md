# WorkBuddy 执行规格 v2：真实飞书工作连接器

> 状态：待整改，禁止真实外发
>
> 更新日期：2026-07-15
>
> 执行者：WorkBuddy
>
> 单一目标平台：飞书
> 规格优先级：本文件高于现有飞书草稿实现；发现代码与本文件冲突时，先更新规格或代码，不得静默降级。

## 1. 目标

在专用飞书测试租户内，用自建应用、机器人、官方事件接收能力和飞书原生审批，完成一条真实、可审计、必须经授权用户审批的闭环：

`接收白名单消息 -> 生成可溯源纪要和行动项 -> 冻结发送快照 -> 创建飞书原生审批 -> 核验实际审批人 -> 向白名单目标发送一次 -> 保存回执或失败证据`

成功不是“接口能调用”或“fake 测试通过”，而是：

- 审批前真实发送次数为 0。
- 拒绝、撤回、过期、审批人不符、内容变化、目标变化全部阻断。
- 审批通过后只向审批中展示的白名单目标发送一次。
- 进程重启、并发请求、事件重放和网络超时不会造成重复发送。
- 每个关键阶段都有脱敏、可查询、可复核的记录。
- 完成一次专用测试租户实测后，才能声明“真实飞书闭环通过”。

## 2. 默认假设

WorkBuddy 按以下假设执行；除非用户明确改变，不再自行扩大范围：

1. 使用企业自建应用，不使用商店应用。
2. 使用专用测试租户、测试群和测试人员，不使用真实业务群。
3. 首选飞书官方 Python SDK 长连接接收事件；不手写 WebSocket 握手。
4. HTTP 回调只作为可选兼容路径，启用时必须完成 URL 校验、签名或 Verification Token 校验以及加密载荷解密。
5. 首版只处理白名单群聊文本消息，只发送 `text` 消息。
6. 审批定义由租户管理员在飞书审批后台预先创建并发布。
7. 审批实例标题首版不传；如必须自定义标题，再完整实现 `@i18n@` 与 `i18n_resources`。
8. 审批发起人使用配置中的 `open_id`，实际审批人从审批实例的 `task_list` / `timeline` 中读取并核验。
9. 原始消息只按最小必要原则保存；非白名单消息不保存正文。
10. 不接邮箱、钉钉、日历或第二个协作平台。

## 3. 当前实现基线与审查结论

当前工作区已有以下未提交实现：

- `clawos/services/feishu/config.py`
- `clawos/services/feishu/feishu_client.py`
- `clawos/services/feishu/fake_client.py`
- `clawos/services/feishu/connector_service.py`
- `clawos/services/feishu/__init__.py`
- `clawos/tests/test_feishu_connector.py`
- `clawos/clawos_server.py`
- `clawos/static/console.html`
- `clawos/static/assets/console.js`
- `clawos/services/maintenance_service.py`

已验证：

- 飞书单元测试：15 个通过。
- 前端静态测试：42 个通过。
- Python AST、Node 语法和 `git diff --check` 通过。
- 未发现真实密钥进入变更。

现有实现仍有以下阻断项，修复前不得设置 `FEISHU_LIVE=true`：

1. 创建审批实例没有传 `user_id` 或 `open_id`，真实 API 请求无效。
2. 审批实例传入普通文本标题，不符合飞书 `@i18n@` 标题契约。
3. 审批同步只读取总体状态，没有核验实际做出决定的审批人。
4. `approver_id` 为空时允许名单检查被跳过。
5. HTTP 事件入口没有来源校验、URL 校验和加密载荷解密。
6. 手写长连接不符合官方 SDK 协议，且没有启动调用点。
7. 出站 `chat_id/open_id` 没有强制目标白名单。
8. 审批表单未明确展示发送目标、内容哈希和来源消息集合。
9. 非白名单消息仍会把正文写入数据库。
10. 控制台读取的健康字段与后端脱敏响应结构不一致。
11. 没有真实并发、进程重启恢复、超时后不重复发送的测试。
12. `clawos/.env.example`、依赖声明、运行手册和真实租户证据尚未补齐。

## 4. 范围

### 4.1 必须完成

- 官方 SDK 长连接接收 `im.message.receive_v1`。
- 可选 HTTP 回调的安全校验和 URL verification。
- 白名单群消息规范化、去重和最小化持久化。
- 纪要、行动项、负责人候选、截止时间候选和来源引用。
- 可编辑草稿与不可变发送快照分离。
- 飞书原生审批实例创建、查询和实际审批人核验。
- 白名单目标、审批快照和发送前二次校验。
- 数据库级幂等、状态机、失败分类和审计。
- 控制台最小闭环与一致的健康状态。
- fake 自动化测试、API 集成测试和专用测试租户验收。

### 4.2 明确不做

- 邮箱、钉钉、日历、企业微信等其他平台。
- 全租户历史消息采集。
- 自动外发、批量群发、定时群发。
- 图片、文件、音视频下载或执行。
- 富文本、卡片和交互式卡片发送。
- 已读、送达或用户行为追踪。
- 自动创建群、自动邀请成员、自动修改飞书权限。
- 自动创建或修改审批定义。
- 将 fake、mock 或本地 dry-run 表述为真实租户通过。

## 5. 技术栈与项目结构

### 5.1 技术栈

- Python 3.12。
- FastAPI。
- SQLite / 现有 MemoryStore 连接管理。
- `httpx`：飞书 OpenAPI。
- 飞书官方 Python SDK：长连接和事件分发。
- 原生 `unittest`。
- 原生浏览器 JavaScript。

新增依赖前先确认现有环境是否已安装；如需加入官方 SDK，必须同步更新依赖锁定或 requirements 文件，并记录版本。

### 5.2 目标结构

```text
clawos/services/feishu/
  __init__.py              # 稳定导出
  config.py                # 环境变量解析、边界校验、脱敏健康结构
  feishu_client.py         # OpenAPI 与官方 SDK 适配器
  connector_service.py     # 状态机、审批门禁、持久化、审计
  fake_client.py           # 无网络的行为级测试替身

clawos/tests/
  test_feishu_connector.py # 服务、客户端、并发与失败测试
  test_feishu_api.py       # API、事件安全和返回契约测试
  test_frontend_static.py  # 控制台静态契约

clawos/static/
  console.html
  assets/console.js

clawos/
  .env.example             # 只列变量名和安全示例，不写真实值
  requirements*.txt        # 官方 SDK 版本
```

如一个任务需要修改超过约 5 个文件，先拆成更小的垂直任务，不把重构、功能和 UI 混成一次修改。

## 6. 配置契约

### 6.1 必需变量

| 变量 | 作用 | 是否秘密 |
|---|---|---|
| `FEISHU_APP_ID` | 自建应用 ID | 否 |
| `FEISHU_APP_SECRET` | 自建应用密钥 | 是 |
| `FEISHU_TENANT_ID` | ClawOS 内部租户命名空间 | 否 |
| `FEISHU_APPROVAL_CODE` | 已发布审批定义 Code | 否 |
| `FEISHU_APPROVAL_FORM_CONTROL_ID` | 审批正文文本控件 ID | 否 |
| `FEISHU_APPROVAL_INITIATOR_OPEN_ID` | 审批发起人 open_id | 敏感标识 |
| `FEISHU_ALLOWED_CHAT_IDS` | 允许接收和群聊发送的 chat_id 列表 | 敏感标识 |
| `FEISHU_APPROVER_OPEN_IDS` | 允许批准外发的实际审批人列表 | 敏感标识 |
| `FEISHU_LIVE` | 真实网络写开关，默认 false | 否 |

### 6.2 可选变量

| 变量 | 默认值 | 作用 |
|---|---|---|
| `FEISHU_EVENT_MODE` | `long_connection` | `long_connection` 或 `webhook` |
| `FEISHU_ALLOWED_TARGET_OPEN_IDS` | 空 | 允许单聊发送的用户 open_id |
| `FEISHU_VERIFICATION_TOKEN` | 空 | webhook 来源校验 |
| `FEISHU_ENCRYPT_KEY` | 空 | webhook 签名与解密 |
| `FEISHU_APPROVAL_TIMEOUT_MINUTES` | 1440 | 本地审批过期时间 |
| `FEISHU_SEND_TIMEOUT_SECONDS` | 15 | OpenAPI 请求超时 |
| `FEISHU_SYNC_LIMIT` | 50 | 单次读取上限 |
| `FEISHU_MESSAGE_RETENTION_DAYS` | 30 | 最小化数据保留策略 |

删除 `FEISHU_LONG_CONNECT_URL` 和 `FEISHU_LONG_CONNECT_TOKEN`：官方长连接使用 APP_ID / APP_SECRET 建立，不接受手工拼装租户 WebSocket 地址。

### 6.3 启动校验

`FEISHU_LIVE=true` 时，任一必需配置缺失必须启动失败或将连接器标为不可用；不得自动回退到“看似成功”的 dry-run。

`base_url` 首版固定为 `https://open.feishu.cn`。如测试确需覆盖，测试通过依赖注入提供，不从生产环境变量接受任意 URL，避免密钥发送到非飞书主机。

## 7. 端到端架构

```text
Feishu test chat
        |
        v
Official SDK long connection
        |
        v
Event authenticity + schema validation
        |
        v
Inbound whitelist + event/message dedup
        |
        v
Minimal message record
        |
        v
Summary/action generation + source references
        |
        v
Editable draft
        |
        v
Immutable outbound snapshot
        |
        v
Native approval instance
        |
        v
Query instance + verify task/timeline approver
        |
        v
Recheck target/hash/expiry/unused/idempotency
        |
        v
Feishu message API
        |
        v
Receipt/failure/audit/evidence
```

事件接收、审批同步和发送服务必须是独立边界。控制台只调用后端，不直接持有飞书凭据。

## 8. 事件接收设计

### 8.1 官方长连接

- 使用官方 SDK 的事件分发器注册 `im.message.receive_v1`。
- 使用 `APP_ID` 和 `APP_SECRET` 初始化官方 WebSocket Client。
- 在应用生命周期启动后台接收任务，在关闭时优雅停止。
- 连接状态、最近事件时间和最后错误写入内存健康状态，不写 token。
- 断线重连使用 SDK 行为；不得自建无限快速重连循环。
- 事件处理只做验证、去重和入队/入库，耗时摘要异步执行。

### 8.2 HTTP 回调兼容路径

只有 `FEISHU_EVENT_MODE=webhook` 时启用：

- 处理 URL verification challenge。
- 配置 Encrypt Key 时先验证签名再解密。
- 未配置 Encrypt Key 时至少核验 Verification Token。
- 时间戳过旧、签名不符、token 不符、重复 event_id 全部拒绝。
- 记录脱敏拒绝原因，不回显验证密钥。
- 在飞书要求的响应窗口内返回；摘要和模型调用不得阻塞回调响应。

### 8.3 消息白名单和隐私

- 入站只接受 `allowed_chat_ids`。
- 非白名单事件只记录 event_id 哈希、拒绝类别和时间，不保存正文、发送者 ID 或附件元数据。
- 白名单消息只保存处理所需的安全文本；设置长度上限。
- 首版只接受 `text`。其他类型标为 `unsupported_type`，不展开 payload。
- API 默认不返回完整原始消息；控制台显示经过截断和转义的文本。
- 到期消息按保留策略清理，但不得删除审批、发送和审计证据所需哈希。

## 9. 纪要与发送快照

### 9.1 纪要

输出结构固定为：

```json
{
  "topic": "string",
  "conclusions": [
    {"text": "string", "source_message_id": "om_x", "source_timestamp": "epoch"}
  ],
  "action_items": [
    {
      "description": "string",
      "owner": "string",
      "due_date": "string",
      "source_message_id": "om_x",
      "source_timestamp": "epoch"
    }
  ],
  "owner_candidates": [],
  "deadline_candidates": [],
  "open_questions": []
}
```

所有结论和行动项必须有真实来源。模型失败时保留消息处理状态和错误类别，不生成空审批。

### 9.2 可编辑草稿与冻结快照

- 纪要为可编辑草稿。
- 创建审批时复制出不可变发送快照。
- 快照包含：tenant、目标类型、目标 ID、消息类型、完整发送正文、来源 message_id、审批发起人、审批定义、创建时间、过期时间。
- 规范化 JSON 后计算 SHA256，不能只对正文计算。
- 审批创建后修改纪要不会改变快照。
- 如需修改正文或目标，必须废弃旧审批并创建新快照。

## 10. 飞书原生审批门禁

### 10.1 创建审批实例

调用 `POST /open-apis/approval/v4/instances` 时必须：

- 传入已发布的 `approval_code`。
- 传入 `open_id=FEISHU_APPROVAL_INITIATOR_OPEN_ID`。
- `form` 控件 ID 使用 `FEISHU_APPROVAL_FORM_CONTROL_ID`，不得硬编码猜测。
- 表单正文明确展示：发送平台、目标类型、目标 ID、消息正文、内容 SHA256、来源消息 ID、过期时间。
- 使用稳定审批幂等 UUID。
- 首版不传 `title`，避免不完整的 i18n 请求。
- 保存返回的 instance_code；返回为空视为失败。

### 10.2 同步审批状态

获取单个审批实例详情后必须核验：

- instance_code 与本地审批绑定。
- approval_code 与配置一致。
- uuid 与本地幂等键一致。
- form 中的目标、正文摘要和内容哈希与冻结快照一致。
- 状态属于已知枚举。
- `APPROVED` 时，从 `task_list` / `timeline` 提取实际完成审批的用户。
- 至少一个实际批准者在 `FEISHU_APPROVER_OPEN_IDS` 中。
- 审批人字段缺失、无法解析或允许名单为空时一律不发送。
- `CANCELED`、`DELETED`、`REJECTED`、未知状态全部阻断。
- 查询失败保持原状态并记录错误，不把旧状态自动视为继续有效。

### 10.3 发送前最终门禁

发送事务开始前重新读取数据库并逐项检查：

- `FEISHU_LIVE=true`。
- 客户端已鉴权。
- 审批状态为 approved。
- 实际审批人已核验并持久化。
- 未过期、未撤回、未使用。
- target_type 只允许 `chat_id` 或 `open_id` 的内部枚举。
- 目标位于对应出站白名单。
- 当前快照 SHA256 等于审批冻结 SHA256。
- 审批 instance_code、approval_code、uuid 完整匹配。
- 同一幂等键没有已发送或不确定状态的 dispatch。

任何一项不满足均返回阻断结果，不调用发送客户端。

## 11. 幂等、并发和失败恢复

### 11.1 状态机

审批状态：

`draft -> pending -> approved | rejected | canceled | expired | failed`

发送状态：

`pending_approval -> reserved -> sending -> sent | failed_retryable | failed_terminal | outcome_unknown`

不允许任意逆向跳转。状态更新使用条件更新，例如：

```python
updated = conn.execute(
    """
    UPDATE feishu_dispatches
       SET status = 'reserved'
     WHERE idempotency_key = ?
       AND status = 'pending_approval'
    """,
    (idempotency_key,),
).rowcount
if updated != 1:
    return existing_dispatch
```

### 11.2 数据库级并发控制

- 幂等键唯一约束是必要条件，不是完整并发方案。
- 创建 dispatch、占用审批和状态转换必须在同一数据库事务中完成。
- 先成功 reserve 的请求才有权调用飞书发送 API。
- 并发失败者返回已有 dispatch，不得再次发送。
- 不允许先查后插而把唯一冲突处理放在不会捕获异常的位置。

### 11.3 超时和未知结果

- 飞书发送 API 超时可能发生在服务端已接收之后，不能直接重试。
- 超时后状态设为 `outcome_unknown`。
- 使用同一 uuid 查询或通过受控核验确认结果；无法确认时人工处理。
- `outcome_unknown` 不允许自动重发。
- 只有能证明飞书未接收，且审批仍有效时，才允许显式人工重试。
- 进程在发送后、落库前崩溃时，重启恢复不得自动重发。

## 12. 数据模型

### 12.1 feishu_messages

关键字段：

- tenant_id
- event_id_hash / event_id
- message_id
- chat_id
- sender_id（仅白名单事件）
- message_type
- safe_text
- create_time
- processed_status
- received_at
- retention_until

唯一约束：

- `(tenant_id, event_id)`
- `(tenant_id, message_id)`

### 12.2 feishu_summaries

- tenant_id
- topic
- conclusions_json
- action_items_json
- source_message_ids_json
- status
- created_at / updated_at

### 12.3 feishu_approvals

- tenant_id
- summary_id
- approval_code
- instance_code
- approval_uuid
- initiator_open_id
- verified_approver_open_ids_json
- target_type
- target_id
- outbound_msg_type
- snapshot_json
- content_hash
- status
- reason
- created_at / decided_at / expires_at
- used_at

### 12.4 feishu_dispatches

- approval_id
- idempotency_key
- target_type / target_id
- status
- attempts
- feishu_message_id
- api_code / api_msg
- request_id / trace_id
- error_category
- outcome_verified
- created_at / updated_at

迁移必须在 MaintenanceService 中真正创建或升级表结构；不能只写入 migration 标记而把建表隐藏在服务构造函数中。迁移重复执行必须安全。

## 13. API 契约

建议拆分资源式端点，不继续扩大单个 action 路由：

- `GET /api/feishu/health`
- `POST /api/feishu/events`：仅 webhook 模式
- `GET /api/feishu/messages`
- `POST /api/feishu/summaries`
- `PATCH /api/feishu/summaries/{id}`
- `POST /api/feishu/approvals`
- `POST /api/feishu/approvals/{id}/sync`
- `POST /api/feishu/approvals/{id}/send`
- `GET /api/feishu/dispatches`

所有写操作使用严格 Pydantic 请求模型，不用宽松 `dict.get` 接收任意字段。

HTTP 状态：

- 400：格式或配置错误。
- 401/403：事件鉴权失败或访问无权。
- 404：资源不存在。
- 409：审批状态、哈希、目标或幂等冲突。
- 422：请求字段校验失败。
- 502：飞书确定性上游失败。
- 503：连接器未配置或不可用。
- 504：上游超时，同时本地记录 outcome_unknown。

API 响应不得包含 app_secret、token、验证密钥、完整审批表单原文或不必要的个人身份信息。

## 14. 控制台要求

飞书页只承担查看与人工触发，不承担安全决策：

- 健康状态字段必须与后端脱敏结构一致。
- 显示 event mode、live、鉴权、长连接、审批定义、白名单计数和最近错误类别。
- 消息列表默认截断正文并转义。
- 审批预览必须同时展示目标、正文、哈希、来源和过期时间。
- “创建审批”前显示确认对话，不自动填写 `confirmed=true` 代替真实用户确认。
- “发送”按钮只有后端返回 approved + verified approver + valid snapshot 时才可用。
- UI 禁用只改善体验；后端仍必须独立执行全部门禁。
- 回执明确写“飞书 API 已受理”，不写“对方已读”。
- 增加前端静态契约测试，覆盖导航、字段名、确认提示和无密钥输出。

## 15. 安全与隐私边界

### Always

- 对外部事件做来源校验。
- 对所有入站 JSON 做边界验证和大小限制。
- 使用参数化 SQL。
- 对控制台内容做 HTML 转义。
- 用最小权限申请飞书 scope。
- 真实写操作必须同时满足 live、白名单和有效原生审批。
- 日志、审计、测试报告和截图全部脱敏。
- 提交前扫描密钥、数据库、日志、缓存和生成证据。

### Ask first

- 安装或升级官方飞书 SDK。
- 修改数据库既有表结构或清理已有测试数据。
- 启动真实长连接。
- 创建真实审批实例。
- 向飞书群或用户实际发送消息。
- 推送 Git、创建 PR 或对外发布证据。

### Never

- 把密钥、token、Encrypt Key 或 Verification Token 写入仓库。
- 使用任意可配置 base_url 发送 app_secret。
- 信任客户端传入的 approver_id 作为实际审批证据。
- 向非白名单目标发送。
- 在 outcome_unknown 状态自动重发。
- 将 dry-run、fake 或 API 返回 0 直接表述为最终送达。
- 删除失败测试来让门禁通过。

## 16. 测试策略

### 16.1 单元测试

必须覆盖：

- 配置缺失、数值边界、列表解析和脱敏。
- 固定飞书 base_url。
- text 事件解析、未知类型拒绝、内容长度限制。
- 非白名单事件不保存正文和发送者。
- event_id/message_id 去重。
- token 缓存、过期刷新和单次 401 刷新。
- 审批创建必须包含 initiator open_id、正确 form control ID，且不传非法 title。
- 审批状态枚举：PENDING、APPROVED、REJECTED、CANCELED、DELETED、未知。
- 实际审批人允许、拒绝、缺失和多人审批。
- 目标 chat/open_id 白名单。
- 内容、目标、来源、过期时间变化全部阻断。
- API 失败分类和脱敏。
- outcome_unknown 不自动重发。

### 16.2 并发与恢复测试

- 两个线程/任务同时发送，只发生一次客户端调用。
- dispatch 唯一冲突返回同一记录。
- 进程重启后 sent 不重发。
- 进程重启后 sending/outcome_unknown 不重发。
- 发送成功后、写回执前模拟崩溃，恢复流程进入人工核验。
- 审批过期与发送 reserve 竞争时不发送。
- 审批撤回与发送 reserve 竞争时不发送。

### 16.3 API 集成测试

- HTTP challenge。
- 签名、token、解密成功与失败。
- 未认证伪造事件不能入库。
- 消息、纪要、审批、同步、发送和回执完整 fake 闭环。
- 未批准发送返回 409，客户端调用 0 次。
- 不在白名单目标返回 409，客户端调用 0 次。
- API 响应不含秘密和完整敏感载荷。
- 控制台健康字段与后端 schema 一致。

### 16.4 真实租户验收

只在所有自动化门禁通过并得到用户明确允许后执行：

1. 在专用测试群发送两条包含结论和行动项的消息。
2. 验证官方长连接接收，event_id/message_id 可追踪。
3. 生成纪要，逐条核对来源。
4. 创建审批，核对目标、正文、哈希、来源和过期时间均出现在审批中。
5. 第一次拒绝，确认机器人没有发送，数据库与审计记录 rejected。
6. 第二次由未授权测试人员批准，确认仍被本地门禁阻断。
7. 第三次由授权审批人批准，确认只发送一次。
8. 核对返回 message_id、群内实收和本地 dispatch。
9. 并发触发两次发送，确认群内仍只有一条。
10. 制造错误密钥、机器人移出群、权限不足和请求超时，核对失败分类。
11. 重启 ClawOS 后重放事件和发送请求，确认不重复。
12. 导出脱敏证据并由用户复核。

## 17. 验证命令

在仓库根目录执行：

```powershell
git status --short --branch
.\clawos\.venv\Scripts\python.exe -B -m unittest clawos.tests.test_feishu_connector
.\clawos\.venv\Scripts\python.exe -B -m unittest clawos.tests.test_feishu_api
.\clawos\.venv\Scripts\python.exe -B -m unittest clawos.tests.test_frontend_static
node --check clawos\static\assets\console.js
git diff --check
```

完成定向门禁后，再执行完整回归。完整测试可能修改 `clawos/skills/skill_registry.jsonl` 的使用次数；测试前记录该文件状态，测试后恢复纯副作用，不覆盖用户真实修改。

```powershell
.\clawos\.venv\Scripts\python.exe -B -m unittest discover -s clawos\tests
```

真实租户脚本必须显式要求 `--live`、白名单和人工确认；没有这些参数时只能运行 fake/dry-run。

## 18. WorkBuddy 任务清单

### Phase 0：保护现场与建立红灯测试

- [ ] 记录当前 `git status --short --branch` 和现有未提交文件。
  - Acceptance：没有覆盖或删除现有飞书草稿。
  - Verify：状态快照写入执行记录，不提交本地运行产物。
  - Files：无代码修改。
- [ ] 为 12 个已知阻断项先补失败测试。
  - Acceptance：测试能稳定暴露真实缺陷，而不是只检查 mock happy path。
  - Verify：新增测试在修复前失败、修复后通过。
  - Files：`test_feishu_connector.py`、`test_feishu_api.py`。

### Phase 1：配置与官方客户端

- [ ] 重构配置契约，固定飞书主机并补齐 initiator、表单控件、三类白名单和 event mode。
  - Acceptance：live 缺失任一必需配置时不可用；脱敏输出字段稳定。
  - Verify：配置边界测试通过。
  - Files：`config.py`、`.env.example`、相关测试。
- [ ] 用官方 SDK 替换手写长连接。
  - Acceptance：使用 APP_ID/APP_SECRET 建立连接；生命周期可启动/停止；无自定义 URL/token。
  - Verify：SDK 适配器测试及受控连接 smoke。
  - Files：`feishu_client.py`、依赖文件、相关测试。

### Phase 2：可信事件接收

- [ ] 实现官方长连接事件分发和应用生命周期接线。
  - Acceptance：真实事件进入服务；关闭服务不会遗留线程。
  - Verify：生命周期测试和 fake dispatcher 测试。
  - Files：`feishu_client.py`、`clawos_server.py`、相关测试。
- [ ] 加固 webhook 兼容入口。
  - Acceptance：challenge、签名/token、解密和重放保护完整；伪造事件不入库。
  - Verify：API 安全测试。
  - Files：`clawos_server.py`、`config.py`、`test_feishu_api.py`。
- [ ] 修复非白名单数据最小化。
  - Acceptance：拒绝事件数据库中无正文和发送者 ID。
  - Verify：隐私测试直接查询数据库。
  - Files：`connector_service.py`、测试。

### Phase 3：审批真实性

- [ ] 修复审批实例请求契约。
  - Acceptance：传 initiator open_id、真实控件 ID、完整表单；不传非法 title。
  - Verify：精确断言 fake 客户端收到的请求体。
  - Files：`feishu_client.py`、`connector_service.py`、`fake_client.py`、测试。
- [ ] 核验实际审批人。
  - Acceptance：只相信飞书实例 task/timeline；空值、未知或未授权审批人阻断。
  - Verify：单人、多人、缺失、冒充审批人测试。
  - Files：`connector_service.py`、`fake_client.py`、测试。
- [ ] 冻结并核验完整快照。
  - Acceptance：目标、正文、来源、审批配置任一变化均要求重新审批。
  - Verify：篡改矩阵测试。
  - Files：`connector_service.py`、测试。

### Phase 4：出站白名单与幂等

- [ ] 建立目标类型和目标白名单强校验。
  - Acceptance：只有允许 chat_id/open_id 可进入审批和发送。
  - Verify：创建审批与发送前各自的拒绝测试。
  - Files：`config.py`、`connector_service.py`、测试。
- [ ] 实现事务化 reserve/send 状态机。
  - Acceptance：真实并发只有一个调用者获得发送资格。
  - Verify：多线程并发测试，客户端调用次数严格为 1。
  - Files：`connector_service.py`、迁移、测试。
- [ ] 实现 outcome_unknown 恢复策略。
  - Acceptance：超时和崩溃后不自动重发，可人工核验。
  - Verify：超时、崩溃和重启测试。
  - Files：`connector_service.py`、`feishu_client.py`、测试。

### Phase 5：迁移、API 和控制台

- [ ] 把建表和升级移入真实迁移。
  - Acceptance：空库、旧库和重复迁移均通过；迁移记录与真实 schema 一致。
  - Verify：迁移测试。
  - Files：`maintenance_service.py`、迁移测试、服务初始化。
- [ ] 将飞书 API 改为严格请求模型和资源式端点。
  - Acceptance：边界校验、状态码和脱敏响应符合第 13 节。
  - Verify：API 集成测试。
  - Files：`clawos_server.py`、请求模型、`test_feishu_api.py`。
- [ ] 修复最小控制台。
  - Acceptance：健康字段一致；审批预览完整；无审批时发送按钮不可用。
  - Verify：前端静态测试、Node 语法、浏览器 smoke。
  - Files：`console.html`、`console.js`、`test_frontend_static.py`。

### Phase 6：回归、文档和真实租户

- [ ] 运行定向测试和完整回归。
  - Acceptance：无新增失败；skill registry 测试副作用不进入提交。
  - Verify：保存测试摘要。
  - Files：不修改产品文件。
- [ ] 更新运行文档和 PROJECT_CONTEXT。
  - Acceptance：配置、启动、关闭、失败恢复和真实证据状态准确。
  - Verify：文档链接和命令可执行。
  - Files：`PROJECT_CONTEXT.md`、相关 README。
- [ ] 经用户明确允许后运行真实租户验收。
  - Acceptance：第 16.4 节 12 项全部有脱敏证据。
  - Verify：用户复核群内实收、审批记录和本地审计。
  - Files：只生成被忽略的本地证据，不提交秘密。

## 19. 证据格式

真实验收证据保存到被忽略的本地输出目录，至少包括：

```json
{
  "schema": "clawos.feishu-live-acceptance.v1",
  "tenant_alias": "test-tenant",
  "app_id_suffix": "last4",
  "chat_id_hash": "sha256",
  "source_message_ids_hash": "sha256",
  "approval_instance_code_hash": "sha256",
  "actual_approver_verified": true,
  "approval_decision": "approved",
  "content_hash": "sha256",
  "dispatch_id": 1,
  "feishu_message_id_hash": "sha256",
  "api_accepted": true,
  "observed_in_test_chat": true,
  "duplicate_send_count": 0,
  "started_at": "ISO-8601",
  "completed_at": "ISO-8601",
  "checks": [],
  "failures": []
}
```

不得保存 app_secret、access token、Encrypt Key、Verification Token、完整成员 open_id、完整聊天内容或未脱敏截图。

## 20. 运行与故障处理

- 启动前：检查 live 开关、白名单、审批定义状态、机器人是否入群、scope 是否最小化。
- 运行中：监控连接状态、最近事件、审批查询错误、outcome_unknown 和限流。
- 停止时：先停止事件接收，再等待在途持久化完成，最后关闭 HTTP/SDK 客户端。
- 密钥疑似泄露：立即停用 live、轮换密钥、撤销 token、保留脱敏审计，不删除证据。
- 重复发送疑似发生：立即停用 live，冻结 dispatch，核对群消息和 uuid，不自动补发或删除记录。
- 审批身份异常：停用发送，核对审批定义流程和 task/timeline，重新申请审批。
- 事件伪造疑似发生：停用 webhook，轮换验证配置，检查时间戳和签名失败记录。

## 21. 完成定义

只有以下全部满足才算完成：

- [ ] 12 个当前阻断项全部修复并有回归测试。
- [ ] 官方 SDK 长连接真实接收测试群消息。
- [ ] webhook 若保留，安全校验完整；若不保留，则端点完全禁用。
- [ ] 审批实例请求符合官方契约。
- [ ] 实际审批人来自飞书返回并通过允许名单核验。
- [ ] 审批中可见发送目标、正文、哈希、来源和有效期。
- [ ] 目标类型和目标 ID 在出站白名单内。
- [ ] 并发、重放、超时和重启均没有重复发送。
- [ ] 拒绝、撤回、过期、篡改、未授权审批全部阻断。
- [ ] 定向测试、前端测试和完整回归通过。
- [ ] 真实租户拒绝一次、未授权批准一次、授权批准一次的证据完整。
- [ ] 群内实际收到且只有一条批准后的消息。
- [ ] 日志、数据库导出、API 响应和证据无秘密。
- [ ] `PROJECT_CONTEXT.md` 更新为真实状态。
- [ ] 用户完成最终复核。

在完成真实租户步骤前，交付状态只能写“自动化门禁通过，真实租户待验收”，不能写“飞书连接器完成”。

## 22. 用户需要准备

执行真实租户验收前，由用户或租户管理员提供：

- 专用测试租户。
- 已创建的自建应用。
- App ID 和 App Secret，通过本地 `.env` 配置。
- 已启用机器人能力。
- 已订阅 `im.message.receive_v1`。
- 最小必要消息和审批权限。
- 已发布的测试审批定义。
- 审批正文文本控件 ID。
- 审批发起人 open_id。
- 授权审批人 open_id 列表。
- 测试群 chat_id。
- 机器人已加入测试群并允许发言。
- 测试群成员对消息处理知情同意。
- 对启动真实长连接、创建审批和发送测试消息的逐项明确授权。

## 23. WorkBuddy 执行指令

将以下内容连同本文件交给 WorkBuddy：

> 先读取 `PROJECT_CONTEXT.md`、`README.md` 和本规格。保护当前未提交飞书实现，不覆盖其他协作者修改。按 Phase 0 到 Phase 6 顺序执行，测试先行；每完成一项立即运行对应验证。禁止设置 `FEISHU_LIVE=true`，禁止连接真实租户，直到所有自动化门禁通过且用户明确授权。遇到规格与飞书官方文档冲突时，以最新官方文档为准并先更新本规格。不要修改邮箱、钉钉、日历或无关模块。不要提交 `skill_registry.jsonl` 的测试使用次数副作用。最终报告必须区分 fake、自动化、官方 API smoke 和真实租户证据。

## 24. 官方文档

- 消息事件：https://open.feishu.cn/document/server-docs/im-v1/message/events/receive?lang=zh-CN
- Python SDK 事件处理：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/server-side-sdk/python--sdk/handle-events
- 回调接收与安全校验：https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks?lang=zh-CN
- 发送消息：https://open.feishu.cn/document/server-docs/im-v1/message/create?lang=zh-CN
- 审批概述：https://open.feishu.cn/document/server-docs/approval-v4/approval-overview?lang=zh-CN
- 原生审批实例概述：https://open.feishu.cn/document/server-docs/approval-v4/instance/overview-approval-instance?lang=zh-CN
- 创建审批实例：https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/approval-v4/instance/create
- 获取单个审批实例详情：https://open.feishu.cn/document/server-docs/approval-v4/instance/get?lang=zh-CN
