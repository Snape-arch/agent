# 失败驱动的 3D 场景计划

这是视觉评估之后的第二阶段：把一个明确的分类失败与一个确定的 3D 资产版本关联，保存受控场景与可复现的变体清单。入口是 **视觉评估 → 失败分析 → 关联 3D 场景**。

## 使用流程

1. 导入固定测试集并上传真实 Run 的预测，选择失败样本，点击“关联 3D 场景”。
2. 选择资产版本。当前接受自包含 GLB、OBJ、STL，主文件 1 字节至 16 MB，不接受 sidecar 资源；其他格式可先通过已有资产工作流转换。
3. 确认资产代表该样本的真实标签。系统验证标签一致，但不自动识别模型语义。
4. 设置相机角度与距离、主光方向与强度、材质颜色/粗糙度/金属度、背景颜色和遮挡块尺寸，以及种子与变体数量（1–256）。最小值等于最大值表示固定参数。
5. 保存计划，选择变体，点击“加载 3D 预览”。预览只按保存参数显示，修改草稿不会改变保存版本。
6. “修改并创建新版本”载入旧参数，重新确认资产标签后保存新记录。可以改用另一个资产版本，旧计划保持原样。版本允许分支，父记录 ID 是准确的谱系标识。
7. 导出场景清单，用作后续渲染器的输入。

Viewer 可以查看计划、核验资产、切换预览与导出；创建需要研究员及以上角色和写权限。资产选择和计划列表使用服务端分页，预览代码与资产字节按需加载。

## 冻结与核验

计划保存报告 ID/摘要、测试集 ID/摘要、Run ID、失败样本 ID、真实与预测标签、原始条件、声明的图片哈希、资产 ID/版本/格式/实际字节数及实际 SHA-256。

创建时哈希来自对象存储中的实际主文件字节。预览接口重新核验文件哈希、版本与格式；不一致返回 409，文件不可用明确失败。原始图片仍是 URI 引用，其哈希为用户声明，未在此阶段读取或核验图片内容。

被引用的资产进入引用列表，普通删除、永久清理和垃圾回收会保护它；数据库外键也限制移除关联记录。场景没有覆盖更新或删除接口。

`digest` 是 `manifest` 的规范 JSON SHA-256：UTF-8、键排序、无多余空白、保留 Unicode、禁止非有限数值。名称、生成时间与谱系 ID 不参与场景内容摘要。导出包含记录元数据及完整 `manifest`，不是资产二进制归档；可通过有权限的 `/asset` 接口另行取得核验内容。对象存储遭人为改写后，清单可读但重放可能失败。

## 参数协议 `clawvision.scene-plan/1`

| 参数 | 允许范围 | 单位/含义 |
| --- | --- | --- |
| cameraAzimuth / lightAzimuth | -180–180 | 度，从 +Z 向 +X 为正 |
| cameraElevation / lightElevation | -80–80 | 度，相对于 XZ 平面 |
| cameraDistance | 1.5–10 | 归一化模型半径 |
| lightIntensity | 0–10 | Three.js 主光强度参数 |
| roughness / metalness | 0–1 | 标准 PBR 材质参数 |
| occluderSize | 0–1.5 | 遮挡方块边长，单位为模型半径 |

右手系、Y 向上。模型轴对齐包围盒导出包围球，球心移到原点、半径缩放为 1。相机面向原点、FOV 46°；目标渲染分辨率 512×512。白色环境光强度 0.7，白色方向主光距原点 5 个半径。所有网格覆盖为统一颜色的标准 PBR 材质；保留已有法线，缺失时计算顶点法线，使用 sRGB、ACESFilmic、曝光 1。当前显示静态模型，不采样动画或重现原始材质。

遮挡块颜色 #343434，面向相机，位于相机与原点的中点，再沿相机右向偏移 0.35 个半径。边长 0 时隐藏。**它不是图像遮挡面积百分比**，不保证遮挡后主体仍可见。

