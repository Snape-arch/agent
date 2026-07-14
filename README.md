# Agent / ClawOS Workspace

ClawOS 是一个 Windows 本地个人 Agent OS 原型，围绕 observe-plan-execute-reflect-memory-improve 闭环组织模型路由、工具调用、任务状态、记忆和反思审查。

## 接手先读

新协作者优先阅读：

1. `PROJECT_CONTEXT.md`：当前分支、提交、进度、风险和下一步。
2. `clawos/README.md`：ClawOS 子项目说明。
3. `clawos/MTCLAW_INTEGRATION.md`：MTClaw 接入说明。
4. `.agents/skills/`：仓库内协作技能。

## Windows 本地启动

从任意 clone 路径进入仓库根目录：

```powershell
cd <your-cloned-agent-repo>
.\start_clawos.bat
```

For an explicit local daily-use profile after the verified Qwen, llama.cpp,
embedding, and Chroma assets are installed:

```powershell
.\start_clawos.bat --local
```

`--local` selects `clawos/config.local.json` for the current launcher process,
starts or reuses the local Qwen service, enables Chroma with Qwen3 embeddings,
and keeps the CPU-heavy reranker disabled by default. It does not modify
`clawos/.env` and does not download missing model/runtime files.

启动脚本使用自身位置推导仓库路径，不依赖 `D:\Projects\agent`。默认端口：

- ClawOS: `http://127.0.0.1:18790`
- MTClaw Function Router: `http://127.0.0.1:18791`

脚本会提示：

- Python 或 `clawos\.venv` 缺失。
- 默认端口已被占用。
- `clawos\.env` 缺失。没有真实 Key 时，mock 和 frozen benchmark 仍可运行。

## 本地配置

真实密钥只放在：

```text
clawos/.env
```

示例配置见：

```text
clawos/.env.example
```

常用变量：

- `MODEL_PROVIDER=deepseek`
- `MODEL_BASE_URL=https://api.deepseek.com/v1`
- `MODEL_NAME=deepseek-chat`
- `MODEL_API_KEY=...`
- `MTCLAW_ENABLED=true`
- `MTCLAW_BASE_URL=http://127.0.0.1:18791`

不要把 API Key 写入命令、文档、报告或提交内容。

## 健康检查

启动后检查：

```powershell
Invoke-RestMethod http://127.0.0.1:18790/health
```

`/health` 应能看到：

- `model_provider.provider`
- `model_provider.model`
- `model_provider.configured`
- `mtclaw.enabled` / `mtclaw.reachable`
- `database.configured` / `database.reachable`

## 离线验收

优先运行 mock / frozen 流程，不消耗 API。

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py
.\clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider mock
```

输出摘要包含通过数、失败数、通过率和关键失败原因。脚本使用临时数据库，避免污染 `clawos\.env`、本地数据库或仓库状态。

比赛架构与 MTClaw 垂直路由验收：

```powershell
python clawos\scripts\run_mtclaw_vertical_acceptance.py
python clawos\scripts\validate_competition_architecture.py
python clawos\scripts\evaluate_paper_intelligence.py
python clawos\scripts\benchmark_paper_retrieval.py
```

论文与知识库阶段一验收报告见 `clawos/PAPER_KNOWLEDGE_ENTERPRISE_ACCEPTANCE_2026-07-10.md`。后一个命令会加载仓库外 `tools/models` 中的真实本地 Qwen3 embedding/reranker 权重；权重目录和临时下载文件不得提交。

目标 MTT Linux 的严格比赛入口为：

```bash
cd clawos
bash scripts/start_competition_stack.sh
```

该入口使用 `config.competition.json`，要求本地 Qwen 和 MTClaw 可用，关闭 MTClaw fallback，且不配置云模型 fallback。真实设备验收前不要把离线合同测试表述为 MTT 实机通过。

## 真实 API 手动验收

不要默认运行真实 API。需要手动验收 DeepSeek 时，由用户先确认额度和 Key，再运行：

```powershell
$env:MODEL_API_KEY="<your-deepseek-key>"
.\clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider deepseek --model deepseek-chat --base-url https://api.deepseek.com/v1 --out output\deepseek_acceptance_report.json
```

报告不包含 API Key。提交前确认 `output\deepseek_acceptance_report.json` 不进入 Git。

## 控制台演示检查

启动后打开：

```text
http://127.0.0.1:18790/console
```

演示前至少检查：

- 首页和控制台能打开。
- 配置页能显示 provider/model/configured，API Key 不明文回显。
- 任务页能显示任务状态、恢复队列、Step Trace 和事件审计。
- 工具调用页能显示执行记录和确认状态。
- Memory/Reflection Review 能显示审查列表和操作按钮。

只修阻碍演示的问题，不做大规模视觉重构。

## 干净交付

不要右键压缩整个项目目录，因为会带上 `.env`、`.venv`、数据库、日志和缓存。只打包已提交内容时使用：

```powershell
git archive --format=zip --output ..\agent-clean.zip HEAD
```

提交前检查：

```powershell
git status --short
git ls-files clawos/.env clawos/*.db clawos/*.log clawos/__pycache__
```

`.env`、数据库、日志、缓存不应进入提交。

## 常用测试

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
.\clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\scripts\run_frozen_benchmarks.py clawos\scripts\evaluate_model_acceptance.py
node --check clawos/static/assets/console.js
```

当前目标是 Windows 本地 MVP+：可交接、可启动、可验收、可演示。
