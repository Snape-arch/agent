# 第 5、6、7 优先级实现说明

更新日期：2026-06-15

本轮实现依据：

- `plan_text.txt`
- `架构说明.txt`
- `架构图/clawos总架构图.png`
- `架构图/clawos数据库er图.png`
- `架构图/通讯时序图.png`

## Policy Optimizer

实现了持久化 Contextual UCB：

```text
Register Group/Arms
  -> Context Filter
  -> UCB or epsilon Exploration
  -> Selection Trace
  -> Execute
  -> Reward Evidence
  -> Arm Statistics
  -> Promote Best Arm
  -> Runtime Policy
  -> Rollback
```

支持 Tool、Agent、Prompt、Workflow 四类策略。Reward 与计划书一致：

```text
0.4 * success
+ 0.3 * satisfaction
- 0.2 * normalized latency
- 0.1 * resource cost
```

关键 API：

- `POST /api/policy/groups`
- `POST /api/policy/groups/{name}/select`
- `POST /api/policy/selections/{id}/reward`
- `GET /api/policy/groups/{name}/stats`
- `POST /api/policy/groups/{name}/promote`
- `POST /api/policy/promotions/{id}/rollback`

## 安全运行时

工具执行顺序：

```text
Tool Request
  -> Path/Command Policy
  -> Audit Preflight
  -> Human Confirmation when required
  -> Isolated Worker Process
  -> Hard Timeout
  -> Audit Result
```

已实现：

- 白名单根目录与路径规范化。
- Shell 可执行程序及 Git 子命令白名单。
- 拒绝管道、重定向、命令拼接和明显破坏性命令。
- 独立 `tool_worker.py` 进程、受限环境变量和硬超时。
- ClawOS、Skill 回放、MTClaw bridge 共用同一安全策略。
- 审计事件查询。
- 环境变量引用式 Secret Manager；数据库和 API 不保存、不回显密钥值。

当前边界：

- 这是进程级与策略级沙箱，不是虚拟机或容器级内核隔离。
- Linux 竞赛机仍建议叠加 systemd、容器或 seccomp 资源限制。
- Secret Manager 依赖部署环境提供密钥；后续可接入操作系统 Keyring/HSM。

## 场景工作台

### 会议

- 会前：标题、日期、参会人、议程。
- 会中/会后：导入转写文本。
- 自动抽取：Decision、Risk、Action。
- 行动项保存 owner、due date、状态和原始证据。
- 会议摘要写入 Experience Memory。

### 科研 PDF

- 本地 `pdftotext` 提取。
- 保存 SHA-256、页数、页码分块。
- 写入 Knowledge Memory。
- 检索结果返回 `file#page=N` 和页码引用。

### 学习系统

- 学习目标、目标日期、知识主题。
- 复习评分、证据、笔记、掌握度和下一次复习。
- 无证据不得提升掌握度。

### Git 协作

- 分支、工作区状态、Diff 统计、最近提交快照。
- 生成 dry-run 提交计划。
- 不自动 stage、commit 或 push，写操作继续要求人工确认。

### 模板中心

- 版本化模板与文件清单。
- 内置 Python Service、Research Project 模板。
- 参数渲染。
- 临时目录构建后原子落盘。
- 阻止模板路径穿越；失败时清理半成品。

场景 API 位于 `/api/workspace/*`，同时注册了以下 Agent 工具：

- `meeting_workflow`
- `research_pdf`
- `learning_workspace`
- `git_workspace`
- `template_list`
- `template_instantiate`

## 验收

```powershell
python -m unittest discover -s clawos\tests
```

最终测试结果记录在 `PROJECT_CONTEXT.md`。
