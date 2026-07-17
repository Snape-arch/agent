# Project Context

这是 ClawOS 当前状态的简洁交接入口。2026-07-14 以前的详细记录已归档到 `clawos/docs/PROJECT_HISTORY_2026-07-14.md`。

## 当前状态（2026-07-17）

- 当前分支：`codex/p0-demo-polish`。
- 当前提交：`4784d94`；与 `origin/codex/p0-demo-polish` 一致，相对 `origin/master` 超前 1 个文档提交。
- 本轮只有活跃工作文档更新；`.env`、`.workbuddy/`、`clawos/tmp/` 为本地忽略项，不得提交或擅自清理。
- 2026-07-17 沙箱外全量回归：**326 个通过、1 个跳过、0 失败**。沙箱内出现的 4 个失败均由既有输出/备份文件覆盖权限导致，4 项在沙箱外单独重跑通过；不是代码回归。
- 已验证的产品基线仍包括本地 Qwen、Chroma/Qwen3 向量能力、MTClaw 路由、办公工作流、Academy 页面和五条真实证据链。物理目标设备验收及企业连接器真实租户验收尚未完成。
- 2026-07-17 N1 本地启动基线完成：本地 Qwen、MTClaw 与 ClawOS 冷启动、停止、重启和健康检查通过；模型 routing/upstream 真实探针可达，MTClaw 本地热身成功并加载 30 个工具；`FEISHU_LIVE=false` 保持不变。下一步从 N2 六条核心功能闭环开始。
- 本轮只更新 `PROJECT_CONTEXT.md`、`WORK_STATUS.md` 和 `WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md`；未修改代码，未重跑全量单元测试。N1 运行日志位于 ignored 的 `tmp/n1*`，不得提交。
- 2026-07-17 N2 六条核心闭环已用安全测试资料完成：文档 `3/4`、报告任务 `21`、项目任务 `24`、引用/项目/检查点 run 均可重新查询，报告 Markdown/PDF 可重新读取。测试输入和报告位于 ignored 的 `tmp/n2/`。
- N2 修复了 MTClaw 成功路由不持久化 Task Steps 的缺陷：`clawos_server.py` 现在把 MTClaw trace 写为 tool step，`test_mtclaw_adapter.py` 增加回归断言；真实 task `24` 包含 succeeded `tools_list` step 及 step started/finished 事件。
- N2 相关回归共 48 项：沙箱内 46 通过、2 个既有权限/worker 假失败；2 项在沙箱外单独重跑均通过。下一步进入 N3 当前界面桌面/移动端验收。
- 2026-07-17 N3 当前界面审查已覆盖桌面工作台/知识库与 390 × 844 移动工作台/知识库/模型设置；无 P0。用户确认的 4 个 P1（移动知识页头部、分类标签换行、低对比文字、移动菜单名称）已修复并复测，Lighthouse 移动 accessibility 由 96 提升至 100、best practices 保持 100；2 个 P2 按约束未改。

## 飞书连接器 v2

