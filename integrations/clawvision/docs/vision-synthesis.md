# 场景渲染与合成标注：第三阶段

已接通「失败报告 → 固定资产版本和场景计划 → 后台渲染 → 几何标注 → 筛选 → ZIP」。在视觉评估页面选择保存的场景，即可设置变体范围与质量阈值，启动任务、查看进度、取消或重试，并查看 RGB 和两种掩码。

## 输出与标注含义

每个变体输出 512×512 RGB PNG、主体可见区域二值 PNG、遮挡前区域二值 PNG。深度缓冲确定几何遮挡；可见边界框使用像素坐标 `x,y,width,height`，面积来自可见掩码。可见比例为画面内可见像素数 / 遮挡前像素数；遮挡前掩码也受画面裁剪，不能代表画面外完整物体。

分类标签来自用户确认的资产与真实标签关联，不自动判断模型是否真的代表该零件。几何标注不是人工真实图片标注。当前每份包只有一个主体类别；合并不同类别时，需要重映射类别、图片与标注 ID。

默认至少 64 个可见像素、可见比例至少 0.2，并剔除遮挡前主体触及图像边界的帧。剔除原因保存到清单。通过帧进入 COCO 和分类清单；剔除帧仍保留图片与标注以供审计。全部剔除的任务也能导出，但训练清单为空。

ZIP 内容：

| 路径 | 内容 |
| --- | --- |
| accepted/images、masks、amodal-masks | 通过筛选的 RGB 与掩码 |
| rejected/images、masks、amodal-masks | 被剔除的 RGB 与掩码 |
| annotations.json | COCO 格式可见边界框、面积、未压缩列优先 RLE 分割标注 |
| classification.json | 通过样本的标签与相对图片路径 |
| manifest.json | 源报告/测试清单/Run、资产版本及文件哈希、场景摘要、渲染实现与 NumPy 版本、参数、质量阈值和全部帧 |

`digest` 为规范化数据清单的 SHA-256，**不是 ZIP 文件哈希**。每张 PNG 有独立 SHA-256 和字节数；读取、续跑和导出均核验。已完成任务不可改写；同一任务重复导出的 ZIP 字节一致。参数或筛选阈值变化会创建另一任务；同一租户、场景和配置重复请求返回同一任务。不同执行尝试的对象路径不同，不承诺不同任务的 ZIP 字节相同。

## 渲染后端与运行边界

安装 `pip install -r requirements-synthesis.txt`，开发依赖和 API 镜像也包含 NumPy。后端执行 CPU 三角形光栅化，使用简化 Lambert/Blinn–Phong 光照、双面不透明网格及 ACES 近似色调映射。它与浏览器 Three.js PBR 预览存在明暗差异，不处理贴图、动画、骨骼、变形、压缩几何或外部资源。只接受自包含 GLB、OBJ、STL，其他格式先转换；不生成占位几何。

每批选择 1–64 个场景变体。网格上限 60,000 顶点、20,000 三角形；三角形数量×批次变体数最多 400,000。每次执行限时 180 秒，ZIP 总量限制 64 MiB。任务固定渲染器源码摘要和 NumPy 版本，环境变化会明确报错；可使用当前环境创建新任务。固定环境下相同输入可重放，不承诺跨系统浮点计算逐像素相同。

队列和任务原子入库；嵌入式模式自动重试、恢复过期租约和启动前的排队任务，独立 Worker 也处理 `synthesis` 类型。最多自动尝试 3 次；用户可对失败或取消任务显式重试。每帧成功提交后保存断点，续跑会先核验已保存文件，再补剩余帧。提交前检查租约归属及有效期，取消或旧 Worker 不能覆盖新结果。失败尝试可能留下未引用对象，仍计入存储额度，当前未提供合成对象垃圾回收。

读取列表、图片、掩码、清单与 ZIP 都受租户鉴权保护；Viewer 可以读取，写角色与作用域控制生成、取消和重试。列表、帧都分页；前端按选中样本请求图片，不批量载入整包。

