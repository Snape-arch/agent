# ClawOS Competition Readiness P0-P2

日期：2026-07-26

## 结论

本轮将分散的比赛架构、四场景演示、真实反馈学习、目标硬件证据和高级学习门禁
收敛为一个统一控制面：

```text
Versioned software contracts
  + observed feedback / preference data
  + frozen benchmark-backed demo flows
  + target hardware evidence
  -> P0 / P1 / P2 checks
  -> software_p0_p2_closed
  -> competition_release_ready
```

`software_p0_p2_closed=true` 只代表软件合同和门禁已实现，不等于目标硬件、
真实用户学习或比赛发布已经通过。

## P0：比赛低风险闭环

- 新增 `competition_demo_v1.json`，定义科研、学习、办公、项目四条黄金演示链。
- 每条演示链都绑定现有冻结基准用例；合同缺少对应 case 时 P0 直接失败。
- 聚合 MTClaw 比赛架构、显式反馈数据面和 Task-bound Reward 修订能力。
- 目标硬件证据不存在时明确保持 `competition_release_ready=false`。

## P1：数据与学习运营闭环

- 聚合真实轨迹、显式反馈覆盖、偏好对、场景覆盖和 Arm 暴露。
- 展示 Reward Calibration 与 Preference Ranker 的 Active / Shadow 状态。
- 数据未达门槛时只显示 collecting / blocked，不生成合成达标结果。
- 控制台 Self-Evolution 页面可以查看 P0-P2、四条演示链和下一步门槛。

Reward 校准门槛保持：

- 至少 50 条完成轨迹；
- 至少 20 条显式反馈；
- 存在 Policy Arm 时，每个 Arm 至少暴露 10 次。

Preference Ranker 门槛保持：

- 至少 100 个有效偏好对；
- learning、research、project、office 每类至少 20；
- 矛盾率低于 15%。

## P2：高级学习准入闭环

- 深度 Router、Trajectory RL 和行为 LoRA 继续使用已实现的逐项 readiness。
- 报告固定包含 `online_rl_claimed=false`。
- 数据门槛达到只允许启动独立实验评审，不会自动训练或自动上线。

## 目标硬件证据

模板：`HARDWARE_ACCEPTANCE_TEMPLATE.json`

模板默认不通过，必须在真实目标设备上填写：

- 设备和本地模型身份；
- 离线模式；
- MTClaw 必经且 fallback 关闭；
- 首 Token P95；
- Token 吞吐；
- 峰值内存；
- 不少于 30 条任务的通过率，且通过率至少 90%。

将真实报告保存为：

```text
output/competition_hardware_acceptance.json
```

控制面会计算证据摘要；模板或缺字段报告不能通过硬件门禁。

## 使用

API：

- `GET /api/competition/readiness`
- `POST /api/competition/hardware-evidence/validate`
- `POST /api/competition/readiness/export`

导出接口会写本地 JSON 与 Markdown，必须显式传入：

```json
{"confirmed": true}
```

命令行：

```powershell
python clawos\scripts\export_competition_readiness.py `
  --db clawos\memoryos.db `
  --hardware-report output\competition_hardware_acceptance.json `
  --out-dir output
```

正式发布检查可以增加 `--strict`。当真实硬件证据或其他发布门禁缺失时，
严格模式以非零状态退出。

目标硬件到位后的建议顺序：

1. 使用 `config.competition.json` 启动本地 Qwen、MTClaw 和 ClawOS。
2. 运行 `validate_competition_architecture.py`。
3. 运行 `run_mtclaw_vertical_acceptance.py`。
4. 运行冻结场景和真实模型验收。
5. 采集延迟、吞吐、资源及不少于 30 条任务结果。
6. 填写硬件证据文件并运行 readiness `--strict`。

## 证据边界

- 当前没有目标 MTT AIBOOK，不能声称目标设备已经验收。
- 当前真实反馈和偏好样本尚未达到训练门槛，不能声称个性化效果已经验证。
- 当前没有在线 PPO、在线策略梯度或基础模型持续微调。
- 硬件、真实数据与发布门禁不会被单元测试、模板或 mock 报告替代。
