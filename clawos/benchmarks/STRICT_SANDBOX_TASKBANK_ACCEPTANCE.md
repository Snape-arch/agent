# 严格执行隔离与首批项目任务验收

后续2026-10-11版本已增加默认部署、独立宿主监督和活动工作区清理互斥，见 [默认私有运行时与调用者退出恢复验收](SANDBOX_RUNTIME_SUPERVISION_ACCEPTANCE.md)。本页模型结果仅证明历史冻结版本，不能作为新增执行器的模型证据。

2026-10-09 至 10-10，接续 f3fbdab。以下区分旧轮中断证据和 Git 控制面修复后的新验收，失败保留，不合并成成功样本。

## 最终追加验收（2026-10-10）

最终新全量 **955/955，2344.648秒**。真实富文本加强契约轮 `output/taskbank/e78fd9cf1c60`：单代理 **1/1，1调用／3000计费token／187.031秒**；多代理 **1/1，5调用／16449计费token／591.203秒**。原公开与共同后置均退出0；5040全标记排列、非变异、等样式拼接与既有限额检查实际执行。协议完整、预算合规、执行可比较、全部任务解决均True；只代表这一个复用的模块任务，未增加独立任务计数。

多代理实际一个工作者，公开集成第一轮exit1，原机制自动诊断、修复、第二轮exit0、评审，再通过独立重放。六个模型回答均有计费与结构化回执，20源码见证稳定；未向模型回传后置检查。此结果证明一次真实失败恢复，不能替代跨文件多人并行、冲突恢复的大样本验收或推断多代理普遍优于单代理。

系统26/26、任务控制38次全部符合预期，包含探针41个唯一SID；模型阶段7次实际执行使用另外7个SID，共48不同SID，父进程令牌证明、Git封存、专属撤权/profile删除独立核验。`independent-audit.json`、`live-independent-audit.json`、`final-state-audit.json`。最终report SHA256 `97179783cc1905c152b9939f30489b4851ef995efd216694292cec16a83406b8`；比较报告文件SHA256 `1beb632e04a4f73b1d1dc2d56ea09b47e9e922f035de364a15627adb40324644`；规范化比较摘要 `ac768df0eb8468656e3cf8fbae1f8c2ad35fc3c3f8b8b0d788296e421e8af381`；plan `7c082294253129dfd05bc63e01423b9dea257b80a4656fb569726bf383037a72`。

模型Qwen3.5-9B/Q4_K_M，运行器exe SHA `cb77cf494da91d7a403142071f4d3b88180f3e63e2d08ecaef6addcbc54d2d89`、权重SHA `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`；16384上下文、2槽，启动参数请求20 GPU layers不视为已核验GPU加速。专属18938/PID16360按exe和UTC ticks639272328472913663核对后于12:56:22Z关闭，`output/strict-taskbank-helper-20261010/stopped.json`。没有重启生产。

14个变更Python源码语法解析和diff检查通过；工作副本原始字节的规范JSON（按仓库相对路径排序、紧凑分隔）下表摘要bundle `2fb76e21a8df2c6e5067074e260ef107f05418a8801f9ae06d5465a05a6d0189`，全量和模型结束后不变。日常DB摘要不变，output/DB/tools/权重及原技能注册表修改排除提交。参考修复留在评估器工作区，未自动修改对应业务功能。旧六任务总体失败与旧排序覆盖不足结果保留；本轮不能抵消旧失败或称六任务成功。

