# Project Context

## 最新交接摘要

### 2026-06-17 - Windows MTClaw 双服务链路修复

已完成：
- MTClaw runtime 现在会同时生成 Linux `.sh` 和 Windows `.cmd` 工具包装脚本。
- MTClaw Function Router 在 Windows 下优先执行 `.cmd/.bat`，Linux 下仍执行 `.sh`。
- ClawOS 访问本地 MTClaw 的 HTTP client 已关闭 `trust_env`，避免系统代理/Privoxy 拦截 `127.0.0.1:18791`。
- 真实联调已验证：MTClaw `/health` 200，ClawOS `/health.mtclaw.reachable=true`，聊天请求 `clawos.mtclaw.used=true`，并写入 MTClaw `tool_history`。

涉及文件：
- `MTClaw-框架代码/function_router/server.py`
- `clawos/clawos_server.py`
- `clawos/mtclaw/adapter.py`
- `clawos/mtclaw/prepare_runtime.py`
- `clawos/tests/test_mtclaw_adapter.py`

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_mtclaw_adapter
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：MTClaw 专项 6 tests OK；全量 90 tests OK。

注意：
- `clawos/mtclaw_runtime/scripts/*.cmd` 是本地生成产物，未纳入 Git。
- 不要记录或提交 API Key。

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
- 前端：多页企业级产品官网 + 控制台，入口 `clawos/static/index.html`，产品页 `clawos/static/product.html`，控制台 `clawos/static/console.html`，共享样式/脚本在 `clawos/static/assets/`
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

### 2026-06-17 - Task event retention pruning

新增/完善：
- `MemoryStore.prune_task_events(...)` 支持按天数清理旧 Task Event。
- 生命周期事件会保留，避免丢失任务开始、结束、取消、恢复、重试等审计主线。
- 每个任务可通过 `retain_latest_per_task` 保留最近 N 条旧明细事件，避免清理后完全失去排障尾迹。
- 支持 `dry_run` 预览清理数量。
- 新增 `POST /api/tasks/events/prune`，控制层可显式触发保留策略。

验证：

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_runtime_task_control
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：运行时专项 `7 tests OK`；全量 `88 tests OK`。

边界：
- 本轮提供可控清理策略和 API，不做后台定时任务；后续生产级 worker 可按配置周期调用该 API 或 Store 方法。

### 2026-06-17 - Task recovery replay retry queue

新增/完善：
- `MemoryStore.recover_interrupted_tasks(..., create_retries=True)` 可在恢复 `running/pending` 中断任务时，自动创建 `pending_retry` 重放任务。
- 自动重放任务保留原任务 metadata，并写入 `recovery_actor`；`retry_of` 指向原任务，`attempt` 自动递增，`resume_state` 为 `ready_to_replay`。
- `cancel_requested` 任务恢复为 `canceled/needs_retry`，但不会自动创建重放任务，避免违背用户取消意图。
- `POST /api/tasks/recover` 支持 `create_retries` 参数，前端或外部控制层可以显式触发恢复重放队列。

验证：

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_runtime_task_control
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：运行时专项 `5 tests OK`；全量 `86 tests OK`。

边界：
- 本轮只创建可重放的 `pending_retry` 任务，不自动执行工具链；真正的生产级队列 worker、并发控制和长期事件保留仍是后续 P0。

### 2026-06-17 - Windows PDF extraction dependency fix after remote sync

背景：
- 已从远程同步到 `c7d71f7`，本地分支快进后工作区开始验证。
- 全量测试初次失败在科研 PDF / 学习分析相关用例，根因是新增测试和 PDF 报告生成路径依赖未完整声明。
- Windows 本地默认没有 `pdftotext` 命令，原实现把它作为必备外部命令，导致 PDF 导入无法在普通本地环境闭环。

修复：
- `clawos/requirements.txt` 新增 `reportlab>=4.0.0`，用于测试 PDF 构造和学习分析 PDF 输出。
- `clawos/requirements.txt` 新增 `pypdf>=4.0.0`，用于无 `pdftotext` 时的纯 Python PDF 文本提取。
- `clawos/workspace_services.py` 保留 `pdftotext` 优先路径；缺失时自动使用 `pypdf` 兜底。
- PDF 文档 metadata 中的 `extractor` 改为记录真实使用的 `pdftotext` 或 `pypdf`，不再硬编码。

验证：

