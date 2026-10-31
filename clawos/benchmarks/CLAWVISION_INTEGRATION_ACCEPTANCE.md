# ClawVision × ClawOS 第一阶段整合验收（2026-10-31）

## 交付范围

ClawOS新增`/academy/vision/`同源React工作区和`/api/vision/*`网关，整合实验/对比、数据/图表、资产/3D及视觉评估原有源码。前端采用现有ClawOS暖米白、森林绿与共享color-system，统一字体、参数表、表单、侧栏和空状态，移除外部字体请求、无动作的项目入口和没有实测依据的固定存储进度条。

ClawVision保持独立进程、SQLite/对象存储与任务队列；按明确点击启动，不随ClawOS导入或状态查询启动。仅现有ClawOS直接本机所有者可控制，文档邀请/转发头/伪造Bearer不授予实验权限。没有把两个系统数据库或用户表拼在一起，不宣称团队SSO已经完成。

研究阅读包新增“带着这个方向做实验”。RAG/PEFT/扩散方向可带入工作区；从此入口创建的参数实验附带`clawos-reading-context.json`，记录用户选择的阅读引用，并明确`paperReproductionVerified=false`。当前是方向引用与通用实验连接，**不是RAG、LoRA或扩散论文的专用执行器/复现实验已经完成**。教材知识点绑定、专门实验模板和结果回写学习评估属于后续工作。

## 来源及存储边界

- 从用户指定的ClawVision目录冻结236份源码/文本，1764124字节，基于`65afd74a0fc170a32340a36594afd42207c1b5a9`，包含当时131个未提交路径所对应的当前源码。`integrations/clawvision/SOURCE_SNAPSHOT.json`保留起点文件摘要，不能称全部代码来自该干净提交。
- 原目录只读，不提交或改写其Git历史。收尾重新读取这236份源码，全部与起点摘要一致。原数据库、数据资产、凭据、node_modules和模型权重未导入。
- 整合修改位于本仓库副本；默认构建目标是ClawOS。原AuthGate仍保留，独立开发模式需显式使用根base，见`integrations/clawvision/INTEGRATION.md`。
- 当前实验数据位于ClawOS DATA_DIR下独立`vision`目录。测试只在output独立库运行，未重启生产。现有历史实验/数据未自动迁移。
- 私有worker只监听随机loopback端口，端口由已拥有进程的PID/session就绪文件核对；每进程随机握手经私有stdin传入，不写token文件、不放命令行/浏览器、不继承主进程API Key、代理、DATABASE_URL或原.env。worker拒绝直接无握手访问，网关剥离Cookie/Authorization/跨域响应头，保留SSE、Range、内容类型和状态码。
- Windows Job Object负责进程树随所有者退出清理，POSIX使用独立进程组；它不代表文件系统或网络沙箱。服务状态/启动锁等待通过线程池执行，避免阻塞ClawOS事件循环。

## 功能闭环

1. 暖色统一入口、原工作台导航和按需服务启动；整合模式默认确定性模拟器，GPU/Conda必须主动选择。
2. 模拟执行来源随Run参数持久化；指标页面明确准确率、损失、GPU数值为模拟，不当真实训练或设备测量。普通参数表使用中文名称并隐藏内部任务元数据，原始JSON仍保留。
3. 方向→参数实验→对比→阅读引用产物。来源关联失败单独报告，不重复创建已经成功的实验。
4. 数据页读取已保存目录/分页/指定数据集，刷新恢复；默认不使用48行内置样例替代真实数据。样例需明确选择并标记，不能作为保存图表的数据源。
5. 图表标明预览行数，支持原有五类图表与导出；新保存图表为私有，按visualization ID重新打开冻结的图表/数据预览。没有把“保存”暗中当作公开分享。
6. 构建在全新暂存目录进行，旧编译资源逐文件留档output；最终21份产品静态资源随源码交付，React/ReactDOM/Three/Lucide许可文本和源项目声明的Apache-2.0文本保留。
7. 桌面打包脚本加入整合源码；可选分析依赖复制到worker专属runtime-libs，不覆盖ClawOS主Python环境。完整桌面安装包本轮未重打包验收。

## 验证与证据

| 验证组 | 最终结果 | 边界 |
| --- | --- | --- |
| ClawOS网关及研究相关回归 | **143/143，0失败/错误/跳过，20.263秒** | 新网关9项+既有研究134项；不是全项目全量测试 |
| ClawVision后端相关单测 | **55/55，0失败/错误/跳过，34.459秒** | Run、评估、场景、合成、渲染、微型CPU视觉拟合、训练安全及数据引擎基础；不等于GPU大模型或原项目全部历史验收 |
| React前端测试 | **55/55，17个文件，10.07秒** | 包含启动门禁、命名空间、来源关联失败、真实数据恢复及私有图表；渲染器夹具不替代浏览器/WebGL验收 |
| TypeScript与生产构建 | 通过，2026模块，21份产品文件 | 3D相关分块保留按需加载；无node_modules进入提交 |
| 独立真实HTTP/SSE链路 | **13/13通过** | 明确使用模拟器，无LLM或GPU模型调用，非长时负载 |
| 静态检查 | AST8、JS检查、diff检查通过 | 不等于开放域安全认证 |

