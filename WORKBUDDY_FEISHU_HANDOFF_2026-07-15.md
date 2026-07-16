# WorkBuddy 飞书连接器接手单（更新于 2026-07-16）

## 一眼结论

飞书连接器 v2 的自动化门禁、资源式 API、控制台收口和真实租户只读入站已经完成。官方 SDK 长连接已真实握手，并实时收到测试群的 `im.message.receive_v1` 事件。尚未完成的是飞书原生审批配置、审批身份验证和经用户批准后的单次外发闭环。

当前必须保持 `FEISHU_LIVE=false`。未经用户对每个真实写阶段单独授权，不得创建审批、改变飞书共享状态或发送消息。

完整设计见 `WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md`，运维与故障处理见 `docs/feishu-runbook.md`。本文件是 WorkBuddy 的当前执行入口。

## 当前现场

- 仓库：`D:\Projects\clawos`；分支：`codex/p0-demo-polish`。
- 当前提交：`2a660f4`（`Handle missing Feishu token response code`）；本地分支与跟踪远端一致。
- tracked 工作区干净；`.env`、`.workbuddy/`、`clawos/tmp/` 均被忽略，不得提交或清理。
- `FEISHU_EVENT_MODE=long_connection`，`FEISHU_LIVE=false`。
- App ID、App Secret 已通过只读 token 请求验证；Secret 不得输出、记录或提交。
- `.env` 已配置真实 `tenant_key`、测试群 `chat_id` 和当前测试用户 `open_id`。文档中不得记录这些标识真值。
- 当前测试群被飞书标记为外部群。正式外发验收前优先改用内部专用测试群；若继续使用外部群，必须由用户明确确认范围和风险。

## 已完成并有真实证据

### 自动化与代码基线

- 飞书连接器 v2 的 12 个 P0 阻断项已关闭。
- 资源式 API、严格请求模型、真实迁移、审批快照、白名单、实际审批人校验、并发幂等和 `outcome_unknown` 保护已落地。
- 已有基线：36 个飞书测试通过；此前全量回归为 320 个通过、1 个跳过、0 失败。

### 真实租户只读入站

- 自建应用和机器人已发布并安装，机器人已加入测试群。
- `tenant_access_token` 只读鉴权成功，`auth_ok=true`。
- 官方 SDK 已完成到飞书消息服务的真实 WebSocket 握手。
- 实时捕获 3 条 `im.message.receive_v1`，`tenant_key`、`chat_id`、`sender.open_id`、`message_id` 均非空；同一租户标识一致。
- 全程未输出 Secret、未保存消息正文到预检输出、未发送消息、未创建审批。
- 监听任务已停止。

### 本轮发现的缺陷

`FeishuClient._ensure_token()` 原先使用 `int(data.get("code", -1) or -1)`，会把飞书成功响应的 `code: 0` 误判为失败。提交 `2a660f4` 已改为显式区分缺失 code 与 `code == 0`。

该修复目前缺少针对 token 成功响应的专门回归测试，是 WorkBuddy 的第一个任务。

## WorkBuddy 接下来按顺序执行

### W1：补齐鉴权修复的回归测试

只改测试，除非测试揭示修复仍不完整。

至少覆盖：

1. HTTP 200、`code: 0`、存在 token：`health_check().auth_ok == true`。
2. 响应缺少 `code`：fail closed，分类为鉴权或终止错误，不缓存 token。
3. 非零鉴权错误码：保持 `AUTH` 分类。
4. 测试和日志均不得出现真实 App ID、Secret、token、chat_id 或 open_id。

验收：飞书定向测试全绿，`git diff --check` 通过。

### W2：复核并固化真实入站预检

审查 `clawos/tmp/feishu_lc_receive_preflight.py`，但不要提交临时脚本。把可复用的“真实握手状态”能力落到正式 `long_connect.py` 或正式测试中时，必须先用失败测试证明需求；不要依赖 `manager.running` 判断连接成功。

验收条件：

- 只有 token 鉴权成功且 SDK `on_reconnected`/等价真实握手信号发生后，健康状态才显示 connected。
- 握手失败或 SDK 无限重连时不能显示成功。
- `FEISHU_LIVE=false` 仍允许只读入站，但所有外部写操作继续 fail closed。

如果现有正式实现已经满足，不做代码改动，只报告证据。

### W3：清点审批前置配置，不做真实写操作

