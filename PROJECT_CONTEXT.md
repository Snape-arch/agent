# Project Context

## Agent Product P0-P2 software closure (2026-07-30)

- Added the canonical `clawos.task-run.v2` state/event protocol across API,
  existing task streaming, workers, and the VS Code source integration.
  Transitions are fail-closed; terminal runs cannot silently resume; checkpoint
  URI/digest evidence is included in a replayable event graph.
- The VS Code MVP now creates and updates the canonical run, opens native Git
  changes, retains the last result, supports explicit checkpoint rewind, and
  records cancellation/failure rather than leaving a hidden running task.
- Expanded deterministic lifecycle governance to `clawos.agent-hooks.v2` with
  matcher, scope, handler type, and task/subagent/worktree/checkpoint/compact
  events. Existing synchronous enforcement remains compatible.
- Added default-deny plugin manifest validation, a capability-aware Agent SDK
  registry, multi-agent graph/worktree validation, and a least-privilege
  sandbox plan. The sandbox truth boundary fixes `os_enforced=false` until a
  real OS backend probe passes.
- Added context and memory explanations, explicit confirmed memory enable/
  disable controls, and modular `/api/agent-product/*` contracts. Product
  Readiness now detects the unified protocol, Hook v2, SDK, safety truth
  boundary, explainability, and IDE change/rewind loop.
- Validation: 32 focused tests passed; full regression passed **396 tests** with
  0 failures. Python compilation and bundled-Node VS Code syntax validation
  passed. Only pre-existing FastAPI `on_event` and PyMuPDF/SWIG deprecation
  warnings remain.
- Truth boundary: this is software-contract closure only. Signed VSIX,
  production OS sandbox enforcement, real-user/repository lift, target
  hardware, advanced Router/Trajectory RL/LoRA promotion, and online RL are not
  claimed. See `clawos/AGENT_PRODUCT_P0_P2.md`.
- Next step: implement and probe Windows/Linux OS sandbox backends, package/sign
  the VS Code extension, then run long-lived real-repository TaskRun recovery
  acceptance without relaxing any learning or product evidence gate.

## Product maturity P0-P2 software closure (2026-07-30)

- Real coding A/B evidence now has a strict JSON contract: unique blinded
  cases, repository/issue identity, distinct baseline/candidate policies,
  hidden-test and patch digests, latency, cost, regression, rollback, human
  intervention, and safety metrics. Promotion requires at least 30 valid cases
  across five repositories plus positive cluster-bootstrap lift.
- The local evaluator can run real Git repositories in isolated detached clones;
  the paired benchmark CLI can persist a fail-closed report.
- Added a Python 3.12 hosted-CI contract with exact test dependencies, full
  tests, compilation, and VS Code syntax validation.
- Added a modular `GET /api/product/readiness` router and CLI. Current truth:
  `software_contracts_closed=true`, `product_ready=false`, and
  `online_rl_claimed=false`.
- The VS Code source MVP now has health preflight, proposal preview, explicit
  apply/test confirmation, cancellation, timeout, and visible error handling.
  A signed VSIX is still not claimed.
- Current observed evidence remains 3 controlled fixtures, 0 passes,
  0 real-repository cases, 3 trajectories, 3 grounded evaluator feedback
  records, 0 independent humans, and no target-hardware result.
- Validation: 52 focused product/coding/learning tests passed; full repository
  regression passed **390 tests** with 1 environment-dependent skip. Python
  compilation, bundled-Node syntax validation, and `git diff --check` passed.
- See `clawos/PRODUCT_MATURITY_P0_P2.md`.

## Coding evaluator data P0-P2 closure (2026-07-30)

- Codex feedback is now an explicit `codex_evaluator` provenance class. It
  requires an evidence digest and evaluation method, contributes to grounded
  task-quality feedback, and never inflates independent-human counts.
- Unknown model action probabilities are persisted as zero and excluded from
  propensity-complete OPE evidence. Production Agentic Coding actions now enter
  the task-bound learning trajectory when a real task ID is available.
