# 冻结基准、任务可靠性与 Skill Review 实现说明

日期：2026-06-16

## 已实现

### 冻结场景基准

- 新增 `scenario_benchmarks.py`。
- 默认套件 `competition-frozen-v1` 覆盖会议、学习、模板、技能、记忆五类低风险场景。
- 每次运行持久化：
  - case result
  - pass rate
  - P95 latency
  - thresholds
  - scenario list
- API：
  - `GET /api/benchmarks/scenarios/suites`
  - `POST /api/benchmarks/scenarios/suites`
  - `GET /api/benchmarks/scenarios/runs`
  - `POST /api/benchmarks/scenarios/run`

### 任务取消、重试、恢复、幂等

- `tasks` 新增：
  - `idempotency_key`
  - `retry_of`
  - `attempt`
  - `cancellation_requested`
  - `resume_state`
- Chat completion 支持：
  - `clawos_idempotency_key`
  - `Idempotency-Key` header
  - 已完成幂等任务可直接返回已保存响应。
- 工具执行前会检查取消标记。
- 启动时自动把未完成任务恢复为 `interrupted` 或 `canceled`。
- API：
  - `POST /api/tasks/{id}/cancel`
  - `POST /api/tasks/{id}/retry`
  - `POST /api/tasks/recover`
  - `GET /api/tasks/events`
  - `GET /api/tasks/stream`

### Skill Review Inbox

- `skill_review_events` 记录 reviewer、action、notes。
- Review Inbox 聚合候选版本、最近评测与最近审核事件。
- 支持 `needs_changes`、`reject`、`reopen`。
- 已验证版本仍通过原 `promote` API 发布。
- API：
  - `GET /api/skills/evolution/review-inbox`
  - `POST /api/skills/evolution/versions/{id}/review`

### 前端控制台

- 运行轨迹页新增：
  - 实时事件状态
  - 取消任务
  - 重试任务
  - 恢复中断任务
- 技能页新增 Skill Review Inbox。
- 新增冻结基准页，可运行默认冻结套件并查看历史结果。

## 验证

```powershell
python -m unittest discover -s clawos\tests
python -m py_compile clawos\memoryos\memory_store.py clawos\clawos_server.py clawos\scenario_benchmarks.py clawos\skills\skill_evolution.py
git diff --check
```

结果：`76 tests OK`。仅有既有 MTClaw FastAPI `on_event` deprecation warning。

JS 语法使用 Node REPL `vm.Script` 检查通过；本机 PowerShell PATH 中没有 `node` 命令。

## 仍未达到 100% 的部分

- 取消无法强杀已经进入外部系统调用的子进程，只能在工具执行前和任务边界生效。
- 重试当前创建 `pending_retry` 任务并保留 replay metadata，尚未自动重新进入完整 chat loop。
- 冻结基准是确定性低风险套件，真实 DeepSeek/本地模型质量基准仍需离线实机补充。
- SSE 为轻量轮询式事件流，生产级还需要任务队列、租户隔离和断线补偿。