| 源码 | SHA256 |
| --- | --- |
| `clawos/benchmarks/coding_taskbank_v1.py` | `e3379f8f89bf3b3229358406a761af544b5745f7a70d02c796b3562927295c40` |
| `clawos/scripts/probe_appcontainer_boundary.py` | `341c9958ee4e4e16e887709db5ec6a9e095286bf2b1368cb34d3f4c5632dc413` |
| `clawos/scripts/probe_strict_sandbox.py` | `d1fb0ddbbd19b90dd921079d3cd2e78f8252f87d3a1c2908dd0604ef39bad753` |
| `clawos/scripts/run_coding_taskbank.py` | `00f4558feef1efbb123037a9c7b476582bafd495b1a97a7418c8fc06993cad00` |
| `clawos/scripts/run_regression.py` | `e9e7f19c8b9b55c62d613606abd4d7d2a9a4256097f60286e9b09920f8356731` |
| `clawos/services/appcontainer_process.py` | `9765a3965ae8bd3143a40033119f854ea2107ddc6b43d24d4b2c837cc52fd3e6` |
| `clawos/services/autonomous_coding_service.py` | `51be95b553e421a14307aa907fc327f25b4f3f3672088da364bb8b331c4eb178` |
| `clawos/services/coding_comparison_service.py` | `2ce0c9a6894f370eb319034256842f8b24f541719ef07f18726e0ceb006c8130` |
| `clawos/services/coding_workflow_service.py` | `4ce1e4efbd2c649d06a520232547fbf59e92a95ae2342d6fa047d5bd8f39fdb9` |
| `clawos/services/strict_sandbox_acceptance.py` | `67c712e851e3756ef30e69972f7d2e64c589369cb5d65c18c6e0808614dfff54` |
| `clawos/services/windows_appcontainer_boundary.py` | `a54af233795c33ada66beb9060c78c5062da4c753e4a8f089265188eb9a5ebb0` |
| `clawos/tests/test_coding_agent_excellence.py` | `f21b9ffc8f533a5416d566126acd1ab73dbade1b268814ebce02ac7f08eb597f` |
| `clawos/tests/test_coding_comparison_service.py` | `82ef59aed3f9784181088ac635e38b0904b2312109770ff11ecda6a93c1b7d67` |
| `clawos/tests/test_strict_sandbox_upgrade.py` | `15c1768988150fbfcc21d294535baf5a28c119cd5d36eafacf628f31c7fd0cd0` |

## 历史：Git 控制面修复后的验收

成功改 ACL 的宿主正控已补齐：对临时合成指针通过持有的 WRITE_DAC 句柄实际设成受保护的 null-DACL，查询确认 DACL 为空；此时写入、重命名仍被文件共享锁拒绝。模拟启动异常退出后，再次打开查询确认原 DACL 恢复，指针内容不变且正常写入可用。机制测试 **11/11，8.535 秒**，隔离目录 `output/regression/f8e215249a67488887c6ec243c4f1ac2`。此测试证明普通异常收尾，不证明强制杀死父进程后的恢复。

新版工作树控制轮 `output/taskbank/67963adf0d7b/report.json`：系统探针 **26/26**，六项任务原实现／参考修复／公开过拟合负控共 **36 次执行**全部符合预期。参考与负控在真实隔离 worktree 中执行，原种子仓库保持干净。独立审计核对包括探针在内 **39 次原生命令、39 个不同 SID**，父进程核验、无网络能力、Git 指针封存、授权撤销和 profile 删除均有回执，源码指纹稳定。报告 SHA256：`18a5686fddda6f6571c59edd347176c5fb0107d6a8c3a9e57873b84f8a7c1cd4`；独立审计 `independent-audit.json`。

首个全量运行 `output/regression/32aac78646b64968b767949b414a635e`：953 项、1458.666 秒、1 项失败，保留为失败。旧后端测试要求 restricted-token，但未固定后端选择，受已有 AppContainer profile 的宿主状态影响；缺私有运行时后执行器拒绝启动。现只在此旧后端测试固定未安装状态与非严格模式，仍实际执行受限进程；不修改或删除宿主已有 profile，不让生产执行器降级。新增反向回归确认已安装但缺私有运行时必须 exit=126 且不运行弱后端。修复后旧后端 **10/10，15.871 秒**；新版机制 **12/12，8.121 秒**。回归入口增加逐项日志参数 `--verbose`。

追加锚点修复前的隔离全量 **954/954，1449.933 秒**，`output/regression/6b083702b24140888ecdf0ce97f4406a`、`output/strict-taskbank-regression-20261009-final.log`。旧 SWIG/依赖弃用及 asyncio 慢回调警告不阻断。日常数据库 SHA256 仍为 `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`。

首批模型轮已结束，详情如下；其结果未通过。当前只有六个维护者内部任务，策略仍不发布，生产就绪状态仍为 false。

## 2026-10-10 首批真实模型结果与后续修复

