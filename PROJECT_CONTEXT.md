# 项目接手上下文

当前在 `master` 上维护。仓库整理基于 `05bfe2a`，原 `clawos/skills/skill_registry.jsonl` 本机改动须保留。用户已授权普通提交推送，禁止强推。提交不包含tools、权重、凭据、数据库或运行产物。

现行入口见 [README](README.md) 和 [文档导航](docs/README.md)。MT 路由在 `clawos/mtclaw/router`，可视化领域实现和 worker 在 `clawos/visualization`，React 源码在 `clawos/web`。共用 ClawOS 产品入口，保留隔离进程和数据边界。

[仓库归并验收](clawos/benchmarks/REPOSITORY_CONSOLIDATION_ACCEPTANCE.md)记录首轮失败、复验及实际进程结果。归并基线 `f065939` 的 [云端 CI](https://github.com/Snape-arch/agent/actions/runs/42335596143) 已全部通过。历史证据以对应版本为准。教学可视化是主线，沿用墨蓝与暖白风格。学习自述不计为掌握或Agent策略收益。

本轮从基线 `9620bc6` 完成领域 API、执行装配、12 个共享事务仓储、14 个控制台模块、私有可视化处理器以及工作区和学习策略拆分。保持 3,346 个路径与方法组合的匹配结果及 OpenAPI 模式，两处既有重复操作 ID 单独记录。运行证据读接口与摘要刷新分离，向量检索复核数据库工作区。 [可维护性说明](docs/MAINTAINABILITY.md)

最终核心回归 1,315/1,315，前端 116/116，可视化后端 138/138。真实教学旅程 52 项、私有网关 13 项及 Chrome 8 项通过。

工程评估为 8.3/10，22 个功能模块的综合能力为 7.9/10。测试、范围、评分和余下集中点见报告。基线 `9620bc6` 的云端 CI 已全部通过。 [全局评估](docs/PROJECT_ASSESSMENT.md) [基线 CI](https://github.com/Snape-arch/agent/actions/runs/42336808615)

## 尚未验收

- 275个历史资料或产物缺少可核验原件，用户不确定备份是否存在；不能按同名候选重新绑定。
- 用户关机中断48小时协作测试并要求先不重测；旧ReadError与重连停滞保留独立失败记录，不拼接时长。
- 暂无可故障注入的独立Windows测试机或VM；系统重启、物理磁盘、当前桌面安装包签名与干净机器仍未验收。
- 真实模型论文综合、独立评审、教师校准和实际学习效果，以及多设备、屏幕阅读器和长期多人负载需独立验证。
- 此次未验证飞书真实租户审批与外发；本机配置和凭据未更改。
