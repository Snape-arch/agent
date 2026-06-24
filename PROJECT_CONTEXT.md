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
