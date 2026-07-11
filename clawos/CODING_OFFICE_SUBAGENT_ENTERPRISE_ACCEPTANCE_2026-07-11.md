# Coding、办公与自治 Subagent 阶段一验收

评估日期：2026-07-11

## 结论

本轮把 ClawOS 从“具备零散 coding/办公工具”推进为可审计的完整工作流：coding 覆盖检查、计划、受控修改、测试、修复重试、评审、checkpoint 与回滚；办公覆盖会议、邮件、日历及 DOCX/XLSX/PPTX/PDF/MD/TXT/JSON/CSV/EML/ICS 的创建、编辑、检查和质量门禁；自治 subagent 覆盖角色隔离、依赖 DAG、并发、预算、工具权限、checkpoint/resume、证据汇总和硬门禁仲裁。

阶段一综合评分为 **90/100**。这是仓库代码和离线验收成熟度，不代表 MTT AIBOOK 实机或真实邮件/日历租户验收已经通过。

## 产业级评分

| 维度 | 权重 | 得分 | 可复核证据 | 尚未通过的外部门禁 |
|---|---:|---:|---|---|
| Coding 完整循环 | 20 | 19 | 定向测试；确定性验收真实经历首轮失败、第二轮修复、测试与 checkpoint | 未在大型真实仓库做长时压力和故障注入 |
| 会议工作流 | 12 | 11 | 会议写操作确认、音频/转写边界、会议包及回归测试 | 真实 ASR、说话人分离和实机音频集 |
| 邮件与日历 | 12 | 10 | EML/ICS 标准制品、幂等发送接口、连接器确认门禁 | 真实 SMTP/企业日历租户与回执 |
| 多格式文件 | 16 | 15 | 10 类格式；六格式会议包重新打开质量门禁 | OCR 扫描 PDF、复杂版式和超大文件矩阵 |
| 自治 Subagent | 20 | 18 | 隔离上下文、DAG、并发预算、工具最小权限、checkpoint/resume、硬门禁优先仲裁 | 当前真实 Qwen 报告未通过硬门禁，需实机复验与提示优化 |
| MTClaw 真实集成 | 10 | 9 | 63/63 handler parity；9/9 垂直安全工具；7/7 路由合同 | 缺原始 upstream URL/SHA 身份证据 |
| 安全、审计与可恢复 | 10 | 8 | 写操作确认、路径限制、网络目标约束、幂等键、RunRecord、rollback | OS 级沙箱、真实 RBAC/SSO、集中可观测性 |
| **合计** | **100** | **90** | | |

## 闭环定义

### Coding

`inspect -> plan -> scoped patch -> tests -> review -> bounded repair -> checkpoint -> human review -> optional rollback`

- 不自动 commit/push；通过后生成可审查 diff 和 change request。
- 修改限定在仓库内、受支持源码类型和 checkpoint 文件集合。
- 测试命令使用 allowlist，阻断 shell 控制符和破坏性命令。
- 测试或评审失败时恢复原文件；通过后仍要求人工发布确认。

### 会议、邮件、日历和文件

`structured input -> confirmed local write -> create/edit -> reopen/inspect -> quality gate -> draft package -> confirmed connector dispatch -> audit record`

- 会议包可同时形成纪要、行动项表、邮件草稿和日历邀请。
- 外部发送与发布必须显式确认，并支持幂等键。
- 连接器目标执行 DNS/IP 安全检查，阻止 loopback、私网和非允许端口。
- 文件制品保存 SHA-256、大小、格式、检查结果和 RunRecord 证据。

### 自治 Subagent

`objective -> role contracts -> dependency DAG -> isolated context -> bounded model/tool loop -> checkpoints -> evidence arbitration -> human gate or pass -> resume`

- 每个角色拥有独立指令、允许工具、模型/工具次数、token 和超时预算。
- 依赖只传递公开结果和哈希证据，不共享隐式对话上下文。
- 安全、测试和证据硬门禁优先于投票或评审者意见。
- 副作用工具必须在运行级显式授权；未授权时进入 human gate。

## 验收证据

```powershell
python -m unittest discover -s tests
python scripts\run_mtclaw_vertical_acceptance.py
python scripts\validate_competition_architecture.py
python scripts\coding_office_subagent_acceptance.py --out benchmarks\coding_office_subagent_acceptance_deterministic_2026-07-11.json
```

- 全量测试：254 tests，全部通过。
- MTClaw 垂直合同：7/7，通过率 1.0，P95 0.056 ms（离线合同延迟，不是模型端到端延迟）。
- 比赛架构门禁：95/100，competition architecture ready=true，enterprise release ready=false。
- Coding/办公/Subagent 确定性验收：全部三项通过；办公包 6 个格式通过重新打开门禁；两角色均完成并形成 checkpoint。
- 已保留 2026-07-10 的真实 Qwen 失败报告：模型调用确实发生，但 subagent 硬门禁未通过，不计为实机成功。

## 阶段一边界与下一步

在以下证据完成前，不宣称企业生产就绪或实机验收通过：

1. 在目标 MTT AIBOOK 上跑同一全量、路由和 live-model 验收，记录 P50/P95、吞吐、内存/显存和 24 小时稳定性。
2. 使用真实会议音频集评估 ASR、说话人分离、行动项精度和人工修订率。
3. 在测试租户验证 SMTP/企业邮件和 CalDAV/ICS/企业日历的发送、幂等、回执、重试与撤销。
4. 对复杂 DOCX/PPTX/XLSX、OCR PDF、超大文件和中英文混排做视觉与内容金标评测。
5. 调整真实 Qwen subagent 输出契约后重跑 live-model 硬门禁，不得用确定性 fixture 替代模型质量证明。
6. 由项目方补充 MTClaw 原始 upstream URL 和 commit SHA。
