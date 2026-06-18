# Project Context

这个文件是 ClawOS 的协作交接入口。下一位 Codex 或协作者应先读这里，再按需读具体模块，避免重新扫描整个仓库。

## 维护规则

- 每次完成一个有意义的开发块，都更新“最近完成”。
- 状态、风险、验证结果或下一步变化时，直接更新对应章节。
- 不记录 API Key、token、密码、私有密钥或 `.env` 内容。
- 不写夸大表述；除非有逐项证据，不使用“生产级”“企业级”等措辞。

## 当前状态

- 当前分支：`codex/fix-routing-memory-ui`
- 远程仓库：`https://github.com/Snape-arch/agent.git`
- 当前提交：本开发块提交信息为 `收束 ClawOS Windows MVP 验收闭环`；具体 hash 用 `git log -1 --oneline` 查看。
- 当前定位：Windows 本地个人 Agent OS 原型的 MVP+ 收束版。
- 当前目标：可交接、可启动、可验收、可演示。
- Windows 双服务入口：根目录 `start_clawos.bat`
- 控制台入口：`http://127.0.0.1:18790/console`

## 接手顺序

1. 读 `PROJECT_CONTEXT.md`。
2. 读根目录 `README.md` 的启动、验收和交付章节。
3. 需要看 MTClaw 时读 `clawos/MTCLAW_INTEGRATION.md`。
4. 需要改前端时读 `clawos/static/console.html`、`clawos/static/assets/console.js`、`clawos/static/assets/site.css`。
5. 需要改后端时优先定位 `clawos/clawos_server.py`、`clawos/memoryos/`、`clawos/scripts/` 中对应模块。

## 项目结构

- 主服务：`clawos/clawos_server.py`
- 前端：`clawos/static/`
- 模型 provider：`clawos/providers/`
- MTClaw adapter/runtime：`clawos/mtclaw/`、`clawos/mtclaw_runtime/`
- 记忆系统：`clawos/memoryos/`
- Reflection：`clawos/reflection/`
- 工具执行：`clawos/scripts/tool_runner.py`、`clawos/scripts/scenario_tools.py`
- 离线验收：`clawos/scripts/run_frozen_benchmarks.py`
- 模型验收：`clawos/scripts/evaluate_model_acceptance.py`
- 测试：`clawos/tests/`
- 协作 skills：`.agents/skills/`

## 已完成能力

- DeepSeek / OpenAI-compatible / mock provider 抽象。
- `/health` 暴露 provider、model、configured、MTClaw、数据库状态，不暴露 API Key。
- Windows 双服务启动脚本从自身路径推导仓库位置，不依赖 `D:\Projects\agent`。
- 启动脚本提示端口占用、Python/虚拟环境缺失、`.env` 缺失。
- MTClaw 双服务链路：ClawOS -> MTClaw `/v1/chat/completions` -> Tool History -> ClawOS trace。
- MemoryOS 五类记忆、检索、Review、ACL 和评测基础。
- Reflection 卡片、反馈、状态机、回归验证和回滚基础。
- Task / Step / Event 持久化运行时，含幂等、取消、重试、恢复、队列领取和事件审计基础。
- 控制台可展示系统状态、模型配置、任务状态、恢复队列、Step Trace、事件审计、工具调用、Memory Review、Reflection Review。
- 文件化冻结验收任务：`clawos/benchmarks/competition_frozen_v1.json`，当前 30 条。
- mock 模型验收脚本：`clawos/scripts/evaluate_model_acceptance.py --provider mock`。

## 当前验收命令

离线优先，不消耗 API：

```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py
.\clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider mock
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

真实 DeepSeek 验收只在用户明确允许后运行：

```powershell
$env:MODEL_API_KEY="<your-deepseek-key>"
.\clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider deepseek --model deepseek-chat --base-url https://api.deepseek.com/v1 --out output\deepseek_acceptance_report.json
```

报告不包含 API Key。`output\deepseek_acceptance_report.json` 不应进入提交。

## 重要风险

1. 不要泄露本地 `.env`。不要右键压缩整个项目目录交付，因为会带上 `.env`、`.venv`、数据库、日志和缓存。
2. 干净打包只能使用 Git 已提交内容：
   ```powershell
   git archive --format=zip --output ..\agent-clean.zip HEAD
   ```
3. `clawos_server.py`、`memory_store.py`、`tool_runner.py` 仍偏大；当前优先稳定演示和验收，不做大规模拆分。
4. 真实 API 验收会消耗额度，不能自动运行。
5. 本地离线 Qwen/vLLM-MUSA 尚未闭环；当前离线验收依赖 mock provider 和 frozen benchmark。

## 当前缺口

- 还需要一次真实浏览器截图或人工目视复核；本轮已完成启动后的 HTTP 页面/API 演示检查，但本地 Node 未安装 `playwright` 包，独立截图未生成。
- Task Runtime 仍缺长期后台 worker、补偿事务和故障注入验收。
- 身份、RBAC、Keyring、备份恢复、迁移、可观测性还只是后续方向，不属于本轮 MVP+ 验收门槛。

## 最近完成

### 2026-06-18 - MVP+ 交接和验收闭环收束

已完成：

- 根目录 `README.md` 收束为 Windows 本地启动、健康检查、离线验收、真实 API 手动验收、控制台演示检查和干净交付说明。
- `start_clawos.bat` 增加默认端口占用预检查，并说明 `.env` 缺失时 mock/offline 检查仍可运行。
- `/health` 增加 SQLite 数据库配置和连通状态。
- `run_frozen_benchmarks.py` 文本输出固定为通过数、失败数、通过率、P95 和失败原因。
- `evaluate_model_acceptance.py` 文本输出增加通过数和失败数。
- 测试覆盖补充：冻结 runner 输出、模型验收输出、`/health` 数据库状态。

验证结果：

- `.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py`：`30/30` passed，`failed_count=0`。
- `.\clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider mock`：`score=150/150 rate=1.0`，`failed_count=0`。
- `.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests`：`104 tests OK`。
- `.\clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\scripts\run_frozen_benchmarks.py clawos\scripts\evaluate_model_acceptance.py`：通过。
- `node --check clawos/static/assets/console.js`：通过。
- 启动后 HTTP/API 演示检查通过：首页、控制台、模型配置文案、任务 Trace/事件审计、工具记录、Memory Review、Reflection Review、乱码扫描、Key 遮罩、`/health` provider/model/configured/MTClaw/database 字段。

## 下一步

1. 用用户可见浏览器或已安装 Playwright 的环境补一张控制台截图，确认布局没有明显遮挡。
2. 若用户允许，手动运行 DeepSeek 验收命令并保存 `output\deepseek_acceptance_report.json`，不要提交报告。
3. 若发现演示阻碍问题，只做最小修复。
4. 确认 `git status` 只包含本轮应提交文件，且 `.env`、数据库、日志、缓存未进入 Git。
