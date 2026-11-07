# 教学与科研可视化模块

原Vision代码已归并到ClawOS：前端在 `clawos/web/`，实验领域实现、SDK、worker及测试在 `clawos/visualization/`。正式入口仍为 `/academy/vision/`，统一网关为 `/api/vision/service/`，不再维护根目录的外置Vision项目。

教学主线保持文献方向、原文导读、来源过滤/检索对照、可视化观察、个人解释、教材图谱和教师复核的一体化关系。18种可视化插件及数据、3D、评估工具保留，绘图不是教学界面的附属装饰。

## 模块职责

- `backend/`：数据、实验、队列、3D、视觉评估和对象存储，使用限定模块导入。
- `worker.py`：由ClawOS通过私有管道握手启动；默认不加载模型，退出随所属进程清理。
- `sdk/clawvision/`：保留原SDK导入名，供训练回传与离线重放使用。
- `workers/`、`scripts/`：有界工作进程与模块验收/回放工具；不等于这些可选后端均已实测。
- `tests/`：模块协议和持久化回归。前端测试与构建工具统一位于 `clawos/web/`。

主应用数据与原导入回执不因源码位置变化而重建。实验数据仍使用 `CLAWVISION_DATA_DIR` / `CLAWVISION_OBJECT_DIR` 指向的隔离目录。可选数据/ML/CAD依赖保持独立，用户的本地模型与权重不搬入源码。

原Apache-2.0许可在模块根目录，初次导入的原始文件指纹见[来源说明](third-party/vision/README.md)。[领域设计参考](visualization)描述内部协议，不能当作第二套部署入口或当前完整生产验收。

验证：`python clawos/scripts/project.py test visualization`、`test web`、`build-web`。真实私有网关启动与拒绝直连可用 `clawos/scripts/vision_integration_acceptance.py` 在新隔离目录验证。模拟器、CPU机制实验、真实训练与真实教学收益分别记录。

SDK和保留的独立后端兼容测试描述原训练协议，不证明外部SDK已接入ClawOS团队身份。正式UI只走ClawOS私有网关；后续对外训练回传接口仍需单独验证身份与权限，不为方便迁移而开放私有worker。
