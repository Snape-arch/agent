# P0 沙箱监督者退出与重启收尾 — 2026-10-22

接续 `8bc3c12`。本轮补齐自有执行树退出后的宿主权限收尾，不进行模型采样或策略发布。`production_sandbox_ready=false` 仍保持：物理断电、实际系统重启、更多语言/依赖和多天运行尚未验收。

## 实现

- 使用 `PROC_THREAD_ATTRIBUTE_JOB_LIST` 在进程创建时指定 Job，替代 CreateProcess 后再 AssignProcess 的窗口。Job 不在客体继承的三个管道句柄中，保留 kill-on-close、单进程和内存限制。此属性由 [Windows UpdateProcThreadAttribute 文档](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute) 定义；API 成功不是所有故障时序的穷尽证明。
- v2 请求绑定 UUID 命令 profile。创建 profile、授予权限之前，持久化宿主写前日志：请求摘要、原先 profile 不存在、工作区/运行时目录身份、Git 指针对象身份/字节摘要/DACL、调用者和监督者 PID/创建时间。客体恢复执行之前再记录其 PID/创建时间。状态合并写入，保留早期意图，不被末期状态覆盖。
- 监督者使用私有 TEMP，但沙箱锁统一存放于配置的 `sandbox/locks`，避免调用者、监督者、应用和手工恢复因 TEMP 不同而各锁各的。锁目录在客体授权范围之外，沿用禁止重解析点/外部硬链接的检查。
- 应用 lifespan 调用 `recover_pending`。也可运行 `clawos/scripts/sandbox_runtime.py recover --command-id <32位命令ID> --confirmed`。仅处理绑定可信宿主日志的新格式请求；旧格式、缺失/损坏意图、原目录被替换、Git 指针内容变化、进程仍存活、身份不可读取、撤权失败均保留隔离。
- 先核对原调用者/监督者/已记录客体均已退出。PID 被复用不等于原进程仍存活，也不会终止复用后的进程；访问拒绝不作退出证据。恢复过程不发送终止信号，不恢复业务执行，只撤销本命令 SID 授权、恢复 Git 指针权限策略并删除原命令 profile。
- Git 指针保留对象身份和字节摘要，验证完整 ACE 序列及保护位。Windows 恢复时可能规范化自动继承控制标志，不能要求整个安全描述符字节一致；不忽略 ACE 或保护位的改变。
- 完整核验后才写 `cleanup_verified=true` 回执。回执明确声明原执行结果不可用、`execution_replayed=false`，没有伪造 `result`、成功任务或业务检查点。未知状态仍阻止工作区复用。应用其余任务中断标记沿用现有 TaskService 链路，任意编码任务续跑未获认证。

## 终版独立实测

证据均在忽略目录，日志、数据库、复制的标准库运行时和权限记录不提交。

| 验收 | 结果 | 证据 |
| --- | --- | --- |
| 隔离全量回归 | 1031/1031，1736.112 秒 | `output/p0-restart-20261022/full-regression.log`，工作区 `output/regression/e30e8f29579b4b078c54f0b69edc125c` |
| 终版沙箱相关回归 | 24/24，0.360 秒 | `output/p0-restart-20261022/boundary-sandbox-tests.log`，隔离工作区见日志首行 |
| 终版原生重启探针 | 26/26，通过、源码稳定 | `output/sandbox-restart/7ecb9d708305/report.json` |
| 原有原生监督回归 | 15/15，通过、源码稳定 | `output/supervision/1ca02b5d8fc8/report.json` |

全量启动后补加了宿主锁目录与客体目录重叠的拒绝检查及两项测试，终版由上述 24 项和 26 项实测覆盖，不称为冻结终版的 1033 项全量。原有 15 项在最后路径边界检查前完成，各轮独立计数。全量末尾 SWIG DeprecationWarning 保留，不影响本次通过结论。

新 26 项实际包含：自有私有运行时完整性；客体真实运行；跨 TEMP 新宿主进程获取同一工作区锁被拒；只强杀监督者及强杀调用者/监督者两种情形；客体实际退出；无伪造成功回执；恢复前工作区隔离；新进程 CLI 收尾；真实应用启动收尾；Git 指针对象/字节与权限策略复核；命令 profile 删除；复用工作区再次在创建时 Job/LPAC 中输出 42。测试树仅指自有调用者、监督者和 LPAC 客体三进程，控制探针存活；不是把生产工作台、模型服务或整台电脑终止。

另外在真实权限及 profile 已收尾之后，把自有最终回执移到证据文件，注入最终发布丢失。新进程可再次核验、补发结果；第三次调用返回 already_clean。此为已知故障点注入，不是物理掉电验收。

原有 15 项还验证：并发部署仅激活一份、客体读写宿主回执被拒、活动工作区不可删除、调用者退出时取消返回 130、私有运行时篡改拒绝、未知回执继续隔离。两轮与回归不能合并为模型成功率或连续负载时长。

