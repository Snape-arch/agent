# Project Context

## 2026-07-11 - 控制台全视图 Clean UI 重构

Completed:

- 根据工作台、运行轨迹、搜索与知识库四张真实截图，确认旧玻璃样式通过高特异度 selector 污染所有控制台视图；不再逐页补丁，新增最终加载的 `console.clean.css` 作为统一渲染契约。
- 全局清除 workspace/panel/dashboard/knowledge/ops/scenes 斜切伪层、按钮高光、深色背景、白字继承、玻璃阴影和 backdrop filter。
- 对动态 runtime records、failure library、搜索结果、知识库多模式、项目、会议/场景、技能、权限、运维、抽屉和模型设置建立同一套暖白/墨黑/钴蓝组件规范。
- 统一 auto-height 文档流、局部表格横向滚动、grid `min-width:0`、媒体限宽和 1100/900/760/480 响应式收束，避免全页遮挡与横向溢出。
- 保留原有功能和 DOM/JS 接口；首页、产品、Academy 跳转以及移动端侧栏入口继续可用。

Verification:

- bundled Node syntax check passed.
- frontend static suite: 36 tests OK.
- full suite: 258 tests OK, 1 skipped.
- `git diff --check`: passed.

Known notes:

- 四张截图是修复前证据；应用内浏览器无法访问宿主机 loopback，因此修复后最终截图仍需用户刷新补充，`design-qa.md` 保持 blocked 而不冒充视觉验收通过。
- `clawos/skills/skill_registry.jsonl`、`clawos/output/` 与 `tmp/` 不纳入提交。

Recommended next step:

- 强制刷新 `/console` 并依次检查工作台、任务、搜索、知识库；补一组修复后截图即可完成最终视觉签收。

## 2026-07-11 - 控制台视觉冲突与遮挡整改

Completed:

- 根据用户实际截图定位并清除旧深色 workspace 伪层、按钮高光、红黄绿窗口装饰与新明亮工作台的样式串层。
- 将 composer 从页面底部 sticky 浮层移动到任务意图面板内部，消除对交付表格的遮挡；输入、附件、联网搜索、发送和停止能力保持不变。
- 顶部恢复首页、产品与 AI Academy 跳转；窄屏在侧栏提供同等入口。
- 增加截图故障回归契约：全页只有一个 composer/prompt，工作台无旧伪层，输入区为普通文档流，产品链接完整。

Verification:

- bundled Node `--check clawos/static/assets/console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: 36 tests OK.
- `cd clawos && python -m unittest discover -s tests`: 258 tests OK, 1 skipped.
- `git diff --check`: passed.

Known notes:

- 用户截图作为修复前浏览器证据；应用内浏览器仍无法访问宿主机 loopback，修复后截图需要用户刷新页面补充，因此 `design-qa.md` 继续如实标为 blocked。
- `clawos/skills/skill_registry.jsonl`、`clawos/output/` 与 `tmp/` 仍不纳入提交。

Recommended next step:

- 用户强制刷新 `/console` 后补一张同视口截图；若无残留遮挡，将 `design-qa.md` 更新为 passed。

## 2026-07-11 - 控制台冠军向任务工作台重构

Completed:

- 依据 Product Design 审计与用户选定的方案 1+3，控制台从三层导航和深色玻璃后台重构为单一明亮任务工作台；后台治理能力收束到次级抽屉。
- 工作台首屏统一暴露目标输入、Coding/会议/数据分析/论文精读快捷入口、真实任务进度、自主执行级别、办公交付质量预览和 subagent 角色状态。
- `/api/tasks` 结果会动态渲染到工作台；无任务时显示诚实空态。自主级别具备 `aria-pressed` 与本地持久化。
- 将每次导航触发的全量后台刷新改为按视图加载，保留原有全部后台页面与功能入口。
- 新增统一暖白/墨黑/钴蓝视觉 tokens、清晰选中态、低阴影、响应式断点和数据表横向保护；移除核心工作面的机器人/HUD/重复导航表达。

Verification:

- bundled Node `--check clawos/static/assets/console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: 35 tests OK.
- `cd clawos && python -m unittest discover -s tests`: 257 tests OK, 1 skipped.
- 本地 HTTP `/console` 与 `/health` 返回 200；应用内浏览器因 loopback 隔离返回 `ERR_CONNECTION_REFUSED`，因此 `design-qa.md` 如实记录视觉 QA blocked，未冒充浏览器验收通过。

Known notes:

- `clawos/skills/skill_registry.jsonl` 的既有工作树状态、`clawos/output/` 与 `tmp/` 未纳入本次提交。
- 交付中心当前明确标注为示例布局；真实任务进度已接入，统一 artifact 列表后续可再接真实交付记录。

Recommended next step:

- 在可访问本机 loopback 的浏览器中以 1440×1024 打开 `/console`，对照选定 mock 完成最后一轮截图比较并把 `design-qa.md` 从 blocked 更新为 passed；随后再接统一 artifact API 替换交付示例。

## 2026-07-11 - 办公视觉质量与高级数据分析闭环

Completed:

- 新增 `OfficeVisualQualityService`，对 DOCX/PPTX/XLSX/PDF 输出统一机器可读质量门禁；支持 PDF/LibreOffice 渲染入口、PPTX 越界/文本框重叠/最小字号、XLSX 公式错误/格式/筛选/冻结窗格/图表、DOCX 语义样式/长表重复表头/中英文混排及模板样式保留检查。
- 升级办公生成质量：DOCX 使用明确层级、页边距、页脚和重复表头；PPTX 使用固定画布、30pt 标题和 20pt 正文；XLSX 使用表格、筛选、冻结窗格、语义格式、公式和图表；PDF 嵌入本地 CJK 字体并使用专用表头样式。
- 新增高级数据分析：数值概况、分组汇总、相关性、公式驱动 Summary/Group Analysis 工作表和分析图；验收工作簿含 20 个可审计公式、3 个筛选/冻结工作表和 1 张图。
- 自治 subagent 新增 `advanced_data_analysis` 四角色团队（剖析、分析、工作簿、独立质检），并增加输出契约验证与定向 JSON repair 重试。
- 新增 `office_visual_data_acceptance.py` 和冻结结果，覆盖中英文混排、80 行跨页长表、模板保真、PDF 真渲染、PPTX 越界、XLSX 高级分析、OCR PDF 拒绝和数据团队配置。

Verification:

- bundled Office runtime 定向测试：11 tests OK。
- 系统运行时相关回归：38 tests OK，1 skipped（系统 Python 缺专业 Office 依赖；同项已在 bundled runtime 通过）。
- 全量：256 tests OK，1 skipped。
- 办公视觉/数据验收：7/7 checks passed。
- PDF 三页 Poppler 真渲染并逐页目视复查；首轮发现 CJK 方块字、第二轮发现表头对比不足，修复后最终复查无缺字、裁切、重叠或分页缺陷。
- 架构门禁 95/100；MTClaw 垂直合同 7/7 passed。

Known notes:

- 本机没有 LibreOffice，因此 DOCX/PPTX/XLSX 报告为 `structural_only`，没有冒充真渲染视觉通过；在装有 LibreOffice/WPS 转换能力的比赛环境应使用 `strict_visual=true` 重跑。
- OCR PDF 当前实现检测并阻止无文本层文件通过；真正 OCR 识别仍依赖后续接入 Tesseract/PaddleOCR 或现有 OCR worker。
- 这套能力接近高质量自动化办公生成/编辑与验收，不等同于完整 WPS 桌面交互编辑器内核。

Recommended next step:

- 在目标环境安装 LibreOffice 或接入 WPS 可自动化渲染接口，对 DOCX/PPTX/XLSX 全部执行逐页/逐幻灯片/逐工作表截图验收；补真实复杂企业模板、多图表仪表板、透视表、OCR 识别和 100+ 文件批量回归。

## 2026-07-11 - Coding、办公与自治 Subagent 闭环

Completed:

- 新增受确认门禁保护的 coding 完整循环：仓库检查、计划、范围化修改、测试、有限修复重试、diff 评审、checkpoint、失败恢复和人工 change request；服务本身不自动 commit/push。
- 新增统一办公生产力服务，覆盖 DOCX/XLSX/PPTX/PDF/MD/TXT/JSON/CSV/EML/ICS 的创建、编辑、检查和质量门禁，并打通会议包、邮件草稿/发送、日历草稿/发布、幂等和审计。
- 新增模型驱动自治 subagent 编排：隔离角色上下文、依赖 DAG、并发、token/时间/模型/工具预算、最小工具权限、副作用确认、checkpoint/resume、证据汇总和硬门禁仲裁。
- 将 coding 的 inspect/plan 与 office 的 inspect 作为低风险能力接入 MTClaw；写操作继续由 ClawOS 显式确认执行。
- 新增确定性与 live-model 验收制品，以及 `clawos/CODING_OFFICE_SUBAGENT_ENTERPRISE_ACCEPTANCE_2026-07-11.md` 产业评分报告。

Verification:

- `python -m unittest discover -s tests`: 254 tests OK。
- `python scripts\run_mtclaw_vertical_acceptance.py`: 7/7 passed，P95 0.056 ms（离线合同延迟）。
- `python scripts\validate_competition_architecture.py`: 95/100，competition architecture ready=true；缺 upstream identity，enterprise release ready=false。
- `python scripts\coding_office_subagent_acceptance.py --out benchmarks\coding_office_subagent_acceptance_deterministic_2026-07-11.json`: 三项闭环全部通过。

Known notes:

- 2026-07-10 live Qwen subagent 验收真实调用了 Qwen，但硬门禁失败；报告保留为失败证据，未计为通过。
- 当前未具备 MTT AIBOOK 实机、真实 ASR 音频集或企业邮件/日历测试租户条件；这些均为外部验收门禁。
- FastAPI `on_event`、Chroma telemetry 和 Python 3.14 asyncio 产生非阻塞弃用警告。

Recommended next step:

- 在目标实机重复全量、MTClaw 和 live-model 验收；用真实会议音频与测试邮件/日历租户补齐质量、延迟、资源、回执和长稳证据；由项目方补 MTClaw 原始 upstream URL/SHA。

这个文件是 ClawOS 的协作交接入口。下一位 Codex 或协作者应先读这里，再按需读具体模块，避免重新扫描整个仓库。

## 维护规则

- 每次完成一个有意义的开发块，都更新“最近完成”。
- 状态、风险、验证结果或下一步变化时，直接更新对应章节。
- 不记录 API Key、token、密码、私有密钥或 `.env` 内容。
- 不写夸大表述；除非有逐项证据，不使用“生产级”“企业级”等措辞。

## 当前状态

- 当前分支：`master`
- 远程仓库：`https://github.com/Snape-arch/agent.git`
- 当前提交：以 `git log -1 --oneline` 为准；2026-07-10 已完成比赛架构与 MTClaw 垂直路由闭环。
- 当前定位：Windows 本地个人 Agent OS 原型的 MVP+ 收束版。
- 当前目标：可交接、可启动、可验收、可演示。
- Windows 双服务入口：根目录 `start_clawos.bat`
- 控制台入口：`http://127.0.0.1:18790/console`

## 接手顺序

1. 读 `PROJECT_CONTEXT.md`。
2. 读 `PROJECT_ROADMAP.md`，确认产品定位、主场景和优先级。
3. 读根目录 `README.md` 的启动、验收和交付章节。
4. 需要看 MTClaw 时读 `clawos/MTCLAW_INTEGRATION.md`。
5. 需要改前端时读 `clawos/static/console.html`、`clawos/static/assets/console.js`、`clawos/static/assets/site.css`。
6. 需要改后端时优先定位 `clawos/clawos_server.py`、`clawos/memoryos/`、`clawos/scripts/` 中对应模块。

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
- Task Runtime 已有单进程后台 worker、恢复、取消、重试和真实业务 job 接入；仍缺分布式调度、资源配额、补偿事务和故障注入验收。
- 身份、RBAC、Keyring、可观测性和长期审计导出仍是后续方向；备份恢复和迁移已有本地 API/UI 闭环。

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

### 2026-07-10 - 论文与知识库垂直场景闭环

Completed:

- 新增 `PaperIntelligenceService`：方法/实验/发现/局限结构化抽取，表格、公式、参考文献提取，claim-to-citation 对齐、90% 证据门禁及跨论文矛盾候选。
- 新增 Crossref/OpenAlex/Semantic Scholar 多源检索、Unpaywall DOI 开放获取解析和严格 OA PDF 下载；包含公网 HTTPS、开放获取来源、MIME、PDF 魔数、大小、SHA-256 和原子写入校验。
- 新增 API、function router 与 Paper Studio 可视入口；`paper_intelligence` 以只读动作进入 MTClaw，联网搜索/下载继续要求 ClawOS 确认。
- 新增两个冻结金标集和两个验收 runner。真实本地 Qwen3 embedding/reranker 检索验收已通过。

Verification:

- `python clawos/scripts/evaluate_paper_intelligence.py`: score `100.0`, all gates passed（2 篇/10 claims 的有限回归集）。
- `python clawos/scripts/benchmark_paper_retrieval.py`: 12 cases，embedding Recall@3 `1.0`、MRR `0.9583`；reranker Hit@1/MRR `1.0`。
- 真实网络：Crossref/OpenAlex 检索成功；Semantic Scholar 429 被隔离；真实 OA PDF 下载 `771621` bytes、MIME/PDF/哈希校验通过。
- 阶段一综合评分 `92/100`，详见 `clawos/PAPER_KNOWLEDGE_ENTERPRISE_ACCEPTANCE_2026-07-10.md`。

Remaining external gates:

- 目标比赛设备上的容量、延迟和 24 小时长稳验收。
- 500+ 真实论文、1 万+ 领域盲标 claims 的分层精度验收。
- Semantic Scholar 429/5xx 指数退避、熔断和生产监控。

### 2026-06-18 - Console CSS module and knowledge/RAG IA cleanup

Completed:
- Reviewed current teammate baseline: branch `master` is aligned with `origin/master`; latest commit is `e22b675 收束 ClawOS Windows MVP 验收闭环`.
- Moved chat-first console override rules out of `clawos/static/assets/site.css` into dedicated `clawos/static/assets/console.css`; `console.html` now loads it after the shared stylesheet.
- Reworked console IA so sidebar `库` is now user-owned `知识库` for RAG documents, notes, papers, blog drafts, and project material. System MemoryOS governance moved into the More drawer as `记忆治理`.
- Added knowledge library UI with save/search, category tabs, conversation-to-document draft action, and a lightweight topology map.
- Added `/api/knowledge`, `/api/knowledge/search`, and `POST /api/knowledge`, backed by existing MemoryOS `knowledge` storage and vector refresh.
- Improved session history labels: `/api/sessions` now returns compact `title/topic/tags` derived from early turns, so history is not just arbitrary last-message text.

Verification:
```powershell
python -m py_compile clawos\clawos_server.py clawos\memoryos\memory_store.py
node --check clawos/static/assets/console.js
python -m unittest clawos.tests.test_frontend_static clawos.tests.test_memoryos_mvp
python -m unittest discover -s clawos\tests
```

Result:
- Targeted tests: `20 tests OK`.
- Full suite: `107 tests OK`.
- Browser validation passed on `http://127.0.0.1:18790/console`: default chat, dedicated `console.css`, sidebar Knowledge, More drawer, Memory governance entry, file picker, and knowledge topology DOM all verified.

Known notes:
- The local `.venv` is absent on this machine. Browser verification used the bundled Codex Python runtime to start `clawos_server.py`.
- Full tests mutate `dev_health_check` usage stats; the registry line was restored after validation so the working tree contains only intentional source/UI/test changes.

### 2026-06-19 - Knowledge library management and console liveliness pass

Completed:
- Upgraded the user knowledge library from a surface-level RAG tab into managed modules: research, learning, writing, and project libraries now filter and store real categorized knowledge items.
- Added a dedicated upload area in the knowledge view. Text-like local files can be imported into the active library and then searched, edited, deleted, sent back into chat, and reflected in the topology map.
- Replaced the vague "current conversation" document action with an explicit history-session picker. Users choose a past session, generate a document draft, edit it, and save it into the selected knowledge module.
- Added knowledge CRUD backend support with `PUT /api/knowledge/{knowledge_id}` and `DELETE /api/knowledge/{knowledge_id}`, plus MemoryOS update/delete methods and vector-store refresh.
- Made the knowledge topology module-aware: the active library is the center node and imported/saved items become per-module map nodes instead of a decorative static graph.
- Loosened overly fixed console layout rules: main content now scrolls, panel views can grow naturally, and knowledge toolbar/drop zones have responsive layout so content is less likely to overflow fixed boxes.
- Updated frontend/static and MemoryOS tests to cover upload/session-picker DOM, knowledge editor state, CRUD lifecycle, and knowledge topology wiring.

Verification:
```powershell
node --check clawos/static/assets/console.js
python -m py_compile clawos\clawos_server.py clawos\memoryos\memory_store.py
python -m unittest clawos.tests.test_frontend_static clawos.tests.test_memoryos_mvp
python -m unittest discover -s clawos\tests
```

Result:
- Targeted tests: `20 tests OK`.
- Full suite: `107 tests OK`.
- Browser validation passed on `http://127.0.0.1:18790/console`: knowledge upload picker, session picker, active category switching, scrollable layout rules, and topology nodes were verified in the in-app browser.
- API CRUD smoke test passed: create, update, search, and delete worked against the running local server.

Known notes:
- Keep using `http://127.0.0.1:18790/console` for API-backed console testing. Opening `static/console.html` through `file://` can show layout but cannot fully exercise server APIs.
- The local `.venv` is still absent on this machine; validation used the available `python` runtime that had the required dependencies.
- FastAPI emits non-blocking `on_event` deprecation warnings during the full test suite.

Recommended next step:
- Connect imported knowledge items to real document parsing/chunking for PDF/DOCX and add persisted graph edges based on extracted entities/citations, so the topology becomes analytical rather than only item-level.

### 2026-06-19 - Console overflow safety fix

Completed:
- Added an overflow safety layer to `clawos/static/assets/console.css` so dense console surfaces remain reachable when content exceeds the visible area.
- Knowledge library panels, knowledge item sections, tables, topology area, settings modal, and more drawer now use auto scrolling instead of clipping content below the fold.
- Added thin scrollbar styling and regression assertions in `clawos/tests/test_frontend_static.py`.

Verification:
- `python -m unittest clawos.tests.test_frontend_static`: `12 tests OK`.

Known note:
- Local Node Playwright could not launch because the Chromium binary is missing in `C:\Users\34712\AppData\Local\ms-playwright`; use the in-app browser/manual visual check or install Playwright browsers for screenshot QA.

### 2026-06-19 - Chat attachment context behavior

Completed:
- Changed chat file upload from "paste file text into the prompt box" to an attachment tray model.
- The `+` button now shows loading/ready file chips with a spinner and remove action; the prompt remains clean.
- Frontend sends files as `clawos_attachments` with the chat request. The user-visible chat bubble only shows the message plus attachment names.
- Backend converts attachments into hidden context for routing/model/tool use, while MemoryOS stores only the user's original message, not the full uploaded file text.
- Confirmation retries preserve the attachment context.

Verification:
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js` passed.
- `python -m py_compile clawos\clawos_server.py` passed.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_routing_memory`: `27 tests OK`.

Known note:
- Current attachment reading is text-based in the browser. Binary/PDF/DOCX should be routed through a real upload/parsing endpoint next, so large or non-text files can be chunked, indexed, and cited instead of loaded client-side.

### 2026-06-19 - Real document upload, parsing, chunking, and RAG closure

Completed:
- Added `clawos/memoryos/document_ingestion.py` as the unified document ingestion service.
- Added server-side upload parsing for txt/md/csv/json/html, PDF via `pdftotext` or `pypdf`, and DOCX via OpenXML extraction.
- Added MemoryOS `documents` and `document_chunks` tables plus document list/chunk/search methods.
- Added `/api/documents/upload`, `/api/documents`, `/api/documents/{id}/chunks`, and `/api/documents/search`.
- Upload now stores original files under `clawos/uploads`, extracts text, chunks content, persists citations like `doc:N#chunk=M`, creates knowledge entries for each chunk, and refreshes the vector index.
- Chat attachments now upload via `FormData` and keep only `document_id` metadata on the frontend. The chat request asks the backend to retrieve relevant chunks as hidden RAG context instead of sending raw file text from the browser.
- Knowledge library upload now uses the same backend ingestion path, so files become managed documents, indexed chunks, knowledge entries, and topology/search inputs.
- Duplicate uploads by file hash reuse the same document id and clear old chunk-derived knowledge before re-indexing.

Verification:
- `python -m py_compile clawos\clawos_server.py clawos\memoryos\memory_store.py clawos\memoryos\document_ingestion.py` passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js` passed.
- Targeted tests: `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_memoryos_mvp clawos.tests.test_routing_memory`: `37 tests OK`.
- Full suite: `python -m unittest discover -s clawos\tests`: `111 tests OK`.
- API smoke with FastAPI TestClient passed: multipart upload to `/api/documents/upload` returned one document and `/api/documents/{id}/chunks` returned four chunks.

Known notes:
- PDF text extraction depends on local `pdftotext` or Python `pypdf`. OCR-only scanned PDFs are detected as low/empty text and should later route to an OCR worker.
- Current vector search is the existing lightweight in-memory hash embedding. It is closed-loop and offline, but a competition final could swap it for stronger embeddings while keeping the same document/chunk API.

### 2026-06-19 - Web fetch capability verification

Completed:
- Confirmed existing `web_search` is registered and implemented through DuckDuckGo HTML, but it is not yet robust enough to call enterprise-grade because parser/source reliability is weak.
- Added `web_fetch` tool to `functions.jsonl` and `tool_runner.py`.
- `web_fetch` accepts a public http(s) URL, performs a real GET, follows redirects, strips HTML, returns title, cleaned text excerpt, links, status code, content type, and final URL.
- Console capability panel now displays `联网搜索/网页抓取`.

Verification:
- `python -m py_compile clawos\scripts\tool_runner.py` passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js` passed.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_routing_memory`: `28 tests OK`.
- Full suite: `python -m unittest discover -s clawos\tests`: `111 tests OK`.
- Real network smoke with elevated network permission: `web_fetch https://example.com` succeeded with title `Example Domain` and non-empty cleaned text.

Known notes:
- In the normal sandbox, outbound socket access is blocked, so web tools need a runtime/network policy that permits outbound HTTP(S).
- `web_search` should be upgraded to a provider abstraction with at least two search backends, source URLs, snippets, rank, error classification, and tests with mocked HTML/API responses.

