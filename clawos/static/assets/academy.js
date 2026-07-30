const AI_LAYERS = [
  {
    id: "foundation", title: "基础支撑层", short: "Foundation",
    summary: "数学、编程、数据、统计和系统基础，是后续所有 AI 能力的底座。",
    concepts: ["线性代数", "概率统计", "优化方法", "Python", "数据结构", "实验设计", "可复现环境", "Git"],
    papers: ["Pattern Recognition and Machine Learning", "The Elements of Statistical Learning"],
    experiments: ["实现梯度下降", "手写 train/valid/test split", "记录一次实验日志"],
    mastery: ["能解释 bias/variance", "能独立复现实验", "能读懂基本公式"]
  },
  {
    id: "ml", title: "传统 AI / 机器学习层 ML", short: "ML",
    summary: "从特征、模型、训练和泛化开始理解学习系统。",
    concepts: ["监督学习", "无监督学习", "特征工程", "SVM", "决策树", "随机森林", "XGBoost", "聚类", "降维"],
    papers: ["Random Forests", "XGBoost: A Scalable Tree Boosting System"],
    experiments: ["用 sklearn 做分类", "比较线性模型和树模型", "分析特征重要性"],
    mastery: ["能选择 baseline", "能解释过拟合", "能读懂 ROC/F1/PR-AUC"]
  },
  {
    id: "dl", title: "深度学习层 DL", short: "DL",
    summary: "掌握神经网络、反向传播、表示学习和训练稳定性。",
    concepts: ["MLP", "反向传播", "CNN", "RNN", "正则化", "BatchNorm", "Dropout", "优化器", "学习率调度"],
    papers: ["Deep Learning", "Adam: A Method for Stochastic Optimization", "Batch Normalization"],
    experiments: ["训练 MLP", "调学习率", "可视化 loss curve"],
    mastery: ["能解释梯度流", "能定位训练不收敛", "能设计消融实验"]
  },
  {
    id: "cv", title: "计算机视觉层 CV", short: "CV",
    summary: "理解图像分类、检测、分割、视觉表示和视觉预训练。",
    concepts: ["CNN", "ResNet", "ViT", "目标检测", "语义分割", "CLIP", "数据增强", "迁移学习"],
    papers: ["ResNet", "Vision Transformer", "CLIP"],
    experiments: ["训练小型图像分类器", "对比 CNN 与 ViT", "用 CLIP 做零样本分类"],
    mastery: ["能解释卷积与注意力差异", "能读懂 mAP/IoU", "能处理数据增强"]
  },
  {
    id: "nlp_llm", title: "NLP 与 LLM 层", short: "NLP/LLM",
    summary: "从语言建模走向 Transformer、大模型、上下文学习和对齐。",
    concepts: ["Tokenization", "Embedding", "Attention", "Transformer", "预训练", "SFT", "RLHF", "DPO", "上下文窗口", "幻觉"],
    papers: ["Attention Is All You Need", "BERT", "GPT-3", "InstructGPT"],
    experiments: ["实现 attention toy", "比较 prompt 策略", "分析一次幻觉样本"],
    mastery: ["能解释 attention", "能区分预训练/微调/对齐", "能做 prompt eval"]
  },
  {
    id: "vlm", title: "VLM / 多模态层", short: "VLM",
    summary: "连接视觉、文本、音频和动作，理解多模态对齐与推理。",
    concepts: ["视觉语言对齐", "Image Captioning", "VQA", "OCR", "Audio-Text", "Multimodal RAG", "Grounding"],
    papers: ["Flamingo", "BLIP-2", "LLaVA", "GPT-4V Technical Report"],
    experiments: ["用图像生成结构化描述", "做图文检索", "设计多模态证据卡"],
    mastery: ["能解释跨模态对齐", "能识别 grounding 失败", "能设计多模态评测"]
  },
  {
    id: "genai", title: "生成式 AI 层", short: "GenAI",
    summary: "覆盖文本、图像、音频、视频生成和可控生成。",
    concepts: ["Diffusion", "Autoregressive Generation", "Sampling", "Temperature", "Guidance", "LoRA", "ControlNet"],
    papers: ["DDPM", "Stable Diffusion", "LoRA"],
    experiments: ["比较 sampling 参数", "生成同主题多版本", "评估一致性与安全性"],
    mastery: ["能解释扩散过程", "能调控生成风格", "能识别版权/安全风险"]
  },
  {
    id: "agent", title: "AI Agent 层", short: "Agent",
    summary: "把模型变成能规划、调用工具、审计、返工和交付的执行系统。",
    concepts: ["Planner", "Tool Use", "RAG", "Memory", "Trace", "Reviewer", "Risk Gate", "Judge", "Rework Loop"],
    papers: ["ReAct", "Toolformer", "Reflexion", "Voyager"],
    experiments: ["设计 Planner/Builder/Reviewer 流程", "记录 tool trace", "实现质量门禁返工"],
    mastery: ["能拆解复杂任务", "能治理工具权限", "能做可视化 trace"]
  },
  {
    id: "aicoding", title: "AI Coding / 软件工程智能体层", short: "AI Coding",
    summary: "把 AI Agent 用到真实代码理解、修改、测试、评审和交付。",
    concepts: ["Repo Understanding", "Patch Planning", "Test Selection", "Code Review", "CI", "Regression", "DevEx"],
    papers: ["SWE-bench", "CodeRepair", "AlphaCode"],
    experiments: ["定位 bug", "生成 patch", "跑测试并写变更说明"],
    mastery: ["能最小化改动", "能保护用户改动", "能说明测试覆盖"]
  },
  {
    id: "infra", title: "AI Infra / MLOps / LLMOps 层", short: "Infra",
    summary: "模型、数据、向量库、评测、部署、监控和成本治理。",
    concepts: ["Serving", "Vector DB", "Feature Store", "Model Registry", "Prompt Versioning", "Observability", "Cost", "Latency"],
    papers: ["TFX", "MLflow", "LLMOps surveys"],
    experiments: ["搭建 eval pipeline", "记录 p50/p95", "做 provider fallback"],
    mastery: ["能解释生产链路", "能做回滚", "能看懂延迟与成本"]
  },
  {
    id: "governance", title: "Evaluation / Safety / Governance 层", short: "Eval/Safety",
    summary: "用可复现验收、红队、安全策略和治理机制控制 AI 风险。",
    concepts: ["Benchmark", "Citation Consistency", "Red Team", "Policy", "Privacy", "Audit", "Risk Scoring", "Human Review"],
    papers: ["HELM", "NIST AI RMF", "EU AI Act resources"],
    experiments: ["设计 30-case eval", "记录 failure reason", "做 citation gate"],
    mastery: ["能定义 pass/fail", "能解释失败样本", "能提出治理策略"]
  },
  {
    id: "rl", title: "强化学习层 RL", short: "RL 支线", branch: true,
    summary: "作为支线理解策略、价值函数、探索和人类反馈。",
    concepts: ["MDP", "Policy Gradient", "Q-learning", "Actor-Critic", "RLHF", "Reward Model"],
    papers: ["DQN", "PPO", "InstructGPT"],
    experiments: ["跑 CartPole", "比较 reward shaping", "理解 PPO clip"],
    mastery: ["能解释 exploration", "能区分 policy/value", "能理解 RLHF 局限"]
  },
  {
    id: "application", title: "AI 应用层", short: "AI Apps",
    summary: "将模型能力落入教育、办公、科研、代码、会议、内容和企业交付。",
    concepts: ["Workflow Design", "UX", "Domain Knowledge", "Human-in-the-loop", "ROI", "Quality Gate"],
    papers: ["Human-AI Interaction", "Enterprise AI case studies"],
    experiments: ["设计一条端到端 demo", "定义用户成功指标", "做可解释报告"],
    mastery: ["能从用户任务反推系统", "能减少认知负担", "能证明业务价值"]
  },
  {
    id: "frontier", title: "前沿拓展层", short: "Frontier",
    summary: "跟踪世界模型、具身智能、长上下文、多 Agent 社会和开放式学习。",
    concepts: ["World Model", "Embodied AI", "Long Context", "Multi-Agent", "Continual Learning", "Open-endedness"],
    papers: ["World Models", "RT-2", "Generative Agents"],
    experiments: ["读一篇前沿论文", "写复现计划", "设计风险清单"],
    mastery: ["能判断 hype 与真实进展", "能提出复现实验", "能连接产品落地"]
  }
];

