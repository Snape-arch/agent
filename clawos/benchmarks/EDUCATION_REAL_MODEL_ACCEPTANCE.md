# 教育整书真实模型验收（2026-10-21 至 10-22）

基线 c90ffa8；本轮连接独立环回 Qwen3.5-9B-Q4_K_M，走实际 FastAPI → 共享提供方 → 本地模型 → 本地合同与原文校验 → CAS 持久化。不是确定性模型夹具，也不是教师或学习效果验收。

## 真实输入和隔离

教材为 Swaroop C H 的 [A Byte of Python](https://python.swaroopch.com/)，原始仓库 [swaroopch/byte-of-python](https://github.com/swaroopch/byte-of-python)，固定 commit `84f4dd8d6f09836fa58226eaafe922b8a7baabc6`。正文 CC BY-SA 4.0、代码 BSD 3-clause；QA 文件保留作者、官网、许可及改编说明。24 个 SUMMARY 文件原始章节约204912字符；其中一个源文件为cp1252，显式转码并保留原始字节摘要。发现88处GitBook程序引用后，从相同commit补齐88个程序/输出文件，得到229050字符的QA改编；不执行代码，10处截图仍为外部引用，不能声称图像解析完整。

权重 SHA256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`；llama-server SHA256 `cb77cf494da91d7a403142071f4d3b88180f3e63e2d08ecaef6addcbc54d2d89`。模型端口18943，预览18944，数据库位于 `output/learning-preview/education-model-20261021/learning.db`；生产未重启、日常数据库未写入、未加载配置凭据。公开输入、运行追踪、每批请求结果、失败与源码指纹保存在忽略目录 `output/education-model-20261021`，不提交教材全文、权重或数据库。

## 发现和修复

- 旧目录将代码围栏中的 `#` 注释及所有内层标题拆成226段。新上传Markdown使用 `markdown-chapters.v2`：跨解析片段追踪围栏、只以最外层真实标题分章，仍保留原始片段位置。该书得到26章（包含前置说明及附录中的额外顶层标题）。已有材料保留v1目录，人工目录及已冻结计划不被静默重新解释。
- 本机CUDA DLL在 `tools/llama.cpp/runtime`，启动脚本原先未加入子进程PATH，实际回退CPU。现在仅对模型子进程补上本地运行库路径并恢复原PATH；GPU实例日志实际列出CUDA0，不能把-ngl参数存在当作GPU已运行。
- 图谱及校准使用严格JSON Schema；不支持结构化输出时拒绝。图谱章节、原句与实际片段编号在解码合同中绑定，保留换行和Markdown；服务端再次验证，不能靠空白归一化、翻译或模糊匹配通过。候选原句不充分时省略，不代表语义证据已经充足。
- 单批≤6章/24000源字符，模型新增≤6节点/4关系，max_tokens=2800；每次外层调用最多180秒，提供方可更早超时；模型返回后还要检查实际单调时钟耗时，避免系统长暂停后先处理回复而漏过已到期计时器。只有图谱结构/引用失败可修正一次；CAS冲突、撤权、传输/截断失败不自动重试或覆盖。失败有运行ID和诊断，成功有真实调用/修正计数。所有模型边始终待复核。
- 新导入源若含未展开include，相关片段待复核并暂停提取/出题；不根据源指令自动联网抓取。保留可读原文，要求完整出版文件或人工补齐。
- 页面显示所选章数/字符预算与已有概念提示、阻止重复提交，提取期间固定当前教材，展示调用回执与仍需人工复核的边界。只做静态语法与实际HTTP校验，未声称本轮新版整页浏览器通过。
- 新验收CLI校验QA环境、会话、源文件摘要、目录算法和空图；逐章分批，持久化计划/进度/终局，拒绝覆盖证据。批次全成功与概念覆盖完整是不同指标。

## 失败记录与最终结果

1. `baseline`：旧目录函数小节，CPU服务75.125秒后HTTP502，图谱未写入。
2. `structured-functions`：Schema输出可解析，但引用未定位，两次模型回复后400，74.848秒，未写入。
3. `quoted-functions`：模型将原文换行改为空格，两次严格校验失败，69.290秒，未写入；未通过放宽引用掩盖失败。
4. `bound-functions`：成对候选原句解码通过，19.963秒、3概念/2待复核边。这只是单章。
5. `whole-book`：命中旧材料去重缓存后主动中止，无完整终局。随后CLI增加算法及空图强校验，不能把该轮称为整书通过。
6. `whole-book-current`：26章/16批，14批成功、2批输出达到2800 token上限后HTTP502；568.959秒，整体失败。65节点/54边，18章有概念；该中间版本不是最终6节点/4边解码上限。其88处外部代码尚未展开，不能作为完整示例输入。
7. `whole-book-resolved`：补齐程序后首批400，两次回复均因节点章节与来源不匹配被拒，后主动停止，未有完整终局。随后将章节-片段-原句三者绑定。
8. `whole-book-final`：4/16批后中断，有一批耗时11938.297秒；没有终局。恢复后原模型和预览PID均已不存在，具体长暂停/进程退出原因未核验，不能称连续负载或性能通过。新增实际耗时门禁的181秒合成时钟测试仅验证拒绝逻辑，不是一次真实休眠测试。
9. `whole-book-terminal`：恢复时连接拒绝，无模型调用；确认端口空闲和旧进程缺失后重建自有模型/预览。
10. `whole-book-terminal-v2`：最终独立整书 **16/16批成功**，26章各实际发送一次，489.568秒墙钟、最大单次39.470秒；16次真实模型请求、0次合同修正。生成73节点/55条待复核边，包含19条跨章关系，23/26章已有概念；这不代表全书知识完整。提供方报告114303输入token、19695输出token，共133998，包含缓存输入的提供方口径，不作金钱成本或模式收益推断。

原始Markdown独立核对：170504个非空白字符，索引来源区间重建后同为170504且逐字一致；不证明外部截图/代码已展开。补齐示例后的229050字符输入，188452个非空白字符与最终索引来源区间重建逐字一致。独立审计128处节点/关系引用均在指定章节或批次原文中定位，图谱只追加、节点ID唯一、所有边待复核、16个运行记录与自有Qwen提供方对应，所有实际调用在180秒内；`independent-audit.json`全部检查通过。

终版教育 **103/103，47.576秒**（`output/regression/3186976c561f4f76bbe2f2ee69c72b35`，`education-deadline-final.log`），提供方 **31/31，1.087秒**（`b8e29d6dbf9c4b568a137c9ecc09c44c`，`provider-regression.log`）分别通过，不相加称一次全量；本轮未重跑全仓库全量。此前102/43.910秒等为中间专项，保留日志。Python/JS/PowerShell语法与diff检查通过。

当前自有预览真实HTTP补验11项通过（`current-http.json`）：页面HTML/JS与工作区摘要一致、合成教师草稿CAS与保存、学习者标签隔离/禁止模型请求、待复核边不进入先修路线、HttpOnly会话和双角色撤权；没有记录邀请码或会话值。该证据不是浏览器点击、真人教师或屏幕阅读器验收。

最终12份源码/测试/UI原始字节bundle SHA256 **1d36473fd01275e562e9d360db146ad7a2c129ab6290bf9ef415280362942939**（逐文件摘要见`final-source-audit.json`；排序路径→SHA256映射以JSON sort_keys=True、separators=(逗号,冒号)序列化再哈希）。末轮结束独立复核未变，日常DB仍`8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`。

自有预览父PID38460/子43388与模型PID15764按exe/端口/UTC创建时间核对后，于2026-10-22 09:00:51 UTC关闭，18943/18944无监听；`owned-processes-stopped.json`保留回执。生产进程不动，需正常重启才载入新增源码。提交范围为本轮源码、测试与文档，排除tools/权重/凭据/数据库/output及原registry改动；沿用授权origin/codex分支，不强推、不合并master。

## 可复现入口与边界

先启动自有本地模型和隔离 `scripts/learning_preview.py --session <qa-session> --local-provider-url http://127.0.0.1:<model-port>/v1`。提供保留原署名/许可、人工补齐引用的本地教材，然后运行：

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/academy_graph_acceptance.py --url http://127.0.0.1:<preview-port> --session <qa-session> --source <local-book.md> --upload-name <fresh-qa-book.md> --index-algorithm markdown-chapters.v2 --require-empty --all-chapters --output <fresh-output-directory>
```

本轮没有真实教师量尺、真实学生答卷或至少七天追踪，不伪造人类署名、人员独立性或题组等值。`teacher_calibration_verified=false`、`semantic_accuracy_verified=false`、`real_learning_effect_verified=false`；所有图谱边待复核，引用能定位不能证明先修逻辑正确。候选句每片段最多6项，可能限制细粒度覆盖；单批只提核心概念，整书接收完不代表知识完备。仅一个模型、一本英文教材、无扫描公式/表格专门实测。此前浏览器内部错误页被策略拒绝，未换浏览器或底层接口绕过；不计本轮新版全页面、真实多设备/读屏验收通过。
