# ClawOS 反馈、Reward 校准与 Preference Ranker P0-P2

日期：2026-07-26

## 结论

本轮闭环的是“先获得可信反馈，再决定是否升级学习能力”，而不是提前宣称在线 RL：

```text
真实终态 Task
  -> 显式用户反馈
  -> 修订对应 Reward / Trajectory
  -> 数据质量与覆盖率门禁
  -> Reward Calibration Candidate
  -> Holdout Evaluation
  -> Shadow
  -> 人工确认激活
  -> Preference Ranker Candidate（样本达标后）
  -> Holdout Evaluation
  -> Shadow
  -> 人工确认激活
```

深度 Router、Trajectory RL 和行为 LoRA 本轮只提供基于已观测本地数据的 readiness
评估，不会自动训练、自动部署或修改基础模型权重。

## P0：真实反馈与 Reward 校准

- 聊天响应增加赞、踩和 1-5 分显式反馈入口；反馈必须绑定已进入终态的 Task。
- 反馈支持幂等键、来源、原因、纠正内容和元数据，数据库保留审计记录。
- 缺失反馈保持 `missing`，不再自动转换成 0.5 中性满意度。
- 新反馈会修订对应 Policy Reward 和 Trajectory Reward；安全违规仍固定为 `-1`。
- Reward 校准使用任务隔离的训练/留出切分和带符号约束的线性模型。
- 不可下调的训练门槛：

  - 完成轨迹不少于 50；
  - 显式反馈不少于 20；
  - 存在 Policy Arm 时，每个 Arm 暴露不少于 10。

- 候选必须在留出集上不劣于 baseline，且 MAE 不高于 0.35，才能进入 Shadow；
  激活必须显式传入 `confirmed=true`。

## P1：Preference Ranker

- 使用 chosen/rejected 偏好对训练用户条件化的 pairwise ranker。
- 输入覆盖任务上下文、用户上下文和候选 payload；输出只对提供的候选排序。
- 使用确定性哈希特征与 pairwise logistic objective，不增加重型微调依赖。
- 训练/留出按 Task 隔离，训练样本同时生成镜像样本，降低位置偏差。
- 不可下调的训练门槛：

  - 有效偏好对不少于 100；
  - learning、research、project、office 每类不少于 20；
  - 互相矛盾的偏好比例低于 15%。

- 候选留出集至少 20 对，准确率至少 55%，并且至少高于长度启发式 baseline
  2 个百分点，才能进入 Shadow；激活同样要求人工确认。

## P2：下一阶段 readiness

`GET /api/agent-learning/advanced-readiness` 只读取本地真实数据并返回逐项检查：

- 深度 Router：轨迹 500、偏好对 200、显式反馈 100、每个 Arm 暴露 50。
- Trajectory RL：轨迹 2000、决策 Step 10000、反馈覆盖率 60%、有效行为概率
  99%，且不存在冲突反馈 Task。
- 行为 LoRA：每个实际场景至少 500 条轨迹和 200 个偏好对。

报告固定包含 `online_rl_claimed: false`。门槛达到只表示“可以启动独立实验评审”，
不等于允许自动上线。

## API

- `POST /api/agent-learning/feedback`
- `GET /api/agent-learning/data-quality`
- `GET /api/agent-learning/reward-calibrations`
- `POST /api/agent-learning/reward-calibrations/train`
- `POST /api/agent-learning/reward-calibrations/{id}/evaluate`
- `POST /api/agent-learning/reward-calibrations/{id}/activate`
- `GET /api/agent-learning/preference-ranker/readiness`
- `GET /api/agent-learning/preference-ranker/models`
- `POST /api/agent-learning/preference-ranker/train`
- `POST /api/agent-learning/preference-ranker/models/{id}/evaluate`
- `POST /api/agent-learning/preference-ranker/models/{id}/activate`
- `POST /api/agent-learning/preference-ranker/rank`
- `GET /api/agent-learning/advanced-readiness`

## 当前边界

- 软件闭环和门禁已经完成，但仓库中的合成测试样本不代表真实用户分布。
- 当前没有目标硬件验收，不声明吞吐、延迟、功耗或多日稳定性结果。
- 当前没有在线策略梯度、PPO 或基础模型持续微调。
- Ranker 与校准模型只能在候选、留出评估、Shadow、人工确认激活的状态机中流转。
- 高风险工具权限、人工确认、Skill 签名与 Runtime Policy 仍是独立硬门禁。
