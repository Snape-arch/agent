# Project Context

这个文件是 ClawOS 项目的协作交接记录。下一位 Codex 或协作者应先读这里，再按需读具体代码，避免每次重新扫描整个仓库。

## 维护规则

- 每次完成一个有意义的开发块，都在“最近完成”中追加记录。
- 如果项目状态、风险、评分或下一步变化，直接更新对应章节。
- 不记录 API Key、token、密码、私有密钥或 `.env` 内容。
- 测试命令和结果只写必要摘要，不贴长日志。

## 当前状态

- 当前分支：`codex/fix-routing-memory-ui`
- 远程仓库：`https://github.com/Snape-arch/agent.git`
- 最近本地提交：`d94b128 修复了一些问题`
- 当前成熟度估计：`75/100`
- 定位：Windows 本地可运行的个人 Agent OS 原型，围绕 observe-plan-execute-reflect-memory-improve 闭环，重点实现模型可切换、工具可审计、危险操作可确认、记忆可管理、反思可沉淀。
- Windows 双服务入口：根目录 `start_clawos.bat`

## 项目结构

- 主服务：`clawos/clawos_server.py`
- 前端：`clawos/static/`
- 模型 provider：`clawos/providers/`
- MTClaw adapter/runtime：`clawos/mtclaw/`
- 记忆系统：`clawos/memoryos/`
- Reflection：`clawos/reflection/`
- 工具执行：`clawos/scripts/tool_runner.py`
- 测试：`clawos/tests/`
- 协作 skills：`.agents/skills/`

## 已完成能力

- DeepSeek / OpenAI-compatible / mock provider 抽象。
- `/health` 暴露 provider/model/configured 状态，不暴露 API Key。
- MTClaw 双服务真实链路：ClawOS -> MTClaw `/v1/chat/completions` -> Tool History -> ClawOS trace。
- Windows 下 MTClaw 可执行 `.cmd` 工具包装脚本，避免依赖未配置 WSL bash。
- MemoryOS 五类记忆、检索、Review、ACL、评测基础。
- Reflection 卡片、反馈、状态机、回归验证和回滚基础。
- Task / Step / Event 持久化运行时，含幂等、取消、重试、恢复、队列领取和事件审计基础。
- 前端已有产品页、控制台、Memory/Reflection Review 操作、Skills、Tools、Task Trace、恢复队列和事件审计视图。
- 全量单测当前基线：`97 tests OK`。
- 文件化冻结验收任务：`clawos/benchmarks/competition_frozen_v1.json`，runner 为 `clawos/scripts/run_frozen_benchmarks.py`，当前 `30/30 passed`。
- 模型验收评分脚手架：`clawos/scripts/evaluate_model_acceptance.py`，mock 离线基线 `score=150/150 rate=1.0`。

## 当前主要缺口

1. Windows 双服务一键启动已实现基础版，但仍需端口占用检测、优雅停止和用户手动试跑反馈。
2. README/PROJECT_CONTEXT 已恢复可读，但其他历史文档可能仍有乱码，需逐步清理。
3. 前端已有任务流、恢复队列、Trace/事件审计、确认弹窗、Memory/Reflection Review 操作基础，但仍缺视觉验收和长任务状态联动。
4. Task Runtime 已有幂等、取消、重试、恢复、队列领取和事件审计基础，但仍缺完整后台 worker、补偿事务和长期故障注入。
5. 本地离线 Qwen/vLLM-MUSA 尚未闭环，目前主要依赖 DeepSeek API。
6. 已有 30 条文件化冻结验收任务和模型评分脚手架，仍需跑 DeepSeek/本地 Qwen 真实对比，并把真实模型路由命中率纳入验收。
7. 身份、RBAC、多租户、Keyring、备份恢复、迁移、可观测性仍未达标。

## 重要风险

1. 不要泄露本地 `.env`。禁止右键压缩整个项目文件夹交付，因为会带上 `.env`、`.venv`、`memoryos.db`、logs、`__pycache__` 等本地内容。
2. 干净打包只能使用 Git 已提交内容，例如：
   ```powershell
   git archive --format=zip --output ..\agent-clean.zip HEAD
   ```
3. 文档和演示话术必须克制。不要写“企业级”“全自动自进化”“完全本地离线”“95% 准确率”“生产级系统”，除非有当前验收证据。
4. `clawos_server.py`、`memory_store.py`、`tool_runner.py` 偏大，长期维护有风险；但当前优先级是稳定演示、同步文档、形成验收脚本、保证别人能看懂，不急着大拆。

## 最近完成

### 2026-06-17 - Windows MTClaw 双服务链路修复