### 2026-06-20 - Enterprise web, risk, routing, and health closure

Completed:
- Upgraded `web_search` to provider fallback order: Tavily, SerpAPI, Bing, DuckDuckGo. Results now use a normalized shape with `title`, `url`, `snippet`, `source`, `published_at`, `rank`, and `error_type`; failures include provider attempts and classified errors.
- Extended `web_fetch` with `ingest=true` and `category`. Fetching a page can now save HTML under `clawos/uploads/web`, run through the same document ingestion service, create chunks, citations, knowledge entries, and refresh the vector index.
- Added unified risk policy output for network tools, shell, writes, Git workspace operations, and external API-like tools. Policy now returns `risk_level` and `decision`, and `execute_tool_call` uses policy `confirm` decisions for the same confirmation bar path as existing high-risk tools.
- Added URL policy for `web_fetch`: only public http(s), blocks local/private network URLs.
- Tool execution envelopes and audit details now include `risk_level`.
- Added `/api/model/health` with primary/fallback model visibility and optional probe, plus ordered provider fallback for routing/upstream calls when `routing_fallbacks`, `upstream_fallbacks`, or `model_fallbacks` are configured.
- Added `/api/tools/accuracy` to summarize tool calls, success rate, error count, confirmation rate, and average latency from existing tool execution logs.
- Added `/api/routing/policy` with scenario policies for research, learning, office, project, web, and general workflows.
- Console dashboard now includes model health, tool accuracy, and scenario routing summary blocks; confirmation bar shows risk level for tools needing approval.

Verification:
- `python -m py_compile clawos\clawos_server.py clawos\scripts\tool_runner.py clawos\security\policy.py` passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js` passed.
- Targeted tests: `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_routing_memory clawos.tests.test_model_provider clawos.tests.test_runtime_security`: `46 tests OK`.
- Full suite: `python -m unittest discover -s clawos\tests`: `114 tests OK`.

Known notes:
- Real network smoke in this sandbox confirmed policy risk/confirmation behavior, but outbound public fetch returned HTTPS EOF / HTTP 502 from the environment. Code paths are tested; final live web validation should run in a runtime with stable outbound HTTP(S).
- Search provider keys are read from `TAVILY_API_KEY`, `SERPAPI_API_KEY`, and `BING_SEARCH_API_KEY`; DuckDuckGo remains no-key fallback.

### 2026-06-20 - Enterprise console, smart routing, RAG graph, and permission center pass

Completed:
- Kept the chat surface cleaner by putting deeper operational controls behind the More drawer. Added a dedicated Permission Center view instead of exposing security tables in the primary chat workspace.
- Upgraded `/api/routing/policy` from a single ordered scenario match to scored policy routing. It now returns `candidates`, selected `strategy`, model profile, retrieval mode, risk, required confirmations, matched keywords, and recommended tool chain while keeping existing `scenario/selected/policies` compatibility.
- Added document/RAG product endpoints: `/api/documents/ocr-queue`, `/api/documents/citation-answer`, and `/api/knowledge/graph`.
- Knowledge graph now has real backend nodes and edges from categories, documents, chunks, and knowledge entries. The console topology panel fetches this graph instead of only rendering local item cards.
- Knowledge view now exposes an OCR queue and citation-answer panel. Citation answers use indexed document chunks and return citations/snippets instead of raw frontend text stuffing.
- Added console Permission Center tables for policy checks, workspace boundaries, and security audit events using existing `/api/security/policy/check`, `/api/workspace/capabilities`, and `/api/security/audit`.
- Added overflow and long-text hardening for panel views, tables, chat bubbles, and security/knowledge workspaces in `clawos/static/assets/console.css`.
- Restored test-mutated `clawos/skills/skill_registry.jsonl` usage counters after validation; no runtime stats should be committed from this pass.

Verification:
- `python -m py_compile clawos\clawos_server.py clawos\memoryos\memory_store.py` passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js` passed.
- Targeted tests: `python -m unittest clawos.tests.test_routing_memory clawos.tests.test_frontend_static`: `33 tests OK`.
- Full suite: `python -m unittest discover clawos\tests`: `117 tests OK`.

Known notes:
- The new citation answer endpoint is currently extractive over indexed chunks. It is closed-loop and citeable, but a final champion-grade version should let the model synthesize over the returned citations while preserving citation IDs.
- OCR is detected and surfaced as a queue, but there is not yet a local OCR worker to resolve scanned pages automatically. Next step is a pluggable OCR worker with per-page status and re-indexing.
- Permission Center is read-only in this pass. The next product step is editable allowlist/risk policy with persisted approvals, expiry, and per-tool scopes.
### 2026-06-19 - Skills workbench completion pass

Completed:
- Expanded the console Skills view from three passive tables into a usable workbench with search, category/status filters, selectable skill cards, skill detail, required parameter hints, step preview, version history, evaluation runs, review inbox, and execution quality.
- Added `POST /api/skills/execute` with `plan_only=true` by default. The console uses this for safe skill preview before explicit execution.
- Added frontend/static and runtime tests for the new Skills workbench controls and plan-mode execution contract.
- Added `python-multipart>=0.0.9` to `clawos/requirements.txt`; current document upload routes require it.

Verification:
```powershell
node --check clawos\static\assets\console.js
.\clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static clawos.tests.test_skill_runtime
```

Result:
- JS syntax check passed.
- Python compile passed.
- Targeted tests: `19 tests OK`.

Known notes:
- Full suite currently stops during `clawos_server.py` import because the local `.venv` does not have `python-multipart` installed. Install/update dependencies first:
  ```powershell
  .\clawos\.venv\Scripts\python.exe -m pip install -r clawos\requirements.txt
  .\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
  ```
- `skill_registry.jsonl` is a runtime registry and tests can bump `dev_health_check` usage counters; restore that file before committing if it changes.

### 2026-06-20 - Local Qwen provider bootstrap

Completed:
- Selected `Qwen3.5-9B-Q4_K_M.gguf` as the current local Qwen target because official Qwen3.7 weights were not available and official Qwen3.6 starts at larger 27B/35B-A3B sizes.
- Downloaded the GGUF model to ignored local path `tools/models/qwen3.5-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf`; model binaries stay out of Git.
- Added `clawos/models/qwen3_5_9b_q4_k_m.json` as the committed model dependency manifest with repo, filename, size, hash, and local path.
- Added `qwen` as a first-class model provider alias over the existing OpenAI-compatible provider, defaulting to `http://127.0.0.1:8000/v1` and no API key. API providers remain primary when `MODEL_API_KEY` is present; Qwen is the local fallback path.
- Added `clawos/scripts/download_qwen_model.ps1` and wired `start_qwen_llama_server.ps1` to download/verify the Qwen GGUF when it is missing. `start_clawos.bat` starts local Qwen automatically when no API key is configured.
- Added `clawos/scripts/start_qwen_llama_server.ps1` to start a local llama.cpp OpenAI-compatible server when `llama-server.exe` is available.

Known notes:
- `llama-server.exe` is not bundled in Git. Put it at `tools/llama.cpp/llama-server.exe`, install it on PATH, or pass `-ServerPath`.
- The downloaded model SHA256 observed locally was `03B74727A860A56338E042C4420BB3F04B2FEC5734175F4CB9FA853DAF52B7E8`.

### 2026-06-22 - Model mode UI and API provider aliases

Completed:
- Added a visible console header model-mode panel so the workbench distinguishes `DeepSeek/API 模式`, `Local Qwen 模式`, and `Mock/offline test 模式`.
- Added `qwen` to the model settings dropdown for local llama.cpp/Qwen and added `qwen_api` plus `glm` API options for OpenAI-compatible Qwen/DashScope and GLM/Zhipu providers.
- Added frontend provider presets for DeepSeek, Local Qwen, Qwen API, GLM, Local OpenAI, and Mock/offline test mode.
- Extended provider factory and config validation to accept `qwen_api`, `glm`, and `zhipu` aliases through the existing OpenAI-compatible contract.
- Updated `provider_smoke.py` so keyless local providers such as Qwen report `configured=true` when endpoint/model settings are valid.
- Added a `curl.exe` retry fallback to `download_llama_cpp.ps1` for environments where `Invoke-WebRequest` fails.

Verification:
- Local Qwen GGUF exists at `tools/models/qwen3.5-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf`.
- SHA256 verified: `03B74727A860A56338E042C4420BB3F04B2FEC5734175F4CB9FA853DAF52B7E8`.
- `python -m py_compile clawos\clawos_server.py clawos\providers\factory.py clawos\scripts\provider_smoke.py` passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js` passed.
- Targeted tests: `python -m unittest clawos.tests.test_model_provider clawos.tests.test_frontend_static`: `33 tests OK`.
- Full suite: `python -m unittest discover clawos\tests`: `125 tests OK`.

Known notes:
- `llama-server.exe` is now present under `tools/llama.cpp`, and Qwen can load/listen on `http://127.0.0.1:8000/v1` during a temporary smoke run.
- Offline Qwen smoke result after JSON-mode/grammar/repair work: `direct_completion`, `tool_calling`, and `reflection_json` all passed against the local llama.cpp endpoint.
- Current observed timings on the local Qwen GGUF smoke: direct completion about `57.1s`, tool calling about `14.2s`, reflection JSON about `17.9s`. This proves local offline capability, but DeepSeek/API mode is still the faster demo path.
- Qwen reflection JSON closure depends on short prompts, `response_format={"type":"json_object"}`, JSON grammar, `reasoning_content` fallback, and JSON repair.

### 2026-06-22 - OCR worker, Permission Center grants, and service split

Completed:
- Added `clawos/services/model_service.py` and `clawos/services/knowledge_service.py` so model status/mode and document/RAG/OCR/graph work are no longer owned directly by `clawos_server.py`.
- Closed the scanned-PDF ingestion gap: uploads with no extractable text but `ocr_required=true` now become `needs_ocr` documents instead of failing before they can enter the OCR queue.
- Added `POST /api/documents/{document_id}/ocr`. It supports manual sidecar OCR text, sidecar `.ocr.txt` / `.ocr.json` files, and local `pdftoppm` + `tesseract` when installed; successful runs rebuild chunks, knowledge entries, citations, and vector indexes.
- Added persistent `SecurityGrantStore` with allow/confirm/deny grants, expiry, and scopes for tool, URL host, path prefix, and command prefix. Permission Center now has APIs to list/create/revoke grants.
- Upgraded the console Permission Center from read-only status tables to editable fine-grained grants. OCR queue rows can now trigger real OCR processing.

Verification:
- `python -m py_compile clawos\clawos_server.py clawos\security\policy.py clawos\memoryos\document_ingestion.py clawos\services\__init__.py clawos\services\model_service.py clawos\services\knowledge_service.py` passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js` passed.
- Targeted tests: `python -m unittest clawos.tests.test_runtime_security clawos.tests.test_routing_memory clawos.tests.test_frontend_static clawos.tests.test_memoryos_mvp`: `49 tests OK`.
- Full suite: `python -m unittest discover clawos\tests`: `131 tests OK`.

Known notes:
- OCR is now closed-loop, but true production quality depends on installing a robust local OCR stack and adding per-page progress/retry UI.
- Permission grants are persisted in local `clawos/security_policy.json` at runtime; do not commit that file if it contains user-specific permissions.
- `clawos_server.py` still contains many route handlers, but model and knowledge responsibilities now have service boundaries. A later cleanup can continue with `ToolService`, `SecurityService`, and route-module splitting.

### 2026-06-23 - Tool/Security/Task services, ops checks, core E2E, and streaming cancel

Completed:
- Added `clawos/services/tool_service.py`, `task_service.py`, `security_service.py`, and `maintenance_service.py`.
- `clawos_server.py` now delegates tool execution envelopes, security grants/audit/secrets, and runtime task helpers through service boundaries while preserving existing API/helper names for compatibility.
- Added system operations APIs: `/api/system/config/check`, `/api/system/migrations`, `/api/system/migrations/apply`, and `/api/system/backup`.
- Added SQLite migration tracking via `schema_migrations` and safe SQLite backup using the SQLite backup API plus JSON metadata.
- Added deterministic `core-e2e-v1` benchmark suite in `clawos/benchmarks/core_e2e_v1.json`, covering learning, research, code, and office flows.
- Chat streaming now emits SSE metadata/chunks, includes `task_id`, and checks task cancellation during streaming.
- Console chat now uses stream mode by default and includes a Stop button that aborts the active request and calls the task cancel API.

Verification:
- `python -m py_compile clawos\clawos_server.py clawos\scenario_benchmarks.py clawos\services\tool_service.py clawos\services\task_service.py clawos\services\security_service.py clawos\services\maintenance_service.py`: passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js`: passed.
- Targeted tests: `python -m unittest clawos.tests.test_operations_and_streaming clawos.tests.test_scenario_benchmarks clawos.tests.test_frontend_static clawos.tests.test_runtime_security clawos.tests.test_runtime_task_control clawos.tests.test_routing_memory`: `58 tests OK`.
- Full suite: `python -m unittest discover -s clawos\tests`: `136 tests OK`.
- Frozen benchmark: `python clawos\scripts\run_frozen_benchmarks.py`: `30/30`, pass_rate `1.0`, P95 about `440.854ms`.
- Core E2E benchmark: `python clawos\scripts\run_frozen_benchmarks.py --suite clawos\benchmarks\core_e2e_v1.json`: `4/4`, pass_rate `1.0`, P95 about `70.114ms`.

Known notes:
- `node` is not on this Windows PATH; use bundled Node at `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe` for JS checks on this machine.
- Streaming is SSE over the existing non-token provider call for model completions, with chunked delivery and cancellation checks. True provider-native token streaming can be added later behind the same frontend contract.

### 2026-06-23 - Paper PDF quality and Obsidian knowledge validation pass

Completed:
- Upgraded `WorkspaceServices.generate_research_learning_analysis(..., formats=["pdf"])` PDF rendering from plain Markdown flowables to a journal-style report layout with title page, margins, header/footer, page numbers, section hierarchy, evidence callouts, and inline bold handling.
- Added Obsidian-style knowledge validation in `KnowledgeService`: frontmatter readiness, tags, sources, wiki links, backlinks, and graph coverage now return a deterministic score.
- Added Obsidian vault export support with `index.md` plus note files containing YAML frontmatter, `[[wikilinks]]`, backlinks, tags, and source sections.
- Added API endpoints `/api/knowledge/obsidian/check` and `/api/knowledge/obsidian/export`.
- Added tests for deep paper-reading PDF generation quality and Obsidian vault validation/export.

Verification:
- `python -m py_compile clawos\workspace_services.py clawos\services\knowledge_service.py clawos\clawos_server.py`: passed.
- `python -m unittest clawos.tests.test_workspace_services clawos.tests.test_routing_memory`: `31 tests OK`.
- `python -m unittest discover -s clawos\tests`: `137 tests OK`.
- `python clawos\scripts\run_frozen_benchmarks.py`: `30/30`, pass_rate `1.0`, P95 about `428.767ms`.
- `python clawos\scripts\run_frozen_benchmarks.py --suite clawos\benchmarks\core_e2e_v1.json`: `4/4`, pass_rate `1.0`, P95 about `99.476ms`.
- Rendered a generated learning-analysis PDF with `pdftoppm` and visually inspected pages 1, 2, and 5. Layout, hierarchy, evidence boxes, and footer/page numbers rendered correctly.

Known notes:
- `pdftoppm` emitted a non-blocking `No display font for 'ArialUnicode'` warning, but rendered PNG pages successfully with readable CJK/English text.
- MTTBook hardware validation remains intentionally deferred until the device is available.
- Generated PDF/rendering scratch files are under `clawos\tmp\pdfs\pdf_quality_check` and should not be committed.

Recommended next step:
- Add frontend controls for Obsidian check/export and a visual quality preset selector for report generation, then do real MTTBook acceptance once hardware arrives.

### 2026-06-24 - PDF contrast, Obsidian console controls, semantic graph, and paper intelligence pass

Completed:
- Increased learning-analysis PDF contrast and visual weight: darker ink/rules, stronger evidence boxes, larger body text, and Windows `simhei` priority for more readable CJK/English output.
- Added deterministic `Paper Intelligence Addendum` to paper-reading reports, covering contribution reading, method/experiment/reproducibility/limitation signals, evidence density, and a reproducibility checklist.
- Upgraded `KnowledgeService.knowledge_graph` semantic edges beyond containment: tags, wiki links, backlinks, source/citation nodes, and concept mentions are now represented as graph nodes/edges.
- Added console Obsidian controls in the Knowledge view: check, export directory input, export button, score table, and status feedback wired to `/api/knowledge/obsidian/check` and `/api/knowledge/obsidian/export`.
- Updated frontend graph rendering to draw actual returned semantic edges with per-relation coloring instead of only center-to-node spokes.
- Added tests for PDF intelligence content, Obsidian console controls, semantic graph edges, and frontend API wiring.

Verification:
- `python -m py_compile clawos\workspace_services.py clawos\services\knowledge_service.py clawos\clawos_server.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_workspace_services clawos.tests.test_routing_memory clawos.tests.test_frontend_static`: `47 tests OK`.
- `python -m unittest discover -s clawos\tests`: `137 tests OK`.
- `python clawos\scripts\run_frozen_benchmarks.py`: `30/30`, pass_rate `1.0`, P95 about `688.476ms`.
- `python clawos\scripts\run_frozen_benchmarks.py --suite clawos\benchmarks\core_e2e_v1.json`: `4/4`, pass_rate `1.0`, P95 about `253.843ms`.
- Rendered the updated PDF with `pdftoppm` and visually inspected pages 2 and 6. Text is substantially darker and the intelligence addendum renders without overlap or clipping.

Known notes:
- `pdftoppm` still emits a non-blocking `No display font for 'ArialUnicode'` warning while producing valid PNG output.
- Current paper intelligence is deterministic/extractive. Higher semantic depth can later come from model synthesis over cited chunks, keeping the same report structure.
- MTTBook hardware validation remains deferred until the device is available.

Recommended next step:
- Add a report style selector in the UI and a model-assisted citation synthesis pass for the `Paper Intelligence Addendum`, then run MTTBook real-device acceptance.

### 2026-06-24 - PDF mixed-font polish and configuration-first startup

Completed:
- Changed the learning-analysis PDF font preference from SimHei-first to Microsoft YaHei / Noto Sans SC before SimHei, improving mixed Chinese-English typography while keeping the darker journal-style contrast.
- Slightly softened the darkest PDF ink palette after the font change so body text remains strong without making English look heavy or cramped.
- Changed `start_clawos.bat` so missing `MODEL_API_KEY` opens ClawOS in configuration-first mock mode instead of starting local Qwen or downloading model/runtime dependencies.
- Changed `start_qwen_llama_server.ps1` to opt in to downloads with `-Download`; missing Qwen GGUF or llama.cpp now produces an explicit manual-action message.
- Added console model-settings copy explaining that Local Qwen saves the local endpoint only; users choose API or offline mode themselves and download/start local model manually when needed.
- Added regression tests for the PDF font preference and for launcher/local-Qwen no-auto-download behavior.

Verification:
- `python -m py_compile clawos\workspace_services.py clawos\clawos_server.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest discover -s clawos\tests`: `139 tests OK`.
- `python clawos\scripts\run_frozen_benchmarks.py`: `30/30`, pass_rate `1.0`, P95 about `479.606ms`.
- `python clawos\scripts\run_frozen_benchmarks.py --suite clawos\benchmarks\core_e2e_v1.json`: `4/4`, pass_rate `1.0`, P95 about `77.191ms`.
- Rendered a generated mixed Chinese-English learning-analysis PDF with `pdftoppm` and visually inspected pages 2 and 6. English typography is improved, CJK remains readable, and no overlap/clipping was observed.

Known notes:
- `pdftoppm` still emits the non-blocking `No display font for 'ArialUnicode'` warning while producing valid PNG output.
- The app no longer auto-downloads or auto-starts Qwen from the launcher; offline model setup is now an explicit user choice.

Recommended next step:
- Add a visible report style/preset selector and a first-run model-choice card, then run MTTBook real-device acceptance when hardware is available.

### 2026-06-24 - First-run model choice and report preset controls

Completed:
- Added a first-run model choice card to the console empty chat state with direct choices for DeepSeek/API, Local Qwen, and Mock/offline mode.
- Added report style presets in the Knowledge view for journal, learning notes, business brief, and compact report workflows.
- Wired report preset controls to update the next chat prompt, so users can choose the report output style before asking ClawOS to generate a paper/report artifact.
- Added `report_style` passthrough to `/api/workspace/research/learning-analysis` and persisted it in generated report metadata.
- Added frontend/static and workspace service tests covering the new model-choice and report-style controls.

Verification:
- `python -m py_compile clawos\clawos_server.py clawos\workspace_services.py`: passed.
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js`: passed.
- Targeted tests: `clawos.tests.test_frontend_static clawos.tests.test_workspace_services`: `29 tests OK`.
- Full suite with project `.venv`: `139 tests OK`.

Known notes:
- Full suite mutates `clawos/skills/skill_registry.jsonl` usage counters and produced a `%SystemDrive%/` test artifact on this machine; both were restored/removed after validation.
- `PROJECT_CONTEXT.md` displays mojibake in the current PowerShell output, likely due terminal/codepage handling; file content should be checked in an editor before final handoff if this becomes visible to reviewers.

### 2026-06-24 - User-facing console copy pass

Completed:
- Reworded the first-run model card from demo language to normal product language: choose a model mode for daily use, local offline use, or no-key mode.
- Renamed Obsidian validation UI copy to check/export wording and changed benchmark result copy from acceptance phrasing to run-result phrasing.
- Added frontend static regression coverage so the console does not reintroduce internal demo/competition acceptance terms in user-facing copy.

Verification:
- Bundled Node syntax check: `node.exe --check clawos\static\assets\console.js`: passed.
- Frontend static tests: `19 tests OK`.

### 2026-06-24 - Knowledge document report generation flow

Completed:
- Replaced the Knowledge view report preset card's primary path with a real document-to-report workflow: users can pick an uploaded PDF, select report style/depth, choose an output directory, and generate Markdown/PDF directly.
- Added `library_document_id` support to `/api/workspace/research/learning-analysis`, bridging MemoryOS uploaded documents into the research report generator through the stored source file path.
- Added result rendering for generated report metadata, Markdown/PDF paths, output directory, and preview in the console.
- Added frontend static coverage for the real report generation controls and backend route coverage for generating a report from a library document.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m py_compile clawos\clawos_server.py`: passed.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_learning_analysis_accepts_library_document_id clawos.tests.test_workspace_services.WorkspaceServicesTests.test_research_learning_analysis_generates_markdown_and_pdf`: `21 tests OK`.
- `git diff --check`: passed.
- `python -m unittest discover -s clawos\tests`: `142 tests OK`.

Known notes:
- Current report generation bridge supports uploaded PDF documents because the existing research report generator requires readable PDF input.
- Running tests may create an untracked `%SystemDrive%/` local artifact in the workspace on this Windows machine.

Recommended next step:
- Make `report_style` alter the actual Markdown/PDF report structure, then add a save-generated-report-to-knowledge/Obsidian action for a full user workflow loop.

### 2026-06-24 - Report style templates and save-back action

Completed:
- Confirmed the backend report renderer has distinct Markdown structures for journal, learning notes, business brief, and compact reports.
- Added a console action to save the latest generated report back into the knowledge base, including Markdown/PDF paths, style metadata, and preview content.
- Kept Obsidian export as the next visible action after saving, so generated reports can re-enter the knowledge/Obsidian loop.
- Updated tests so business brief output is checked against business-style sections and all four report styles are covered.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m py_compile clawos\workspace_services.py clawos\clawos_server.py`: passed.
- Targeted report/style/frontend tests: `3 tests OK`.
- `git diff --check`: passed.
- `python -m unittest discover -s clawos\tests`: `143 tests OK`.

