# 项目接手上下文

当前在 `master` 上维护。仓库整理基于 `05bfe2a`，原 `clawos/skills/skill_registry.jsonl` 本机改动须保留。用户已授权普通提交推送，禁止强推。提交不包含tools、权重、凭据、数据库或运行产物。

现行入口为 [README](README.md) 和 [文档导航](docs/README.md)。MT路由在 `clawos/mtclaw/router`，可视化领域实现和worker在 `clawos/visualization`，React源码在 `clawos/web`。共用ClawOS产品入口，保留隔离进程与数据边界。核心服务和MemoryStore仍需按领域拆分，见[维护性评估](docs/MAINTAINABILITY.md)。

[本轮归并验收](clawos/benchmarks/REPOSITORY_CONSOLIDATION_ACCEPTANCE.md)记录首轮失败、复验及实际进程结果。历史证据以对应版本为准。教学可视化是主线，沿用墨蓝/暖白风格；学习自述不等于掌握，也不计为Agent策略收益。

## 尚未验收

- 275个历史资料或产物缺少可核验原件，用户不确定备份是否存在；不能按同名候选重新绑定。
- 用户关机中断48小时协作测试并要求先不重测；旧ReadError与重连停滞保留独立失败记录，不拼接时长。
- 暂无可故障注入的独立Windows测试机或VM；系统重启、物理磁盘、当前桌面安装包签名与干净机器仍未验收。
- 真实模型论文综合、独立评审、教师校准和实际学习效果，以及多设备、屏幕阅读器和长期多人负载需独立验证。
- 此次未验证飞书真实租户审批与外发；本机配置和凭据未更改。
