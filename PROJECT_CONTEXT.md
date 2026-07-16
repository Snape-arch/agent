# Project Context

这是 ClawOS 当前状态的简洁交接入口。2026-07-14 以前的详细记录已归档到 `clawos/docs/PROJECT_HISTORY_2026-07-14.md`。

## 当前状态（2026-07-16）

- 当前分支：`codex/p0-demo-polish`。
- 当前提交：`add8084`；相对 `origin/codex/p0-demo-polish` 超前 4 个提交。
- 工作区有 WorkBuddy 未提交的飞书连接器 v2 改动，必须保护现场，禁止 reset、覆盖或批量暂存。
- 独立聚焦验证：82 个测试通过（test_frontend_static + 40 飞书定向）；前端 JavaScript 语法检查和 `git diff --check` 通过。全量回归已于 2026-07-16 当前现场复跑：**320 个通过、1 个跳过、0 失败**。
- 已验证的产品基线仍包括本地 Qwen、Chroma/Qwen3 向量能力、MTClaw 路由、办公工作流、Academy 页面和五条真实证据链。物理目标设备验收及企业连接器真实租户验收尚未完成。

## 飞书连接器 v2

- 状态（2026-07-16）：v2 整改已完成至 Phase 6（runbook + 文档）与 §13 重构、P1-2 控制台收口，12 个阻断缺陷全部关闭；36/36 飞书测试全绿（test_feishu_api 13 + test_feishu_connector 23 + test_feishu_migration 4）。
- 架构性重构（§13）已完成：废弃单一 action 路由 `POST /api/feishu`，改为资源式端点（`GET /api/feishu/health|messages|summaries|approvals|dispatches`、`POST /api/feishu/events|summaries|approvals`、`PATCH /api/feishu/summaries/{id}`、`POST /api/feishu/approvals/{id}/sync|send`）；写操作强制严格 Pydantic 请求模型；HTTP 状态按 §13 映射（400/401/403/404/409/422/502/503/504）。
- 建表/升级已移入真实迁移：`MaintenanceService.apply_migrations()` 通过 `2026_07_feishu_connector` 迁移调用共享 `services/feishu/schema.py`，幂等、可重跑；不再藏在服务构造函数里。
- Phase 6 已完成：新增 `docs/feishu-runbook.md`；本文件同步更新。P1-2 控制台收口已完成：创建审批/发送改为显式二次确认（不再静默提交 `confirmed:true`）、移除手填审批人、未配置时禁用写按钮、空状态行。
- 必须保持 `FEISHU_LIVE=false`，直到自动门禁（全量回归）通过且用户明确授权测试租户操作。不得把 mock 结果称为真实飞书闭环。
- 审查时本地 ClawOS 服务健康、飞书 live mode 关闭；MTClaw 不可达是系统告警，不是飞书连接器阻断项。

## 仓库卫生

- `clawos/skills/skill_registry.jsonl` 会被全量测试修改使用计数；恢复该副作用后再审查 staged 文件，不能提交它。
- `.playwright-cli/` 是本地界面审查产物，不提交；未经用户许可不得删除。
- 永远不要提交 `.env`、凭据、数据库、日志、缓存、上传、模型、生成报告和浏览器证据。
- 2026-07-14 已完成：清理历史生成物和输入法缓存路径的版本控制、整合忽略规则、归档过长交接记录、审计并回收历史 1.32 GiB Git 模型 blob；本地模型资产保留供复现。

## 交接顺序

1. 先读本文件、`README.md`、`WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md` 和完整飞书规格。
2. 保护未提交改动；以失败测试驱动关闭接手单 P0-1 到 P0-6。
3. 完成 API 和控制台 P1，运行聚焦与全量回归，恢复技能注册表副作用，审查 diff。
4. 用户明确授权后，才在独立飞书测试租户执行：拒绝、越权审批、授权审批、单次发送、事件重放和重启恢复验收。
5. 任何外部发送、日历发布、Git push、PR 或共享状态变更均需用户明确授权。

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