const ACADEMY_LAYER_META = {
  foundation: { domain: "foundation", level: "基础", era: "1940s–1980s", history: [["1943", "人工神经元", "McCulloch–Pitts 把神经计算写成形式模型。"], ["1958", "感知机", "可学习的线性分类器开启统计学习实践。"], ["1986", "反向传播", "多层网络训练成为可操作方法。"]] },
  ml: { domain: "foundation", level: "基础", era: "1980s–2010s", history: [["1995", "统计学习", "泛化、正则化与核方法形成系统框架。"], ["2001", "集成学习", "随机森林展示多模型组合的稳定性。"], ["2016", "Boosting 工程化", "XGBoost 让树模型成为强基线。"]] },
  dl: { domain: "foundation", level: "进阶", era: "2006–至今", history: [["2006", "深层表示", "逐层预训练重新激活深度网络研究。"], ["2012", "AlexNet", "GPU、数据与卷积网络共同改变视觉基准。"], ["2015", "稳定训练", "残差、归一化与新优化器降低训练难度。"]] },
  cv: { domain: "perception", level: "进阶", era: "2012–至今", history: [["2012", "卷积时代", "大规模图像分类推动深度视觉。"], ["2020", "Vision Transformer", "注意力开始统一视觉表征。"], ["2021", "视觉语言预训练", "CLIP 将开放词汇理解带入视觉任务。"]] },
  nlp_llm: { domain: "perception", level: "进阶", era: "2017–至今", history: [["2017", "Transformer", "自注意力重写序列建模。"], ["2018", "预训练迁移", "BERT 展示通用语言表示。"], ["2022", "指令与对齐", "模型从续写器走向可协作助手。"]] },
  vlm: { domain: "perception", level: "专业", era: "2021–至今", history: [["2021", "图文对齐", "CLIP 连接开放文本与视觉表示。"], ["2022", "少样本多模态", "Flamingo 展示跨模态上下文学习。"], ["2023", "视觉指令", "LLaVA 推动开放视觉对话。"]] },
  genai: { domain: "perception", level: "进阶", era: "2014–至今", history: [["2014", "生成对抗", "GAN 推动高保真生成。"], ["2020", "扩散模型", "逐步去噪带来稳定生成范式。"], ["2022", "潜空间生成", "Stable Diffusion 推动开放创作生态。"]] },
  agent: { domain: "systems", level: "专业", era: "2022–至今", history: [["2022", "推理与行动", "ReAct 将语言推理和工具行动交错。"], ["2023", "反思与记忆", "Reflexion 探索通过反馈改进策略。"], ["2025+", "可治理执行", "重点转向权限、证据、返工与真实交付。"]] },
  aicoding: { domain: "systems", level: "专业", era: "2021–至今", history: [["2021", "代码生成", "大模型学习自然语言到程序的映射。"], ["2023", "仓库级任务", "SWE-bench 将评测推向真实软件维护。"], ["2025+", "软件工程 Agent", "能力从生成代码走向验证、审查与交付。"]] },
  infra: { domain: "systems", level: "专业", era: "2015–至今", history: [["2015", "ML 平台化", "训练、发布、监控开始成为统一流水线。"], ["2020", "向量检索", "语义检索成为生成系统的关键基础设施。"], ["2023", "LLMOps", "提示、评测、成本与可观测性进入生产治理。"]] },
  governance: { domain: "governance", level: "专业", era: "2020–至今", history: [["2020", "系统评测", "从单指标走向场景化、多维基准。"], ["2023", "风险管理", "NIST AI RMF 提供治理生命周期。"], ["2024+", "法规落地", "高风险系统需要透明、审计与人类监督。"]] },
  rl: { domain: "foundation", level: "专业", era: "1950s–至今", history: [["1957", "动态规划", "序贯决策形成数学基础。"], ["2013", "深度强化学习", "DQN 联结感知和长期回报。"], ["2017", "PPO", "稳定策略优化成为常用工程方法。"]] },
  application: { domain: "governance", level: "进阶", era: "持续演进", history: [["2016", "Human-AI Interaction", "产品开始系统研究人机分工。"], ["2023", "生成式应用", "检索、工作流与人工确认成为产品骨架。"], ["现在", "结果与证据", "价值由真实任务成功、质量和治理共同证明。"]] },
  frontier: { domain: "governance", level: "专业", era: "正在形成", history: [["2018", "世界模型", "学习环境动态成为通用智能路径。"], ["2023", "具身与多智能体", "模型开始进入行动和社会模拟。"], ["未来", "持续学习", "开放环境中的长期适应仍是核心难题。"]] }
};

AI_LAYERS.forEach(layer => Object.assign(layer, ACADEMY_LAYER_META[layer.id] || { domain: "foundation", level: "进阶", era: "持续演进", history: [] }));

const academyAtlasState = { domain: "all", view: "map", activeId: location.hash.replace("#", "") || "foundation" };

const CODE_SNIPPETS = {
  embedding: `docs = chunk(pdf_text, size=800, overlap=120)
vectors = qwen_embedding.embed(docs)
top_k = vector_store.search(query, vectors, k=30)
answer = synthesize_with_citations(query, top_k)`,
  rerank: `candidates = vector_store.search(query, k=30)
reranked = qwen_rerank.rank(query, candidates)
evidence = reranked[:5]
assert citation_hit_rate(evidence, answer) > 0.8`,
  agent: `plan = Planner.split(user_goal)
evidence = Research.search(plan)
artifact = Builder.run_tools(plan, evidence)
review = Reviewer.check(artifact)
Judge.gate(review, min_score=0.86)`,
  eval: `cases = load_live_cases()
report = run_benchmark(cases)
assert report.pass_rate >= 0.9
assert report.citation_hit_rate >= 0.85`
};

const academyState = {
  completed: new Set(),
  mastery: {},
  learningDashboard: null,
  activeQuiz: null,
  ingestQueue: JSON.parse(localStorage.getItem("clawos_academy_ingest") || "[]")
};

const academyPaperState = {
  document: null,
  chunks: [],
  report: null,
  citation: null,
  savedKnowledgeId: null,
  annotationArtifact: null,
  checkpointArtifact: null,
  persistedStatus: null,
  documents: [],
  checkpoints: [],
  projectItems: [],
  projectPackages: [],
  pdfUrl: "",
  frameSource: "",
  currentPage: 1,
  penEnabled: false,
  drawing: false,
  lastPoint: null
};

function academySave() {
  localStorage.setItem("clawos_academy_ingest", JSON.stringify(academyState.ingestQueue));
}

function academyEsc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

async function academyApi(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const message = await response.text().catch(() => "");
    throw new Error(`${path} ${response.status}: ${message.slice(0, 180)}`);
  }
  return response.json();
}

function academySetText(id, text) {
  const node = document.getElementById(id);
  if (node) node.textContent = text;
}

function academyRenderHtml(id, html) {
  const node = document.getElementById(id);
  if (node) node.innerHTML = html;
}

async function academyLoadLearningDashboard() {
  const dashboard = await academyApi("/api/academy/learning/dashboard");
  academyState.learningDashboard = dashboard;
  academyState.mastery = Object.fromEntries(
    (dashboard.topics || []).map(item => [item.topic_key, Number(item.p_known || 0)])
  );
  academyState.completed = new Set(
    (dashboard.topics || []).filter(item => item.mastered).map(item => item.topic_key)
  );
  academyRenderLayerGraph(document.querySelector(".academy-layer-node.active")?.dataset.layer);
  academyRenderProgressNodes();
  const progress = dashboard.topics?.length
    ? Math.round((dashboard.mastered_count / dashboard.topics.length) * 100)
    : 0;
  academySetText("academyProgress", `${progress}%`);
  academySetText("academyDueCount", String(dashboard.due_count || 0));
  academySetText(
    "academyMasterySummary",
    `已掌握 ${dashboard.mastered_count || 0}/${dashboard.topics?.length || 0}；证据模型 ${dashboard.topics?.[0]?.algorithm_version || "未初始化"}`
  );
  return dashboard;
}

function academyCompleteNode(key) {
  const item = academyState.learningDashboard?.topics?.find(row => row.topic_key === key);
  if (item?.mastered) {
    academySetText("academyProgress", "该节点已有至少两份掌握证据。");
    return;
  }
  window.location.href = "/academy/quiz";
}

function academyRenderLayerStrip() {
  const target = document.getElementById("academyLayerStrip");
  if (!target) return;
  target.innerHTML = AI_LAYERS.map((layer, index) => `<a class="${layer.branch ? "branch" : ""}" href="/academy/path#${academyEsc(layer.id)}"><b>${String(index + 1).padStart(2, "0")}</b><span>${academyEsc(layer.short)}</span></a>`).join("");
}

function academyRenderLayerGraph(activeId = academyAtlasState.activeId) {
  const graph = document.getElementById("academyLayerGraph");
  const detail = document.getElementById("academyLayerDetail");
  if (!graph || !detail) return;
  const query = (document.getElementById("academyLayerSearch")?.value || "").trim().toLowerCase();
  const level = document.getElementById("academyLayerLevel")?.value || "all";
  const visible = AI_LAYERS.filter(layer => {
    const domainMatch = academyAtlasState.domain === "all" || layer.domain === academyAtlasState.domain;
    const levelMatch = level === "all" || layer.level === level;
    const text = [layer.title, layer.short, layer.summary, ...layer.concepts, ...layer.papers, ...layer.experiments].join(" ").toLowerCase();
    return domainMatch && levelMatch && (!query || text.includes(query));
  });
  const active = visible.find(layer => layer.id === activeId) || visible[0] || AI_LAYERS[0];
  academyAtlasState.activeId = active.id;
  document.getElementById("academyAtlasEmpty")?.toggleAttribute("hidden", visible.length > 0);
  graph.innerHTML = visible.map((layer, index) => {
    const unlocked = academyState.completed.has(layer.id);
    const secondary = academyAtlasState.view === "history" ? layer.era : academyAtlasState.view === "practice" ? `${layer.experiments.length} 个实践任务` : `${layer.level} · ${layer.concepts.length} 个核心概念`;
    return `<button class="academy-layer-node ${layer.id === active.id ? "active" : ""} ${layer.branch ? "branch" : ""} ${unlocked ? "unlocked" : ""}" data-layer="${academyEsc(layer.id)}" style="--i:${index}"><b>${academyEsc(layer.short)}</b><span>${academyEsc(layer.title)}</span><small>${academyEsc(secondary)}</small></button>`;
  }).join("");
  detail.innerHTML = `
    <div class="atlas-inspector-head"><span>${active.branch ? "Exploration Branch" : "Knowledge Layer"}</span><h3>${academyEsc(active.title)}</h3><p>${academyEsc(active.summary)}</p><div class="atlas-meta"><i>${academyEsc(active.level)}</i><i>${academyEsc(active.era)}</i><i>${active.concepts.length} 个概念</i></div></div>
    <section><b>核心知识</b><ul>${active.concepts.slice(0, 6).map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <section><b>发展脉络</b><div class="atlas-history">${active.history.map(item => `<article><span>${academyEsc(item[0])}</span><b>${academyEsc(item[1])}</b><small>${academyEsc(item[2])}</small></article>`).join("")}</div></section>
    <section><b>代表资料</b><ul>${active.papers.map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <section><b>最小实践</b><ul>${active.experiments.map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <section><b>掌握证据</b><ul>${active.mastery.map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <button class="pill solid dark" type="button" onclick="academyCompleteNode('${academyEsc(active.id)}')"><span class="fluent-icon" aria-hidden="true">&#xE930;</span>${academyState.completed.has(active.id) ? "已记录掌握" : "记录掌握证据"}</button>`;
  graph.querySelectorAll(".academy-layer-node").forEach(btn => btn.addEventListener("click", () => {
    history.replaceState(null, "", `#${btn.dataset.layer}`);
    academyRenderLayerGraph(btn.dataset.layer);
  }));
}

