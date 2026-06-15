# MemoryOS 与 Reflection 治理闭环

更新日期：2026-06-15

## MemoryOS 2.0

写入链路：

```text
Memory Write
  -> Version Snapshot
  -> Evidence Link
  -> Conflict Detection
  -> Review Inbox (when conflict_policy=review)
  -> Approve / Reject
  -> Search Index Refresh
```

主要 API：

- `GET /api/memory/items/{id}/versions`
- `GET /api/memory/items/{id}/evidence`
- `GET /api/memory/reviews`
- `POST /api/memory/reviews/{id}/resolve`
- `GET|POST /api/memory/items/{id}/acl`
- `POST /api/memory/evaluations/run`

ACL 支持 user、role、workspace 和 read/write/review/admin 权限。当前 API
通过显式 `actor_id`、`roles`、`workspace_id` 接收调用者上下文；正式多用户交付前，
仍需接入不可伪造的登录身份、服务端会话和授权中间件。

## Reflection 2.0

每张完整反思卡保存：

- 任务、会话、触发器、结果和失败分类
- 根因、洞察、模式和完整工具轨迹
- 工具证据与用户反馈
- 独立改进项及其审计事件

改进状态机：

```text
proposed -> approved -> testing -> validated -> published -> rolled_back
     |          |           |            |
     +----------+-----------+------------+-> rejected
```

发布前必须提交 baseline/candidate 指标。当前回归门禁支持 success_rate、
quality_score、latency_ms 和 error_rate；发布与回滚在 SQLite 事务中同步修改策略和
审计事件。

主要 API：

- `GET /api/reflection/cards/{id}`
- `POST /api/reflection/cards/{id}/feedback`
- `GET /api/reflection/improvements`
- `POST /api/reflection/improvements/{id}/transition`
- `POST /api/reflection/improvements/{id}/validate`
- `POST /api/reflection/improvements/{id}/publish`
- `POST /api/reflection/improvements/{id}/rollback`

`runtime_policies` 当前是受控策略注册表。具体工具、Prompt 或路由模块必须显式接入
对应 `target_type/target_key` 后才会消费策略，系统不会把模型生成的建议直接执行。

## 验证

```powershell
python -m unittest discover -s clawos\tests
```

2026-06-15 验证结果：`50 tests OK`。
