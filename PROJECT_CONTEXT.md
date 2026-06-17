# Project Context

这个文件是 ClawOS 项目的协作交接记录。下一位 Codex 或协作者应先读这里，再按需读具体代码，避免每次重新扫描整个仓库。

## 维护规则

- 每次完成一个有意义的开发块，都在“最近完成”中追加记录。
- 如果项目状态、风险、评分或下一步变化，直接更新对应章节。
- 不记录 API Key、token、密码、私有密钥或 `.env` 内容。
- 测试命令和结果只写必要摘要，不贴长日志。

## 当前状态

- 当前分支：`codex/fix-routing-memory-ui`
- 远程仓库：`https://github.com/Snape-arch/agent.git`
- 最近本地提交：`232e402 修复MTclaw`
- 当前成熟度估计：`72/100`
- 定位：Windows 本地可演示竞赛原型，正在推进到准企业级 Agent 工作台。
- Windows 双服务入口：根目录 `start_clawos.bat`

## 项目结构

- 主服务：`clawos/clawos_server.py`
- 前端：`clawos/static/`
- 模型 provider：`clawos/providers/`
- MTClaw adapter/runtime：`clawos/mtclaw/`
- 记忆系统：`clawos/memoryos/`
- Reflection：`clawos/reflection/`
- 工具执行：`clawos/scripts/tool_runner.py`
- 测试：`clawos/tests/`
- 协作 skills：`.agents/skills/`

## 已完成能力

- DeepSeek / OpenAI-compatible / mock provider 抽象。
- `/health` 暴露 provider/model/configured 状态，不暴露 API Key。
- MTClaw 双服务真实链路：ClawOS -> MTClaw `/v1/chat/completions` -> Tool History -> ClawOS trace。
- Windows 下 MTClaw 可执行 `.cmd` 工具包装脚本，避免依赖未配置 WSL bash。
- MemoryOS 五类记忆、检索、Review、ACL、评测基础。
- Reflection 卡片、反馈、状态机、回归验证和回滚基础。
- Task / Step / Event 持久化运行时 MVP。
- 前端已有产品页、控制台、Memory、Reflection、Skills、Tools、Task Trace 视图。
- 全量单测当前基线：`93 tests OK`。
- 文件化冻结验收任务基础版：`clawos/benchmarks/competition_frozen_v1.json`，runner 为 `clawos/scripts/run_frozen_benchmarks.py`。

## 当前主要缺口

1. Windows 双服务一键启动已实现基础版，但仍需端口占用检测、优雅停止和用户手动试跑反馈。
2. README/PROJECT_CONTEXT 已恢复可读，但其他历史文档可能仍有乱码，需逐步清理。
3. 前端还不是企业级任务控制台，缺实时任务流、确认弹窗、Trace 可视化、Review 操作。
4. Task Runtime 仍缺完整幂等、取消、重试、恢复、队列 worker 和补偿事务。
5. 本地离线 Qwen/vLLM-MUSA 尚未闭环，目前主要依赖 DeepSeek API。
6. 已有 5 条文件化冻结验收任务，仍需扩展到 20-30 条并形成 DeepSeek/本地 Qwen 对比报告。
7. 企业级身份、RBAC、多租户、Keyring、备份恢复、迁移、可观测性仍未达标。

## 最近完成

### 2026-06-17 - Windows MTClaw 双服务链路修复

已完成：
- `clawos/mtclaw/prepare_runtime.py` 同时生成 Linux `.sh` 和 Windows `.cmd` 工具包装脚本。
- `MTClaw-框架代码/function_router/server.py` 在 Windows 下优先执行 `.cmd/.bat`，Linux 下仍执行 `.sh`。
- `clawos/clawos_server.py` 和 `clawos/mtclaw/adapter.py` 对本地 MTClaw HTTP client 使用 `trust_env=False`，避免系统代理/Privoxy 拦截 `127.0.0.1:18791`。
- 真实联调验证：MTClaw `/health` 200，ClawOS `/health.mtclaw.reachable=true`，聊天响应 `clawos.mtclaw.used=true`，工具调用 `time_now`，MTClaw `tool_history` 有记录。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_mtclaw_adapter
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：MTClaw 专项 `6 tests OK`；全量 `90 tests OK`。

