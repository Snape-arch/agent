# Agent / ClawOS Workspace

本仓库是基于 ClawOS + MTClaw 思路的 Windows 本地个人 Agent OS 原型。它围绕 observe-plan-execute-reflect-memory-improve 闭环，重点实现模型可切换、工具可审计、危险操作可确认、记忆可管理、反思可沉淀。

## 接手先读

下一位 Codex 或协作者接手时，优先阅读：

1. `PROJECT_CONTEXT.md`：当前状态、最近改动、风险和下一步。
2. `clawos/ROADMAP.md`：工程路线图。
3. `clawos/ENTERPRISE_READINESS.md`：成熟度评分和企业级差距。
4. `clawos/MTCLAW_INTEGRATION.md`：MTClaw 集成说明。
5. `.agents/skills/`：仓库内协作 skills。

## 当前重点

短期目标是把项目从“可演示竞赛原型”推进到“Windows 本地稳定闭环的个人 Agent 工作台”：

- 修复协作文档和交接体系。
- 做 Windows 一键启动：ClawOS + MTClaw + health check。
- 建立 20-30 条冻结验收任务，覆盖会议、科研、学习、Git、模板/工具。
- 补强 Task Runtime：幂等、取消、重试、恢复、队列、审计；当前已有基础队列领取，后续补后台 worker 和补偿事务。
- 重构前端为任务控制台：实时任务流、Trace、确认弹窗、Memory/Reflection Review；当前已接入任务队列、领取、步骤 Trace、事件审计和 Review 操作基础。
- 完成 DeepSeek 与未来本地 Qwen 的统一模型切换和验收报告。

## Windows 本地运行

推荐一键启动双服务：

```powershell
cd <your-cloned-agent-repo>
.\start_clawos.bat
```

该脚本应完成：

- 生成 MTClaw runtime。
- 启动 MTClaw Function Router：`http://127.0.0.1:18791`
- 启动 ClawOS：`http://127.0.0.1:18790`
- 执行基础 health check。

也可以手动运行 ClawOS 单服务：

```powershell
cd <your-cloned-agent-repo>\clawos
.\.venv\Scripts\python.exe clawos_server.py --host 127.0.0.1 --port 18790
```

浏览器打开：

```text
http://127.0.0.1:18790
```

## 本地配置

真实密钥只放在：

```text
clawos/.env
```

该文件已被 `.gitignore` 忽略，不要提交。示例配置看：

```text
clawos/.env.example
```

关键变量：

- `MODEL_PROVIDER=deepseek`
- `MODEL_BASE_URL=https://api.deepseek.com/v1`
- `MODEL_NAME=deepseek-chat`
- `MODEL_API_KEY=...`
- `MTCLAW_ENABLED=true`
- `MTCLAW_BASE_URL=http://127.0.0.1:18791`

## 干净打包

不要右键压缩整个项目文件夹，因为会把 `.env`、`.venv`、`memoryos.db`、日志、`__pycache__` 等本地内容一起打进去。

只打包已提交内容时使用：

```powershell
git archive --format=zip --output ..\agent-clean.zip HEAD
```

该命令只包含 Git 已跟踪且已提交的文件，不会带上本地密钥和运行态文件。

## 测试

推荐使用项目虚拟环境：

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

当前基线：全量单测应为 `97 tests OK`。运行测试可能会改动 `clawos/skills/skill_registry.jsonl` 的使用计数，提交前应恢复该运行态副作用。

冻结验收任务：

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py
```

当前基线：`30/30 passed`，覆盖会议、科研、学习、Git、模板、核心工具和少量真实公开数据样例。

模型验收评分脚手架：

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider mock
```

当前离线基线：`score=150/150 rate=1.0`。真实 DeepSeek 或本地 Qwen 验收应复用同一脚本，通过环境变量读取密钥，不要把 API Key 写入命令、文档或提交内容。

## 协作约定

- 开始工作前读 `PROJECT_CONTEXT.md`。
- 每次完成一个有意义开发块，更新 `PROJECT_CONTEXT.md`。
- GitHub 同步、合并、推送前使用 `.agents/skills/clawos-git-collaboration`。
- 开始仓库工作时使用 `.agents/skills/clawos-project-onboarding`。
- 完成交接时使用 `.agents/skills/clawos-handoff-update`。
- 不要提交 API Key、`.env`、本地数据库、运行日志或生成缓存。
- 对外表述保持克制：不要宣称“企业级”“全自动自进化”“完全本地离线”“95% 准确率”或“生产级系统”，除非有逐项验收证据。
