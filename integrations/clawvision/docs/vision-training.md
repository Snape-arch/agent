# 数据集版本与真实训练对比：第四阶段

入口：**视觉评估 → 已完成合成任务 → 登记合成数据集版本**，再进入 **6. 数据版本与真实训练对比**。上传真实训练图片清单与独立真实测试图片清单，选择三个固定版本并启动。界面显示训练进度、两个 Run、准确率、Macro F1、修复/退化及条件分组，可导出完整对比记录。

## 固定数据与模型

合成登记只收录通过筛选的 RGB，绑定已完成合成任务的摘要、源报告和场景摘要。真实图片按用户声明的 `train` 或 `test` 用途登记。每个版本包含标签、条件、规范化图片 SHA-256、原文件 SHA-256、解码像素摘要和私有对象地址。PNG/JPEG 解码后按 EXIF 方向转为 RGB，等比例缩至最长边 512，并存为 PNG；训练使用这些冻结后的图片。

版本接入已有 `datasets` / `dataset_versions`，样本索引存为 Parquet，DataLab 查询与版本接口可读取。专用图片清单保存完整内容与合成血缘；新版本更新数据集当前指针，旧版本不被覆盖。同样的登记请求返回已有版本；提供 `datasetId` 可创建新版本，来源和用途不能改变。全部被剔除的合成任务不能登记为空训练集。

CPU 算法 `cpu-rgb-softmax/1` 从 4×4 RGB 网格、RGB 均值和标准差提取 54 维特征，使用真实训练标签拟合带 L2 正则的多类 softmax。这是可复现的轻量图像分类基线，不能代替 CNN、检测器或工业模型。既有 PyTorch 随机数据演示训练器仍独立存在，本流程不使用它的随机样本或模拟指标。

两组实验分别是：

| 组 | 拟合数据 | 测试数据 |
| --- | --- | --- |
| 基线 | 固定真实训练版本 | 固定独立真实测试版本 |
| 候选 | 同一真实训练版本 + 固定合成训练版本 | 同一测试版本 |

两组固定算法、种子、学习率、L2 正则及轮数，各自仅使用本组训练图片拟合特征归一化参数。每轮保存实际交叉熵损失及模型权重断点；不使用测试集调参、早停或选最好轮次，完成固定轮数后才进行测试推理。生成两个独立 Run、模型 JSON 产物和两个同测试集评估记录，预测来源明确标记为实际 CPU 推理。对比允许改善、持平或退化，不预设合成数据有收益。

模型产物包含权重、偏置、归一化参数、类别、训练版本、样本数及环境信息，保存在 Run 的 artifacts。结果记录模型文件 SHA-256；断点包含校验摘要，续跑检查输入图片、版本和模型环境。源码摘要、NumPy/Pillow 版本变化会明确失败，可在当前环境创建新实验。

## 数据隔离与执行边界

真实训练集须覆盖 2–100 个类别；合成及测试标签须包含在这些类别中。训练与测试之间存在相同规范化图片、原文件或解码像素摘要时拒绝实验。测试版本若已用于合成场景的源报告，或源报告已知图片摘要与测试图片重合，也会拒绝。

这些检查无法识别近重复图、未知来源、同一零件的其他帧或相邻采集批次。用户仍需按零件、拍摄批次等划分独立测试数据。多次查看测试结果后再调参，会使该测试集参与设计；正式验证应另保留新的未参与设计真实样本。

每份真实版本最多 512 张，原图片单张最多 2 MiB、解码最多 4 百万像素，规范化图片总量最多 64 MiB。图像登记需要 NumPy、Pillow、PyArrow：`pip install -r requirements-vision.txt`。API 镜像和开发依赖也已加入。

实验使用持久队列，嵌入式与独立 Worker 均可执行；支持取消、最多 3 次自动尝试、逐轮断点恢复及显式重试。租约有效性在进度和结果提交前校验，旧 Worker 不能提交。每次尝试最多 180 秒、最多 200 轮；并发任务、Run 数量及存储受租户配额控制。完成的实验不可取消或重试修改。列表分页；Viewer 可读取版本、私有图片和对比记录，写入、生成和重试需研究员及以上角色与写作用域。

