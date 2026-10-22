# 专门编码候选评估器验收

2026-10-08，继续a1b1c96。上阶段只能生成诊断候选，此阶段加入真实执行基线与候选的专门评估器，并替换coding_execution永久缺失门禁；没有完成真实样本门槛就不放行。

## 实现与门槛

`CodingRolloutService` 从同一MemoryStore中读取未发布的prompt_policy/coding.proposal或routing_policy/coding.strategy.*候选，冻结候选／基线内容与版本、原Git快照、授权文件、需求、公开及后置命令、模型配置、实现见证、预算及AB/BA顺序。每批1–8个任务、1–3次预声明重复，顺序执行两个变体；调用原CodingStrategyService执行，不替换为配置探针或事先写好的答案。

提示候选进入实际模型消息，先追加再计费和生成输入摘要。模式候选仅可在匹配的运行namespace内改变single/multi。正式运行策略保持不变；任务只在自有工作区编辑，并在新工作区重放原命令。每个变体的回答、计费、测试和补丁保留，实验结果标为native-experiment，不能混进单／多模式收益训练，也不创建实时质量信号。

同候选使用跨进程锁。候选内容／运行基线／模型配置／实现／原源码／实验计划变动会拒绝入库；异常及中断保留局部目录和progress，不生成完整实验凭据。目前不自动续跑父实验；可以保留原轮并显式新开一轮。完整凭据注册到私有coding_rollouts表，调用方上传的“passed”或成功率不能注册成执行证据。

离线编码门禁重新读取数据库注册的原始计划、子报告、上下文／回答凭据和补丁，核对实际执行版本、预算、变体、输入及候选摘要；拒绝被修改的文件、旧执行器、跨模型／预算混合和同任务冲突输入。重复任务按task_group等权聚合，任何未知usage／不完整回答／预算超限／基础设施问题导致整组门禁失败，不悄悄剔除坏的一端。

放行需至少30个独立任务簇、全部成对证据可用、候选成功率至少0.8且不低于基线、成本收益差异置信下界不低于-0.02。收益沿用固定成功率/token/墙钟/调用数权重；1000次任务簇bootstrap，对相同策略基线下不同候选payload进行Bonferroni校正。冻结时的候选家族规模保留；新增候选后重新核验可进一步收紧置信下界，不改写原报告。任务摘要不证明语义独立性，改写目标、测试或路径仍需维护者审核。

SelfEvolutionManager的evaluate读取服务拥有的专门证据，通用frozen/core/retrieval回归仍全部必需；start_shadow、promote_canary、activate再次核验编码证据，缓存的gate.passed不能代替原始证据。离线编码回归通过也不提供实时shadow/canary支持，原来的真实运行样本、分层质量门禁和回滚条件继续生效。

## 入口

