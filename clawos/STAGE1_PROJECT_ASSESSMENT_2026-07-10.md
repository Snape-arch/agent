# ClawOS 第一阶段项目评估（2026-07-10）

## 结论摘要

- 当前综合成熟度：**72/100**。
- 纯软件工程完成度：**76/100**；比赛证据完备度：**69/100**。
- 当前适合定位为“可离线演示、可审计、具备多场景工作流的 MTClaw 增强原型”，尚不宜表述为“垂直 subagent 已全部完善”或“实机交付完成”。
- MTT AIBOOK、Qwen/vLLM-MUSA、真实音频、真实论文质量和现场资源数据尚未具备验收条件，本报告将它们标记为待验证，不用 mock/单测代替实机结论。

## 评分口径

| 维度 | 分数 | 判断 |
|---|---:|---|
| 总体架构与模块边界 | 79 | Provider、MemoryOS、任务、工具、Reflection、Skill、场景服务和控制台已经形成闭环，但 `clawos_server.py` 仍承担过多职责。 |
| MTClaw 集成 | 66 | Adapter、双服务、Tool History、Trace 持久化和契约测试真实存在；默认关闭、流式绕过、垂直工具未进入 MTClaw 安全清单。 |
| Function/场景路由 | 61 | 56/56 function 均有 handler；本地 tool loop 可执行。场景评分策略目前只服务 `/api/routing/policy`，没有约束聊天执行路径。 |
| 任务运行时、安全与治理 | 78 | 有确认、审计、幂等、取消、重试/恢复、Skill 治理和回滚基础；仍缺严格资源配额、网络出口隔离和实机场景故障注入。 |
| 自动化验证 | 88 | 全量 221 项单测通过，冻结任务 30/30，mock 模型 150/150；缺真实模型、真实 ASR、真实论文精度和浏览器/实机基准。 |
| 固定角色多 Agent | 54 | Planner/Research/Builder/Reviewer/Risk/Judge 有确定性 trace、gate 和 rework；本质是同进程规则化评审流水线，不是独立上下文、独立模型调用或并行自治 subagent。 |
| 会议纪要工作助手 | 72 | 有会议生命周期、音频上传、可选 ASR、纪要卡、行动项、知识入库、ICS/EML 草稿；说话人分离和字段抽取仍偏启发式。 |
| MTClaw 原生 Coding | 57 | MTClaw 可调用代码统计、目录树、TODO、搜索等只读工具；写入、补丁、测试修复循环和 Git 提交并非 MTClaw 原生闭环。 |
| 知识库构建 | 81 | 文档上传、解析、分块、引用、检索、OCR fallback、图谱、Obsidian 导出和知识回写较完整；默认 hash embedding、图谱关系偏词法。 |
| 论文精读与精度 | 69 | PDF 导入、页级引用、引用校验、对比矩阵、复现实验、学习分析和证据门禁已经存在；`paper_deep_read` 的核心提取仍是关键词/句子启发式。 |
| 教育板块 | 56 | 已有目标、复习、错题、依赖图和掌握度数据结构，不只是空页面；出题内容、诊断、间隔复习和掌握度校准仍是骨架级。 |
| 前端与交付体验 | 76 | 控制台、学院论文页、离线 readiness、历史和维护报告较完整；缺阶段一统一演示脚本和五类垂直工作流的 MTClaw trace 展示。 |

## Function 路由核查

### 确实被使用的链路

1. `functions.jsonl` 由 ClawOS 启动时加载，56 个声明均能在 `tool_runner.handlers` 找到执行器。
2. ClawOS 自己的 routing provider 会把这些 function schema 交给模型，`run_tool_loop` 执行工具调用。
3. 当 `MTCLAW_ENABLED=true` 且请求为非流式时，聊天接口优先调用 `MTClawAdapter.route()`，再读取 `/v1/tool_history` 并写入 `mtclaw_traces`。
4. MTClaw runtime 会从同一份 `functions.jsonl` 筛选 18 个低风险工具并生成 wrapper。

### 当前断点

- `MTCLAW_ENABLED` 默认是 `false`，普通默认启动不会使用 MTClaw Function Router。
- `stream=true` 会跳过 MTClaw，直接进入 ClawOS 本地 tool loop。
- 18 个 MTClaw 安全工具全部偏只读；会议、科研 PDF、论文精读、教育、知识库写入、Git 工作流均不在其中。
- `score_scenarios()`/`SCENARIO_ROUTING_POLICY` 只被 `/api/routing/policy` 调用，当前是“可解释策略展示”，不是实际执行路由器。
- 因此比赛中可以证明“系统接入并使用 MTClaw”，但暂不能证明“几个垂直 subagent 的核心工作都由 MTClaw Function Router 驱动”。

## 垂直能力审计

### 会议纪要工作助手：72/100

已完成：会议创建/处理/查询、音频上传、sidecar transcript、可选 faster-whisper/whisper CLI、结构化会议卡、知识回写、日历与邮件草稿、run record 和阻塞态。