function academyFilterLayers() { academyRenderLayerGraph(academyAtlasState.activeId); }
function academyFilterDomain(domain) {
  academyAtlasState.domain = domain;
  document.querySelectorAll("[data-atlas-domain]").forEach(button => button.classList.toggle("active", button.dataset.atlasDomain === domain));
  academyRenderLayerGraph(academyAtlasState.activeId);
}
function academySetAtlasView(view) {
  academyAtlasState.view = view;
  document.querySelectorAll("[data-atlas-view]").forEach(button => button.classList.toggle("active", button.dataset.atlasView === view));
  academyRenderLayerGraph(academyAtlasState.activeId);
}

function academyRenderProgressNodes() {
  document.querySelectorAll(".academy-node").forEach(node => {
    node.classList.toggle("unlocked", academyState.completed.has(node.dataset.node));
  });
  const progress = document.getElementById("academyProgress");
  if (progress) {
    const percent = Math.round((academyState.completed.size / Math.max(1, AI_LAYERS.length)) * 100);
    progress.textContent = `${Math.min(100, percent)}%`;
  }
}

function academyPaperSnippet() {
  const chunkText = academyPaperState.chunks.map(chunk => chunk.text || chunk.content || "").join("\n\n").trim();
  return chunkText || document.getElementById("paperAbstract")?.value || "";
}

function academyRenderPaperChunks() {
  const target = document.getElementById("academyPaperText");
  if (!target) return;
  if (!academyPaperState.chunks.length) {
    target.innerHTML = `<article class="paper-chunk"><b>Parsed Text</b><p>等待后端解析论文 chunk。</p></article>`;
    academyRenderPaperRuntimeStatus();
    return;
  }
  target.innerHTML = academyPaperState.chunks.slice(0, 10).map((chunk, index) => {
    const label = chunk.citation || `doc:${academyPaperState.document?.id || "?"}#chunk=${chunk.chunk_index ?? index}`;
    const text = chunk.text || chunk.content || chunk.preview || "";
    return `<article class="paper-chunk"><b>${academyEsc(label)}</b><p>${academyEsc(text.slice(0, 720))}</p></article>`;
  }).join("");
  academyRenderPaperRuntimeStatus();
}

function academyRenderCitationEvidence(result) {
  const answer = result?.answer || result?.summary || "暂无回答。";
  const evidence = result?.citations || result?.evidence || result?.chunks || [];
  academyPaperState.citation = result;
  academyRenderHtml("academyCitationEvidence", `
    <p>${academyEsc(answer)}</p>
    ${evidence.length ? `<ul>${evidence.slice(0, 8).map((item, index) => {
      const label = item.citation || item.source || item.url || `evidence-${index + 1}`;
      const text = item.text || item.snippet || item.content || item.preview || "";
      return `<li><b>${academyEsc(label)}</b><span>${academyEsc(text.slice(0, 260))}</span></li>`;
    }).join("")}</ul>` : "<small>没有返回可用引用，请换一个问题或检查论文解析质量。</small>"}
  `);
}

function academyRenderPaperMeta() {
  const target = document.getElementById("academyPaperMeta");
  if (!target) return;
  const doc = academyPaperState.document || academyPaperState.persistedStatus?.document || {};
  const meta = doc.metadata || {};
  const previewable = academyPreviewablePaperSource(doc);
  const ocrPages = Array.isArray(meta.ocr_pages) ? meta.ocr_pages : [];
  const ocrLabel = meta.ocr_required ? (ocrPages.length ? `Needs OCR: p${ocrPages.join(",")}` : "Needs OCR") : "Not required";
  const rows = [
    ["Filename", doc.filename || doc.title || "Waiting"],
    ["Extractor", doc.extractor || meta.extractor || "Unknown"],
    ["Pages", meta.page_count || meta.pages || "Unknown"],
    ["OCR", ocrLabel],
    ["Preview", previewable ? "Available" : "Chunks only"]
  ];
  target.innerHTML = rows.map(([label, value]) => `<article><b>${academyEsc(label)}</b><span>${academyEsc(value)}</span></article>`).join("");
}
function academyRenderPaperRuntimeStatus() {
  const target = document.getElementById("academyPaperRuntimeStatus");
  if (!target) return;
  const status = academyPaperState.persistedStatus || {};
  const docId = academyPaperState.document?.id || status.document?.id;
  const report = academyPaperState.report?.report || academyPaperState.report || {};
  const persistedReport = status.report || {};
  const markdownPath = report.markdown_path || persistedReport.markdown_path || "";
  const pdfPath = report.pdf_path || persistedReport.pdf_path || "";
  const knowledgeId = academyPaperState.savedKnowledgeId || status.knowledge?.id;
  const annotationArtifact = academyPaperState.annotationArtifact || status.annotation?.artifact || {};
  const annotationPath = annotationArtifact.path || annotationArtifact.uri || "";
  const checkpointArtifact = academyPaperState.checkpointArtifact || status.checkpoint?.artifact || {};
  const checkpointPath = checkpointArtifact.uri || checkpointArtifact.metadata?.storage?.path || checkpointArtifact.path || "";
  const chunkCount = academyPaperState.chunks.length || status.chunks?.count || 0;
  const items = [
    ["Document", docId ? `doc:${docId}` : "Waiting for upload", Boolean(docId)],
    ["Chunks", chunkCount ? `${chunkCount} indexed` : "No chunks yet", chunkCount > 0],
    ["Report", markdownPath || pdfPath ? "Markdown/PDF ready" : "Not generated", Boolean(markdownPath || pdfPath || persistedReport.ready)],
    ["Knowledge", knowledgeId ? `item:${knowledgeId}` : "Not saved", Boolean(knowledgeId)],
    ["Annotation", annotationPath ? "Artifact ready" : "Local fallback", Boolean(annotationPath || status.annotation?.ready)],
    ["Checkpoint", checkpointPath ? "Saved" : "Not saved", Boolean(checkpointPath || status.checkpoint?.ready)]
  ];
  target.innerHTML = items.map(([label, value, ready]) => `
    <article class="${ready ? "ready" : "waiting"}">
      <b>${academyEsc(label)}</b><span>${academyEsc(value)}</span>
    </article>`).join("");
}

async function academyRefreshPaperPersistedStatus() {
  if (!academyPaperState.document?.id) {
    academyPaperState.persistedStatus = null;
    academyRenderPaperRuntimeStatus();
    return null;
  }
  const status = await academyApi(`/api/academy/paper/status?document_id=${Number(academyPaperState.document.id)}`);
  academyPaperState.persistedStatus = status;
  if (status.knowledge?.id) academyPaperState.savedKnowledgeId = status.knowledge.id;
  if (status.annotation?.artifact) academyPaperState.annotationArtifact = status.annotation.artifact;
  if (status.checkpoint?.artifact) academyPaperState.checkpointArtifact = status.checkpoint.artifact;
  academyRenderPaperRuntimeStatus();
  academyRenderPaperMeta();
  return status;
}
function academyRenderPaperReport() {
  const report = academyPaperState.report;
  const target = document.getElementById("academyPaperReportCard");
  if (!target || !report) return;
  const markdownPath = report.report?.markdown_path || report.markdown_path || "";
  const pdfPath = report.report?.pdf_path || report.pdf_path || "";
  const preview = report.preview || report.report?.preview || report.summary || "";
  target.innerHTML = `
    <b>报告产物</b>
    <p id="academyPaperReportStatus">已生成 AI 导读报告。保存到知识库后会形成可追踪 Artifact/Evidence。</p>
    <div class="report-paths">
      <span>Markdown: ${academyEsc(markdownPath || "未返回")}</span>
      <span>PDF: ${academyEsc(pdfPath || "未返回")}</span>
    </div>
    <p>${academyEsc(String(preview).slice(0, 520))}</p>
  `;
  academyRenderPaperRuntimeStatus();
}

function academyLightPaperGraph(stage = "paper") {
  const saved = academyPaperState.savedKnowledgeId ? `知识库条目 #${academyPaperState.savedKnowledgeId}` : "等待保存知识库";
  academyRenderPaperRuntimeStatus();
  academySetText("academyPaperGraphStatus", `论文产物阶段：${stage}；${saved}。掌握度需要独立评估或绑定 TaskRun 的项目证据。`);
}

async function academyRefreshPaperAudit() {
  const target = document.getElementById("academyPaperAuditGrid");
  if (!target) return;
  academySetText("academyPaperAuditStatus", "Checking local workflow...");
  try {
    const docId = academyPaperState.document?.id || academyPaperState.persistedStatus?.document?.id || 0;
    const suffix = docId ? `?document_id=${Number(docId)}` : "";
    const audit = await academyApi(`/api/academy/paper/offline-audit${suffix}`);
    academyPaperState.offlineAudit = audit;
    const checks = audit.checks || [];
    target.innerHTML = checks.map(item => `<article class="${item.ok ? "ready" : "waiting"}"><b>${academyEsc(item.label || item.id)}</b><span>${item.ok ? "Ready" : "Missing"}</span><small>${academyEsc(item.detail || item.id)}</small></article>`).join("");
    academySetText("academyPaperAuditStatus", `${audit.percent || 0}% ready · ${audit.remaining?.length || 0} remaining`);
  } catch (error) {
    academySetText("academyPaperAuditStatus", `Offline audit unavailable: ${error.message}`);
  }
}
async function academyLoadPaperHistory() {
  const target = document.getElementById("academyPaperHistory");
  if (!target) return;
  academySetText("academyPaperHistoryStatus", "Loading local research library...");
  try {
    const payload = await academyApi("/api/documents?category=research");
    academyPaperState.documents = payload.documents || [];
    if (!academyPaperState.documents.length) {
      target.innerHTML = `<button type="button" disabled>No local papers yet</button>`;
      academySetText("academyPaperHistoryStatus", "Upload a paper to start a local history.");
      return;
    }
    target.innerHTML = academyPaperState.documents.slice(0, 8).map(doc => {
      const chunkCount = Number(doc.chunk_count || 0);
      const label = `${doc.title || doc.filename || `Document ${doc.id}`}`;
      return `<button type="button" data-document-id="${Number(doc.id)}">
        <b>${academyEsc(label)}</b><span>doc:${Number(doc.id)} · ${chunkCount} chunks · ${academyEsc(doc.status || "unknown")}</span>
      </button>`;
    }).join("");
    target.querySelectorAll("button[data-document-id]").forEach(button => {
      button.addEventListener("click", () => academyOpenPaperDocument(Number(button.dataset.documentId)));
    });
    academySetText("academyPaperHistoryStatus", `${academyPaperState.documents.length} local research documents`);
  } catch (error) {
    academySetText("academyPaperHistoryStatus", `History unavailable: ${error.message}`);
  }
}