已完成：
- `clawos/mtclaw/prepare_runtime.py` 同时生成 Linux `.sh` 和 Windows `.cmd` 工具包装脚本。
- `MTClaw-框架代码/function_router/server.py` 在 Windows 下优先执行 `.cmd/.bat`，Linux 下仍执行 `.sh`。
- `clawos/clawos_server.py` 和 `clawos/mtclaw/adapter.py` 对本地 MTClaw HTTP client 使用 `trust_env=False`，避免系统代理/Privoxy 拦截 `127.0.0.1:18791`。
- 真实联调验证：MTClaw `/health` 200，ClawOS `/health.mtclaw.reachable=true`，聊天响应 `clawos.mtclaw.used=true`，工具调用 `time_now`，MTClaw `tool_history` 有记录。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_mtclaw_adapter
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：MTClaw 专项 `6 tests OK`；全量 `90 tests OK`。

### 2026-06-17 - 文档恢复与协作上下文整理

已完成：
- 重写根目录 `README.md`，恢复为可读 UTF-8 中文。
- 重写 `PROJECT_CONTEXT.md`，保留项目定位、当前状态、已完成能力、缺口和近期交接。
- 明确长期 goal：把 ClawOS 从 68/100 推进到 80/100 的 Windows 本地稳定闭环版本。

### 2026-06-17 - Windows 双服务启动器基础版

已完成：
- 升级根目录 `start_clawos.bat`，启动流程变为 ClawOS + MTClaw 双服务。
- 脚本会优先使用 `clawos\.venv\Scripts\python.exe`，自动加载 `clawos\.env`，并在需要时把 `DEEPSEEK_API_KEY` 映射为 MTClaw 使用的 `MODEL_API_KEY`。
- 脚本不再硬编码中文 MTClaw 目录名，而是自动查找 `MTClaw-*` 目录。
- 新增 `clawos/scripts/windows_health_check.py`，用于禁用代理的本地 health check。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m py_compile clawos\scripts\windows_health_check.py
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：新增脚本编译通过；全量 `90 tests OK`；受控双服务 smoke 通过：MTClaw `/health` 200，ClawOS `/health` 200，聊天请求 `clawos.mtclaw.used=true`，工具调用 `time_now`。

注意：
- 本轮未直接执行 `start_clawos.bat`，避免在 Codex 环境里留下两个独立控制台窗口；验证使用了同等启动命令的受控子进程。
- 后续应由用户或 Codex 在可见终端中手动试跑一次 `.\start_clawos.bat`，确认窗口体验和报错提示。

### 2026-06-17 - 文件化冻结验收任务基础版

已完成：
- 新增 `clawos/benchmarks/competition_frozen_v1.json`，把冻结验收任务从数据库默认值扩展为可审阅、可版本化的 JSON 文件。
- 当前包含 5 条低风险验收任务，覆盖 `meeting`、`research`、`learning`、`git`、`template` 五类场景。
- `clawos/scenario_benchmarks.py` 支持从文件加载默认 suite，并新增 `data_paths`、`data_contains_text`、`tool` 等结构断言。
- 新增 `clawos/scripts/run_frozen_benchmarks.py`，可独立运行文件化验收任务。
- 修复 `clawos/workspace_services.py` 中 Git subprocess 的 Windows 解码问题，统一使用 UTF-8 + replace，避免中文路径/提交信息导致 Git snapshot 失败。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_scenario_benchmarks
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：冻结任务 `5/5 passed`，P95 约 `137.777ms`；场景 benchmark 专项 `5 tests OK`；全量 `93 tests OK`。

注意：
- 目前只有 5 条 seed 任务，用于建立格式和 runner；长期目标仍是扩展到 20-30 条，并输出模型/工具命中率/P50/P95 报告。
- 冻结任务 runner 不写死仓库路径，运行时从脚本位置推导仓库根目录。

### 2026-06-18 - 冻结验收任务扩展到 27 条

已完成：
- `clawos/benchmarks/competition_frozen_v1.json` 从 5 条扩展到 27 条，覆盖会议、科研、学习、Git、模板、Office artifact、项目脚手架和核心工具。
- `clawos/scripts/run_frozen_benchmarks.py` 支持 `${tmpdir}`、`${repo_root}`、`${clawos_root}` 占位符和 `_benchmark_fixtures`，运行时使用临时数据库，避免污染本地 `.env` 或 `memoryos.db`。
- 新增会议侧边 transcript/audio fixture、科研复现实验目录、学习复盘/错题/图谱/掌握度、Git snapshot/commit plan/change request、模板实例化、Office XLSX/PPTX、代码统计/TODO 扫描等验收面。
- 测试门槛更新为默认 suite 至少 20 条，并校验 runner 输出 `cases=27/27`。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_scenario_benchmarks
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：冻结任务 `27/27 passed`，P95 约 `261.268ms`；场景 benchmark 专项 `5 tests OK`；全量 `93 tests OK`。

