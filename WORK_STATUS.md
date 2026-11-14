# 当前工作状态

本轮已归并MT路由与Vision，淘汰独立上游安装脚本、重复说明和旧安装包；开发与桌面打包统一读取ClawOS源码树。原始参考资料、第三方许可、历史测试证据和用户数据保留。

- [仓库整理验收](clawos/benchmarks/REPOSITORY_CONSOLIDATION_ACCEPTANCE.md)：核心1306项首轮及修复复验、前端116项、可视化138项、真实网关13项、研究教学52项和桌面载荷预检。
- [当前文档](docs/README.md)统一说明入口；[接手上下文](PROJECT_CONTEXT.md)记录未完成的真实验收。
- 主服务、存储、控制台、可视化、工作区和学习策略已完成领域拆分。交付证据和 22 项能力评分见[全局评估](docs/PROJECT_ASSESSMENT.md)。现行职责和剩余集中点见[维护性说明](docs/MAINTAINABILITY.md)。
- 教学 P0 示范课已实现。短课支持固定论文导读、单变量检索、前后测、迁移题与教师复核导出。流程已过独立运行验证，真人教师校准和学生试学待开展。 [试学方案](docs/RAG_INTRO_PILOT.md) [验收](clawos/benchmarks/RAG_INTRO_ACCEPTANCE.md)
- 编码 P1 已完成三道历史缺陷的本地 Qwen 严格沙箱实跑。修复 Windows 换行后复测单代理 0/3、多代理 1/3。两次评审截断使整轮不可比较。跨仓库策略收益待验收。 [P1 验收](clawos/benchmarks/CODING_P1_ACCEPTANCE.md)
- DeepSeek 编码治理复测单代理 2/3、多代理 3/3。三项多代理评审均一次完成。应用本地校验结构和语法，测试在严格沙箱重放，引文单代理的语义遗漏被独立复验拒绝。公开题结果仅用于诊断，私有留出与真实冲突恢复仍待验收。 [实跑证据](clawos/benchmarks/CODING_P1_ACCEPTANCE.md#deepseek-实跑与编码治理)
- 跨仓库编码 P0 已封存 8 道私有模块任务并完成 16 个真实 DeepSeek 变体。单、多代理各交付 5/8，一次截断使整轮未达到严格可比条件，余下七对分别通过 5/7 和 4/7。 [跨仓库验收](clawos/benchmarks/CODING_CROSSREPO_ACCEPTANCE.md)
- 编码协作 P1 已修同文件多处补丁与失败断言定位。固定分工的两次 DeepSeek 演练均验证了进程中断恢复和真实 Git 冲突合并，定向回归 60/60。动态规划下的跨仓库恢复待验证。 [P1 验收](clawos/benchmarks/CODING_CROSSREPO_ACCEPTANCE.md#2026-11-11-补丁诊断与恢复)
- 编码策略 P2 已接入可选单代理优先路由。两条 DeepSeek 路径已实跑，覆盖单代理成功和失败后按剩余预算升级。历史缩进题的复核确认了补丁的空白行缺陷，并修复了完整评审拒绝因理由超长而丢失的问题。 [P2 验收](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#p2-单代理优先)
- 编码评审可在严格沙箱重放契约反例、独立推导预期值、修补和复审。历史缩进题的受控重放通过原公开与独立留出测试。修复了公开评测暴露的共享运行时 ACL 竞争。SWE-bench Pro V2 与 Terminal-Bench 2.1 官方评分仍待验收。 [公开评测与反例验收](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#评审反例修复与公开题验收)
- Aider Polyglot Python 全部 34 道原题完成三轮评分，结果为 18/34、18/34、21/34。最新轮在延长时限后完成 64 次有回执调用，13 道未通过。 [评分方法与回执](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#评审反例修复与公开题验收)
- Windows 复测补上源码与依赖定位、推理截断恢复、结构化失败断言和沙箱阻塞归因。两次动态协作恢复通过，含一次真实同行冲突。13 道旧失败题重测 2 道通过、9 道失败、2 道阻塞，定向回归 55/55。 [Windows 复测](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#windows-代理链路复测)
- 修复反馈保留多行断言首差异，原题评分记录旧通过用例退化。五道同模型同预算配对中，起始代码重做 1/5，沿候选修补 0/5，默认仍用起始代码。 [配对结果](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#修复基线配对实验)
- 编码自主入口已接入固定测试基线、复现源码锚点和严格沙箱交付门禁。编码及 Aider 回归共 150/150，十题整仓预检 40/40。旧版真实模型第二轮补丁提议 1/10、工具循环 0/10。DeepSeek 持续返回 HTTP 402，交付版实时成绩待复测。 [整仓验收](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#真实仓库缺陷主入口比较)
- 工具循环支持批量取证与按限定函数名读取。两道曾耗尽八轮的历史题各用两次脚本动作完成离线复放，公开与留出检查 4/4，代理定向回归 39/39。 [取证验收](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#真实仓库缺陷主入口比较)
- 补丁提议与工具循环已接入精确锚点重试诊断。七份历史失败首答复查，六份定位到源码片段。重复锚点题的两条链路离线重试均通过，公开与留出检查 4/4。 [锚点验收](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#真实仓库缺陷主入口比较)
- DeepSeek 恢复后，原十题真实同预算复测完成。补丁提议 6/10，工具循环 2/10，68 次调用均有完整回执。工具循环八题停在下一请求预算准入，两份公开通过的提议补丁未通过留出。 [真实复测](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#2026-11-13-deepseek-恢复后复测)
- 编码工作记忆压缩工具历史并复用重复查找。原十题同预算复测，两条链路均 7/10，工具循环实际用量下降约 60%，预算准入退出从八题降至零。定向回归 41/41。 [工作记忆验收](clawos/benchmarks/CODING_STRATEGY_EVOLUTION_ACCEPTANCE.md#编码工具历史与工作记忆)
- 固定测试编码任务可跨会话续接。项目笔记支持维护与召回，严格测试证据按源码版本复用。主动暂停和进程中断两种跨进程验收通过，独立沙箱检查 4/4。 [使用说明](docs/CODING_CONTINUITY.md)
- 编码续接可预览事件和工作区差异，经确认从当前仓库重建基线并保留旧工作区。项目决策可关联检查点和理由。跨进程漂移恢复的严格沙箱检查 2/2，定向回归 45/45。 [使用说明](docs/CODING_CONTINUITY.md)
- 编码任务与项目记忆已接到桌面控制台的「任务与进度」。Chrome 验证直接续接和漂移重建，固定测试严格沙箱 2/2，定向回归 49/49。 [使用说明](docs/CODING_CONTINUITY.md)