Known notes:
- Full tests mutate `clawos/skills/skill_registry.jsonl` use counters. A restore attempt was blocked by the environment usage limit, so the working tree currently still shows that test side-effect file as modified.

Recommended next step:
- Add a user-visible link from a saved generated report back into chat, so follow-up Q&A can start from the saved report item instead of only the original source document.

### 2026-06-25 - Saved report follow-up action

Completed:
- Added a follow-up action after saving a generated report to the knowledge base: the result panel now exposes a direct button to ask about the saved report through the existing knowledge prompt path.
- Reused `appendKnowledgeToPrompt` instead of adding a parallel chat mechanism, keeping report follow-up consistent with normal knowledge items.
- Added frontend static coverage for the saved-report knowledge id and follow-up prompt hook.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `19 tests OK`.
- `git diff --check`: passed.
- `python -m unittest discover -s clawos\tests`: `143 tests OK`.

Known notes:
- Full tests mutate `clawos/skills/skill_registry.jsonl` use counters. This remains visible in the working tree because the previous restore attempt was rejected by environment usage limits and should not be bypassed.

Recommended next step:
- Add a small end-to-end user-flow test around upload/generate/save/follow-up once a browser or API-level scenario harness is selected for this workflow.

### 2026-06-25 - API-level report workflow test

Completed:
- Added an API-level user-flow test that models the main knowledge workflow: uploaded library PDF, report generation, save generated report into the knowledge base, and verify the saved report is visible for follow-up actions.
- The test uses the same `/api/workspace/research/learning-analysis`, `/api/knowledge`, and `/api/knowledge` list endpoints that back the console flow.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_user_report_flow_generate_save_and_search_followup`: passed.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_user_report_flow_generate_save_and_search_followup`: `20 tests OK`.
- `git diff --check`: passed.
- `python -m unittest discover -s clawos\tests`: `144 tests OK`.

Known notes:
- Full tests continue to mutate `clawos/skills/skill_registry.jsonl` use counters. The current diff in that file is a test side effect and should be restored before commit when the environment allows it.

Recommended next step:
- Do a user-facing copy and visual pass on the report result panel so the generate/save/follow-up actions read as one compact workflow rather than separate tool outputs.

### 2026-06-25 - Report result workflow copy and layout

Completed:
- Reworked the report result panel into a four-step user workflow: generate report, save to knowledge base, export Obsidian, continue asking questions.
- Added compact styling for the workflow step chips so the result panel reads as one continuous user path instead of isolated tool outputs.
- Updated frontend static coverage for the workflow classes and user-facing result-panel copy.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `19 tests OK`.
- `python -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_user_report_flow_generate_save_and_search_followup`: passed.
- `git diff --check`: passed.
- `python -m unittest discover -s clawos\tests`: `144 tests OK`.

Known notes:
- `clawos/skills/skill_registry.jsonl` still shows the full-test use counter side effect from earlier runs. Restore it before commit when allowed.

Recommended next step:
- Restore the clawos/skills/skill_registry.jsonl test counter side effect when allowed, then stage only product/test/context changes for the final commit.

### 2026-06-25 - Upload-to-report next-step guidance

Completed:
- Improved the Knowledge upload flow from a passive parse result into a clearer next step for normal users.
- After uploading a ready PDF, the console now auto-selects the newest PDF in the report selector and tells the user to choose a style and generate the report.
- If uploaded files are not report-ready PDFs, the status now explains that report generation needs a readable PDF.
- Report generation failures now show user-actionable reasons instead of only passing through a raw error string.
- Added frontend static coverage for PDF auto-selection, next-step copy, and report-generation failure guidance.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `19 tests OK`.
- `python -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_user_report_flow_generate_save_and_search_followup`: failed under system Python because `uvicorn` is not installed there.
- `.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_user_report_flow_generate_save_and_search_followup`: passed.

Known notes:
- Use the project virtual environment for backend/API tests on this machine; system Python is missing FastAPI runtime dependencies such as `uvicorn`.
- Current worktree intentionally contains this frontend/test/context update only.

Recommended next step:
- Run a real browser user-flow check of first-run model choice -> upload PDF -> generate report -> save -> follow-up, then commit this usability pass if the visual flow is acceptable.
### 2026-06-25 - Browser sidebar and knowledge layout fix

Completed:
- Ran a real browser check on the console Knowledge view and reproduced the user-reported sidebar mojibake/compression and report-row clipping issues.
- Added session-title cleanup so unreadable history titles made only of question marks or replacement characters display as `未命名会话`.
- Tightened the left sidebar recent-session list: one-line ellipsis titles, no tag chips in the compact sidebar, scrollable history, and bottom settings pinned after available space.
- Fixed `hidden` handling for the first-run model card so CSS display rules cannot override hidden state.
- Made the Knowledge report-generation row responsive and kept the `生成报告` button inside the panel.
- Constrained top status badges so model/tool status does not overflow the header.
- Captured a post-fix browser screenshot at `tmp/clawos-knowledge-layout-fixed.png` for local visual evidence.

