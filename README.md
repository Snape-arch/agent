# ClawOS

面向个人学习、科研与执行的本地智能体工作台。教育主线把文献订阅、原文导读、教材知识图谱、可视化实验、个人解释和教师复核连接起来；办公、数据处理、文档协作、代码协作与自进化使用同一执行和治理层。

这是一个正在验证的产品原型。模拟器、CPU机制实验、真实模型结果与真实教学效果分别记录，不把有界测试当作生产或学习收益认证。

## 开始使用

Windows在仓库根运行：

```powershell
.\start_clawos.bat
```

工作台默认地址 `http://127.0.0.1:18790`；教学入口 `/academy/lab`，研究学习与可视化入口 `/academy/vision/`。应用依赖按[部署说明](clawos/deployment/README.md)准备。`start_clawos.bat --check-runtime`只检查运行环境；模型端点需要单独准备，仓库不包含权重。

## 一个产品源码树

```text
clawos/
  api/、services/        产品API与业务服务
  memoryos/             记忆、来源、版本与存储
  mtclaw/               内置路由、安全工具桥与适配器
  visualization/        实验、数据、3D、评估、SDK与隔离worker
  web/                  统一React前端源码与依赖锁
  static/               服务端页面和发布后的前端资源
  tests/、scripts/      回归、构建与开发命令
  deployment/           锁定运行时与部署配置
desktop/                同一应用的桌面壳与打包
docs/                   当前架构、开发指南与维护路线
```

MT和Vision均已归入内部模块，不再依赖根目录旁边的独立项目。保留MT路由服务及可视化私有worker的进程边界，用于工具协议、资源和依赖隔离；它们共用ClawOS产品入口。旧API和SDK名称、数据库、来源回执及模型目录保持兼容。

## 开发与验证

```powershell
python clawos/scripts/project.py check
python clawos/scripts/project.py test core
python clawos/scripts/project.py test router
python clawos/scripts/project.py test visualization
python clawos/scripts/project.py test web
python clawos/scripts/project.py build-web
```

`python`应指向已选定的应用/开发环境。前端依赖在 `clawos/web` 通过锁文件安装；模块测试依赖见 `clawos/requirements-modules-test.txt`。完整步骤见[开发指南](docs/DEVELOPMENT.md)。生成资源不能代替源码，权重、凭据、数据库、依赖缓存、日志与安装包不提交。

## 进一步了解

- [文档导航](docs/README.md)：只读当前说明，不必翻阅历史进度长文。
- [架构与权限边界](docs/ARCHITECTURE.md)：Agent、MemoryOS、Reflection、路由与教学可视化的关系。
- [维护性评估](docs/MAINTAINABILITY.md)：已整理内容、仍然过大的核心文件和下一步拆分顺序。
- 各模块的能力分、证据范围与交付验收见[项目全局评估](docs/PROJECT_ASSESSMENT.md)。
- [维护路线图](docs/ROADMAP.md)：真实验证与代码解耦优先级。
- [历史验收证据](clawos/benchmarks)：保留真实失败、时长和未验收项，不回写为全部通过。

MIT路由许可与Apache-2.0可视化许可随模块保留，原始来源记录见相应模块说明。上游来源、真实模型、真人教学、多设备无障碍和长时间多人负载的未验收项不会因仓库整理自动消失。
