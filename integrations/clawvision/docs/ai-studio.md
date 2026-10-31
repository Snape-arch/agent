# AI 3D Studio 与自然语言实验控制

## 两条自然语言链路

### AI 3D Studio

`Prompt → 持久化 Agent Run → 分阶段产物与流式进度 → Quality 反馈重做 → 参数化/语义网格场景 → 节点编辑与 CSG → GLTF/GLB 资产版本`

内置本地规划器不需要 API Key。在线模式支持 OpenAI、DeepSeek、Kimi 与 Qwen 的 OpenAI-compatible Chat Completions 接口。API Key 只随当前请求发送，不写入数据库或浏览器持久化存储；服务端只允许预设 Provider 主机，避免任意 URL 请求。

StudioPlan 包含：

- 模型模板与名称。
- scale、complexity、curveStrength、connectionDensity、color、material 参数。
- 可渲染部件、尺寸、位置、旋转、形状和材质。
- Prompt、Structure、Surface、Material、Quality Agent 执行记录。
- 质量分数、检查项和警告。

当前模板覆盖无人机、机器人、相机、车辆、收音机、引擎、手表、珠宝、建筑、飞机、家具、道具、镜子、耳机、鞋、背包、家电、容器和面板；未命中模板的描述进入开放品类产品组合器。生成后可以实时修改整体参数，也可以用 Transform Gizmo 移动、旋转、缩放单个节点，设置倒角、CSG 运算、UV 重复和纹理强度。保存同一 Generation 会形成新版本，历史版本可以恢复并作为 Before/After 叠加基线。

### Agent Pipeline

- 五个 Agent 阶段分别写入 `agent_stages`，每次重试单独留痕并通过 SSE 推送。
- 每阶段 JSON 中间产物写入对象存储并登记到 `agent_artifacts`。
- Quality 低于阈值时自动创建新 cycle，退回 Structure、Surface、Material 后再次验收。
- 服务重启会恢复本地 Pipeline；在线 Pipeline 因 API Key 不持久化而安全失败，用户需要重新提交。
- 在线供应商响应的 Token 作为实际用量计费；本地阶段只显示 estimated-workload，不计供应商费用。

### 独立 Text-to-3D Worker

`POST /api/studio/text-to-3d` 会启动隔离的 Python 子进程，以 JSON Lines 输出进度，通过隐式场和 marching tetrahedra 生成非参数化三角网格。结果保存为可版本化 OBJ 资产。该本地 Worker 是确定性的语义网格后端，不是需要 GPU 的扩散式高精度生成模型；后续可以保持 API 契约不变，将 Worker 替换为独立 GPU 服务。

### 自然语言实验控制

实验命令解析为 `ExperimentAiPlan`：

- `patch`：对当前参数的修改。
- `params`：应用后的完整参数快照。
- `configs`：单次、Sweep 或二维网格展开后的配置集合。
- `visualization`：建议的 VisualizationSpec。
- `execute`：命令是否要求立即创建实验。

示例：

```text
把学习率改成 0.0005，Batch Size 改成 128，显示损失曲线并运行
学习率从 0.0001 到 0.01 扫描 5 个点并运行
二维网格：学习率从 0.0001 到 0.001 3 个点，batch size 32,64,128
显示 embedding 演化，关闭混合精度
```

包含“运行、开始、创建实验、执行”等动词时，计划会直接提交到持久化 Run 队列并进入 Baseline 对比视图；否则只应用参数和生成 Before/After 预测预览，用户可以再确认创建 Run。

## API

- `POST /api/ai/interpret`：解释实验或 3D Prompt。
- `GET /api/studio/templates`：模板列表。
- `GET/POST /api/studio/generations`：模型生成历史与版本。
- `POST /api/studio/generations/:id/feedback`：生成反馈。
- `POST /api/studio/validate`：模型计划验证。
- `POST /api/studio/mesh`：将 StudioPlan 编译为 Standard / High / Ultra OBJ，写入模型资产版本并返回下载内容。
- `POST /api/studio/export`：导出并版本化 OBJ、GLTF 或 GLB；存在 CSG 标记时使用服务端 SDF 网格编译器。
- `POST /api/studio/agent-runs`、`GET /api/studio/agent-runs/:id`：创建和查询持久化 Agent Pipeline。
- `GET /api/studio/agent-runs/:id/stream`：Agent 阶段、重试、产物和统计 SSE。
- `POST /api/studio/text-to-3d`、`GET /api/studio/text-to-3d/:id`：创建和查询语义网格 Worker 任务。
- `GET /api/studio/text-to-3d/:id/stream`：Worker 进度 SSE。
- `GET/POST /api/parameter-snapshots`：服务端参数快照。

## 模型资产补强

`POST /api/model-assets` 支持主模型 base64 与 `resources[]`。GLTF Loader 使用受控 LoadingManager 将 `.bin`、PNG、JPEG、WebP、KTX2 等依赖解析为内存 Data URL。上传界面可以一次选择主文件和依赖文件，也可以为当前模型覆盖纹理。

AI Studio 的“生成并下载 OBJ”会在服务端把球体、胶囊、圆柱、环面和组合部件细分成真实三角网格。Ultra 模式使用更高曲面细分，设置 50 万面安全上限；生成结果进入 `model_assets` 版本链，之后保存 Studio Generation 时会关联该资产。

在线 Provider 的 Key 仅存在于当前 React 状态和当前 HTTPS 请求。服务端不持久化 Key、不开启任意 Endpoint，并对模型返回结果做 Schema 白名单合并和 3D 计划校验。

## 验收

```bash
python -m unittest discover -s tests -v
python scripts/stress_adapters.py
pnpm run verify:plugins
pnpm run build
```

测试覆盖中文实验命令、Sweep、二维网格、全部显式与开放品类、Agent 重试和 Quality 重做、CSG、GLTF/GLB、非参数化语义网格、SQLite/PostgreSQL Schema、PostgreSQL 参数适配、本地对象存储和 S3 合约。
