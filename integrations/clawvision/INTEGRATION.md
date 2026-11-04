# ClawVision in ClawOS

This is a source snapshot of the user's ClawVision working tree, based on
`65afd74a0fc170a32340a36594afd42207c1b5a9`, including newer uncommitted source.
`SOURCE_SNAPSHOT.json` preserves original file fingerprints before integration
changes. The original project and its Git history are untouched.

The source project declares Apache-2.0 in pyproject.toml; original attribution
and source notices are retained. No model weights, original databases, artifacts,
credentials, node_modules or Git metadata are imported.

ClawOS serves the rebuilt React app at `/academy/vision/` and gateways its API
under `/api/vision/service/`. The experiment backend runs in a separately owned
loopback child process with its own data directory. Only ClawOS's direct local
owner can operate this first integration. Document collaborator permissions do
not grant experiment or training access. Upstream standalone authentication and
tenant APIs remain in the source, but are not presented as integrated team SSO.

ClawOS credentials/environment are not inherited, models are not automatically
loaded, and the service starts only on explicit request. Built-in simulator and
local deterministic geometry are distinct from real training/model inference.

Integration changes: API/resource namespace helpers, ClawOS launch gate and
navigation, shared warm-paper color tokens, typography/layout, an authenticated
loopback worker entry, runtime supervision and bounded streaming gateway.
Standalone source mode retains the original AuthGate; use
`node node_modules/vite/bin/vite.js --base / --host 127.0.0.1` with a separately
configured standalone backend. The default production build targets ClawOS.

Install the tested optional data adapters into an isolated directory with:

```powershell
<app-python> -m pip install --only-binary=:all: --target clawos/output/vision-libs -r integrations/clawvision/requirements-integration.lock.txt
```

They are used only in the child experiment service. The desktop build copies
them into that service's separate `runtime-libs`, without merging them into the
main ClawOS Python environment. Neither directory is committed. GPU/ML/CAD
extras remain optional and require their own installation and validation.

Build the frontend with `node clawos/scripts/build_vision_frontend.mjs`; its
staging, cache and previous compiled assets stay in output. The actual product
assets and third-party notices are published to `clawos/static/vision`.

The integrated data page loads saved datasets instead of silently choosing
sample rows. Dashboard saves are private; reopening uses a saved visualization
ID. Charts describe the size of their preview rather than implying a whole
dataset scan. Built-in examples require explicit selection and remain labeled.
# 第二阶段：课程机制实验（2026-11-01）

从 `/academy/vision/?lesson=rag#teaching` 直接进入；LoRA课程用 `lesson=finetune`，扩散用 `lesson=diffusion`。此入口不需要启动实验子服务或模型。文献包与课程页均有入口，课程可回看对应实验与反思。

三个有界CPU模板分别执行合成短文的来源过滤、六维低秩适配梯度训练、一维解析score的概率流ODE积分。它们是可复跑的机制教学，不是大模型/原论文指标复现。实验保存在ClawOS `DATA_DIR/vision/teaching.sqlite`，与原Vision训练Runs分开显示，避免混用指标类型。

可选教材知识节点会冻结修订/图谱版本及原文来源，版本变化拒绝保存。反思追加而不覆盖，不写掌握度或真实教学效果。仍仅本机所有者访问，不继承文档协作授权。JSON导出可用仓库 `clawos/scripts/vision_teaching_replay.py` 复跑，完整范围见 `clawos/benchmarks/CLAWVISION_TEACHING_ACCEPTANCE.md`。

# 第三阶段：统一可视化教学工作区（2026-11-02）

2026-11-04补充：原默认库27业务表/467记录/63对象已迁入默认ClawOS Vision存储，设置页显示回执。原库保留；离线脚本 `clawos/scripts/migrate_vision_store.py` 拒绝覆盖已有目标、缺对象/未知非空业务表或源变化，不导入账号/凭据，不恢复旧任务或公开分享。详细命令、1266项整体回归、完整应用重启及真实资产回读见 `clawos/benchmarks/INTEGRATION_AND_VISION_MIGRATION_ACCEPTANCE.md`。其他自定义数据目录需要显式指定新目标，不会自动扫描用户磁盘。

`/academy/vision/` 默认进入可视化课堂，文献包和课程直达 `?domain=rag|peft|diffusion#visuals`。一个ClawOS导航连接课堂、手册、数据、三维、评估、资产、三维创作、运行、比较、产物和设置，共11个视图。原standalone模式保留。专注演示填满程序页面，Esc返回；暖米白/森林绿、字体与图表统一。课堂/手册不需要实验子服务，其余工具在同页显式启用服务，不自动加载模型。

课堂读取已保存CPU报告：RAG逐题来源/版本/分数/答案及失败检查，A、B、B×A和总权重的逐格热力图及真实测试损失，扩散积分时间轴/均值/方差/终点分布与成本。切对照保留当前问题或对应位置。数据表、SVG/PNG和完整JSON便于核对；不以预设动画数值冒充计算。

个人观察经 `/api/vision/teaching/reports/{rid}/visualizations` 保存/分页，再由 `/api/vision/teaching/visualizations/{vid}` 恢复。绑定原报告摘要、owner和合法位置，幂等冲突拒绝；每报告200个、每页20个，仍存独立teaching.sqlite，不写掌握度或教师评价。

原18插件保留自动发现与隔离边界。数据图表支持真实导入、私有保存/恢复和保留样式导出；单图充分利用宽度。三维页恢复真实资产，内容失败不替换为程序模型；构造点云/轨迹仅显式打开并标注。画布随容器/演示模式调整，卸载释放观察器、材质和WebGL上下文。

原导入器遗漏的两个 `.mjs` 检查脚本已恢复，原始摘要另存 `SOURCE_SUPPLEMENT.json`，不重写原236份清单。可运行 `node integrations/clawvision/scripts/verify-plugin-architecture.mjs`，构建后运行 `node integrations/clawvision/scripts/check_bundle_budget.mjs`。原初始应用190000字节、Three core560000字节门槛未提高；三维创作懒加载。发布跳过字节相同资源，最后更新入口HTML。

相关108项后端、85项前端、29项实际HTTP和真实浏览器流程完成，详见 `clawos/benchmarks/CLAWVISION_UNIFIED_VISUAL_ACCEPTANCE.md`。整合指单产品入口、教学证据链与工具可达；原库未迁移，GPU/真实模型、团队实验SSO、真人教学、多日负载不在通过范围。