### 2026-06-17 - 文档恢复与协作上下文整理

已完成：
- 重写根目录 `README.md`，恢复为可读 UTF-8 中文。
- 重写 `PROJECT_CONTEXT.md`，保留项目定位、当前状态、已完成能力、缺口和近期交接。
- 明确长期 goal：把 ClawOS 从 68/100 推进到 80/100 的 Windows 本地稳定闭环版本。

### 2026-06-17 - Windows 双服务启动器基础版

已完成：
- 升级根目录 `start_clawos.bat`，启动流程变为 ClawOS + MTClaw 双服务。
- 脚本会优先使用 `clawos\.venv\Scripts\python.exe`，自动加载 `clawos\.env`，并在需要时把 `DEEPSEEK_API_KEY` 映射为 MTClaw 使用的 `MODEL_API_KEY`。
- 脚本不再硬编码中文 MTClaw 目录名，而是自动查找 `MTClaw-*` 目录。
- 新增 `clawos/scripts/windows_health_check.py`，用于禁用代理的本地 health check。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe -m py_compile clawos\scripts\windows_health_check.py
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：新增脚本编译通过；全量 `90 tests OK`；受控双服务 smoke 通过：MTClaw `/health` 200，ClawOS `/health` 200，聊天请求 `clawos.mtclaw.used=true`，工具调用 `time_now`。

注意：
- 本轮未直接执行 `start_clawos.bat`，避免在 Codex 环境里留下两个独立控制台窗口；验证使用了同等启动命令的受控子进程。
- 后续应由用户或 Codex 在可见终端中手动试跑一次 `.\start_clawos.bat`，确认窗口体验和报错提示。

### 2026-06-17 - 文件化冻结验收任务基础版

已完成：
- 新增 `clawos/benchmarks/competition_frozen_v1.json`，把冻结验收任务从数据库默认值扩展为可审阅、可版本化的 JSON 文件。
- 当前包含 5 条低风险验收任务，覆盖 `meeting`、`research`、`learning`、`git`、`template` 五类场景。
- `clawos/scenario_benchmarks.py` 支持从文件加载默认 suite，并新增 `data_paths`、`data_contains_text`、`tool` 等结构断言。
- 新增 `clawos/scripts/run_frozen_benchmarks.py`，可独立运行文件化验收任务。
- 修复 `clawos/workspace_services.py` 中 Git subprocess 的 Windows 解码问题，统一使用 UTF-8 + replace，避免中文路径/提交信息导致 Git snapshot 失败。

验证：
```powershell
.\clawos\.venv\Scripts\python.exe clawos\scripts\run_frozen_benchmarks.py
.\clawos\.venv\Scripts\python.exe -m unittest clawos.tests.test_scenario_benchmarks
.\clawos\.venv\Scripts\python.exe -m unittest discover -s clawos\tests
```

结果：冻结任务 `5/5 passed`，P95 约 `137.777ms`；场景 benchmark 专项 `5 tests OK`；全量 `93 tests OK`。

注意：
- 目前只有 5 条 seed 任务，用于建立格式和 runner；长期目标仍是扩展到 20-30 条，并输出模型/工具命中率/P50/P95 报告。
- 冻结任务 runner 不写死仓库路径，运行时从脚本位置推导仓库根目录。

## 推荐下一步

1. 将冻结验收任务从 5 条扩展到 20-30 条，增加会议转写、科研 PDF、学习复盘、Git 审批、模板实例化等更深场景。
2. 给 `start_clawos.bat` 增加端口占用检测和优雅停止说明。
3. 前端优先补实时任务/Trace/确认弹窗，而不是继续做静态展示。
4. Task Runtime 下一轮优先做幂等键和可恢复队列。
