# ClawOS 当前工作状态（2026-07-17）

这是当前开发与 WorkBuddy 接手的第一入口。详细路线见 `PROJECT_ROADMAP.md`，关键事实与护栏见 `PROJECT_CONTEXT.md`。

## 当前结论

ClawOS 已形成 Windows 本地个人 Agent OS 的 MVP+ 基线，核心能力广度足够，当前重点不是继续增加顶层功能，而是把现有能力验证成稳定、清晰、可恢复的日常工作台。

当前优先顺序：

1. 六条核心功能闭环验收。
2. 桌面端与移动端界面验收。
3. 备份、恢复和数据完整性。
4. 性能基准与长期稳定性。

飞书阶段冻结在“真实只读入站已通过”。审批、外发和任何控制台直发方案均不是当前任务。

## Git 与验证基线

- 当前分支：`codex/p0-demo-polish`。
- 当前提交：`4784d94`，与 `origin/codex/p0-demo-polish` 一致，相对 `origin/master` 超前 1 个文档提交。
- 2026-07-17 沙箱外全量回归：326 个通过、1 个跳过、0 失败。
- 同一套测试在 Codex 沙箱内出现 3 个文件权限错误和 1 个 worker 断言失败；4 个失败测试在沙箱外单独重跑全部通过。根因是沙箱无法覆盖既有 `output/` 与 `clawos/backups/` 产物，不是代码回归。
- 非阻断警告：FastAPI `on_event` 弃用、asyncio event loop 资源警告。

## 功能全景

| 领域 | 已有能力 | 当前状态 | 下一验收 |
| --- | --- | --- | --- |
| 模型 | API、local Qwen、mock/offline 模式 | 2026-07-17 本地 Qwen 冷启动、停止、重启和真实探针通过 | 界面确认三种模式的可见状态 |
| MTClaw | Function Router、工具桥、Trace、严格/降级模式 | 当前机器本地热身成功，加载 30 个工具，ClawOS 可达 | N2 真实任务闭环；MTT AIBOOK 仍缺 |
| 任务 | Task/Step/Event、队列、取消、重试、恢复 | N2 task `24` 已验证 MTClaw 工具步骤和事件持久化 | 继续长期恢复与队列压力验收 |
| 知识 | 上传、解析、分块、检索、引用问答、图谱 | N2 文档 `3/4` 已完成上传、检索、引用、报告和重新打开 | N3 界面验收 |
| 论文/研究 | 阅读器、精读、引用、比较、笔记与批注 | N2 研究闭环通过；N3 审查和 4 个 P1 修复复测完成 | 保留 2 个可选 P2，不在当前范围内 |
| 办公/产物 | 会议、报告、文档、表格/幻灯片结构 | 能力入口存在 | 产物生成、保存、重新打开 |
| 项目/代码 | 仓库分析、任务拆分、工具与审计 | 基线存在 | 一个可恢复的真实项目任务 |
| Memory/Reflection/Skills | 记忆、Review、反思、候选 Skill、回滚 | 自动化基线存在 | 长期数据与人工审核体验 |
| 权限/运维 | 确认、审计、迁移、备份恢复入口 | 机制存在 | 安全测试数据恢复演练 |
| 飞书 | 官方 SDK 长连接、消息接收、审批门禁代码 | 只读入站真实通过，阶段冻结 | 当前不继续 |

## 当前风险

### P0

- N3 未发现 P0；用户确认的 4 个 P1 已修复并有移动端复测证据，Lighthouse accessibility 100、best practices 100。`design-qa.md` 保留 2 个未改 P2。

### P1

- 备份恢复测试会写 `clawos/backups/`；Obsidian 导出和搜索验收会覆盖 `output/`。在 Codex 沙箱内可能假失败，应使用隔离临时目录，或在明确授权下于正常本地环境运行。
- 当前存在一个损坏的本地 Git 引用 `refs/heads/codex/backup-master-c663560`，会导致部分 `git log --all` / `git show-ref` 命令报 `bad object`。未获授权前不要删除该引用。
- 本地 `master` 分支指针很旧，但当前工作分支已经快进到最新 `origin/master`；不要用 reset 修正。
- `start_clawos.bat --local` 的端口冲突路径会进入交互式 `pause`，自动化调用不友好；受限沙箱还可能误判宿主 Qwen 不健康。正常本机运行应以启动前端口检查和三个 `/health` 结果为准。
- 直接资源 API（上传、分块）返回 document/knowledge/chunk ID，不创建 runtime task ID；N2 已记录资源 ID 与持久化路径，但严格统一的任务证据模型仍可后续收口。

### P2

- MTT AIBOOK 上的本地 Qwen/vLLM-MUSA 实机数据仍缺失。
- warm P50/P95、备份恢复、数据完整性和多日 burn-in 尚未形成当前证据。

## WorkBuddy 当前任务

严格按 `WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md` 继续执行 N2→N4；N1 已于 2026-07-17 完成：

1. N2 六条核心功能闭环。
2. N3 功能与界面验收。
3. N4 备份、恢复和仓库卫生。

每个阶段先审查、后修改。只修阻断闭环的问题，不新增顶层模块，不做大规模视觉重构。

## 红线

- `FEISHU_LIVE=false`，不继续审批或外发。
- 不输出、提交或复制 `.env`、Secret、token、数据库、日志、个人资料和运行产物。
- 不调用收费 API、不下载模型、不访问外部网络，除非用户明确授权。
- 不提交、不推送、不创建 PR，除非用户明确授权。
- 不用 mock、历史报告或沙箱权限失败冒充当前真实验收结果。

## 可直接发给 WorkBuddy

> 先读取 `WORK_STATUS.md`、`PROJECT_CONTEXT.md`、`README.md`、`PROJECT_ROADMAP.md` 和 `WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md`。N0 全局盘点和 N1 本地启动基线已于 2026-07-17 完成，当前提交为 `4784d94`，沙箱外全量回归 326 通过、1 跳过。当前本地 Qwen、MTClaw、ClawOS 均健康，飞书阶段冻结并保持 `FEISHU_LIVE=false`。从 N2 六条核心闭环开始，随后执行 N3 桌面/移动端界面验收、N4 备份恢复。先审查后修改；不得调用收费 API、下载模型、发送外部消息、提交或推送。每轮报告已完成、验证、当前状态、风险、外部副作用和下一步。