- Invalid patch planning and execution are recoverable observations inside the
  same trajectory instead of escaping the loop and leaving a running trace.
- Added a reproducible local coding evaluator with hidden tests and aggregate
  truth-boundary reporting.
- Real Ollama `qwen3.5:0.8b` collection: **3 executions, 0 passed**, mean about
  **12.0 seconds**; 3 completed trajectories, 10 decision steps, 3 grounded
  Codex feedback records, 0 independent humans, and 0 OPE-eligible decisions.
  These negative results are retained rather than rewritten as successes.
- Reward Calibration, Preference Ranker, deep Router, Trajectory RL, and
  behavior LoRA remain blocked by data gates; `online_rl_claimed=false`.
  See `clawos/CODING_AGENT_EVALUATOR_DATA_P0_P2.md`.
- Validation: 32 focused learning/coding tests passed; full repository
  regression passed **385 tests** with 1 environment-dependent skip.

## Coding Agent Competitive P0-P2 closure (2026-07-30)

- Production autonomous coding now uses a bounded multi-turn
  observe/action/edit/test/review loop and requires task/session identity.
  Context, model, tool, edit, test, review, and recoverable-failure steps are
  persisted in atomic, digest-bound trajectories.
- Context governance now auto-compacts long sessions and supports path-scoped
  `.clawos/rules` and `.claude/rules` alongside `AGENTS.md`/`CLAUDE.md`.
- LSP sessions are persistent per repo/command and cover symbols, definition,
  references, hover, rename, diagnostics, and document synchronization.
  Headless text/JSON/stream-JSON and a source-level VS Code MVP are present.
- Router training and evaluation use persisted repository/task/session
  group-disjoint splits. The critic evaluates only holdout IDs with a
  training-only outcome estimate. Self-evolution requires 30 paired,
  independent control/candidate identities before promotion.
- Trusted review evidence now requires the server-side HMAC key. Coding
  readiness gained exact evidence mappings for trace wiring, signatures,
  agentic loop, persistent LSP, IDE/headless entry, scoped rules, disjoint
  evaluation, and paired canary control.
- Focused competitive/RL/self-evolution regression: **35/35 passed**. Root
  full regression: **381 passed, 1 skipped, 0 failed**. Python compilation,
  bundled-Node JavaScript syntax, and `git diff --check` passed.
- Truth boundary: this is a software closure only. Real trajectories,
  preference pairs, model lift, target-hardware/OS sandbox validation, packaged
  VS Code distribution, online RL, deep Router, Trajectory RL, and behavior
  LoRA are not claimed. See
  `clawos/CODING_AGENT_COMPETITIVE_CLOSURE_P0_P2.md`.

## Coding Agent Trust P0-P2 closure (2026-07-30)

- Release evidence is now commit-bound and reproducible: a dirty worktree is
  rejected, each capability maps to exact test IDs and its own transcript
  digest, and readiness rejects stale-commit evidence.
- Missing satisfaction stays missing. Self-evolution, UCB policy, lightweight
  router, trajectory critic, and artifact activation use a shared 30
  independent-sample floor; repeated aggregate snapshots cannot inflate it.
- Autonomous coding persists Context/Model/Edit/Test/Review trajectories.
  Normal tool routing and autonomous coding share identity, resource budgets,
  lifecycle hooks, and application-level egress governance.
- Context assembly now performs repository inference, enforces a global token
  budget, and persists real conversation summaries before deleting compacted
  history. CI/review provenance supports tamper-evident HMAC verification.
- Focused affected regression: **34/34 passed**. Root full regression:
  **377/377 passed, 0 failed**. Python compilation and `git diff --check`
  passed; only pre-existing FastAPI/PyMuPDF deprecation warnings remain.
- Truth boundary remains unchanged: current local learning data is still
  below real-data thresholds; `online_rl_claimed=false`; no target-hardware,
  real-model lift, behavior-LoRA, editor-extension, or hosted CI integration is
  claimed. See `clawos/CODING_AGENT_TRUST_CLOSURE_P0_P2.md`.

