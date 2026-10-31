# ClawVision

## 0.22.0 Professional 3D

The 3D pipeline now has exact STEP/IGES/B-Rep round-trip tolerance reports,
OpenCascade Boolean/fillet/chamfer/repair, complex Manifold validation, browser
and native NVIDIA telemetry, authenticated Range streaming, multi-channel PBR,
skins and animation playback. Local semantic generation needs no API key, while
an isolated local-neural GPU Worker can host separately licensed model weights.
See [`docs/professional-3d.md`](docs/professional-3d.md) and the committed
[`professional-3d-windows.json`](docs/benchmarks/professional-3d-windows.json).

## 0.21.0 ML Ecosystem

ClawVision now runs end-to-end Lightning, Hugging Face Trainer, Keras and
PyTorch DDP acceptance fixtures, including checkpoint recovery and rank-zero
reporting. MLflow and W&B support bidirectional offline migration. See
[`docs/ml-ecosystem.md`](docs/ml-ecosystem.md).

## 0.20.0 Analytics Engine

The data layer now supports immutable multi-file/partitioned Parquet versions,
schema evolution, lineage, cross-dataset JOINs, query plans, caching,
cancellation, timeouts, and bounded DuckDB execution. S3/MinIO queries use
direct `httpfs` Range reads instead of downloading complete objects into Python.
See [`docs/analytics-platform.md`](docs/analytics-platform.md) and the committed
10-million-row evidence in
[`docs/benchmarks/analytics-10m-windows.json`](docs/benchmarks/analytics-10m-windows.json).

一个独立实现的 AI 实验可视化工作台，以统一的 `ExperimentRun / Parameter / Metric / Artifact` 数据结构实现完整实验闭环。

## 0.19.0 能力

- 工程成熟度首轮闭环：OpenAPI 3.1、Run/Dataset 分页、服务端数据筛选与聚合、TensorBoard/MLflow/JSONL 导入、glTF 引用完整性门禁，以及可重复的 SQLite/数据引擎/3D 规模基准。
- 详细质量与规模路线图及验收口径见 [`docs/QUALITY_SCALE_ROADMAP.md`](docs/QUALITY_SCALE_ROADMAP.md)。

- 全业务租户隔离：Run、Dataset、Visualization Spec、模型资产、Agent、训练与几何任务均绑定租户，Artifact 对象键按租户分区。
- 安全工作区：登录/首次初始化 UI、短期 Session Token、成员与 API Token 管理接口、角色及租户配额。
- 数据库持久化任务队列：幂等键、租约、心跳、重试、死信、取消与独立 Worker 进程，支持 API/Worker 分离部署。
- 通用训练接入：原生 SDK、Lightning、Hugging Face Trainer、Keras 回调，记录代码/数据集/环境/分布式 Rank 血缘并上传 Checkpoint。

- Parameter Lab 真实训练 Provider：Simulator、当前 Python、Conda/CUDA；支持 JSONL 流式指标、Checkpoint、中间 Artifact、取消、超时、并发限制和重启续跑。
- 本地专业几何环境：Manifold3D 网格布尔/修复/减面，以及 CadQuery/OpenCascade STEP/IGES B-Rep 圆角、倒角和三角化。
- 可选企业访问控制：Owner/Admin/Researcher/Viewer、PBKDF2 密码、哈希 API Token、租户配额、审计日志和 Fernet 加密凭据引用。
- 数据库迁移升级至 v13；v11 增加全业务租户边界，v12 增加持久任务租约，v13 增加训练血缘与资源遥测，旧 SQLite/PostgreSQL 可增量升级。

- P3 语义编辑 Agent：理解未知 Scene Graph，使用自然语言规划选择、变换、材质、布尔与修复；在写入前展示影响范围、风险、成本和预计时长，并保存每阶段决策与中间预览。
- Quality Agent 对预览执行真实网格质量门；不合格时自动追加修复并重跑，最终只有显式确认且版本未漂移时才原子写入新版本。
- P4 专业几何 Worker：内置快速预览与 Manifold、OpenCascade、外部 HTTPS Provider 解耦，支持 Checkpoint、超时、并发限制、抢占式取消和低清预览自动替换。
- 支持 PLY 网格/彩色点云直接归一化为可编辑 glTF；STEP/IGES 可作为 Raw 资产进入专业 Worker，输出 GLB/GLTF/OBJ/STL/PLY/STEP/IGES。
- 数据库迁移升级至 v8，新增 Agent Run、决策日志和专业几何 Job 持久化表。