范围及输出取六位小数。`sha256-counter-v1` 对每个从 0 开始的变体索引及按名称排序的参数，计算 ASCII 字符串 `seed:index:parameterName` 的 SHA-256。前 8 字节视为大端无符号整数，除以 `2^64` 后映射至范围并舍入。固定种子与范围产生相同参数，增加数量保留原有前缀。**已保存的完整变体数组是重放依据**，无需在其他语言复刻舍入细节。

预览限制为 200 万顶点、2000 网格；不访问 GLB 外部资源。无效模型显示错误，不以占位模型替代。切换变体复用渲染器；关闭或离开页面释放资源。浏览器预览随显示像素比变化，不保证跨 GPU/渲染器像素一致。

## API 与 Python SDK

| API | 用途 |
| --- | --- |
| POST /api/evaluation/scenarios | 保存不可变计划，可指定 parentId |
| GET /api/evaluation/scenarios?reportId=…&page=1&pageSize=25 | 租户内计划摘要，pageSize 最大 100 |
| GET /api/evaluation/scenarios/{id} | 完整计划 |
| GET /api/evaluation/scenarios/{id}/export | 导出完整计划 |
| GET /api/evaluation/scenarios/{id}/asset | 核验后返回格式、哈希和 base64 主文件 |

```python
from clawvision.evaluation import EvaluationClient

client = EvaluationClient(api_token="your-token")
plan = client.create_scene_plan(
    "齿轮侧视角光照探索", report_id, failure_sample_id, asset_id, "gear",
    config={"seed": 42, "count": 24,
            "ranges": {"cameraAzimuth": [40, 100], "lightIntensity": [1, 4]}},
)
exported = client.export_scene_plan(plan["id"])
verified_asset = client.verified_scene_asset(plan["id"])
new_plan = client.create_scene_plan(
    plan["name"], report_id, failure_sample_id, asset_id, "gear",
    config={**plan["manifest"]["config"], "seed": 43}, parent_id=plan["id"],
)
```

## 当前边界

失败条件是人工规划线索，不能证明失败由某个参数导致。关联单个失败样本不会自动把整个分组映射成同一资产。变体清单还需要渲染、可见性与图像质量筛选、标注验证和训练数据划分。

第三阶段已接入 CPU 渲染、几何掩码与边界框、质量筛选和可恢复任务，见 [场景渲染与合成标注](vision-synthesis.md)。第四阶段支持将完成任务登记为 DataLab 图片版本，并与真实图片进行固定条件 CPU 训练对比，见 [数据集版本与真实训练对比](vision-training.md)。场景计划本身是不可变输入，生成产物和训练记录分别保存。不能根据参数计划直接宣称工业效果提升。

迁移 20 提供 SQLite 与 PostgreSQL 定义。本机验证以 SQLite 和本地对象存储为准，PostgreSQL/MinIO 需要在相应部署环境补充验证。

## 本地验收（2026-10-07）

- `pnpm test:release` 完整通过：116 项 Python 测试、32 项前端测试，迁移、覆盖率、规模/分析基准、20 条基础验收流程、独立 Worker、插件验证、构建预算与短时 soak。
- 场景服务覆盖率 100%；EvaluationClient 覆盖率 87.7%。新增检查覆盖真实文件哈希、确定采样、参数边界、正确样本拒绝、标签关联、租户/角色/作用域隔离、不可变版本、分页、资产删除及垃圾回收保护。
- Chrome 实测：从失败样本创建 3 个 GLB 变体，切换预览、下载清单并核验摘要；改用 OBJ 和新种子保存第二版，第一版摘要保持不变。GLB/OBJ 都显示实际模型，没有占位替代。
- 390px 视口与文档宽度均为 390px。Viewer 可以查看保存计划与核验预览，草稿表单、文件上传及修改入口不可见；页面无错误提示。
- 首屏预算 174,597 bytes（上限 190,000），Three.js 核心 546,800 bytes（上限 560,000）。预览模块独立延迟加载。
- 浏览器发现缺失法线的 GLB 在材质覆盖后明暗失真，补充法线回退后再次视觉核查；追加运行全部 32 项前端测试、9 项场景服务测试及构建预算检查，均通过。

浏览器验证使用独立临时数据库与明确标注的流程样例，不代表真实工业数据效果。
