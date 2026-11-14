# 编码任务续接和项目记忆

从桌面工作台打开「任务与进度」，进入「编码任务与项目记忆」。输入本地 Git 仓库路径可查看检查点、执行续接预检和维护项目笔记。同一入口可以发起固定测试任务。旧工作区有改动时，预检会列出文件，可选择保留旧工作区并从当前源码重建。

使用本地工作台的 `POST /api/workspace/coding/autonomous`。原有请求继续使用默认动作 `run`。需要持久化的固定测试任务使用 `start` 和 `resume`。

## 暂停和续接

发起任务时指定仓库、问题、测试和当前会话。测试使用 argv 数组，在隔离 Git 工作区执行。

```json
{
  "action": "start",
  "repo_path": "C:/work/my-project",
  "task_id": "fix-parser",
  "session_id": "first-session",
  "objective": "Fix the empty-input behavior in the parser.",
  "test_commands": [["python", "-B", "-m", "unittest", "test_parser.py"]],
  "max_turns": 8,
  "pause_after": 2,
  "confirmed": true
}
```

响应在两轮后包含 `status: paused` 和 `checkpoint_id`。也可省略 `pause_after` 直接运行，使用 `history` 按仓库查询最近 50 个检查点。关闭页面或重启服务后，将同一仓库和检查点传给下一次请求。

```json
{
  "action": "resume",
  "repo_path": "C:/work/my-project",
  "checkpoint_id": "<start 返回的 checkpoint_id>",
  "session_id": "next-session",
  "confirmed": true
}
```

恢复沿用原任务、测试、工作区及累计模型、工具、token 和执行时长计数。暂停期间的等待时间不计入执行时长。已完成的读取回合可以继续使用。进程在一个回合中断时，恢复使用上一个已保存的回合状态，并保留已记录的调用用量。工作区有未确认修改、基线变化或源码指纹漂移时，需要先检查工作区。完成状态只允许查看。续接工作区沿用现有保留机制，每次启动和续接刷新 30 天保留期。

用同一接口发送 `action: "resume_preview"`、仓库路径和检查点 ID，可以在无模型调用的情况下查看下一轮、累计预算、事件时间线、工作区变更路径和当前源仓库的未提交路径。时间线随检查点原子保存，已有检查点可继续使用，事件从下一次续接开始记录。

若需要以当前源仓库为起点，在确认续接时传入 `resume_strategy: "rebuild"`。系统另建隔离工作区并重新运行固定测试，保留旧工作区中的修改，继续累计原预算。旧工作区的源码与工具结果留在旧工作区和事件记录，新回合根据新的基线取证。重建基线失败时，原检查点仍可复查和重试。

## 项目记忆

使用同一个接口和 `repo_path` 管理笔记。

| 动作 | 字段 |
| --- | --- |
| `memory_save` | `topic`、`note`、可选 `scope`、`confirmed: true`。传入已有 `note_id` 更新 |
| `memory_list` | 可选 `query`、`offset`。每页最多 50 条 |
| `memory_delete` | `note_id`、`confirmed: true` |

保存经确认的决策时，可附加 `decision: {"rationale": "记录这项取舍的理由", "checkpoint_id": "<同仓库的检查点 ID>"}`。之后可按决策理由搜索，并用它关联进度、测试和上下文记录。更新普通笔记字段会保留已有决策来源。

`scope` 可填相对源码路径或以斜杠结尾的目录，例如 `src/parser.py` 或 `src/`。有路径范围的笔记在任务覆盖该路径时参与召回，普通笔记按任务文本匹配，支持中文和英文。原文保存在本机，固定测试的仓库发现任务最多接收四条相关笔记的有界片段。恢复时重新读取笔记，已编辑和删除的笔记按当前记录处理。

严格测试通过的任务还记录通过验证的文件版本、运行 ID 和测试数量。后续任务只召回当前文件摘要一致的记录。笔记和历史验证证据是上下文，当前测试和工具权限仍按本次任务执行。项目以本机仓库路径和身份划分。搬迁仓库、设备间同步及远程团队共享目前没有入口。