`output/taskbank/564e0b97ab1a` 的六任务／12变体全部生成报告；计划 `8b6a55b6ec789c014e9d0b3b912f2a3c67261a018d99ea58d18c08f3119c423c`，20源码见证稳定。单代理原检查接受 **1/6，11调用／62,162计费token／2199.173秒累计墙钟**；多代理 **0/6，20调用／130,507计费token／42086.970秒累计墙钟**。这些数值保留请求状态未知时的保守扣账。协议完整=True，但预算合规=False、执行可比较=False、全部任务解决=False，不能据此作整体速度比较或宣称多代理优越。

学习遥测多代理变体出现 **38753.172秒**累计墙钟和请求超时，远超1800秒预算；长时间停顿原因未核验，不能当作成功持续负载。另有四项请求未核实失败。独立核验12个报告／回答账本／补丁／检查点及重放绑定成功，七项观察可作为原协议内诊断，其中六项为真实失败；五项请求/预算问题不进入可用学习样本。原唯一接受的富文本单代理仅通过当时有限检查，审查发现排序描述和全标记组合覆盖不足，不将其当作完整语义契约已证明。

同轮系统26/26和36次任务控制均通过；独立核对39个不同命令SID、父进程证明与专属撤权删除，`independent-audit.json`。容器/运行时ACL均清理，专属18937 helper PID17828按exe和UTC创建ticks639271548577496067核对关闭，生产进程未操作。该轮报告SHA256 `9be0f005bcd8f20ea689b78bad1d7fac6dda711b40823c68e917b0c4996f0358`，比较报告规范化摘要 `333f16fb212c25c6252d87223602f7e2d6af4e4ac860bc94a2ae47c93896f01a`。

提案阶段用只读plan校验精确编辑锚点，把错误锚点纳入现有最多两次、完整计费的模型格式/提案修复；不猜锚点、不写入被拒提案，结束前再次核对原上下文。富文本契约明确类型名升序及不同文本的拼接，后置增加七类标记的全部5040排列；额外错误优先级排序负控须公开通过／后置失败。不改写上轮已冻结结果，也不把重复任务算新增独立任务。

锚点与比较器回归 **15/15，187.821 秒**，含正确第二次修复与连续错误两种零写入、两次完整计费检查；边界与冻结语料 **12/12，15.245 秒**。新版 `output/taskbank/92b0e5604b94`：系统26/26、任务有效性控制38次全部符合预期，独立核对包含探针的41个不同SID，全部专属撤权删除；错误排序负控0/1。追加修复后的最终隔离全量 **955/955，2344.648 秒**，`output/regression/14863eec05fe493788253a4c5cb3f631`，日志 `output/strict-taskbank-regression-20261010-final.log`。加强契约重跑已完成，见本页最终追加验收；旧报告保持原样。

旧模型轮已在独立 `diagnostic-learning.db` 验证入库：12项核验记录、7项可用观察、6张真实失败反思卡；重复入库仍只有1条证据与6张卡。4项请求未核实与1项超预算不生成可用训练样本。未写日常数据库、未发布或晋升策略。诊断审计 `output/taskbank/564e0b97ab1a/diagnostic-learning-audit.json`。

## 系统边界

原 AppContainer 实现把配置存在视为 production_ready，且由可写工作区里的子进程 JSON 回执证明自身令牌。现改为父进程直接调用 Windows API：创建挂起的 LPAC，核验实际 AppContainer SID 和能力列表，加入 Job Object 后才恢复运行。每条命令使用不同临时 SID，结束时撤销对应目录授权并删除自有容器，避免并发任务共用一个 SID 获得其他工作区权限。安装状态不再宣称网络验收通过或生产就绪。

运行时复制到本轮 output 的独立目录，仅给容器读/执行权限；工作区有修改权限与低完整性标签。拒绝路径祖先/目录树的 junction、symlink 和文件 hard link，拒绝运行时与可写目录嵌套。没有修改生产目录、全局解释器、系统防火墙或 loopback 例外。当前运行器支持 Python 标准库；第三方依赖、Node、Go 等不降级到宿主执行。