终版独立回执/profile 复核：4 个命令请求摘要绑定、清理标志、当前 profile 不存在及记录的原进程退出均通过，`output/p0-restart-20261022/independent-audit-final.json`，原生报告 SHA256 `15185bf7dbc03a1d4ab361d7010e4eac205fdf95b8f90bd03e672d5caecb9220`。旧轮 `independent-audit.json` 保留，其中 1 项稍后 PID 查询被系统拒绝，仍按未知，不以新轮覆盖该记录。原生故障结论使用当时持有的创建时间绑定句柄观察退出，后续访问拒绝不能用于解除未清理隔离。终版复核自有 18946 监听数为 0。

## 失败记录

1. 首轮新增 7 项中 1 项错误，`output/regression/a12d0e3b0076424b906c6d77ae79733b`：临时文件原 DACL 为 `D:`，恢复后 Windows 标记为 `D:AI`，ACE 序列相同。初版整串比较拒绝放行。随后限定权限策略比较；7/7、再加指针替换与锁目录等守卫后终版相关 24/24。没有放宽文件身份、摘要、ACE 或保护位。
2. 跨 TEMP 轮 `output/sandbox-restart/4b844c2a7cde` 的探针可能选择已完成的回放请求，finally 等待另一个自有调用者超时，未生成终局报告。该轮不计通过。探针现在只选择当前调用者 PID 的未清理记录，按记录的创建时间打开进程，拒绝终止探针自身；新增回归验证不会选旧回放。失败日志保留。后续独立复核该失败轮 3 个命令回执摘要/清理状态及原进程退出全部通过，只删除其闲置自有发现 profile，见 `failed-probe-audit.json`。
3. 其余早期成功轮保留，但本页终局原生结论使用 `7ecb9d708305`，不把初轮或不同源码的计数累加。

## 部署候选运行时

系统 Python 的向量恢复可用，但完整应用首轮因缺少 lxml 启动失败，见 `output/p0-restart-20261022/prepared-runtime-17c57ced93/app.log`。随后在忽略目录 `output/prepared-app-runtime` 创建独立环境，复用现有系统向量包，按项目已声明约束补齐 pypdf、PyMuPDF、pdfplumber、openpyxl、lxml、python-pptx、lark-oapi；不修改全局或回归 .venv。安装日志保留。

终轮以恢复副本的新拷贝启动真实应用，10/10：Chroma/Qwen 无降级且一致、知识 API、教育/笔记/数据/会议页面 HTTP、启动器就绪门禁、正常关闭及端口关闭。`output/p0-restart-20261022/prepared-runtime-2a8b71c30f/report.json`；解释器摘要和 15 个包版本在 `prepared-runtime-audit.json`，`pip check` 退出 0。仍使用 system-site-packages，不是自包含锁定发行包；没有改默认启动器选择，没有运行六类完整真实业务或浏览器/生成模型。

本机可显式把 `CLAWOS_PYTHON` 指向 `clawos/output/prepared-app-runtime/Scripts/python.exe` 选择此候选，再按原本地启动流程核验模型服务。该环境和路径只属于本机，不提交依赖包或凭据，不能推断其他机器安装成功。

同一候选独立新进程另验真实 CPU Qwen 检索：Chroma 无 fallback、181 条向量、返回 3 条，单次冷查询 26.290 秒，日常库摘要不变，见 `prepared-runtime-2a8b71c30f/query-report.json`。这只证明检索链路可用，不代表语义质量、性能基准或生成模型验收。

## 源码与边界

11 个本轮 Python 源码/测试文件终版原始字节 bundle：`0233664da67f566686003e7570c79beaa5eec0f40808e2c91e352735cb89deb9`，逐文件摘要、AST 解析及终版原生源码一致性校验见 `output/p0-restart-20261022/source-audit.json`。全量启动版本的旧摘要记录在 `source-audit-full-start.json`；原始字节摘要不等同于 Git 换行规范化后的 blob 摘要。执行比较器核心见证增加恢复服务，旧模型报告不能证明当前执行器。没有新增真实生成模型任务、学习增益或进化策略发布。

日常 DB SHA256 仍为 `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`。生产未重启；新应用启动仅使用自有 18946、白名单环境、隔离配置/数据、模型调用为 0、飞书 live 关闭。测试服务正常关闭。

本轮证明已持久化 v2 意图下的指定崩溃收尾路径。写前文件已 fsync/原子替换，但不能据此宣称突然掉电时所有文件系统/存储控制器的耐久性。未知旧日志不会自动迁移或解除隔离。宿主同用户主动篡改日志不在客体隔离边界内。

下一阶段 P0：固定完整部署解释器，补六类真实业务/浏览器流程，进行可控重启和存储故障验收；历史 275 个缺失产物仍为降级，未经可信备份或人工决策不删除记录。Python 第三方依赖、其他语言、多设备/读屏和连续负载继续独立验收。