## Coding Agent Product P0-P2 closure (2026-07-30)

- The normal chat/MTClaw context path now injects the repository context pack;
  repository symbol/dependency analysis uses a persistent content-addressed
  incremental cache.
- Coding readiness is fail-closed. The previous static `verified=true` map was
  removed and replaced by integrity-checked, expiring capability evidence.
- Added real stdio JSON-RPC LSP handshake and document-symbol support.
- Added a bounded model-driven propose/patch/test/repair loop. Every write
  requires confirmation, every edit round has a checkpoint, failed attempts
  restore files, and commits remain human-reviewed.
- OPE now accepts per-record target probabilities and uses group-held-out
  reward estimates. OPE, trajectory-ranker, and offline-policy outputs have a
  durable candidate/evaluated/shadow/active/rollback registry.
- Added a minimum-30 real blinded patch-task A/B gate, IDE context contract,
  traceable CI plus two-reviewer gate, safe worktree cleanup, and read-only
  merge planning.
- Focused product-closure tests: **8/8 passed**. Root full regression:
  **374 passed, 1 skipped, 0 failed**. Python compile checks passed.
- The evidence verifier reported `software_p0_p2_closed=true`; its local
  evidence expires on 2026-08-29 and must then be regenerated.
- Truth boundary: online RL, real-model patch lift, real user feedback,
  target-hardware validation, LoRA/adapter training, and production editor/CI
  distribution are **not claimed**. See
  `clawos/CODING_AGENT_PRODUCT_CLOSURE_P0_P2.md`.

## Coding Agent Excellence P0-P2 软件闭环（2026-07-29）

- 当前开发分支：`codex/coding-agent-excellence-p0-p2`，基于
  `codex/competition-readiness-p0-p2` 的 `3b702ba`；本轮已创建本地提交
  `feat: close coding agent excellence P0-P2`。远端推送被租户安全策略阻止，
  当前分支尚未发布。
- P0 因果评测：自进化 frozen/core 子进程现在真实接收 baseline/candidate
  payload，工具路由候选在执行器中生效；新增 prompt/retrieval/routing/report
  runtime materializer。自动门禁要求执行摘要存在且候选产生可观察变化，避免
  “配置只进入 digest、没有进入执行”的静默通过。
- P0 学习证据：决策轨迹新增完整候选集、全量分数、选择概率、策略版本、
  探索来源、随机种子和上下文摘要；新增 IPS/SNIPS/DR、cluster bootstrap、
  ESS、overlap、时间留出和场景分段门禁。支持不足时明确 abort，不激活策略。
- P0 Coding Context Kernel：新增层级指令、Token 预算、任务相关代码片段、
  Repo Map、Python AST/轻量跨语言符号和依赖、测试映射、Git 上下文、
  IDE/LSP diagnostics、来源信任和 digest。Coding Workflow inspect 已直接返回
  Context Pack，并纳入未跟踪但未忽略的工作区文件。
- P1 编码执行：新增结构化多 hunk 修改、自动测试建议、Python 语法审查、
  `git diff --check`、有界修复、原子写入、checkpoint 和失败精确恢复；
  新增显式确认的 Git Worktree 隔离与 scoped local commit，永不自动 push。
- P2 离线学习与治理：新增 Trajectory Preference Ranker、AWR candidate dataset
  sandbox、身份/角色边界、网络 host/port egress、模型/工具/Token/时间预算、
  lifecycle hooks 和统一 Coding Agent Readiness。
- 新增 API：`/api/agent-learning/ope/evaluate`、
  `/api/agent-learning/trajectory-ranker/train`、
  `/api/agent-learning/offline-policy/sandbox`、
  `/api/coding-agent/readiness`、Coding Worktree/Commit 入口；coding tool schema
  同步支持 Context Pack 与 test discovery。