async function academyLoadPaperCheckpoints(documentId = 0) {
  const target = document.getElementById("academyPaperCheckpointHistory");
  if (!target) return;
  academySetText("academyPaperCheckpointStatus", "Loading local checkpoints...");
  try {
    const suffix = documentId ? `?document_id=${Number(documentId)}&limit=8` : "?limit=8";
    const payload = await academyApi(`/api/academy/paper/checkpoints${suffix}`);
    academyPaperState.checkpoints = payload.checkpoints || [];
    if (!academyPaperState.checkpoints.length) {
      target.innerHTML = `<button type="button" disabled>No checkpoints yet</button>`;
      academySetText("academyPaperCheckpointStatus", "Save a checkpoint after a report or citation pass.");
      return;
    }
    target.innerHTML = academyPaperState.checkpoints.map(item => {
      const label = item.document_title || item.title || item.run_id;
      const knowledge = item.knowledge_id ? `item:${item.knowledge_id}` : "no knowledge";
      return `<button type="button" data-run-id="${academyEsc(item.run_id)}">
        <b>${academyEsc(label)}</b><span>${academyEsc(item.run_id)} · doc:${Number(item.document_id || 0)} · ${academyEsc(knowledge)}</span>
      </button>`;
    }).join("");
    target.querySelectorAll("button[data-run-id]").forEach(button => {
      button.addEventListener("click", () => academyOpenPaperCheckpoint(button.dataset.runId));
    });
    academySetText("academyPaperCheckpointStatus", `${academyPaperState.checkpoints.length} local checkpoints`);
  } catch (error) {
    academySetText("academyPaperCheckpointStatus", `Checkpoint history unavailable: ${error.message}`);
  }
}

async function academyLoadPaperProjectBoard(documentId = 0) {
  const target = document.getElementById("academyPaperProjectBoard");
  if (!target) return;
  academySetText("academyPaperProjectStatus", "Loading local project items...");
  try {
    const suffix = documentId ? `?document_id=${Number(documentId)}&limit=20` : "?limit=20";
    const payload = await academyApi(`/api/academy/paper/project-board${suffix}`);
    academyPaperState.projectItems = payload.items || [];
    if (!academyPaperState.projectItems.length) {
      target.innerHTML = `<article><b>No project items yet</b><span>Add a follow-up question after reading or checkpointing a paper.</span></article>`;
      academySetText("academyPaperProjectStatus", "No local project items yet.");
      return;
    }
    target.innerHTML = academyPaperState.projectItems.map(item => {
      const links = [`doc:${Number(item.document_id || 0)}`];
      if (item.checkpoint_run_id) links.push("checkpoint");
      if (item.report_run_id) links.push("report");
      if (item.knowledge_id) links.push(`knowledge:${item.knowledge_id}`);
      return `<article><b>${academyEsc(item.question || item.title)}</b><span>${academyEsc(item.status || "open")} 路 ${academyEsc(item.priority || "normal")}</span><small>${academyEsc(links.join(" 路 "))}</small><div class="academy-paper-project-actions"><button type="button" data-project-run-id="${academyEsc(item.run_id)}" data-status="done">Done</button><button type="button" data-project-run-id="${academyEsc(item.run_id)}" data-status="blocked">Blocked</button><button type="button" data-project-run-id="${academyEsc(item.run_id)}" data-status="open">Reopen</button></div></article>`;
    }).join("");
    target.querySelectorAll("button[data-project-run-id]").forEach(button => {
      button.addEventListener("click", () => academyUpdatePaperProjectItem(button.dataset.projectRunId, button.dataset.status));
    });
    academySetText("academyPaperProjectStatus", `${academyPaperState.projectItems.length} local project items`);
  } catch (error) {
    academySetText("academyPaperProjectStatus", `Project board unavailable: ${error.message}`);
  }
}

async function academyLoadPaperProjectPackages(documentId = 0) {
  const target = document.getElementById("academyPaperProjectPackages");
  if (!target) return;
  academySetText("academyPaperProjectPackageStatus", "Loading local packages...");
  try {
    const suffix = documentId ? `?document_id=${Number(documentId)}&limit=8` : "?limit=8";
    const payload = await academyApi(`/api/academy/paper/project-board/exports${suffix}`);
    academyPaperState.projectPackages = payload.exports || [];
    if (!academyPaperState.projectPackages.length) {
      target.innerHTML = `<button type="button" disabled>No project packages yet</button>`;
      academySetText("academyPaperProjectPackageStatus", "Export a project package to review it later.");
      return;
    }
    target.innerHTML = academyPaperState.projectPackages.map(item => `<button type="button" data-project-export-id="${academyEsc(item.run_id)}"><b>${academyEsc(item.document_title || item.title || item.run_id)}</b><span>${academyEsc(item.run_id)} 路 items:${Number(item.project_item_count || 0)} 路 checkpoints:${Number(item.checkpoint_count || 0)}</span></button>`).join("");
    target.querySelectorAll("button[data-project-export-id]").forEach(button => {
      button.addEventListener("click", () => academyOpenPaperProjectPackage(button.dataset.projectExportId));
    });
    academySetText("academyPaperProjectPackageStatus", `${academyPaperState.projectPackages.length} local project packages`);
  } catch (error) {
    academySetText("academyPaperProjectPackageStatus", `Project package history unavailable: ${error.message}`);
  }
}


async function academyLoadPaperTimeline(documentId = 0) {
  const target = document.getElementById("academyPaperTimeline");
  if (!target) return;
  const activeDocId = Number(documentId || academyPaperState.document?.id || academyPaperState.persistedStatus?.document?.id || 0);
  academySetText("academyPaperTimelineStatus", "Loading local research timeline...");
  try {
    const suffix = activeDocId ? `?document_id=${activeDocId}&limit=30` : "?limit=30";
    const payload = await academyApi(`/api/academy/paper/timeline${suffix}`);
    academyPaperState.timeline = payload.events || [];
    if (!academyPaperState.timeline.length) {
      target.innerHTML = `<button type="button" disabled>No timeline events yet</button>`;
      academySetText("academyPaperTimelineStatus", "Upload, analyze, save, checkpoint, or export a paper to build the timeline.");
      academyRenderHtml("academyPaperTimelineDetail", "");
      return;
    }
    target.innerHTML = academyPaperState.timeline.map((item, index) => {
      const time = item.updated_at || "unknown time";
      const status = item.status ? ` / ${item.status}` : "";
      return `<button type="button" data-timeline-index="${index}"><b>${academyEsc(item.label || item.kind)}</b><span>${academyEsc(time)} / doc:${Number(item.document_id || 0)}${academyEsc(status)}</span><small>${academyEsc(item.summary || item.run_id || "local event")}</small></button>`;
    }).join("");
    target.querySelectorAll("button[data-timeline-index]").forEach(button => {
      button.addEventListener("click", () => academyOpenPaperTimelineEvent(Number(button.dataset.timelineIndex)));
    });
    academySetText("academyPaperTimelineStatus", `${academyPaperState.timeline.length} local workflow events`);
  } catch (error) {
    academySetText("academyPaperTimelineStatus", `Timeline unavailable: ${error.message}`);
  }
}

