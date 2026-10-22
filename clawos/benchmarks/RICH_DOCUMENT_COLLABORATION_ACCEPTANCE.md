# 富文本、实时协作与前端验收（2026-10-03）

本轮基于 `d2753aa` 继续处理复杂文档编辑、实时多人协作、旧页一致性、无障碍和长文档性能。下述结果来自隔离资料和本机 Chrome；不代表飞书云文档功能完全对等或企业级长期验收。

## 已实现

- 文本块增加受约束的 inline span 模型：粗体、斜体、删除线、下划线、高亮、行内代码、链接可组合并保存。服务端校验样式和链接，生成一致的 Markdown 文本投影；旧文档兼容。
- 实际剪贴板粘贴保留标题、嵌套列表、组合格式、表格、代码块；脚本、框架和外部图片不会随粘贴加载。单个表格或代码片段也创建对应块。代码阅读预览提供基础语法着色。绘图增加坐标字段和键盘添加图形入口。
- 认证 SSE 推送版本、变化块、顺序和在线成员；重连从版本恢复。每次读取重新检查会话及权限，撤销后结束流并切换只读。SQLite 版本轮询支持共享数据库的多 worker，默认间隔 0.6 秒。
- 新客户端显式启用三方合并，旧接口仍默认严格 CAS。不同块、非重叠文字/富文本及不同表格单元可合并；重叠编辑、删除与编辑、相反排序保留草稿并返回冲突。保存响应绑定本次事务快照，修复并发保存后返回另一事务快照的竞态。
- 离线保留本地草稿，恢复网络主动重连并重试；远端变化只更新受影响块，保留未变输入节点。远端更新清除旧撤销栈，避免撤销覆盖他人工作。
- 限制撤销历史为 40 项及约 24MiB，按输入时间分组；缓存、目录和自动保存延迟执行。离屏块使用 content-visibility，图片懒加载，降低每次输入的序列化和布局成本。
- 代码、测验、导入、旧首页/路线图和阅读器接入共享导航、字号、对比度和焦点样式；修复旧导航位移导致的裁切及窄屏标题挤成竖列。阅读器保留全窗口沉浸布局。
- 跳过导航位于首次 Tab 顺序；正文焦点避开动态工具条；阅读标签提供 tab/tabpanel 与方向键；原生对话框支持焦点约束、Escape 和返回触发按钮。提供减少动画、高对比度和键盘绘图支持。

## 验证结果

| 项目 | 结果与边界 |
| --- | --- |
| 最终隔离 Python 全量 | **715/715，323.774 秒**；工作目录 `output/regression/31614d5d30d44479a0e9230b55be4be4`。此后只有前端布局修正，并复测相关前端检查 |
| 专项后端 | **10/10**；12 个并发写线程、同块非重叠富文本、Unicode、重叠冲突、删除/排序、表格、历史过期、权限撤销和 SSE 恢复 |
| 最终 Node | **13/13，257.344ms**；Markdown、SSE、富文本转义/链接/投影和代码预览；六个变更 JS 文件语法检查通过 |
| 实际富文本操作 | Chrome 剪贴板写入后 Ctrl+V；组合格式、2×2 表格、Python 代码及嵌套列表在服务端 JSON 中保留；无外部资源请求或脚本执行。选区格式、清除格式和键盘绘图保存经过检查 |
| 实际多人协作 | 两个独立浏览器会话，一次性邀请加入；不同块自动更新，同一富文本块首尾编辑合并并保留 7 类格式；离线草稿与在线修改恢复合并；重叠写返回 409 并保留本地草稿；撤销访问后 UI 只读、API 403 |
| 无障碍自动检查 | axe-core **4.13.0**，WCAG 2 A/AA、2.1 AA、2.2 AA 标签；九个路由和文档编辑/阅读/协作/绘图四种状态均 **0 violations**。仍有 incomplete 项需人工判断，不表示完整认证 |
| 键盘人工检查 | 首次 Tab 跳过导航；Enter 聚焦正文（顶部 168px，高于工具条底部 156px）；对话框连续 12 次 Tab 未逃逸，Escape 返回触发按钮；坐标字段添加箭头并保存 |
| 窄屏与重排 | Chrome 390×844 触屏模拟，文档、代码、学习、测验、导入、阅读、会议、数据、飞书九页 clientWidth=scrollWidth=390。640 CSSpx / 2 倍像素比覆盖四页，作为等效 200% 重排检查，未冒充真实手机或浏览器缩放 |
| 数据隔离 | 原 `memoryos.db` SHA-256 仍为 `8167052e0c203036ad74bb1409ce74bd9cfaef585244865848ea5be7b2a8c543`；无真实租户外发、生产模型调用或生产服务重启 |

