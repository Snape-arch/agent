# 文件、论文报告、历史与自进化验收（2026-10-03）

本轮从 `268fb2f` 继续实现用户提出的文件操作、论文阅读报告、沙箱、对话历史和自进化链路。按 Windows 本地个人产品尺度主观暂评 **90/100**；评分不是企业准入、模型准确率或安全认证。

## 本轮行为

- 文本写入提供 `preview`、`create_only`、`expected_sha256`；UTF-8 写入/追加限 8 MiB。同一路径的 ClawOS 进程在锁内读取、比较、追加，唯一临时文件 fsync 后原子替换。预览不生成目标文件，也不把旧文件当作新产物交付。文件产物注册同样协调并发，损坏注册表保留并报错。
- 论文报告保留实验条件、当前文档引用、来源摘录与证据快照摘要；剔除跨论文引用和被误识别成发现的章节标题。每次生成使用独立文件名，旧下载不被新报告覆盖。Markdown/PDF/结构化 JSON 可下载，刷新及检查点恢复完整分析。引用存在与语义支持分开记录：`semantic_entailment_verified=false`。
- 报告可展开为整个应用窗口的单列文档，统一绿/墨色与可读字号；提供来源摘录、引用返回和下载。原生对话框 Esc 返回焦点并保留原文窗口阅读；手机原文默认收起助手，可先点“展开笔记”打开报告。
- 历史读取同时覆盖当前记录与压缩归档，按原消息 ID 去重分页，完整正文不再截断到 2000 字。显示更早记录、归档全文搜索、Markdown/JSON 导出与刷新恢复会话；迟到响应不能覆盖新对话。会话列表为原生可聚焦按钮，修复侧栏把最近会话压缩到约 1px 的问题。
- 自进化候选捕获策略基线版本，策略变化后候选不再进入影子/灰度路由或发布。发布与回滚使用数据库事务；回滚必须仍拥有当前策略版本与候选载荷，不覆盖其他新策略。看板只计当前有效策略，已被覆盖的历史发布标成 `superseded`，移除“有候选即企业就绪”的判断。
- `CLAWOS_REQUIRE_OS_SANDBOX=1` 增加严格执行门禁：缺少隔离任务工作区、Windows AppContainer 安装或有效令牌时执行失败，不降级到普通子进程。AppContainer 子包装器先检查实际令牌再启动任务命令。没有改变主机 ACL、安装新配置或启用日常进程严格模式。

## 实际证据

最终完整隔离 Python 回归 **740/740，423.771 s**，目录 `output/regression/27fed9b21257401c8650f51aa5276fb1`。最终源码验证没有失败或跳过项。

Node **17/17，293.3632 ms**；最终 `console.js`、`academy.js` 语法检查通过。新回归文件 **19/19，4.776 s**，覆盖 6 个同步起跑真实子进程竞争同一文件（一个成功、五个冲突）、60 次并发追加、40 个并发产物注册、损坏注册表、历史归档/正文/导出、策略版本与回滚所有权、6 个独立数据库实例的 24 次策略版本递增，以及严格沙箱拒绝执行路径。静态页面 **45/45，0.077 s**；旧测试的样式链接断言升级为同时接受原地址/版本参数并仍要求原样式文件。整体回归使用 `run_regression.py` 的独立数据库与产物目录。

中间完整运行 **739 项、378.950 s** 有一个旧静态断言失败：它只接受未带缓存参数的 CSS URL。没有删掉版本参数或断言；修复其匹配方式，并补齐策略直接更新的跨实例事务保护后，最终完整回归740项全部通过。

实际 HTTP handler 验收 **7/7**：四页合成原论文真实入库；112 条包含归档的历史；JSON 单独格式；实际 Markdown/PDF/JSON；再次生成后旧文件 SHA-256 下载一致；持久化恢复；实际 PDF 渲染；实际回滚接口拒绝未确认请求、恢复当前拥有的策略、拒绝覆盖更新策略。回滚 HTTP 测试预置合成已发布候选，验证接口所有权边界，不替代已有影子/灰度评测门禁。最终 ReportLab 报告两页均已人工查看，修复冗余封面、孤立小标题、引用与摘录分离、发现与实验条件分离、长页眉重叠及链接标记裸露。测试没有调用模型，合成资料中的 85% 仅是测试输入，不代表产品或模型得分。

