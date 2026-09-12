"""Authored learning paths and reading guides. Links checked 2026-09-10.

Teaching prompts are original; third-party books remain on publisher sites.
"""

COURSE_KEY = "clawos-ai-studio-v1"
RESOURCES = [
    dict(id="python", title="Python 官方中文教程", kind="官方教程", language="中文", url="https://docs.python.org/zh-cn/3/tutorial/", scope="第 3–5 章入门、控制流、数据结构；第 8 章异常", cost="免费在线"),
    dict(id="d2l", title="动手学深度学习", kind="开放教材", language="中文", url="https://zh-v2.d2l.ai/", scope="按知识点选读：预备知识 → 线性网络 → 注意力机制", cost="免费在线"),
    dict(id="torch", title="PyTorch · Learn the Basics", kind="可运行教程", language="英文", url="https://docs.pytorch.org/tutorials/beginner/basics/intro.html", scope="Tensors、Datasets、Autograd、Optimization、Save & Load", cost="免费在线"),
    dict(id="sklearn", title="scikit-learn · Getting Started", kind="官方教程", language="英文", url="https://scikit-learn.org/stable/getting_started.html", scope="拟合与预测、预处理、Pipeline、模型评估", cost="免费在线"),
    dict(id="hf", title="Hugging Face · LLM Course", kind="系统课程", language="英文", url="https://huggingface.co/learn/llm-course/chapter1/1", scope="先读第 1 章模型家族，再读 tokenizer、数据与微调章节", cost="免费在线"),
    dict(id="agents", title="Hugging Face · Agents Course", kind="系统课程", language="英文", url="https://huggingface.co/learn/agents-course/unit0/introduction", scope="入门要求 → Agent 基础 → 工具与实践任务", cost="免费在线"),
]


def lesson(key, title, domain, prerequisites, minutes, why, explanation, exercise, checks, resource, section, concepts):
    return dict(id=key, title=title, domain=domain, prerequisites=prerequisites,
                minutes=minutes, why=why, explanation=explanation, exercise=exercise,
                checks=checks, resource=resource, section=section, concepts=concepts)