- 新增 20 条真实 ClawOS 仓库上下文冻结任务：
  `clawos/benchmarks/coding_repository_v1.json`。最新执行 **20/20 通过**，
  MRR `0.377222`，P95 `1312.264ms`。该结果只证明仓库上下文获取，不证明
  模型补丁质量。
- 专项回归 **31/31 通过**；根目录全量 **366/366 通过**。`git diff --check`
  通过，仅有行尾转换提示；原有非阻断警告仍为 MTClaw FastAPI `on_event`
  和 PyMuPDF SWIG 类型弃用警告。
- 事实边界保持：`online_rl_claimed=false`；真实轨迹、Preference、反馈与 OPE
  样本门槛未达时不激活深度 Router/Trajectory RL/LoRA；无目标硬件时
  `hardware_validated=false`。完整说明见
  `clawos/CODING_AGENT_EXCELLENCE_P0_P2.md`。
- 下一步：用 20-50 个真实“修改+测试”仓库任务采集完整反事实轨迹，补真实
  模型补丁成功率；随后接入实际 LSP 进程/IDE client，达到数据门槛后才允许
  Router/Trajectory Ranker 进入 Shadow。不要先扩大网络或启动 Nightly LoRA。

## Competition Readiness P0-P2 闭环（2026-07-26）

- 开发分支：`codex/competition-readiness-p0-p2`；基于反馈学习提交 `44c0283`。
- P0：新增科研、学习、办公、项目四条黄金演示合同，每条均绑定版本化冻结基准；
  聚合比赛架构、显式反馈数据面与 Task-bound Reward 修订证据。
- P1：新增统一学习运营视图，展示真实轨迹、反馈覆盖、偏好场景覆盖、Reward
  Calibration 与 Preference Ranker 的数据门槛和 Active / Shadow 状态。
- P2：统一展示深度 Router、Trajectory RL 和行为 LoRA readiness，固定保持
  `online_rl_claimed=false`，不自动训练或上线。
- 新增目标硬件证据模板与严格校验：离线模式、MTClaw 必经、fallback 关闭、
  首 Token P95、吞吐、峰值内存及不少于 30 条任务、90% 通过率必须全部有值。
- 新增 `/api/competition/readiness`、硬件证据校验和显式确认导出 API；
  CLI 可导出 JSON/Markdown，并在 `--strict` 下对未就绪状态返回非零。
- 控制台 Self-Evolution 页面新增 Competition P0-P2 面板、四条黄金演示链和
  下一步硬门槛。
- 当前可验证结论：`software_p0_p2_closed=true`，
  `competition_release_ready=false`；没有目标硬件和真实样本时不会误报 Ready。
- 专项测试 **5/5 通过**；架构、Agent Learning、反馈学习、日常验收和前端
  受影响回归 **75/75 通过**；Python、JavaScript 和补丁格式检查通过。
- 根目录全量 **359 项 OK**（1 项按预期跳过）；非阻断警告仍是 MTClaw
  FastAPI `on_event` 与 Chroma/OpenTelemetry asyncio 弃用警告。
- 详细使用与边界见 `clawos/COMPETITION_READINESS_P0_P2.md`。

## 反馈学习与 Preference Ranker P0-P2 闭环（2026-07-26）

- 开发分支：`codex/feedback-preference-p0-p2`；基于 Agent Learning 提交 `4ddff4c`。
- P0：新增绑定终态 Task 的显式反馈记录、幂等写入和聊天赞/踩/1-5 分入口；
  缺失反馈保持 missing，不再伪装成 0.5 中性分。真实反馈会修订对应 Policy Reward
  与 Trajectory Reward。
- Reward Calibration 使用任务隔离的训练/留出集、符号约束线性权重、candidate /
  shadow / active 状态机和人工确认激活。硬门槛为 50 条完成轨迹、20 条显式反馈，
  存在 Arm 时每个 Arm 至少暴露 10 次。
