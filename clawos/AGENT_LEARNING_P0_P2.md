# ClawOS Agent Learning P0-P2

日期：2026-07-26

## 结论

ClawOS 已在不依赖目标硬件和大模型微调的前提下，完成 Agent Learning 软件闭环：

```text
Task / User / Environment
  -> versioned trajectory + decision steps
  -> task-bound multi-objective reward
  -> Agent Skill Policy candidate training
  -> offline Trajectory Critic
  -> Shadow gate
  -> explicit activation
  -> Hybrid Policy Network + UCB runtime selection
  -> outcome feedback
  -> explicit rollback
```

这不是在线 PPO，也不修改基础模型权重。学习对象是 Agent、Skill、Tool、Workflow、
Prompt 和检索参数的组合策略。

## P0：Agent Learning Data Plane

- 新增 `agent_trajectories` 与 `agent_trajectory_steps`，使用
  `clawos.trajectory.v1` 数据版本。
- Task 创建时自动建立轨迹；Policy 选择写入行为概率、状态、动作和模型版本；
  Task 终态自动写入结果、多维奖励和折扣回报。
- 奖励由成功、用户满意度、延迟、资源、重试和安全信号组成；安全违规是硬负例。
- 新增用户偏好对，保存 chosen/rejected、来源、置信度和关联轨迹。
- 数据集导出包含 manifest、计数和稳定摘要，并递归脱敏 Secret、Token、
  Authorization、Cookie 和密码字段。
- 中断恢复会关闭旧轨迹，并为重放任务建立新轨迹，避免跨尝试污染。

## P1：Agent Skill Policy Network v0

- 使用确定性哈希特征和分 Arm 线性 Contextual-Q Head，不新增重型训练依赖。
- 输入覆盖任务描述、场景、标签、会话历史统计、用户上下文、历史状态、
  环境/资源状态和候选 Arm 定义。
- Arm payload 可同时表达 Agent、Skill、Tool、Workflow、Prompt 和检索策略。
- 训练使用已完成、已绑定 Reward 的真实决策；固定留出切分记录训练/留出 MAE、
  各 Arm 样本数、训练数据摘要和模型版本。
- 运行时采用 Hybrid UCB：

```text
score = empirical reward + UCB uncertainty bonus + 0.35 * learned Q
```

- 未探索 Arm 仍由 UCB 优先冷启动；学习模型不能覆盖工具安全策略和人工确认。
- 学习到的 Prompt、检索参数与工具路由会被聊天运行时实际消费；Agent、
  Workflow 和 Skills 选择进入可审计决策记录。

## P2：Trajectory Critic

- 候选模型使用留出轨迹进行离线 Doubly-Robust 估计。
- 报告 baseline mean、candidate estimate、lift、标准误、95% 下界、
  effective sample size、安全违规数和决策摘要。
- 门禁同时要求最小样本、非回归、安全违规为零和置信下界不过度退化。
- 通过后只进入 `shadow`；生产激活要求显式 `confirmed=true`。
- 激活模型通过 UCB 安全混合参与真实选择；结果继续回流轨迹数据面。
- 回滚要求显式确认；旧 Active 模型保留为 Retired，可恢复到上一版本。

## API

- `GET /api/agent-learning/trajectories`
- `GET /api/agent-learning/trajectories/{id}`
- `GET /api/agent-learning/dataset`
- `POST /api/agent-learning/preferences`
- `GET /api/agent-learning/models`
- `POST /api/agent-learning/models/train`
- `POST /api/agent-learning/models/{id}/evaluate`
- `POST /api/agent-learning/models/{id}/activate`
- `POST /api/agent-learning/models/{id}/rollback`

## 安全和证据边界

- Policy Network 只在预注册 Arm 中排序，不能生成或绕过新权限。
- 高风险工具确认、路径/命令策略、Runtime Policy 与 Skill 签名仍是独立硬门禁。
- 训练、评估和激活均持久化版本与数据摘要；激活和回滚必须人工确认。
- 当前线性 Router 是可解释的 v0，不代表已完成深度 Agentic RL。
- 当前离线评估证明软件学习链路成立，不代表 MTT AIBOOK 性能或真实模型质量。
- Trajectory RL、Preference Model 与 LoRA 应在真实轨迹数量和质量达到门槛后进行。

## 后续闭环

显式反馈、Reward 校准、Preference Ranker 和高级学习 readiness 已在下一阶段完成，
详见 `FEEDBACK_PREFERENCE_P0_P2.md`。该阶段仍不宣称在线 RL。