async function academyOpenPaperTimelineEvent(index) {
  const item = academyPaperState.timeline[index];
  const detail = document.getElementById("academyPaperTimelineDetail");
  if (!item || !detail) return;
  const target = item.target || {};
  try {
    if (target.kind === "document" && target.document_id) {
      await academyOpenPaperDocument(Number(target.document_id));
    } else if (target.kind === "checkpoint" && target.run_id) {
      await academyOpenPaperCheckpoint(target.run_id);
    } else if (target.kind === "project_export" && target.run_id) {
      await academyOpenPaperProjectPackage(target.run_id);
    }
    detail.innerHTML = `<b>${academyEsc(item.label || item.kind)}</b><pre>${academyEsc(JSON.stringify(item.payload || item, null, 2))}</pre>`;
  } catch (error) {
    detail.innerHTML = `<b>${academyEsc(item.label || item.kind)}</b><span>Open failed: ${academyEsc(error.message)}</span><pre>${academyEsc(JSON.stringify(item.payload || item, null, 2))}</pre>`;
  }
}async function academyOpenPaperProjectPackage(runId) {
  const payload = await academyApi(`/api/academy/paper/project-board/exports/${encodeURIComponent(runId)}`);
  const pack = payload.package || {};
  const doc = pack.document || {};
  academyPaperState.document = doc;
  academyPaperState.persistedStatus = pack.status || null;
  academyPaperState.chunks = pack.chunks || [];
  academyPaperState.projectItems = pack.project_items || [];
  academyPaperState.checkpoints = pack.checkpoints || [];
  academyPaperState.report = pack.status?.report ? { report: pack.status.report } : null;
  academyPaperState.savedKnowledgeId = pack.status?.knowledge?.id || null;
  academyPaperState.annotationArtifact = pack.status?.annotation?.artifact || null;
  academyPaperState.checkpointArtifact = pack.status?.checkpoint?.artifact || null;
  const title = document.getElementById("paperTitle");
  if (title) title.value = doc.title || doc.filename || payload.summary?.document_title || "Research project package";
  academyRenderPaperMeta();
  academyRenderPaperChunks();
  if (academyPaperState.report) academyRenderPaperReport();
  academyRenderPaperRuntimeStatus();
  await academyLoadPaperProjectBoard(Number(doc.id || payload.summary?.document_id || 0));
  await academyLoadPaperCheckpoints(Number(doc.id || payload.summary?.document_id || 0));
  academyLoadPaperTimeline(Number(doc.id || payload.summary?.document_id || 0)).catch(() => null);
  academySetText("academyPaperProjectPackageStatus", `Project package restored: ${runId}`);
}
async function academyUpdatePaperProjectItem(runId, status) {
  try {
    const saved = await academyApi(`/api/academy/paper/project-board/${encodeURIComponent(runId)}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status })
    });
    academySetText("academyPaperProjectStatus", `Project item ${saved.item?.status || status}: ${runId}`);
    await academyLoadPaperProjectBoard(Number(academyPaperState.document?.id || saved.item?.document_id || 0));
  } catch (error) {
    academySetText("academyPaperProjectStatus", `Project item update failed: ${error.message}`);
  }
}

async function academyExportPaperProject() {
  try {
    if (!academyPaperState.document?.id) {
      academySetText("academyPaperProjectStatus", "Open or upload a paper before exporting a project package.");
      return;
    }
    const exported = await academyApi("/api/academy/paper/project-board/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: Number(academyPaperState.document.id) })
    });
    academyLoadPaperTimeline(Number(academyPaperState.document.id)).catch(() => null);
    academySetText("academyPaperProjectStatus", `Project package exported: ${exported.artifact?.path || exported.run?.run_id || "done"}`);
    academyLoadPaperProjectPackages(Number(academyPaperState.document.id)).catch(() => null);
    academyRefreshPaperAudit().catch(() => null);
  } catch (error) {
    academySetText("academyPaperProjectStatus", `Project export failed: ${error.message}`);
  }
}
async function academyAddPaperProjectItem() {
  try {
    if (!academyPaperState.document?.id) {
      academySetText("academyPaperProjectStatus", "Open or upload a paper before adding a project item.");
      return;
    }
    const input = document.getElementById("academyPaperProjectQuestion");
    const question = (input?.value || document.getElementById("academyCitationQuery")?.value || "").trim();
    if (!question) {
      academySetText("academyPaperProjectStatus", "Enter a follow-up question first.");
      return;
    }
    const saved = await academyApi("/api/academy/paper/project-board", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: Number(academyPaperState.document.id),
        question,
        priority: "normal",
        next_action: "follow-up research"
      })
    });
    academyLoadPaperTimeline(Number(academyPaperState.document.id)).catch(() => null);
    academySetText("academyPaperProjectStatus", `Project item saved: ${saved.item?.run_id || "done"}`);
    await academyLoadPaperProjectBoard(Number(academyPaperState.document.id));
  } catch (error) {
    academySetText("academyPaperProjectStatus", `Project item save failed: ${error.message}`);
  }
}
async function academyOpenPaperCheckpoint(runId) {
  const payload = await academyApi(`/api/academy/paper/checkpoints/${encodeURIComponent(runId)}`);
  const checkpoint = payload.checkpoint || {};
  const status = checkpoint.status || {};
  const doc = checkpoint.document || status.document || {};
  academyPaperState.document = doc;
  academyPaperState.persistedStatus = status;
  academyPaperState.citation = checkpoint.citation || null;
  academyPaperState.chunks = checkpoint.chunks || [];
  academyPaperState.report = status.report ? { report: status.report } : null;
  academyPaperState.savedKnowledgeId = status.knowledge?.id || null;
  academyPaperState.annotationArtifact = status.annotation?.artifact || null;
  academyPaperState.checkpointArtifact = payload.summary?.artifact || status.checkpoint?.artifact || null;
  const title = document.getElementById("paperTitle");
  if (title) title.value = doc.title || doc.filename || payload.summary?.document_title || "Checkpoint paper";
  const frame = document.getElementById("academyPdfFrame");
  if (frame) {
    if (doc.id && academyPreviewablePaperSource(doc)) academySetPdfSource(`/api/documents/${Number(doc.id)}/source`);
    else { frame.removeAttribute("src"); academyPaperState.frameSource = ""; document.getElementById("academyReaderEmpty")?.removeAttribute("hidden"); }
  }
  academyRenderPaperMeta();
  academyRenderPaperChunks();
  if (academyPaperState.report) academyRenderPaperReport();
  if (academyPaperState.citation) academyRenderCitationEvidence(academyPaperState.citation);
  academyRenderPaperRuntimeStatus();
  academyLoadPaperProjectBoard(Number(doc.id || 0)).catch(() => null);
  academySetText("academyPaperStatus", `Checkpoint restored: ${runId}`);
}
function academyPreviewablePaperSource(doc) {
  const filename = String(doc?.filename || doc?.file_path || "").toLowerCase();
  const mime = String(doc?.mime_type || "").toLowerCase();
  return filename.endsWith(".pdf") || mime.includes("pdf");
}
async function academyOpenPaperDocument(documentId) {
  const doc = academyPaperState.documents.find(item => Number(item.id) === Number(documentId)) || { id: documentId };
  academyPaperState.document = doc;
  academyPaperState.report = null;
  academyPaperState.citation = null;
  academyPaperState.savedKnowledgeId = null;
  academyPaperState.annotationArtifact = null;
  academyPaperState.checkpointArtifact = null;
  academyPaperState.persistedStatus = null;
  const title = document.getElementById("paperTitle");
  if (title) title.value = doc.title || doc.filename || `Document ${documentId}`;
  const frame = document.getElementById("academyPdfFrame");
  if (frame) {
    if (academyPreviewablePaperSource(doc)) academySetPdfSource(`/api/documents/${Number(documentId)}/source`);
    else { frame.removeAttribute("src"); academyPaperState.frameSource = ""; document.getElementById("academyReaderEmpty")?.removeAttribute("hidden"); }
  }
  academySetText("academyPaperStatus", `Opening local paper doc:${documentId}...`);
  const chunks = await academyApi(`/api/documents/${Number(documentId)}/chunks?limit=12`);
  academyPaperState.document = chunks.document || doc;
  academyPaperState.chunks = chunks.chunks || chunks.items || [];
  academyRenderPaperMeta();
  await academyRefreshPaperPersistedStatus().catch(() => null);
  academyRenderPaperChunks();
  academyGeneratePaperRead();
  academyLightPaperGraph("parsed");
  academyLoadPaperCheckpoints(Number(documentId)).catch(() => null);
  academyLoadPaperProjectBoard(Number(documentId)).catch(() => null);
  academyLoadPaperProjectPackages(Number(documentId)).catch(() => null);
  academyLoadPaperTimeline(Number(documentId)).catch(() => null);
  academyRefreshPaperAudit().catch(() => null);
  academySetText("academyPaperStatus", `Opened local paper doc:${documentId}; ${academyPaperState.chunks.length} chunks loaded.`);
}
async function academyUploadPaper() {
  const fileInput = document.getElementById("academyPaperFile");
  const file = fileInput?.files?.[0];
  if (!file) {
    academySetText("academyPaperStatus", "请先选择 PDF、DOCX 或文本论文。");
    return null;
  }
  academySetText("academyPaperStatus", "正在上传并解析论文...");
  if (academyPaperState.pdfUrl) URL.revokeObjectURL(academyPaperState.pdfUrl);
  academyPaperState.pdfUrl = URL.createObjectURL(file);
  const frame = document.getElementById("academyPdfFrame");
  if (frame && file.type === "application/pdf") academySetPdfSource(academyPaperState.pdfUrl);
  const form = new FormData();
  form.append("files", file);
  form.append("category", "research");
  const uploaded = await academyApi("/api/documents/upload", { method: "POST", body: form });
  const docs = uploaded.documents || uploaded.items || [];
  academyPaperState.document = docs[0] || uploaded.document || null;
  if (!academyPaperState.document?.id) throw new Error("上传成功但没有返回 document id");
  const title = document.getElementById("paperTitle");
  if (title && (!title.value || title.value.includes("Retrieval-Augmented"))) {
    title.value = academyPaperState.document.title || academyPaperState.document.filename || file.name;
  }
  const chunks = await academyApi(`/api/documents/${Number(academyPaperState.document.id)}/chunks?limit=12`);
  academyPaperState.chunks = chunks.chunks || chunks.items || [];
  academyRenderPaperMeta();
  await academyRefreshPaperPersistedStatus().catch(() => null);
  academyRenderPaperChunks();
  academyGeneratePaperRead();
  academyLightPaperGraph("parsed");
  academySetText("academyPaperStatus", `解析完成：document #${academyPaperState.document.id}，chunk ${academyPaperState.chunks.length} 条。`);
  academyLoadPaperHistory().catch(() => null);
  academyLoadPaperCheckpoints(Number(academyPaperState.document.id)).catch(() => null);
  academyLoadPaperProjectBoard(Number(academyPaperState.document.id)).catch(() => null);
  academyLoadPaperProjectPackages(Number(academyPaperState.document.id)).catch(() => null);
  academyRefreshPaperAudit().catch(() => null);
  return academyPaperState.document;
}

async function academyRunPaperWorkflow() {
  try {
    if (!academyPaperState.document?.id) await academyUploadPaper();
    if (!academyPaperState.document?.id) return;
    academySetText("academyPaperReportStatus", "正在生成 Markdown/PDF 深度导读报告...");
    const body = {
      library_document_id: Number(academyPaperState.document.id),
      report_style: "academic_deep_read",
      depth: 5,
      question_count: 40,
      output_dir: "output/academy",
      formats: ["markdown", "pdf"]
    };
    academyPaperState.report = await academyApi("/api/workspace/research/learning-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    academyRenderPaperReport();
    await academyRefreshPaperPersistedStatus().catch(() => null);
    await academyAskPaperCitation("method experiment limitation contribution");
    academyLoadPaperTimeline(Number(academyPaperState.document.id)).catch(() => null);
    academyLightPaperGraph("reported");
  } catch (error) {
    academySetText("academyPaperReportStatus", `报告生成失败：${error.message}`);
  }
}

async function academySavePaperKnowledge() {
  try {
    if (!academyPaperState.report) await academyRunPaperWorkflow();
    if (!academyPaperState.report) return;
    academySetText("academyPaperStatus", "正在保存论文导读到知识库...");
    const title = document.getElementById("paperTitle")?.value || academyPaperState.document?.title || "Academy paper deep read";
    const markdownPath = academyPaperState.report.report?.markdown_path || academyPaperState.report.markdown_path || "";
    const pdfPath = academyPaperState.report.report?.pdf_path || academyPaperState.report.pdf_path || "";
    const citationText = JSON.stringify(academyPaperState.citation || {}, null, 2).slice(0, 3000);
    const content = [
      `# ${title}`,
      "",
      "## AI 导读报告",
      academyPaperState.report.preview || academyPaperState.report.summary || "报告已生成。",
      "",
      `Markdown: ${markdownPath}`,
      `PDF: ${pdfPath}`,
      "",
      "## Citation Evidence",
      citationText
    ].join("\n");
    const saved = await academyApi("/api/knowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: `${title} - Academy Deep Read`, content, category: "research", source: `academy-paper doc:${academyPaperState.document?.id || ""}`, tags: ["academy", "paper", "deep-read", "citation-evidence"] })
    });
    academyPaperState.savedKnowledgeId = saved.id || saved.item?.id || saved.knowledge_id;
    await academyRefreshPaperPersistedStatus().catch(() => null);
    academyLightPaperGraph("saved");
    academySetText("academyPaperStatus", `已保存到知识库：${academyPaperState.savedKnowledgeId || "完成"}。`);
    const graph = await academyApi("/api/knowledge/graph?category=research&limit=20").catch(() => null);
    if (graph) {
      const nodeCount = (graph.nodes || graph.items || []).length;
      academyRenderPaperRuntimeStatus();
    academyLoadPaperCheckpoints(Number(academyPaperState.document.id)).catch(() => null);
      academyLoadPaperTimeline(Number(academyPaperState.document.id)).catch(() => null);
      academySetText("academyPaperGraphStatus", `知识库已更新：research graph ${nodeCount} 个节点；学习图谱已点亮论文相关能力。`);
    }
  } catch (error) {
    academySetText("academyPaperStatus", `保存失败：${error.message}`);
  }
}

async function academySavePaperCheckpoint() {
  try {
    if (!academyPaperState.document?.id) {
      academySetText("academyPaperStatus", "请先上传或打开论文，再保存 Checkpoint。");
      return;
    }
    academySetText("academyPaperStatus", "正在保存 Paper Studio Checkpoint...");
    const saved = await academyApi("/api/academy/paper/checkpoint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: Number(academyPaperState.document.id),
        citation: academyPaperState.citation || {}
      })
    });
    academyPaperState.checkpointArtifact = saved.artifact || saved.status?.checkpoint?.artifact || null;
    academyPaperState.persistedStatus = saved.status || academyPaperState.persistedStatus;
    academyRenderPaperRuntimeStatus();
    academyLoadPaperCheckpoints(Number(academyPaperState.document.id)).catch(() => null);
    academyRefreshPaperAudit().catch(() => null);
    academyLoadPaperTimeline(Number(academyPaperState.document.id)).catch(() => null);
    academySetText("academyPaperStatus", `Checkpoint 已保存：${saved.artifact?.path || saved.run?.run_id || "done"}`);
  } catch (error) {
    academySetText("academyPaperStatus", `Checkpoint 保存失败：${error.message}`);
  }
}
async function academyAskPaperCitation(seedQuery) {
  try {
    if (!academyPaperState.document?.id) {
      academySetText("academyCitationEvidence", "请先上传并解析论文。");
      return;
    }
    const query = typeof seedQuery === "string" ? seedQuery : document.getElementById("academyCitationQuery")?.value || "contribution method experiment limitation";
    academySetText("academyCitationEvidence", "正在从论文 chunks 中检索证据...");
    const path = `/api/documents/citation-answer?q=${encodeURIComponent(query)}&category=research&document_id=${Number(academyPaperState.document.id)}&limit=6`;
    const result = await academyApi(path);
    academyRenderCitationEvidence(result);
    academyLoadPaperTimeline(Number(academyPaperState.document.id)).catch(() => null);
  } catch (error) {
    academySetText("academyCitationEvidence", `证据检索失败：${error.message}`);
  }
}

