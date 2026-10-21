# Agent / ClawOS Workspace

教育新增 `/academy/lab`：36个由基础到AI前沿的单元、整书目录与带原文依据的知识图谱、人工先修复核、教师校准工作台，以及冻结题组的前测/后测/至少七天延迟测、双人盲评、独立仲裁和同身份续期。计划保存实际来源快照，旧版本保留；真实教学效果尚未验证，账户不代表已认证教师或独立真人。见 [教育工作区验收与边界](clawos/benchmarks/EDUCATION_LEARNING_LAB_ACCEPTANCE.md)。现有服务需正常重启载入新增API，本轮没有重启生产。

严格执行验收新增 Windows LPAC 与 Job Object：父进程验证令牌、每命令独立容器、私有标准库运行时、无网络能力、超时和输出限额。
六个冻结的项目模块任务先通过原实现／参考修复／公开样例过拟合负控，再进行同预算单／多代理比较。
这仍是受限配置的内部验收，生产就绪状态保持 false；见 [严格沙箱与任务库验收](clawos/benchmarks/STRICT_SANDBOX_TASKBANK_ACCEPTANCE.md)。
精确编辑锚点在只读规划中校验，错误提案可在既有计费预算内修复。最终全量955项通过；加强契约的富文本真实对照单／多代理均通过，多代理保留首轮失败与自动修复记录。首批六任务总体失败仍保留，尚不支持发布模式收益策略。

编码提案及协作各角色使用授权范围内的 JSON Schema 输出，并在本地严格复核字段、类型、编辑操作和诊断目标。
`requirements` 可附加逐条 `clauses` 和显式 Python `interface`；写前、集成、独立重放及交付检查原契约。
条款绑定测试与静态签名检查有各自的证据边界，不能把 JSON 合法或示例测试通过当作语义正确。
实现与真实模型验收见 [结构化输出与契约验收](clawos/benchmarks/STRUCTURED_CODING_CONTRACT_ACCEPTANCE.md)。

编码策略工作台新增 `/api/workspace/coding/strategy` 和 `clawos/scripts/coding_strategy.py`：
冻结单／多代理执行、记录成本收益建议，并将核验后的真实失败转成反思卡和未发布提示候选。
重复任务不增加独立样本，外部导入仅用于诊断；策略建议不会自动生效。
接口、复现与发布边界见 [编码策略验收](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md)。
候选可用 `rollout` / `rollout_evidence` 实际比较基线与候选，冻结预算和后置重放证据；
离线门禁不足30个独立任务簇时保持未发布，详见 [专门编码候选验收](clawos/benchmarks/CODING_CANDIDATE_ROLLOUT_ACCEPTANCE.md)。

ClawOS 是一个 Windows 本地个人 Agent OS 原型，围绕 observe-plan-execute-reflect-memory-improve 闭环组织模型路由、工具调用、任务状态、记忆和反思审查。

## 接手先读

新协作者优先阅读：

1. `WORK_STATUS.md`：当前全局状态、功能全景、风险和活跃任务。
2. `PROJECT_CONTEXT.md`：当前分支、提交、验证基线和协作护栏。
3. `PROJECT_ROADMAP.md`：本地工作台的阶段目标与完成门槛。
4. `clawos/README.md`：ClawOS 子项目说明。
5. `clawos/MTCLAW_INTEGRATION.md`：MTClaw 接入说明。
6. `.agents/skills/`：仓库内协作技能。

## Windows 本地启动

从任意 clone 路径进入仓库根目录：

```powershell
cd <your-cloned-agent-repo>
.\start_clawos.bat
```