真实链路最终证据`output/vision-integration-20261031-d/result.json`：状态查询不启动、来源/身份/转发拒绝、重复启动同一进程、worker直接访问拒绝、二次初始化拒绝、模拟任务3步指标/终局、阅读引用产物、SSE终局与跨域头剥离、CSV3行、真实OBJ资产206 Range、停止自有进程、重启后Run/数据持久性、编译入口可读。

最终真实浏览器18936：默认模拟器、参数最小值校验、创建`single-125322`，进入对比；Run `run_78f723b20049`完成10步模拟指标，HTTP回读确认RAG来源与`paperReproductionVerified=false`真实保存。数据页载入已保存3行CSV，保存私有图表`viz_cef3d0b3ac3b`并重新打开v1；HTTP回读确认`isPublic=false`、1张图表/3行快照。记录为`browser-created-run.json`及`browser-private-visualization.json`。截图位于output/playwright/vision-integration/home.png与data-workbench.png。

两个代理创建的页面均已关闭。按PID/UTC创建时间/脚本/目录/监听端口核验后，先经API停止子服务，再关闭独立预览：18935/PID45676/07:22:27.328061Z与18936/PID2036/12:46:39.552416Z。本轮没有把多小时空闲预览、休眠或审批等待计作持续成功负载。

## 保留的失败与修复

- 首轮CSV导入500实际是缺少PyArrow，保留初轮目录；将PyArrow/DuckDB/NumPy/Pillow准备到隔离output/vision-libs后复验成功。测试版本为26.0.0/2.0.0/2.5.4/12.3.0，锁在requirements-integration.lock.txt。没有升级生产Python或启动权重。
- -c轮Range验收脚本误用不存在的`/stream`，断言失败；核对原路由为`/content`后另起-d轮13项通过，不把脚本失败归因成实际Range实现缺陷。
- 最初网关单测用已消费的HTTPX缓冲响应模拟流，产生StreamConsumed；改为真正AsyncByteStream后通过。真实HTTP链路独立验证，未靠夹具掩盖传输错误。
- 新前端测试最初缺少CreateJobInput要求的两个估算字段，TypeScript拒绝构建；补齐后才发布。
- 自动审批曾因额度不足/超时不执行构建或浏览器操作，用户要求继续后按相同审批路径重试成功；未绕过审批。
- 源数据页默认内置样例、刷新不能直接恢复持久数据，以及保存Spec默认公开，是浏览器发现的整合缺口；本轮已修复并加入3项组件回归及真实私有保存/重新打开验证。
- 暂存检查发现Vite注入行与Windows HTML换行混合；产品HTML已规范为LF且构建脚本固定此步骤。生成Three.js的GLSL模板字面量保留原始行尾空白，仅该第三方生成文件通过局部gitattributes声明，未格式化或改写着色器。最终暂存diff检查通过。

## 指纹与保护项

最终`vision_delivery_audit.py`以UTF-8/LF文本规范计算排序path→sha256 JSON集合摘要：

- 整合源码250文件：`45d4ce023f8fb56decf1e71214be5f55c12977fead60c7d5bedb8db5c66c8a32`。
- 产品静态资源21文件：`5a7d7fbea1d24bc3b0862fdfb64642f1767c3d577a6e2129ef110cd1a2dc17a8`。
- 网关/构建/接入及换行规则等14文件：`1631278114003e8c17eb3819f3537682138d01410a849bb3a10c4c09d59caf63`。

细目保存在最终-d/delivery-audit-final-lf.json；Markdown验收/全局进度文档不计入这三个集合。日常memoryos.db摘要`8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`与原registry脏改摘要`a72423d78ff1e7d67c646fcd7debf1824ce9e88767b0034455ff1fefcc5a23d4`前后不变。排除tools、权重、数据库、output、依赖目录及原registry改动；普通提交推送master，不修改原ClawVision仓库。

## 尚未宣称完成

多用户实验授权/SSO、原数据迁移、真实GPU深度模型及外部Provider、专业CAD可选依赖、大规模/多天负载、移动端和屏幕阅读器、本轮完整桌面安装包，均未由此次验收证明。导入的原项目历史benchmark仅保留出处，不自动继承为合并版本通过。RAG/PEFT/扩散专门执行模板、课程/知识点绑定和学习评估回写仍需继续实现。

复现与安装方式见`integrations/clawvision/INTEGRATION.md`。下次正常启动ClawOS后从“实验与视觉”进入；没有为此次交付重启生产。
