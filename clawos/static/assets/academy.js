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
  completed: new Set(JSON.parse(localStorage.getItem("clawos_academy_completed") || '["foundation"]')),
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
  penEnabled: false,
  drawing: false,
  lastPoint: null
};

function academySave() {
  localStorage.setItem("clawos_academy_completed", JSON.stringify([...academyState.completed]));
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

function academyCompleteNode(key) {
  academyState.completed.add(key);
  academySave();
  academyRenderLayerGraph(document.querySelector(".academy-layer-node.active")?.dataset.layer || key);
}

function academyRenderLayerStrip() {
  const target = document.getElementById("academyLayerStrip");
  if (!target) return;
  target.innerHTML = AI_LAYERS.map((layer, index) => `<a class="${layer.branch ? "branch" : ""}" href="/academy/path#${academyEsc(layer.id)}"><b>${String(index + 1).padStart(2, "0")}</b><span>${academyEsc(layer.short)}</span></a>`).join("");
}

function academyRenderLayerGraph(activeId = location.hash.replace("#", "") || "foundation") {
  const graph = document.getElementById("academyLayerGraph");
  const detail = document.getElementById("academyLayerDetail");
  if (!graph || !detail) return;
  const active = AI_LAYERS.find(layer => layer.id === activeId) || AI_LAYERS[0];
  graph.innerHTML = AI_LAYERS.map((layer, index) => {
    const unlocked = academyState.completed.has(layer.id);
    return `<button class="academy-layer-node ${layer.id === active.id ? "active" : ""} ${layer.branch ? "branch" : ""} ${unlocked ? "unlocked" : ""}" data-layer="${academyEsc(layer.id)}" style="--i:${index}"><b>${academyEsc(layer.short)}</b><span>${academyEsc(layer.title)}</span></button>`;
  }).join("");
  detail.innerHTML = `
    <div><span>${active.branch ? "Optional Branch" : "Main Layer"}</span><h3>${academyEsc(active.title)}</h3><p>${academyEsc(active.summary)}</p></div>
    <section><b>具体内容</b><ul>${active.concepts.map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <section><b>代表资料 / 论文</b><ul>${active.papers.map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <section><b>实验任务</b><ul>${active.experiments.map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <section><b>掌握标准</b><ul>${active.mastery.map(item => `<li>${academyEsc(item)}</li>`).join("")}</ul></section>
    <button class="pill solid dark" type="button" onclick="academyCompleteNode('${academyEsc(active.id)}')">点亮这一层</button>`;
  graph.querySelectorAll(".academy-layer-node").forEach(btn => btn.addEventListener("click", () => {
    history.replaceState(null, "", `#${btn.dataset.layer}`);
    academyRenderLayerGraph(btn.dataset.layer);
  }));
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
  ["nlp_llm", "rag", "governance"].forEach(node => academyState.completed.add(node));
  if (stage === "saved") academyState.completed.add("application");
  academySave();
  academyRenderProgressNodes();
  const saved = academyPaperState.savedKnowledgeId ? `知识库条目 #${academyPaperState.savedKnowledgeId}` : "等待保存知识库";
  academyRenderPaperRuntimeStatus();
  academySetText("academyPaperGraphStatus", `已点亮 NLP/LLM、RAG、Evaluation/Safety 节点；${saved}。`);
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
    if (doc.id && academyPreviewablePaperSource(doc)) frame.src = `/api/documents/${Number(doc.id)}/source`;
    else frame.removeAttribute("src");
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
    if (academyPreviewablePaperSource(doc)) frame.src = `/api/documents/${Number(documentId)}/source`;
    else frame.removeAttribute("src");
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
  if (frame && file.type === "application/pdf") frame.src = academyPaperState.pdfUrl;
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

function academyGeneratePaperRead() {
  const title = document.getElementById("paperTitle")?.value || "Untitled paper";
  const abstract = academyPaperSnippet();
  const target = document.getElementById("paperDeepReadOutput");
  if (!target) return;
  academyState.completed.add("nlp_llm");
  academyState.completed.add("rag");
  academySave();
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

function academyResizeInkCanvas() {
  const canvas = document.getElementById("academyInkCanvas");
  const viewer = document.getElementById("academyPaperViewer");
  if (!canvas || !viewer) return;
  const rect = viewer.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
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
  ctx.strokeStyle = document.getElementById("academyPenColor")?.value || "#2563eb";
  ctx.lineWidth = 3;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(prev.x, prev.y);
  ctx.lineTo(next.x, next.y);
  ctx.stroke();
  academyPaperState.lastPoint = next;
}

function academySetupInk() {
  const canvas = document.getElementById("academyInkCanvas");
  if (!canvas) return;
  academyResizeInkCanvas();
  window.addEventListener("resize", academyResizeInkCanvas);
  document.getElementById("academyPenToggle")?.addEventListener("click", event => {
    academyPaperState.penEnabled = !academyPaperState.penEnabled;
    canvas.classList.toggle("active", academyPaperState.penEnabled);
    event.currentTarget.classList.toggle("solid", academyPaperState.penEnabled);
    academySetText("academyPaperStatus", academyPaperState.penEnabled ? "画笔已开启，可以在论文预览区域直接标注。" : "画笔已关闭。");
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
  academyState.completed.add("foundation");
  academySave();
  if (target) {
    target.innerHTML = `<b>Cornell Note</b><p>关键词：${academyEsc(input.slice(0, 56))}</p><p>核心解释：用自己的话重述概念，再写一个例子和一个反例。</p><p>复盘问题：它解决什么问题？依赖什么假设？如何验证？和哪一层图谱相关？</p>`;
  }
}

function academyRenderCode(topic = "embedding") {
  document.querySelectorAll(".code-lab-tabs button").forEach(btn => btn.classList.toggle("active", btn.dataset.codeTopic === topic));
  const target = document.getElementById("academyCodeBlock");
  if (target) target.textContent = CODE_SNIPPETS[topic] || CODE_SNIPPETS.embedding;
}

function academyCompleteExperiment() {
  academyState.completed.add("infra");
  academyState.completed.add("governance");
  academySave();
}

function academyQueueKnowledge(kind) {
  academyState.ingestQueue.unshift({ kind, time: new Date().toISOString() });
  academyState.ingestQueue = academyState.ingestQueue.slice(0, 5);
  academyState.completed.add("application");
  academySave();
  const target = document.getElementById("academyIngestStatus");
  if (target) target.textContent = `已加入知识入库队列：${academyState.ingestQueue.map(item => item.kind).join(" / ")}`;
}

function academyGenerateQuiz() {
  const questions = [
    ["RAG 最核心的价值是什么？", "把外部证据引入生成过程", "rag"],
    ["为什么需要 rerank？", "提升召回候选的最终证据质量", "infra"],
    ["Agent trace 的作用是什么？", "让规划、工具、产物和门禁可审计", "agent"],
    ["论文精读最容易漏掉什么？", "历史来源、实验设置和失败样本", "nlp_llm"],
    ["企业级验收为什么要记录 failure reason？", "让失败可复现、可返工、可治理", "governance"]
  ];
  const grid = document.getElementById("academyQuizGrid");
  if (!grid) return;
  grid.innerHTML = questions.map((item, index) => `<article><b>Q${index + 1}</b><p>${academyEsc(item[0])}</p><button type="button" onclick="academyAnswerQuiz(this, '${academyEsc(item[2])}')">${academyEsc(item[1])}</button></article>`).join("");
}

function academyAnswerQuiz(button, node) {
  button.closest("article")?.classList.add("answered");
  academyState.completed.add(node);
  academySave();
}

function academyResetProgress() {
  academyState.completed = new Set(["foundation"]);
  academySave();
  academyGenerateQuiz();
}

function academyBoot() {
  academyRenderLayerStrip();
  academyRenderLayerGraph();
  academyRenderProgressNodes();
  academyRenderCode("embedding");
  academyGenerateQuiz();
  academySetupInk();
  academyRenderPaperRuntimeStatus();
  academyRefreshPaperAudit().catch(() => null);
  academyLoadPaperHistory().catch(() => null);
  academyLoadPaperCheckpoints().catch(() => null);
  academyLoadPaperProjectBoard().catch(() => null);
  academyLoadPaperProjectPackages().catch(() => null);
  document.querySelectorAll(".code-lab-tabs button").forEach(btn => btn.addEventListener("click", () => academyRenderCode(btn.dataset.codeTopic)));
}

academyBoot();
