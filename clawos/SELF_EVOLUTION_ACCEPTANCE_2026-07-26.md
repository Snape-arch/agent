# ClawOS 自进化 P0-P2 闭环验收

日期：2026-07-26

## 结论

ClawOS 自进化已完成当前 Windows 本地单用户 MVP+ 范围内的 P0-P2 软件闭环：

```text
Task / Reflection / User feedback
  -> evidence-clustered low-risk candidate
  -> isolated executed benchmark
  -> Shadow materialization
  -> stable-bucket Canary
  -> task-bound quality signals
  -> confidence/sample gates
  -> confirmed activation
  -> automatic canary stop / explicit rollback
```

## P0

- 删除基于配置关键词合成质量、召回和延迟的自动验收路径。
- frozen/core E2E 通过隔离子进程实际执行；检索通过确定性检索 case 实际执行。
- benchmark evidence 必须包含执行类型、报告摘要和 case count。
- Prompt、检索参数和工具路由 Runtime Policy 已被聊天执行路径消费。
- 每个 Task 保存运行策略版本、run、候选暴露和 Shadow 物化证据。
- Canary Task 自动产生失败、取消和重试质量信号。

## P1

- Shadow 不影响用户结果，但实际物化候选 Prompt、检索参数和工具面。
- Canary 按 session/task 稳定哈希分桶，候选策略真实进入执行。
- 至少 3 个 Shadow 样本进入 Canary，至少 5 个 Canary 样本才允许激活。
- 失败、取消、重试率越过阈值会自动停止 Canary。
- Contextual UCB 已能接入 `routing:{scenario}` 组；选择绑定 Task。
- reward 由终态 Task 推导，调用方不能直接提交 success/latency。
- 策略晋升至少需要 5 个样本，使用 95% 置信区间下界排序。

## P2

- 重复失败 Reflection 可聚类为低风险候选，保留 failure category 与 pattern 证据。
- Fresh-agent audit 使用 `python -I` 独立进程，并检测 silent bypass。
- Skill Canary 使用真实稳定分桶；高风险工具不能进入自动 Canary。
- Skill Canary/晋升要求签名；密钥来自 OS Keyring 或本地环境变量。
- 新增重复 Skill、零使用 Skill、复杂度和历史版本健康检查。
- 库压缩只归档旧非活动版本，不删除评测、签名、审核和晋升证据。

## 安全边界

- 自进化不能修改代码、脚本、二进制或数据库迁移。
- 激活、策略晋升、Skill 晋升和实际库压缩均要求显式 `confirmed=true`。
- Shadow 默认不重复调用真实模型，避免费用和外部副作用。
- 真实模型质量、目标硬件性能、企业身份与多租户仍属于外部验收项。

## 验证

相关实现测试和全量测试结果以根目录 `PROJECT_CONTEXT.md` 最新记录为准。