主要缺口：当前 diarization 主要依赖文本标签或轮换式 Speaker 标记；行动项抽取多为关键词句子筛选，负责人、截止时间、决策证据缺少统一 schema 和精度集；真实音频验收尚未做。

### MTClaw 原生 Coding：57/100

已完成：目录、读取、搜索、统计、TODO、文件信息等 7 类代码理解工具可通过 MTClaw；ClawOS 侧另有 project init、受控文件写入、shell、Git 审批/commit/revert。

主要缺口：没有 MTClaw 驱动的 `inspect -> patch -> test -> review -> retry` 循环；写工具被刻意排除在 MTClaw 清单之外；没有 diff 级 CodingAgent 状态、独立 reviewer 或失败恢复证据。因此它现在更接近“MTClaw 原生代码阅读助手”，不是完整 coding agent。

### 知识库构建：81/100

已完成：多格式文档入库、去重、分块、引用、检索、知识条目、OCR fallback、图谱、Obsidian 检查/导出、聊天 RAG 上下文与 run record。

主要缺口：默认 embedding 仍可退化为 hash；reranker 默认关闭；实体/关系图谱主要依赖标签、wikilink 和词法概念；大文档、混合语言和 OCR 噪声下的召回/精确率缺少金标准评测。

### 论文精读与阅读精度：69/100

已完成：论文上传、页面/分块引用、检索、引用合法性、对比矩阵、复现实验工作流、报告/checkpoint/project board、证据一致性门禁。

主要缺口：`paper_deep_read` 的方法、发现、局限提取是关键词启发式；缺章节识别、表格/公式/参考文献解析、claim-to-citation 对齐精度、跨论文矛盾识别和人工标注集。当前“流程完整度”高于“阅读精度证据”。

### 教育板块：56/100

已完成：学习目标、主题项、复习证据、错题、依赖图、掌握度评估和基础练习生成。

主要缺口：练习题目前是通用模板，未基于教材证据生成多题型；没有题目难度标定、知识点诊断、间隔重复调度、rubric 自动评分和长期掌握度校准。用户所说“刚构建骨架”基本准确。

### 固定角色评审队：54/100

已有角色卡、执行 trace、质量门禁、仲裁、rework、知识回写和持久化 run record。但角色分数和结论主要由确定性条件生成，缺独立上下文、角色专属 prompt/model/tool policy、并发调度与真实意见冲突。对外建议称“固定角色多 Agent 评审流水线”，暂不称“自治 subagent 群”。

## 优先级

### P0：第一阶段提交前必须补强

1. **统一并证明 MTClaw 主链路。** 增加 competition profile：默认启用 MTClaw、验收模式关闭 fallback；明确流式请求策略，并让五类演示都能看到 MTClaw trace。
2. **让场景路由真正参与执行。** 将 `score_scenarios()` 的选择结果接入聊天编排，限制候选工具与 model profile，而不是只作为一个查询 API。
3. **给垂直场景增加低风险 MTClaw wrapper。** 优先接入 `meeting_action_items`、`paper_deep_read`、`research_pdf.search/validate`、`learning_workspace.get/graph/assessment`、知识检索；写操作仍走确认和 ClawOS 安全层。
4. **做五条确定性端到端比赛用例。** 每条固定输入、输出、MTClaw Tool History、ClawOS trace、知识证据、耗时、失败原因和截图位；不依赖实机也能先完成软件链路验收。
5. **修正产品表述。** 把领域 workflow、固定角色评审队、自治 subagent 三种概念分开，避免评委追问时暴露架构名实不符。

### P1：有设备前可并行完善

1. 会议：建立 10-20 条带人工标注的转写/纪要集，评估 WER、行动项 precision/recall、owner/due-date 准确率。
2. 论文：建立小型金标准论文集，评估 claim-citation 命中率、页码正确率、方法/结论/局限抽取准确率。
3. Coding：实现受控 patch/test/reviewer/retry 循环，保留每次 diff、命令、退出码和回滚点。
4. 教育：基于知识库证据出题，加入多题型、答案评分、错因分类、间隔复习和校准曲线。
5. 知识库：比赛配置启用真实 embedding/reranker，补召回率、MRR/nDCG 和 citation correctness 基准。

### P2：实机条件具备后

1. MTT AIBOOK 上完成 Qwen/vLLM-MUSA 安装、冷/热启动、首 token、吞吐、内存/显存、工具命中率和断网验收。
2. 跑真实音频、OCR、长论文和并发任务，记录资源峰值、超时、恢复和降级行为。
3. 冻结现场演示配置、离线资产、录屏备份、故障预案和提交清单。

## 本次验证证据

```text
相关模块测试：70 tests OK
全量单元测试：221 tests OK
冻结基准：30/30 passed，pass_rate=1.0，P95=456.679 ms
mock 模型验收：150/150，rate=1.0
function 声明/handler：56/56，无缺失
MTClaw 安全 function：18/18 有 handler；垂直场景 function 进入 MTClaw 清单：0
```

非阻塞警告：FastAPI `on_event` 和 Chroma telemetry 使用了已弃用接口。未执行网络 fetch、真实 API、真实 ASR、Qwen 或 MTT 实机验收。