配置迁移：已有 AppContainer profile 不会自动准备新版私有运行时。应用启动须通过 `CLAWOS_APPCONTAINER_RUNTIME` 指定含 python.exe/Lib/DLLs 的独立可信标准库副本，并指定已安装 profile；缺运行时或未验证令牌时 exit=126，拒绝弱后端降级。验收脚本自行复制可信运行时、安装专属 profile，只设置自己进程的环境并在结束后恢复。默认应用的运行时部署入口仍需继续产品化；本轮内部验收不能代替默认应用接入验收。

LPAC 声明 registryRead 这一运行时能力，父进程核对其 SID；没有网络能力。网络通过 OS 令牌限制，继承句柄白名单仅有 stdin/stdout/stderr 三个管道句柄。进程数上限 1、进程内存上限 512 MiB、超时终止整个 Job、kill-on-close；流式读取保留有界尾部，累计输出超过 2 MiB 即终止。没有执行宿主 shell，也没有使用可伪造的子进程文件证明令牌。

此阶段仍保持 production_sandbox_ready=false。这是当前 Windows / Python 标准库配置的合成边界验收，未覆盖所有系统公开资源、注册表权限、设备/COM、所有 IPC、磁盘配额、服务账户、多平台和长期并发。任务工作区可写目录内的内容本来可由代码修改；OS 隔离不等于结果正确性或防御所有内核漏洞。

实现参考：[Microsoft LPAC 启动与能力](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)、[显式继承句柄](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)、[能力 SID 的内存释放规则](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-derivecapabilitysidsfromname)。能力只增加 registryRead，没有为便于启动放开网络或整个用户目录。

## 真实系统探针

`scripts/probe_strict_sandbox.py`（旧 probe_appcontainer_boundary.py 入口重定向至该脚本）只在本项目 output 内创建唯一的测试目录和解释器副本，建立唯一测试容器，最终撤权并删除容器。探针从不访问真实凭据或外部网络。

Git 控制面修复前的独立探针 `output/strict-sandbox/e1a6e41c6f58/report.json`：20/20 检查通过，专属目录权限与容器均清理；任务有效性控制轮 `output/taskbank/d5a5cf4191b7/report.json` 再次通过相同矩阵，源码见证稳定。这些旧探针未检查 Git 指针，不能替代本页开头的新版 26 项验收。

| 检查 | 证据要求 |
| --- | --- |
| 工作区读写、运行时可读 | 受限 Python 实际读写成功 |
| 受保护外部文件读/写、运行时写 | PermissionError；宿主正控成功、内容保持不变 |
| ALL_APPLICATION_PACKAGES 可读合成文件 | LPAC 拒绝，排除仅启动普通 AppContainer 的误报 |
| IPv4/IPv6 TCP/UDP 直连 | 四个自有本地监听器，宿主正控成功；受限访问明确 WSAEACCES 10013 |
| 环境清理、额外进程 | 合成环境秘密不存在，实际子进程创建被拒 |
| 令牌、超时、洪泛 | 父进程核验令牌；实际超时退出 124、洪泛退出 125 |

初始失败保留：adea37eaf167 的受限工具环境无法创建 profile；76834710e88c 启动错误 203，补充指向自有工作区的 Windows 环境路径；7ecec2ae715a 令牌核验通过但 Python 运行时启动 STATUS_ACCESS_DENIED，整轮矩阵未通过；0c287296502c 能力推导 DLL 选错导致异常，纠正至 KernelBase。0423d09d1162 的同 profile 探针通过之后，进一步改为每命令独立 SID，再进行上述最终探针。失败未当作成功，也没有转用弱后端完成陌生代码执行。

## 首批任务与防止公开样例过拟合

`benchmarks/coding_taskbank_v1.py` 固定实际源码提交 f3fbdab7e38b8e11ebcf7e67c0285ac83b2bda02，任务材料来自六个项目模块，保留必要的 document_merge → document_richtext 依赖。任务不是新建空白函数练习，但主要是单模块维护切片，不代表完整仓库复杂跨文件开发。