Verification:
- Browser DOM check confirmed no `??????????` session title remains, no common mojibake fragments are visible, no internal demo/acceptance terms are visible, the report button stays inside its panel, and header actions stay inside the header.
- `node --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `19 tests OK`.

Known notes:
- The screenshot under `tmp/` is local visual evidence and should not be committed unless explicitly needed.

Recommended next step:
- Continue browser-driven checks on the full first-run workflow, especially after uploading a real PDF and generating/saving a report.
### 2026-06-25 - Browser report workflow validation and artifact ignore

Completed:
- Ran the main browser workflow against the live local console: temporary PDF upload, automatic report document selection, compact report generation, save generated report to the knowledge base, and continue asking about the saved report.
- Verified the generated report panel shows Markdown path, PDF path, output directory, style, question count, preview content, save action, Obsidian action, and follow-up prompt action.
- Added root `.gitignore` entries for local ClawOS runtime artifacts created during manual/browser validation: `clawos/uploads/`, `output/reports/`, and `tmp/*.png`.

Verification:
- Browser flow returned `ok=true` for report generation and populated the follow-up chat prompt from the saved knowledge report.
- `git status` after the ignore update no longer lists the generated upload/report/screenshot artifacts.

Known notes:
- The browser validation intentionally used a synthetic non-sensitive PDF named `clawos-flow-check.pdf`.
- Runtime artifacts remain on disk for local inspection, but are now ignored by Git.

Recommended next step:
- Run one more focused browser check with a realistic user PDF when the user is ready, then prepare the branch for push/PR.
### 2026-06-25 - Obsidian export path stability fix

Completed:
- Browser validation found that entering `output/obsidian/browser-flow-check` in the Obsidian export field produced a duplicated path: `output/obsidian/output/obsidian/browser-flow-check`.
- Added `resolve_obsidian_output_dir()` in `clawos_server.py` so both `browser-flow-check` and `output/obsidian/browser-flow-check` resolve to the same stable vault directory under `output/obsidian`.
- Kept the existing safety boundary: absolute or relative paths outside `output/obsidian` still raise `400`.
- Added routing-memory test coverage for the stable output path behavior.
- Added `output/obsidian/` to `.gitignore` so local Vault exports do not pollute Git status.

Verification:
- `.\clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py`: passed.
- `.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_obsidian_export_output_dir_accepts_repo_relative_path`: passed.
- `.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_knowledge_obsidian_check_and_vault_export clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_obsidian_export_output_dir_accepts_repo_relative_path`: `2 tests OK`.

Known notes:
- The already-running browser server needs a restart to pick up this backend path fix.

Recommended next step:
- Restart the local ClawOS server and rerun the browser Obsidian export check with `output/obsidian/browser-flow-check`.
### 2026-06-25 - Restore API, minimal task worker, and model settings placement

Completed:
- Added `/api/system/restore` to close the SQLite backup/restore loop. Restore now requires `confirm=true`, validates the backup with SQLite integrity check, creates a pre-restore backup, replaces the active DB, reapplies migrations, and refreshes vectors.
- Added a minimal background task worker path with `/api/tasks/worker/status`, `/api/tasks/worker/tick`, `/api/tasks/worker/start`, and `/api/tasks/worker/stop`.
- Worker support covers queue consumption, startup recovery retry creation, deterministic long-task sleep, cancellation checks, failure marking, and bounded retry creation.
- Moved API/local/mock model choice out of the chat first screen. Model selection now lives under More -> Model configuration only, while Local Qwen remains explicit/manual for download and startup.
- Added tests for restore rollback behavior, worker success/failure/retry/cancellation, and the model-choice UI placement.

Verification:
- `python -m py_compile clawos\clawos_server.py clawos\services\maintenance_service.py clawos\services\task_service.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Targeted tests: `python -m unittest clawos.tests.test_operations_and_streaming clawos.tests.test_runtime_task_control clawos.tests.test_frontend_static`: `32 tests OK`.
- Full suite: `python -m unittest discover -s clawos\tests`: `145 tests OK`.
- Frozen benchmark: `python clawos\scripts\run_frozen_benchmarks.py`: `30/30`, pass_rate `1.0`, P95 about `510.304ms`.
- Core E2E benchmark: `python clawos\scripts\run_frozen_benchmarks.py --suite clawos\benchmarks\core_e2e_v1.json`: `4/4`, pass_rate `1.0`, P95 about `73.603ms`.

Known notes:
- The worker is intentionally minimal and single-process. It is good for local recovery/queue consumption demos, not yet a distributed scheduler or multi-agent runtime.
- Restore is a local high-risk operation and must remain confirmation-gated in product UI.

Recommended next step:
- Add a small Ops UI for backup/restore/worker controls, then add richer worker actions for real report generation and document processing jobs.

### 2026-06-26 - Ops Center, real worker jobs, and professional boards

Completed:
- Added an Ops Center under the More drawer with readiness score, config check, backup/restore controls, worker start/stop/tick, and long-running business job queue controls.
- Added `/api/system/readiness` so the local single-user ops standard is visible as weighted checks rather than a vague claim.
- Extended `TaskService` with pluggable worker action handlers and pending enqueue support.
- Connected real business jobs to the worker: background report generation, batch document ingestion, and OCR queue processing. These reuse the existing report, document ingestion, and KnowledgeService OCR paths.
- Added job enqueue APIs: `/api/tasks/jobs/report`, `/api/tasks/jobs/ocr-queue`, and `/api/tasks/jobs/batch-ingest`.
- Added a professional scenario board for research, learning, code, and office workflows with concrete gates: citation/reproducibility, mastery evidence, tests/handoff, and export quality.
- Added regression tests covering real worker handler dispatch, business job queueing, batch ingest + OCR worker execution, Ops UI wiring, and Professional Template Board presence.

Verification:
- Bundled Node syntax check: `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Targeted tests: `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_runtime_task_control`: `35 tests OK`.
- Full suite: `python -m unittest discover -s clawos\tests`: `152 tests OK`.

Known notes:
- Ops readiness is scoped to a local single-user enterprise-style operations gate. It is not a production enterprise claim because RBAC, Keyring, multi-tenant identity, resource quotas, and MTTBook real-device validation remain pending.
- Full tests still mutate `clawos/skills/skill_registry.jsonl` usage counters; the file was restored after validation and should not be staged.

Recommended next step:
- Run a browser visual pass on More -> Ops Center and Scenes -> Professional Template Board, then decide whether to add progress percentages/log tailing for long report/OCR jobs.

### 2026-06-26 - Frontend mojibake cleanup, responsive console polish, and board QA

Completed:
- Rebuilt the console HTML/JS user-facing copy so core console surfaces no longer expose mojibake or broken Chinese text.
- Standardized the core console layout around page header, actions, metrics/tables, results, and empty states for chat, knowledge, tasks, Ops, and scenes.
- Added icon-text treatment and clearer status/action affordances for export, restore, cancel, retry, worker, Ops, and knowledge flows.
- Upgraded Professional Template Board into scenario workbench cards. Each board now shows input, output, quality gate, and next action for research, learning, code, and office workflows.
- Fixed small-width layout so the sidebar becomes a compact top navigation, the main work area starts inside the viewport, and dense tables scroll inside their cards instead of crushing text.
- Updated frontend static tests to assert clean Chinese copy, no common mojibake fragments, model choice placement, report flow, Ops UI, and Professional Board contracts.

Verification:
- Bundled Node syntax check: `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Frontend static tests: `python -m unittest clawos.tests.test_frontend_static`: `21 tests OK`.
- Unicode mojibake scan across `clawos/static/console.html`, `clawos/static/assets/console.js`, and `clawos/static/assets/console.css`: `0` flagged fragments.
- Browser visual QA with real CSS loaded through an embedded local static server: desktop `1440x980`, laptop `1280x860`, and narrow `390x900`; views checked: chat, knowledge, tasks, Ops, scenes. All reported `issueCount=0`.
- Narrow follow-up check: Ops/scenes main content begins at `mainLeft=0`, page scroll width equals viewport width `390`, and Ops tables use card-local horizontal scrolling.

Known notes:
- Browser QA screenshots and JSON reports were written under `output/playwright/` for local inspection and should remain untracked.
- Existing untracked DeepSeek reports and PDF preview artifacts remain untouched and should not be staged with this frontend commit.

Recommended next step:
- Run a product-owner review of the live console copy and decide whether to add a dedicated mobile "More" drawer entry so small-width users can reach every secondary module without horizontal nav scrolling.

### 2026-06-26 - Dedicated mobile More drawer entry

Completed:
- Added a dedicated mobile-only `More apps` entry in the console sidebar so narrow-width users can open the command drawer without relying on horizontal nav scrolling.
- Kept the existing desktop navigation unchanged and scoped the new control to `max-width:760px`.
- Added frontend static coverage to protect the mobile entry, drawer wiring, and responsive CSS contract.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `22 tests OK`.

Known notes:
- This was a targeted navigation/accessibility improvement; no backend or report-generation logic changed.

Recommended next step:
- Run a live browser pass on the first-run path at mobile width: model settings -> upload material -> generate report -> save to knowledge/Obsidian.

### 2026-06-26 - User report-to-Obsidian flow test coverage

Completed:
- Extended the user-facing report workflow regression so it now covers: choose an uploaded/library PDF, generate Markdown/PDF, save the generated report into the knowledge base, export that saved report to an Obsidian vault, and verify the exported note keeps Markdown/PDF paths and report style.
- Kept the flow on the real route functions instead of static UI assertions, using the existing output/obsidian safety boundary.
- Normalized the test report title separator to ASCII to avoid unnecessary encoding fragility in the regression.

Verification:
- `python -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_user_report_flow_generate_save_and_search_followup`: passed.
- `python -m unittest clawos.tests.test_routing_memory clawos.tests.test_workspace_services`: `36 tests OK`.
- `node --check clawos\static\assets\console.js`: passed.

Known notes:
- The test writes its Obsidian export under `output/obsidian/user-flow-e2e-test`, which is already ignored as a local generated artifact.

Recommended next step:
- Run the same first-run path through a live browser at mobile width, then decide whether the report result panel needs clearer one-click actions for continuing the conversation from the saved note.

### 2026-06-26 - Mobile browser first-run flow and Obsidian graph link fix

Completed:
- Ran a live Chrome DevTools mobile viewport pass at 390x900 against the local console. The mobile More entry is visible, the main area starts at x=0, and no horizontal page overflow was detected.
- Exercised the user flow with a real uploaded PDF document: choose library PDF, generate a business brief Markdown/PDF report, save it into the knowledge base, export to Obsidian, and continue asking from the saved report.
- Fixed the saved report knowledge content so it includes a source wikilink like `[[source title #1]]`; this gives the Obsidian export a real graph edge/backlink instead of showing failed wikilink/backlink checks after a successful report export.
- Added `output/playwright/` to `.gitignore` for local browser evidence screenshots/PDFs.

Verification:
- Mobile browser layout check: viewport `390x900`, `scrollWidth=390`, `clientWidth=390`, `mainLeft=0`, mobile More entry displayed as `flex`, no common mojibake/internal demo fragments.
- Mobile browser report flow: generated Markdown/PDF under `output/reports/mobile-browser-flow-linked`, saved latest report knowledge item with `Related source: [[mobile-flow-source #1]]`, Obsidian result showed `100 / 100` with wikilinks/backlinks success, and Continue follow-up returned to chat with the saved-report prompt.
- Browser evidence screenshots: `output/playwright/mobile-console-more-entry.png` and `output/playwright/mobile-report-obsidian-linked.png` (local ignored artifacts).
- `node --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `22 tests OK`.

Known notes:
- The live browser run used a synthetic non-sensitive PDF generated under `output/playwright/`; uploaded/report/Obsidian artifacts are local runtime evidence and ignored by Git.

Recommended next step:
- Review the model settings modal copy and first-run API/local/offline mode selection at mobile width, then run the targeted routing/workspace tests before a final full-suite pass.

### 2026-06-26 - Model mode chooser cleanup and race fix

Completed:
- Reworked the model settings modal into three clear user modes: API mode, local mode, and offline mode.
- Replaced the old English/implementation-facing model chooser buttons with mobile-friendly mode cards and localized provider option labels.
- Fixed `chooseFirstRunModel()` so choosing local/offline mode no longer races with async config loading and falls back to the previous DeepSeek value.
- Unified frontend and backend model mode labels to `API mode`, `local mode`, and `offline mode` equivalents in Chinese.
- Added regression coverage for model mode labels and frontend model settings contracts.

Verification:
- `node --check clawos\static\assets\console.js`: passed.
- `python -m py_compile clawos\services\model_service.py`: passed.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_model_mode_labels_are_user_facing_modes`: `23 tests OK`.
- `python -m unittest clawos.tests.test_routing_memory clawos.tests.test_frontend_static`: `46 tests OK`.
- Browser check before the final backend label fix confirmed the mobile modal layout at `390x900` had no horizontal overflow and that choosing `deepseek`, `qwen`, and `mock` preserved the selected provider/model/base URL.

Known notes:
- The final browser reload/restart pass could not be completed because the local tool approval layer reported the current usage limit. The source-level and unit/static verification passed; a fresh browser check should be run after tools are available again.

Recommended next step:
- Restart ClawOS, verify `/health` and the top model badge now show the simplified mode labels, then run a final targeted browser pass for model settings plus the report flow.

### 2026-06-27 - Console UX naming, sidebar behavior, and vector DB assessment

Completed:
- Fixed the sidebar "新聊天" entry so it creates a fresh session instead of only switching back to the chat view after history/search usage.
- Replaced letter-like sidebar badges with softer symbolic controls and added a real sidebar collapse toggle for desktop use.
- Removed user-facing Obsidian naming from the console. The UI now describes the feature as Markdown/双链笔记库 check/export while retaining the existing internal endpoint/function names for compatibility.
- Added frontend static coverage for new-chat behavior, sidebar toggle presence, and the absence of user-facing "导出 Obsidian" / "Obsidian Vault" copy.
- Reviewed current vector retrieval: it remains SQLite-backed with an in-memory character n-gram hash vector index. It is good for deterministic offline demos, but not enough for higher-quality paper reading, semantic note linking, or larger knowledge bases.

Verification:
- Bundled Node syntax check: `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Frontend static tests: `python -m unittest clawos.tests.test_frontend_static`: `22 tests OK`.
- Unicode mojibake scan across console HTML/JS/CSS: `0` flagged fragments.

Known notes:
- Internal API paths still contain `obsidian` for backward compatibility. User-facing text should use "笔记库", "双链笔记", or "Markdown 笔记库".
- The vector DB upgrade should be implemented behind the existing `MemoryVectorStore` contract so the rest of RAG, graph, report, and context-building code does not churn.

Recommended next step:
- Add a vector backend abstraction with `lightweight` and `chroma` providers, then run retrieval quality benchmarks on paper-reading, note linking, code search, and office document scenarios before switching defaults.

### 2026-06-27 - True collapsed sidebar and offline Chroma vector backend

Completed:
- Changed the desktop collapsed sidebar from a half-width icon rail into a true compact rail: only the ClawOS mark and the expand arrow remain, while navigation/history/bottom controls are hidden.
- Added an offline Chroma vector backend behind the existing `MemoryVectorStore` contract. Set `VECTOR_PROVIDER=chroma` to request it; if `chromadb` is unavailable, ClawOS falls back to the lightweight backend and reports the fallback reason in vector stats.
- Chroma uses deterministic local character n-gram embeddings for now, so it does not download embedding models or require network access. This gives persistent Chroma collections first, with stronger local embedding models left as the next layer.
- Added `vector_store` config with `provider` and `chroma_dir`, `.env.example` entries, optional `chromadb` requirements note, and ignored `clawos/data/chroma/`.
- Added tests for Chroma provider request/fallback safety and collapsed sidebar CSS contracts.

Verification:
- `python -m py_compile clawos/memoryos/services/vector_store.py clawos/clawos_server.py`: passed.
- `node --check clawos/static/assets/console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_model_provider clawos.tests.test_memoryos_mvp`: `56 tests OK`.

Known notes:
- Current environment does not have `chromadb` installed, so Chroma mode was verified through the safe fallback path. To use real Chroma offline, install `chromadb` from a local wheelhouse and set `VECTOR_PROVIDER=chroma`.
- Chroma currently stores local hash embeddings. Retrieval quality will improve further when an offline embedding model is added.

Recommended next step:
- Add an offline embedding provider abstraction (`hash`, local bge/e5/qwen embedding) and benchmark Chroma+local embeddings against the current lightweight index on paper reading and note-linking tasks.

### 2026-06-27 - Chroma installed and real offline vector flow accepted

Completed:
- Installed `chromadb==1.5.9` in the local Python environment.
- Switched default config examples from lightweight vectors to offline Chroma: `VECTOR_PROVIDER=chroma` and `config.json` default `${VECTOR_PROVIDER:-chroma}`.
- Moved `chromadb>=1.5.9` into `clawos/requirements.txt` as an installed runtime dependency for the offline vector backend.
- Disabled Chroma anonymized telemetry through client settings when available.
- Added explicit vector-store `close()` support so Windows releases Chroma index files before test cleanup.
- Ran a real Chroma acceptance flow covering SQLite MemoryOS writes, vector refresh, semantic search, context injection, close/reopen persistence, and repeated retrieval from the persisted collection.

Verification:
- Real Chroma acceptance: `chromadb_version=1.5.9`, `provider=chroma`, `fallback_reason=""`, `vector_count=2`, `context_injected=true`, `persisted_vector_count=2`.
- `python -m py_compile clawos\memoryos\services\vector_store.py clawos\clawos_server.py`: passed.
- `python -m unittest clawos.tests.test_memoryos_mvp clawos.tests.test_model_provider clawos.tests.test_frontend_static`: `56 tests OK`.
- `python -m unittest discover -s clawos\tests`: `156 tests OK`.

Known notes:
- Chroma is now the configured default path, while direct `MemoryVectorStore(...)` construction still stays lightweight unless provider/env/config requests Chroma. This keeps older deterministic tests and isolated scripts safe.
- Retrieval persistence is enterprise-demo ready, but semantic quality still depends on the current deterministic hash embeddings. The next quality jump is an offline embedding provider such as bge/e5/qwen embeddings.

### 2026-06-27 - DeepSeek online API and semantic retrieval benchmark

Completed:
- Added `clawos/scripts/deepseek_retrieval_benchmark.py` for explicit online DeepSeek retrieval acceptance. It probes `/models`, `/chat/completions`, and `/embeddings`, then runs four recall scenarios: journal paper reading, bidirectional notes, code search, and office documents.
- Confirmed live DeepSeek chat works with `deepseek-chat`; `/models` returned `deepseek-v4-flash` and `deepseek-v4-pro`; `/embeddings` returned `404`, so the current public compatible API should not be treated as a native embedding provider.
- Closed the online semantic retrieval path as DeepSeek query understanding + DeepSeek relevance judgment + local Chroma persistent recall. Offline Qwen/local embedding validation remains deferred.
- Added deterministic helper tests for the DeepSeek retrieval benchmark script and ignored local `output/deepseek_*.json` reports.

Verification:
- `python clawos\scripts\deepseek_retrieval_benchmark.py --model deepseek-chat --base-url https://api.deepseek.com/v1 --out output\deepseek_retrieval_benchmark.json`: `ok=True`, `chat_ok=True`, `embeddings_status=404`, `recall_at_5=1.0`, `mrr=0.875`, `judge_hit_rate=1.0`.
- `python clawos\scripts\evaluate_model_acceptance.py --provider deepseek --model deepseek-chat --base-url https://api.deepseek.com/v1 --suite clawos\benchmarks\core_e2e_v1.json --out output\deepseek_core_e2e_report.json`: `passed_count=4 failed_count=0 score=20/20 rate=1.0`.
- `python clawos\scripts\evaluate_model_acceptance.py --provider deepseek --model deepseek-chat --base-url https://api.deepseek.com/v1 --out output\deepseek_acceptance_report.json`: `passed_count=30 failed_count=0 score=150/150 rate=1.0`.
- `python -m unittest clawos.tests.test_deepseek_retrieval_benchmark`: `3 tests OK`.

Known notes:
- DeepSeek output reports are local evidence only and must not be committed. They do not contain API keys.
- The current online retrieval quality is strong for the benchmark corpus, but true large-corpus paper-grade semantic recall still needs a native embedding provider or offline embedding model.

### 2026-06-27 - Qwen3 Embedding + Chroma vector DB enterprise acceptance

Completed:
- Verified the manually downloaded local Qwen3-Embedding-0.6B model under `tools/models/qwen3-embedding-0.6b`. The missing `1_Pooling/config.json` sentence-transformers subfolder config was added locally under `tools/` and remains untracked.
- Installed local loading dependencies: `sentence-transformers` and `transformers`.
- Upgraded `MemoryVectorStore` so Chroma can use configurable local embedding backends. Default remains `hash`; setting `EMBEDDING_PROVIDER=qwen3` uses the local Qwen3 model with `EMBEDDING_DIM=1024`.
- Added `clawos/models/qwen3_embedding_0_6b.json` as a committed metadata manifest only. Model weights remain in ignored `tools/`.
- Added `clawos/scripts/vector_db_acceptance.py` for explicit enterprise vector DB acceptance covering model files, local embedding load, Chroma indexing, direct vector recall, hybrid retrieval, and close/reopen persistence.

Verification:
- Local model smoke: `SentenceTransformer('tools/models/qwen3-embedding-0.6b', local_files_only=True)` loaded and encoded 2 texts with shape `[2, 1024]`.
- Vector DB acceptance: `python clawos\scripts\vector_db_acceptance.py --out output\reports\vector_db_acceptance.json` returned `ok=True`, `provider=chroma`, `embedding=qwen3`, `dim=1024`, `direct_recall_at_5=1.0`, `hybrid_recall_at_5=1.0`, `direct_mrr=0.875`, `vector_count=12`, persisted vector count unchanged after reopen.
- `python -m py_compile clawos\memoryos\services\vector_store.py clawos\clawos_server.py clawos\scripts\vector_db_acceptance.py`: passed.
- `python -m unittest clawos.tests.test_model_provider clawos.tests.test_memoryos_mvp`: `35 tests OK`.
- `python -m unittest discover -s clawos\tests`: `160 tests OK`.

Known notes:
- Runtime report `output\reports\vector_db_acceptance.json` is ignored and should not be committed.
- Current Qwen3 embedding path is local CPU sentence-transformers. MTTBook/Qwen runtime performance and optional reranker acceptance remain future work.

### 2026-06-27 - Qwen3 Reranker second-stage retrieval acceptance

Completed:
- Downloaded local `Qwen/Qwen3-Reranker-0.6B` under ignored `tools/models/qwen3-reranker-0.6b`.
- Added committed metadata manifest `clawos/models/qwen3_reranker_0_6b.json`; model weights remain out of Git.
- Added `CrossEncoderReranker` to `memoryos.services.retrieval`. The production path is now configurable as Chroma + Qwen3-Embedding top-30 recall followed by Qwen3-Reranker top-5 precision ranking.
- Wired optional reranker config through `config.json`, `.env.example`, `clawos_server.py`, and `ContextBuilder`. Default remains `RERANKER_PROVIDER=none`, so normal startup does not load the 1.2GB reranker unless explicitly enabled.
- Extended `vector_db_acceptance.py` to validate reranker file completeness, top-30 vector recall, top-5 reranked recall, and rerank MRR.

Verification:
- Local reranker smoke: `CrossEncoder('tools/models/qwen3-reranker-0.6b', local_files_only=True)` loaded and scored the relevant office candidate above an unrelated paper candidate.
- Vector DB acceptance: `python clawos\scripts\vector_db_acceptance.py --out output\reports\vector_db_acceptance.json` returned `ok=True`, `direct_recall_at_30=1.0`, `hybrid_recall_at_5=1.0`, `rerank_recall_at_5=1.0`, `direct_mrr=0.875`, `rerank_mrr=1.0`.
- `python -m py_compile clawos\memoryos\services\retrieval.py clawos\memoryos\context_builder.py clawos\clawos_server.py clawos\scripts\vector_db_acceptance.py`: passed.
- `python -m unittest clawos.tests.test_retrieval_reranker clawos.tests.test_model_provider clawos.tests.test_memoryos_mvp`: `36 tests OK`.
- `python -m unittest discover -s clawos\tests`: `161 tests OK`.

Known notes:
- Reranker improves ranking quality but adds CPU latency. It should be enabled for high-quality paper/knowledge workflows and left off for lightweight demos unless needed.

### 2026-06-28 - Long-paper citation-aware RAG stress acceptance

Completed:
- Upgraded generic document ingestion so PDF text split by form-feed preserves page-aware chunk citations such as `doc:1#page=4&chunk=1`.
- Made reranker candidates citation-aware by including title and citation/source metadata in the query-passage scoring input.
- Added batch embedding/upsert support for vector indexing, so Chroma + local Qwen3 embedding can handle larger corpus acceptance runs without one-by-one encode overhead.
- Added `clawos/scripts/paper_rag_acceptance.py`, which generates a real multi-page PDF, ingests page-aware chunks, adds a larger distractor corpus, indexes through Chroma/Qwen3 embedding, then validates top-30 recall and top-5 Qwen3 rerank.
- Added regression coverage for page-aware PDF chunk citations.

Verification:
- `python clawos\scripts\paper_rag_acceptance.py --out output\reports\paper_rag_acceptance.json`: `ok=True`, `pages=16`, `chunks=32`, `vector_count=352`, `vector_recall_at_30=1.0`, `rerank_recall_at_5=1.0`, `rerank_mrr=1.0`, persisted vector count `352`.
- `python clawos\scripts\vector_db_acceptance.py --out output\reports\vector_db_acceptance.json`: `ok=True`, `direct_recall_at_30=1.0`, `hybrid_recall_at_5=1.0`, `rerank_recall_at_5=1.0`, `rerank_mrr=1.0`.
- `python -m py_compile clawos\memoryos\services\vector_store.py clawos\memoryos\document_ingestion.py clawos\memoryos\services\retrieval.py clawos\scripts\paper_rag_acceptance.py`: passed.
- `python -m unittest clawos.tests.test_memoryos_mvp clawos.tests.test_retrieval_reranker`: `13 tests OK`.
- `python -m unittest discover -s clawos\tests`: `162 tests OK`.

Known notes:
- Stress reports under `output\reports\` are ignored runtime evidence and should not be committed.
- The current stress corpus is synthetic but exercises real PDF generation, parsing, chunking, Chroma persistence, embedding, reranking, and citation checks. Next step for production evidence is running the same script against user-provided real papers.

### 2026-06-28 - Self-evolution run governance and regression gate

Completed:
- Added persistent `self_evolution_runs` records so every configuration improvement has baseline payload, candidate payload, benchmark evidence, gate result, conclusion, publish decision, and rollback payload.
- Added `reflection.self_evolution.SelfEvolutionManager` for low-risk automatic optimization targets only: prompt, retrieval parameters, report templates, and tool-routing policy. Code/source/script/module targets are rejected.
- Added a forced publish gate requiring all three benchmark families: frozen benchmark, core E2E, and retrieval benchmark. A candidate can publish only when required evidence is present and candidate metrics do not regress against baseline.
- Added `/api/self-evolution/runs`, create, evaluate, and publish endpoints. Publishing writes the candidate payload to `runtime_policies` only after the gate passes.
- Added deterministic tests for successful publish, retrieval regression rejection, missing benchmark rejection, and code-target rejection.

Verification:
- `python -m py_compile clawos\reflection\self_evolution.py clawos\memoryos\memory_store.py clawos\clawos_server.py`: passed.
- `python -m unittest clawos.tests.test_self_evolution`: `4 tests OK`.
- `python -m unittest clawos.tests.test_reflection_governance clawos.tests.test_policy_optimizer clawos.tests.test_memoryos_governance`: `9 tests OK`.
- `python -m unittest discover -s clawos\tests`: `166 tests OK`.

Known notes:
- The self-evolution gate currently evaluates supplied frozen/core/retrieval benchmark evidence. It does not yet auto-launch the benchmark scripts from a background job.
- This closes low-risk config self-improvement; automatic code modification remains intentionally blocked.

### 2026-06-28 - Self-evolution worker automation, candidate generation, and release board

Completed:
- Added automatic benchmark execution through the existing background worker. Creating a self-evolution run through `/api/self-evolution/runs` now defaults to queueing a `self_evolution_benchmark` task.
- Added deterministic candidate generation for low-risk targets: prompt rewrite, retrieval `top_k` / `rerank_top_k`, report template versioning, and tool-routing policy tuning.
- Added worker-generated frozen, core E2E, and retrieval benchmark evidence. Passing runs now move to `shadow` automatically instead of active runtime publish.
- Added staged release controls: `shadow`, `canary`, and `activate`. Active runtime policy writes happen only after gate pass and quality-signal checks.
- Added real quality-signal storage and runtime snapshot aggregation for retry rate, cancel rate, report-save count, citation hit count, retrieval hit rate, and long-task failure rate.
- Added `/api/self-evolution/board`, candidate generation, quality-signal, quality-snapshot, canary, and activate APIs.
- Added a console Self-Evolution Board showing candidate runs, release stage, traffic percent, gate checks, quality signals, and actions.

Verification:
- `python -m py_compile clawos\reflection\self_evolution.py clawos\memoryos\memory_store.py clawos\clawos_server.py`: passed.
- Bundled Node syntax check for `clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_self_evolution`: `7 tests OK`.
- `python -m unittest clawos.tests.test_runtime_task_control`: `14 tests OK`.
- `python -m unittest clawos.tests.test_frontend_static`: `23 tests OK`.
- Related governance suite: `47 tests OK`.
- `python -m unittest discover -s clawos\tests`: `170 tests OK`.

Known notes:
- Self-evolution still blocks automatic code/source/script changes by design.
- Worker benchmark evidence is deterministic and closed-loop; future production hardening should add an optional long-running external benchmark mode that invokes full scripts against real user corpora.

### 2026-06-28 - Enterprise document stack: PDF, Typst, PaddleOCR, and Office engines

Completed:
- Upgraded PDF ingestion from plain text extraction to a layered academic parsing stack: PyMuPDF for layout/page/block extraction, pdfplumber for table-aware text extraction, and optional GROBID TEI parsing through `GROBID_BASE_URL`.
- Preserved fallback behavior for competition demos: if enhanced parsers are missing or fail, ingestion still falls back to `pdftotext` and then `pypdf`.
- Added extraction metadata for downstream paper reading quality gates: extractor chain, page count, OCR-required pages, layout awareness, sections, tables, figures, references, title, authors, and abstract when available.
- Upgraded report PDF generation to prefer Typst when the local `typst` binary is installed. The existing ReportLab journal-style renderer remains as the offline fallback.
- Added PaddleOCR-first offline OCR resolution for scanned PDFs in `KnowledgeService`, with existing sidecar OCR and Tesseract paths retained as fallbacks.
- Upgraded Office artifact generation to prefer mature engines: `openpyxl` for XLSX create/edit and `python-pptx` for PPTX create/edit, while keeping the existing stdlib OpenXML implementation as fallback.
- Extended `/api/workspace/capabilities` so the frontend and Ops checks can report whether PyMuPDF, pdfplumber, GROBID, PaddleOCR, Typst, openpyxl, and python-pptx are actually available on the machine.
- Added regression coverage for enhanced PDF metadata, Typst-preferred PDF generation, PaddleOCR/layout capability wiring, and professional Office engine fallbacks.

Verification:
- `python -m py_compile clawos\memoryos\document_ingestion.py clawos\services\knowledge_service.py clawos\workspace_services.py clawos\office_artifacts.py clawos\clawos_server.py`: passed.
- `python -m unittest clawos.tests.test_memoryos_mvp clawos.tests.test_workspace_services`: `29 tests OK`.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_model_provider clawos.tests.test_runtime_task_control`: `61 tests OK`.
- `python -m unittest clawos.tests.test_routing_memory clawos.tests.test_retrieval_reranker`: `25 tests OK`.
- `python -m unittest discover -s clawos\tests`: `174 tests OK`.

Known notes:
- GROBID is intentionally optional and expects a separately running local service configured with `GROBID_BASE_URL`; this keeps offline deployments deterministic while allowing paper-grade TEI parsing when installed.
- Typst and PaddleOCR are also local-install dependencies. The code now detects and uses them, but final quality should still be validated on the target Windows machine after installing the binaries/models.
- This closes the architecture and code path for enterprise document parsing/generation. The next quality jump is a real corpus acceptance run with user papers, scanned Chinese PDFs, and generated Office deliverables.

### 2026-06-29 - ClawOS Enterprise Delivery Room super Skill

Completed:
- Added `competition_delivery_package`, a judge-facing delivery-package tool that reads project evidence from the business plan, architecture notes, project context, MTClaw integration docs, roadmap/readiness notes, architecture images, and plan documents.
- Registered the super Skill `clawos_enterprise_delivery_room`, with a replay script at `clawos/skills/skill_clawos_enterprise_delivery_room.py`.
- The generated package contains `delivery_index.md`, `executive_brief.md`, `technical_evidence.md`, `demo_runbook.md`, `judge_qa.md`, and `risk_register.md`.
- Wired the tool into `functions.jsonl`, `tool_runner`, `scenario_tools`, and `ToolSecurityPolicy`; it is path-scoped and treated as a confirmation-required write tool.
- Fixed a real import-order risk: `scenario_tools.py` and `tool_runner.py` now append `memoryos` to `sys.path` instead of inserting it before the top-level package, preventing `services` import shadowing.

Verification:
- `python -m py_compile clawos\scripts\scenario_tools.py clawos\scripts\tool_runner.py clawos\security\policy.py`: passed.
- `python -m unittest clawos.tests.test_skill_runtime clawos.tests.test_scenarios_e2e clawos.tests.test_runtime_security`: `18 tests OK`.
- `python -m unittest clawos.tests.test_skill_evolution clawos.tests.test_frontend_static`: `34 tests OK`.
- Final targeted rerun for the new Skill/tool/security tests: `3 tests OK`.

Known notes:
- `tmp/pdfs/*` still contains local untracked PDF scratch artifacts and must not be added to Git.
- The super Skill generates delivery artifacts under the requested output directory; runtime artifacts should stay out of commits.
- MTTBook/MTT AIBOOK real-device validation remains separate and still pending hardware availability.

Recommended next step:
- Add a visible console action for the Enterprise Delivery Room, then optionally feed its generated package back into the knowledge base for follow-up judge Q&A and presentation generation.

### 2026-06-29 - Enterprise Delivery Room console loop and DeepSeek acceptance

Completed:
- Added a Knowledge view `企业交付室` panel that runs `clawos_enterprise_delivery_room` as a one-click workflow.
- The console now displays package directory, readiness score, missing checks, evidence counts, and generated artifact paths.
- `competition_delivery_package` now returns `knowledge_items` for the generated index, executive brief, technical evidence, demo runbook, judge Q&A, and risk register.
- Added `保存到知识库` support for Enterprise Delivery Room outputs; saved items enter the project knowledge library and can be used for follow-up judge Q&A prompts.
- Added frontend/static and scenario regression coverage for the new workflow.

Verification:
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_scenarios_e2e.ScenarioEndToEndTests.test_competition_delivery_package_generates_enterprise_artifacts clawos.tests.test_skill_runtime.SkillRuntimeTests.test_enterprise_delivery_room_skill_generates_package`: `29 tests OK`.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m py_compile clawos\scripts\scenario_tools.py`: passed.

DeepSeek acceptance:
- `evaluate_model_acceptance.py --provider deepseek --model deepseek-chat --suite clawos\benchmarks\core_e2e_v1.json --out output\deepseek_core_e2e_report.json`: `passed_count=4 failed_count=0 score=20/20 rate=1.0`.
- `evaluate_model_acceptance.py --provider deepseek --model deepseek-chat --out output\deepseek_acceptance_report.json`: `passed_count=30 failed_count=0 score=150/150 rate=1.0`.
- `deepseek_retrieval_benchmark.py --model deepseek-chat --out output\deepseek_retrieval_benchmark.json`: `ok=True`, `chat_ok=True`, `embeddings_status=404`, `recall=1.0`, `mrr=0.875`, `judge_hit_rate=1.0`.

Known notes:
- DeepSeek reports under `output\deepseek_*.json` are local ignored evidence and must not be committed.
- DeepSeek public compatible API did not expose embeddings in this run (`404`), so the retrieval benchmark remains DeepSeek query/judgment plus local vector recall.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add a browser-level smoke check for the Enterprise Delivery Room panel and then build the multi-agent Reviewer pass on top of the saved delivery package.

### 2026-06-29 - DeepSeek + Qwen3 Hybrid RAG full-chain acceptance

Completed:
- Added `clawos/scripts/hybrid_rag_acceptance.py` to validate the full chain: DeepSeek query rewrite, Qwen3-Embedding + Chroma vector recall, Qwen3-Reranker top-k precision ranking, DeepSeek grounded answer generation, and DeepSeek answer judging.
- Added deterministic unit coverage in `clawos/tests/test_hybrid_rag_acceptance.py` for JSON parsing, ID normalization, model file checks, and metric aggregation.
- The script uses API keys only from the process environment and writes no secret values to the report.

Verification:
- `python -m py_compile clawos\scripts\hybrid_rag_acceptance.py`: passed.
- `python -m unittest clawos.tests.test_hybrid_rag_acceptance`: `4 tests OK`.
- Real full-chain run:
  `python clawos\scripts\hybrid_rag_acceptance.py --model deepseek-chat --base-url https://api.deepseek.com/v1 --out output\deepseek_hybrid_rag_acceptance.json`
  returned `ok=True`, `chat_ok=True`, `embedding=qwen3`, `vector_recall_at_30=1.0`, `rerank_recall_at_5=1.0`, `rerank_mrr=1.0`, `citation_hit_rate=1.0`, `judge_grounded_rate=1.0`, `judge_expected_citation_rate=1.0`.

Known notes:
- DeepSeek `/embeddings` probe still returned `404`; the accepted architecture is DeepSeek for reasoning/query/answer/judge plus local Qwen3 embedding/reranker for knowledge retrieval.
- The report `output\deepseek_hybrid_rag_acceptance.json` is ignored and should not be committed.
- Observed case latency is dominated by local Qwen3 reranker + DeepSeek calls; current report p50 was about `17.3s` and p95 about `20.2s` for the synthetic complex cases.

Recommended next step:
- Add a console/ops entry for running or displaying Hybrid RAG acceptance evidence, then benchmark latency with smaller recall windows or cached rerank batches for demo mode.

### 2026-06-29 - Fixed-role multi-agent self-review committee

Completed:
- Added `multi_agent_review_committee`, a deterministic fixed-role review squad for ClawOS delivery readiness.
- The squad roles are `PlannerAgent`, `ResearchAgent`, `ProductWriterAgent`, `RiskAgent`, and `JudgeAgent`; each returns findings, actions, and a score.
- Registered the Skill `clawos_self_review_committee` plus replay script `clawos/skills/skill_clawos_self_review_committee.py`.
- Added Knowledge view controls to run the committee, display role/priorities tables, save the committee report back to the project knowledge base, and continue judge-style follow-up questions.
- Wired the tool into `functions.jsonl`, `tool_runner`, `scenario_tools`, and `ToolSecurityPolicy`; it is path-scoped and confirmation-required like the Enterprise Delivery Room.

Verification:
- `python -m unittest clawos.tests.test_scenarios_e2e clawos.tests.test_skill_runtime`: `14 tests OK`.
- `python -m unittest clawos.tests.test_runtime_security clawos.tests.test_frontend_static`: `33 tests OK`.
- `python -m py_compile clawos\scripts\scenario_tools.py clawos\scripts\tool_runner.py clawos\skills\skill_clawos_self_review_committee.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Real project dry run returned committee `score=92/100`, delivery readiness `100/100`, and report path `output\delivery\ClawOS\committee\multi_agent_review.md`.

Known notes:
- MTTBook real-machine validation remains the top P0 blocker until hardware is available.
- Generated committee reports stay under `output/` and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add a visible trace timeline for the five fixed roles so judges can inspect how the committee reached the final score and P0/P1/P2 priorities.

### 2026-06-29 - Multi-agent execution squad and quality gate arbitration

Completed:
- Upgraded `multi_agent_review_committee` from a review-only committee into a fixed-role execution squad.
- The squad now runs `PlannerAgent`, `ResearchAgent`, `BuilderAgent`, `ReviewerAgent`, `RiskAgent`, and `JudgeAgent`.
- Added `execution_trace` output so the console can show how roles moved through plan, evidence, build, review, risk gate, judge decision, and rework.
- Added `quality_gate` thresholds: default final score >= 85, RiskAgent >= 80, JudgeAgent >= 85.
- Added `arbitration_rounds`; when RiskAgent or JudgeAgent is below threshold, the run becomes `revision_required` and opens required rework instead of silently approving.
- Updated the Knowledge view panel from review-only wording to a multi-agent execution squad with trace, gate, and arbitration tables.

Verification:
- `python -m py_compile clawos\scripts\scenario_tools.py clawos\scripts\tool_runner.py clawos\skills\skill_clawos_self_review_committee.py`: passed.
- `python -m unittest clawos.tests.test_scenarios_e2e clawos.tests.test_skill_runtime`: `14 tests OK`.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_runtime_security`: `33 tests OK`.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Real project dry run returned `score=92/100`, `quality_gate.status=revision_required`, `RiskAgent score 76 < 80`, `trace_steps=7`, and two arbitration rounds: `blocked` then `pending_recheck`.

Known notes:
- The gate is intentionally stricter than the final score: current total score is high, but MTTBook hardware evidence keeps RiskAgent below release threshold.
- Generated reports remain under `output/` and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- After MTTBook arrives, rerun the execution squad and require `quality_gate.status=pass` before final submission rehearsal.

### 2026-06-29 - Rework loop and five-scenario complex task acceptance

Completed:
- Extended `multi_agent_review_committee` with `rework_loop`, so a failed quality gate now triggers Builder rework, Reviewer recheck, RiskAgent rescore, and JudgeAgent rescore.
- The loop ends as `pass`, `revision_required`, or explicit `blocked`; current MTTBook hardware evidence remains an external blocker and is reported as `blocked_external_dependency` instead of being silently accepted.
- The console now displays rework rounds alongside trace, gate, arbitration, roles, and priorities.
- Expanded `hybrid_rag_acceptance.py` into a five-scenario complex-task benchmark covering `research`, `office`, `code`, `learning`, and `competition`.
- Each complex-task case now records `pass`, citation hit, latency, top reranked evidence, answer/judge output, and `reproducible_io` with task/query/expected slug and generated output.

Verification:
- `python -m unittest clawos.tests.test_scenarios_e2e clawos.tests.test_skill_runtime clawos.tests.test_frontend_static clawos.tests.test_hybrid_rag_acceptance`: `46 tests OK`.
- `python -m py_compile clawos\scripts\scenario_tools.py clawos\scripts\hybrid_rag_acceptance.py clawos\scripts\tool_runner.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Real DeepSeek + Qwen3 full-chain complex-task run wrote ignored local report `output\deepseek_hybrid_rag_acceptance.json` and returned `ok=True`, `case_count=5`, `pass_rate=1.0`, `passed_count=5`, `failed_count=0`, `vector_recall_at_30=1.0`, `rerank_recall_at_5=1.0`, `rerank_mrr=1.0`, `citation_hit_rate=1.0`, `judge_grounded_rate=1.0`, `judge_expected_citation_rate=1.0`, `latency_p50_ms=19258.453`, `latency_p95_ms=21486.345`.

Known notes:
- The API key was supplied via environment for the live run and is not written to code, reports, or this context.
- `output\deepseek_hybrid_rag_acceptance.json` is ignored evidence and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.
- MTTBook real-machine evidence remains the main blocker for turning the multi-agent gate from blocked to pass.

Recommended next step:
- Add a compact console card that loads the latest complex-task acceptance report and shows per-scenario pass/fail, citation hit, latency, and report path without exposing secrets.

### 2026-06-29 - Multi-agent timeline and enterprise rubric matrix

Completed:
- Added `timeline` output to `multi_agent_review_committee`, turning raw trace rows into judge-facing timeline events with role, input, action, artifact, score, gate, status, and rework round.
- Added `rubric_matrix` with seven enterprise scoring dimensions: Functionality, Evidence Quality, Stability, Security Governance, Business Narrative, Reproducibility, and Demo Determinism.
- The Markdown committee report now includes `Multi-Agent Trace Timeline` and `Enterprise Rubric Matrix` sections before the raw execution trace.
- The Knowledge console now renders a visual timeline and enterprise rubric summary/table instead of relying only on raw trace tables.

Verification:
- `python -m py_compile clawos\scripts\scenario_tools.py clawos\scripts\tool_runner.py`: passed.
- `python -m unittest clawos.tests.test_scenarios_e2e clawos.tests.test_skill_runtime clawos.tests.test_frontend_static`: `41 tests OK`.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- Real project dry run returned `score=92/100`, `quality_gate.status=revision_required`, `timeline_steps=9`, `rubric_score=87.72/100`, and seven rubric categories.

Known notes:
- Rubric score is strong, but release remains evidence-gated because MTTBook hardware validation is still missing.
- Generated committee reports remain under `output/` and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add a compact console card for the latest DeepSeek+Qwen complex-task acceptance report, then wire rubric categories to per-scenario evidence once the report card exists.

### 2026-06-30 - V2 rework artifacts and complex acceptance report card

Completed:
- `multi_agent_review_committee` now writes real V2 rework artifacts under `output/delivery/.../rework_v2`: risk register, judge Q&A, demo runbook, and V2 index.
- Each rework round now records `v2_artifacts`, `reviewer_diff`, and `judge_decision`; the Markdown report and console rework table expose the V1->V2 review, artifacts, unresolved blockers, and rescore decision.
- Added read-only `/api/acceptance/deepseek-qwen/latest`, which summarizes the latest ignored DeepSeek+Qwen complex-task report without exposing secrets.
- The Knowledge console now has a compact DeepSeek+Qwen acceptance card showing 5-scenario pass/fail, citation hit, latency P50/P95, retrieval ranks, model, and report path.

Verification:
- `python -m py_compile clawos\scripts\scenario_tools.py clawos\clawos_server.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_scenarios_e2e clawos.tests.test_skill_runtime clawos.tests.test_frontend_static clawos.tests.test_routing_memory`: `66 tests OK`.

Known notes:
- `output\deepseek_hybrid_rag_acceptance.json` remains ignored local evidence and should not be committed.
- V2 rework artifacts generated by real runs remain under `output/` and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.
- MTTBook real-machine evidence remains the main blocker for turning the multi-agent quality gate from blocked to pass.

Recommended next step:
- Add a browser smoke test or screenshot check for the Knowledge console acceptance card, then wire the rubric matrix to the latest scenario-level evidence for even stronger judge-facing traceability.

### 2026-06-30 - 25-case Hybrid RAG acceptance and multi-agent disagreement log

Completed:
- Expanded `hybrid_rag_acceptance.py` from 5 complex cases to 25 cases: `research`, `office`, `code`, `learning`, and `competition` now each have 5 cases.
- The hybrid report still preserves reproducible input/output, citation hit, latency, answer, judge result, top reranked evidence, and now adds explicit `failure_reason` plus per-scenario aggregate counts.
- Added structured `disagreement_log` to `multi_agent_review_committee` so ReviewerAgent, RiskAgent, and JudgeAgent can object, cite evidence, assign a decision owner, record arbitration, and mark whether rework is required.
- The committee Markdown report now includes `Conflict Debate And Arbitration Log`, and the console renders the dispute table next to arbitration and rework rounds.

Verification:
- `python -m py_compile clawos\scripts\hybrid_rag_acceptance.py clawos\scripts\scenario_tools.py clawos\clawos_server.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_hybrid_rag_acceptance clawos.tests.test_scenarios_e2e clawos.tests.test_skill_runtime clawos.tests.test_frontend_static clawos.tests.test_routing_memory`: `72 tests OK`.

Known notes:
- The 25-case suite is implemented but a new live DeepSeek+Qwen run has not been executed in this block, to avoid consuming API/model time by default.
- `output\deepseek_hybrid_rag_acceptance.json` remains ignored local evidence and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.
- MTTBook real-machine evidence remains the blocker for final pass.

Recommended next step:
- Run the 25-case DeepSeek+Qwen acceptance once quota and local model time are acceptable, then update the console report card from the new report and compare latency against the previous 5-case baseline.

### 2026-06-30 - Multi-agent audit board visualization

Completed:
- Upgraded the Knowledge console multi-agent result from table-first output to a visual audit board.
- Added role avatar swimlanes for Planner, Research, Builder, Reviewer, Risk, and Judge with score and latest role status.
- Added horizontal audit timeline, dispute cards for objector/evidence/decision/rework, and V1/V2 artifact diff cards for rework rounds.
- Kept raw trace, gate, arbitration, rework, role, rubric, and priority tables below the visual board for detailed audit drill-down.

Verification:
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `27 tests OK`.

Known notes:
- This block is frontend visualization only; no new live API run was executed.
- `output\deepseek_hybrid_rag_acceptance.json` remains ignored local evidence and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Start the local console and browser-smoke `/console` after running the multi-agent workflow to visually verify the audit board with a real payload.

### 2026-06-30 - BuilderAgent executable subtask workbench

Completed:
- Upgraded `BuilderAgent` from delivery-package writer to deterministic subtask executor inside `multi_agent_review_committee`.
- Builder now executes six Planner subtasks with tool evidence: RAG retrieval, report generation, code analysis, DeepSeek+Qwen benchmark summary, knowledge-base save candidate, and demo runbook generation.
- Builder writes `builder_execution_report.md` and `builder_demo_runbook.md` under the committee output directory and returns structured `builder_execution` plus `builder_review`.
- Reviewer/Risk/Judge findings now explicitly review Builder execution evidence; trace/timeline includes B1-B6 Builder tool execution steps.
- Console audit board now shows Builder Execution task cards with task/tool/status/output/artifact before the broader timeline and dispute panels.

Verification:
- `python -m py_compile clawos\scripts\scenario_tools.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_scenarios_e2e clawos.tests.test_skill_runtime clawos.tests.test_frontend_static`: `41 tests OK`.

Known notes:
- Builder benchmark evidence uses the latest ignored report if present, otherwise records a fallback summary; no live API run is started by this committee tool.
- `output\deepseek_hybrid_rag_acceptance.json` remains ignored local evidence and should not be committed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Browser-smoke the Knowledge console multi-agent flow with a real committee payload, then consider wiring Builder execution cards to expandable raw evidence snippets.

### 2026-06-30 - Console space navigation audit and fix

Completed:
- Added a real top-level `spaceSwitcher` navigation strip for all 15 console spaces: chat, search, knowledge, projects, dash, memory, tools, tasks, reflection, evolution, skills, benchmarks, scenes, security, and ops.
- Unified all `button[data-view]` navigation through one controller so side nav, space switcher, and More Apps drawer update the active button state, page title/subtitle, URL hash, and visible `view-*` panel consistently.
- Converted More Apps drawer entries from ad hoc inline navigation calls to the shared `data-view` contract, so low-frequency spaces are no longer fake or disconnected sections.
- Added a frontend static regression test that checks every `data-view` has a matching real `view-*` target and prevents future side-nav-only binding regressions.

Verification:
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `28 tests OK`.
- Local `/console` browser smoke on `127.0.0.1:8765`: clicked all 15 space switcher entries; every entry updated hash, active title, active switcher button, and real visible panel. Also clicked More Apps -> Ops Center and confirmed the drawer closed while `view-ops` became active.

Known notes:
- The first plain `node --check` attempt failed because `node` is not on PATH; the bundled Codex Node executable passed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add a lightweight automated browser smoke script for `/console` space navigation so the 15-space click check can run in CI or pre-demo validation without manual browser control.

### 2026-06-30 - Product shell unification and capability index

Completed:
- Unified the home and product top navigation around the same product hierarchy: `ClawOS / Personal Agent OS`, `Overview`, `Product Map`, and `Console`.
- Added a compact console layer strip (`Overview -> Product Map -> Console`) so the operating console clearly reads as the final action layer of the same product.
- Added shared visual tokens in `site.css` for card radius, pill radius, glass surfaces, brand/accent colors, and reused them across shell navigation, CTA buttons, and product capability cards.
- Reworked the product page from a static tab-like explanation block into a real Console Capability Index with six cards linking to true console spaces: MemoryOS, Tool Router, Task Trace, Skill Evolution, Security, and Ops.
- Added frontend static coverage for shared navigation, visual token selectors, product capability links, and removal of the fake product tab bar.

Verification:
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `29 tests OK`.
- Browser smoke with an in-session static server: home shows `Personal Agent OS` and `View Product Map`; product shows 6 capability cards and no `.tab-bar`; clicking `MemoryOS` navigates to `/console#memory`, and console opens `view-memory` with title `记忆治理` plus the layer strip.

Known notes:
- FastAPI smoke was not used for final visual validation because the bundled Python lacks `httpx`; a static browser smoke covered the requested shell/navigation behavior.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add a small reusable static/browser smoke script for the product shell so pre-demo checks can verify all six product capability links, not just the MemoryOS path.

### 2026-06-30 - Home hero polish and console product navigation

Completed:
- Replaced the home scan-wall labels from literal `* Agent` names with lifestyle/narrative labels (`Urban Signal`, `Archive Mode`, `Study Drift`, `Memory Club`, `Patch Culture`, `Desk Ritual`, `Skill Drop`) so the portrait imagery reads as a trend/culture sequence rather than mismatched agent avatars.
- Adjusted the home hero composition: the robotic arm now sits higher and slightly right with a stable static opacity, while the title stack sits lower with more visual breathing room.
- Fixed a browser-observed hero animation issue where the robotic arm opacity could remain at the animation start value; opacity is now controlled by static CSS and the animation only moves/scales the arm.
- Added an explicit console sidebar product navigation strip with direct links to `首页` and `产品页`, plus an active `控制台` state, so users can leave the console without relying on the subtle header layer strip.
- Added frontend static coverage for the new lifestyle labels, hero placement tokens, and console product navigation.

Verification:
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `30 tests OK`.
- Browser smoke with an in-session static server: home scan labels rendered as the new lifestyle labels; hero arm transform was offset right and final opacity was `0.94`; console product nav exposed `首页 -> /`, `产品页 -> /product`, and active `控制台`.

Known notes:
- `tmp/pdfs/*` remains local scratch output and must not be staged.
- Current branch already includes the previous unpushed product-shell commit.

Recommended next step:
- Take one visual screenshot pass on desktop and mobile before pushing, focusing on hero overlap, console side navigation density, and product page card scanning.

### 2026-06-30 - Product hero console visual replacement

Completed:
- Replaced the product page hero right-side fluid/abstract image with a real ClawOS console screenshot supplied from the current UI.
- Compressed the supplied console screenshot into `clawos/static/assets/hero/clawos-console-product.jpg` for web use, reducing the asset to about 112 KB while preserving the interface signal.
- Removed text-like decorative content from the product hero visual area; the right side now contains the console preview plus three purely visual glyph layers.
- Added static coverage to ensure the product hero uses the console preview, includes non-text visual glyphs, and no longer references the old fluid image inside the hero section.

Verification:
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `30 tests OK`.
- Browser smoke with an in-session static server: product hero had `product-console-visual`, three `.visual-glyph` elements, loaded `/assets/hero/clawos-console-product.jpg` at natural width 1600, had no visual text, and did not reference the old `217661...jpg` image in the hero.

Known notes:
- `tmp/pdfs/*` remains local scratch output and must not be staged.
- Current branch already includes two previous unpushed frontend commits.

Recommended next step:
- Do one visible desktop/mobile screenshot review of the product hero before push, focusing on crop, tilt, and whether the console image remains readable enough beside the headline.

### 2026-06-30 - Console structure and anti-compression cleanup

Completed:
- Split the console space switcher into two explicit groups: `工作前台` for user-facing workspaces and `系统后台` for runtime, governance, evaluation, security, and ops spaces.
- Renamed the sidebar main label to `前台工作` and added a `后台系统` label above system settings/tool evaluation so the left rail matches the same information architecture.
- Added an anti-compression CSS layer for all console tables: dense data tables now use horizontal overflow, `table-layout:auto`, horizontal writing mode, and normal word breaking instead of squeezing Chinese into vertical-looking columns.
- Added wider minimum widths for task, tool, security, ops, evolution, and benchmark tables so runtime records can breathe instead of forcing unreadable narrow columns.
- Added frontend static coverage for the前台/后台 grouping and anti-compression table rules.

Verification:
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: `31 tests OK`.
- Browser smoke with an in-session static server on `/console#tasks`: active view was `view-tasks`, top groups showed `工作前台` and `系统后台`, sidebar labels showed `前台工作` / `后台系统`, and task table computed styles were `table-layout:auto`, `min-width:920px`, `writing-mode:horizontal-tb`, with horizontal overflow enabled.

Known notes:
- `tmp/pdfs/*` remains local scratch output and must not be staged.
- Current branch already includes three previous unpushed frontend commits.

Recommended next step:
- Do a visible screenshot pass on the busiest backend spaces (`任务`, `权限`, `运维`) to tune individual column priorities if any real production payload still feels too dense.

### 2026-06-30 - Runtime service split and unified Run schema

Completed:
- Added service-layer boundaries for `workflow_engine`, `agent_orchestration_service`, `artifact_storage`, `evaluation_service`, and `runtime_records`.
- Introduced unified `clawos.run.v1` Run / Artifact / Evidence / FailureCase records for runtime tasks, multi-agent committee results, and DeepSeek+Qwen acceptance reports.
- Added a generic workflow state machine for multi-agent rework gates, report generation, acceptance execution, artifact saving, and pass/fail/blocked outcomes.
- DeepSeek+Qwen latest acceptance API now returns previous compact-card fields plus `run_record` and `failure_library` for failed, misjudged, low-quality, or citation-miss samples.
- Multi-agent committee output now includes normalized `run_record` evidence with artifacts, quality-gate failures, disagreements, and state-machine rework status.
- Added `/api/runtime/schema`, `/api/runtime/runs/latest`, and `/api/runtime/failure-cases`.
- Split `clawos/static/assets/console.modules.js` from the main console bundle and added a compact Run/Artifact/Evidence card to the Task Trace space.

Verification:
- `python -m py_compile clawos\services\runtime_records.py clawos\services\workflow_engine.py clawos\services\artifact_storage.py clawos\services\evaluation_service.py clawos\services\agent_orchestration_service.py clawos\clawos_server.py clawos\scripts\scenario_tools.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.modules.js`: passed.
- `python -m unittest clawos.tests.test_runtime_records clawos.tests.test_frontend_static clawos.tests.test_scenarios_e2e`: `44 tests OK`.
- `python -m unittest discover -s clawos\tests`: `200 tests OK`.

Known notes:
- Browser smoke on a temporary static localhost URL was not completed because the in-app browser security policy rejected `http://127.0.0.1:8791`; no workaround was attempted. Static tests and the full unit suite passed.
- The new runtime record layer is a normalized service boundary, not yet a full database migration for all historical run artifacts.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Persist Run/Artifact/Evidence/FailureCase records into durable tables and route every artifact-producing workflow through `ArtifactStorage` instead of direct ad hoc output paths.

### 2026-07-01 - Durable runtime tables and meeting audio workflow

Completed:
- Added durable `run_records`, `run_artifacts`, `run_evidence`, and `run_failure_cases` tables in MemoryOS, with read/list helpers for latest runs and failure samples.
- Routed task completion, multi-agent committee normalization, DeepSeek+Qwen acceptance summaries, report files, and delivery artifacts through the unified Run/Artifact/Evidence/FailureCase model where this service layer owns the workflow result.
- Wired `ArtifactStorage` and `WorkflowEngine` into evaluation, multi-agent orchestration, scenario report generation, and task persistence so new artifacts carry traceable run evidence instead of only ad hoc files.
- Added `MeetingAudioService` with optional local ASR via `faster-whisper` first and whisper.cpp/whisper CLI fallback, plus PCM-WAV energy VAD splitting, label/heuristic diarization, structured meeting cards, knowledge save, and durable Evidence/Artifact creation.
- Extended workspace meeting audio import so audio plus sidecar/provided transcript produces a meeting card, transcript artifact, knowledge item, durable run record, and workflow gate result.
- Added a deterministic meeting-audio acceptance suite covering two speakers, noisy room, long meeting/VAD, Chinese-English mix, interruptions, and leading silence.

Verification:
- `python -m py_compile clawos\memoryos\memory_store.py clawos\services\runtime_records.py clawos\services\artifact_storage.py clawos\services\workflow_engine.py clawos\services\evaluation_service.py clawos\services\agent_orchestration_service.py clawos\services\meeting_audio_service.py clawos\workspace_services.py clawos\clawos_server.py clawos\scripts\scenario_tools.py clawos\scripts\meeting_audio_acceptance.py`: passed.
- `python -m unittest clawos.tests.test_runtime_records clawos.tests.test_workspace_services`: `24 tests OK`.
- `python clawos\scripts\meeting_audio_acceptance.py`: `6/6 passed`, `pass_rate=1.0`.
- `python -m unittest clawos.tests.test_scenarios_e2e clawos.tests.test_scenario_benchmarks clawos.tests.test_runtime_records clawos.tests.test_workspace_services clawos.tests.test_frontend_static`: `70 tests OK`.
- Bundled Node syntax checks for `clawos\static\assets\console.js` and `clawos\static\assets\console.modules.js`: passed.
- `python -m unittest discover -s clawos\tests`: `203 tests OK`.

Known notes:
- True ASR depends on locally installed `faster-whisper` or a whisper.cpp/whisper CLI binary and a model file; this block wires the engine detection/fallback but did not benchmark real model inference.
- Current VAD is a lightweight offline PCM-WAV energy splitter, not Silero/WebRTC-grade VAD.
- Current diarization is speaker-label based with a deterministic heuristic fallback, not pyannote-style embedding clustering.
- Meeting audio acceptance uses generated WAV plus sidecar transcripts for deterministic CI-like closure; add real meeting files before claiming production ASR quality.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Install and benchmark one real local ASR path (`faster-whisper` small/medium or whisper.cpp quantized model), then add real noisy/long meeting fixtures with WER, diarization error rate, and action-item extraction accuracy.

### 2026-07-02 - Real faster-whisper small ASR and console one-click meeting workflow

Completed:
- Installed `faster-whisper` in the local Python environment and warmed the `small` model for offline reuse.
- Changed ClawOS local ASR default to `faster-whisper small` with CPU/int8 and model cache under user-local cache (`%LOCALAPPDATA%\ClawOS\asr_models`) so model files do not slow repo scans or enter Git.
- Added `clawos/scripts/install_local_asr_small.py` for reproducible setup and `clawos/scripts/meeting_audio_real_asr_eval.py` for real ASR acceptance with generated meeting speech.
- Added multipart `/api/workspace/meetings/audio/upload` so the console can upload an audio file, optionally include a transcript file/text, run ASR/VAD/diarization, save a meeting card to knowledge, and return Artifact/Run evidence.
- Added a Scene Workbench meeting-audio panel with file picker, optional transcript input, one-click processing, and compact meeting card / artifact / run result display.
- `WorkspaceServices.import_meeting_audio` now returns `transcript`, enabling frontend display and ASR evaluation metrics.

Verification:
- `python clawos\scripts\install_local_asr_small.py --model small --skip-pip`: model ready in `C:\Users\34712\AppData\Local\ClawOS\asr_models`.
- `python clawos\scripts\meeting_audio_real_asr_eval.py --out output\asr_real_eval`: `6/6 transcribed`, `avg_wer=0.0714`, `action_hit=0.9583`, `p95=7567.55ms`; report path `output\asr_real_eval\meeting_audio_real_asr_report.json`.
- Multipart upload smoke via FastAPI TestClient: HTTP `200`, `transcript_imported`, meeting card created, knowledge item saved, artifact returned, transcript returned.
- `python -m py_compile clawos\clawos_server.py clawos\services\meeting_audio_service.py clawos\workspace_services.py clawos\scripts\meeting_audio_real_asr_eval.py clawos\scripts\install_local_asr_small.py`: passed.
- `python -m unittest clawos.tests.test_workspace_services clawos.tests.test_frontend_static`: `49 tests OK`.
- Bundled Node checks for `clawos\static\assets\console.js` and `clawos\static\assets\console.modules.js`: passed.
- `python -m unittest discover -s clawos\tests`: `203 tests OK`.

Known notes:
- Real ASR evidence is stored under ignored `output\asr_real_eval`; do not commit the generated audio, report DB, or model cache.
- HF Hub emitted unauthenticated download and Windows symlink-cache warnings during model warmup; inference still worked.
- Current diarization remains label/heuristic, not speaker-embedding clustering.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add 5-10 real human-recorded meeting clips, including noisy rooms and speaker overlap, then track WER, diarization error rate, and action extraction accuracy against human labels.

### 2026-07-02 - Enterprise Search Evidence Engine

Completed:
- Added `services/search_evidence.py` as the shared Search/Evidence layer for provider retry, local cache, file-backed rate limiting, source ranking, credibility scoring, freshness scoring, JS-render fetch fallback, and citation consistency checks.
- Upgraded `web_search` to use provider fallback plus retry/cache/rate-limit/source scoring and to persist a durable `web_evidence` Run with source Evidence.
- Upgraded `web_fetch` to use shared fetch/cache/retry/rate-limit logic, optional `render_js=true` Playwright browser rendering, source quality scoring, and durable Run/Evidence persistence.
- Added `web_citation_check` for claim-to-source support checks and anti-hallucination gates with required rework for unsupported claims.
- Added `web_search_benchmark` offline acceptance suite covering official-source ranking, freshness ranking, citation gate, artifact output, and durable Run recording.
- Exposed `web_research` capability metadata in `/api/workspace/capabilities` and the console capability table: provider router, cache, retry, rate limit, source ranking, credibility, freshness, citation gate, anti-hallucination, benchmark, and browser rendering availability.

Verification:
- `python -m py_compile clawos\services\search_evidence.py clawos\scripts\tool_runner.py clawos\clawos_server.py`: passed.
- `python -m unittest clawos.tests.test_search_evidence clawos.tests.test_frontend_static clawos.tests.test_routing_memory`: `60 tests OK`.
- `web_search_benchmark` tool smoke: `3/3` passed, artifact created, durable run type `web_evidence`.
- Bundled Node checks for `clawos\static\assets\console.js` and `clawos\static\assets\console.modules.js`: passed.
- `python -m unittest discover -s clawos\tests`: `206 tests OK`.

Known notes:
- Real search coverage still depends on configured provider keys and runtime network permission; the new layer records provider attempts, failures, cache hits, and rate-limit status instead of hiding those constraints.
- JS-heavy rendering uses optional Playwright. If Playwright/browsers are unavailable, `render_js=true` reports an explicit `playwright_unavailable` fetch failure.
- Search cache, rate limit files, and benchmark artifacts are ignored under `clawos\data\search_evidence` and `output\search_evidence`.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add live provider smoke tests behind explicit network approval, then expand the offline search suite from 3 cases to 30-50 cases across news freshness, docs, papers, policy, product pages, Chinese pages, and JS-rendered pages.

### 2026-07-02 - Search 36-case gate, multi-agent citation gate, and ASR profile expansion

Completed:
- Expanded `web_search_benchmark` from 3 offline cases to 36 reproducible cases across official docs, news freshness, papers, policy, product info, Chinese web pages, and JS-render-required pages.
- Added category-level benchmark reporting, JS-render case counts, citation support counts, failure reasons, artifact output, and durable `web_evidence` run recording.
- Wired Multi-Agent ResearchAgent output through the shared citation consistency gate. ReviewerAgent and JudgeAgent now treat unsupported claims as rework blockers, and the committee report includes a dedicated Research Evidence Gate section.
- Saved the Research Evidence Gate as a knowledge item alongside the multi-agent committee report and builder workbench artifact.
- Expanded the real faster-whisper small ASR evaluation suite from 6 to 12 cases with clean, background-noise, overlap, echo, long-meeting, fast-speech, and quiet-speaker profiles; report now includes by-profile metrics.

Verification:
- `python -m unittest clawos.tests.test_search_evidence clawos.tests.test_scenarios_e2e clawos.tests.test_workspace_services`: 28 tests OK.
- `web_search_benchmark` tool smoke: 36/36 passed, pass_rate=1.0, 7 categories, 5 JS-render cases, durable run_type=`web_evidence`.
- `python clawos\scripts\meeting_audio_real_asr_eval.py --out output\asr_real_eval`: 12/12 transcribed, avg_wer=0.2301, action_hit=0.9583, p95=12609.16ms, report path `output\asr_real_eval\meeting_audio_real_asr_report.json`.
- `python -m unittest discover -s clawos\tests`: 207 tests OK.
- Bundled Node checks for `clawos\static\assets\console.js` and `clawos\static\assets\console.modules.js`: passed.
- `python -m py_compile clawos\scripts\tool_runner.py clawos\scripts\scenario_tools.py clawos\scripts\meeting_audio_real_asr_eval.py clawos\services\search_evidence.py`: passed.

Known notes:
- The search benchmark is intentionally offline and deterministic; live search quality still depends on configured provider keys, network permission, and provider coverage.
- ASR samples are generated speech plus deterministic noise/overlap/echo profiles. They exercise the real ASR pipeline, but human-recorded field audio is still needed before claiming production meeting accuracy.
- Generated reports/audio remain ignored under `output\`; `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Add a small human-recorded meeting fixture pack with ground-truth transcripts and speaker labels, then add live search provider smoke tests behind explicit network/key approval.

### 2026-07-03 - Console frontstage IA, project workspace, and web-search toggle

Completed:
- Reduced home navigation to the three primary product routes: home, product, and console.
- Removed the duplicate console header product-layer strip, keeping page navigation in the left rail.
- Adjusted the home robotic arm placement and mobile opacity to reduce title overlap.
- Tightened the console frontstage: work spaces remain visible, while system/backend surfaces are visually collapsed behind backend management and drawer entry points.
- Reworked Knowledge Library into a user-facing workspace with mode-specific shells for all/research/learning/writing/project, clear upload affordance, graph/node summary, and advanced knowledge tools hidden behind a backend tools toggle.
- Clarified Project Workspace ownership: project uploads, root path, goal, request preview, and explicit send-to-chat action. Project action buttons now produce visible in-page feedback instead of silently filling the hidden chat composer.
- Added a chat web-search toggle; when enabled, the message requests `web_search` and asks the model to preserve clickable source links. Chat rendering now auto-links http(s) URLs.

Verification:
- `python -m unittest clawos.tests.test_frontend_static`: 33 tests OK.
- Bundled Node syntax checks for `clawos\static\assets\console.js` and `clawos\static\assets\console.modules.js`: passed.

Known notes:
- This block is frontend/static behavior only. It does not run a live browser screenshot pass.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Run a live browser walkthrough of `/console#knowledge` and `/console#projects` against the FastAPI server before demo, then tune spacing/copy from the actual viewport.

### 2026-07-04 - Live Search Provider Health and Console Report Card

Completed:
- Added `clawos/scripts/search_live_acceptance.py` for Provider Health + live smoke reporting across 40 cases covering official docs, news freshness, papers, policy, product docs, Chinese web, JS pages, developer docs, security, and education.
- Added provider health aggregation to `SearchEvidenceEngine.search()` and exposed `web_search_live_benchmark` in `tool_runner.py` and `functions.jsonl`.
- Added `/api/search/live/latest` to read the newest durable live search report without triggering network calls from the UI.
- Added a console compact card for live search reports: provider success rate, pass rate, citation hit, p50/p95 latency, by-scenario stats, and failure reasons.

Verification:
- `python clawos\scripts\search_live_acceptance.py --offline-mock --limit-cases 40 --out output\search_evidence --no-cache`: 40/40 passed, citation_hit_rate=1.0, provider_success_rate=1.0.
- Real network smoke with `--providers tavily,serpapi,bing,duckduckgo --limit-cases 40`: report generated at `output\search_evidence\live_search_report.json`; 0/40 passed because Tavily/SerpAPI/Bing keys were not configured and DuckDuckGo returned HTTPError/empty results in this environment. The report records these provider failure reasons explicitly.
- `python -m py_compile clawos\services\search_evidence.py clawos\scripts\tool_runner.py clawos\scripts\search_live_acceptance.py clawos\clawos_server.py`: passed.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m unittest clawos.tests.test_search_evidence clawos.tests.test_frontend_static`: 37 tests OK.
- `python -m unittest discover -s clawos\tests`: 209 tests OK.

Known notes:
- Generated live/offline reports and runtime cache files remain ignored under `output\search_evidence`; do not stage them.
- Live search acceptance is now observable rather than hidden. A failing provider health card means the runtime needs stable provider credentials/network/parser work, not that the report pipeline failed.
- `tmp/pdfs/*` remains local scratch output and must not be staged.

Recommended next step:
- Configure at least one stable search provider key, rerun the 40-case live suite, and tune provider-specific result parsing/ranking until live pass rate and citation hit rate become competition-grade.

### 2026-07-05 - Tavily live search closure and console front/back polish

Completed:
- Configured Tavily locally via ignored `clawos/.env`; no provider key was committed.
- Added `.env` loading to `clawos/scripts/tool_runner.py` so CLI tools and live benchmark scripts see the same local provider configuration as the server.
- Tuned the live search acceptance suite's security-news case toward official CISA evidence after Tavily surfaced a non-official event page.
- Reworked the Knowledge Library console into clearer product layers: frontstage metrics, a frontstage work-zone label, a stateful backend management entry, and a backend section label for reports, acceptance, delivery, OCR, and citation QA.

Verification:
- `python clawos\scripts\search_live_acceptance.py --providers tavily --limit-cases 5 --out output\search_evidence --no-cache --retries 1`: 5/5 passed using ignored local `.env`.
- `python clawos\scripts\search_live_acceptance.py --providers tavily --limit-cases 40 --out output\search_evidence --no-cache --retries 1`: 40/40 passed, citation_hit_rate=1.0, provider_success_rate=1.0, latency_p50_ms=787.46, latency_p95_ms=1606.36, report path `output\search_evidence\live_search_report.json`.
- `python -m unittest clawos.tests.test_frontend_static clawos.tests.test_search_evidence`: 37 tests OK.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\console.js`: passed.
- `python -m py_compile clawos\scripts\search_live_acceptance.py clawos\scripts\tool_runner.py clawos\services\search_evidence.py clawos\clawos_server.py`: passed.
- `python -m unittest discover -s clawos\tests`: 209 tests OK.

Known notes:
- `clawos/.env`, `output\search_evidence`, and `tmp/pdfs/*` remain local/ignored or untracked and must not be staged.
- Full tests still mutate `clawos/skills/skill_registry.jsonl` usage counters; restore that file before committing.
- Live report quality now depends on the configured Tavily account quota and network availability.

Recommended next step:
- Start the server and do a browser walkthrough of `/console#knowledge`: verify the frontstage metrics, backend management toggle, and live search report card against the actual viewport before the next demo recording.

### 2026-07-06 - ClawOS AI Academy first pass

Completed:
- Added a standalone `ClawOS AI Academy` page at `/academy`, visually aligned with the product-page shell but independent from the console UI.
- Wired Academy navigation from home, product, and console product nav. Product capability index now includes an AI Academy card.
- Added interactive Academy workflows: AI learning path, point-light knowledge graph, paper deep-reading workbench, code experiment tabs, guided note generation, knowledge ingest queue, and quiz generation that updates graph progress.
- Added `/academy` FastAPI route and no-cache handling for `/assets/academy.js`.

Verification:
- `python -m unittest clawos.tests.test_frontend_static`: 34 tests OK.
- `python -m unittest discover -s clawos\tests`: 210 tests OK.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\academy.js`: passed.
- `python -m py_compile clawos\clawos_server.py`: passed.
- Local HTTP smoke after starting `clawos_server.py`: `/academy` returned 200 and `/assets/academy.js` returned 200.

Known notes:
- Playwright package is present, but the local Chromium executable is missing, so screenshot-level browser verification could not run without installing browser binaries.
- `clawos/.env`, `output\search_evidence`, and `tmp/pdfs/*` remain local/ignored or untracked and must not be staged.
- Full tests still mutate `clawos/skills/skill_registry.jsonl` usage counters; restore that file before committing.

Recommended next step:
- Do a visual browser pass after installing/available Playwright browser binaries, then connect Academy actions to real knowledge ingestion/report APIs instead of local-only UI state.

### 2026-07-07 - AI Academy multi-page learning system

Completed:
- Reworked `/academy` into an Academy landing page with module cards and explanations only, instead of crowding every workflow into one page.
- Added independent Academy pages: `/academy/path`, `/academy/paper`, `/academy/code`, `/academy/notes`, `/academy/ingest`, and `/academy/quiz`.
- Rebuilt the learning route as a dynamic layered graph covering Foundation -> ML -> DL -> CV -> NLP/LLM -> VLM/Multimodal -> GenAI -> AI Agent -> AI Coding -> AI Infra/MLOps/LLMOps -> Evaluation/Safety/Governance, with RL as an optional branch, then AI Application and Frontier layers.
- Each layer expands into detailed concepts, representative papers/resources, experiments, and mastery criteria.
- Paper deep reading now lives on its own page with PDF/text input affordance plus AI-guided report sections: concepts, definitions, historical sources, motivation, methods, experiments, ablations, limitations, reproducibility, and report handoff.

Verification:
- `python -m unittest clawos.tests.test_frontend_static`: 34 tests OK.
- `python -m unittest discover -s clawos\tests`: 210 tests OK.
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\academy.js`: passed.
- `python -m py_compile clawos\clawos_server.py`: passed.
- Local HTTP smoke after restarting `clawos_server.py`: `/academy`, `/academy/path`, `/academy/paper`, `/academy/code`, `/academy/notes`, `/academy/ingest`, `/academy/quiz`, and `/assets/academy.js` all returned 200.

Known notes:
- Academy workflows are still frontend/local-state interactions; next pass should connect paper upload/report generation and knowledge ingest to existing ClawOS APIs.
- `clawos/.env`, `output\search_evidence`, and `tmp/pdfs/*` remain local/ignored or untracked and must not be staged.
- Full tests still mutate `clawos/skills/skill_registry.jsonl` usage counters; restore that file before committing.

Recommended next step:
- Wire `/academy/paper` to real document upload/report generation and `/academy/ingest` to `/api/knowledge`, then add a real browser visual pass when Playwright browser binaries are available.

### 2026-07-07 - Academy Paper Studio real workflow wiring

Completed:
- Upgraded `/academy/paper` from a local demo page into a Paper Studio workflow with PDF/file upload, browser PDF preview, extracted chunk stream, canvas pen annotation controls, AI assistant panel, report cards, citation evidence, and graph-lighting status.
- Wired Paper Studio frontend actions to existing ClawOS capabilities: `/api/documents/upload`, `/api/documents/{id}/chunks`, `/api/workspace/research/learning-analysis`, `/api/documents/citation-answer`, `/api/knowledge`, and `/api/knowledge/graph`.
- Paper reports now request Markdown/PDF outputs through the research learning-analysis service, then can be saved back to the research knowledge library with citation evidence metadata.
- Learning progress now lights NLP/LLM, RAG, Evaluation/Safety, and Application nodes as paper parsing/reporting/knowledge-save stages complete.
- Added static regression coverage for real paper workflow wiring, citation evidence, report cards, and annotation UI.

Verification:
- `C:\Users\34712\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe --check clawos\static\assets\academy.js`: passed.
- `python -m py_compile clawos\clawos_server.py`: passed.
- `python -m unittest clawos.tests.test_frontend_static`: 34 tests OK.
- `python -m unittest discover -s clawos\tests`: 210 tests OK.
- Local HTTP smoke: `http://127.0.0.1:18790/academy/paper` returned 200.

Known notes:
- Canvas annotations currently persist to browser localStorage as an annotation image; next step is to persist them through ArtifactStorage as first-class annotation artifacts.
- PDF viewing uses the browser's native iframe/object handling, not a custom PDF.js renderer yet.
- `clawos/.env`, `output\*`, `tmp/pdfs/*`, and provider/API keys must remain uncommitted. Full tests still touch `clawos/skills/skill_registry.jsonl`; ensure no content diff is staged.

Recommended next step:
- Add a small PDF fixture smoke test through FastAPI TestClient for upload -> chunks -> report -> knowledge save, then persist pen annotations as Artifact/Evidence records.

### 2026-07-07 - Local model readiness visibility

Completed:
- Added a no-download local Qwen readiness check in `MaintenanceService.local_model_assets()`.
- `/api/model/health` now includes `local_model_assets`, so provider configuration and real local assets are visible separately.
- `/api/system/readiness` now includes `local_model_assets` as a weighted check and returns the full local model asset report.
- Console model health now renders routing/upstream primary and fallback providers plus local Qwen asset readiness.
- Added regression tests for missing local Qwen assets, model health asset reporting, and console consumption of `local_model_assets`.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\services\maintenance_service.py clawos\clawos_server.py`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider`: `26 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `node --check clawos\static\assets\console.js`: passed.
- Runtime local asset check reports `ready=False` with missing `qwen_9b`, `embedding`, `reranker`, and `llama_server` on this machine.

Known notes:
- This pass does not download models or run a real local Qwen server.
- `tools/models/qwen3.5-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf`, `tools/llama.cpp/llama-server.exe`, `tools/models/qwen3-embedding-0.6b`, and `tools/models/qwen3-reranker-0.6b` are still absent locally.
- The existing `%SystemDrive%/...` deleted-path git noise remains untouched.

Recommended next step:
- With explicit network/download approval, install llama.cpp runtime and Qwen GGUF, then run `/api/model/health?probe=true` and `evaluate_model_acceptance.py --provider qwen --base-url http://127.0.0.1:8000/v1 --model Qwen3.5-9B-Q4_K_M`.
### 2026-07-07 - Qwen acceptance default config fix

Completed:
- Updated `evaluate_model_acceptance.py` so `--provider qwen` no longer passes empty `model` or `base_url` values that override `QwenProvider` local defaults.
- Qwen acceptance config now marks `requires_api_key=false` when using the local provider.
- Added a regression test proving Qwen acceptance config relies on provider defaults unless explicit CLI/env values are supplied.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\scripts\evaluate_model_acceptance.py`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance`: passed.

Known notes:
- This pass still does not start a local Qwen server or download model assets.
- Real Qwen acceptance remains blocked on installing `tools/llama.cpp/llama-server.exe` and `tools/models/qwen3.5-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf`.

Recommended next step:
- After local model assets are installed, run `evaluate_model_acceptance.py --provider qwen --limit 2 --json` first, then scale to the full frozen suite.
### 2026-07-07 - Academy paper annotation artifact persistence

Completed:
- Added `ArtifactStorage.write_bytes()` for binary local artifacts.
- Added `POST /api/academy/paper/annotations` to persist Paper Studio pen annotations as PNG artifacts under `output/academy/annotations`.
- Annotation saves now create a durable `academy_annotation` RunRecord with an `annotation_png` artifact and document-linked evidence citation.
- `/academy/paper` now attempts artifact persistence after saving the browser canvas, while keeping localStorage as the offline fallback when no document is uploaded or the API fails.
- Added regression coverage for annotation artifact creation, run/evidence persistence, and frontend API wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\services\artifact_storage.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `26 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.

Known notes:
- This pass does not add a visual browser screenshot check.
- Generated annotation artifacts live under ignored `output/academy/annotations` and should not be committed.
- The existing `%SystemDrive%/...` deleted-path git noise remains untouched.

Recommended next step:
- Add a FastAPI/TestClient-style PDF upload -> chunks -> report -> knowledge save smoke test, then run a browser walkthrough of `/academy/paper` when browser tooling is available.
### 2026-07-07 - Uploaded paper workflow smoke coverage

Completed:
- Added a regression smoke test that exercises the real `/api/documents/upload` entrypoint with an in-memory PDF upload.
- The smoke flow now proves uploaded PDFs become ready library documents, expose citation-bearing chunks, generate markdown/PDF learning reports, and save a follow-up knowledge note with a `doc:N` source.
- The test keeps uploads, reports, and the temporary MemoryOS database inside a temp directory, so it remains offline and does not touch real `clawos/uploads` data.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\tests\test_routing_memory.py`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory.MemoryAndRoutingTests.test_uploaded_pdf_flow_chunks_report_and_knowledge_save`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `27 tests OK`.

Known notes:
- This pass adds backend/service smoke coverage only; it does not launch the browser or visually inspect `/academy/paper`.
- The existing `%SystemDrive%/...` deleted-path git noise remains untouched.

Recommended next step:
- Add a small runtime health card or Paper Studio status hint that surfaces whether the current document has chunks, generated reports, saved knowledge, and annotation artifacts, then do a browser pass when tooling is available.
### 2026-07-07 - Paper Studio runtime status panel

Completed:
- Added a Paper Studio runtime status panel on `/academy/paper` for document upload, parsed chunks, generated report artifacts, saved knowledge, and annotation artifact state.
- Wired the panel to existing `academyPaperState` updates after upload/chunk parsing, report generation, knowledge save, annotation save, and initial page boot.
- Added static frontend coverage so the status panel markup, renderer, state token, and CSS class remain part of the Academy Paper workflow.

Verification:
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `27 tests OK`.
- `git diff --check -- PROJECT_CONTEXT.md clawos\static\academy-paper.html clawos\static\assets\academy.js clawos\static\assets\site.css clawos\tests\test_frontend_static.py clawos\tests\test_routing_memory.py`: passed with CRLF warnings only.

Known notes:
- This is a frontend state visibility pass only; it does not change backend document/report/artifact APIs.
- Browser screenshot verification is still not run in this environment.

Recommended next step:
- Start the local server and do a browser walkthrough of `/academy/paper`, then connect the panel to persisted historical run records if the user wants status to survive a full page reload.
### 2026-07-08 - Paper Studio persisted status recovery

Completed:
- Added `academy_paper_report` RunRecord persistence when a library document generates a learning-analysis report.
- Added `GET /api/academy/paper/status?document_id=N` to recover uploaded document chunk count, latest report artifacts, latest knowledge item linked by `doc:N`, and latest annotation artifact.
- Updated `/academy/paper` so the runtime status panel refreshes from persisted state after upload, report generation, knowledge save, annotation save, and page state refresh.
- Paper knowledge saves now include the source document marker in `source`, so status recovery can reconnect saved notes to the original document.
- Added regression coverage for report RunRecord recovery, knowledge recovery, annotation recovery, and frontend API wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `27 tests OK`.
- `git diff --check -- PROJECT_CONTEXT.md clawos\clawos_server.py clawos\static\assets\academy.js clawos\tests\test_frontend_static.py clawos\tests\test_routing_memory.py`: passed with CRLF warnings only.

Known notes:
- Browser screenshot verification is still not run in this environment.
- The status recovery is document-scoped; a future pass can add a document picker/history drawer for reopening older Paper Studio sessions.

Recommended next step:
- Add a Paper Studio document history selector backed by `/api/documents?category=research`, so users can reopen prior local papers without re-uploading.
### 2026-07-08 - Paper Studio local document history

Completed:
- Added a local Recent Papers selector on `/academy/paper`, backed by `/api/documents?category=research`.
- The page now loads recent research documents on boot and after uploads, showing document id, chunk count, and status without needing cloud services.
- Clicking a prior paper opens it from MemoryOS, reloads chunks, refreshes persisted report/knowledge/annotation status, and regenerates the local deep-read cards without re-uploading the file.
- Opening a historical document clears the stale PDF iframe preview because the browser object URL only exists for fresh uploads.
- Added static frontend coverage for the history selector and API wiring, plus a backend smoke assertion for the document list shape and `chunk_count`.

Verification:
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `27 tests OK`.
- `git diff --check -- PROJECT_CONTEXT.md clawos\static\academy-paper.html clawos\static\assets\academy.js clawos\static\assets\site.css clawos\tests\test_frontend_static.py clawos\tests\test_routing_memory.py`: passed with CRLF warnings only.

Known notes:
- Browser screenshot verification is still not run in this environment.
- Historical paper reopen currently restores chunks/status/report metadata; it does not rehydrate the original PDF preview unless a file is uploaded again.

Recommended next step:
- Add an optional source-file preview endpoint for local uploads, with path confinement, so reopened PDFs can be previewed safely from the stored document record.
### 2026-07-08 - Confined document source preview

Completed:
- Added `GET /api/documents/{document_id}/source` for local source preview of uploaded research documents.
- The endpoint only serves files whose resolved path is inside the configured `UPLOAD_DIR`, and rejects missing, external, or unsupported source files.
- Previewable source types are limited to PDF and common text-like formats; Paper Studio uses it only to restore PDF iframe previews when reopening historical papers.
- `/academy/paper` now restores PDF preview URLs for reopened local PDFs instead of leaving the iframe blank after history selection.
- Added regression coverage for successful local PDF preview, upload-directory confinement, frontend preview helper wiring, and server route exposure.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.
- `git diff --check -- PROJECT_CONTEXT.md clawos\clawos_server.py clawos\static\assets\academy.js clawos\tests\test_frontend_static.py clawos\tests\test_routing_memory.py`: passed with CRLF warnings only.

Known notes:
- Browser screenshot verification is still not run in this environment.
- DOCX source files remain parsed into chunks/reports, but are not served as browser previews by this endpoint.

Recommended next step:
- Add a small in-page source metadata panel showing filename, extractor, page count, OCR status, and source preview availability for the active document.
### 2026-07-08 - Paper Studio active document metadata

Completed:
- Added an active document metadata panel on `/academy/paper` for filename, extractor, page count, OCR status, and source preview availability.
- The panel renders from existing MemoryOS document fields and ingestion metadata, without adding a new table or cloud dependency.
- Metadata refreshes after upload, historical document reopen, and persisted status refresh, so it stays aligned with the currently active paper.
- Added static frontend coverage for the panel, renderer, and CSS class, plus backend flow assertions that uploaded PDF metadata and OCR state are present in status recovery.

Verification:
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.
- `git diff --check -- PROJECT_CONTEXT.md clawos\static\academy-paper.html clawos\static\assets\academy.js clawos\static\assets\site.css clawos\tests\test_frontend_static.py clawos\tests\test_routing_memory.py`: passed with CRLF warnings only.

Known notes:
- Browser screenshot verification is still not run in this environment.
- The panel reports DOCX/text documents as chunks-only preview unless the existing source preview endpoint marks them browser-previewable.

Recommended next step:
- Add a compact Paper Studio export/checkpoint action that bundles report paths, knowledge item id, annotation artifact, citation evidence, and document metadata into one local run summary.
### 2026-07-08 - Paper Studio checkpoint export

Completed:
- Added `POST /api/academy/paper/checkpoint` to save a local JSON checkpoint for the active paper.
- The checkpoint bundles document metadata, chunk previews, latest report paths, saved knowledge item, annotation artifact, and citation evidence into `output/academy/checkpoints`.
- Checkpoints are recorded as `academy_paper_checkpoint` RunRecords with artifact and evidence links, so they remain searchable through MemoryOS traces.
- `/api/academy/paper/status` now reports the latest checkpoint, and `/academy/paper` exposes a `保存 Checkpoint` action plus runtime status.
- Added regression coverage for the upload -> report -> knowledge -> checkpoint flow and static frontend route wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.

Known notes:
- Checkpoint export is JSON-only for now; it intentionally avoids re-running model analysis or copying source PDFs.

Recommended next step:
- Add a small checkpoint history/reopen panel so prior Paper Studio sessions can be compared and resumed from their saved local run summaries.
### 2026-07-08 - Paper Studio checkpoint history and restore

Completed:
- Added local checkpoint history APIs for Paper Studio: list checkpoints and load a checkpoint detail by `run_id`.
- Checkpoint detail reads the saved JSON artifact only from `output/academy/checkpoints`, preserving the local-first artifact boundary.
- `/academy/paper` now shows a Checkpoints panel, loads saved checkpoint runs on boot, and can restore document metadata, chunk previews, citation evidence, report status, knowledge id, annotation artifact, and PDF preview when available.
- Saving a new checkpoint refreshes the in-page checkpoint list so a research session can be resumed without cloud services or model re-execution.
- Added regression coverage for checkpoint list/detail recovery and frontend history/restore wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.

Known notes:
- Checkpoint restore rehydrates the saved run summary and previews; it does not copy or duplicate the original source file.

Recommended next step:
- Add a compact project/research task board that links documents, reports, checkpoints, and follow-up questions into durable local project records.
### 2026-07-08 - Local research project board

Completed:
- Added a local Paper Studio project board backed by `academy_research_project_item` RunRecords, avoiding new cloud dependencies or a new database table.
- Added `GET /api/academy/paper/project-board` and `POST /api/academy/paper/project-board` to list and save follow-up research items for a paper.
- Each project item links the active document, latest report run, checkpoint run, knowledge item, and annotation run where available.
- `/academy/paper` now includes a Project Board panel with a follow-up question input and local item list.
- The board refreshes on page boot, paper upload, historical paper open, and checkpoint restore, so research work can resume offline from durable local records.
- Added regression coverage for project item persistence/linkage and frontend route/UI wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.

Known notes:
- Project items currently support create/list only; status transitions such as done/blocked are not yet editable from the UI.

Recommended next step:
- Add project item status updates and a compact export so a research project can be reviewed as a local package of documents, checkpoints, reports, evidence, and follow-up decisions.
### 2026-07-08 - Research project status and export package

Completed:
- Added project item status updates with `POST /api/academy/paper/project-board/{run_id}/status` for `open`, `done`, and `blocked` states.
- Added `POST /api/academy/paper/project-board/export` to write a local JSON research project package under `output/academy/projects`.
- The project export bundles document metadata, current Paper Studio status, project items, checkpoint summaries, and chunk previews into one offline-reviewable artifact.
- Exports are recorded as `academy_research_project_export` RunRecords with artifact and evidence links.
- `/academy/paper` now exposes Done/Blocked/Reopen controls for project items and a project package export button.
- Added regression coverage for status transition, project package export, artifact existence, and frontend route/UI wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.

Known notes:
- Project package export is JSON-only and intentionally references existing source/report/checkpoint artifacts instead of duplicating them.

Recommended next step:
- Add a local project package history panel or console summary so exported research packages can be reopened and reviewed outside the current Paper Studio session.
### 2026-07-08 - Research project package history and restore

Completed:
- Added local project package history APIs: `GET /api/academy/paper/project-board/exports` and `GET /api/academy/paper/project-board/exports/{run_id}`.
- Project package detail reads the saved JSON artifact only from `output/academy/projects`, preserving the local artifact boundary.
- `/academy/paper` now shows a Project Packages panel, loads local exports on boot, and refreshes it after project export.
- Clicking a project package restores document metadata, Paper Studio status, chunk previews, project items, checkpoint summaries, report status, knowledge id, and annotation/checkpoint artifacts where available.
- Added regression coverage for package list/detail recovery and frontend history/restore wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.

Known notes:
- Project package restore rehydrates the saved JSON package and linked local state; it does not duplicate source files or reports.

Recommended next step:
- Add a compact local readiness/audit panel that summarizes whether the workstation can run the full offline workflow: local model assets, document ingestion, report generation, checkpoints, project packages, and evidence search.
### 2026-07-08 - Offline workflow readiness audit

Completed:
- Added `GET /api/academy/paper/offline-audit` to summarize local-first research workflow readiness for the active paper or latest research document.
- The audit checks local 8B/9B model assets, document ingestion/chunks, report runs, research knowledge, citation evidence readiness, checkpoints, project board items, and project package exports.
- `/academy/paper` now includes an Offline Workflow Audit panel with a manual refresh button and per-capability readiness cards.
- The audit refreshes on page boot, paper upload/open, checkpoint save, and project package export so local workflow gaps are visible while working offline.
- Added regression coverage for audit counts/checks and frontend route/UI wiring.

Verification:
- `clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py`: passed.
- `node --check clawos\static\assets\academy.js`: passed.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static`: `34 tests OK`.
- `clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory`: `28 tests OK`.

Known notes:
- Audit is a local readiness summary; it does not run a live model generation probe or mutate artifacts.

Recommended next step:
- Add a compact console-level offline readiness surface that links this Paper Studio audit with `/api/system/readiness` and `/api/model/health` for whole-workbench daily checks.

### 2026-07-08 - Console workbench offline readiness

Completed:
- Added `GET /api/workbench/offline-readiness` as a compact local-first readiness summary for the whole workbench.
- Reused `/api/system/readiness` logic through `_system_readiness_payload()` so system readiness has a single scoring source.
- Aggregated local 8B/9B model asset readiness with Paper Studio offline workflow audit, including document chunks, research knowledge, report runs, citation evidence, checkpoints, project board items, and project package exports.
- Added an Offline Readiness panel to the Console dashboard with workbench/system/paper/model summary metrics and per-check status cards.
- Extended frontend static tests and the Paper Studio routing-memory workflow test to cover the new API and panel wiring.

Verification:
```powershell
clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
```

Result:
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- The new readiness check is offline-only; it does not probe a live model endpoint or call network APIs.

Recommended next step:
- Add a daily local acceptance preset that runs this workbench readiness check together with mock model acceptance and frozen benchmark output, then exposes one copyable summary for self-use maintenance.
### 2026-07-08 - Explicit local Qwen smoke check

Completed:
- Added `_local_qwen_smoke_check()` and `POST /api/workbench/local-qwen-smoke` for an explicit local Qwen endpoint smoke test.
- The smoke check uses the local OpenAI-compatible Qwen provider at `QWEN_BASE_URL` / `QWEN_MODEL`, defaults to `http://127.0.0.1:8000/v1` and `Qwen3.5-9B-Q4_K_M`, and never requires or sends an API key.
- `POST /api/workbench/daily-local-acceptance` now supports `include_qwen_smoke=true`, folding real local Qwen availability into the daily summary only when explicitly requested.
- Console Offline Readiness now exposes `Daily + Qwen` and `Qwen smoke` actions next to the default quick daily check.
- Smoke results report endpoint, model, asset readiness summary, duration, error class, and a short content preview without logging prompts or secrets.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
```

Result:
- Model acceptance tests: `6 tests OK`.
- Static frontend tests: `34 tests OK`.
- Model provider tests: `26 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.

Known notes:
- The Qwen smoke path is explicit because it calls the local llama.cpp/OpenAI-compatible server. It is still offline/local, but it can fail if the server is not running or assets are missing.
- The default daily local acceptance remains mock/frozen-only for fast no-model maintenance checks.

Recommended next step:
- Add a persisted local acceptance history so daily checks, Qwen smoke results, readiness gaps, and benchmark pass rates can be reviewed over time from the Console without relying on external dashboards.
### 2026-07-08 - Local acceptance history

Completed:
- Added persisted RunRecord history for daily local acceptance and explicit Qwen smoke checks.
- `POST /api/workbench/daily-local-acceptance` saves `workbench_daily_acceptance` runs by default, including readiness gaps, frozen benchmark metrics, mock model acceptance score, optional Qwen smoke result, evidence, and failure cases.
- `POST /api/workbench/local-qwen-smoke` saves `workbench_qwen_smoke` runs by default, including endpoint/model, asset readiness, duration, error class, evidence, and failure case when the smoke check fails.
- Added `GET /api/workbench/local-acceptance-history` to return compact local history across daily checks and Qwen smoke runs.
- Console Offline Readiness panel now includes a Local Acceptance History table with refresh, status, readiness percent, Qwen result, and summary columns.
- Added regression coverage for persisted daily/Qwen history, route wiring, frontend history UI, and secret redaction expectations.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `7 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- History persistence depends on MemoryOS being initialized. Without MemoryOS, the history API returns `durable=false` and no rows.
- Daily and Qwen APIs support `persist=false` for temporary smoke calls.

Recommended next step:
- Add a small trend summary over acceptance history, such as latest pass/fail, rolling pass rate, Qwen failure streak, and top recurring readiness gaps.
### 2026-07-08 - Local acceptance trend summary

Completed:
- Added `GET /api/workbench/local-acceptance-trends` to summarize persisted daily local acceptance and Qwen smoke RunRecords.
- Trend output includes latest run, rolling overall/daily/Qwen pass rates, Qwen failure streak, average workbench readiness, average benchmark pass rate, average model score rate, and top recurring readiness gaps.
- Console Local Acceptance History now renders a compact trend grid above the history table: latest status, daily pass rate, Qwen streak, average readiness, and top gaps.
- Reused RunRecord failure cases for readiness gap counting, so no new table or cloud dependency is needed.
- Added regression coverage for trend API, trend UI wiring, and secret redaction expectations.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `7 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Trend summary depends on persisted local acceptance history. Empty MemoryOS returns a durable=false/empty trend shape.
- Qwen streak counts explicit Qwen smoke runs and daily runs that included Qwen smoke.

Recommended next step:
- Add a guided remediation panel for top readiness gaps, mapping missing model assets, missing Qwen server, missing project packages, or missing evidence search into concrete local actions/scripts.
### 2026-07-08 - Local readiness remediation guide

Completed:
- Added `GET /api/workbench/local-remediation-guide` to map recurring readiness gaps into concrete local remediation actions.
- The guide covers local Qwen/model assets, llama.cpp/Qwen server startup, document ingestion/report gaps, evidence-chain gaps, project board gaps, and offline checkpoint/project package gaps.
- Remediation output includes severity, action, why, relevant local scripts such as `start_qwen_llama_server.ps1`, `download_qwen_model.ps1`, `download_llama_cpp.ps1`, and follow-up check APIs.
- Console Local Acceptance History now renders remediation cards under the trend grid and refreshes them with local history.
- The remediation guide is read-only: it does not run downloads, start servers, mutate data, or call cloud APIs.
- Added regression coverage for remediation API payloads, frontend UI wiring, CSS, and secret redaction expectations.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `7 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Remediation suggestions depend on historical readiness gaps when available, otherwise they fall back to current workbench offline readiness.
- Scripts are shown as paths only; user still decides whether to run downloads or start the Qwen server.

Recommended next step:
- Add an exportable local maintenance report that bundles readiness, trend summary, remediation guide, and latest daily acceptance summary into one Markdown/JSON artifact for long-term self-audit.
### 2026-07-08 - Local maintenance report export

Completed:
- Added `POST /api/workbench/local-maintenance-report` to export a local-first maintenance snapshot without cloud/API dependency.
- The report bundles workbench offline readiness, local acceptance history, trend summary, remediation guide, and latest daily acceptance summary.
- Exports both JSON and Markdown artifacts under `output/maintenance` via `ArtifactStorage`.
- Persists a `workbench_maintenance_report` RunRecord when MemoryOS is available, with links to the JSON and Markdown artifacts.
- Console Offline Readiness now includes an `Export report` action that shows exported artifact paths and refreshes local acceptance history.
- Added regression coverage for backend report export, RunRecord persistence, frontend wiring, and secret redaction expectations.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Report history and RunRecord persistence depend on MemoryOS initialization.
- Export writes local files only; it does not run remediation scripts, download assets, start servers, or call cloud APIs.

Recommended next step:
- Add a console-side report browser for recent `workbench_maintenance_report` RunRecords, including Markdown preview and artifact open/copy actions.
### 2026-07-09 - Local maintenance report browser

Completed:
- Added `GET /api/workbench/local-maintenance-reports` to list recent `workbench_maintenance_report` RunRecords.
- Added `GET /api/workbench/local-maintenance-reports/{run_id}` to read the saved Markdown and JSON artifacts for a selected maintenance report.
- Maintenance report artifact reads are constrained to `output/maintenance`, so the detail API does not become a general file reader.
- Console Offline Readiness now includes a Local Maintenance Reports table with refresh and per-report Markdown preview.
- Exporting a report now refreshes the report browser and opens the newly generated Markdown preview when the RunRecord is persisted.
- Added regression coverage for report list/detail APIs, frontend report browser wiring, CSS, and secret redaction expectations.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- The browser depends on MemoryOS RunRecords. If MemoryOS is unavailable, the list is empty and durable=false.
- The detail endpoint reads local report artifacts only; it does not open files externally or execute remediation actions.

Recommended next step:
- Turn remediation guide entries into explicit local action checklists that can be marked reviewed/resolved and linked back into the next maintenance report.
### 2026-07-09 - Local remediation action checklist

Completed:
- Added persistent local remediation actions backed by `workbench_remediation_action` RunRecords, avoiding a new table while keeping the data local and auditable.
- Added `POST /api/workbench/local-remediation-actions` so remediation guide items can be marked `open`, `reviewed`, or `resolved` with a stable action id.
- `GET /api/workbench/local-remediation-guide` now annotates each action with `action_id`, status, status note, status RunRecord id, and reviewed/resolved counts.
- Local maintenance report exports now include a Remediation Status section and reviewed/resolved counts, so reports capture not only gaps but also what has been acknowledged or closed.
- Console remediation cards now show status and expose `Mark reviewed` / `Mark resolved` actions without running scripts, downloading models, starting services, or calling cloud APIs.
- Added regression coverage for status persistence, guide/report integration, frontend action wiring, CSS, and secret redaction expectations.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Remediation action persistence requires MemoryOS. Without MemoryOS, the guide remains readable but status writes return 503.
- Marking an action resolved is a user audit state only; it does not execute the suggested remediation script or re-run checks automatically.

Recommended next step:
- Add a one-click local recheck for a resolved remediation item that runs only safe local checks such as readiness, model health, or Qwen smoke depending on the action's `checks` list.
### 2026-07-09 - Safe local remediation recheck

Completed:
- Added `POST /api/workbench/local-remediation-actions/recheck` for one-click safe local rechecks of remediation actions.
- Rechecks are restricted to local/read-only checks already represented by the guide: model health, offline readiness, local acceptance trends, remediation guide refresh, Qwen smoke, document counts, Paper Studio audit, checkpoint/export/project/report RunRecord counts.
- Recheck results are written back into the same `workbench_remediation_action` RunRecord under `last_recheck`, preserving the reviewed/resolved audit state.
- `GET /api/workbench/local-remediation-guide` now returns `last_recheck` per action so the Console and future reports can show whether a resolved item still needs attention.
- Console remediation cards now show last recheck state and include a `Recheck` button next to `Mark reviewed` and `Mark resolved`.
- Recheck does not run remediation scripts, download model assets, start background servers, mutate project artifacts, or call cloud APIs.
- Added regression coverage for backend recheck persistence, guide integration, frontend route/function wiring, and secret redaction expectations.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Qwen smoke remains a local endpoint call and can fail when the local server is not running; this is reported as a recheck result, not treated as a tool execution failure.
- Recheck uses local state snapshots and RunRecord counts; it is a maintenance gate, not an automatic fixer.

Recommended next step:
- Surface the remediation/recheck history inside the Local Maintenance Report browser so old reports and current action state can be compared side by side.
### 2026-07-09 - Maintenance report current-state comparison

Completed:
- `GET /api/workbench/local-maintenance-reports/{run_id}` now returns both `report_remediation` from the saved artifact and `current_remediation` from the live local RunRecords.
- The detail response keeps historical report artifacts immutable while allowing the Console to compare old report state against current reviewed/resolved/recheck progress.
- Console maintenance report preview now shows report-time reviewed/resolved counts and current reviewed/resolved/rechecked counts before the Markdown body.
- This makes the report browser useful as a longitudinal audit surface: old snapshots remain readable while current remediation closure is visible in the same view.
- Added regression coverage for detail API remediation snapshots and frontend comparison text.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Historical JSON/Markdown artifacts are not rewritten; current state is returned separately by the detail API.
- Current-state comparison depends on MemoryOS RunRecords being available.

Recommended next step:
- Add a compact local workbench timeline that merges daily acceptance, Qwen smoke, remediation actions, rechecks, and maintenance reports into one chronological view.
### 2026-07-09 - Local workbench timeline

Completed:
- Added `GET /api/workbench/local-timeline` to merge key local maintenance RunRecords into one chronological view.
- Timeline currently covers daily local acceptance, explicit Qwen smoke checks, remediation action state changes, remediation rechecks, and maintenance report exports.
- Remediation actions with a `last_recheck` produce both an action event and a recheck event, making the audit trail easier to scan from the Console.
- Console Offline Readiness now includes a Local Workbench Timeline table between trend summary and remediation cards.
- The timeline is local-only and read-only; it does not execute checks, mutate action state, open files, or call cloud APIs.
- Added regression coverage for timeline API event kinds, maintenance report timeline inclusion, frontend DOM/JS/CSS wiring, and route registration.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Timeline depends on MemoryOS RunRecords. Without MemoryOS it returns an empty durable=false payload.
- Current remediation action RunRecords are upserted by action id, so the timeline represents the latest remediation action state plus the latest recheck event, not every historical status transition.

Recommended next step:
- Add timeline drill-down so selecting an event opens the relevant report preview, remediation card, Qwen smoke details, or daily acceptance summary.
### 2026-07-09 - Local timeline drill-down

Completed:
- Timeline events now include `target` and `payload` data so the Console can open event-specific local details without additional tables.
- Console Local Workbench Timeline now has an `Open` action per row and a local detail preview pane.
- Opening a maintenance report event reuses the existing maintenance report preview; daily acceptance, Qwen smoke, remediation action, and recheck events render their local payload details inline.
- This keeps the timeline read-only while making the audit trail actionable for long-term self-maintenance.
- Added regression coverage for timeline `target`/`payload`, frontend drill-down DOM/function wiring, and retained route/static checks.
- Fixed an accidental target-field insertion into Academy checkpoint summaries caught by `clawos.tests.test_routing_memory`.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Timeline drill-down is read-only. It opens existing report previews or local payload snapshots; it does not rerun checks or mutate action state.
- Maintenance report events can open rich previews because report artifacts already have a detail API; other event kinds currently show structured JSON payloads inline.

Recommended next step:
- Add a local-first research workflow timeline that connects document ingestion, citation answers, reports, project board items, checkpoints, and project package exports for Paper Studio.
### 2026-07-09 - Timeline event drill-down

Completed:
- Timeline items now include `target` and `payload` fields for local drill-down without adding new persistence tables.
- Console Local Workbench Timeline now includes an `Open` action per event plus `localWorkbenchTimelineDetail` for inline details.
- Maintenance report timeline events open the existing report preview; daily acceptance, Qwen smoke, remediation action, and remediation recheck events show their local payload snapshots inline.
- Added regression assertions that timeline events expose target/payload data and that the frontend includes the timeline drill-down cache, Open handler, and detail panel.
- Fixed an accidental `target` insertion into Academy checkpoint summary discovered by `clawos.tests.test_routing_memory`.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_model_acceptance.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\console.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Model acceptance tests: `8 tests OK`.
- Static frontend tests: `34 tests OK`.
- Routing/memory workflow tests: `28 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- Timeline drill-down is read-only. It does not rerun checks, mark actions, open external files, or call cloud APIs.
- Non-report event details currently render JSON payloads; richer per-kind panels can be added later if needed.

Recommended next step:
- Add a local-first research workflow timeline that connects Paper Studio document ingestion, citation answers, reports, project board items, checkpoints, and project package exports.
### 2026-07-09 - Paper Studio research workflow timeline

Completed:
- Added `GET /api/academy/paper/timeline` for a read-only, local-first Paper Studio workflow timeline.
- The timeline merges research document ingestion, saved knowledge/citation notes, paper reports, annotations, checkpoints, project board items, and project package exports.
- Timeline items include `target` and `payload` so the Academy page can reopen documents, checkpoints, and project packages or inspect local event details inline.
- Paper Studio now shows a Research Timeline panel and refreshes it from the existing upload, report, knowledge save, checkpoint, project board, and export flows.
- Citation answers do not yet have their own RunRecord; durable citation evidence is surfaced when saved into knowledge or captured inside a checkpoint.
- The endpoint is local-only and read-only. It does not run models, re-run searches, open files externally, download assets, execute scripts, or call cloud APIs.
- Added regression coverage for backend event kinds/targets/payloads, frontend DOM/JS/CSS wiring, and route registration.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\academy.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_acceptance
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider
```

Result:
- Routing/memory workflow tests: `28 tests OK`.
- Static frontend tests: `34 tests OK`.
- Model acceptance tests: `8 tests OK`.
- Model provider tests: `26 tests OK`.

Known notes:
- The timeline is reconstructed from existing MemoryOS documents, knowledge items, and RunRecords; it does not add a new persistence table.
- Current citation-answer API responses are transient unless the user saves them to knowledge or checkpoint state.

Recommended next step:
- Persist citation-answer runs as explicit `academy_citation_answer` RunRecords so evidence Q&A appears in the Paper Studio timeline immediately, without requiring a checkpoint or knowledge-save step.
### 2026-07-09 - Durable Paper Studio citation-answer runs

Completed:
- `GET /api/documents/citation-answer` now persists each evidence Q&A as an `academy_citation_answer` RunRecord when MemoryOS is available.
- Citation-answer RunRecords store query/category/document inputs, answer/citation outputs, citation count metrics, and evidence records linked to document/chunk citations.
- Paper Studio timeline now reads `academy_citation_answer` RunRecords directly, so evidence Q&A appears immediately after a citation query without waiting for a checkpoint or knowledge-save step.
- Paper Studio refreshes the research timeline after citation-answer queries.
- Added regression coverage for citation-answer RunRecord persistence, evidence metadata, timeline inclusion, and static route/run-type wiring.

Verification:
```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m py_compile clawos\clawos_server.py clawos\tests\test_routing_memory.py clawos\tests\test_frontend_static.py
node --check clawos\static\assets\academy.js
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_routing_memory
clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
```

Result:
- Routing/memory workflow tests: `28 tests OK`.
- Static frontend tests: `34 tests OK`.

Known notes:
- Citation-answer persistence depends on MemoryOS, which is already required by the citation-answer service.
- The citation-answer route remains local and read-only with respect to external systems; it only writes a local audit RunRecord.

Recommended next step:
- Add a report-side evidence chain browser that can open citation-answer RunRecords, source chunks, and generated report sections from one local Paper Studio panel.

### 2026-07-10 - Local Qwen installer and CUDA runtime reliability

Completed:
- Fixed `download_llama_cpp.ps1` so NVIDIA installs select the real `llama-*-bin-win-cuda-*.zip` server archive instead of the similarly named `cudart-*` companion archive.
- Added installation of the matching official CUDA runtime companion archive and made an existing `llama-server.exe` without `cudart64*.dll` count as incomplete.
- Changed llama.cpp and Qwen downloads to prefer resumable `curl.exe -C -` transfers, with the existing PowerShell/Hugging Face alternatives retained when curl is unavailable.
- Installed the ignored local llama.cpp b9946 CUDA 12.4 runtime and companion files under `tools/llama.cpp/runtime`.
- Updated `MaintenanceService.local_model_assets()` to recognize the downloader's `tools/llama.cpp/runtime/llama-server.exe` install path instead of falsely reporting the installed server as missing.
- Completed the Qwen3.5-9B Q4_K_M download by resuming a verified GGUF prefix, then copied the verified model to its manifest path.
- Disabled Qwen thinking by default through `chat_template_kwargs`, while preserving an explicit per-request override.
- Prevented local Qwen requests from leaking through environment HTTP proxies by using a no-proxy client for loopback model endpoints; cloud provider proxy behavior remains unchanged.
- Made local embedding and reranker model loaders default to CPU, with environment device overrides, so they do not compete with the 9B model for the laptop GPU.
- Tuned the single-user llama.cpp default to one 8192-token slot and 20 GPU layers for this 8 GB RTX 5060 Laptop GPU.

Verification:
```powershell
tools\llama.cpp\runtime\llama-server.exe --version
tools\llama.cpp\runtime\llama-cli.exe --list-devices
clawos\.venv\Scripts\python.exe clawos\scripts\provider_smoke.py
clawos\.venv\Scripts\python.exe clawos\scripts\evaluate_model_acceptance.py --provider qwen --limit 2 --json
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_frontend_static
$env:PYTHONDONTWRITEBYTECODE='1'; clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_model_provider clawos.tests.test_model_acceptance clawos.tests.test_retrieval_reranker
```

Result:
- llama.cpp reports build `9946 (fb30ba9a6)`.
- CUDA device discovery reports `NVIDIA GeForce RTX 5060 Laptop GPU` with 8150 MiB total VRAM.
- GGUF size verified at `5,680,522,464` bytes and SHA256 verified as `03B74727A860A56338E042C4420BB3F04B2FEC5734175F4CB9FA853DAF52B7E8`.
- Provider smoke passed direct completion, tool calling, and reflection JSON; observed durations were about `0.32s`, `0.49s`, and `1.84s`.
- Real Qwen model acceptance passed `2/2` cases with `10/10` score and no provider errors in three consecutive runs under the 20-GPU-layer profile; each run took about `5.0-5.2s` and model identity was `Qwen3.5-9B-Q4_K_M`.
- ClawOS `POST /api/workbench/local-qwen-smoke` returned `LOCAL_OK` and persisted a passing `workbench_qwen_smoke` history record.
- Under the 20-GPU-layer configuration, the 9B server retained roughly `1.8-2.3 GB` free VRAM, generated about `23.5 tok/s`, and passed `8/8` requests at concurrency 8 through the single queued slot.
- Combined frontend/provider/model-acceptance/retrieval regression: `74 tests OK` after the final acceptance-prompt regression was added.
- Both modified PowerShell scripts pass parser validation.

Known notes:
- Qwen3.5-9B is now locally usable and verified. The configured primary ClawOS provider remains DeepSeek until the user switches model mode; explicit local Qwen health/smoke paths are operational.
- Embedding and reranker weights are still incomplete. Embedding small repository files were downloaded, but the main safetensors download was stopped after xet stalled and the follow-up curl request was blocked by the environment usage limit.
- `torch`, `sentence-transformers`, and `chromadb` are not installed in the current venv, so ClawOS falls back to the lightweight local vector store.
- Interrupted Hugging Face `.incomplete` cache files remain untouched; no cache files were deleted.

Recommended next step:
- After network approval recovers, finish Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B, install/verify the local Chroma and sentence-transformers runtime, then run `vector_db_acceptance.py` and `paper_rag_acceptance.py` before enabling semantic embedding/reranking by default.

### 2026-07-10 - Stage 1 architecture and vertical-agent assessment

Completed:
- Added `clawos/STAGE1_PROJECT_ASSESSMENT_2026-07-10.md` with a repository-grounded 72/100 assessment and P0/P1/P2 priorities.
- Verified that all 56 declared functions have handlers, while MTClaw exposes only 18 low-risk tools and currently exposes none of the core meeting/research/learning vertical tools.
- Confirmed that MTClaw routing is real but default-off, non-streaming-only, and bypassed by the informational scenario policy API.
- Assessed meeting, coding, knowledge, paper, education, and fixed-role multi-agent capabilities without treating unavailable hardware/model checks as passed.

Verification:
- Relevant module suite: `70 tests OK`.
- Full suite: `221 tests OK`.
- Frozen benchmark: `30/30 passed`, P95 `456.679 ms`.
- Mock model acceptance: `150/150`, rate `1.0`.
- Function inventory: `56/56` handlers; MTClaw safe tools `18/18`; vertical tools in MTClaw safe set `0`.

Known notes:
- No network fetch, real model API, real ASR, Qwen runtime, or MTT AIBOOK acceptance was run.
- Existing user changes in `clawos/skills/skill_registry.jsonl` and untracked `tmp/` files remain outside this assessment commit.
- FastAPI `on_event` and Chroma telemetry emitted non-blocking deprecation warnings.

Recommended next step:
- Make the scored scenario policy control execution, add low-risk vertical wrappers to the MTClaw route, and freeze five trace-backed Stage 1 demo cases before expanding UI breadth.

### 2026-07-10 - Competition architecture and MTClaw vertical-routing closure

Completed:
- Converted scenario routing from an informational API into an enforced execution policy that filters model-visible tools and denies policy-outside calls.
- Expanded the generated MTClaw surface from 18 to 24 low-risk tools with six vertical entries: local knowledge search, meeting extraction, paper deep reading, exam practice, research read actions, and learning read actions.
- Added three-layer least-privilege controls for vertical wrappers: schema removal, read-only action enums, and bridge-time denial.
- Removed the streaming bypass: MTClaw handles the request first and ClawOS emits SSE with routing and trace metadata.
- Added strict local competition configuration and launcher: MTClaw required, fallback disabled, no cloud model fallback.
- Added vendored MTClaw provenance fingerprints, a five-case vertical routing benchmark, an offline architecture gate, regression tests, and a new enterprise-standard acceptance report.

Verification:
- `python -m unittest discover -s clawos\tests`: `229 tests OK`.
- `python clawos\scripts\run_frozen_benchmarks.py`: `30/30 passed`, P95 `500.27 ms`.
- `python clawos\scripts\evaluate_model_acceptance.py --provider mock`: `150/150`, rate `1.0`.
- `python clawos\scripts\run_mtclaw_vertical_acceptance.py`: `5/5 passed`, contract P95 `0.062 ms`.
- `python clawos\scripts\validate_competition_architecture.py`: architecture gate `95/100`, competition architecture ready `true`, enterprise release ready `false`.

Known notes:
- The original GitHub URL and upstream commit SHA for the vendored MTClaw snapshot were not retained; `MTClaw-框架代码/UPSTREAM.md` records local commits and SHA256 fingerprints but needs owner-supplied upstream identity.
- MTT AIBOOK/Qwen performance, real model quality, real ASR, and paper claim-to-citation gold-set acceptance remain external blockers and were not simulated as passed.
- Existing `clawos/skills/skill_registry.jsonl` worktree state and untracked `tmp/` files remain outside this development block.
- FastAPI `on_event` and Chroma telemetry emit non-blocking deprecation warnings.

Recommended next step:
- Record the exact MTClaw upstream URL/SHA, then run `scripts/start_competition_stack.sh` and the same frozen/vertical gates on MTT AIBOOK with resource, latency, routing-accuracy, ASR, and paper-quality evidence.

### 2026-07-10 - Repository sync with competition architecture

Completed:
- Merged `origin/master` at `513d3b0` into `codex/p0-demo-polish` while preserving the verified local Qwen3.5-9B provider, installer, retrieval-device, maintenance, and Paper Studio timeline changes.
- Resolved the only content conflict in `PROJECT_CONTEXT.md` by retaining both the local 9B/workbench history and the remote Stage 1/MTClaw competition architecture history.
- Automatic merges in `clawos_server.py`, console assets, and routing/frontend tests were retained after full regression validation.

Verification:
- Python compilation passed for the merged server, MTClaw bridge/runtime, competition validators, and model acceptance script.
- `node --check clawos/static/assets/console.js` passed.
- Competition architecture validation passed at `95/100`; the only blocker is the missing original MTClaw upstream URL/SHA.
- Full suite: `234 tests OK`.

Recommended next step:
- Confirm the original MTClaw upstream URL/SHA, then finish the local embedding/reranker assets and run the vector database and Paper RAG acceptance gates.

### 2026-07-11 - Local semantic retrieval runtime preparation

Completed:
- Installed the declared local retrieval dependencies in `clawos/.venv`: CPU-only PyTorch `2.13.0`, sentence-transformers `5.6.0`, transformers `5.13.0`, and ChromaDB `1.5.9`.
- Verified a real temporary Chroma persistent store can index, reopen its local collection contract, and return an offline vector query without cloud APIs.
- Searched the Hugging Face cache and common user/download/project model locations for reusable Qwen3 embedding/reranker weights. No complete local copy was found; an existing valid embedding safetensors prefix was reused.
- Completed `Qwen3-Embedding-0.6B/model.safetensors`: size `1,191,586,416` bytes and SHA256 `0437E45C94563B09E13CB7A64478FC406947A93CB34A7E05870FC8DCD48E23FD` both match the committed manifest.
- Verified the real ClawOS `MemoryVectorStore -> Chroma -> Qwen3-Embedding` path on CPU with a 1024-dimensional multilingual query; the relevant local-workbench document ranked first with no fallback.
- Extended `download_qwen_model.ps1` to support repository-style embedding/reranker manifests, metadata/tokenizer sync, resilient range retries, exact safetensors verification, and an optional explicit `-Proxy` without hard-coding a personal proxy.
- Downloaded the complete Qwen3-Reranker repository metadata/tokenizer set and resumed its main weight to `168,019,048 / 1,191,588,280` bytes before the next network quota pause.

Verification:
- Dependency imports and versions passed; `torch.cuda.is_available()` is `False`, matching the CPU isolation policy for embedding/reranking.
- Chroma smoke: provider `chroma`, fallback reason empty, one persisted knowledge vector indexed and retrieved successfully.
- `python -m unittest tests.test_memoryos_mvp tests.test_retrieval_reranker tests.test_memoryos_governance`: `18 tests OK`.
- Qwen3 embedding load/encode smoke: shape `[3, 1024]`, CPU load succeeded, and the cross-language related pair scored above the unrelated pair.
- Qwen3-backed Chroma integration smoke: provider `chroma`, embedding provider `qwen3`, dimension `1024`, fallback reason empty, and the expected document ranked first.
- PowerShell parser validation passed for `download_qwen_model.ps1`; provider/retrieval regression: `31 tests OK`.

Known notes:
- Reranker metadata is complete but its main safetensors file is still partial and must not be enabled before size/SHA256 verification.
- FlClash exposes a working mixed proxy at `http://127.0.0.1:7890`. A proxy resume attempt was paused when the environment network usage limit rejected the request; the partial target remains resumable.
- `vector_db_acceptance.py` and `paper_rag_acceptance.py` have not been run with reranking because the reranker weight is incomplete.

Recommended next step:
- Resume the reranker with `download_qwen_model.ps1 -ManifestPath clawos\models\qwen3_reranker_0_6b.json -Proxy http://127.0.0.1:7890`, verify its manifest hash, then run `vector_db_acceptance.py --json` and `paper_rag_acceptance.py --json` before enabling Qwen3 semantic retrieval by default.

### 2026-07-11 - Console readability and knowledge explorer closure

Completed:
- Replaced the remaining history conversation cards with compact, high-contrast navigation rows and strengthened the shared Chinese/English typography hierarchy across controls, tables and metadata.
- Added a standalone full-screen knowledge relationship explorer with node-type, relation and text filters, responsive relationship rendering, counts, legend and a contextual node inspector.
- Kept Home, Product and AI Academy navigation available while preserving the single-rail, content-first console structure established by the accepted product references.
- Added static regression contracts for readable history styling and the knowledge explorer structure and behavior.

Visual verification:
- Loaded the live console in the in-app browser at 1440 x 1024 and inspected workbench, history/search, knowledge library and expanded graph states.
- Confirmed the legacy dark/diagonal overlays and composer obstruction are absent; history rows and knowledge controls remain readable without overlap.
- Confirmed the full-screen graph fits the viewport and provides filters, canvas, legend and inspector as a distinct analysis workspace.
- Browser console was empty during the workbench validation pass. Local screenshots are retained under `tmp/ui-qa/` and intentionally excluded from Git.

Verification:
- Bundled Node syntax check for `clawos/static/assets/console.js`: passed.
- Frontend static suite: `37 tests OK`.
- Full regression suite: `259 tests OK (skipped=1)`.
- Bundled Node syntax check and `git diff --check`: passed.

Known notes:
- Knowledge graph coordinates are deterministic and client-rendered; very large production graphs should later add semantic clustering and canvas/WebGL virtualization.
- Existing user changes in `clawos/skills/skill_registry.jsonl`, `clawos/output/` and `tmp/` remain outside this commit.