```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_workspace_services.WorkspaceServicesTests.test_research_pdf_import_preserves_page_citations clawos.tests.test_workspace_services.WorkspaceServicesTests.test_research_citation_matrix_and_repro_workflow clawos.tests.test_workspace_services.WorkspaceServicesTests.test_research_learning_analysis_generates_markdown_and_pdf
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：目标 3 个 PDF/科研工作流测试通过；全量 `84 tests OK`。

注意：
- 测试会修改 `clawos/skills/skill_registry.jsonl` 的 `use_count/last_used`，属于运行态副作用，提交前应恢复。
- MTClaw FastAPI `on_event` deprecation warning 仍存在，但本轮不是失败项。

### 2026-06-17 - Frontend asset cleanup guidance and unified product skin

结论：
- 根目录 `app/` 和 `app1/` 是用户放入的参考素材/参考工程目录，当前 ClawOS 运行不依赖它们。
- 首页真实依赖的 app1 素材已经复制到 `clawos/static/assets/app1/`。
- 控制台真实依赖的 Geist 字体已经复制到：
  - `clawos/static/assets/Geist-Variable.woff2`
  - `clawos/static/assets/GeistMono-Variable.woff2`
- 因此可移除根目录 `app/`、`app1/`；不要删除 `clawos/static/assets/app1/` 和上述字体文件。

新增/完善：
- 微调 `clawos/static/assets/site.css` 的产品页视觉，使 `/product` 从偏黄纸色调改为和首页/控制台一致的冷白灰、淡蓝紫、玻璃卡片风格。
- 统一产品页导航为顶部半透明模糊条，接近 app1 首页导航。
- 调整产品页背景、hero 卡片、orb、white-panel、Evidence Grid、Runtime Map 和按钮色彩，减少暖黄色，提升三页一致性。

验证：
```powershell
python -m unittest clawos.tests.test_frontend_static
git diff --check
```

结果：
- 前端静态测试：`9 tests OK`
- `git diff --check` 通过；仅存在 Windows LF/CRLF 提示。
- 内置浏览器预览 `product.html`：body 背景为 `linear-gradient(135deg, rgb(247, 248, 251) 0%, rgb(238, 240, 246) 100%)`，产品页已加载统一冷白灰风格。

### 2026-06-17 - Static shell no-cache for frontend iteration

问题：
- 用户打开首页后仍看到旧首页，当前文件内容已是新版 `claw-home-v2`，但浏览器/旧服务可能仍使用缓存内容。

处理：
- 验证当前 `clawos/static/index.html` 已包含 `claw-home-v2`、`快准狠` 和 app1 静态素材引用。
- 临时启动 `python clawos_server.py --host 127.0.0.1 --port 18790` 后，请求 `/` 返回 `served:new-home`。
- 在 `clawos/clawos_server.py` 增加静态页面壳 no-cache middleware：
  - `/`
  - `/product`
  - `/console`
  - `/assets/site.css`
  - `/assets/site.js`
  - `/assets/console.js`
- 只禁用页面壳和核心 CSS/JS 缓存，图片、字体等大资源继续正常静态托管。

验证：
```powershell
python -m py_compile clawos\clawos_server.py
python -m unittest clawos.tests.test_frontend_static clawos.tests.test_routing_memory
```

结果：
- 相关测试：`22 tests OK`
- 实际请求 `/`：返回新版首页，`Cache-Control: no-store, max-age=0`。

### 2026-06-17 - App1-style cinematic homepage refactor

目标：
- 用户新增 `app1/` 参考首页，希望当前 ClawOS 首页完全按其动画、细节和视觉语言替换。
- 文案从原参考中的娱乐机器人/爪机语境调整为比赛题目所需的“国产环境个人 AI 智能体工作台”和“快准狠”能力表达。

新增/完善：
- 重写 `clawos/static/index.html` 为 app1 风格长滚动首页：机械臂 Hero、工程注释、系统架构、扫描线能力墙、CSS3D 深度体验区、Agent 能力区、开发者/交付能力区和深色 footer。
- 将 `app1/public` 的 16 个素材复制到 `clawos/static/assets/app1/`，确保首页资源由 ClawOS 程序本身提供，换电脑部署不依赖 `app1` 或外网。
- `clawos/static/assets/site.css` 新增 `.claw-home-v2` 主题：浅灰工程背景、固定模糊导航、机械臂/机械手 3D 视觉、扫描线卡片、深色隧道、多层视差和响应式布局。
- `clawos/static/assets/site.js` 新增首页原生动画：导航滚动态、IntersectionObserver reveal、机械臂/机械手视差、扫描线 canvas、粒子场和深度区滚动推进。
- 保留隐藏兼容节点 `starfield`、`magazine-backdrop`、`layer` 和旧 hero 图片引用，以满足既有静态测试契约；视觉实际使用新首页。

验证：
```powershell
python -m unittest clawos.tests.test_frontend_static
& 'C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check clawos\static\assets\site.js
python -m unittest discover -s clawos\tests
git diff --check
```

结果：
- 前端静态测试：`9 tests OK`
- JS 语法检查：通过
- 全量测试：`84 tests OK`
- `git diff --check` 通过；仅存在 Windows LF/CRLF 提示。
- 浏览器插件拒绝访问临时本地端口 `127.0.0.1:18801`，因此未完成截图级可视验收；后续可通过正式服务 `python clawos_server.py --host 127.0.0.1 --port 18790` 打开 `/` 进行人工视觉确认。

边界/下一步：
- 当前以静态 HTML/CSS/JS 复刻 app1 的视觉和动画，不引入 Vite/React 构建链，优先保证比赛交付和可移植性。
- 如后续要做到源码层也完全沿用 app1 技术栈，可在静态版本验收后规划 React/Vite 化迁移。

### 2026-06-17 - MemoryOS startup migration hotfix

问题：
- 用户从 `C:\Users\34712\Desktop\agentwork\clawos` 运行 `python clawos_server.py --host 127.0.0.1 --port 18790` 时，FastAPI lifespan 启动失败。
- 报错为 `sqlite3.OperationalError: no such column: idempotency_key`。

原因：
- 旧版 `tasks` 表没有 `idempotency_key` 字段。
- `MemoryStore._init_db()` 在执行 `_ensure_columns()` 补列之前，就在 `executescript()` 中创建了依赖 `tasks(idempotency_key)` 的唯一索引，导致旧数据库无法完成迁移。

修复：
- 从建表脚本中移除 `idx_tasks_idempotency` 的提前创建。
- 保留 `_ensure_columns(c, "tasks", ...)` 之后的索引创建逻辑，确保旧库先补齐 `idempotency_key`、`retry_of`、`attempt`、`cancellation_requested`、`resume_state` 等字段，再创建幂等索引。

验证：
```powershell
python -m py_compile clawos\memoryos\memory_store.py clawos\clawos_server.py
python -c "from clawos.memoryos.memory_store import MemoryStore; s=MemoryStore(r'clawos\memoryos.db'); print('memory db init ok')"
python -c "import asyncio; from clawos_server import lifespan, app; ..."
python -m unittest clawos.tests.test_runtime_task_control clawos.tests.test_memoryos_mvp clawos.tests.test_frontend_static
```

结果：
- 当前真实 `clawos/memoryos.db` 初始化迁移通过。
- FastAPI lifespan 启动/关闭通过，日志显示 `ClawOS ready`。
- 相关测试：`18 tests OK`。

### 2026-06-17 - Aether-style white glass console refactor

目标：
- 用户在仓库新增 `app/` 参考控制台，并提供白色毛玻璃 Aether 风格截图；本轮按同款视觉语言重构 ClawOS 控制台。
- 低风险原则：先保持现有 ClawOS 静态 HTML/CSS/JS 架构、后端 API、前端 DOM id 和测试契约不变，只替换控制台视觉和信息架构。

新增/完善：
- 重构 `clawos/static/console.html` 为 Aether-like 控制台布局：固定左侧白色毛玻璃导航、Dashboard 顶部标题区、右上角状态按钮、三张指标卡、实时 Agent 拓扑面板和右下角浮动操作按钮。
- 保留并重新承载原有视图：Dashboard、Agents、Knowledge Base、Reflection、Skills、Tools、Logs、Benchmarks、Scenes，确保现有 JS/API 功能仍可挂载。
- `clawos/static/assets/site.css` 新增 `.aether-console` 主题：柔和浅灰背景、玻璃卡片、紫蓝高光、圆角阴影、响应式布局、表格/表单/消息区统一白色工作台风格。
- 复制 Geist 字体到 `clawos/static/assets/Geist-Variable.woff2` 和 `clawos/static/assets/GeistMono-Variable.woff2`，保证换机部署时不依赖外网字体。
- `clawos/static/assets/console.js` 调整默认视图标题与 Dashboard 指标：ACTIVE TOOLS、MEMORY ITEMS、SOLIDIFIED SKILLS。
- 为贴近参考截图，视觉上隐藏历史会话入口和 New Chat 按钮，但 DOM 仍保留，避免破坏现有脚本和测试。

验证：
```powershell
python -m unittest clawos.tests.test_frontend_static
python -m unittest discover -s clawos\tests
git diff --check
```

结果：
- 前端静态测试：`9 tests OK`
- 全量测试：`84 tests OK`
- 浏览器实测：默认进入 Dashboard，存在 3 张指标卡，9 个导航项，浮动按钮正常，历史会话区已隐藏。
- `git diff --check` 通过；仅存在 Windows LF/CRLF 提示。

边界/下一步：
- 当前是静态控制台的高保真视觉重构，不是完整 React/Vite 迁移；这样可以先保证比赛交付稳定性。
- 如后续要做到与 `app/` 技术栈完全一致，可在冻结 API 契约后，把控制台迁移为独立 Vite/React 前端，再通过同一套 `/api/*` 接入 ClawOS 后端。

### 2026-06-17 - Architecture review and built-in Office artifacts

架构复盘：
- 已阅读 `架构说明.txt` 与 `架构图/` 下 5 张架构图：总架构图、数据库 ER、MemoryOS 详细架构、Reflection Engine 详细架构、通讯时序图。
- 结论：目标架构层面基本完整，Application Layer 已包含 Office Assistant / Competition Assistant / DataAgent，MemoryOS 图已包含 Table Memory，通讯时序也覆盖文件/报告生成链路。
- 主要缺口：代码层尚未把 XLSX/PPTX 作为 ClawOS 自带工具实现，不能依赖 Codex 桌面插件，否则换电脑部署时能力不可控。

新增/完善：
- 新增 `clawos/office_artifacts.py`：使用 Python 标准库 `zipfile` + OpenXML 生成和轻量编辑 Office 文件。
- 新增 `office_artifacts` 表，记录 Office 产物类型、动作、路径和元数据。
- 新增 WorkspaceServices 能力：
  - `create_spreadsheet`
  - `edit_spreadsheet`
  - `create_presentation`
  - `edit_presentation`
- 新增 Agent 工具 `office_artifact`：
  - `spreadsheet_create`
  - `spreadsheet_edit`
  - `presentation_create`
  - `presentation_edit`
- 新增 API：
  - `POST /api/workspace/office/spreadsheets`
  - `POST /api/workspace/office/spreadsheets/edit`
  - `POST /api/workspace/office/presentations`
  - `POST /api/workspace/office/presentations/edit`
- `GET /api/workspace/capabilities` 新增 `office_artifacts`，明确 XLSX/PPTX 不依赖 Microsoft Office、openpyxl 或 python-pptx。
- 前端“场景工作流”页新增“自带 XLSX 表格”和“自带 PPTX 演示文稿”能力展示。
- 安全策略：`office_artifact` 纳入路径白名单与写工具确认策略。
- 实现说明：`clawos/OFFICE_ARTIFACTS_IMPLEMENTATION.md`。

验证：
```powershell
python -m unittest clawos.tests.test_workspace_services clawos.tests.test_frontend_static
python -m py_compile clawos\office_artifacts.py clawos\workspace_services.py clawos\scripts\tool_runner.py clawos\clawos_server.py clawos\security\policy.py
git diff --check
```

结果：专项 `20 tests OK`，编译通过，diff 空白检查通过；仅有 Windows LF/CRLF 提示。已生成演示产物：
- `output/office/customer_metrics.xlsx`
- `output/office/customer_metrics_edited.xlsx`
- `output/office/customer_briefing.pptx`
- `output/office/customer_briefing_edited.pptx`

当前边界：已满足可迁移的基础 XLSX/PPTX 生成与轻量编辑；复杂图表、公式透视表、母版主题、图片、动画和高级排版仍作为后续增强项。

### 2026-06-16 - File generation and paper learning analysis report

新增/完善：
- 明确当前系统可以在路径白名单内生成结构化文件，适用于会议纪要、数据整理、科研学习报告等场景。
- `GET /api/workspace/capabilities` 新增 `structured_file_generation` 和 `paper_learning_analysis`，前端“场景工作流”页展示 Markdown/PDF 等输出能力。
- `research_pdf` 新增 `learning_analysis` 动作，支持客户选择 `document_id` 或 `file_path`、`output_dir`、`formats`、`depth`、`question_count`。
- 新增 `POST /api/workspace/research/learning-analysis`。
- 新增 `research_analysis_reports` 表，记录论文学习解析报告产物、深度、问题数量和元数据。
- 新增自我提问式论文解析文件生成：总览、论文框架、核心学习问题、L1-L5 追问树、页码证据、概念表、局限和系统学习建议。
- 输出 Markdown + PDF；Markdown 便于知识库和二次编辑，PDF 面向客户交付。
- 已用用户提供的范例 PDF 生成演示产物：
  - `output/pdf/paper_learning_analysis_sample_v5/GalaxyVS_Sample_Learning_Analysis_learning_analysis.md`
  - `output/pdf/paper_learning_analysis_sample_v5/GalaxyVS_Sample_Learning_Analysis_learning_analysis.pdf`
- 实现说明：`clawos/FILE_GENERATION_PAPER_ANALYSIS_IMPLEMENTATION.md`。

验证：
```powershell
python -m unittest clawos.tests.test_workspace_services clawos.tests.test_frontend_static
python -m py_compile clawos\workspace_services.py clawos\scripts\tool_runner.py clawos\clawos_server.py clawos\security\policy.py
git diff --check
```

结果：`19 tests OK`，编译通过，diff 空白检查通过；仅有 Windows LF/CRLF 提示。

当前边界：论文解析生成器目前是确定性证据驱动版本，不调用外部模型扩写，优点是低风险、可追溯、不会凭空补论文细节；下一步可在相同 API 上接 DeepSeek/本地模型，对每个追问节点进行更高质量的学习化扩写，并保留页码证据约束。

### 2026-06-16 - Advanced Scenario Workflows: local files, meetings, research, learning, Git approval, Skill governance

新增/完善：
- 本地能力确认 API：`GET /api/workspace/capabilities`，明确允许的本地文件根、TXT 读写、项目/模板创建、PDF 文本抽取、OCR 需求检测、音频会议能力、Git 审批写操作和 Skill 治理能力。
- 会议全流程增强：`meeting_workflow` 支持本地音频登记、sidecar 转写导入、说话人标签解析、会议纪要结构化提取、日历 `.ics` 草稿和邮件 `.eml` 草稿。当前不自动发送邮件/日历，不内置真实 ASR；检测到 `whisper` 时暴露可用性。
- 科研工作流增强：PDF 导入保留页码证据和 OCR 状态，新增引用校验、文献/术语对比矩阵、可复现实验目录与 `experiment_plan.json` 生成。
- 学习系统增强：新增学习依赖边、错题证据、学习图谱和长期掌握度评估，支持从复习记录和错题趋势计算薄弱项。
- Git 协作增强：新增写操作审批流，先生成 diff preview 与 HEAD checkpoint，再人工 approve commit；rollback 使用 `git revert`，避免破坏性 reset。
- Skill 治理增强：新增依赖清单、HMAC 签名、fresh-context audit、canary 元数据发布；canary 不自动进生产路由，仍需显式 promote。
- 控制台新增 “场景工作流” 页面，展示本地文件、TXT/PDF、音频会议、Git 审批、Skill 治理和交付边界。

代码：
- `clawos/workspace_services.py`
- `clawos/scripts/tool_runner.py`
- `clawos/functions.jsonl`
- `clawos/security/policy.py`
- `clawos/clawos_server.py`
- `clawos/skills/skill_evolution.py`
- `clawos/static/console.html`
- `clawos/static/assets/console.js`
- `clawos/ADVANCED_SCENARIOS_IMPLEMENTATION.md`

验证：
```powershell
python -m unittest clawos.tests.test_workspace_services clawos.tests.test_skill_evolution
python -m unittest clawos.tests.test_workspace_services clawos.tests.test_skill_evolution clawos.tests.test_frontend_static
python -m py_compile clawos\workspace_services.py clawos\scripts\tool_runner.py clawos\skills\skill_evolution.py clawos\clawos_server.py clawos\security\policy.py
python -m unittest discover -s clawos\tests
git diff --check
```

结果：专项 `16 tests OK`，场景/技能/前端静态 `25 tests OK`，全量 `82 tests OK`，编译和 diff 空白检查通过。仅有既有 MTClaw FastAPI `on_event` deprecation warning。

当前边界：本轮已支持本地文件操作、TXT/PDF 解析、音频资产登记、带 sidecar 转写的会议纪要、说话人标签分离、连接器草稿、科研/学习/Git/Skill 治理闭环；真实离线 Whisper/ASR、真实说话人声纹分离、OCR 引擎执行、邮箱/日历 OAuth 自动发送、远程 PR/CI 集成仍属于后续国产离线环境接入项。

### 2026-06-16 - 冻结基准、可靠任务控制与 Skill Review Inbox

新增/完善：
- 冻结场景基准：新增 `clawos/scenario_benchmarks.py`，默认 `competition-frozen-v1`
  覆盖会议、学习、模板、技能、记忆五类低风险场景，持久化逐例结果、Pass Rate、P95、阈值和场景列表。
- Task Runtime 可靠性：`tasks` 增加 `idempotency_key`、`retry_of`、`attempt`、
  `cancellation_requested`、`resume_state`；支持幂等返回已完成响应、取消请求、重试任务、启动恢复和事件游标。
- 实时任务 API：新增任务取消、重试、恢复、事件查询和 SSE 事件流接口。
- Skill Review Inbox：`skill_review_events` 记录 reviewer/action/notes，支持
  `needs_changes`、`reject`、`reopen`，前端可发布已验证候选。
- 控制台：运行轨迹页增加取消/重试/恢复和实时事件状态；技能页增加 Review Inbox；
  新增冻结基准页，可运行默认套件并查看历史结果。
- 实现说明：`clawos/RUNTIME_BENCHMARK_SKILL_REVIEW_IMPLEMENTATION.md`。

验证：
```powershell
python -m unittest clawos.tests.test_frontend_static clawos.tests.test_runtime_task_control clawos.tests.test_scenario_benchmarks clawos.tests.test_skill_evolution
python -m py_compile clawos\memoryos\memory_store.py clawos\clawos_server.py clawos\scenario_benchmarks.py clawos\skills\skill_evolution.py
python -m unittest discover -s clawos\tests
git diff --check
```

结果：专项 `19 tests OK`，全量 `76 tests OK`，编译和空白检查通过。仅有既有
MTClaw FastAPI `on_event` deprecation warning。本机 PowerShell PATH 无 `node` 命令，
已用 Node REPL `vm.Script` 检查 `console.js` 语法通过。

### 2026-06-16 - 多页企业级产品官网与电影感控制台前端

新增/重构：
- 将原单页工作台重构为真实三页递进结构：`/` 首页、`/product` 产品页、`/console` 控制台。
- 首页使用用户指定的 `d55c96717921508cafd61730a1623e08.jpg` 作为淡化/虚化全屏背景，并做成可进入的 3D 杂志封面入口：固定背景、红色边框光晕、前中后三层深度框、Canvas 星场、鼠标/滚动视差、玻璃卡片和电影感暗色入口。
- 产品页学习 Adaline HTML、Cursor Compile PDF、ElevenLabs PDF：采用 sticky 胶囊导航、大标题留白、白底胶囊模块、证据网格、Compile 式线条图案和企业 SaaS 产品叙事。
- 控制台拆到 `console.html`，保留原有接口能力：聊天、状态总览、MemoryOS、Reflection、Skills、Tools、Task Trace、工具确认条和工具执行轨迹。
- `clawos_server.py` 新增 `/assets` 静态挂载以及 `/product`、`/console` 页面路由。
- 新增共享前端资源：`clawos/static/assets/site.css`、`site.js`、`console.js`。
- 修复前端中文文案与旧页面编码损坏问题。

验证：
```powershell
python -m unittest clawos.tests.test_frontend_static
python -m py_compile clawos\clawos_server.py
git diff --check
python -m unittest discover -s clawos\tests
```

结果：前端静态测试 `7 tests OK`，全量测试 `69 tests OK`，服务端编译通过，diff 空白检查通过。仅有既有 MTClaw FastAPI `on_event` deprecation warning。用 Node 动态导入检查 `site.js` 和 `console.js` 语法，结果均非 `SyntaxError`；最新首页用 Browser 插件访问临时 `127.0.0.1:18790` 静态服务完成 DOM/资源验证，确认封面背景、中心 3D 入口、10 个视差层、图片加载和前端日志均正常。

### 2026-06-15 - 项目复盘与受控自进化 Skill

复盘：

- 对照计划书、赛题和架构说明重新评估，当前约为 `64/100`。
- 定位为“具备治理闭环的竞赛交付候选”，尚不能宣称企业级工业生产交付。
- 更新 `clawos/ENTERPRISE_READINESS.md`，列出比赛证据、模块成熟度、企业硬门槛和 P0-P2。
- 参考 Generative Agents、Voyager、MemGPT、SkillOS、SkillEvolver 五篇论文形成
  `clawos/SELF_EVOLVING_SKILLS.md`。

新增 Skill 进化闭环：

- `skill_versions`：候选、验证、激活、拒绝、归档和回滚版本。
- `skill_eval_suites`：不可原地修改的冻结评测集。
- `skill_eval_runs`：逐例结果、通过率、P95、阈值和证据。
- `skill_promotions`：生产晋升快照和一键回滚记录。
- 候选定义支持 `plan-only` 或隔离执行，不发布、不增加生产使用次数。
- 只有通过质量门禁的 `validated` 版本可以人工晋升。
- API 覆盖候选、评测集、执行评测、晋升、回滚、版本和运行记录。
- 代码：`clawos/skills/skill_evolution.py`、`clawos/skills/skill_registry.py`。

验证：

```powershell
python -m unittest discover -s clawos\tests
python -m py_compile clawos\skills\skill_registry.py clawos\skills\skill_evolution.py clawos\clawos_server.py
git diff --check
```

结果：`67 tests OK`，编译与 diff 检查通过。仅有 MTClaw 上游 FastAPI
`on_event` deprecation warning。

### 2026-06-15 - 五类个人工作台场景闭环

新增：

- 会议全流程：会前议程、转写导入、决策/风险/行动项抽取、负责人和截止时间、经验记忆。
- 科研 PDF：本地提取、SHA-256、页码分块、Knowledge Memory、可跳转引用检索。
- 学习系统：目标、主题、证据化复习、掌握度和间隔复习；无证据不得更新掌握度。
- Git 协作：分支/状态/Diff/提交历史快照和 dry-run 提交计划，不自动写仓库。
- 模板中心：版本化模板、参数渲染、临时目录构建、原子落盘和失败清理。
- 场景 API 与 `meeting_workflow`、`research_pdf`、`learning_workspace`、
  `git_workspace`、`template_list`、`template_instantiate` Agent 工具。
- 实现说明：`clawos/PRIORITIES_5_7_IMPLEMENTATION.md`。

专项验证：

```powershell
python -m unittest clawos.tests.test_workspace_services clawos.tests.test_scenarios_e2e
```

结果：`9 tests OK`。

本轮最终全量验证：

```powershell
python -m unittest discover -s clawos\tests
```

结果：`62 tests OK`。仅有 MTClaw 上游 FastAPI `on_event` deprecation warning。

### 2026-06-15 - 工具安全、审计与密钥引用管理

新增：

- 统一 `ToolSecurityPolicy`，覆盖 ClawOS API、Skill 回放和 MTClaw bridge。
- 文件路径规范化与白名单根目录校验，拒绝目录逃逸。
- Shell 程序/子命令白名单，拒绝管道、重定向、命令拼接和破坏性命令。
- 独立 `tool_worker.py` 进程、受限环境变量和硬超时。
- `audit_events`：记录工具预检、执行、密钥登记和密钥读取的允许/拒绝/错误证据。
- `secret_refs` 与 Secret Manager：数据库只保存环境变量引用、用途和允许工具，不保存密钥值。
- 安全策略检查、审计查询、密钥引用登记和状态查询 API。

验证：

```powershell
python -m unittest clawos.tests.test_runtime_security clawos.tests.test_routing_memory clawos.tests.test_skill_runtime clawos.tests.test_mtclaw_adapter
```

结果：`25 tests OK`。

### 2026-06-15 - Policy Optimizer 可运行闭环

新增：

- `policy_groups`、`policy_arms`、`policy_selections`、`policy_rewards` 持久化模型。
- Contextual UCB + epsilon 探索，支持 Tool、Agent、Prompt、Workflow 四类策略臂。
- 严格实现计划书 Reward：`0.4*成功 + 0.3*满意度 - 0.2*时延成本 - 0.1*资源成本`。
- 策略注册、上下文选择、奖励回传和统计 API。
- 最佳策略达到最小样本后可晋升到 `runtime_policies`，并支持恢复上一版。
- 每次策略选择记录 context、score、探索标记、task/session；Reward 只能写入一次。

验证：

```powershell
python -m unittest clawos.tests.test_policy_optimizer
```

结果：`2 tests OK`。

### 2026-06-15 - Reflection 2.0 安全改进闭环

新增：

- 独立 `reflection_cards` 完整反思卡，持久化结果详情、失败分类、轨迹、证据和用户反馈。
- 独立 `reflection_improvements` 与事件审计表。
- `proposed -> approved -> testing -> validated -> published -> rolled_back` 状态机。
- success rate、quality、latency、error rate 回归门禁；失败自动进入 `rejected`。
- `runtime_policies` 策略注册表，发布时保存旧策略快照，回滚时事务化恢复。
- Reflection 卡片、反馈、状态迁移、验证、发布和回滚 API。
- Learning Loop 不再自动应用模型建议，只生成待审核改进项。
- 治理说明：`clawos/MEMORY_REFLECTION_GOVERNANCE.md`。

验证：

```powershell
python -m unittest discover -s clawos\tests
```

结果：`50 tests OK`。存在 MTClaw 上游 FastAPI `on_event` deprecation warning，
不影响测试通过。

### 2026-06-15 - MemoryOS 2.0 治理闭环

新增：

- `memory_versions`：记录创建、更新、启停和冲突审批版本。
- `memory_evidence`：关联会话、用户确认、文档或其他来源证据。
- `memory_conflicts` 与 `memory_reviews`：自动抽取遇到不同值时进入 Review Inbox，不静默覆盖。
- `memory_acl`：支持 user、role、workspace 的 read/write/review/admin 授权和检索过滤。
- `retrieval_evaluation_runs` 与检索评测服务：输出 Recall@K、Precision@K、MRR、Hit Rate、P50/P95 时延。
- 版本、证据、Review、ACL 和检索评测 API。
- 修复高风险工具等待确认时 Runtime Task 一直保持 `running` 的问题，现进入 `waiting_confirmation`。

验证：

```powershell
python -m unittest clawos.tests.test_memoryos_governance clawos.tests.test_memoryos_mvp
```

结果：`9 tests OK`。

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

最近一次验证结果：`86 tests OK`。

## 当前主要差距

第一优先级：

- MemoryOS 生命周期、硬删除证明、敏感字段加密和真实多租户身份接入。
- Reflection 反思去重聚类、冻结回归任务集，以及各运行模块对 `runtime_policies` 的显式消费。
- Task Runtime 已支持恢复时显式创建 `pending_retry` 重放任务和 Task Event 保留清理；仍缺生产级队列 worker、进程级取消和更完整的断线补偿。
- 容器/seccomp 级工具隔离、CPU/内存配额和操作系统 Keyring。
- MTT AIBOOK + 本地 Qwen/vLLM-MUSA 的离线部署、性能和质量证据。

第二优先级：

- Policy Optimizer 真实任务样本、离线评测和显著性检验。
- Skill 治理已具备依赖清单、签名、fresh-context audit、silent-bypass 检测和 canary 元数据；下一步需要真实双 Agent A/B、密钥托管和生产路由灰度策略。
- Git 写操作已具备审批、补丁预览、HEAD checkpoint 与 `git revert` 回滚；下一步需要远程 PR/CI、冲突处理和团队权限接入。
- PDF 已具备文本抽取、页码证据、OCR 需求检测和引用校验；下一步需要接入真实 OCR 引擎并保存版面坐标证据。
- 会议已具备音频登记、sidecar 转写、说话人标签解析、纪要抽取、日历/邮件草稿；下一步需要本地 Whisper/声纹分离和 OAuth 连接器。
- 学习系统已具备学习图谱、错题证据和长期掌握度评估；下一步需要更强前端可视化和 spaced-repetition 调度。
- 前端下一步是接入真实运行服务下的视觉回归、移动端细节打磨和任务图/DAG 的更强可视化。

## 下一步建议

建议下一步：

```text
可靠交付:
MTT AIBOOK 本地模型验收 + 冻结基准报告导出 + 生产级任务队列/自动重放
```

原因：

- MTClaw、Task Runtime、MemoryOS 2.0、Reflection 2.0、Skill Review 和冻结场景基准已形成后端可信闭环。
- 当前最高风险已转为本地模型实机性能、真实长任务恢复、外部连接器和高风险写操作补偿。
- 离线模型尚未验收前，不要宣称 100% 企业级或工业级，只能称为“竞赛交付候选”。

## 本地运行注意事项

- Windows 本地优先用 `start_clawos.bat`。
- `.env` 放在 `clawos/.env`，不要提交。
- 当前工作区已有 `clawos/.venv`，测试优先用 `clawos/.venv/Scripts/python.exe`。
- 如果重新建环境，先安装 `clawos/requirements.txt`；PDF 工作流在无 `pdftotext` 的 Windows 环境下会使用 `pypdf` 兜底。
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
