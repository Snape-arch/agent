# 视觉评估与失败分析：第一阶段

第二阶段已接入资产版本关联、受控场景、变体计划与 3D 预览，见 [失败驱动的场景计划](vision-scenes.md)。

第三阶段已接通可恢复 CPU 渲染、几何标注、质量筛选与 ZIP，见 [场景渲染与合成标注](vision-synthesis.md)。

第四阶段已接入固定图片版本、实际 CPU 分类拟合与独立测试推理对比，见 [数据集版本与真实训练对比](vision-training.md)。

本阶段实现单标签分类的「固定测试清单 → Run 预测 → 场景分组 → 配对对比」。它是工业视觉数据修复闭环的评估基础，不执行模型推理、合成数据生成或自动重训。

## 工作台使用

1. 启动 API 和前端，登录后进入左侧 **视觉评估**。空工作区需要先在运行概览创建 Run，或通过 Python SDK 记录实际实验。
2. 导入测试集 JSON。每个样本包含唯一 `id`、真实 `label`，可附带字符串形式的 `conditions`，如 `lighting=reflection`、`angle=side`、`batch=batch-01`。连续值应先分桶。
3. 选择一个真实 Run，上传预测 JSON 数组，或含 `predictions` 数组的对象。文件中的每条记录包含 `sampleId`、预测 `label` 和可选 `confidence`。Run 与测试集以当前界面选择为准。
4. 查看错误率、Macro F1、各类 Precision/Recall、混淆计数以及场景分组。点击分组可分页查看其中的失败样本。
5. 在评估记录中分别选择基线和候选。它们必须属于两个不同 Run，且使用同一个测试集 ID。对比显示修复、新增退化、两次都正确和两次都错误的样本数，以及各场景错误率变化。
6. 可导出测试清单、单份评估报告及配对对比报告。所有记录按租户隔离；Viewer 可以读取与对比，写入要求研究员以上角色和 `write` scope。

`examples/vision_evaluation/` 包含四个手工构造的流程样本及两份预测，不代表真实模型表现。样例中准确率由 50% 到 75%，修复 2 个样本，同时新增 1 个退化；`angle=front` 分组错误率上升 50 个百分点。样例只在用户明确导入后进入工作区。

## 数据与证据边界

- 测试清单和评估记录不提供修改或覆盖接口。修正标签应创建新测试清单，并重新评估两个 Run。
- 测试清单 SHA-256 包含任务、类别、规范化样本及来源数据版本 ID；样本、类别顺序及展示名称不影响摘要。同内容的两次导入仍是不同测试集 ID，不能直接配对。
- `imageUri` 仅作为引用记录并展示，不在服务端抓取，也不自动下载外部图片。冻结的是清单和标签，不是外部图片字节。可提供 `contentHash`（SHA-256）供推理端核验，当前服务不核验该图片哈希。
- 可通过 API/SDK 提供 `datasetVersionId`，服务校验版本归属并保存来源引用；它不验证手工清单是否实际从该版本提取。
- 每份评估保存上传时 Run 名称、来源、状态、参数及 revision 快照。可选 `modelArtifactId` 必须属于此 Run；这是产物引用，当前不证明上传预测由该模型执行，也不冻结模型字节。
- 必须恰好覆盖全部样本。缺失、额外、重复样本 ID、类别表以外的预测标签和非法置信度会拒绝整次上传，不保存部分结果。
- 未提供 `classes` 时从真实标签推导；如果模型可能预测测试清单中没有出现的类别，须显式声明完整类别表。
- 类别 Precision 或 Recall 的分母为零时显示空值；Macro F1 对真实或预测出现过的类别取均值，两者均未出现的类别不纳入。没有预测置信度时显示空值。
- 场景分组可重叠，错误数不能跨分组相加；分组关联不等于因果结论。准确率与错误率差异以百分点表示。
- 第一版最多 5,000 个样本、100 个类别，每个样本 8 个条件维度，整个清单 200 个条件组。工作台 JSON 文件最多 8 MB。集合与失败样本从数据库分页读取，`pageSize` 上限 100。