- P1：新增用户条件化 Preference Ranker；训练硬门槛为 100 个有效偏好对，
  learning/research/project/office 每类至少 20，矛盾率低于 15%。留出准确率必须
  至少 55%，且高于长度 baseline 2 个百分点，才可进入 Shadow。
- P2：新增深度 Router、Trajectory RL 和行为 LoRA 的证据型 readiness 报告；
  只读取已观测本地数据，固定返回 `online_rl_claimed: false`，不自动启动训练或上线。
- 新增反馈、数据质量、Reward 校准、Preference Ranker 和高级 readiness API；
  激活操作均要求 `confirmed=true`。
- 专项验证：新增闭环测试 **8/8 通过**；Agent Learning、UCB、Task Runtime 与
  Self-Evolution 受影响回归 **30/30 通过**；根目录全量 **354 项 OK**
  （1 项按预期跳过）。Python 编译、JavaScript 语法和补丁格式检查均通过。
- 全量首轮发现 Windows GBK 无法输出前端字面量赞/踩 emoji；已改为等价 HTML
  数字实体，界面显示不变，隔离基准与失败的 2 项测试复跑通过。
- 无硬件支持的阶段只声明软件闭环和离线门禁成立，不声明真实设备吞吐、延迟、
  功耗、多日稳定性或在线 RL。
- 详细门槛、API 和边界见 `clawos/FEEDBACK_PREFERENCE_P0_P2.md`。

## Agent Learning P0-P2 闭环（2026-07-26）

- 开发分支：`codex/agent-learning-p0-p2`；基于自进化闭环提交 `1a6f12a`。
- P0：新增版本化 Task Trajectory、逐决策 Step、行为概率、多目标 Reward、
  折扣回报、chosen/rejected 偏好对和脱敏数据集 manifest。Task 创建、终态、
  重试和中断恢复均已接入轨迹生命周期。
- P1：新增无重型训练依赖的 Agent Skill Policy Network v0，使用确定性哈希特征
  和分 Arm Contextual-Q Head，输入任务、用户、历史统计和环境状态，输出预注册的
  Agent/Skill/Tool/Workflow/Prompt/检索组合。运行时使用
  `empirical + UCB bonus + 0.35 * learned Q`，保留冷启动探索与安全边界。
- P2：新增离线 Doubly-Robust Trajectory Critic，报告候选收益、lift、标准误、
  95% 下界、effective sample size 和安全违规；通过后进入 Shadow，激活与回滚
  均要求显式确认。Active 模型已进入真实聊天策略选择并继续回流 Task Outcome。
- 新增 `/api/agent-learning/*` 轨迹、数据集、偏好、训练、评估、激活和回滚接口。
- 验证：Agent Learning 专项 **6/6 通过**；Task/Policy/Self-Evolution 受影响测试
  **37/37 通过**；根目录全量 **346 项 OK**（1 项按预期跳过）；Python 编译检查通过。
- 非阻断警告保持不变：MTClaw FastAPI `on_event` 与 Chroma/OpenTelemetry
  asyncio 弃用警告。
- 详细结构、门禁和证据边界见 `clawos/AGENT_LEARNING_P0_P2.md`。
- 下一步：先积累真实、明确反馈的轨迹并校准奖励；达到样本门槛后再做
  Preference Ranker、深度 Router 或 LoRA，不把当前线性 Router 表述为在线 RL。

## 自进化 P0-P2 闭环（2026-07-26）

- 开发分支：`codex/self-evolution-p0-p2`；基线为本地 `master` 的 `ae200cf`。
  开工前 `git fetch origin` 因网络连接重置失败；本地基线当时显示与已知
  `origin/master` 对齐。
- 自动自进化基准已从“根据候选字段合成分数”改为隔离子进程实际执行
  frozen/core E2E 套件和确定性检索 case；证据包含 runner、报告摘要、配置摘要
  和 case count，缺执行证据不能进入 Shadow。
- `prompt_policy`、`retrieval_params`、`tool_routing_policy` 已接入聊天运行时。
  Task 保存策略目标、版本、run、候选暴露、稳定分桶和 Shadow 物化结果。
