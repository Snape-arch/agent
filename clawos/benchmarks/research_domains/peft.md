# 参数高效微调（PEFT）：文献分类、初稿与综述对照

三个AI方法方向的代表性阅读种子集，不是穷尽检索或2026年前沿全集。

先冻结初稿，再对照综述全文。选综述时已看到标题、摘要及搜索片段；不声称盲测。综述从不进入初稿证据集合。

整理者：助手。真实模型调用0次，独立真人评审0次。不是领域质量认证。

## 阅读准备

梯度与优化器 → Transformer权重矩阵 → 显存、精度和量化

## 初始8篇与分类

### 新增适配参数

- [Adapters · 2019-02-02 · 1902.00751v2](https://arxiv.org/abs/1902.00751v2)：冻结原网络，为各任务添加小型适配模块。

### 软提示

- [Prefix-Tuning · 2021-01-01 · 2101.00190v1](https://arxiv.org/abs/2101.00190v1)：冻结语言模型，通过可训练连续前缀适配生成任务。
- [Prompt Tuning · 2021-04-18 · 2104.08691v2](https://arxiv.org/abs/2104.08691v2)：学习输入端软提示，并研究模型规模对适配效果的影响。

### 选择性更新与缩放

- [BitFit · 2021-06-18 · 2106.10199v5](https://arxiv.org/abs/2106.10199v5)：仅更新偏置参数，考察极少参数更新的适配能力。
- [IA³ · 2022-05-11 · 2205.05638v2](https://arxiv.org/abs/2205.05638v2)：通过学习向量缩放内部激活，探索少样本高效适配。

### 低秩与资源优化

- [LoRA · 2021-06-17 · 2106.09685v2](https://arxiv.org/abs/2106.09685v2)：冻结基础权重，以可训练低秩矩阵表示任务更新。
- [AdaLoRA · 2023-03-18 · 2303.10512v2](https://arxiv.org/abs/2303.10512v2)：围绕重要性自适应分配低秩更新的参数预算。
- [QLoRA · 2023-05-23 · 2305.14314v1](https://arxiv.org/abs/2305.14314v1)：结合冻结的量化基础模型与低秩适配，降低微调内存需求。

## 阅读与问题链条

箭头表示下述阅读/问题组织关系，不代表来源引用、方法继承或因果证明。

- 适配位置的不同选择（并行路线）：[Adapters](https://arxiv.org/abs/1902.00751v2)、[Prefix-Tuning](https://arxiv.org/abs/2101.00190v1)、[Prompt Tuning](https://arxiv.org/abs/2104.08691v2)、[BitFit](https://arxiv.org/abs/2106.10199v5)、[IA³](https://arxiv.org/abs/2205.05638v2)。比较添加模块、学习提示、选择参数与缩放激活；不是线性替代史。
- 低秩更新、预算和显存（问题演进）：[LoRA](https://arxiv.org/abs/2106.09685v2)、[AdaLoRA](https://arxiv.org/abs/2303.10512v2)、[QLoRA](https://arxiv.org/abs/2305.14314v1)。依次学习更新表示、参数预算和量化内存；AdaLoRA不是QLoRA的已证实直接前身。

### 作者原文明确描述的关系

这些是目标论文作者的表述，不等于独立考证或实验复现；与阅读顺序分开。

- [Prefix-Tuning](https://arxiv.org/abs/2101.00190v1)、[Prompt Tuning](https://arxiv.org/abs/2104.08691v2)：作者称其为简化形式。依据见目标论文摘要，片段及版本位置保存在JSON。
- [Prompt Tuning](https://arxiv.org/abs/2104.08691v2)、[SPoT](https://arxiv.org/abs/2110.07904v2)：作者称其基于前者。依据见目标论文摘要，片段及版本位置保存在JSON。

## 冻结初稿

PEFT的共同问题是避免为每个任务维护和训练整套基础权重。本组从新增模块、连续提示、选择性更新及低秩更新四个入口比较适配位置；方法分类是阅读组织，不是唯一标准。

依据：[Adapters](https://arxiv.org/abs/1902.00751v2)、[Prefix-Tuning](https://arxiv.org/abs/2101.00190v1)、[Prompt Tuning](https://arxiv.org/abs/2104.08691v2)、[BitFit](https://arxiv.org/abs/2106.10199v5)、[LoRA](https://arxiv.org/abs/2106.09685v2)、[IA³](https://arxiv.org/abs/2205.05638v2)

低秩更新不等于量化。LoRA研究权重更新的低秩表示，AdaLoRA研究预算如何分配，QLoRA则将量化基础模型与适配器结合。可训练参数少不能单独推出端到端显存、吞吐和精度都更优。

依据：[LoRA](https://arxiv.org/abs/2106.09685v2)、[AdaLoRA](https://arxiv.org/abs/2303.10512v2)、[QLoRA](https://arxiv.org/abs/2305.14314v1)

合理比较应固定基础模型、任务、数据、训练步数和硬件，同时报告可训练参数、峰值显存、训练时间及任务指标。不同规模和任务上的作者结果不能直接拼成统一排行榜；以上比较计划尚未实测。

依据：[Prompt Tuning](https://arxiv.org/abs/2104.08691v2)、[LoRA](https://arxiv.org/abs/2106.09685v2)、[QLoRA](https://arxiv.org/abs/2305.14314v1)

## 外部综述对照

[Parameter-efficient fine-tuning in large language models: a survey of methodologies](https://link.springer.com/article/10.1007/s10462-025-11236-4) · Artificial Intelligence Review · DOI 10.1007/s10462-025-11236-4

全文对照版本：publisher_open_full_text。正式发表记录与修订全文版本分别留证。

| 对照维度 | 初稿状态 | 初稿入口 | 对照后的补充 | 判断 |
| --- | --- | --- | --- | --- |
| 新增参数 | 有代表入口 | [Adapters](https://arxiv.org/abs/1902.00751v2)、[Prefix-Tuning](https://arxiv.org/abs/2101.00190v1)、[Prompt Tuning](https://arxiv.org/abs/2104.08691v2)、[IA³](https://arxiv.org/abs/2205.05638v2) | 无 | 初稿把软提示单列作教学入口，综述把它纳入新增参数，属于分类粒度差异。 |
| 重参数化 | 有代表入口 | [LoRA](https://arxiv.org/abs/2106.09685v2)、[AdaLoRA](https://arxiv.org/abs/2303.10512v2) | 无 | 已有低秩表示与预算分配，不能代表全部重参数化方法。 |
| 选择性更新 | 有代表入口 | [BitFit](https://arxiv.org/abs/2106.10199v5) | 无 | 偏置更新是代表样本；稀疏结构搜索仍欠缺。 |
| 混合方法 | 初稿遗漏 | 无 | [UniPELT](https://arxiv.org/abs/2110.07577v3) | 补读UniPELT，避免把单种适配方式视为互斥选择。 |
| 量化适配 | 部分覆盖 | [QLoRA](https://arxiv.org/abs/2305.14314v1) | 无 | 已有QLoRA，但量化技术不能压缩成一篇方法的全部结论。 |
| 任务间迁移 | 初稿遗漏 | 无 | [SPoT](https://arxiv.org/abs/2110.07904v2) | 补读SPoT作为提示迁移入口，多任务领域仍有大量未覆盖工作。 |

覆盖判断为助手拟定；综述分节作为外部参照，不能证明主张正确，也不计算领域准确率。

## 对照后新增2篇

对照后补充UniPELT与SPoT：除适配参数放在哪里，还需要看多种方法如何组合，以及任务间怎样迁移。初稿四类是阅读入口，不能冒充综述的完整分类。

- [UniPELT · 2110.07577v3](https://arxiv.org/abs/2110.07577v3)（混合适配（补充））：结合多种适配子模块并学习门控，补充初稿缺少的混合方法。
- [SPoT · 2110.07904v2](https://arxiv.org/abs/2110.07904v2)（任务间迁移（补充））：先在源任务学习软提示，再用于目标任务初始化，补充跨任务迁移路线。

## 初稿边界与后续扩展

以下保留初稿的范围记录。补读增加了代表入口，并未完整覆盖这些方向。

- 主要覆盖NLP/语言模型，未系统收集视觉、多模态与多任务组合。
- 未覆盖稀疏结构搜索、混合方法和完整系统优化，不能声称PEFT全集。

## 可复核来源

以下保留捕获时间、摘要/规范化全文位置和SHA256；短引文见JSON及站内来源展开。

- Adapters：2026-10-31T06:30:02.282030+00:00 / abstract[236:276] / text SHA256 070f807eb0ec4dc53acc94a0312b7c87ad0819934405257ded0e1740f8e70e94 / raw SHA256 c7b22c9e2b133957b2f9ce72b5d0f50392e4080019321e802d86b970795946e2
- Prefix-Tuning：2026-10-31T06:30:06.873335+00:00 / abstract[350:443] / text SHA256 c439a42b68ccd1c88d79f42e27fd6b5831885e935d575f42c207df52a9a1bdf7 / raw SHA256 ff29832454e0bf85d20ecf235f6f3b0658e162e4dd07c65447c640a8dab76c92
- Prompt Tuning：2026-10-31T06:30:14.377091+00:00 / abstract[79:138] / text SHA256 ccf20fd92d81ab5c8203d1608844ee815538549d9df5dfa24f9ebf41dcb7dfd3 / raw SHA256 3edfe725f5d52fabf0cf9e40d4e978f56d9c56d98e66266f8cbc29b1cae0ce99
- BitFit：2026-10-31T06:30:18.964544+00:00 / abstract[54:127] / text SHA256 d8e55d4a10251ef84560abe404e330943849580ee856fdc12744dead8f2818ac / raw SHA256 160a987f524737fcd9512f5d08ce4dedcc1933a5469a625bc6a65408c7cdccfe
- LoRA：2026-10-31T06:30:23.535450+00:00 / abstract[459:546] / text SHA256 b52ab87811b316fa0170a1eb0340f0c484463f708f9fb763f17d3c48e5a8e247 / raw SHA256 70bb70b4fd6d41b8a0f53fc5148017bf6ef5b73acba822027397f861aee135c6
- IA³：2026-10-31T06:30:28.127638+00:00 / abstract[825:862] / text SHA256 e65d1d2724240cce3015e3a01df7ddfaba136c308af21e15e839d341c3e1f799 / raw SHA256 7fe83c8f69e82beb613dad31f72ade42aa5bf0da42b89518dfd3ce9d5e5e840d
- AdaLoRA：2026-10-31T06:30:32.693570+00:00 / abstract[713:812] / text SHA256 c3fe322b6212a220272ea3a93128639bf6be1f5cd82d46595b5c79f8a5ac595f / raw SHA256 17fc4ccac44f3cddce89b14ce2e7c482a84c2358fa6ebf057553197a0c841a15
- QLoRA：2026-10-31T06:30:39.618266+00:00 / abstract[203:310] / text SHA256 6272079be29d11ca8f943e1c3e9ebb29ac5113ef009a0e85a6fb8b4fc88723ce / raw SHA256 6388775a19989a46dfb02d9e30c0021d32095f6edd44d7f248181de8b517ccc5
- UniPELT：2026-10-31T06:35:11.032326+00:00 / abstract[560:609] / text SHA256 30d4365fab338958bce69f39e53e6ae91513b14c1817b8fd1ec671b22d72a571 / raw SHA256 a1035a95509e2338344f8a2edb4785fd526193a26f1ebc45e6e4ee8ad333c28a
- SPoT：2026-10-31T06:35:15.891462+00:00 / abstract[392:441] / text SHA256 681ab453f3cd467c1527d9a5e848ab328a2f490624ba5b6d31a89ee4bf2b5af0 / raw SHA256 b0ed027cb9fe449216d86b24197f99214b5b23b3e23a4ac3e70a907b9fb1d3d5
- 综述§3.1 新增参数：2026-10-31T06:32:40.615035+00:00 / text[51841:51854] / raw SHA256 d59a985dd538df8be0ce8fc973aaffd063241d9f52a8fe5d2c31d33dbf13c834
- 综述§3.2 重参数化：2026-10-31T06:32:40.615035+00:00 / text[51961:51981] / raw SHA256 d59a985dd538df8be0ce8fc973aaffd063241d9f52a8fe5d2c31d33dbf13c834
- 综述§3.3 选择性更新：2026-10-31T06:32:40.615035+00:00 / text[52129:52143] / raw SHA256 d59a985dd538df8be0ce8fc973aaffd063241d9f52a8fe5d2c31d33dbf13c834
- 综述§3.4 混合方法：2026-10-31T06:32:40.615035+00:00 / text[52259:52270] / raw SHA256 d59a985dd538df8be0ce8fc973aaffd063241d9f52a8fe5d2c31d33dbf13c834
- 综述§3.5 量化适配：2026-10-31T06:32:40.615035+00:00 / text[52398:52415] / raw SHA256 d59a985dd538df8be0ce8fc973aaffd063241d9f52a8fe5d2c31d33dbf13c834
- 综述§3.6 任务间迁移：2026-10-31T06:32:40.615035+00:00 / text[52472:52487] / raw SHA256 d59a985dd538df8be0ce8fc973aaffd063241d9f52a8fe5d2c31d33dbf13c834