async function academySearchScholar() {
  const query = document.getElementById("academyScholarQuery")?.value?.trim() || "";
  const target = document.getElementById("academyScholarResults");
  if (!query || !target) return;
  academySetText("academyScholarStatus", "Searching scholarly providers...");
  try {
    const result = await academyApi(`/api/research/literature/search?q=${encodeURIComponent(query)}&limit=8`);
    const papers = result.results || [];
    target.innerHTML = papers.length ? papers.map((paper, index) => `
      <article>
        <b>${academyEsc(paper.title || "Untitled paper")}</b>
        <span>${academyEsc([paper.year, paper.venue, paper.doi].filter(Boolean).join(" · "))}</span>
        <small>relevance ${Number(paper.relevance_score || 0).toFixed(3)} · ${academyEsc((paper.sources || []).join(", "))}</small>
        ${paper.open_access_pdf_url ? `<button class="pill" type="button" onclick="academyDownloadScholar(${index})">Download OA PDF & ingest</button>` : ""}
      </article>`).join("") : "<p>No results. Provider attempts are shown in the status.</p>";
    academyPaperState.scholarResults = papers;
    const ok = (result.attempts || []).filter(item => item.ok).length;
    academySetText("academyScholarStatus", `${papers.length} ranked papers · ${ok}/${(result.attempts || []).length} providers available`);
  } catch (error) {
    academySetText("academyScholarStatus", `Scholarly search failed: ${error.message}`);
  }
}

async function academyDownloadScholar(index) {
  const paper = (academyPaperState.scholarResults || [])[Number(index)];
  if (!paper || !window.confirm(`Download and ingest the verified open-access PDF?\n\n${paper.title || "Untitled paper"}`)) return;
  academySetText("academyScholarStatus", "Validating, downloading, and ingesting the open-access PDF...");
  try {
    const result = await academyApi("/api/research/literature/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper, confirmed: true })
    });
    academySetText("academyScholarStatus", `Ingested document #${result.document?.id || "?"}; SHA-256 ${String(result.download?.sha256 || "").slice(0, 12)}...`);
    academyLoadPaperHistory().catch(() => null);
  } catch (error) {
    academySetText("academyScholarStatus", `Download blocked or failed: ${error.message}`);
  }
}

async function academyAnalyzePaperStructure() {
  const documentId = Number(academyPaperState.document?.id || 0);
  const target = document.getElementById("academyPaperIntelligenceResult");
  if (!documentId || !target) {
    academySetText("academyScholarStatus", "Open or upload a local paper first.");
    return;
  }
  academySetText("academyScholarStatus", `Analyzing structure and evidence for doc:${documentId}...`);
  try {
    const result = await academyApi(`/api/research/papers/${documentId}/structure`);
    const q = result.quality || {};
    const sectionNames = Object.entries(result.sections || {}).filter(([, rows]) => rows?.length).map(([name]) => name);
    target.innerHTML = `<b>Paper intelligence score ${Number(q.score || 0).toFixed(1)}</b>
      <p>Sections: ${academyEsc(sectionNames.join(", ") || "none")}</p>
      <p>Claims ${Number(q.claim_count || 0)} · tables ${Number(q.table_count || 0)} · formulas ${Number(q.formula_count || 0)} · references ${Number(q.reference_count || 0)}</p>
      <p>Evidence gate: ${q.checks?.claims_grounded ? "PASS" : "REVISION REQUIRED"}</p>`;
    academySetText("academyScholarStatus", `Paper analysis complete · ${Number(q.score || 0).toFixed(1)}/100`);
  } catch (error) {
    academySetText("academyScholarStatus", `Paper analysis failed: ${error.message}`);
  }
}

function academyGeneratePaperRead() {
  const title = document.getElementById("paperTitle")?.value || "Untitled paper";
  const abstract = academyPaperSnippet();
  const target = document.getElementById("paperDeepReadOutput");
  if (!target) return;
  const terms = abstract.split(/\W+/).filter(Boolean).slice(0, 10).join(" / ");
  const cards = [
    ["概念与定义", "抽取论文核心对象、变量、任务定义、输入输出边界和评价指标。"],
    ["历史工作来源", "追踪传统方法、直接前置论文、数据集来源和被解决/未解决的问题。"],
    ["出发点", "判断论文要解决 factual grounding、效率、泛化、交互、对齐或安全中的哪类矛盾。"],
    ["方法原理", `围绕 ${terms || "核心术语"} 建立机制图：模块、数据流、损失函数、推理路径和失败模式。`],
    ["实验与消融", "拆分数据集、baseline、主指标、消融、鲁棒性、成本、延迟和复现脚本。"],
    ["报告输出", "生成导读、术语表、实验复现计划、局限风险、答辩 Q&A 和知识库入库摘要。"]
  ];
  target.innerHTML = `<h3>${academyEsc(title)}</h3>` + cards.map(([k, v]) => `<article><b>${academyEsc(k)}</b><p>${academyEsc(v)}</p></article>`).join("");
}

function academySendPaperPrompt() {
  const title = document.getElementById("paperTitle")?.value || "AI paper";
  const abstract = document.getElementById("paperAbstract")?.value || "";
  const prompt = encodeURIComponent(`请按 ClawOS AI Academy 论文精读框架生成报告：${title}\n\n${abstract}`);
  location.href = `/console#knowledge?prompt=${prompt}`;
}

let academyReaderScale = 1;
let academyReaderTool = "none";
let academyReaderNotes = JSON.parse(localStorage.getItem("clawos_academy_reader_notes") || "[]").map((note, index) => ({
  ...note,
  id: note.id || `${note.at || "legacy"}-${index}`
}));

function academySetPdfSource(source, page = 1, mode = "fit") {
  const frame = document.getElementById("academyPdfFrame");
  if (!frame || !source) return;
  academyPaperState.frameSource = String(source).split("#")[0];
  academyPaperState.currentPage = Math.max(1, Number(page) || 1);
  if (mode === "fit") academyReaderScale = 1;
  const view = mode === "fit" ? "view=FitH" : `zoom=${Math.round(academyReaderScale * 100)}`;
  frame.src = `${academyPaperState.frameSource}#page=${academyPaperState.currentPage}&${view}`;
  frame.style.width = "100%";
  frame.style.height = "100%";
  frame.style.transform = academyReaderScale === 1 ? "none" : `scale(${academyReaderScale})`;
  document.getElementById("academyReaderEmpty")?.setAttribute("hidden", "");
  window.requestAnimationFrame(academyResizeInkCanvas);
}