LESSONS = [
    lesson("python", "Python 与数据处理", "基础", [], 35,
        "把一份原始资料变成可复现的数据输入，是所有 AI 项目的第一步。",
        "把读取、清洗、统计拆成小函数。输入输出约定比脚本长度更重要：空行如何处理，编码出错是否跳过，重复数据如何识别，都应有明确规则。保留原文件，并为清洗结果记录来源。",
        "用标准库读取一个包含空行和重复项的 CSV，按 ID 去重，输出有效行数和错误行号。",
        ["空文件返回 0 条而不是崩溃", "重复运行输出一致", "错误数据有原因和行号"], "python", "第 4 章函数、第 5 章数据结构、第 7 章输入输出", ["函数", "异常", "数据"]),
    lesson("linear", "向量与矩阵", "基础", [], 30,
        "理解向量形状，才能解释 embedding 和注意力的计算过程。",
        "向量表示对象的特征，矩阵表示一批对象或线性变换。先写清每个轴的含义，再做乘法。余弦相似度比较方向，不直接代表事实相关性；相似文本仍可能给出相反结论。",
        "手算两个三维向量的点积与余弦相似度，再用 Python 检查。给零向量设计明确处理规则。",
        ["写出矩阵乘法前后的形状", "解释归一化的作用", "给出相似度高但结论相反的例子"], "d2l", "第 2 章：线性代数", ["向量", "矩阵", "相似度"]),
    lesson("statistics", "概率与实验设计", "基础", [], 35,
        "避免把一次偶然提高当成模型能力提升。",
        "训练集用于拟合，验证集用于选择方案，测试集用于最终评估。若反复根据测试结果改方案，测试集也参与了选择。记录样本来源、分组方法和随机种子，并观察不同子群的错误。",
        "给 100 条问答设计训练、验证、测试划分；同一原文生成的问题必须在同一分组。",
        ["说明数据泄漏的路径", "保留不参与调参的测试集", "报告样本数与错误类型"], "d2l", "第 2 章：概率；第 4 章：模型选择", ["训练", "测试", "泄漏"]),
    lesson("ml", "机器学习基线", "模型", ["python", "statistics"], 45,
        "先建立简单基线，才能判断复杂模型是否值得。",
        "先定义预测目标与错误成本，再选指标。预处理也会学习数据分布，必须只在训练集拟合。用 Pipeline 将预处理和模型绑在一起，比较多数类基线与一个简单分类器。",
        "用 sklearn 自带数据集训练分类器，报告混淆矩阵，并找出 3 个预测失败样本。",
        ["预处理没有看到测试数据", "比较多数类基线", "解释精确率和召回率的取舍"], "sklearn", "Pipeline 与模型评估", ["基线", "训练", "评估"]),
    lesson("neural", "神经网络与梯度", "模型", ["linear", "python"], 50,
        "能追踪一次参数更新，才能有效排查训练失败。",
        "前向计算得到预测，损失衡量偏差，反向传播计算梯度，优化器更新参数。梯度累积与更新是两件事；忘记清零会改变训练行为。先让模型拟合一个很小的数据集，再扩大规模。",
        "训练两层网络拟合小数据集，分别记录损失、梯度范数和学习率；故意使用过大学习率比较结果。",
        ["说明清零、反传、更新的顺序", "能在小样本上降低损失", "保存配置和曲线"], "torch", "Autograd 与 Optimization", ["梯度", "损失", "参数"]),
    lesson("token", "Token 与语言模型", "模型", ["python"], 30,
        "理解上下文成本、分词差异与生成的不确定性。",
        "语言模型根据已有 token 预测后续 token。字符数不等于 token 数；中文、代码和特殊符号的切分也不同。截断可能丢失关键条件，因此应显式记录输入长度与截断位置。",
        "选同一句中文、代码和英文，观察 tokenizer 输出；构造一个截断后失去否定词的例子。",
        ["区分 token 与字符", "记录输入输出 token 长度", "说明生成流畅不等于事实正确"], "hf", "第 1 章模型家族与 tokenizer 章节", ["token", "上下文", "预测"]),
    lesson("attention", "Attention 的计算", "模型", ["linear", "neural"], 45,
        "从计算过程理解哪些信息被聚合，而不是背公式。",
        "Query 与 Key 的匹配分数经过缩放和 softmax，得到对 Value 的加权系数。因果掩码阻止当前位置访问未来 token。权重展示信息聚合方式，但不能自动解释模型的全部因果机制。",
        "用 3 个 token 手算一次缩放点积注意力，加入因果 mask，画出前后的权重矩阵。",
        ["标注 Q、K、V 的形状", "每行权重和为 1", "未来位置的权重为 0"], "d2l", "第 10 章：注意力评分函数与自注意力", ["query", "key", "value"]),
    lesson("transformer", "Transformer 结构", "模型", ["attention", "token"], 50,
        "把注意力、位置和残差连接成一个可理解的模型。",
        "Transformer 块把注意力与逐位置前馈网络组合，通过残差和归一化改善训练。位置编码让模型获得顺序信息。原论文的编码器—解码器结构与常见 decoder-only 语言模型要分开理解。",
        "画出一个 decoder 块，给每个箭头标出张量形状；解释去掉因果 mask 会导致什么训练问题。",
        ["区分 encoder 与 decoder", "标明位置、残差和归一化", "解释训练与自回归推理的区别"], "d2l", "第 10.7 节 Transformer", ["注意力", "位置", "残差"]),
    lesson("embedding", "Embedding 与检索", "应用", ["linear", "python"], 40,
        "让系统在自己的资料中找到真正有用的证据。",
        "将片段编码成向量并检索近邻，只解决了候选召回。切分粒度、标题上下文和原文定位会影响可用性。分别记录是否找到正确片段以及答案是否忠于片段，避免混用两类指标。",
        "选 10 篇短文，人工写 10 个问题及正确片段；比较两种切分长度的 Recall@3。",
        ["保留文档与片段 ID", "问题集独立于切分调试", "分析至少一个未召回案例"], "hf", "语义搜索与 embeddings 章节", ["检索", "向量", "片段"]),
    lesson("rag", "有证据的 RAG", "应用", ["embedding", "token"], 50,
        "把引用、拒答与错误分析做进知识助手。",
        "RAG 将检索结果交给生成器。召回失败、片段过期和模型误读会产生不同错误。要求引用具体片段，并在证据不足时返回不知道。原始 RAG 论文的联合训练方法不等同于所有现代检索拼接应用。",
        "做一个 10 问资料助手：至少包含 2 个资料中没有答案的问题，保存检索片段、回答与引用。",
        ["引用能回到原文", "无证据问题能拒答", "分别统计检索错误与生成错误"], "hf", "语义搜索章节；配合 RAG 原论文导读", ["检索", "证据", "拒答"]),
    lesson("evaluation", "评估与回归", "应用", ["statistics", "token"], 40,
        "用稳定的测试集决定改动是否真的有效。",
        "为准确性、引用、延迟和成本分别制定评价规则。保存每次运行的输入、输出和配置。总体平均分可能掩盖少数重要场景的退化，因此还要按错误类型和任务子集比较。",
        "建立 20 条固定问题的评测表，比较两个提示词版本，并检查新版本每一条退化案例。",
        ["固定测试样本与配置", "报告改善和退化数量", "对无答案问题单独计分"], "sklearn", "模型评估：把独立评估原则迁移到生成任务", ["评估", "回归", "测试"]),
    lesson("agent", "工具调用与 Agent", "应用", ["rag", "evaluation"], 55,
        "让工具行动有边界、有结果检查，也有停止条件。",
        "Agent 循环包含选择行动、执行工具、读取观察和决定下一步。工具返回成功不等于任务完成。限制步数、预算与权限；对超时、空结果和部分成功设计可恢复的处理方式。",
        "实现一个最多 5 步的资料搜索助手，模拟工具超时与空结果，保存逐步行动和观察。",
        ["失败有停止条件", "每次行动对应真实观察", "写操作有明确权限边界"], "agents", "Unit 1：Agent 与工具循环", ["工具", "观察", "停止"]),
    lesson("finetune", "LoRA 与微调", "研究", ["transformer", "statistics"], 55,
        "判断何时应调整模型，而不只是不断增加提示词。",
        "LoRA 固定原有权重，用低秩矩阵表示更新量，减少可训练参数。它不保证每个任务都优于全量微调。先排查数据质量与评估划分，再比较不同 rank 的效果、显存与时间。",
        "不下载大模型：先计算一个 4096×4096 线性层在 rank=8 与 16 时的可训练参数量，设计对照实验表。",
        ["区分总参数与可训练参数", "报告 rank 改变的成本", "验证集不含训练重复样本"], "hf", "微调章节；配合 LoRA 论文导读", ["低秩", "参数", "微调"]),
    lesson("reproduce", "论文实验复现", "研究", ["evaluation", "transformer"], 60,
        "把读懂的主张变成可以被别人检查的实验。",
        "先写可检验的主张，再找相应表格、基线与实验条件。缩小规模的机制验证可以有价值，但应明确它不是原始指标的完整复现。记录数据、版本、随机种子与所有偏离原文之处。",
        "从 Attention 或 LoRA 导读中选一项小实验，先写预期趋势，再运行并记录不符合预期的结果。",
        ["主张对应原文位置", "基线与实验只有一个关键差异", "列出与原论文不同的条件"], "d2l", "选读相关章节的实验与习题", ["基线", "复现", "条件"]),
    lesson("deployment", "推理与交付", "应用", ["agent"], 45,
        "从能运行一次走向可观察、可回退的服务。",
        "把模型响应包装成服务后，还需要并发限制、超时、日志和版本回退。对敏感原文和密钥进行最少记录。比较首 token 延迟和完整响应延迟，不能用单次最快结果代表体验。",
        "为资料助手写一份交付检查表，并模拟超时、缺少配置和检索不可用三个故障。",
        ["用户能看懂失败原因", "不在日志中泄漏密钥", "记录版本及回退步骤"], "agents", "实践任务：在自己的项目中补充运行边界", ["超时", "日志", "回退"]),
]

