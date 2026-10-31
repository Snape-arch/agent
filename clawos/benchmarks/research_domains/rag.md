# 检索增强生成（RAG）：文献分类、初稿与综述对照

三个AI方法方向的代表性阅读种子集，不是穷尽检索或2026年前沿全集。

先冻结初稿，再对照综述全文。选综述时已看到标题、摘要及搜索片段；不声称盲测。综述从不进入初稿证据集合。

整理者：助手。真实模型调用0次，独立真人评审0次。不是领域质量认证。

## 阅读准备

向量与相似度 → 编码器与序列生成 → 训练集、评测集和数据泄漏

## 初始8篇与分类

### 知识检索与预训练

- [REALM · 2020-02-10 · 2002.08909v1](https://arxiv.org/abs/2002.08909v1)：把检索器纳入语言模型预训练，讨论如何通过外部文本补充知识。
- [DPR · 2020-04-10 · 2004.04906v3](https://arxiv.org/abs/2004.04906v3)：用双编码器进行稠密段落检索；是检索组件研究，并不等于完整生成系统。

### 检索生成耦合

- [RAG · 2020-05-22 · 2005.11401v4](https://arxiv.org/abs/2005.11401v4)：结合参数化模型和外部非参数记忆，比较按序列和按词条件化的生成方式。
- [Fusion-in-Decoder · 2020-07-02 · 2007.01282v2](https://arxiv.org/abs/2007.01282v2)：围绕开放域问答，研究生成模型如何利用多条检索段落。
- [RETRO · 2021-12-08 · 2112.04426v3](https://arxiv.org/abs/2112.04426v3)：在语言建模中使用大规模外部检索库，研究参数规模与检索的配合。

### 查询改写

- [HyDE · 2022-12-20 · 2212.10496v1](https://arxiv.org/abs/2212.10496v1)：先生成假设文档再编码检索，关注不依赖相关性标注的稠密检索。

### 检索决策与评估

- [RAGAS · 2023-09-26 · 2309.15217v2](https://arxiv.org/abs/2309.15217v2)：提出无参考答案的RAG评估框架；自动评估不能替代人工事实核验。
- [Self-RAG · 2023-10-17 · 2310.11511v1](https://arxiv.org/abs/2310.11511v1)：通过反思标记学习按需检索及自我评价，连接检索决策与生成检查。

## 阅读与问题链条

箭头表示下述阅读/问题组织关系，不代表来源引用、方法继承或因果证明。

- 从找资料到用资料（阅读顺序）：[DPR](https://arxiv.org/abs/2004.04906v3)、[RAG](https://arxiv.org/abs/2005.11401v4)、[Fusion-in-Decoder](https://arxiv.org/abs/2007.01282v2)。先理解检索组件，再比较生成阶段如何融合材料。
- 从固定检索到决策与核查（问题演进）：[RAG](https://arxiv.org/abs/2005.11401v4)、[HyDE](https://arxiv.org/abs/2212.10496v1)、[Self-RAG](https://arxiv.org/abs/2310.11511v1)、[RAGAS](https://arxiv.org/abs/2309.15217v2)。分别考察查什么、何时查、如何评估；不是声称这些论文逐篇继承。
- 外部记忆与模型训练（并行路线）：[REALM](https://arxiv.org/abs/2002.08909v1)、[RETRO](https://arxiv.org/abs/2112.04426v3)。比较检索参与预训练和语言建模的方式。

## 冻结初稿

本组文献把RAG分为检索表示、检索与生成耦合、查询构造、决策及评估四层。REALM与DPR分别研究知识检索参与训练和段落检索，不能把检索器效果直接当作生成答案正确率。

依据：[REALM](https://arxiv.org/abs/2002.08909v1)、[DPR](https://arxiv.org/abs/2004.04906v3)

原始RAG将参数记忆与外部索引结合，FiD考察多段落生成，RETRO把检索扩展到语言建模。三者服务的任务和模型条件不同，不能依据各自摘要中的效果描述排出统一优劣。

依据：[RAG](https://arxiv.org/abs/2005.11401v4)、[Fusion-in-Decoder](https://arxiv.org/abs/2007.01282v2)、[RETRO](https://arxiv.org/abs/2112.04426v3)

HyDE、Self-RAG和RAGAS分别把注意力移到查询表示、按需检索与自我评价、系统评估。后续实验应固定语料和预算，分别测检索相关性、答案依据、拒答及成本；这些实验建议尚未执行。

依据：[HyDE](https://arxiv.org/abs/2212.10496v1)、[Self-RAG](https://arxiv.org/abs/2310.11511v1)、[RAGAS](https://arxiv.org/abs/2309.15217v2)

## 外部综述对照

[Retrieval-Augmented Generation for AI-Generated Content: A Survey](https://link.springer.com/article/10.1007/s41019-025-00335-5) · Data Science and Engineering · DOI 10.1007/s41019-025-00335-5

全文对照版本：publisher_open_full_text。正式发表记录与修订全文版本分别留证。

| 对照维度 | 初稿状态 | 初稿入口 | 对照后的补充 | 判断 |
| --- | --- | --- | --- | --- |
| 输入融合 | 有代表入口 | [RAG](https://arxiv.org/abs/2005.11401v4)、[Self-RAG](https://arxiv.org/abs/2310.11511v1) | 无 | 初稿有输入侧检索生成与按需检索入口。 |
| 隐表示融合 | 有代表入口 | [Fusion-in-Decoder](https://arxiv.org/abs/2007.01282v2)、[RETRO](https://arxiv.org/abs/2112.04426v3) | 无 | FiD与RETRO提供代表性入口，未穷尽变体。 |
| 概率层融合 | 初稿遗漏 | 无 | [kNN-LM](https://arxiv.org/abs/1911.00172v2) | 初稿缺少这一融合位置，补读kNN-LM；代表篇目不等于覆盖整类。 |
| 检索式解码加速 | 初稿遗漏 | 无 | [REST](https://arxiv.org/abs/2311.08252v2) | 初稿没有检索草稿解码，补读REST。 |
| 增强流水线 | 部分覆盖 | [HyDE](https://arxiv.org/abs/2212.10496v1)、[Self-RAG](https://arxiv.org/abs/2310.11511v1)、[RAGAS](https://arxiv.org/abs/2309.15217v2) | 无 | 已有查询、决策和评估，但生成器优化、结果改写等仍不完整。 |
| 跨模态应用 | 初稿范围外 | 无 | 无 | 初稿主要选文本任务，不能代表综述的代码、音频、图像等应用。 |

覆盖判断为助手拟定；综述分节作为外部参照，不能证明主张正确，也不计算领域准确率。

## 对照后新增2篇

对照后补充kNN-LM与REST：原先按流水线阶段分类，容易忽略概率融合与解码加速。它们与RAG/FiD是不同融合位置，不能排成单线升级史。

- [kNN-LM · 1911.00172v2](https://arxiv.org/abs/1911.00172v2)（概率层融合（补充））：插值语言模型和近邻模型的预测分布，补上初稿遗漏的概率层融合路线。
- [REST · 2311.08252v2](https://arxiv.org/abs/2311.08252v2)（检索式推测解码（补充））：检索草稿token以加速解码，补上初稿遗漏的检索替代部分生成路线。

## 初稿边界与后续扩展

以下保留初稿的范围记录。补读增加了代表入口，并未完整覆盖这些方向。

- 以文本开放域任务为主，未覆盖多模态RAG、图检索和行业部署。
- 尚无统一数据与预算下的复现比较；正文引用不自动证明推论。

## 可复核来源

以下保留捕获时间、摘要/规范化全文位置和SHA256；短引文见JSON及站内来源展开。

- REALM：2026-10-31T06:29:21.929388+00:00 / abstract[342:414] / text SHA256 5f8d5a3e009b05ab6987183a9be87c33f0e7afb9c40f8cbbf5585991ef39ed70 / raw SHA256 23016cdf4110fb99af8caa0fad38997b310045acb9555d233ac662896339bf88
- DPR：2026-10-31T06:29:26.543877+00:00 / abstract[303:406] / text SHA256 1d92ab3f358bc517ca0fd9d5169dfe04832dadfdb47fd8baf2488f9d9f76fbc2 / raw SHA256 769c22fd7b352a6d61add95a3116af5d85f4e1f540f9d52a6faa392999ed5aab
- RAG：2026-10-31T06:29:31.202577+00:00 / abstract[763:856] / text SHA256 766b22c091b5e3c8cdd736cd8c8d1529a5abe2f4895f6bd8f01df31f93851d55 / raw SHA256 8fe67b6e6cba908511e7a7bb688a6306cd15309ae9096b4e57970469dce23e55
- Fusion-in-Decoder：2026-10-31T06:29:35.887704+00:00 / abstract[623:710] / text SHA256 6a2761de45678f85877801c08576553c7ecdd6c60b7d679265b0ca4d2eab4452 / raw SHA256 9fdefe266e7b7e3015ceb91ac5403db2a4c42c4b6ff2e649fe10319ec1c1490a
- RETRO：2026-10-31T06:29:40.701235+00:00 / abstract[46:107] / text SHA256 a75657f4f84f1bd40bcaa00d8115d0d9f3f1a3edab86924d5d68a503dfce453a / raw SHA256 6c7a832050eaa1225c00015ba51fafaadee4da3e5146638f56f7b1351869467c
- HyDE：2026-10-31T06:29:45.397601+00:00 / abstract[483:515] / text SHA256 8e63a0b4e12a085d6ab549264f7c09ca28b834e7c53029f33f9abcad43045af8 / raw SHA256 7df8ca35a04609ba72c26b1b6f20cb884b4d6af1e48b460b4286f99e1a1220b8
- RAGAS：2026-10-31T06:29:52.979450+00:00 / abstract[64:155] / text SHA256 9c6df951d4376008bf1cb7f8b808167321fed949ab8d6491b3b156c98e1c37b0 / raw SHA256 51f0d7a686ebc9341f5596a066e858fe1c9d3132e82b95ad72559f48fb248d69
- Self-RAG：2026-10-31T06:29:57.571012+00:00 / abstract[796:835] / text SHA256 814a0385136a61001126f1bf731b56ffa68fd09e048d30a5d9272706cfdc64c4 / raw SHA256 6d3054cb5738cb8373d8b757eca3a5fba3f142304c8727e68476a5487272ca1c
- kNN-LM：2026-10-31T06:35:01.675506+00:00 / abstract[78:113] / text SHA256 404389459153c3f1de7955aa7538905a4c3bbac51b1db086e93bd5faf4e476cf / raw SHA256 172044a2910d1ef34e6573de0a727703fafafa1f68a0f2fc6292c640811f083d
- REST：2026-10-31T06:35:06.368867+00:00 / abstract[364:426] / text SHA256 cb7ec15517ac9ff3228292d7affbfdda41a3fa2e5dc9b7a06f42d7c3d3f41df9 / raw SHA256 44005954f3daa7fd0b2343f321c56c84fce5abbfbd91874f23f45b98ce20dc4c
- 综述§3.1.1 输入融合：2026-10-31T06:32:33.584560+00:00 / text[18187:18202] / raw SHA256 451f0d1df140c1295bb602442d5179ed9e486cec0996fb8be890ee9f5cf6f9c0
- 综述§3.1.2 隐表示融合：2026-10-31T06:32:33.584560+00:00 / text[21092:21123] / raw SHA256 451f0d1df140c1295bb602442d5179ed9e486cec0996fb8be890ee9f5cf6f9c0
- 综述§3.1.3 概率层融合：2026-10-31T06:32:33.584560+00:00 / text[24768:24783] / raw SHA256 451f0d1df140c1295bb602442d5179ed9e486cec0996fb8be890ee9f5cf6f9c0
- 综述§3.1.4 检索式解码加速：2026-10-31T06:32:33.584560+00:00 / text[26225:26240] / raw SHA256 451f0d1df140c1295bb602442d5179ed9e486cec0996fb8be890ee9f5cf6f9c0
- 综述§3.2 增强流水线：2026-10-31T06:32:33.584560+00:00 / text[27313:27329] / raw SHA256 451f0d1df140c1295bb602442d5179ed9e486cec0996fb8be890ee9f5cf6f9c0
- 综述§4 跨模态应用：2026-10-31T06:32:33.584560+00:00 / text[44175:44187] / raw SHA256 451f0d1df140c1295bb602442d5179ed9e486cec0996fb8be890ee9f5cf6f9c0
