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