- Shadow 不影响用户响应；Canary 按 session/task 稳定哈希分桶并真实使用候选。
  至少 3 个 Shadow 样本才可进入 Canary，至少 5 个 Canary 样本才可激活；
  失败/取消/重试信号越线会自动停流。
- Contextual UCB 已能接入 `routing:{scenario}`；选择绑定 Task，reward 从终态
  Task 派生，策略晋升至少需要 5 个样本并按 95% 置信区间下界排序。
- Reflection 可聚类近期重复失败并生成低风险候选；Fresh-agent audit 改为
  `python -I` 独立进程并检测 silent bypass。
- Skill Canary 使用真实稳定分桶，高风险工具不得自动灰度；Canary/晋升必须签名。
  签名密钥来自 OS Keyring `ClawOS/skill-signing` 或本地
  `CLAWOS_SKILL_SIGNING_KEY`，API 不接收 Secret。
- 新增 Skill 库重复/零使用/复杂度审计和保留证据的归档式压缩。
- 验证：受影响测试 **128/128 通过**；根目录标准发现命令全量
  **340/340 通过**（1 项按预期跳过）。首次根目录运行暴露的两个既有测试导入路径问题已补最小修复。
- 非阻断警告：MTClaw FastAPI `on_event` 弃用警告、PyMuPDF SWIG 类型警告。
- 详细边界与验收见 `clawos/SELF_EVOLUTION_ACCEPTANCE_2026-07-26.md`。
- 下一步：在 MTT AIBOOK/真实本地模型上补 A/B、首 token、吞吐、资源峰值和
  多日 burn-in；本轮不把确定性软件基准表述为真实模型质量。

## Windows 桌面安装交付（2026-07-18）

- 新增 `desktop/` 桌面交付层：PyInstaller 无控制台 `ClawOS.exe`、WebView2 原生窗口、单实例、ClawOS/MTClaw 隐藏启动与随窗口退出回收。
- 新增 Inno Setup 用户级安装器：安装到 `%LOCALAPPDATA%\Programs\ClawOS`，任务、配置、日志和产物独立保存到 `%LOCALAPPDATA%\ClawOS`；卸载应用时保留用户数据。
- `clawos_server.py` 新增 `CLAWOS_DATA_DIR`、`CLAWOS_OUTPUT_DIR`、`CLAWOS_ENV_PATH` 等桌面运行路径，密钥、数据库、上传和生成产物不再要求写入安装目录。
- 构建只复制 Git 跟踪的运行文件，明确排除 `.env`、数据库、日志、`tmp`、`tools`、测试、文档、上传、备份和生成产物；`desktop/build/`、`desktop/stage/` 与本地验收 JSON 不进入提交。最终安装包按用户要求通过 Git LFS 跟踪，避免触发 GitHub 100 MB 普通对象限制。
- 本机真实安装验收 14/14 通过：静默安装、便携 Python、无终端启动、ClawOS/MTClaw 健康、控制台 200、真实 `ClawOS` 顶层窗口、关窗回收服务、静默卸载全部通过。最终安装包位于 ignored 的 `dist/ClawOS-Setup-0.1.0.exe`，SHA-256 为 `FBF783FFAABECA0B969F51CA17F7467913D74CB0E1CF2F7355C96B7FFFB9B8D2`。
- Windows UI 自动化已确认软件合成模式下工作台真实渲染，不是仅有后台健康状态；全量回归 **331/331 通过**。
- 证据边界：当前机器为 Windows 家庭中文版且无 Windows Sandbox，故本轮只能声称“本机全新安装级验收通过”。`desktop/ClawOS-Clean-Machine.wsb` 与 `clean_machine_acceptance.ps1` 已提供给 Windows Sandbox/干净 VM；获得另一台环境的报告前，不得声称干净机器实机已经通过。
- 当前安装包未代码签名；比赛发布前应使用正式证书签名并在干净 Windows VM/目标设备上复跑验收。协作者 clone/push 前须启用 Git LFS。