function academyRefreshPdfView(mode = "zoom") {
  if (!academyPaperState.frameSource) return;
  const frame = document.getElementById("academyPdfFrame");
  if (!frame) return;
  if (mode === "page") {
    frame.src = `${academyPaperState.frameSource}#page=${academyPaperState.currentPage}&view=FitH`;
    return;
  }
  const scale = mode === "fit" ? 1 : academyReaderScale;
  frame.style.width = "100%";
  frame.style.height = "100%";
  frame.style.transform = scale === 1 ? "none" : `scale(${scale})`;
}

function academyPreviewLocalPaper(file) {
  if (!file) return;
  const frame = document.getElementById("academyPdfFrame");
  if (academyPaperState.pdfUrl) URL.revokeObjectURL(academyPaperState.pdfUrl);
  academyPaperState.pdfUrl = URL.createObjectURL(file);
  if (frame && (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"))) academySetPdfSource(academyPaperState.pdfUrl);
  document.getElementById("academyReaderEmpty")?.setAttribute("hidden", "");
  academySetText("academyReaderProgress", "原文已打开");
  academySetText("academyPaperStatus", `${file.name} 已在本地打开；点击“解析原文”后启用证据检索。`);
}

function academyMirrorPaperFile(input) {
  const target = document.getElementById("academyPaperFile");
  if (target && input?.files?.length) {
    target.files = input.files;
    academyPreviewLocalPaper(input.files[0]);
  }
}

function academyReaderZoom(delta) {
  academyReaderScale = Math.min(2.5, Math.max(.5, Number((academyReaderScale + delta).toFixed(1))));
  academyRefreshPdfView("zoom");
  academySetText("academyReaderZoom", `${Math.round(academyReaderScale * 100)}%`);
  academySetText("academyPaperStatus", `阅读缩放已调整为 ${Math.round(academyReaderScale * 100)}%。`);
  document.getElementById("academyZoomOut")?.toggleAttribute("disabled", academyReaderScale <= .5);
  document.getElementById("academyZoomIn")?.toggleAttribute("disabled", academyReaderScale >= 2.5);
}

function academyReaderFit() {
  academyReaderScale = 1;
  academyRefreshPdfView("fit");
  academySetText("academyReaderZoom", "100%");
  document.getElementById("academyZoomOut")?.removeAttribute("disabled");
  document.getElementById("academyZoomIn")?.removeAttribute("disabled");
  academySetText("academyPaperStatus", "已按阅读区宽度适配原文。");
}

function academyJumpPaperSection(page, button) {
  if (!academyPaperState.frameSource) {
    academySetText("academyPaperStatus", "请先打开 PDF，再使用目录跳转。");
    return;
  }
  academyPaperState.currentPage = Math.max(1, Number(page) || 1);
  document.querySelectorAll(".reader-outline-list button").forEach(item => item.classList.toggle("active", item === button));
  academyRefreshPdfView("page");
  academySetText("academyReaderProgress", `正在阅读第 ${academyPaperState.currentPage} 页`);
  academySetText("academyPaperStatus", `已跳转到第 ${academyPaperState.currentPage} 页。`);
}

function academyToggleOutline() {
  const workspace = document.querySelector(".paper-reader-workspace");
  const button = document.getElementById("academyOutlineToggle");
  if (!workspace) return;
  const collapsed = workspace.classList.toggle("outline-collapsed");
  button?.setAttribute("aria-expanded", String(!collapsed));
  button?.setAttribute("title", collapsed ? "展开目录" : "折叠目录");
}

async function academyToggleReaderFullscreen() {
  const viewer = document.getElementById("academyPaperViewer");
  if (!viewer) return;
  try {
    if (document.fullscreenElement === viewer) await document.exitFullscreen();
    else await viewer.requestFullscreen();
  } catch (error) {
    academySetText("academyPaperStatus", `浏览器未允许全屏：${error.message}`);
  }
}

function academyToggleResearchOps() {
  const panel = document.getElementById("academyResearchOps");
  const button = document.querySelector(".reader-ops-toggle");
  if (!panel) return;
  const opening = panel.hasAttribute("hidden");
  panel.toggleAttribute("hidden", !opening);
  button?.setAttribute("aria-expanded", String(opening));
  if (opening) panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function academySwitchReaderTab(tab) {
  document.querySelectorAll("[data-reader-tab]").forEach(button => button.classList.toggle("active", button.dataset.readerTab === tab));
  document.querySelectorAll("[data-reader-panel]").forEach(panel => panel.classList.toggle("active", panel.dataset.readerPanel === tab));
}

function academySetGuidedPrompt(kind) {
  const prompts = {
    method: "这篇论文的核心机制是什么？它依赖哪些假设，关键变量如何相互作用？",
    evidence: "哪些实验真正支持核心结论？基线、消融、数据和指标是否足够？",
    limits: "方法在什么条件下会失败？作者未验证哪些外推场景或风险？"
  };
  const input = document.getElementById("paperAbstract");
  if (input) { input.value = prompts[kind] || prompts.method; input.focus(); }
}

function academyRenderReaderNotes() {
  const target = document.getElementById("academyReaderNotes");
  if (!target) return;
  target.innerHTML = academyReaderNotes.length ? academyReaderNotes.map(note => `<article><b>${academyEsc(note.tag || "阅读笔记")}</b><p>${academyEsc(note.text)}</p><small>${academyEsc(new Date(note.at || Date.now()).toLocaleString())}</small><button class="reader-note-delete" type="button" aria-label="删除笔记" data-reader-note-id="${academyEsc(note.id)}">×</button></article>`).join("") : `<div class="reader-placeholder"><b>还没有笔记</b><p>写下判断、疑问或复现线索，保存后会保留在这台设备。</p></div>`;
}

function academyAddReaderNote() {
  const input = document.getElementById("academyReaderNote");
  const text = input?.value.trim() || "";
  if (!text) {
    academySetText("academyReaderNoteStatus", "请先输入笔记内容。");
    input?.focus();
    return;
  }
  const now = new Date().toISOString();
  academyReaderNotes.unshift({ id: `${Date.now()}`, text, tag: document.getElementById("academyReaderNoteTag")?.value.trim() || "阅读笔记", at: now, document: document.getElementById("paperTitle")?.value || "" });
  academyReaderNotes = academyReaderNotes.slice(0, 30);
  localStorage.setItem("clawos_academy_reader_notes", JSON.stringify(academyReaderNotes));
  localStorage.removeItem("clawos_academy_reader_note_draft");
  if (input) input.value = "";
  academyRenderReaderNotes();
  academySetText("academyReaderNoteStatus", `笔记已保存 · ${new Date(now).toLocaleTimeString()}`);
}

function academyDeleteReaderNote(noteId) {
  academyReaderNotes = academyReaderNotes.filter(note => String(note.id) !== String(noteId));
  localStorage.setItem("clawos_academy_reader_notes", JSON.stringify(academyReaderNotes));
  academyRenderReaderNotes();
  academySetText("academyReaderNoteStatus", "笔记已删除。");
}

function academySetupReaderNoteDraft() {
  const input = document.getElementById("academyReaderNote");
  if (!input) return;
  const draft = localStorage.getItem("clawos_academy_reader_note_draft") || "";
  if (draft && !input.value) input.value = draft;
  input.addEventListener("input", () => {
    localStorage.setItem("clawos_academy_reader_note_draft", input.value);
    academySetText("academyReaderNoteStatus", input.value.trim() ? "草稿已自动保存。" : "请输入阅读笔记。");
  });
}

function academySetupReaderControls() {
  document.getElementById("academyZoomOut")?.addEventListener("click", () => academyReaderZoom(-.1));
  document.getElementById("academyZoomIn")?.addEventListener("click", () => academyReaderZoom(.1));
  document.getElementById("academyZoomFit")?.addEventListener("click", academyReaderFit);
  document.getElementById("academyReaderFullscreen")?.addEventListener("click", academyToggleReaderFullscreen);
  document.getElementById("academyOutlineToggle")?.addEventListener("click", academyToggleOutline);
  document.getElementById("academySaveReaderNote")?.addEventListener("click", academyAddReaderNote);
  document.querySelectorAll("[data-paper-page]").forEach(button => button.addEventListener("click", () => academyJumpPaperSection(button.dataset.paperPage, button)));
  document.getElementById("academyReaderNotes")?.addEventListener("click", event => {
    const button = event.target.closest("[data-reader-note-id]");
    if (button) academyDeleteReaderNote(button.dataset.readerNoteId);
  });
}

function academyDownloadText(filename, text) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function academyExportReaderNotes() {
  const title = document.getElementById("paperTitle")?.value || "Paper notes";
  const body = academyReaderNotes.map(note => `## ${note.tag}\n\n${note.text}`).join("\n\n");
  academyDownloadText("paper-reading-notes.md", `# ${title}\n\n${body || "尚无阅读笔记。"}\n`);
}

function academyResizeInkCanvas() {
  const canvas = document.getElementById("academyInkCanvas");
  const viewer = document.getElementById("academyPaperViewer");
  if (!canvas || !viewer) return;
  const rect = viewer.getBoundingClientRect();
  const toolbarInset = academyPaperState.frameSource ? 56 : 0;
  const drawableHeight = Math.max(1, rect.height - toolbarInset);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(drawableHeight * ratio));
  canvas.style.top = `${toolbarInset}px`;
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${drawableHeight}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  academyRestoreInk();
}

function academyRestoreInk() {
  const canvas = document.getElementById("academyInkCanvas");
  const viewer = document.getElementById("academyPaperViewer");
  const saved = localStorage.getItem("clawos_academy_paper_annotation");
  if (!canvas || !viewer || !saved) return;
  const image = new Image();
  image.onload = () => {
    const rect = canvas.getBoundingClientRect();
    canvas.getContext("2d").drawImage(image, 0, 0, rect.width, rect.height);
  };
  image.src = saved;
}

function academyCanvasPoint(event) {
  const canvas = document.getElementById("academyInkCanvas");
  const rect = canvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function academyDrawInk(event) {
  if (!academyPaperState.penEnabled || !academyPaperState.drawing) return;
  const canvas = document.getElementById("academyInkCanvas");
  const ctx = canvas.getContext("2d");
  const next = academyCanvasPoint(event);
  const prev = academyPaperState.lastPoint || next;
  ctx.strokeStyle = document.getElementById("academyPenColor")?.value || "#315cf5";
  ctx.globalAlpha = academyReaderTool === "highlight" ? .28 : 1;
  ctx.lineWidth = academyReaderTool === "highlight" ? 18 : 3;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(prev.x, prev.y);
  ctx.lineTo(next.x, next.y);
  ctx.stroke();
  ctx.globalAlpha = 1;
  academyPaperState.lastPoint = next;
}

function academySetupInk() {
  const canvas = document.getElementById("academyInkCanvas");
  if (!canvas) return;
  academyResizeInkCanvas();
  window.addEventListener("resize", academyResizeInkCanvas);
  document.getElementById("academyPenToggle")?.addEventListener("click", event => {
    academyReaderTool = academyReaderTool === "pen" ? "none" : "pen";
    academyPaperState.penEnabled = academyReaderTool !== "none";
    canvas.classList.toggle("active", academyPaperState.penEnabled);
    document.querySelectorAll(".annotation-tools .tool-button").forEach(button => button.classList.remove("active"));
    event.currentTarget.classList.toggle("active", academyReaderTool === "pen");
    academySetText("academyPaperStatus", academyPaperState.penEnabled ? "画笔已开启，可在原文上直接标注。" : "批注工具已关闭。");
  });
  document.getElementById("academyHighlightToggle")?.addEventListener("click", event => {
    academyReaderTool = academyReaderTool === "highlight" ? "none" : "highlight";
    academyPaperState.penEnabled = academyReaderTool !== "none";
    canvas.classList.toggle("active", academyPaperState.penEnabled);
    document.querySelectorAll(".annotation-tools .tool-button").forEach(button => button.classList.remove("active"));
    event.currentTarget.classList.toggle("active", academyReaderTool === "highlight");
    academySetText("academyPaperStatus", academyPaperState.penEnabled ? "荧光笔已开启，可标记关键证据。" : "批注工具已关闭。");
  });
  document.getElementById("academyTextNoteToggle")?.addEventListener("click", () => {
    academySwitchReaderTab("notes");
    document.getElementById("academyReaderNote")?.focus();
  });
  canvas.addEventListener("pointerdown", event => {
    if (!academyPaperState.penEnabled) return;
    academyPaperState.drawing = true;
    academyPaperState.lastPoint = academyCanvasPoint(event);
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", academyDrawInk);
  canvas.addEventListener("pointerup", () => {
    academyPaperState.drawing = false;
    academyPaperState.lastPoint = null;
  });
  document.getElementById("academyClearInk")?.addEventListener("click", () => {
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    localStorage.removeItem("clawos_academy_paper_annotation");
    academySetText("academyPaperStatus", "批注已清除。");
  });
  document.getElementById("academySaveAnnotation")?.addEventListener("click", async () => {
    const dataUrl = canvas.toDataURL("image/png");
    localStorage.setItem("clawos_academy_paper_annotation", dataUrl);
    if (!academyPaperState.document?.id) {
      academySetText("academyPaperStatus", "批注已保存到本地缓存；上传论文后可持久化为 Artifact。");
      return;
    }
    try {
      const title = document.getElementById("paperTitle")?.value || academyPaperState.document.title || "Academy paper annotation";
      const saved = await academyApi("/api/academy/paper/annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: Number(academyPaperState.document.id), title, image_data: dataUrl })
      });
      academyPaperState.annotationArtifact = saved.artifact;
      await academyRefreshPaperPersistedStatus().catch(() => null);
      academySetText("academyPaperStatus", `批注已保存为 Artifact：${saved.artifact?.path || "saved"}`);
    } catch (error) {
      academySetText("academyPaperStatus", `批注已保留在本地缓存，Artifact 保存失败：${error.message}`);
    }
  });
}

function academyGenerateNote() {
  const input = document.getElementById("academyNoteInput")?.value || "今天学习了一个 AI 概念。";
  const target = document.getElementById("academyNoteOutput");
  if (target) {
    target.innerHTML = `<b>Cornell Note</b><p>关键词：${academyEsc(input.slice(0, 56))}</p><p>核心解释：用自己的话重述概念，再写一个例子和一个反例。</p><p>复盘问题：它解决什么问题？依赖什么假设？如何验证？和哪一层图谱相关？</p>`;
  }
}

function academyInsertNotePrompt(kind) {
  const input = document.getElementById("academyNoteInput");
  if (!input) return;
  const prompts = { explain: "\n\n请用自己的话解释：", example: "\n\n例子：\n反例：", question: "\n\n可验证问题：" };
  input.value += prompts[kind] || prompts.explain;
  input.focus();
}

function academyExportNote() {
  const output = document.getElementById("academyNoteOutput")?.innerText || "尚无结构化笔记。";
  academyDownloadText("academy-guided-note.md", `# Academy Guided Note\n\n${output}\n`);
}

function academyRenderCode(topic = "embedding") {
  document.querySelectorAll(".code-lab-tabs button").forEach(btn => btn.classList.toggle("active", btn.dataset.codeTopic === topic));
  const target = document.getElementById("academyCodeBlock");
  if (target) target.textContent = CODE_SNIPPETS[topic] || CODE_SNIPPETS.embedding;
}

function academyCompleteExperiment() {
  academySetText(
    "academyCodeEvidenceStatus",
    "本地草稿不会直接改变掌握度。请运行、测试并通过 TaskRun 项目证据入口提交产物摘要。"
  );
}

async function academyCopyCode() {
  const text = document.getElementById("academyCodeBlock")?.textContent || "";
  await navigator.clipboard?.writeText(text);
}

function academyQueueKnowledge(kind) {
  academyState.ingestQueue.unshift({ kind, time: new Date().toISOString() });
  academyState.ingestQueue = academyState.ingestQueue.slice(0, 5);
  academySave();
  const target = document.getElementById("academyIngestStatus");
  if (target) target.textContent = `已加入知识入库队列：${academyState.ingestQueue.map(item => item.kind).join(" / ")}`;
}

async function academyGenerateQuiz() {
  const grid = document.getElementById("academyQuizGrid");
  if (!grid) return;
  grid.innerHTML = "<article><p>正在加载到期复习题……</p></article>";
  try {
    const quiz = await academyApi("/api/academy/learning/quiz");
    academyState.activeQuiz = quiz;
    const question = quiz.question;
    grid.innerHTML = `<article class="academy-evidence-quiz">
      <b>${academyEsc(question.cognitive_level)} · 难度 ${academyEsc(question.difficulty)}</b>
      <p>${academyEsc(question.prompt)}</p>
      <textarea class="academy-quiz-answer" placeholder="请先作答，再查看评分与缺失概念。至少 24 个字符。"></textarea>
      <button type="button" onclick="academyAnswerQuiz(this, ${Number(question.id)})">提交掌握证据</button>
      <small>答案不会在提交前披露；仅持久化评估或项目证据可以改变掌握度。</small>
    </article>`;
  } catch (error) {
    grid.innerHTML = `<article><b>题目暂不可用</b><p>${academyEsc(error.message)}</p></article>`;
  }
}

async function academyAnswerQuiz(button, questionId) {
  const article = button.closest("article");
  const answer = article?.querySelector(".academy-quiz-answer")?.value || "";
  button.disabled = true;
  try {
    const result = await academyApi(`/api/academy/learning/questions/${questionId}/answers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer })
    });
    article?.classList.add("answered");
    const missing = result.rubric?.missing_concepts || [];
    article?.insertAdjacentHTML("beforeend", `<div class="academy-quiz-result">
      <b>得分 ${Math.round(Number(result.score || 0) * 100)}%</b>
      <p>${missing.length ? `仍需补充：${academyEsc(missing.join(" / "))}` : "本轮概念覆盖通过。"}</p>
      <small>下次复习：${Number(result.next_review_days || 1)} 天后；算法 ${academyEsc(result.model_after?.algorithm_version || "")}</small>
    </div>`);
    await academyLoadLearningDashboard();
  } catch (error) {
    article?.insertAdjacentHTML("beforeend", `<p class="academy-error">${academyEsc(error.message)}</p>`);
    button.disabled = false;
  }
}

function academyResetProgress() {
  academySetText("academyProgress", "掌握证据不能在浏览器中重置；请通过学习记录治理入口操作。");
  academyGenerateQuiz();
}

function academyBoot() {
  academyRenderLayerStrip();
  academyRenderLayerGraph();
  academyRenderProgressNodes();
  academyLoadLearningDashboard().catch(error => {
    academySetText("academyProgress", `学习后端不可用：${error.message}`);
  });
  academyRenderCode("embedding");
  academyGenerateQuiz();
  academySetupInk();
  academyRenderReaderNotes();
  academySetupReaderNoteDraft();
  academySetupReaderControls();
  document.getElementById("academyPaperViewer")?.addEventListener("keydown", event => {
    if (!(event.ctrlKey || event.metaKey)) return;
    if (["+", "="].includes(event.key)) { event.preventDefault(); academyReaderZoom(.1); }
    if (event.key === "-") { event.preventDefault(); academyReaderZoom(-.1); }
    if (event.key === "0") { event.preventDefault(); academyReaderFit(); }
  });
  document.addEventListener("fullscreenchange", () => {
    const active = document.fullscreenElement?.id === "academyPaperViewer";
    document.getElementById("academyReaderFullscreen")?.classList.toggle("active", active);
    document.getElementById("academyReaderFullscreen")?.setAttribute("aria-label", active ? "退出全屏" : "全屏阅读");
  });
  document.getElementById("academyPaperFile")?.addEventListener("change", event => academyPreviewLocalPaper(event.target.files?.[0]));
  academyRenderPaperRuntimeStatus();
  academyRefreshPaperAudit().catch(() => null);
  academyLoadPaperHistory().catch(() => null);
  academyLoadPaperCheckpoints().catch(() => null);
  academyLoadPaperProjectBoard().catch(() => null);
  academyLoadPaperProjectPackages().catch(() => null);
  document.querySelectorAll(".code-lab-tabs button").forEach(btn => btn.addEventListener("click", () => academyRenderCode(btn.dataset.codeTopic)));
}

academyBoot();