- Run × 3D 统一时间轴：指标、Artifact、Embedding、点云、轨迹、向量场、仿真帧和模型 checkpoint 按 step 对齐；Parameter Lab 新 Run 自动进入带 Before/After 3D 叠加的综合对比。
- 资产生产工作台：项目、目录、搜索、标签、Raw/Edit/LOD/Release 筛选、批量更新、独立 Mesh/Material/Texture 组件版本、发布审批、归档恢复和安全 GC。
- 引用保护：Run、Scene、Scene Version 和 Generation 仍引用资产时拒绝删除；软删除经过宽限期后才允许回收对象存储。
- Python SDK 新增 Embedding 演化、点云、轨迹、向量场、仿真状态和模型资产绑定接口。
- 数据库迁移升级至 v7；CI 使用冻结的 pnpm 锁，生产镜像固定版本，并增加 PostgreSQL + MinIO Compose 冒烟、备份与恢复链路。

- 发布基线：GitHub Actions 同时执行 Python 测试、迁移门禁、插件契约、TypeScript 和 Vite 构建；Docker Compose 提供 Web、API、PostgreSQL 与 MinIO 一键部署。
- 多格式编辑导入：浏览器 Worker 后台读取 GLB、GLTF、OBJ、STL、`.bin` 与纹理依赖；OBJ/STL 会转成保留 Raw 血缘的自包含 GLB。
- 本地网格内核：Boolean Union/Subtract/Intersect 使用封闭体素网格求解，减面使用顶点聚类，Remesh/Repair 处理碎片、孔洞、法线和缺失 UV。
- 大网格操作队列：修改器在服务端后台执行，提供进度、取消、原子版本提交与重启孤儿任务回收。

- 可编辑语义资产：导入或生成的 GLB/GLTF 会解析为真实节点、网格、材质和边界数据；所有修改从 Raw 资产重放，Preview 不落盘，确认后生成新的 Release 资产与版本。
- 语义场景编辑器：多选、重命名、显隐、锁定、分组、复制/删除、Transform Gizmo、数值变换和 Before/After 叠加对比。
- 自然语言直接编辑真实 GLB：支持复合命令、语义选区、高亮预览、确认/取消，以及历史版本恢复。
- 修改器栈：Mirror、Array、Boolean、Subdivision、Decimate、Remesh、Normal Repair 与 Bevel，可启停、排序和删除；PBR 与 UV 重复使用 glTF 标准材质扩展保存。
- 本地质量门：检查退化面、边界、非流形边和连通分量；可清理碎片、补洞、修复法线并生成 LOD1/LOD2。
- 资产工作台：Raw → Edit → Release 血缘、操作/节点/材质/面数差异、版本恢复、LOD 预览和 GLB/GLTF 导出。
- 数据库迁移升级至 v7，发布验收包含 20 次连续编辑、落盘和导出且无挂起 Worker。

- 托管 Text-to-3D API：Meshy 为主 Provider、Tripo 为备用 Provider，本地 implicit worker 负责秒级低清预览；密钥只从服务端环境变量读取。
- 生成资产分为 Preview、Provider Raw、Release GLB 三层；发布前检查 GLB/OBJ 有效性、几何拓扑、法线、UV、PBR 材质和纹理，低分结果自动进入清洗、法线修复、UV 与 PBR 打包链路。
- 非破坏式 3D 编辑：80 步本地撤销/重做、服务端场景版本、多节点选择、分组、复制/删除、Transform 数值输入、World/Local、吸附、CSG 顺序和重拓扑/修复修改器。
- 自然语言 3D 编辑：中文/英文命令解析为结构化 Scene Operation；先显示受影响节点与高亮预览，确认后才写入场景版本，可继续撤销。