TRACKS = [
    dict(id="builder", title="AI 应用工程师", subtitle="做出可引用、可评估的知识助手", goal="deployment", accent="mint", project="knowledge-assistant"),
    dict(id="foundation", title="模型原理学习者", subtitle="从矩阵到能解释 Transformer", goal="transformer", accent="blue", project="attention-lab"),
    dict(id="research", title="论文与复现进阶", subtitle="从读结论到验证实验主张", goal="reproduce", extra=["finetune"], accent="peach", project="paper-reproduction"),
]

# Deep links are checked independently from the parent library entry.
CHAPTER_URLS = {
    "python": "https://docs.python.org/zh-cn/3/tutorial/inputoutput.html",
    "linear": "https://zh-v2.d2l.ai/chapter_preliminaries/linear-algebra.html",
    "statistics": "https://zh-v2.d2l.ai/chapter_preliminaries/probability.html",
    "attention": "https://zh-v2.d2l.ai/chapter_attention-mechanisms/attention-scoring-functions.html",
    "transformer": "https://zh-v2.d2l.ai/chapter_attention-mechanisms/transformer.html",
    "token": "https://huggingface.co/learn/llm-course/chapter6/1",
    "embedding": "https://huggingface.co/learn/llm-course/chapter5/6",
    "rag": "https://huggingface.co/learn/llm-course/chapter5/6",
    "agent": "https://huggingface.co/learn/agents-course/unit1/what-are-agents",
}
for _lesson in LESSONS:
    _lesson["chapter_url"] = CHAPTER_URLS.get(_lesson["id"], next(r["url"] for r in RESOURCES if r["id"] == _lesson["resource"]))