这是 ClawOS 当前状态的简洁交接入口。2026-07-14 以前的详细记录已归档到 `clawos/docs/PROJECT_HISTORY_2026-07-14.md`。

## 历史状态（2026-07-17）

- 当前分支：`codex/p0-demo-polish`。
- 当前提交：`4784d94`；与 `origin/codex/p0-demo-polish` 一致，相对 `origin/master` 超前 1 个文档提交。
- 本轮只有活跃工作文档更新；`.env`、`.workbuddy/`、`clawos/tmp/` 为本地忽略项，不得提交或擅自清理。
- 2026-07-17 沙箱外全量回归：**326 个通过、1 个跳过、0 失败**。沙箱内出现的 4 个失败均由既有输出/备份文件覆盖权限导致，4 项在沙箱外单独重跑通过；不是代码回归。
- 已验证的产品基线仍包括本地 Qwen、Chroma/Qwen3 向量能力、MTClaw 路由、办公工作流、Academy 页面和五条真实证据链。物理目标设备验收及企业连接器真实租户验收尚未完成。
- 2026-07-17 N1 本地启动基线完成：本地 Qwen、MTClaw 与 ClawOS 冷启动、停止、重启和健康检查通过；模型 routing/upstream 真实探针可达，MTClaw 本地热身成功并加载 30 个工具；`FEISHU_LIVE=false` 保持不变。下一步从 N2 六条核心功能闭环开始。
- 本轮只更新 `PROJECT_CONTEXT.md`、`WORK_STATUS.md` 和 `WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md`；未修改代码，未重跑全量单元测试。N1 运行日志位于 ignored 的 `tmp/n1*`，不得提交。
- 2026-07-17 N2 六条核心闭环已用安全测试资料完成：文档 `3/4`、报告任务 `21`、项目任务 `24`、引用/项目/检查点 run 均可重新查询，报告 Markdown/PDF 可重新读取。测试输入和报告位于 ignored 的 `tmp/n2/`。
- N2 修复了 MTClaw 成功路由不持久化 Task Steps 的缺陷：`clawos_server.py` 现在把 MTClaw trace 写为 tool step，`test_mtclaw_adapter.py` 增加回归断言；真实 task `24` 包含 succeeded `tools_list` step 及 step started/finished 事件。
- N2 相关回归共 48 项：沙箱内 46 通过、2 个既有权限/worker 假失败；2 项在沙箱外单独重跑均通过。下一步进入 N3 当前界面桌面/移动端验收。
- 2026-07-17 N3 当前界面审查已覆盖桌面工作台/知识库与 390 × 844 移动工作台/知识库/模型设置；无 P0。用户确认的 4 个 P1（移动知识页头部、分类标签换行、低对比文字、移动菜单名称）已修复并复测，Lighthouse 移动 accessibility 由 96 提升至 100、best practices 保持 100；2 个 P2 按约束未改。

## 飞书连接器 v2

