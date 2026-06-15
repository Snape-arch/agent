# ClawOS 受控自进化 Skill

## 目标

把任务经验转化为可复用 Skill，同时避免模型直接修改生产工作流。进化对象是外部 Skill
定义，不是模型权重。

## 文献到实现

| 文献 | 可复用机制 | ClawOS 落点 |
|---|---|---|
| Generative Agents, 2023 | 记忆检索、反思、规划闭环 | MemoryOS + Reflection 证据作为候选来源 |
| Voyager, 2023 | 可组合技能库、执行错误、自验证 | 多步骤 Skill、隔离执行、逐例结果 |
| MemGPT, 2024 | 分层外部记忆、显式控制 | Skill 版本和评测证据持久化到 SQLite |
| SkillOS, 2026 | Executor/Curator 分离、下游效用、库紧凑性 | 生产执行与候选策展分离；冻结任务评测 |
| SkillEvolver, 2026 | 部署后反馈、fresh-agent audit、过拟合和 bypass 检查 | 当前已实现质量门禁；fresh-agent/bypass 为下一阶段 |

参考文件位于 `参考文献/`：

- `2304.03442v2.pdf`
- `2305.16291v2.pdf`
- `2310.08560v2.pdf`
- `2605.06614v1.pdf`
- `2605.10500v1.pdf`

## 生命周期

状态：

```text
candidate -> validated -> active -> archived
          \-> rejected
active -> rolled_back
```

规则：

1. `propose` 只创建候选版本，不修改当前注册表。
2. 评测套件创建后不可原地编辑，以保证基准冻结。
3. 候选可做 `plan` 检查或 `execute` 执行评测。
4. 评测记录逐例结果、通过率、P95 和阈值。
5. 只有 `validated` 版本可晋升。
6. 晋升保存旧生产定义；回滚恢复旧定义和版本。
7. Reflection、用户反馈或 Trace 只作为 `source_ref`，不能绕过评测门禁。

## API

- `POST /api/skills/evolution/candidates`
- `POST /api/skills/evolution/suites`
- `POST /api/skills/evolution/versions/{id}/evaluate`
- `POST /api/skills/evolution/versions/{id}/promote`
- `POST /api/skills/evolution/promotions/{id}/rollback`
- `GET /api/skills/evolution/versions`
- `GET /api/skills/evolution/runs`

## 后续增强

1. 用独立新会话执行 candidate 与 baseline A/B，防止作者上下文泄漏。
2. 检测候选是否实际被路由调用，避免 silent bypass。
3. 增加 baseline 对比、非劣门槛、成本和库复杂度惩罚。
4. 为 Skill 增加权限清单、依赖锁、签名和来源可信度。
5. 使用 canary 流量和自动回滚，但生产晋升继续保留人工授权。