- AI 3D Studio：自然语言生成结构化参数模型，支持本地规划器与 OpenAI、DeepSeek、Kimi、Qwen 兼容接口。
- Prompt、Structure、Surface、Material、Quality 五阶段 Agent 独立执行、SSE 流式进度、失败重试、中间产物持久化，以及 Quality 自动退回重做。
- 每阶段记录尝试次数、Token、费用和耗时；在线 Structure 使用供应商实际 Token，本地确定性阶段明确标记为工作量估算且不计费。
- 覆盖无人机、机器人、相机、车辆、收音机、引擎、手表、珠宝、建筑、飞机、家具、道具、镜子、耳机、鞋、背包、家电、容器、面板和开放品类产品。
- 节点级 Transform Gizmo、CSG 并/差/交、倒角/圆角、UV 重复与纹理强度，以及 OBJ、GLTF、GLB 资产版本导出。
- 独立 Text-to-3D Worker 进程生成非参数化语义网格，支持任务进度、重启恢复、OBJ 资产落库和参数模型/语义网格切换预览。
- 可插拔 Meshy、Tripo、TRELLIS、Hunyuan3D、TripoSR 与通用外部 Text-to-3D Provider 契约；低清预览会被清理、法线修复、自动 UV、纹理烘焙后的 PBR GLB 自动替换。
- v1-v6 数据库增量迁移、Agent/Worker 取消与超时、GPU 并发和显存预算、checkpoint、孤儿任务恢复、场景操作历史及服务端 AI 凭据。
- 自然语言实验控制：直接修改参数、选择可视化、创建单次 Run、Sweep 或二维网格并自动进入对比视图。
- GLTF 多文件依赖、外部纹理映射、模型落地归一化、Dashboard 自由跨度调整和服务端参数快照。
- 队列任务进程重启恢复；数据库与对象存储健康检查。
- AI 计划可编译为 Standard / High / Ultra OBJ 网格，自动保存模型资产版本并下载；Ultra 模式可生成数万至数十万三角面。
- PostgreSQL、S3、Parquet 独立压力/故障验证脚本；本地对象存储采用 fsync + 原子替换。
- Three.js core/addons 与 React vendor 独立拆包，3D 插件继续按需加载。

- Schema 化实验参数：优化器、学习率、Dropout、Batch Size、Epoch 和随机种子。
- 启动、实时推进、停止和完成 Run。
- 实时准确率、训练损失、验证损失、GPU 利用率和运行日志。
- 多 Run 曲线对齐、参数差异和结果对比。
- 混淆矩阵、预测样本和可交互 3D embedding。
- Parameter Lab：Baseline、Before/After、参数快照、单参数 Sweep、二维网格、队列并发和成本/时长预估。
- 插件化可视化：自动发现时间序列、表格、图片网格、混淆矩阵、2D/3D embedding、JSON 和日志终端插件。
- 通用数据工作台：CSV/JSON/Parquet、字段识别、五类图表、联动筛选、拖拽 Dashboard、导出及 Spec 分享。
- 3D 工作台：模型资产版本、CAD 参数模型、Embedding 演化、点云/轨迹/向量场及仿真回放。
- SQLite / PostgreSQL 数据库适配，刷新后保留实验、指标、事件、作业和 Artifact 元数据。
- 本地对象存储 / S3 / MinIO Artifact 适配。
- REST + SSE 实时数据链路。
- 零依赖 Python SDK，支持批量上报、断线落盘、顺序补传与真实逻辑回归训练示例。
- 确定性训练模拟器；相同参数与种子可以复现实验趋势。

## 启动

打开两个终端：

```bash
# 终端 1：SQLite API + SSE
python backend/server.py

# 终端 2：前端
pnpm install
pnpm dev
```

然后访问 `http://127.0.0.1:5173`。运行真实 SDK 示例：

```bash
python examples/train_demo.py
```

生产构建：

```bash
pnpm build
python scripts/stress_adapters.py
```

完整生产栈：

```bash
docker compose up --build
# http://127.0.0.1:8080

# PostgreSQL + MinIO 备份 / 恢复
sh scripts/backup_restore.sh backup
sh scripts/backup_restore.sh restore
```

API 与 Worker 也可以独立运行：设置 `CLAWVISION_EMBEDDED_WORKERS=false` 后，分别启动
`python backend/server.py` 和 `python workers/task_worker.py`。发布前可运行
`pnpm test:release`；其中包含开启鉴权的 uvicorn 实时传输测试和独立 Worker 黑盒验收。
首次运行发布门禁前安装 `python -m pip install -r requirements-dev.txt -e ".[parquet]"`。
`pnpm test:e2e:production` 会启动隔离的 uvicorn 服务与生产构建预览，验证真实登录、空工作区、SDK Run、SSE 指标更新和 Viewer 写入拒绝。

