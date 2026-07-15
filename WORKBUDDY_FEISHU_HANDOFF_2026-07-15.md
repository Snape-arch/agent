# WorkBuddy 飞书连接器接手单（2026-07-15）

## 一眼结论

当前代码已有飞书连接器 v2 的主要骨架和模拟闭环，但尚未达到真实租户可启用标准。WorkBuddy 下一步先关闭 P0 安全与一致性阻断，再完成 API 和控制台收口，最后跑完整回归。未经用户明确授权，保持 `FEISHU_LIVE=false`，不得连接真实租户、创建真实审批或发送真实消息。

完整设计见 `WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md`；本文件只定义执行顺序、验收和交付格式。

## 当前现场

- 仓库：`D:\Projects\clawos`；分支：`codex/p0-demo-polish`；提交：`add8084`，超前远端分支 4 个提交。
- 工作区已有 WorkBuddy 未提交改动。不得 reset、覆盖或整批暂存。
- `clawos/skills/skill_registry.jsonl` 是测试的计数副作用，不提交。
- `.playwright-cli/` 是本地界面审查产物，不提交，也不要擅自删除。
- 审查时本地服务可用，`FEISHU_LIVE=false`，没有完整真实飞书租户配置。
- MTClaw 不可达是现有系统告警，不是飞书闭环阻断项。

## 已完成

- 官方 `lark-oapi` SDK、长连接生命周期骨架、扩展配置、迁移和 API/控制台雏形。
- 目标白名单、真实审批人提取、超时结果未知和禁止自动重发的初步保护。
- 独立聚焦验证：82 个测试通过；`node --check`、`git diff --check` 通过。
- WorkBuddy 曾记录全量回归 316 个通过、1 个跳过；当前现场未独立复跑。

## P0：必须按顺序完成

### P0-1 可信事件接收

HTTP 回调只处理 challenge 和 Verification Token，未完整实现 Encrypt Key 验签/解密。v1 优先只允许官方长连接；若保留 webhook，必须补齐官方验签、解密、重放保护及失败测试。

验收：错误 token、签名、密文和重复事件全部被拒绝或幂等处理；只有完整配置的事件模式显示 ready。

### P0-2 所有真实写操作 fail closed

在服务构造、创建审批、同步审批和发送消息四层统一检查 `live_readiness()`；缺任意配置时不得创建真实客户端或发起外部请求。

验收：缺配置的每个入口均返回明确缺失项，fake client 外部调用数为 0。

### P0-3 冻结完整审批快照并绑定远端实例

对规范化快照计算 hash，至少包含 tenant、target type/id、消息类型、正文、来源 ID、审批定义/控件 ID 和过期时间。同步审批时校验 approval code、uuid、表单、状态和真实审批人。

验收：审批后改正文、目标、来源、消息类型、配置或过期时间均拒绝发送；错绑审批实例不能放行。

### P0-4 审批表单配置化

删除未配置的硬编码控件 ID。优先把完整预览和快照 hash 放入一个可配置 textarea；若多控件，所有 ID 均显式配置并在启动时校验。

验收：表单序列化有测试覆盖，不存在隐式控件 ID。

### P0-5 数据库级并发幂等

以事务原子预占 dispatch；冲突调用读取并返回既有 dispatch。超时记 `outcome_unknown`，禁止自动重试。

验收：两个并发调用都成功返回同一 dispatch ID，外部发送严格一次；重启和重放后不重复发送。

### P0-6 审批人和目标只由服务端决定

删除/忽略前端手填 `approver_id`；审批人仅取飞书任务/时间线。目标仅接受配置白名单中的 `chat_id` 或 `open_id`。

验收：客户端伪造审批人、目标类型或目标 ID 均不能绕过门禁。

## P1：P0 完成后收口

1. 用严格请求/响应模型和统一错误结构收紧 API；兼容入口不得绕过服务层。
2. 控制台未配置时禁用创建审批/发送，不自动提交 `confirmed:true`；统一 `chat_id/open_id`，移除手填审批人，补空状态并修移动端表格。
3. 修复当前 `/api/skills`、`/api/tools`、reflection cards 的 404；若与飞书无关，拆为独立提交。
4. 跑聚焦、全量、语法和 diff 检查；全量测试后恢复 `skill_registry.jsonl` 的计数副作用。
5. 更新 `.env.example`、`PROJECT_CONTEXT.md` 和完整规格中的完成状态。

## 验证命令

```powershell
git status --short --branch
.\clawos\.venv\Scripts\python.exe -B -m unittest clawos.tests.test_feishu_connector clawos.tests.test_feishu_api clawos.tests.test_feishu_migration clawos.tests.test_frontend_static
node --check clawos\static\assets\console.js
.\clawos\.venv\Scripts\python.exe -B -m unittest discover -s clawos\tests
git diff --check
git status --short
```

若项目要求在 `clawos` 目录运行，则使用 `tests.*` 模块名；不要为了测试改导入结构。

## 真实租户验收：仅用户授权后

用户需提供或确认测试租户中的 App ID/Secret、tenant、审批定义 code、发起人和授权审批人的 open_id、表单控件 ID、允许的 chat_id/open_id，并明确允许创建审批和发送测试消息。

验收顺序：拒绝一次、未授权审批一次、授权审批一次、只发送一次、事件重放一次、服务重启后重试一次。证据不得包含 Secret、token 或原始敏感消息。

## 禁止事项

- 不得设置 `FEISHU_LIVE=true`，不得真实发消息、创建审批、提交、推送或创建 PR，除非用户明确分别授权。
- 不得用 `git reset --hard`、`git checkout --` 或覆盖方式清理现场。
- 不得提交 `.env`、凭据、数据库、日志、浏览器产物或 `skill_registry.jsonl` 计数变化。
- 不得把 mock 结果说成真实飞书闭环完成。

## 每轮交付格式

1. 已完成：任务编号和改动文件。
2. 验证：精确命令、通过/跳过/失败数。
3. 当前状态：`git status --short --branch`，区分原有与本轮改动。
4. 剩余风险：未关闭的 P0/P1。
5. 下一步：一个最小可执行任务；涉及真实租户或外部发送时停下请求授权。

## 可直接发给 WorkBuddy 的指令

> 先完整阅读 `PROJECT_CONTEXT.md`、`WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md` 和 `WORKBUDDY_REAL_FEISHU_CONNECTOR_PLAN.md`。保护当前未提交现场，保持 `FEISHU_LIVE=false`。按 P0-1 到 P0-6 以失败测试驱动修复，再完成 P1、跑聚焦和全量回归，并恢复技能注册表测试副作用。不要连接真实租户、发送消息、提交或推送，直到我明确授权。最终按“已完成、验证、当前状态、剩余风险、下一步”汇报。