## API 与 SDK

| API | 用途 |
| --- | --- |
| POST /api/evaluation/scenarios/{id}/renders | 创建任务，返回 202 |
| GET /api/evaluation/scenarios/{id}/renders | 分页任务列表 |
| GET /api/evaluation/synthesis/{id} | 状态、断点进度、通过/剔除数量 |
| GET /api/evaluation/synthesis/{id}/frames | 分页帧标注和带鉴权产物地址 |
| GET /api/evaluation/synthesis/{id}/frames/{index}/{image\|mask\|amodalMask} | 核验后的 PNG |
| GET /api/evaluation/synthesis/{id}/manifest | 已完成数据清单 |
| GET /api/evaluation/synthesis/{id}/export | 核验后下载 ZIP |
| POST /api/evaluation/synthesis/{id}/{cancel\|retry} | 取消或断点重试 |

```python
import time
from pathlib import Path
from clawvision.evaluation import EvaluationClient

client = EvaluationClient(api_token="your-token")
job = client.render_scene(scene_id, variant_indices=[0, 1, 2],
                          min_visible_pixels=64, min_visible_fraction=0.2)
while job["status"] in {"queued", "running"}:
    time.sleep(1)
    job = client.get_synthesis_job(job["id"])
if job["status"] != "completed":
    raise RuntimeError(job.get("error") or job["status"])
Path("synthetic.zip").write_bytes(client.download_synthesis_package(job["id"]))
frames = client.synthesis_frames(job["id"], page=1, page_size=25)
manifest = client.synthesis_manifest(job["id"])
```

合成包定位为训练材料。第四阶段已接入 [数据集版本与真实训练对比](vision-training.md)：完成任务后可登记通过帧，使用真实图片运行 CPU 基线对比。效果验证仍需保留未参与设计的真实样本，不根据流程样例宣称工业效果提升。

迁移 21 提供 SQLite/PostgreSQL 定义。本机验收使用 SQLite、本地对象存储和 CPU；PostgreSQL、S3/MinIO 部署仍需环境实测。独立完整流程验收：`python scripts/synthesis_acceptance.py`，使用临时 ASGI 服务、独立 Worker 和明确标记的流程样例。

## 本地验收（2026-10-07）

- `pnpm test:release` 完整通过：132 项 Python 测试、37 项前端测试，覆盖率、迁移、规模/分析基准、20 条基础流程、独立 Worker、合成验收、插件检查、生产构建预算与短时 soak。
- 合成服务覆盖率 95.6%，光栅渲染器 89.8%，EvaluationClient 90.7%。验证像素面积/边界框/RLE 与 PNG 一致、部分和完全遮挡、真实光照/相机变化、静态网格格式与变换、取消后的断点重试、租约隔离、配额、哈希篡改及租户/角色隔离。
- ASGI 与独立 Worker 实测部分遮挡批次通过 3 张，严格阈值批次剔除 3 张；训练清单仅包含通过帧，剔除产物仍保留。重复 ZIP 导出字节一致。
- Chrome 从保存场景启动生成，状态达到 3/3、通过 3 张；RGB 和可见掩码均实际加载为 512×512，ZIP 下载后核验所有 RGB 哈希和 COCO 图片清单。
- 移动端视口与文档宽度均为 390px，无页面错误提示。Viewer 可以加载图片并下载 ZIP，生成、取消、重试和修改场景入口均不可见。控制台仅有登录前鉴权探测及缺失 favicon 的既有请求错误，没有新增功能异常。
- 首屏脚本 174,716 bytes（上限 190,000），Three.js 核心 546,800 bytes（上限 560,000）。合成工作台随视觉评估页按需加载。

验收使用独立临时数据库和立方体流程样例，不代表工业零件真实效果，也不替代 PostgreSQL/S3 部署验证。