## 运行模式

- Parameter Lab 计划提交给后端队列执行，Run、指标、事件与结果 Artifact 全部持久化；创建后自动进入 Baseline 对比。
- 外部训练通过 `sdk/clawvision` 上报，示例脚本执行真实梯度下降。
- 工作区默认只显示后端真实 Run；没有 Run 或诊断产物时显示空状态。后端连接异常时保留上次成功加载的数据，并明确提示连接状态。
- 首页的“查看演示实验”可显式打开模拟指标与诊断，演示模式有持续提示，可随时返回真实工作区。

### 托管 Text-to-3D API

在服务端环境中配置一个或两个 Provider；前端不会接收或传输 API Key：

```bash
# 主 Provider
TEXT3D_MESHY_API_KEY=msy_xxx

# 可选备用 Provider
TEXT3D_TRIPO_API_KEY=tsk_xxx

# 可选质量门槛与轮询间隔
TEXT3D_QUALITY_THRESHOLD=75
TEXT3D_API_POLL_SECONDS=2
```

启动后 AI 3D Studio 会优先选择已配置的 Meshy，其次选择 Tripo；未配置时仍可使用 `Local implicit preview`。模型生成内容会发送到所选第三方 Provider，请按数据合规要求决定是否提交敏感 Prompt 或参考图。测试套件使用本地模拟 API 验证异步提交、轮询和 GLB 下载，不会消耗第三方额度；真实供应商联调需自行提供有效 Key。

## 数据协议

核心定义在 `src/domain.ts`：

- `ExperimentParams`：一次运行的参数快照。
- `MetricPoint`：按 step 追加的时序指标。
- `ExperimentRun`：运行状态、指标、日志与诊断产物。
- `SamplePrediction`、`EmbeddingPoint`：可视化产物。

后端数据模型位于 `backend/database.py`，默认数据库为 `data/clawvision.db`，Artifact 默认写入 `data/objects`。通过 `.env.example` 可切换 PostgreSQL 与 S3/MinIO；P3 说明及当前边界见 `docs/p3.md`。

生产适配器压测、故障注入参数和 DeepSeek 实际联调记录见 `docs/production-validation.md`。

## Python SDK

```python
import clawvision

with clawvision.start_run("mnist", params={"learningRate": 0.001}) as run:
    run.log_param("batchSize", 64)
    run.log_metrics(1, train_loss=0.8, val_loss=0.9, accuracy=0.72)
    run.log_artifact("confusion", [[50, 2], [3, 45]], "confusion-matrix")
```

网络恢复后可显式补传：

```python
print(clawvision.sync_offline())
```

Lightning、Hugging Face Trainer 和 Keras 可直接使用
`LightningCallback`、`HuggingFaceCallback` 和 `KerasCallback`；分布式训练只由 rank 0
上报，代码、数据集、环境、父 Run 与 Checkpoint 恢复关系写入训练血缘。

## 视觉评估扩展

新增单标签分类工作台：冻结测试清单、完整预测校验、失败样本与场景分组、两个 Run 的修复/退化对比，提供 Python 客户端及报告导出。详见 [视觉评估与失败分析](docs/vision-evaluation.md)。当前评估用户上传的预测，自动重训列为后续阶段。

失败样本现在可关联固定 3D 资产版本，保存相机、灯光、材质和遮挡参数，生成固定种子的变体计划并预览、导出及创建新版本。详见 [失败驱动的 3D 场景计划](docs/vision-scenes.md)。

场景可提交 CPU 渲染任务，输出 RGB、可见及遮挡前掩码、边界框，按像素数、可见比例和裁剪筛选，再导出带 COCO、分类清单、图片哈希及血缘的 ZIP。任务支持取消、自动重试与断点恢复；所有产物受租户鉴权保护。详见 [场景渲染与合成标注](docs/vision-synthesis.md)。这提供合成训练材料，未自动重训或证明真实工业效果。

合成通过帧现在可登记为固定数据集版本。上传真实训练与独立测试图片版本，即可用相同条件运行 CPU 图像分类基线，对比“仅真实数据”和“真实＋合成数据”的实际预测，保存模型、Run、损失与修复/退化记录；支持逐轮断点恢复和已知数据泄漏检查。详见 [数据集版本与真实训练对比](docs/vision-training.md)。