注意：
- 本轮已按安全要求补充 README/PROJECT_CONTEXT：禁止右键压缩整个项目，干净打包使用 `git archive --format=zip --output ..\agent-clean.zip HEAD`。
- 文档表述已降调为“Windows 本地个人 Agent OS 原型”，避免宣称企业级、全自动自进化、完全离线、95% 准确率或生产级系统。

### 2026-06-18 - 冻结验收任务加入真实公开数据样例

已完成：
- `clawos/benchmarks/competition_frozen_v1.json` 从 27 条扩展到 30 条，仍保持在 20-30 条冻结验收任务范围内。
- 新增 NASA Apollo 11、UCI Iris、Project Gutenberg Alice 三类公开来源样例，用于后续 DeepSeek/API Key 实测和自动评分。
- 新增任务只保存来源 URL、少量结构化事实和小样例数据，不保存大段外部文本，也不依赖外部网络运行。
- `clawos/tests/test_scenario_benchmarks.py` 的 runner 输出校验更新为 `cases=30/30`。

真实数据来源：
- NASA Apollo 11 Mission Overview: `https://www.nasa.gov/history/apollo-11-mission-overview/`
- UCI Iris Dataset: `https://archive.ics.uci.edu/dataset/53/iris`
- Project Gutenberg eBook 11: `https://www.gutenberg.org/ebooks/11`

验证：
```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_scenario_benchmarks
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：冻结任务 `30/30 passed`，P95 约 `259.679ms`；场景 benchmark 专项 `5 tests OK`；全量 `93 tests OK`。

### 2026-06-18 - 模型验收评分脚手架

已完成：
- 新增 `clawos/scripts/evaluate_model_acceptance.py`，复用 30 条冻结任务，先执行工具侧验收，再调用统一 ModelProvider 生成验收结论并打分。
- 默认 provider 为 `mock`，不依赖真实 API Key；真实 DeepSeek/Qwen 运行时通过环境变量读取密钥，不在输出中暴露 Key。
- 新增 `clawos/tests/test_model_acceptance.py`，覆盖 mock provider、截断 suite、JSON 输出和密钥不泄露检查。
- 更新 `clawos/ENTERPRISE_READINESS.md`，加入当前验收证据、75/100 评分、差距和下一步。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider mock
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
```

结果：模型验收 mock 基线 `score=150/150 rate=1.0`；模型验收与场景 benchmark 专项合计 `6 tests OK`；全量 `94 tests OK`；本轮冻结任务复测 P95 约 `277.739ms`。

### 2026-06-18 - Task Runtime 队列领取与审计基础

已完成：
- `clawos/memoryos/memory_store.py` 新增 `list_task_queue` 和 `claim_next_task`，支持列出 `pending_retry/pending` 任务并由 worker 领取。
- 领取任务会把状态更新为 `running`，`resume_state` 更新为 `claimed`，并在 metadata 中记录 `claimed_by/claimed_at`。
- 新增 `task_claimed` 事件，保证队列领取动作可审计。
- `clawos/clawos_server.py` 新增 `/api/tasks/queue` 和 `/api/tasks/queue/claim`，方便前端或后续 worker 使用。
- `clawos/tests/test_runtime_task_control.py` 增加队列和 API 覆盖。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_runtime_task_control
```

结果：Task Runtime 专项 `9 tests OK`；全量 `96 tests OK`；本轮冻结任务复测 P95 约 `306.271ms`。

### 2026-06-18 - 前端任务控制台队列与审计视图

已完成：
- `clawos/static/console.html` 的任务页新增“恢复队列”“步骤 Trace”“事件审计”三个区域。
- `clawos/static/assets/console.js` 接入 `/api/tasks/queue` 和 `/api/tasks/queue/claim`，支持刷新队列和从控制台领取下一个可恢复任务。
- 任务详情从混合表格拆成步骤 Trace 和事件审计，便于现场演示任务如何执行、如何被取消/重试/恢复。
- `clawos/tests/test_frontend_static.py` 增加队列、领取、Trace 和审计视图静态覆盖。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
```

结果：前端静态测试 `9 tests OK`；全量 `96 tests OK`；本轮冻结任务复测 P95 约 `277.057ms`。

### 2026-06-18 - Memory/Reflection Review 操作接入控制台