只读检查 `.env` 的“是否填写”，不得输出真值。列出仍缺失或仍为占位符的：

- `FEISHU_APPROVAL_CODE`
- `FEISHU_APPROVAL_FORM_CONTROL_ID`
- `FEISHU_APPROVER_OPEN_IDS`

规则：

- 审批定义必须由用户/租户管理员在飞书审批后台创建并发布，WorkBuddy 不得猜 code 或控件 ID。
- 正文使用单个多行文本控件，表单需展示目标、正文、快照 hash、来源消息和过期时间。
- 审批人应与发起人不同；不要把当前测试用户同时当作发起人和唯一审批人。
- 取得另一位测试审批人的 `open_id` 时，优先通过同一只读事件链捕获，不读取无关通讯录。

验收：输出缺失项清单和用户需要在飞书完成的最小操作，不改 `FEISHU_LIVE`。

### W4：自动化回归与仓库卫生

依次运行：

```powershell
git status --short --branch
.\clawos\.venv\Scripts\python.exe -B -m unittest clawos.tests.test_feishu_connector clawos.tests.test_feishu_api clawos.tests.test_feishu_migration
node --check clawos\static\assets\console.js
.\clawos\.venv\Scripts\python.exe -B -m unittest discover -s clawos\tests
git diff --check
git status --short
```

全量测试若修改 `clawos/skills/skill_registry.jsonl`，只恢复该测试计数副作用，不覆盖其他改动。不得提交 `.env`、临时预检脚本、日志、数据库、缓存或浏览器产物。

### W5：停在真实写操作授权门前

完成 W1-W4 后停止，并向用户报告。不得自行设置 `FEISHU_LIVE=true`。

用户后续授权必须分阶段：

1. 授权创建一个测试审批实例，但不发送消息。
2. 用户在飞书中完成拒绝/越权/授权审批测试，WorkBuddy 只同步并验证状态。
3. 用户再次明确授权后，才向白名单测试目标发送一次。
4. 最后验证事件重放、并发和重启恢复均不会重复发送。

每一阶段都要给出即将影响的飞书对象、预期副作用和停止条件，获得明确授权后再执行。

## 剩余完成定义

- [ ] token `code: 0` 回归测试已补齐。
- [ ] 正式健康状态能区分线程存活与真实 WS 握手成功。
- [ ] 审批定义已发布，approval code 和正文控件 ID 已配置。
- [ ] 独立授权审批人的 open_id 已配置。
- [ ] 创建审批前的自动化与配置门禁全绿。
- [ ] 用户授权后完成拒绝路径与越权审批阻断。
- [ ] 用户授权后完成授权审批和单次白名单发送。
- [ ] 重放、并发、超时和重启均无重复发送。
- [ ] 真实租户证据脱敏，最终由用户复核。

在以上全部完成前，项目状态只能写“真实只读入站已通过，审批与外发待验收”，不能写“真实飞书闭环完成”。

## 禁止事项

- 不得输出或提交 App Secret、token、真实 `.env` 或完整敏感标识。
- 不得默认设置 `FEISHU_LIVE=true`。
- 不得创建审批、发送消息、修改飞书权限、提交代码或推送远端，除非用户明确授权相应动作。
- 不得用 `manager.running` 作为 WS 已连接的唯一证据。
- 不得把 mock、token 成功或只读入站称为审批外发闭环完成。
- 不得 reset、覆盖、批量暂存或擅自删除被忽略的本地产物。

## 每轮交付格式

1. 已完成：任务编号和改动文件。
2. 验证：精确命令及通过/跳过/失败数。
3. 当前状态：分支、提交、tracked/untracked/ignored 状态。
4. 真实飞书动作：明确列出是否连接、创建审批、发送消息。
5. 剩余风险：尚未关闭的完成定义。
6. 下一步：一个最小任务；触及真实写操作时停下请求授权。

## 可直接发给 WorkBuddy 的指令

> 先完整阅读 `PROJECT_CONTEXT.md`、`WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md`、`WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md` 和 `docs/feishu-runbook.md`。当前真实只读入站已经通过，但审批和外发尚未验收。严格按接手单 W1→W5 执行：先补 token `code:0` 回归测试，再核对正式长连接握手状态、只读清点审批配置、跑定向和全量回归并检查仓库卫生。保持 `FEISHU_LIVE=false`；不得输出凭证、创建审批、发送消息、提交或推送。完成 W1-W4 后停在真实写授权门前，按规定格式汇报。
