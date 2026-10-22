# AI Academy 学习工作室：产品范围与验收

## 目标与交付

把“知识层展示页”变成可持续使用的学习入口：目标选择 → 先修路径 → 讲解与教材 → 实验 → 笔记 → 定向测验 → 错题复习。

| 学习需求 | 已实现 |
| --- | --- |
| 不知道先学什么 | 应用工程、模型原理、论文复现三条路径；20/40/60 分钟每日预算；基于先修与测验状态推荐下一步 |
| 图谱只有造型 | 15 个课程知识点与同一套测验数据绑定；WebGL 球形着色、透视、旋转、缩放、先修高亮、搜索、筛选、展开和列表视图 |
| 教材只有书名 | 6 个官方/开放资源入口，中文选读说明；9 个知识点提供经过核验的章节直达链接 |
| 读完论文不会用 | Attention、RAG、LoRA、ReAct 四篇导读；阅读顺序、关键追问、小实验和五字段论文卡片 |
| 学习缺少实践 | 15 个练习及完成标准；向量、因果 Attention、LoRA 三个无需模型的页面内计算实验 |
| 学习记录不连贯 | SQLite 保存路径、阅读笔记、论文卡片、项目清单；Markdown 导出；保留原课程和阅读器/代码工作区入口 |
| 进度缺乏依据 | 阅读、自查、测验证据区分显示；30 道定向题；先修解锁、错题和重复答案控制复用既有学习服务 |

## 验收结果（2026-09-12）

- 全仓 Python 回归：567/567，286.356 秒。随后补充章节直链、计算实验、错误提示和布局收尾；最终教育相关 Python 复测 61/61，Node 计算实验测试 3/3。
- Python 编译与前端 JavaScript 语法检查通过。
- 浏览器使用实际 HTTP 路由和隔离 SQLite：启用路径、进入 Python 学习室、保存中文笔记、低分作答、重新作答清除同题错误、进入复习队列通过。
- 论文卡片与项目自查：保存后刷新，内容及勾选仍在。
- Attention 实验：因果掩码开启时未来权重为零，关闭后恢复非零权重；数学单测检查归一化。
- 默认桌面与 390×844 布局已目视检查；图谱搜索 LoRA 返回两个相关知识点；列表显示先修关系。窄屏存在标签密集情况，可使用列表、搜索或展开视图。
- 运行隔离预览：`python clawos/scripts/learning_preview.py`，访问 `http://127.0.0.1:18897/academy`。其数据库位于忽略的 `output/learning-preview` 会话目录，退出后清理，不使用正式学习数据库。

## 数据与上线边界

- 工作室课程按稳定 key 幂等初始化；只有用户选择路径才启用该课程。切换路径复用同一 enrollment，原有课程记录保留。
- 记录 API 仅接受明确类型与已知课程/论文/项目 ID。阅读勾选、笔记和自查清单不会写入掌握证据。
- 评分仍是概念覆盖与推理表达规则，不是完整语义评分，也不是学习效果的独立验证。项目清单是个人自查，不能替代实际代码运行或评审。
- 教材原文由官方平台提供；本地没有完整教材副本，也不分发模型权重。资源核验时间为 2026-09-10/11，并非持续监控。
- 本次未重启正式 ClawOS 服务或迁移用户数据。正式服务加载新 Python 路由需要重启，前端资产带版本参数以避免旧缓存。
- 后续内容工作：继续细化测验评分与反例、扩展视觉/多模态等专题，并用真实学习者任务验证路径和内容深度。不要把本次本地功能验收称为“顶级教育产品”或独立学习成效证明。

## 资源来源

- [Python 中文教程](https://docs.python.org/zh-cn/3/tutorial/)
- [动手学深度学习](https://zh-v2.d2l.ai/)
- [PyTorch 基础教程](https://docs.pytorch.org/tutorials/beginner/basics/intro.html)
- [scikit-learn 入门](https://scikit-learn.org/stable/getting_started.html)
- [Hugging Face LLM Course](https://huggingface.co/learn/llm-course/chapter1/1)
- [Hugging Face Agents Course](https://huggingface.co/learn/agents-course/unit0/introduction)
- [Attention](https://arxiv.org/abs/1706.03762)、[RAG](https://arxiv.org/abs/2005.11401)、[LoRA](https://arxiv.org/abs/2106.09685)、[ReAct](https://arxiv.org/abs/2210.03629)