`POST /api/workspace/coding/strategy` 新增action=rollout与rollout_evidence。rollout需要run_id、cases数组、confirmed=true，可选limits/baseline_mode/repetitions。离线查看无需模型；执行需要当前配置的模型。

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/coding_strategy.py rollout --workspace clawos/output/coding-state --run-id 1 --case <frozen-cases-array.json> --url http://127.0.0.1:18933/v1 --model Qwen3.5-9B-Q4_K_M --execute
.\clawos\.venv\Scripts\python.exe clawos/scripts/coding_strategy.py rollout_evidence --workspace clawos/output/coding-state --run-id 1
```

CLI只接受无凭据loopback HTTP模型端点，使用显式output内隔离数据库。权重、数据库、运行产物及旧注册表改动不提交。

## 验收记录

第一轮专门机制14项/251.188秒有1失败：重复检查调用了仅允许新目录的比较构造器。改为直接核对已加载源码见证后，14/14（196.479秒）通过。没有放宽篡改断言。补充家族校正后15/15（197.657秒）；最终加入实际并发拒绝／锁释放后重试、候选payload中途被替换测试，**17/17（247.122秒）**通过。

本轮真实实验使用上阶段JSON失败生成的静态白名单格式候选。计划包含两个自有小型任务：一个复用先前FAILED的finite-numbers回归任务，一个新增record-projection维护者夹具。每个任务公开4个方法及后置5个方法，后者是维护者测试，不是外部盲测。它们只能贡献两个task_group，不是30个独立任务，也不证明大仓库成功率或CC/Codex同等能力。

真实Qwen3.5-9B、同一工厂及默认每变体24调用/50,000计费token/1800秒、请求／命令300秒、输出1800token、3次编辑尝试；AB/BA冻结顺序。全部结果保留：

| 任务 | 变体 | 调用 | 计费token | 总耗时秒 | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| finite-numbers（旧负例） | baseline | 2 | 2703 | 90.406 | FAILED：格式修复后仍非法JSON |
| finite-numbers（旧负例） | candidate | 2 | 2868 | 102.813 | FAILED：静态格式候选仍未解决非法JSON |
| record-projection（新维护者夹具） | candidate | 3 | 5278 | 217.156 | FAILED：进入实际编辑／测试但未通过 |
| record-projection（新维护者夹具） | baseline | 3 | 5437 | 130.906 | FAILED：保留测试尝试，最终仍有格式失败 |

10次真实调用、16,286计费token、4变体合计541.281秒。完整回答、usage、预算及16个选择性见证均核验通过；任务成功率baseline=0/2、candidate=0/2，平均候选收益差-0.001376236，置信下界-0.002077833。原源码没有应用业务补丁。真正独立任务簇仅2且成功率为0，因此门禁FAILED；不能把置信下界单项大于-0.02说成评估通过。实际执行为single串行实验，不是新的多工作者并行／冲突／故障恢复验收，相关机制由真实Git命令加确定性模型夹具验证。

父报告output/cr/376a778358/report.json，文件SHA256 **0aac6a6093fc64613230599b3a889e90bfca596958f525dab38818b5d9144b9c**；CLI、源快照、16个见证、审计和进程拥有权记录在output/cr6-20261008。独立审计两次读取相同凭据，验证1完整实验、5报告包（旧imported1、新native-experiment4）、4变体、6张去重反思卡、运行策略0、晋升质量信号0。旧imported仅用于格式候选提名，未进入实验统计或晋升支持。

另外实际执行通用Frozen（30场景）、Core（4场景）、Retrieval（5场景）、配置物化（1场景）的基线／候选对照，全都通过。**这30个Frozen场景不是30个真实编码任务**。SelfEvolutionManager仍因专门coding_execution门禁不满足而将候选#1标为rejected；再次start_shadow被拒绝，没有自动发布。完成的是“真实失败提名→实际候选执行→证据复核→拒绝无效候选”链路，未证明候选改善了代码能力。

本轮首个自有18933/PID41940按exe与UTC启动时刻07:52:13.2039310Z精确核对，08:04:14.0451181Z已退出；生产与原预览不动。首轮6个变更Python编译通过，执行期间指纹不变；bundle **b4abd0de4186270b222c8a411e922475b21d39dae84716c96b5383cc0e5656c3**。

首次隔离全量930项/1747.670秒，**ERROR=1**：旧test_active_owner_cannot_be_replaced在TemporaryDirectory清理时WinError32，另一个工作者的原生Git/文件线程仍持有repo。取消asyncio.to_thread不会停止底层线程，协调者可能先释放锁。修复ReliableCollaborationService的全部自有原生操作：shield并排空线程才传播取消，执行DAG也排空后才离开协调者锁；连续取消只向执行任务转发一次，保持原生收尾及取消语义。新增阻塞真实clone并连续两次取消的测试，收尾未完成时重接管仍被拒绝，没有忽略清理错误或放宽所有权断言。

该修复改变选择性执行器见证；首轮真实实验保留为历史，并验证当前执行器拒绝其旧凭据。修复后多代理针对性28/28（276.531秒）通过，含原所有权测试和新增连续取消测试。取消需等待原生操作收尾，可能超出协程软墙钟；原生命令自身超时仍生效，这不是强制停止线程的OS隔离。

修复后新隔离state复用同一冻结格式候选与旧finite-numbers任务做新baseline/candidate轮，不把两轮相加成新的独立任务。baseline2调用/2703token/86.235秒、candidate2/2868/80.750秒均格式FAILED；共4真实调用/5571token/166.985秒、独立task_group=1、成功率均0/1、所有pair可用。当前版本复核两次一致，16见证稳定，通用基线／候选回归再次通过，专门门禁仍FAILED并自动rejected，无运行策略或新增晋升质量信号。父报告output/cr/b27fabc914/report.json的SHA256 **73f9df6c62265c2000fc5a7489503d42a32d62a983b749a29d99e7d1aaf4e93b**；审计output/cr6d-20261008/audit.json。自有18933/PID71992启动08:40:28.0867756Z，经exe与精确UTC ticks核对08:46:43.2505230Z退出。

最终8源码编译通过，bundle **295e691bec5c4d998647ec893e7a0af53724d2e08c4cd75e6cc3e83f98e07928**，manifest在output/cr6d-20261008/final-source.json。最终隔离全量 **931/931（1654.448秒）通过**，workspace=output/regression/54f6c78147c84622a6cf3565d8f90daf，log=output/rollout-full-post-drain-20261008.log；最终指纹未变。旧swig弃用、openpyxl表头及asyncio慢回调警告未阻断；首轮930项失败记录保留，不改写成通过。日常数据库复核SHA256仍8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543。按已有授权提交指定origin/codex/coding-agent-competitive-p0-p2，仅8源码/测试及4说明文档；排除tools/权重/凭据/DB/output与原skill_registry.jsonl，不强推或合并master。

## 边界

离线实验不等于真实用户运行质量，不能自动发布。源码见证是选择性的已加载源码摘要，非整个模型、依赖或执行环境证明；数据库注册来源信任本机应用所有者，不是第三方加密来源证明。当前不增加图形工作台、第二模型、外部独立任务语料、语义独立性识别、严格OS文件／socket边界或多天负载验收；历史48小时文档负载FAILED保持原结论。
