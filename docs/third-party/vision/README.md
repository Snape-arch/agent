# 可视化模块来源

原始代码来自用户ClawVision工作树，基线 `65afd74a0fc170a32340a36594afd42207c1b5a9`，含当时较新的工作树源码。SOURCE_SNAPSHOT.json与SOURCE_SUPPLEMENT.json保留导入时原文件名及字节指纹，不随此次重排改写。

当前实现分布在 `clawos/visualization/` 与 `clawos/web/`，归并了前端、运行与测试入口；后端导入改为限定命名空间，原公开SDK名保留兼容。原始个人项目及其Git历史未修改。

原项目声明Apache-2.0，许可完整保留于 `clawos/visualization/LICENSE`。MT路由另遵循其MIT许可，不能据此推断整个ClawOS应用已经采用同一开源许可。

模型、凭据、数据库和node_modules不属于导入源码。较早验收结果位于 `clawos/benchmarks/vision-upstream/`，仅表示当时的记录，不是本轮重新测量值。
