# 默认私有运行时与调用者退出恢复验收

2026-10-11，接续 `ce14f8a`。本轮完善严格执行的部署入口和宿主监督进程，不进行新模型采样，不发布进化策略。下述通过仅覆盖明确列出的场景；`production_sandbox_ready=false`。

## 实现与使用

从仓库根目录执行：

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/sandbox_runtime.py setup --confirmed
.\clawos\.venv\Scripts\python.exe clawos/scripts/sandbox_runtime.py status
.\clawos\.venv\Scripts\python.exe clawos/scripts/sandbox_runtime.py quarantine
```

部署复制可信解释器的 Python 标准库到项目 `output/sandbox/deployment`，排除 site-packages，生成逐文件 SHA256 清单和自有 profile。并发部署共享锁，只有一份新部署可被激活；中断阶段预先写入 setup-state。文件新增、缺失、改动、profile 身份改变、非法清单或未确认收尾的部署均拒绝激活。没有自动安装第三方依赖，也不修改全局解释器权限。

当未显式指定 `CLAWOS_APPCONTAINER_RUNTIME` / `CLAWOS_APPCONTAINER_PROFILE` 时，`CodingWorkflowService` 自动核验并使用该部署。显式配置保留兼容。损坏部署返回 exit126，不降级为宿主执行。`CLAWOS_OUTPUT_DIR` 可指定独立部署/凭据根目录；回归使用隔离目录。首次 setup 的 `--confirmed` 表示执行部署授权，不是完成运行验收。

严格命令交给隐藏的宿主监督进程执行。监督者持有调用者真实 Windows 进程句柄和创建时间，避免 PID 复用；调用者退出或发出取消时，终止自有 Job，再恢复 Git 指针原 DACL、撤销本次工作区/运行时 SID 授权、删除临时命令 profile。Windows 句柄等待和 Job 行为参照 [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject) 与 [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。

请求、状态、最终回执存放在客体工作区和运行时之外。最终回执绑定原始 request.json 摘要；客体无法读取或伪写该控制目录。工作区执行、请求发布、删除、回滚、过期清理共享锁；活动任务无法被这些入口删除或重置。缺失、损坏、未确认清理或摘要不匹配的回执阻断工作区复用与清理。`quarantine` 仅报告，`automatic_release=false`，不伪造成功恢复。

## 当前实际结果

| 验收 | 结果 | 本机忽略目录证据 |
| --- | --- | --- |
| 新增机制回归 | 8/8，0.081 秒；最终版本也纳入全量 | `output/regression/315e7de9da0b437c9ee8c0bfb3b61f71` |
| 隔离检查CLI追加回归 | 5/5，0.053秒；全量启动后追加，单独验证 | `output/regression/fd77a60e41a14692b0b013d9a365ff6f` |
| 工作区原有回归 | 19/19，10.819 秒 | `output/regression/aa21e7aa0cc14d30a373c9b8f0ece70c` |
| 原生监督故障探针 | 15/15，源码稳定 | `output/supervision/a3a51ac31144` |
| 当前任务有效性控制 | 系统26/26、任务38次预期退出、41不同命令SID | `output/taskbank/0f7fbcbc8afe` |
| 实际默认应用入口 | 无自定义运行时/profile变量，LPAC监督执行成功 | `output/supervision-default-20261011/3e7f8cf86d2b` |
| 独立凭据复核 | 44/44请求绑定、清理回执、profile删除与唯一SID | `output/supervision-handoff-20261011/independent-audit.json` |
| 最终隔离全量 | 963/963，1533.946秒；不含随后追加的CLI5项 | `output/regression/74c582129c5d4a4e958dc0a40e84e6d8` |

15 项原生探针实际验证：两个部署进程竞争只生成一份激活部署；默认发现及完整性；客体读取/写入宿主回执均被拒；客体真实持续写入；活动工作区删除被拒；强杀自有调用者后真实子进程退出、退出被检测、清理确认、取消exit130；Git指针字节和原DACL恢复；临时profile已删除；同工作区再次实际执行输出42；私有解释器篡改被拒；未知回执保持隔离。

强杀探针只操作自有调用者 PID48460/创建时间134361762855282350 与自有子进程 PID53040/创建时间134361762870576998，记录保留在报告中。监督进程在此场景存活。本轮没有扫描或重启生产进程，没有读写凭据和日常知识库。

全局默认部署已实际安装并核验，保留为产品配置：`runtime-81432b9a58454494a52d6839b07c14d3`，profile `ClawOS.Runtime.27c8d69f5c5d474f92f7fa58519c2340`。它位于忽略的项目 output；临时实验部署与命令profile已清理，发现用profile有意保留。应用入口冒烟使用新加载的服务，不能推断已有生产进程热更新成功。

最初新增7项回归出现1失败（`4c6c21c8f5c84ec8a5e4212f7f2c4c45`，0.077秒）：空字符串profile环境变量影响默认发现。已使用非空默认值修复；后续7/7（`e9c5f6417d4442e6afdbe50be5278864`），再补中断部署与错误摘要回执共8项。原失败保留，不计成功。早期11/14项探针和旧7见证控制轮保留为历史，最终结论使用上表9见证版本。

## 摘要与源码冻结

独立核验的报告 SHA256：

- 任务控制：`c2c916f799f26102514b7e20857d640aa653bab4b971c0c8ecb217cda8412652`
- 原生监督：`0347f3674908d63a25cf00ed61275ca6073b96a87bcfd3ac48f9ea64e6019c0b`
- 默认入口：`54f93829b566c2857b8d1a5c5a039b2bbcc146ee07b877c35fa50cef983a401a`
- 日常DB，未改变：`8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`

12 个变更 Python 文件的最终工作副本原始字节摘要如下，按仓库相对路径排序的紧凑JSON bundle：`113da87bb70a1ca7ff40b01298af340e407bb316ce89521ade843e9d0e0ee0cf`。全量启动时11源bundle为 `9c637111e275e9d88b74d73bbfb9c18d96121ee80b7e6f5d8d5d619ab2e26bfb`；启动后仅修改检查CLI并添加5项独立测试，执行核心及原生9见证保持不变。Git可能归一化换行，不能把Git blob摘要与原始工作副本混同。

| 文件 | SHA256 |
| --- | --- |
| services/sandbox_runtime.py | c48762b1e5e81be6e4e3207791bbe8ba559f6582583a97fc40969f7660b9725f |
| services/sandbox_supervisor.py | a73f64e03f666030ad561f16b7e3782e2fa30a74b77041a428a55886669f7a4d |
| services/coding_workspace_service.py | e6b4fa44d94fb59001da3ec688de93ddc02aef03379ec6a7fd692677af0ef018 |
| services/appcontainer_process.py | 9ef6ae1efccab8b3adb15cdee9b7c5ebd3fc95a3448baeaf789c099e08c98c26 |
| services/coding_comparison_service.py | d14bd40a297c3199ac7879091c377e8838ffea9e09e7a28b8da1e3863415b667 |
| services/coding_workflow_service.py | e6b9cfbd696e85ee47e351fb9530e92540f200ab15415431602c40c4bcf17726 |
| services/strict_sandbox_acceptance.py | 4477fcb1fb806b4b14628942372befd7a3ddd24f2177eeb5d3795450f5c3bc4c |
| services/windows_appcontainer_boundary.py | 3864c32e6ed3cec1843aec10b0fcb7781463dfa81ac7a67eb0b398061c7f681a |
| scripts/sandbox_runtime.py | 7819789951a526b32f3bcb4a3d8ffcf667d647580d9b62b94078c4aebdcfde90 |
| scripts/probe_sandbox_supervision.py | 2fb6599028437ac4842948d99027b07bcd2b063ce93d96172b3f0d2482ae91b7 |
| tests/test_sandbox_supervision.py | 20280875c92903abc6eed06f76960d53312dd80a924287447699723e089b4b13 |
| tests/test_sandbox_runtime_cli.py | 984787be064919bd05ae7937b754a4a23e906c197d78ccaa408051fbbfbce744 |

原生报告的9个执行见证包含新增部署、监督、工作区服务以及原有os_sandbox/file_transactions。比较器核心见证增至17个（任务库另附5个，共22）；本轮没有新模型报告，不能用历史模型报告证明当前执行器。

全量在上轮用户中断后正常收尾，原生执行核心见证不变；最终12文件解析及工作副本指纹复核通过。全量日志SHA256 `4b35472b360d976fa2035ee14acb56e8adcd31f7bc5577decb22aaf817b857eb`，`output/supervision-handoff-20261011/final-state.json`。随后追加的CLI5项独立通过，不声称一次968项全量。现有SWIG弃用和asyncio慢回调提示非阻断。

## 结论与下一步

默认部署及“调用者被硬终止、监督者仍存活”的收尾链路通过当前验收。整个进程树/监督者同时被杀、断电、跨会话重启后的自动恢复尚未证明；未知状态继续隔离，尚无自动修复/解除隔离或管理UI。宿主同一用户主动修改回执不属于客体隔离边界。Python第三方依赖、Node及其他语言未覆盖。

历史六任务总体失败不因本轮控制通过而改变；真实模型其余五任务的语义/请求失败、至少30个独立任务、跨文件多人并行与冲突、第二模型、长期并发仍需后续实测。旧富文本成功只属于旧执行器与一个复用任务。本轮不形成新能力胜率或策略晋升证据；没有发布策略或写入日常DB。

提交仅包含验收源码、测试和文档，排除tools、权重、凭据、数据库、output及原有 `clawos/skills/skill_registry.jsonl` 改动。沿用用户已授权的origin/codex/coding-agent-competitive-p0-p2正常推送，不强推、不合并master。