已完成：
- `clawos/static/console.html` 新增 `Memory Review Inbox` 和 `Reflection Review Inbox`。
- `clawos/static/assets/console.js` 接入 `/api/memory/reviews`、`/api/memory/reviews/{id}/resolve`，支持在控制台批准/拒绝记忆冲突。
- `console.js` 接入 `/api/reflection/improvements` 及 transition/validate/publish/rollback API，支持反思改进从提议、批准、验证、发布到回滚的基本操作。
- `clawos/tests/test_frontend_static.py` 增加 Memory/Reflection Review 操作静态覆盖。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
```

结果：前端静态测试 `10 tests OK`；全量 `97 tests OK`；本轮冻结任务复测 P95 约 `271.388ms`。

## 推荐下一步

1. 给 `start_clawos.bat` 增加端口占用检测和优雅停止说明。
2. 用真实 DeepSeek API 跑 `evaluate_model_acceptance.py`，保存评分报告，并补充失败样例分析。
3. 前端下一轮优先补真实浏览器截图验收和长任务状态联动。
4. Task Runtime 下一轮优先做后台 worker、补偿事务和故障注入验收。
### 2026-06-18 - Console visual refinement and model API settings

Completed:
- Refined `clawos/static/console.html` and `clawos/static/assets/site.css` toward a lighter console surface: fewer dashboard blocks, softer liquid-glass panels, reduced hard borders, overflow-safe layout, and a less cluttered first screen.
- Added in-page model API configuration through the system settings sheet. The UI writes provider/base URL/model/API key through `/api/config/model` and never renders the full API key back to the page.
- Added backend helpers in `clawos/clawos_server.py` to update `clawos/.env`, refresh routing/upstream providers at runtime, and return only masked model config state.
- Updated `start_clawos.bat` so a missing `clawos\.venv` no longer hard-fails when system Python is available.

Verification:
```powershell
python -m unittest clawos.tests.test_model_provider clawos.tests.test_frontend_static
python -m py_compile clawos\clawos_server.py
node --check clawos/static/assets/console.js
```

Result:
- Model provider + frontend static tests: `21 tests OK`.
- Python compile and JS syntax check passed.

Known note:
- Browser visual verification for `file:///.../console.html` was blocked by the in-app browser URL policy, so the next manual step is to refresh the open console page and visually inspect the liquid-glass layer and settings modal.
### 2026-06-18 - Scenario tool expansion and skill evolution loop

Completed:
- Added five local scenario tools in `clawos/scripts/tool_runner.py` and registered them in `clawos/functions.jsonl`:
  - `meeting_action_items`
  - `paper_deep_read`
  - `exam_practice_builder`
  - `work_brief_builder`
  - `research_experiment_plan`
- Added five default solidified skills in `clawos/skills/skill_registry.jsonl`:
  - `meeting_action_review`
  - `paper_deep_reading`
  - `exam_practice_coach`
  - `work_delivery_brief`
  - `research_experiment_designer`
- Added scenario coverage tests in `clawos/tests/test_scenarios_e2e.py`.
- Added a self-evolution loop test in `clawos/tests/test_skill_evolution.py`: propose a new scenario skill, run an execution suite, promote it, then execute the published skill.

Verification:
```powershell
python -m unittest discover -s clawos\tests
```

Result:
- Full suite: `102 tests OK`.

Known note:
- `tool_runner.py` is now too large. The next maintainability step should split scenario tools into a dedicated `scenario_tools.py` module and keep `tool_runner.py` as a thin dispatcher.

### 2026-06-18 - Scenario dispatcher split and chat-first console layout

Completed:
- Split scenario-oriented tool implementations into `clawos/scripts/scenario_tools.py`; `clawos/scripts/tool_runner.py` now delegates meeting, research, learning, office, template, git workspace, and skill governance scenario tools through a dispatch layer.
- Reworked the console into a chat-first product layout: default chat surface, compact sidebar, searchable history view, standalone library view, project workspace, local file attach button in the composer, and a More drawer for lower-frequency system panels.
- Added library tabs for project/research-learning/skill/preference memory so the existing RAG/memory direction can evolve into multiple maintained knowledge bases.
- Updated frontend static coverage for the new sidebar IA and scenario modules.

Verification:
```powershell
python -m unittest discover -s clawos\tests
python -m py_compile clawos\scripts\tool_runner.py clawos\scripts\scenario_tools.py clawos\clawos_server.py
node --check clawos/static/assets/console.js
```

Result:
- Full suite: `102 tests OK`.
- Python compile and JS syntax checks passed.
- Browser validation passed on `http://127.0.0.1:18790/console`: chat default, More drawer, search, library, projects, and file picker DOM all responded correctly.

Known note:
- Console CSS now has several override layers. A later cleanup should consolidate the console-only visual rules into a dedicated section or file before the final competition polish pass.