| 任务 | 需求 |
| --- | --- |
| richtext-canonical-runs | 富文本标记规范顺序、空片段过滤、相邻等样式合并、非变异与限额保留 |
| table-shape-contract | 三分支矩阵形状检查、包括快捷返回、合法尺寸变化与原冲突语义 |
| paper-citation-boundary | 论文引用 ID/页码/片段校验、重复参数、数字归一化 |
| history-character-budget | Unicode 字符预算、完整连续尾段、超大消息、角色过滤与历史兼容 |
| evidence-document-review | 权威文档审核状态、坏 metadata、精确 chunk 与部分可用证据 |
| learning-health-telemetry | 缺失/坏/离线遥测拒绝、最新有效行、非有限数与原健康门槛 |

维护者预先编写公开检查、额外后置检查与参考修复。后置脚本不进入模型工作区，也不回传反馈；代码只在公共阶段结束后的共同重放中通过冻结参数执行。后置测试与参考实现属于可公开的评估器材料，不能称为保密外部盲测。

六项均实际验证：原实现公开/后置退出 1/1；参考修复 0/0；只满足公开样例的错误修复 0/1。共 36 次 LPAC 命令，均有父进程令牌证明与专属授权/容器清理，六个任务控制组全部通过。每项有原模块/公开/后置源码摘要，基线 Git 工作区保持干净。任务有效性不等于模型解决任务，六个不同任务摘要也不自动证明所有未来语义任务独立。

复现：

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/probe_strict_sandbox.py
.\clawos\.venv\Scripts\python.exe clawos/scripts/run_coding_taskbank.py
.\clawos\.venv\Scripts\python.exe clawos/scripts/run_coding_taskbank.py --live --url http://127.0.0.1:18936/v1 --model Qwen3.5-9B
```

容器创建需要正常 Windows 用户权限；如果调用工具自身受限，不能以该异常宣称产品 OS 隔离失败或改在宿主运行任务。实时入口仅接受显式、无凭据 loopback HTTP endpoint；每轮目录唯一、旧失败保留。

## 中断前的阶段验证与剩余工作

新增机制 9/9（12.238 秒），比较器回归 14/14（165.234 秒），文件/历史/进化回归 20/20（7.713 秒）；10 个变更 Python 文件语法解析与 git diff --check 通过。全量回归与首批真实比较都已停止，未完成，不计通过；最终修复版本待重新验收。

新运行器与 AppContainer 模块进入比较源码见证；旧弱沙箱证据不能替代新执行器验收。尚未达到至少 30 个真实独立任务，不能发布模式收益策略或进化候选。后续需加入跨文件/依赖/跨语言任务、锁定离线依赖与更广系统权限/长期并发验收。

## 2026-10-09 中断时的真实状态

追加控制面探针发现旧运行器允许改写合成 .git 指针（c14bc8cc-report.json，exit=0且control_unchanged=false）。因此停止旧模型轮，保留原始证据，不能将其称为完整严格验收。

新GitControlSeal持有只共享读取的指针句柄，使用预先取得的WRITE_DAC句柄保存/恢复原DACL；不向子进程继承此句柄。直接可写.git数据库目录拒绝执行，参考控制组改成隔离worktree。新版原生探针5f6a4973f926达到26/26，自有profile与ACL均清理；新增Git写/删除/重命名/改ACL后写的否定检查与指针完整性检查。客体实际改ACL返回5；还需额外正控验证成功改成null-DACL时仍不可写且结束后恢复。父进程被强制终止时的控制面收尾尚未证明，production_sandbox_ready仍false。

当前机制测试10/10（19.512秒），新版六任务控制和真实模型比较尚未重跑。旧50718ba57bff计划12变体，仅完成richtext两变体：single失败，2调用/21502保守扣账/562.875秒；multi通过，5调用/15962token/758.000秒，实际1工作者。随后第二任务仅部分执行，没有完整总报告，未完成的调用与计划不能冒充通过样本。前段与全量回归争用资源，数据不支持纯速度比较；原全量主动终止，不计通过。

自有77168/18936模型helper已核对exe和UTC创建时间停止；旧Bank测试profile根据私有runtime的明确SID授权和对应名称撤权删除（owned-profiles-stop.json），无生产操作。日常DB摘要未变。未提交、未推送、未发布学习策略；当前源码指纹与待办记录output/strict-taskbank-handoff-20261009/audit.json。
