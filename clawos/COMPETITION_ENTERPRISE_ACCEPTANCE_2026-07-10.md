# ClawOS 比赛架构与企业标准验收（2026-07-10）

## 验收结论

| 口径 | 分数 | 结论 |
|---|---:|---|
| MTClaw 比赛架构门禁 | **95/100** | 通过比赛架构冻结线；缺原始上游 GitHub URL/SHA。 |
| 当前比赛综合就绪度 | **80/100** | 软件主链闭环，可进入演示冻结和实机前准备。 |
| 企业生产发布就绪度 | **66/100** | 不通过；仍缺实机、真实质量、身份隔离、资源治理等外部/生产证据。 |

本轮将第一阶段评估中的综合成熟度从 72 提升到 80。提升来自真实执行路由、垂直 MTClaw 安全面、流式闭环、严格比赛配置、来源指纹和新增验收门禁，不来自 UI 数量或 mock 分数堆叠。

## 已闭环

1. 场景路由从展示 API 升级为执行策略，按 research/learning/office/project/web/general 限制模型可见工具。
2. 策略外工具即使被模型返回，也会在执行前得到 `denied`。
3. MTClaw 安全工具从 18 个扩展到 24 个，新增 6 个垂直入口：知识检索、会议提取、论文精读、练习生成、科研只读动作、学习只读动作。
4. 垂直入口使用 schema 缩减、action allowlist、bridge 二次校验三层最小权限。
5. `stream=true` 不再绕过 MTClaw；MTClaw 完成后由 ClawOS 输出 SSE。
6. `config.competition.json` 要求 MTClaw 必经、关闭 fallback、关闭云模型 fallback，默认本地 Qwen/embedding/reranker。
7. 五条垂直路由合同覆盖会议、论文证据、论文精读、学习掌握度和 Coding 检查。
8. 57 个 function 与 57 个 handler 完全一致。
9. MTClaw 源码增加本地导入提交、修复提交、MIT License 和文件 SHA256 指纹记录。

## 企业标准门禁结果

| 门禁 | 状态 | 证据/缺口 |
|---|---|---|
| 第三方许可证 | 通过 | Vendored MTClaw 保留 MIT License。 |
| 第三方精确来源 | 未通过 | 原始 clone 的 GitHub URL 和 upstream commit SHA 未随 `.git` 保留，需项目所有者补录。 |
| Function 契约完整性 | 通过 | 57/57 声明与 handler 对齐。 |
| 垂直 MTClaw 接入 | 通过 | 6/6 计划垂直入口进入安全面。 |
| 最小权限 | 通过 | 写参数删除、只读 action 枚举、运行前拒绝均有测试。 |
| 场景执行隔离 | 通过 | 路由策略实际限制模型工具面并拒绝越权工具。 |
| 严格比赛配置 | 通过 | MTClaw 必经、fallback 关闭、云 fallback 为空。 |
| 流式链路一致性 | 通过 | 流式请求经过 MTClaw，并带 meta/trace 输出。 |
| 自动化回归 | 通过 | 229 tests OK。 |
| 冻结场景 | 通过 | 30/30，P95 500.27 ms。 |
| 垂直路由合同 | 通过 | 5/5，离线策略 P95 0.062 ms。该数字不是模型端到端耗时。 |
| 模型验收脚手架 | 通过 | mock 150/150；不代表真实模型质量。 |
| MTT 实机 | 未验收 | 无设备条件。 |
| 本地 Qwen 质量/性能 | 未验收 | 缺真实首 token、吞吐、内存/显存、工具命中率。 |
| 会议真实精度 | 未验收 | 缺真实音频 WER、行动项 precision/recall、owner/due-date 精度。 |
| 论文真实精度 | 未验收 | 缺 claim-to-citation 金标准和跨文档精度数据。 |
| 企业身份与隔离 | 未通过 | 缺真实身份源、租户隔离、SSO/RBAC 强制边界。 |
| 企业资源治理 | 未通过 | 缺容器/进程隔离、CPU/内存/超时配额、网络出口策略和负载报告。 |

## 当前最强比赛叙事

ClawOS 不是把 MTClaw 当作装饰依赖，而是使用 MTClaw 承担低风险高频 Function Router 快速路径；ClawOS 在上层提供场景编排、任务恢复、MemoryOS、知识证据、Reflection 和 Skill 治理。复杂或写操作继续进入 ClawOS 的确认、审计和恢复链路。

```text
用户请求
  -> 强制场景路由与工具面缩减
  -> MTClaw Function Router（低风险快速路径）
  -> ClawOS 安全工具/垂直只读动作
  -> Tool History + ClawOS Trace
  -> MemoryOS / 知识证据 / Reflection / Skill Gate
```

## 提交后最高优先级

1. 由项目所有者补录 MTClaw 原始 GitHub URL 与 upstream commit SHA。
2. 在 MTT AIBOOK 上运行严格比赛配置，保存健康检查、trace、P50/P95、首 token、吞吐和资源峰值。
3. 使用同一任务集比较无 MTClaw、MTClaw permissive、MTClaw strict 的 Pass@1、路由 precision/recall、P95 和 token 消耗。
4. 建立会议与论文小型人工金标准，补真实精度报告。
5. 现场演示只承诺已经过证据门禁的能力；未验收项明确标注“待实机/待真实数据”。
