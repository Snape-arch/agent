# Project Context

这个文件用于让下一次协作快速了解当前项目情况。每次完成一个有意义的修改后，都应该更新本文件。

## 维护规则

- 新增功能、修复 bug、同步远程、调整架构后，都在“变更记录”追加一条。
- 如果项目状态、下一步计划、风险点发生变化，直接修改对应章节。
- 不记录 API Key、token、密码、私有密钥。
- 下次 Codex 接手时，优先读本文件，再按需读具体代码。

## 项目定位

ClawOS 是一个 Windows 本地运行的个人 Agent 工作台，当前使用 DeepSeek / OpenAI-compatible provider 调模型，并通过 MTClaw adapter 接入 Function Router 风格工具路由。

目标不是单纯聊天，而是形成：

```text
User Request
  -> Router / MTClaw
  -> Tool Execution
  -> Task / Step / Event Trace
  -> LLM Summary
  -> MemoryOS
  -> Reflection
  -> Future Reuse
```

## 当前仓库状态

- 主项目目录：`clawos/`
- 后端：FastAPI，入口 `clawos/clawos_server.py`
- 前端：单文件工作台 `clawos/static/index.html`
- 存储：SQLite，核心在 `clawos/memoryos/memory_store.py`
- 工具运行：`clawos/scripts/tool_runner.py`
- 模型 provider：`clawos/providers/`
- MTClaw adapter：`clawos/mtclaw/`
- 测试目录：`clawos/tests/`

## 已完成能力

- Provider 抽象：`deepseek`、`openai_compatible`、`mock`
- 本地 `.env` 加载，避免提交密钥
- `/health` 暴露 provider/model/configured 状态，不暴露 API Key
- MemoryOS 五类统一记忆：profile、preference、project、experience、skill
- MemoryOS 检索、启用/禁用、前端维护页面
- Reflection 基础分析和经验写入
- MTClaw adapter、trace API、fallback 策略
- 工具执行 envelope 和部分高风险工具确认机制
- Task / Step / Event 持久化运行时 MVP
- 前端已有 Memory、Reflection、Skills、Tools、Task Trace 视图

## 最近完成的开发块

### 2026-06-14 - Task / Step / Event 运行时 MVP

新增：

- `tasks` 表：记录一次用户请求级任务。
- `task_steps` 表：记录工具调用等步骤。
- `task_events` 表：记录 task/step 生命周期事件。
- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `/v1/chat/completions` 响应中返回 `clawos.task_id`
- 前端“任务轨迹”面板，展示 task 列表、step 和 event。

验证：

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

最近一次验证结果：`44 tests OK`。

## 当前主要差距

第一优先级：

- MemoryOS 版本、冲突检测、证据链、Review Inbox。
- Reflection 完整反思卡表、用户反馈、改进项状态机。
- 工具沙箱、路径白名单、命令策略、审计和密钥管理。
- 持久化任务的取消、重试、恢复、幂等键。

第二优先级：

- Policy Optimizer / Bandit 策略优化。
- Git 协作工作流、项目模板中心。
- 科研 PDF 知识库、会议全流程、学习系统。
- 前端企业级交互重构和可视化任务图。

## 下一步建议

建议先做：

```text
MemoryOS 2.0 MVP:
版本记录 + 冲突检测 + 证据链 + Review Inbox
```

原因：

- Task runtime 已经有了 trace 载体。
- MemoryOS 是后续 Reflection、Policy Optimizer、长期复用的核心。
- 先解决“不静默覆盖记忆”和“每条记忆可追溯”，能明显提高项目可信度。

## 本地运行注意事项

- Windows 本地优先用 `start_clawos.bat`。
- `.env` 放在 `clawos/.env`，不要提交。
- 如果测试用系统 Python 报缺 `uvicorn`，改用 `clawos/.venv/Scripts/python.exe`。
- MTClaw 相关测试可能打印 FastAPI deprecation warning，通常不是失败。

## 协作习惯

- 修改前先看本文件。
- 开始工作时使用 repo-local skill：`.agents/skills/clawos-project-onboarding/SKILL.md`。
- GitHub 同步、合并、推送前使用：`.agents/skills/clawos-git-collaboration/SKILL.md`。
- 完成开发块并交接时使用：`.agents/skills/clawos-handoff-update/SKILL.md`。
- 每个开发块尽量控制在一个清晰主题内。
- 开发后跑测试，并把结果写进“最近完成的开发块”。
- 如果出现测试运行导致 `clawos/skills/skill_registry.jsonl` 的 use_count/last_used 变化，通常是测试副作用，不要当作业务改动提交。

## Repo-local Skills

已新增三类协作 skills，目的是让两个人和两个 Codex 都按同一套节奏工作：

- `clawos-project-onboarding`：接手项目前先读上下文、检查 Git 状态、避免扫全仓库。
- `clawos-git-collaboration`：远程同步、合并后快进、分支 ahead/behind 判断和安全推送前检查。
- `clawos-handoff-update`：完成开发块后更新 `PROJECT_CONTEXT.md`、记录测试、风险和下一步。