新增日常工作台入口：`/data-lab` 支持 CSV/TSV/XLSX 清洗、派生列、分组统计、图表和处理流程导出；
`/meetings` 支持原文草稿、复核发布、行动项和协作文档；`/academy/notes` 支持按文档授权的阅读/评论/编辑与版本冲突保护。
会议及文档可生成带来源的飞书审批草稿，实际发送仍需配置就绪、白名单和原生审批。
双架构仍为 ClawOS 工作台/MemoryOS → MTClaw 函数路由 → 受限工具桥 → 请求级证据。
本轮验收及未完成的真实租户/长期并发部分见 `clawos/benchmarks/COLLABORATION_DATA_MTCLAW_ACCEPTANCE.md`。

编码协作新增 `autonomous_subagents` 的 `reliable_coding` 模式：模型按授权文件拆分任务，
独立 Git 工作区并行修改，依赖任务接收真实提交，统一集成、冲突处理、测试与评审。
检查点支持核对已完成提交后恢复；源仓库不自动应用或推送。
接口、复现和验收边界见 `clawos/benchmarks/RELIABLE_MULTI_AGENT_ACCEPTANCE.md`。
通过后可在新工作区重放补丁并复验测试，冻结交付清单与差异，再按精确摘要确认。
交付确认不自动应用源仓库；脏草稿、源码漂移和证据损坏均有独立门禁。
本阶段接口与证据见 `clawos/benchmarks/RELIABLE_MULTI_AGENT_CLOSURE_ACCEPTANCE.md`。
调用方可附加 `requirements`，将冻结需求绑定到授权路径及原测试命令索引；规划、工作者、恢复与交付均保留这些绑定。
测试失败时先读取实际失败上下文并诊断目标，再限定范围修复；明确声明的类型规则机械修复单独记录为非模型生成。
真实项目切片及连续两次退出恢复证据见 `clawos/benchmarks/CODING_RELIABILITY_STAGE1_ACCEPTANCE.md`，不代表公开基准成功率。
单代理提案、迭代编辑与可靠协作共用版本化源码视图：授权写路径、只读依赖、行号/符号、实际失败帧及字节摘要；编辑前核对源码，协作恢复和交付核对上下文凭据。
Python本地依赖有界解析；大仓库任务需明确收窄路径。实现及验收边界见 `clawos/benchmarks/SHARED_CODING_CONTEXT_ACCEPTANCE.md`。

`clawos/scripts/compare_coding_pipelines.py` 可在同一冻结快照、授权范围、需求、测试和预算下，
比较单代理与可靠协作完整链路；预先声明重复次数，交替执行顺序，保留失败及实际调用凭据。
支持显式配置多个本地模型；当前真实验收只使用本地 Qwen3.5-9B，不能当作跨模型质量排名。
报告区分记录完整、实际执行可比较、预算合规和任务通过；完成报告不等于编码成功。
协议、复现及真实负例见 `clawos/benchmarks/CODING_PIPELINE_COMPARISON_ACCEPTANCE.md`。

论文报告支持全窗口阅读、实验条件/原文引用及 Markdown、PDF、JSON 下载，重新生成保留旧文件；
工作台历史支持完整归档分页、全文查询、导出和会话恢复。文本工具支持预览、仅创建与 SHA-256 冲突保护。
自进化候选绑定当前策略版本并支持受所有权保护的回滚。CodingWorkflowService 可用
`CLAWOS_REQUIRE_OS_SANDBOX=1` 要求已安装的 Windows AppContainer，缺少边界时拒绝执行；
默认兼容路径及文件锁并不等同完整操作系统隔离。本轮证据与后续边界见
`clawos/benchmarks/FILE_HISTORY_EVOLUTION_ACCEPTANCE.md`。

策略演进实验室支持反思多候选、冻结任务成对回放、独立留出与任务类别门禁，
以及带租约校验的检查点恢复。已使用的留出题禁止跨实验重用；模型成对输出可冻结为
匿名 A/B 盲评包，收录不可覆盖的具名评分、分歧及完整证据。上传评分不计入线上发布证据，
模型执行与审核者身份仍需独立认证。验收与边界见
`clawos/benchmarks/SELF_EVOLUTION_STAGE2_ACCEPTANCE.md`。

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
