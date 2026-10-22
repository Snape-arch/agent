# 编码协作收益与失败候选验收

2026-10-07，继续阶段4的同任务／同预算比较。此阶段实现后端策略工作台和诊断候选入口；不把候选生成等同于策略已经提升。

## 实际行为

- `CodingStrategyService` 预览并持久化冻结决策。没有已发布策略时，使用调用方明确选择的 single 或 multi 基线；发布策略由原 `RuntimePolicyController` 解析，保留 shadow/canary 分配。执行中或入库前版本变化会拒收。不会自动应用生成的业务补丁。
- 成对比较沿用相同授权范围、原测试／后置命令、模型配置和预算。收益为 `accepted - .10*token_fraction - .05*wall_fraction - .02*call_fraction`；先按任务簇平均重复运行，再对任务簇等权。1000次确定性 bootstrap，检查两个模式采用单侧97.5%下界。至少30个成对任务簇、下界大于0.02才产生建议；建议仍只是候选，不自动改变运行模式。
- 分桶是事先固定的文件数量、Python／混合语言、需求绑定和命令数量。模型配置、执行器见证、预算及提示策略摘要隔离数据。它不是语义任务难度估计，也不是AST依赖图路由。同样任务换ID／路径不增加样本；改写任务文本可能形成新摘要，实际独立性仍需维护者审核。
- 外部导入报告始终标为 imported，不会变成 native-paired。选中模式的单次运行也不能冒充成对实验。任一端缺少完整回答／已知usage、预算超限或存在基础设施问题时，整对不参与收益估计；失败仍留在原报告和诊断列表。这种删失会限制估计适用范围，应连同排除数量审核。
- `CodingEvidenceService` 有界读取并核验计划／任务／报告摘要、调用预留与回答绑定、usage计费和预算谓词、冻结命令及补丁摘要；多代理同时核验原生检查点、执行上下文与回答绑定。每次提议前重新读取并核验原文件，变动即拒绝；数据库保存规范化诊断和摘要，不复制模型文本到反思卡／候选提示。
- 格式、测试和其他流水线失败可以产生反思卡及静态白名单提示候选；重复失败幂等去重。预算、环境、来源完整性和未知传输不会冒充语义失败。分类基于可观察事件，不能证明具体语义根因。候选不新增运行质量信号，不发布、不修改源代码。
- 现有通用配置探针不能证明编码策略收益。`SelfEvolutionManager` 对 `coding.proposal` 与 `coding.strategy.*` 增加 `coding_execution` 缺失门禁，通用回归即使通过仍不能进入 shadow。目前专门的真实基线／候选编码 rollout 评估器尚未实现，编码候选保持未发布；需要后续完成该评估器，再沿用真实新样本、shadow/canary及回滚门禁。

## 可复现入口

`POST /api/workspace/coding/strategy` 的 action：preview、run、compare、ingest、failures、nominate_failure、nominate_routing。执行需 `confirmed: true`；case 是阶段4的七字段冻结对象：id、repo、objective、paths、test_commands、post_commands、requirements。repo 必须是干净的显式Git快照。离线诊断与候选提名无需模型。

