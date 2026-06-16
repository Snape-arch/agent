# 高级场景工作流实现说明

日期：2026-06-16

## 本地文件和项目创建能力确认

当前 ClawOS 已支持在安全白名单根目录内进行本地文件操作：

- TXT/Markdown：读取、写入、搜索、统计。
- PDF：通过 `pdftotext` 做文本抽取、页码分块和引用检索。
- 项目创建：`project_init` 和模板中心可创建 Python、科研项目等目录骨架。
- 写操作：由 `ToolSecurityPolicy` 限制路径，部分高风险工具需要确认。

当前边界：

- PDF OCR 目前是“检测并标记 OCR required”，真实图片 OCR 需要接入本地 OCR 引擎。
- 音频会议支持音频登记和 sidecar 文本转写导入；如本机存在 `whisper` 命令，可在能力页显示可用，但当前不会假装完成自动转写。
- 说话人分离为标签式解析，例如 `Alice: ...`、`[00:01] Bob: ...`。

## 会议

新增：

- 本地音频文件登记。
- sidecar transcript 导入。
- 说话人标签解析。
- 会议纪要、决策、风险、行动项继续沿用原会议闭环。
- 日历 `.ics` 和邮件 `.eml` 草稿生成，不自动外发。

API：

- `POST /api/workspace/meetings/audio`
- `POST /api/workspace/meetings/{meeting_id}/connector-drafts`

Agent 工具：

- `meeting_workflow` 新增 `audio_import`、`connector_draft`。

## 科研

新增：

- PDF 低文本页 OCR 需求标记。
- 引用校验：检查 `file#page=N` 是否已导入且页码有效。
- 对比矩阵：按论文和术语统计覆盖。
- 可复现实验工作流：生成 README、`experiment_plan.json` 和 notebooks 目录。

API：

- `POST /api/workspace/research/citations/validate`
- `POST /api/workspace/research/compare-matrix`
- `POST /api/workspace/research/repro-workflows`

Agent 工具：

- `research_pdf` 新增 `validate_citations`、`compare_matrix`、`repro_workflow`。

## 学习

新增：

- 学习依赖图。
- 错题证据记录。
- 长期掌握度评估：结合 mastery、证据数量、错题数量和复习到期状态。

API：

- `POST /api/workspace/learning/goals/{goal_id}/dependencies`
- `POST /api/workspace/learning/items/{item_id}/mistakes`
- `GET /api/workspace/learning/goals/{goal_id}/graph`
- `GET /api/workspace/learning/goals/{goal_id}/assessment`

Agent 工具：

- `learning_workspace` 新增 `dependency`、`mistake`、`graph`、`assessment`。

## Git

新增：

- 写操作审批请求。
- 补丁预览和 checkpoint HEAD。
- 审批后执行 `git add` + `git commit`。
- 回滚使用 `git revert --no-edit`，不使用破坏性 reset。

API：

- `POST /api/workspace/git/change-requests`
- `POST /api/workspace/git/change-requests/{request_id}/approve`
- `POST /api/workspace/git/change-requests/{request_id}/rollback`

Agent 工具：

- `git_workspace` 新增 `request_commit`、`approve`、`rollback`。

## Skill 治理

新增：

- 依赖清单。
- HMAC-SHA256 签名记录。
- fresh-agent audit，包含 silent bypass 检测。
- canary 元数据。canary 不直接修改生产路由，正式发布仍需 promote。

API：

- `GET /api/skills/evolution/versions/{version_id}/manifest`
- `POST /api/skills/evolution/versions/{version_id}/sign`
- `POST /api/skills/evolution/versions/{version_id}/fresh-audit`
- `POST /api/skills/evolution/versions/{version_id}/canary`

Agent 工具：

- `skill_governance`

## 前端

控制台新增“场景工作流”页：

- 本地文件/项目创建能力。
- TXT/PDF/音频能力边界。
- Git 审批写操作。
- Skill 治理能力。

能力体检 API：

- `GET /api/workspace/capabilities`

## 验证

```powershell
python -m unittest discover -s clawos\tests
python -m py_compile clawos\workspace_services.py clawos\scripts\tool_runner.py clawos\skills\skill_evolution.py clawos\clawos_server.py clawos\security\policy.py
git diff --check
```

结果：`82 tests OK`。仅有既有 MTClaw FastAPI `on_event` deprecation warning。