目前未提供图片版本或失败暂存对象垃圾回收。物体语义和“真实来源”由用户声明，本地验收使用人工流程样例，不能说明工业效果提升。PostgreSQL/S3 定义沿用现有存储接口，仍需对应部署环境实测。

## 导入与 SDK

页面可上传以下 JSON。`purpose` 为 `train` 或 `test`，可包含可选 `datasetId`；`conditions` 为最多 8 个字符串条件。

```json
{
  "name": "独立真实测试集",
  "purpose": "test",
  "samples": [
    {"id": "part-001", "label": "gear", "imageBase64": "PNG 或 JPEG 的 base64", "conditions": {"lighting": "low"}}
  ]
}
```

```python
import base64
import time
from pathlib import Path
from clawvision.evaluation import EvaluationClient

client = EvaluationClient(api_token="your-token")
def samples(records):
    return [{"id": sample_id, "label": label,
             "imageBase64": base64.b64encode(Path(filename).read_bytes()).decode()}
            for sample_id, label, filename in records]

real = client.create_image_dataset("真实训练集", samples(training_records), purpose="train")
test = client.create_image_dataset("独立真实测试集", samples(test_records), purpose="test")
synthetic = client.register_synthesis_dataset(completed_synthesis_job_id)
job = client.create_training_comparison(real["id"], synthetic["id"], test["id"],
                                      config={"seed": 42, "epochs": 50, "learningRate": 0.1, "regularization": 0.001})
while job["status"] in {"queued", "running"}:
    time.sleep(1)
    job = client.get_training_comparison(job["id"])
if job["status"] != "completed":
    raise RuntimeError(job.get("error") or job["status"])
Path("training-comparison.json").write_text(__import__("json").dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
```

| API | 用途 |
| --- | --- |
| POST /api/evaluation/image-datasets | 冻结真实图片版本，201 |
| POST /api/evaluation/synthesis/{id}/dataset-version | 登记通过筛选的合成版本，201 |
| GET /api/evaluation/image-versions | 分页图片版本摘要 |
| GET /api/evaluation/image-versions/{id} | 完整图片清单 |
| GET /api/evaluation/image-versions/{id}/images/{index} | 鉴权及哈希校验后的 PNG |
| POST /api/evaluation/experiments | 创建固定条件对比，202 |
| GET /api/evaluation/experiments | 分页对比列表 |
| GET /api/evaluation/experiments/{id} | 进度、输入版本、Run 与对比结果 |
| POST /api/evaluation/experiments/{id}/{cancel\|retry} | 取消或逐轮断点重试 |

迁移 22 增加图片版本绑定与训练对比记录。完整独立流程验收：`python scripts/vision_acceptance.py`，临时 ASGI 服务和独立 Worker 会真实拟合人工图片，不访问用户数据库。

## 本地验收记录（2026-10-08）

- `pnpm test:release` 通过：138 项 Python 测试、42 项前端测试，迁移 1–22、覆盖率门禁、独立 Worker、合成和实际训练流程、构建预算及短时稳定性检查均通过。
- 新服务覆盖率：CPU 模型 90.3%，图片版本服务 87.8%，训练对比服务 89.5%。验证包含版本不可变、真实梯度拟合和损失下降、独立测试推理、重复图片与已知设计泄漏拒绝、租户/角色隔离、逐轮恢复和旧租约提交阻断。
- 独立 ASGI 服务与 Worker 使用 4 张人工训练图、3 张合成图和 2 张独立人工测试图。两组各训练 12 轮，产生模型文件、Run 指标及同一测试集上的评估记录，准确率差值为 0。
- Playwright 浏览器验收通过：Owner 从完成任务登记合成版本，上传训练/测试 JSON，选择固定版本，启动并完成 24/24 轮，导出结果。导出文件核验了版本摘要、CPU 推理来源和同一测试集 ID。Viewer 可以查看和导出结果，上传与训练写操作入口不显示；390×844 视口无页面横向溢出。

以上图片是明确标注的人工流程样例，只验证系统完整性。尚未导入用户的真实工业图片，不能据此宣称合成数据提高了实际业务效果。
