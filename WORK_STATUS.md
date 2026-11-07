# 当前工作状态

本轮已归并MT路由与Vision，淘汰独立上游安装脚本、重复说明和旧安装包；开发与桌面打包统一读取ClawOS源码树。原始参考资料、第三方许可、历史测试证据和用户数据保留。

- [仓库整理验收](clawos/benchmarks/REPOSITORY_CONSOLIDATION_ACCEPTANCE.md)：核心1306项首轮及修复复验、前端116项、可视化138项、真实网关13项、研究教学52项和桌面载荷预检。
- [当前文档](docs/README.md)统一说明入口；[接手上下文](PROJECT_CONTEXT.md)记录未完成的真实验收。
- 代码维护下一步：[路线图](docs/ROADMAP.md)先抽取主服务中边界清晰的只读API，再拆持久化和前端状态；每次保持接口和数据契约。
