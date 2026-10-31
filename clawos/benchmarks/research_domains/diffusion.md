# 扩散生成模型：文献分类、初稿与综述对照

三个AI方法方向的代表性阅读种子集，不是穷尽检索或2026年前沿全集。

先冻结初稿，再对照综述全文。选综述时已看到标题、摘要及搜索片段；不声称盲测。综述从不进入初稿证据集合。

整理者：助手。真实模型调用0次，独立真人评审0次。不是领域质量认证。

## 阅读准备

概率分布与噪声 → 梯度与分数函数 → 微分方程和数值采样

## 初始8篇与分类

### 概率扩散与分数建模

- [Diffusion Probabilistic Models · 2015-03-12 · 1503.03585v8](https://arxiv.org/abs/1503.03585v8)：利用逐步破坏和恢复数据的扩散过程建立生成模型。
- [Score Matching / NCSN · 2019-07-12 · 1907.05600v3](https://arxiv.org/abs/1907.05600v3)：学习数据分布的分数函数，并通过Langevin动力学生成样本。
- [DDPM · 2020-06-19 · 2006.11239v2](https://arxiv.org/abs/2006.11239v2)：展示去噪扩散概率模型，并讨论与去噪分数匹配的联系。

### 采样与连续时间

- [DDIM · 2020-10-06 · 2010.02502v4](https://arxiv.org/abs/2010.02502v4)：通过非马尔可夫过程，在保持训练目标关联的同时改变采样方式。
- [Score-based SDE · 2020-11-26 · 2011.13456v2](https://arxiv.org/abs/2011.13456v2)：用随机微分方程统一分数生成框架，并讨论概率流常微分方程。
- [DPM-Solver · 2022-06-02 · 2206.00927v3](https://arxiv.org/abs/2206.00927v3)：设计扩散常微分方程求解器，关注少步数高质量采样。

### 潜空间生成

- [Latent Diffusion · 2021-12-20 · 2112.10752v2](https://arxiv.org/abs/2112.10752v2)：在预训练自动编码器的潜空间中进行扩散，以降低高分辨率生成成本。

### 条件控制

- [ControlNet · 2023-02-10 · 2302.05543v3](https://arxiv.org/abs/2302.05543v3)：在预训练文本到图像扩散模型上学习空间条件控制。

## 阅读与问题链条

箭头表示下述阅读/问题组织关系，不代表来源引用、方法继承或因果证明。

- 生成基础的两条线（阅读顺序）：[Diffusion Probabilistic Models](https://arxiv.org/abs/1503.03585v8)、[Score Matching / NCSN](https://arxiv.org/abs/1907.05600v3)、[DDPM](https://arxiv.org/abs/2006.11239v2)、[Score-based SDE](https://arxiv.org/abs/2011.13456v2)。比较扩散概率建模和分数建模，再学习联系与统一表述。
- 推理成本与采样（问题演进）：[DDPM](https://arxiv.org/abs/2006.11239v2)、[DDIM](https://arxiv.org/abs/2010.02502v4)、[Score-based SDE](https://arxiv.org/abs/2011.13456v2)、[DPM-Solver](https://arxiv.org/abs/2206.00927v3)。训练过程、采样过程和求解器需要分开理解。
- 从像素成本到可控生成（阅读顺序）：[DDPM](https://arxiv.org/abs/2006.11239v2)、[Latent Diffusion](https://arxiv.org/abs/2112.10752v2)、[ControlNet](https://arxiv.org/abs/2302.05543v3)。从基础图像生成读到潜空间和空间条件控制，不声称逐篇因果继承。

### 作者原文明确描述的关系

这些是目标论文作者的表述，不等于独立考证或实验复现；与阅读顺序分开。

- [DDPM](https://arxiv.org/abs/2006.11239v2)、[DDIM](https://arxiv.org/abs/2010.02502v4)：作者称训练过程相同。依据见目标论文摘要，片段及版本位置保存在JSON。

## 冻结初稿

扩散概率模型和分数模型提供两条理解生成过程的入口，DDPM讨论去噪扩散与分数匹配的联系，SDE工作提供连续时间的统一框架。学习路径应解释目标和采样机制，不能仅按年份串成单一祖先树。

依据：[Diffusion Probabilistic Models](https://arxiv.org/abs/1503.03585v8)、[Score Matching / NCSN](https://arxiv.org/abs/1907.05600v3)、[DDPM](https://arxiv.org/abs/2006.11239v2)、[Score-based SDE](https://arxiv.org/abs/2011.13456v2)

采样效率与表示空间是不同维度。DDIM和DPM-Solver关注采样过程及求解效率，LDM把扩散移到潜空间，ControlNet关注空间条件控制；这些维度可以组合，但本组不声称其组合已在项目中复现。

依据：[DDIM](https://arxiv.org/abs/2010.02502v4)、[DPM-Solver](https://arxiv.org/abs/2206.00927v3)、[Latent Diffusion](https://arxiv.org/abs/2112.10752v2)、[ControlNet](https://arxiv.org/abs/2302.05543v3)

评价应同时说明数据、分辨率、采样步数、耗时、样本质量及条件服从度。不同数据和模型下的质量指标不能直接横比；训练成本、数据偏差和生成安全也需要专门材料，本轮尚未完成这些实验或风险评估。

依据：[DDPM](https://arxiv.org/abs/2006.11239v2)、[DPM-Solver](https://arxiv.org/abs/2206.00927v3)、[Latent Diffusion](https://arxiv.org/abs/2112.10752v2)、[ControlNet](https://arxiv.org/abs/2302.05543v3)

## 外部综述对照

[Diffusion Models: A Comprehensive Survey of Methods and Applications](https://arxiv.org/html/2209.00796v15) · ACM Computing Surveys · DOI 10.1145/3626235

全文对照版本：revised_arxiv_v15_not_publisher_version。正式发表记录与修订全文版本分别留证。

| 对照维度 | 初稿状态 | 初稿入口 | 对照后的补充 | 判断 |
| --- | --- | --- | --- | --- |
| 生成基础 | 有代表入口 | [Diffusion Probabilistic Models](https://arxiv.org/abs/1503.03585v8)、[Score Matching / NCSN](https://arxiv.org/abs/1907.05600v3)、[DDPM](https://arxiv.org/abs/2006.11239v2)、[Score-based SDE](https://arxiv.org/abs/2011.13456v2) | 无 | 扩散、分数和SDE入口已列入。 |
| 高效采样 | 部分覆盖 | [DDIM](https://arxiv.org/abs/2010.02502v4)、[DPM-Solver](https://arxiv.org/abs/2206.00927v3) | 无 | 已有免训练采样路线，未收集蒸馏等学习式采样。 |
| 训练与似然 | 部分覆盖 | [DDPM](https://arxiv.org/abs/2006.11239v2)、[Score-based SDE](https://arxiv.org/abs/2011.13456v2) | [Improved DDPM](https://arxiv.org/abs/2102.09672v1) | 初稿提到训练目标和SDE，但未专门组织似然改进，补读Improved DDPM。 |
| 特殊数据结构 | 初稿遗漏 | 无 | [D3PM](https://arxiv.org/abs/2107.03006v3) | 补读离散状态D3PM；不因此覆盖不变性、流形等所有结构。 |
| 潜空间 | 有代表入口 | [Latent Diffusion](https://arxiv.org/abs/2112.10752v2) | 无 | 已有LDM作为潜空间入口。 |
| 应用 | 部分覆盖 | [ControlNet](https://arxiv.org/abs/2302.05543v3)、[Latent Diffusion](https://arxiv.org/abs/2112.10752v2) | 无 | 有图像条件控制；视频、三维、时间序列及科学应用仍未系统整理。 |

覆盖判断为助手拟定；综述分节作为外部参照，不能证明主张正确，也不计算领域准确率。

## 对照后新增2篇

对照后补充Improved DDPM与D3PM：高效采样并不能覆盖训练与似然优化，连续图像也不能代表所有数据结构。视频、三维与科学应用仍需扩展，不能因新增两篇便宣称全面。

- [Improved DDPM · 2102.09672v1](https://arxiv.org/abs/2102.09672v1)（训练与似然（补充））：讨论简单修改、反向过程方差学习、似然及样本质量，补上初稿较弱的训练目标维度。
- [D3PM · 2107.03006v3](https://arxiv.org/abs/2107.03006v3)（离散结构（补充））：在离散状态空间设计噪声转移过程，补充初稿局限于连续图像的视角。

## 初稿边界与后续扩展

以下保留初稿的范围记录。补读增加了代表入口，并未完整覆盖这些方向。

- 以连续图像扩散为主，未系统纳入离散、音频、视频、三维和科学应用。
- 未覆盖全部引导方法、训练改进和最新流匹配；没有执行生成实验。

## 可复核来源

以下保留捕获时间、摘要/规范化全文位置和SHA256；短引文见JSON及站内来源展开。

- Diffusion Probabilistic Models：2026-10-31T06:30:47.667365+00:00 / abstract[533:598] / text SHA256 137e9eec744075e31a89053cc9e996de5697de33f58023e79c70499048cf75dd / raw SHA256 6c2b6e6e4c40d50051328f7ebe2b691cf8cfffac08a74ddde4fffe381f5a865e
- Score Matching / NCSN：2026-10-31T06:30:52.285555+00:00 / abstract[42:155] / text SHA256 4be6e02e2d87497cf893e6f8d3d96deabd938cc53f0c55eefaf7dfba50c2e2c9 / raw SHA256 d501cc1c517cbe4ba7d57db497fea893c96d8b027dde12681972498e24665356
- DDPM：2026-10-31T06:30:56.873047+00:00 / abstract[279:388] / text SHA256 3a50b647f9d733f159c2489601bde0857b17dd704fd742747319a93b28af77ea / raw SHA256 1d90b00e8fd3a70b202531e8548ca5008ce331daa8e89cd6266c91fb3de9d89b
- DDIM：2026-10-31T06:31:01.547307+00:00 / abstract[353:389] / text SHA256 6a175e159d1540d25a04e3ac7b9642f46c2c82aba58ff549cde9f1991bc5c104 / raw SHA256 83567a8987f955253d28b6a7d6daa13ab306c98fe4ea339ab77c2681a07dfd7a
- Score-based SDE：2026-10-31T06:31:06.107238+00:00 / abstract[700:819] / text SHA256 5efc36a634a45a0ac5e67c6a2063cb49a3a04ef8df4a5085fc33cbb6c3ef3dca / raw SHA256 2c6211c9c6cba67029ccef941e33a4446a02a6c235f0ba6d597cad2c402fcdf5
- Latent Diffusion：2026-10-31T06:31:10.752070+00:00 / abstract[613:682] / text SHA256 585143d800043bc39f24ae1e367299afbf7ae6c0d04dcb3c3531ab94cffea97c / raw SHA256 9dee697e0a7865ad6b3340a3bdc55b288c6e6cb03470f3515bd14e44a38f45f1
- DPM-Solver：2026-10-31T06:31:15.400034+00:00 / abstract[853:906] / text SHA256 eed591a5d98e40d2e06f4a8ddd8d5a08133144729fc5b480b56d05bec8d5df9a / raw SHA256 62d439b8a0a25805b9b7be197c9653d370ddaa776b9a60e0fb23410d33d33156
- ControlNet：2026-10-31T06:31:20.049925+00:00 / abstract[56:141] / text SHA256 7bc42744b4359b542460e3ca145fc802540ac94939f4c8be7761548ce074d69c / raw SHA256 fec234ea8655feb2ed3feed38f21d5bfae072fe8ab21c7777f6d86d0e9a3031a
- Improved DDPM：2026-10-31T06:35:20.730572+00:00 / abstract[211:276] / text SHA256 d63d11a7b07949deaf965f428977b85717f134bdfb0c18ba63dad825cc00c1ba / raw SHA256 ad8732a376dcb662092b248ca1723d44dc66346e00e22c9eb877c273e11ecf06
- D3PM：2026-10-31T06:35:25.362602+00:00 / abstract[235:285] / text SHA256 fc6a5be656feab7be8fcde7b6abb259ee187718daa8a7e5a925f868b84dc9f32 / raw SHA256 d7fb3036be23823bdfdccb576e4900b0a6d9eadc53134548779386037d7e1e1a
- 综述§2 生成基础：2026-10-31T06:32:47.721606+00:00 / text[347:378] / raw SHA256 c8e9e28809f7c5f08776c18411f98cc0e64a7b2e800cd4ec868027ce48e8a099
- 综述§3 高效采样：2026-10-31T06:32:47.721606+00:00 / text[548:566] / raw SHA256 c8e9e28809f7c5f08776c18411f98cc0e64a7b2e800cd4ec868027ce48e8a099
- 综述§4 训练与似然：2026-10-31T06:32:47.721606+00:00 / text[768:787] / raw SHA256 c8e9e28809f7c5f08776c18411f98cc0e64a7b2e800cd4ec868027ce48e8a099
- 综述§5 特殊数据结构：2026-10-31T06:32:47.721606+00:00 / text[916:934] / raw SHA256 c8e9e28809f7c5f08776c18411f98cc0e64a7b2e800cd4ec868027ce48e8a099
- 综述§8 潜空间：2026-10-31T06:32:47.721606+00:00 / text[2666:2688] / raw SHA256 c8e9e28809f7c5f08776c18411f98cc0e64a7b2e800cd4ec868027ce48e8a099
- 综述§7 应用：2026-10-31T06:32:47.721606+00:00 / text[56:68] / raw SHA256 c8e9e28809f7c5f08776c18411f98cc0e64a7b2e800cd4ec868027ce48e8a099
