# ClawOS 与 MTClaw 真实集成说明

## 集成目标

ClawOS 不修改 MTClaw 源码，而是使用 MTClaw 官方提供的 OpenAI-compatible
Function Router Provider 契约进行集成。

```text
ClawOS Web / API
  -> MemoryOS 上下文构建
  -> MTClawAdapter
  -> MTClaw /v1/chat/completions
  -> MTClaw Function Router
  -> ClawOS safe tool wrapper
  -> MTClaw /v1/tool_history
  -> ClawOS mtclaw_traces
  -> Reflection / 前端 Trace
```

这满足“基于 MTClaw 开源 AI 智能体框架进行创意开发”的要求：

- 任务路由真实经过 MTClaw Function Router。
- 工具定义由 MTClaw 加载。
- 工具执行遵循 MTClaw stdin JSON、stdout JSON、exit code 契约。
- 会话通过 `x-openclaw-session-id` 隔离。
- ClawOS 使用 MTClaw Tool History 作为运行证据。
- ClawOS 的 MemoryOS、Reflection 和工作台作为 MTClaw 之上的智能增强层。

## 代码证据

| 证据 | 文件 |
|---|---|
| MTClaw Provider Adapter | `mtclaw/adapter.py` |
| MTClaw 到 ClawOS 工具桥 | `mtclaw/bridge_runner.py` |
| 安全运行目录生成 | `mtclaw/prepare_runtime.py` |
| MTT Linux 一键启动 | `scripts/start_mtclaw_stack.sh` |
| Trace 数据表与 API | `memoryos/memory_store.py`, `/api/mtclaw/traces` |
| 真实 MTClaw API 契约测试 | `tests/test_mtclaw_adapter.py` |

## 低风险策略

比赛版 MTClaw 暴露 24 个只读或低风险工具：

- 时间、计算、文本统计
- 文件列表、读取、搜索、元数据
- 代码统计、TODO 扫描、目录树
- MemoryOS 只读查询
- Reflection、Skill、工具列表查询
- 本地知识库检索
- 会议纪要结构化提取（禁止输出文件）
- 论文精读与练习生成（禁止输出文件）
- 科研 PDF 的搜索、引用校验、对比矩阵只读动作
- 学习目标的查询、图谱和掌握度评估只读动作

垂直工具同时经过三层约束：生成给 MTClaw 的 JSON Schema 删除写参数、`action` 枚举缩减为只读动作、bridge 执行前再次拒绝越权参数。ClawOS 自身的场景路由还会根据 research/learning/office/project/web/general 策略缩减模型可见工具；模型即使返回策略外工具也会被拒绝。

以下能力不通过 MTClaw 自动执行：

- `shell_exec`
- `file_write`
- `skill_delete`
- 批量重命名和文件整理
- 项目创建及其他写操作

这些工具继续使用 ClawOS 原有确认机制，避免误操作。

## 比赛严格配置

`config.competition.json` 是本地 Qwen 比赛配置：

- MTClaw 默认启用。
- `fallback_on_error=false`，成功请求可以证明经过 MTClaw。
- 不配置云模型 fallback。
- 默认启用本地 embedding 和 reranker 配置位。
- `stream=true` 也先经过 MTClaw，再由 ClawOS 转换为 SSE，不再绕过 Function Router。

启动：

```bash
bash scripts/start_competition_stack.sh
```

离线架构验收：

```bash
python scripts/run_mtclaw_vertical_acceptance.py
python scripts/validate_competition_architecture.py
```

## 启动

目标环境为 MTT AIBOOK Linux。

```bash
cd clawos
export MODEL_API_KEY="your-key"
bash scripts/start_mtclaw_stack.sh
```

端口：

- MTClaw Function Router：`127.0.0.1:18791`
- ClawOS 工作台：`0.0.0.0:18790`

启动脚本会：

1. 从 ClawOS `functions.jsonl` 筛选安全工具。
2. 生成 MTClaw `config.json`、`functions.jsonl` 和 wrapper。
3. 启动 MTClaw Function Router。
4. 完成 MTClaw 健康检查。
5. 设置 `MTCLAW_ENABLED=true` 并启动 ClawOS。

## Trace 验证

发送请求：

```bash
curl -s http://127.0.0.1:18790/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"session_id":"demo-001","stream":false,"messages":[{"role":"user","content":"现在几点"}]}'
```

响应中应包含：

```json
{
  "clawos": {
    "mtclaw": {
      "used": true,
      "trace": []
    }
  }
}
```

查询持久化证据：

```bash
curl -s "http://127.0.0.1:18790/api/mtclaw/traces?session_id=demo-001"
curl -s "http://127.0.0.1:18791/v1/tool_history?limit=10"
```

验证点：

- 两侧 session id 一致。
- Trace 中包含 `function_name`、`tool_input` 和 `tool_result`。
- ClawOS 数据库存在 `route_status=success` 的 MTClaw Trace。

## 降级行为

若 MTClaw 未启动或请求失败：

- `fallback_on_error=true`：自动回到现有 ClawOS 路由，保证 Demo 可继续。
- `fallback_on_error=false`：返回 503，用于严格验收 MTClaw 必经链路。

比赛正式验收建议设置 `fallback_on_error=false`，确保任何成功请求都能证明经过
MTClaw；现场演示可设置为 `true`，降低环境意外导致的失败风险。

## 自动化证据

`tests/test_mtclaw_adapter.py` 直接加载仓库内 MTClaw FastAPI 应用，验证：

1. Adapter 调用真实 MTClaw `/v1/chat/completions` 路由。
2. `x-openclaw-session-id` 被 MTClaw 识别。
3. `/v1/tool_history` 返回对应会话工具证据。
4. ClawOS 主聊天接口实际选择 MTClaw Adapter。
5. Trace 被持久化到 ClawOS 数据库。
6. 生成运行目录只包含安全工具。

`tests/test_competition_architecture.py` 进一步验证：

1. 场景策略实际缩减模型工具面。
2. 垂直工具写参数和变更动作被 bridge 拒绝。
3. 生成的 MTClaw schema 遵循最小权限。
4. 流式请求仍经过 MTClaw。
5. 五条垂直路由合同全部闭环。

## 本地双服务验收结果

2026-06-13 已完成不依赖外网的双服务真进程验收：

- 启动真实 MTClaw Function Router 进程，加载 18 个 ClawOS 安全工具及 5 个 builtin。
- 启动真实 ClawOS 进程，并设置 `MTCLAW_ENABLED=true`。
- 请求“现在几点”从 ClawOS 进入 MTClaw。
- MTClaw 实际执行 `time_now.sh` wrapper。
- 响应包含 `clawos.mtclaw.used=true`。
- MTClaw `/v1/tool_history` 返回 1 条对应 session 记录。
- ClawOS `/api/mtclaw/traces` 返回 1 条持久化证据。
- 健康检查显示 MTClaw `reachable=true`、`tools_loaded=21`。

尚待完成的唯一环境证据是：在 MTT AIBOOK 上使用本地 Qwen/vLLM-MUSA 重复同一
验收，并记录模型延迟、工具命中率和资源占用。