真实试点应独立维护训练与测试数据，按零件实体或采集批次划分，避免相似视角泄漏；固定训练预算并重复实验。当前服务不会自动检测训练/测试泄漏，也不会凭一次提升给出发布通过结论。

## Python 调用

安装项目 SDK 后，可接入现有推理脚本：

```python
import json
from pathlib import Path
from clawvision.evaluation import EvaluationClient

client = EvaluationClient(base_url="http://127.0.0.1:8787")
# 认证读取 CLAWVISION_API_TOKEN，也可传 api_token。
manifest = json.loads(Path("test-set.json").read_text(encoding="utf-8"))
test_set = client.create_test_set(manifest["name"], manifest["samples"], classes=manifest.get("classes"))
baseline = client.evaluate(test_set["id"], baseline_run_id, baseline_predictions)
candidate = client.evaluate(test_set["id"], candidate_run_id, candidate_predictions)
comparison = client.compare(baseline["id"], candidate["id"])
Path("comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
```

`baseline_run_id` / `candidate_run_id` 来自实际实验，两个 predictions 列表来自用户的推理结果。SDK 调用失败会显式抛错，不使用指标批次的离线队列，也不会把未上传的数据显示为已完成评估。

## API 与存储

OpenAPI：`GET /api/openapi.json`。新增接口：

| 方法 | 路径 | 功能 |
|---|---|---|
| GET / POST | `/api/evaluation/test-sets` | 分页列表 / 创建冻结清单 |
| GET | `/api/evaluation/test-sets/{id}` | 清单元数据 |
| GET | `/api/evaluation/test-sets/{id}/export` | 完整清单导出 |
| GET / POST | `/api/evaluation/reports` | 分页列表 / 创建评估；列表支持 `testSetId` |
| GET | `/api/evaluation/reports/{id}` | 指标与来源快照 |
| GET | `/api/evaluation/reports/{id}/cases` | 分页样本，支持 `failuresOnly`、`dimension` + `value` |
| GET | `/api/evaluation/compare?baselineId=...&candidateId=...` | 配对对比 |

数据库 migration 19 新增五张表，SQLite 和 PostgreSQL 使用相同业务结构；不改已有 Run 历史或数据集对象。新增模块按需加载，沿用既有首页包体积门槛。

## 后续阶段

先用真实工业样本验证分组和对比是否帮助用户定位问题。随后关联 CAD/3D 资产及场景参数，接入一个实际渲染与标注后端，再比较原始数据、普通合成数据和针对失败条件生成的数据。检测、分割、定位任务需要各自的标注协议与评估器，不应套用当前分类指标。

## 本地验收（2026-10-07）

- Python 全量 105 项测试、前端 28 项测试通过。评估服务覆盖率 98.6%，评估 SDK 79.6%，已加入各自 85% / 75% 的覆盖率门槛。
- 新库安装、旧库升级和重复迁移通过，版本 1–19 连续，旧数据保留；完整预测校验、跨租户拒绝、Viewer/Scope 权限及 105 条失败样本分页有自动测试。
- 生产构建和包体积门槛通过：首页应用脚本 174,589 bytes，视觉评估作为独立模块按需加载。
- Playwright CLI 在隔离的认证 uvicorn、SQLite、本地对象存储与生产预览上验证了文件导入、场景筛选、配对对比和下载。浏览器导出的报告与预期修复 2 / 退化 1 一致；390px 窄屏整页宽度仍为 390px；Viewer 没有上传控件，并成功完成只读对比。
- 既有 quick scale、analytics、20 条基础验收流程、独立 Worker、插件结构与短时 soak 检查通过。
- PostgreSQL 迁移路径已接入，当前本地验收未运行真实 PostgreSQL/MinIO 环境。样例是手工预测，尚无真实工业模型提升的证据。