九个扫描路由：`/academy/notes`、`/academy/code`、`/academy/path`、`/academy/quiz`、`/academy/ingest`、`/academy/paper`、`/meetings`、`/data-lab`、`/console?view=feishu`。`/academy/path` 实际渲染 studio，旧路径 HTML 也同步了共享样式。

焦点检查依据 [W3C Focus Not Obscured](https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum)。自动检测能力及人工判断边界参见 [Deque axe-core](https://www.deque.com/axe/axe-core/)；本轮未实测 NVDA 等屏幕阅读器。

## 长文档对照实测

Chrome **154.0.8037.92**，headless 实际渲染，1280×800。本机同一隔离后端、同一合成文档规格，每组 3 次；基线通过 `git show d2753aa` 截取六个原有静态文件并在浏览器路由中覆盖，未复制运行资料。最终对照运行期间没有同时执行 Python 全量或手动浏览器验收。

文档包含 **300 块、696,055 个字符、2,102,269 字节 JSON**。每次真实键盘输入 81 字符。输入延迟取 keydown 至双 requestAnimationFrame 的绘制代理值；不是完整 INP 指标。JS 堆取输入后 Chrome Performance 指标，不是整个浏览器内存、峰值或 RSS。

| 指标（3 次中位数） | 基线 d2753aa | 本轮 |
| --- | ---: | ---: |
| 300 块首屏就绪 | 333.9ms | **267.1ms** |
| 单次输入到绘制 P95 | 39.9ms | **32.0ms** |
| 输入后 JS 堆 | 144.76MiB | **6.85MiB** |
| 每轮 >50ms 长任务数量 | 1 / 1 / 1 | **0 / 0 / 0** |

原始 JSON、截图、开发扫描依赖均在忽略目录 `clawos/output/editor-upgrade-20261003/`，最终对照为 `benchmark-idle/result.json`；不作为源码提交。预览 `18912` 使用 `editor-realtime-20261003` 合成数据库，模型关闭；旧预览/生产服务没有被替换。

## 复现

```powershell
.\clawos\.venv\Scripts\python.exe clawos/scripts/run_regression.py
node --test clawos/tests/chat_content.test.cjs clawos/tests/academy_labs.test.cjs clawos/tests/document_richtext.test.cjs
.\clawos\.venv\Scripts\python.exe clawos/scripts/learning_preview.py --port 18912 --session editor-realtime-20261003
node clawos/scripts/editor_experience_benchmark.cjs --url http://127.0.0.1:18912 --baseline d2753aa --playwright PLAYWRIGHT_PACKAGE_PATH --browser CHROME_EXECUTABLE_PATH --axe AXE_MIN_JS_PATH --out clawos/output/editor-experience-benchmark
```

将三个大写路径换成本机安装位置；Playwright 与 axe 是验收依赖，不是产品运行依赖。脚本先检查仅在隔离预览存在的 `/api/qa/environment` 标记，拒绝向未确认隔离的服务写入合成文档。`--scan-only` 可只进行页面无障碍扫描。

## 当前问题与评分

按本机个人产品前端尺度主观暂评 **86/100**（此前 82）。编辑、协作和可操作性明显提升；以下范围仍未达到飞书级成熟度：

1. 独立块仍是各自编辑宿主，跨块连续选区格式化有限；表格单元富文本、合并单元格、公式、范围批注、复杂外部文档导入尚未实现。代码着色是基础词法预览。下划线/高亮保存在 JSON，标准 Markdown 投影不保留这两种视觉样式。
2. 三方合并采用保守连续变更区间；同一块多处独立修改可能产生可人工解决的额外冲突。还不是 CRDT；在线状态定位到块，尚无远端精确光标。历史保留最近 50 版，离线超出历史需显式恢复。
3. 0.6 秒 SQLite 轮询适合当前规模；大量持续在线连接仍需要负载实测和事件分发优化。12 写线程与两个浏览器是有界测试，多天、多设备、慢网和多人真实资料未完成。
4. 仍有 300 块/8MB 边界，未实现完整虚拟文档；此次约 70 万字符基准不能外推到万页资料。仍需屏幕阅读器、真实手机、真实浏览器缩放和不同硬件验收。
5. 本地权限与 SSE 已修复，真实飞书租户 SSO、云文档 ACL/双向同步及真实教师质量校准不属于本次已验证结果。旧页面仍存在局部遗留组件，后续应继续迁移为统一组件。

非阻断警告：既有 FastAPI on_event 弃用、openpyxl header/footer 与 SWIG 提示。交付仅源码、测试、脚本和文档；排除 tools、模型权重、凭据、数据库、产物和预先存在的 Skill 注册表改动。
