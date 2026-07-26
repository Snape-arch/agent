# ClawOS 受控自进化 Skill

## Agent Learning P0-P2 扩展（2026-07-26）

现有 UCB 已扩展为 Hybrid Agent Skill Policy：任务决策自动记录为版本化轨迹，
由可持久化的轻量 Contextual-Q Router 学习 Agent/Skill/Tool/Workflow/Prompt
组合，并通过 UCB 保留冷启动探索。候选模型使用留出轨迹和 Doubly-Robust
Trajectory Critic 评估，通过后进入 Shadow；激活和回滚继续要求显式确认。

详细数据结构、训练门禁、API 和安全边界见 `AGENT_LEARNING_P0_P2.md`。

## 2026-07-26 P0-P2 闭环

本轮将“有状态机的治理原型”收口为真实运行闭环：

1. 自动基准不再根据候选字段启发式合成分数。`ExecutedEvolutionBenchmarkRunner`
   在隔离子进程运行文件化 frozen/core E2E 套件，并执行检索探针；证据包含
   baseline/candidate 报告摘要、配置摘要、逐套件 case count 和 runner 类型。
2. `prompt_policy`、`retrieval_params`、`tool_routing_policy` 已进入聊天执行链路。
   Task 保存目标、版本、run、baseline/candidate 暴露、稳定分桶和 Shadow 物化结果。
3. Shadow 物化候选 Prompt、检索参数和工具面但不影响用户结果；Canary 使用
   session/task 稳定哈希分桶，命中的任务真实使用候选策略。
4. Canary 任务完成后自动写入重试、取消和失败信号；越过红线立即停流。
   至少 3 个 Shadow 样本才可进入 Canary，至少 5 个 Canary 样本才可激活。
5. Contextual UCB 可进入真实场景路由；reward 从绑定的终态 Task 派生，
   晋升至少需要 5 个样本并按 95% 置信区间下界排序。
6. Reflection 可对近期重复失败做聚类并生成低风险候选，但仍只进入候选区，
   不自动发布。
7. Fresh-agent audit 改为 `python -I` 独立进程 plan 审计；检测 silent bypass。
8. Skill Canary 使用真实稳定分桶；高风险工具禁止自动灰度。
9. Skill 晋升和 Canary 必须先签名。签名密钥来自 OS Keyring
   `ClawOS/skill-signing`，或本地环境变量 `CLAWOS_SKILL_SIGNING_KEY`；
   API 不再接受客户端提交签名 Secret。
10. 新增 Skill 库健康度、重复序列、零使用候选和保留证据的归档式压缩。

证据边界：隔离 benchmark 是当前仓库的确定性软件基准，不代表真实大模型质量、
MTT AIBOOK 性能或长期用户满意度。Canary 会真实选择候选策略，但正式发布继续要求
人工确认。

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

1. 在 MTT AIBOOK 上补本地模型真实 A/B、首 token、吞吐、资源峰值和多日 burn-in。
2. 将用户显式满意度反馈绑定到 Task，使在线 reward 不只依赖默认中性满意度。
3. 为 Shadow 增加可选的双模型执行预算；当前默认只物化候选配置，不重复调用模型。
4. 接入不可伪造的登录身份和发布角色；当前仍是本机单用户确认模型。