本地CLI默认使用显式隔离数据库，workspace必须位于忽略的output内，模型端点仅接受无凭据loopback HTTP：

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/coding_strategy.py ingest --workspace clawos/output/coding-state --folder clawos/output/cc4-20261007-v2/comparison
.\clawos\.venv\Scripts\python.exe clawos/scripts/coding_strategy.py failures --workspace clawos/output/coding-state
.\clawos\.venv\Scripts\python.exe clawos/scripts/coding_strategy.py nominate_failure --workspace clawos/output/coding-state --category format
.\clawos\.venv\Scripts\python.exe clawos/scripts/coding_strategy.py compare --workspace clawos/output/coding-state --case <frozen-case.json> --url http://127.0.0.1:18932/v1 --model Qwen3.5-9B-Q4_K_M --execute
```

文件内容摘要只证明自有本地记录一致，不是第三方密码学来源证明；导入内容不能用于运行晋升。运行器记录选择性的已加载源码见证，不能证明整个环境／模型权重／OS隔离。所有测试均为维护者指定的测试，不是独立外部盲测。

## 验收记录

新增机制测试第一轮17项/132.103秒有1个错误：测试查询使用了反思卡对外字段trigger，实际数据库列为trigger_type；修正测试后20/20（145.318秒）通过。随后补充跨namespace同任务失败计数测试，纳入最终全量回归。没有放宽产品行为、命令或断言。

通过CLI导入阶段4真实Qwen报告，完整核验两个成功／两个失败arm及原生凭据，来源始终imported；两次单代理格式失败去重为一张反思卡、一个任务簇，先产生候选#1且保持candidate。

新真实Qwen任务是自有小型finite-numbers库、一个授权函数，4项公开测试与5项维护者后置测试。两个模式保持默认24调用/50,000计费token/1800秒、输出1800token、请求及命令300秒、3次编辑尝试：

| 模式 | 实际调用 | 实际计费token | 总耗时秒 | 验收结果 |
| --- | ---: | ---: | ---: | --- |
| single | 2 | 2734 | 87.015 | FAILED：实际格式修复后仍非法JSON，未应用业务补丁；共同重放原测试仍失败 |
| multi | 4 | 5027 | 140.281 | FAILED：工作者经历一次真实格式修复；内部公开4项通过及模型评审通过，独立重放后置5项有1项失败，错误接纳int子类 |

多代理编排内部status=passed仍被外层共同重放拒绝，没有将其包装成任务成功。机械代码修复0，源快照未变；新任务只有一个可写文件，不是2工作者并行验收。两个arm均已知usage、完整回答、预算合规且见证稳定；两者失败照常进入成对记录。此任务不是一般项目成功率，也不是CC/Codex或多模型比较。

新报告位于output/cs/8a87a3311f，CLI与审计位于output/cs5-20261007。报告文件SHA256 **5d251f664f33e221def8257a6a8dfcec11f7e26370ccc9e9c6357868b99c0210**，计划摘要c29c40c838b3e521b8c0d42045aa43511826b8b7d9efd3f654c752f78671f9e7，14个选择性源码见证。验收后只修改失败候选的独立任务计数：同task_group跨模型／预算namespace不再重复计数；该修改在真实执行期间未发生。最终策略见证因此不同，新报告保留为原版本native-paired证据；原namespace可用任务簇1、平均multi-minus-single收益-0.007732、无建议，最终namespace匹配样本0。不能把旧执行当作最终版本新的训练样本。最终计数修正由全量测试验证。

独立审计重新核验2个完整报告包（一个历史imported、一个新native-paired）。共4条失败观察、3张幂等反思卡；再次提名格式候选#2覆盖2个任务簇，测试候选#3覆盖1个。候选#1保留历史；全部未发布，运行策略数0，新增质量信号0，调用第二次提名返回相同ID。审计保留output/cs5-20261007/audit.json。CLI首次使用未解析的cwd相对folder时被拒读，已修正resolve后再核验；没有跳过摘要检查。

本轮自有18932/PID71472按exe与UTC启动时刻（13:55:25.5394210Z）核对，14:01:06.2445351Z已退出；第一次关闭因PowerShell JSON日期转字符串格式不一致被身份检查拒绝，改用UTC ticks精确比较后关闭，没有杀其他进程。生产与原预览未重启，权重只读。

最终隔离全量 **913/913（1563.131秒）**，output/regression/5d1b1b8e92d644fda13caeb33bc2edea，日志output/strategy-full-final.log；包括最终21项新增机制测试及原892项兼容回归。原SWIG/FastAPI弃用、openpyxl表头和asyncio慢回调警告不阻断。8个变更Python文件编译通过、执行前后源码指纹一致、差异空白检查通过；最终8文件bundle **91ce573f04e59da0e3b3dda5afba51fc34675e475d4df6da2b56a3d5e6a1dc3f**（相对路径→原始字节SHA256的排序紧凑JSON再SHA256）。日常数据库最终SHA256仍 **8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543**。

源码、测试与验收文档按已授权origin/codex/coding-agent-competitive-p0-p2提交推送；不提交tools、权重、凭据、数据库、output或原有skills/skill_registry.jsonl改动，不强推、不合并master。

## 仍需完成

真实独立任务与第二个模型的覆盖、编码策略专门rollout评估器、删失与长期分布漂移审核、任务语义独立性审查、证据规模增大后的索引与性能，以及图形化策略工作台。现有数据不足以发布自学习编码策略。严格文件系统／不可绕过socket隔离及production_sandbox_ready仍未通过；历史48小时文档负载FAILED不变。本轮不新增前端／浏览器／屏幕阅读器或多天验收。