Chrome **154.0.8037.92** 的 CI 独立上下文 **8/8 功能检查通过**：最近会话可点击/112 条完整分页、刷新/导出、归档正文查询、迟到响应隔离、显式飞书页面不被会话恢复覆盖、全窗口报告与三种下载、Esc/精读引用返回、390px 手机无报告横溢。两个报告状态 axe-core **4.13.0** 自动违规为零；`aria-prohibited-attr`、`color-contrast` 的 incomplete 项仍需人工判断，不等同于实际屏幕阅读器语音验收。

本机忽略目录内可复查的证据：

- `output/learning-preview/file-workflow-verified-20261003/acceptance.json`、`report-page-1.png`、`report-page-2.png`。
- 最终 HTTP 7 项：`output/learning-preview/file-workflow-http-final-20261003/acceptance.json`。
- `output/file-workflow-ui-20261003/acceptance.json`、`paper-fullscreen.png`、`paper-mobile.png`。
- 独立预览 `http://127.0.0.1:18917/academy/paper?document=1&reader=window`，合成数据库、模型关闭。`/console` 的 `acceptance-history` 为合成历史。

日常数据库 SHA-256 保持 `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`；没有生产重启、真实飞书外发或模型/权重写入。原来的 Skill 注册表修改保留；tools、权重、数据库、秘密和运行证据不入 Git。

## 复现

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/run_regression.py
node --test clawos/tests/chat_content.test.cjs clawos/tests/academy_labs.test.cjs clawos/tests/document_richtext.test.cjs clawos/tests/document_transactions.test.cjs
.\clawos\.venv\Scripts\python.exe clawos/scripts/file_workflow_acceptance.py --out clawos/output/learning-preview/file-workflow-recheck
.\clawos\.venv\Scripts\python.exe clawos/scripts/learning_preview.py --port 18917 --session file-workflow-recheck
# 另开终端：传入本机已有 Playwright、Chrome 和 axe 路径，不使用用户浏览器资料。
node clawos/scripts/file_workflow_ui_acceptance.cjs --url http://127.0.0.1:18917 --playwright <installed-playwright-module> --browser <chrome-executable> --axe <axe.min.js>
```

严格模式仅针对 CodingWorkflowService 命令边界，可在启动进程前显式设置 `$env:CLAWOS_REQUIRE_OS_SANDBOX='1'`。先按现有沙箱安装/权限流程准备 AppContainer；本轮未扩展主机权限。

## 当前问题与后续顺序

1. 论文证据校验目前确认引用属于当前资料，尚无独立语义蕴含验收。下一步采用教师盲标的真实论文集，分别测结论、实验条件、引用支持与模型降级；再完善扫描件 OCR、多栏/复杂图表、公式与 DOCX 导出。不能把模型关闭的链路测试当作真实研究阅读质量证明。
2. 自进化仍是允许范围内的运行策略优化，保留评测、影子、灰度与发布门禁；没有自动改源码/权重。迁移前未捕获基线版本的候选不能继续推广，需重新建候选与评测。下一步扩大独立质量样本和自动停止灰度的持续观测，不扩大无证据的自动权限。
3. 文件锁仅协调 ClawOS 进程；任意外部编辑器、硬链接或不遵守锁的程序仍可能竞争。严格沙箱为显式可选，本轮只验拒绝降级/拒绝执行与包装器顺序，没有重新验主机级隔离攻击矩阵；默认兼容路径仍不等同完整文件系统/网络隔离。
4. 历史列表上限 500 会话、页面上限 1000 消息，导出上限 10000 消息/16 MiB。下一步加入虚拟列表、FTS 索引和归档生命周期管理；当前全文搜索仍扫描正文，未做百万级历史性能证明。
5. 前一轮的真实 **48 小时、12 个认证 API 身份** 协作测试继续运行，测试的协作核心源码指纹未变；不能提前写“通过”，也不等同本轮新增模块的多天测试。真实读屏语音、多设备多人浏览器、长期浏览器内存与真实飞书云 ACL/同步仍未验收。

既有 FastAPI `on_event`、openpyxl 列名与 SWIG 警告为非阻断提示。最终提交推送按用户授权执行到 `origin/codex/coding-agent-competitive-p0-p2`，不强推、不合并 master。