PAPERS = [
    dict(id="attention", title="Attention Is All You Need", year=2017, topic="transformer", url="https://arxiv.org/abs/1706.03762", minutes=45,
        question="不依赖循环网络，怎样表达序列中的依赖？", summary="论文提出以注意力为核心的 Transformer。阅读时把架构设计与机器翻译实验分开：前者解释机制，后者支持特定条件下的效果。",
        steps=["扫读摘要与 Figure 1：画出编码器和解码器。", "精读 §3：追踪 Q/K/V、位置编码和 mask 的作用。", "对照 §5–6：记录训练设置、翻译基线与消融变量。"],
        challenge="注意力图能否直接证明模型的因果解释？请区分可视化与因果证据。", experiment="用 3 个 token 对比有无因果 mask 的注意力权重。此实验验证机制，不声称复现 BLEU。"),
    dict(id="rag", title="Retrieval-Augmented Generation", year=2020, topic="rag", url="https://arxiv.org/abs/2005.11401", minutes=40,
        question="如何结合参数记忆与可检索的外部知识？", summary="原文将序列生成模型与稠密检索结合，并比较按整段和按 token 使用检索文档的两种形式。它的训练与评估设置应与自己的资料助手区分。",
        steps=["扫读摘要与方法图：找出检索器、索引和生成器。", "精读 §2：比较 RAG-Sequence 与 RAG-Token。", "阅读实验：把开放域问答与生成任务的指标分别记录。"],
        challenge="如果检索文档过期，回答带引用是否仍可能错误？设计反例。", experiment="固定 10 个问题，对比不检索与检索的回答，分别标记召回失败、误读与正确拒答。"),
    dict(id="lora", title="LoRA: Low-Rank Adaptation", year=2021, topic="finetune", url="https://arxiv.org/abs/2106.09685", minutes=45,
        question="能否用更少的可训练参数适配大型模型？", summary="LoRA 冻结预训练权重，以低秩分解表示增量。重点理解更新矩阵的形状，以及实验中如何同时比较效果和训练资源。",
        steps=["先读引言：记录全量微调的资源问题。", "精读方法中的 W + BA：手算矩阵维度与参数量。", "检查实验及 rank 分析：记录模型、任务与对照条件。"],
        challenge="较小 rank 在一个任务上有效，能否推出所有任务都应使用同一 rank？", experiment="计算两个 rank 的参数量并设计验证集对照；有设备时再进行小模型实验，记录硬件与耗时。"),
    dict(id="react", title="ReAct: Reasoning and Acting", year=2022, topic="agent", url="https://arxiv.org/abs/2210.03629", minutes=40,
        question="推理与外部行动如何共同推进任务？", summary="ReAct 让语言模型交替生成推理与行动，利用环境观察推进任务。阅读时关注实际行动轨迹和失败案例，而不只看最终成功率。",
        steps=["读引言和示例轨迹：标出行动及对应观察。", "读方法：比较只有推理、只有行动与交替执行。", "检查不同任务的结果：记录工具环境和失败类型。"],
        challenge="工具调用成功但返回无关内容时，Agent 应该如何决定下一步？", experiment="用一个模拟搜索工具记录 5 步内的轨迹，加入超时和空结果，检查是否能停止并解释失败。"),
]

PROJECTS = [
    dict(id="knowledge-assistant", title="带引用的资料助手", topic="rag", level="应用交付", steps=["准备 10 篇有使用权限的资料并保留原文 ID", "实现切分、召回、回答和可追溯引用", "建立 20 问评估集，包含无答案和矛盾证据", "提交运行说明、逐题结果、失败分析和版本信息"]),
    dict(id="attention-lab", title="可解释的 Attention 实验室", topic="attention", level="原理实践", steps=["手工构造 Q/K/V 并标注形状", "实现缩放、softmax 与因果 mask", "用断言检查权重和及未来位置", "保存权重图、实验代码和自己的机制解释"]),
    dict(id="paper-reproduction", title="一篇论文的最小复现", topic="reproduce", level="研究实践", steps=["选定一条有原文定位的可检验主张", "写出基线、变量、指标与预期结果", "记录数据、依赖、随机种子与设备", "交付结果表、失败分析及与原论文的差异清单"]),
]


def track_nodes(track):
    by_id = {row["id"]: row for row in LESSONS}
    selected = set()
    def visit(key):
        if key in selected:
            return
        selected.add(key)
        for prerequisite in by_id[key]["prerequisites"]:
            visit(prerequisite)
    for goal in [track["goal"], *track.get("extra", [])]:
        visit(goal)
    return [row["id"] for row in LESSONS if row["id"] in selected]