- 状态（2026-07-16）：v2 整改已完成至 Phase 6（runbook + 文档）与 §13 重构、P1-2 控制台收口，12 个阻断缺陷全部关闭；36/36 飞书测试全绿（test_feishu_api 13 + test_feishu_connector 23 + test_feishu_migration 4）。
- 架构性重构（§13）已完成：废弃单一 action 路由 `POST /api/feishu`，改为资源式端点（`GET /api/feishu/health|messages|summaries|approvals|dispatches`、`POST /api/feishu/events|summaries|approvals`、`PATCH /api/feishu/summaries/{id}`、`POST /api/feishu/approvals/{id}/sync|send`）；写操作强制严格 Pydantic 请求模型；HTTP 状态按 §13 映射（400/401/403/404/409/422/502/503/504）。
- 建表/升级已移入真实迁移：`MaintenanceService.apply_migrations()` 通过 `2026_07_feishu_connector` 迁移调用共享 `services/feishu/schema.py`，幂等、可重跑；不再藏在服务构造函数里。
- Phase 6 已完成：新增 `docs/feishu-runbook.md`；本文件同步更新。P1-2 控制台收口已完成：创建审批/发送改为显式二次确认（不再静默提交 `confirmed:true`）、移除手填审批人、未配置时禁用写按钮、空状态行。
- 真实租户只读入站已于 2026-07-16 通过：token 鉴权成功、官方 SDK WebSocket 真握手成功，并实时收到 3 条 `im.message.receive_v1`；关键事件标识均非空。全程 `FEISHU_LIVE=false`，未创建审批、未发送消息。
- 真实预检发现的 token `code:0` 误判已有专门回归测试；正式长连接已区分 `running`（线程存活）与 `connected`（真实 WS 握手）。
- 2026-07-16 用户决定暂停飞书审批与外发验收。WorkBuddy 生成的控制台直发、`POST /api/feishu/send` 和数据库重建改动已全部撤销，未进入提交。必须保持 `FEISHU_LIVE=false`；不得把只读入站称为真实飞书闭环。
- 审查时本地 ClawOS 服务健康、飞书 live mode 关闭；MTClaw 不可达是系统告警，不是飞书连接器阻断项。

## 仓库卫生

- `clawos/skills/skill_registry.jsonl` 会被全量测试修改使用计数；恢复该副作用后再审查 staged 文件，不能提交它。
- `.playwright-cli/` 是本地界面审查产物，不提交；未经用户许可不得删除。
- 永远不要提交 `.env`、凭据、数据库、日志、缓存、上传、模型、生成报告和浏览器证据。
- 本地损坏引用 `refs/heads/codex/backup-master-c663560` 会让部分 `git --all` 命令报 `bad object`；未获用户授权前不要删除或改写。
- 2026-07-14 已完成：清理历史生成物和输入法缓存路径的版本控制、整合忽略规则、归档过长交接记录、审计并回收历史 1.32 GiB Git 模型 blob；本地模型资产保留供复现。

## 交接顺序

1. 先读 `WORK_STATUS.md`、本文件、`README.md`、`PROJECT_ROADMAP.md` 和 `WORKBUDDY_FEISHU_HANDOFF_2026-07-15.md`。
2. 飞书阶段冻结；不继续审批、外发或连接器功能扩展。
3. N0 与 N1 已完成；按接手单继续 N2 六条核心功能闭环、N3 桌面/移动端界面验收、N4 备份恢复和仓库卫生。
4. 先审查后修改；只修阻断闭环的问题，不新增顶层模块或大规模视觉重构。
5. 任何外部发送、真实 API、模型下载、Git push、PR 或共享状态变更均需用户明确授权。

## 常用验证

```powershell
git status --short --branch
.\clawos\.venv\Scripts\python.exe -B -m unittest discover -s clawos\tests
git diff --check
```

## 论文阅读器交互闭环（2026-07-16）

- 已修复 PDF 空态与研究运行面板的 `hidden` 层级问题，阅读器打开原文后不再被品牌图或透明面板遮挡。
- 缩放改为不重载 PDF 的真实视觉变换；补齐适合宽度、全屏、目录折叠/跳页、笔记草稿/保存/删除和批注本地保存反馈。
- 关键阅读器控件改为独立事件绑定，避免黑色工具栏只显示样式但点击无效。
- 变更文件：`clawos/static/academy-paper.html`、`clawos/static/assets/academy.js`、`clawos/static/assets/site.css`、`clawos/tests/test_frontend_static.py`。
- 验证：Node JavaScript 语法检查通过；`python -m unittest tests.test_frontend_static` 为 42/42 通过；内置浏览器已验证遮挡、缩放、笔记保存/删除、画笔与目录折叠。
- 非阻断项：本地历史论文源接口在当前输出目录策略下返回 403，未修改该安全边界；上传任意本地 PDF 仍可在阅读器直接预览。
