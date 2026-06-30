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