- 状态（2026-07-16）：v2 整改已完成至 Phase 6（runbook + 文档）与 §13 重构、P1-2 控制台收口，12 个阻断缺陷全部关闭；36/36 飞书测试全绿（test_feishu_api 13 + test_feishu_connector 23 + test_feishu_migration 4）。
- 架构性重构（§13）已完成：废弃单一 action 路由 `POST /api/feishu`，改为资源式端点（`GET /api/feishu/health|messages|summaries|approvals|dispatches`、`POST /api/feishu/events|summaries|approvals`、`PATCH /api/feishu/summaries/{id}`、`POST /api/feishu/approvals/{id}/sync|send`）；写操作强制严格 Pydantic 请求模型；HTTP 状态按 §13 映射（400/401/403/404/409/422/502/503/504）。
- 建表/升级已移入真实迁移：`MaintenanceService.apply_migrations()` 通过 `2026_07_feishu_connector` 迁移调用共享 `services/feishu/schema.py`，幂等、可重跑；不再藏在服务构造函数里。
- Phase 6 已完成：新增 `docs/feishu-runbook.md`；本文件同步更新。P1-2 控制台收口已完成：创建审批/发送改为显式二次确认（不再静默提交 `confirmed:true`）、移除手填审批人、未配置时禁用写按钮、空状态行。
- 真实租户只读入站已于 2026-07-16 通过：token 鉴权成功、官方 SDK WebSocket 真握手成功，并实时收到 3 条 `im.message.receive_v1`；关键事件标识均非空。全程 `FEISHU_LIVE=false`，未创建审批、未发送消息。
- 真实预检发现的 token `code:0` 误判已有专门回归测试；正式长连接已区分 `running`（线程存活）与 `connected`（真实 WS 握手）。
- 2026-07-16 用户决定暂停飞书审批与外发验收。WorkBuddy 生成的控制台直发、`POST /api/feishu/send` 和数据库重建改动已全部撤销，未进入提交。必须保持 `FEISHU_LIVE=false`；不得把只读入站称为真实飞书闭环。
- 审查时本地 ClawOS 服务健康、飞书 live mode 关闭；MTClaw 不可达是系统告警，不是飞书连接器阻断项。

## 仓库卫生

- `clawos/skills/skill_registry.jsonl` 会被全量测试修改使用计数；恢复该副作用后再审查 staged 文件，不能提交它。
- `.playwright-cli/` 是本地界面审查产物，不提交；未经用户许可不得删除。
- 永远不要提交 `.env`、凭据、数据库、日志、缓存、上传、模型、生成报告和浏览器证据。
- 本地损坏引用 `refs/heads/codex/backup-master-c663560` 会让部分 `git --all` 命令报 `bad object`；未获用户授权前不要删除或改写。
- 2026-07-14 已完成：清理历史生成物和输入法缓存路径的版本控制、整合忽略规则、归档过长交接记录、审计并回收历史 1.32 GiB Git 模型 blob；本地模型资产保留供复现。

## 交接顺序

1. 先读 `WORK_STATUS.md`、本文件、`README.md`、`PROJECT_ROADMAP.md` 和 `WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md`。
2. 飞书阶段冻结；不继续审批、外发或连接器功能扩展。
3. N0 与 N1 已完成；按接手单继续 N2 六条核心功能闭环、N3 桌面/移动端界面验收、N4 备份恢复和仓库卫生。
4. 先审查后修改；只修阻断闭环的问题，不新增顶层模块或大规模视觉重构。
5. 任何外部发送、真实 API、模型下载、Git push、PR 或共享状态变更均需用户明确授权。

## 常用验证

```powershell
git status --short --branch
.\clawos\.venv\Scripts\python.exe -B -m unittest discover -s clawos\tests
git diff --check
```

## 论文阅读器交互闭环（2026-07-16）

- 已修复 PDF 空态与研究运行面板的 `hidden` 层级问题，阅读器打开原文后不再被品牌图或透明面板遮挡。
- 缩放改为不重载 PDF 的真实视觉变换；补齐适合宽度、全屏、目录折叠/跳页、笔记草稿/保存/删除和批注本地保存反馈。
- 关键阅读器控件改为独立事件绑定，避免黑色工具栏只显示样式但点击无效。
- 变更文件：`clawos/static/academy-paper.html`、`clawos/static/assets/academy.js`、`clawos/static/assets/site.css`、`clawos/tests/test_frontend_static.py`。
- 验证：Node JavaScript 语法检查通过；`python -m unittest tests.test_frontend_static` 为 42/42 通过；内置浏览器已验证遮挡、缩放、笔记保存/删除、画笔与目录折叠。
- 非阻断项：本地历史论文源接口在当前输出目录策略下返回 403，未修改该安全边界；上传任意本地 PDF 仍可在阅读器直接预览。
