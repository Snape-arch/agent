const API = location.origin;
let currentSession = "default";
let busy = false;
let lastToolCalls = [];
let allTools = [];
let pendingConfirmation = null;
let lastTaskId = null;
let taskEventCursor = 0;
let taskStream = null;
let benchmarkSuites = [];
let knowledgeCategory = "";
let knowledgeItems = [];
let knowledgeDocuments = [];
let lastGeneratedReport = null;
let lastSavedReportKnowledgeId = null;
let lastEnterpriseDelivery = null;
let lastEnterpriseKnowledgeIds = [];
let lastSelfReviewCommittee = null;
let lastCommitteeKnowledgeIds = [];
let lastComplexAcceptanceReport = null;
let lastLiveSearchReport = null;
let editingKnowledgeId = null;
let chatAttachments = [];
let allSkills = [];
let skillVersions = [];
let skillRuns = [];
let skillReviews = [];
let selectedSkillName = "";

const $ = id => document.getElementById(id);
const VIEW_META = {
  chat: ["新聊天", "发起任务，连接工具、知识库、文件和项目上下文"],
  search: ["搜索聊天", "查找历史会话并继续上下文"],
  knowledge: ["知识库", "管理用户主动构建的 RAG 资料、文档和学习沉淀"],
  dash: ["状态总览", "查看模型、工具、任务和记忆系统的运行状态"],
  memory: ["记忆治理", "管理画像、偏好、项目、经验和技能等系统记忆"],
  projects: ["项目", "进入本地项目、科研目录和交付任务"],
  reflection: ["反思循环", "审查任务复盘、改进建议、验证结果和回滚记录"],
  evolution: ["Self-Evolution", "候选生成、自动基准门禁、shadow/canary 灰度和真实质量信号"],
  skills: ["固化技能", "查看可复用工作流、候选版本和执行质量"],
  tools: ["工具路由", "查看本地函数清单、参数结构和调用轨迹"],
  tasks: ["运行轨迹", "跟踪任务取消、重试、恢复、队列领取和事件审计"],
  ops: ["Ops Center", "备份恢复、配置检查、后台 worker 和真实业务长任务"],
  benchmarks: ["冻结基准", "运行离线基准套件，查看通过率和 P95 延迟"],
  scenes: ["场景工作台", "核对会议、科研、办公、学习、Git 和技能治理的交付边界"],
  security: ["权限中心", "查看审批、授权、风险策略和安全审计"]
};
const esc = value => {
  const node = document.createElement("div");
  node.textContent = value ?? "";
  return node.innerHTML;
};

async function api(path, opts) {
  const response = await fetch(API + path, opts || {});
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  return await response.json();
}

function usePrompt(text) {
  const prompt = $("prompt");
  if (!prompt) return;
  prompt.value = text;
  prompt.focus();
}

function projectPromptText(kind) {
  const root = $("projectRootInput")?.value?.trim() || "当前项目";
  const goal = $("projectGoalInput")?.value?.trim() || "给出清晰的项目分析、风险和下一步建议";
  const base = `请基于项目上下文分析：${root}。目标：${goal}。`;
  return ({
    structure: `${base}\n请输出项目结构、关键入口文件、前端/后端/数据/脚本边界，以及用户下一步最该看的文件。`,
    health: `${base}\n请做代码健康检查，包含风险、TODO、测试缺口、前后端职责是否清晰、可演示性问题。`,
    brief: `${base}\n请生成一份项目交付简报，包含当前完成度、可展示能力、缺口、验收命令和答辩说法。`,
    experiment: `${base}\n请设计一个可复现实验，评估工具命中率、任务完成率、延迟、失败原因和可追踪产物。`,
    root: `${base}\n请先确认你会把我上传的项目资料和这个路径作为上下文，再给出项目管理建议。`,
    full: `${base}\n请综合项目结构、质量风险、交付计划和演示路径，给出一份项目管理视角的行动清单。`,
  }[kind] || base);
}

function prepareProjectPrompt(kind) {
  const text = projectPromptText(kind);
  usePrompt(text);
  if ($("projectRequestPreview")) $("projectRequestPreview").textContent = text;
  if ($("projectRequestCard")) $("projectRequestCard").classList.add("ready");
  if ($("projectStatus")) $("projectStatus").textContent = "已生成项目请求，可直接发送到对话，或继续修改项目目标。";
}

function sendPreparedProjectPrompt() {
  const text = $("projectRequestPreview")?.textContent?.trim() || $("prompt")?.value?.trim() || "";
  if (!text || text.includes("点击上方任一项目动作")) {
    if ($("projectStatus")) $("projectStatus").textContent = "请先点击一个项目动作生成请求。";
    return;
  }
  usePrompt(text);
  setView("chat");
  if (!busy) sendMessage();
}

function handleProjectFiles(event) {
  handlePickedFiles(event);
  const count = event.target.files?.length || 0;
  if ($("projectStatus")) $("projectStatus").textContent = count ? `已添加 ${count} 个项目文件到对话附件。` : "未选择文件。";
}

function statusBadge(status) {
  const raw = String(status ?? "").toLowerCase();
  const ok = ["ok", "success", "succeeded", "ready", "true", "passed", "allow"].includes(raw);
  const bad = ["error", "failed", "false", "deny", "canceled", "cancelled"].includes(raw);
  const cls = ok ? "ok" : bad ? "err" : "wait";
  const label = status === true ? "ok" : status === false ? "failed" : String(status || "pending");
  return `<span class="state ${cls}">${esc(label)}</span>`;
}

function table(headers, rows) {
  const head = `<thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${(rows || []).map(row => `<tr>${row.map(cell => {
    if (cell && typeof cell === "object" && "html" in cell) return `<td>${cell.html}</td>`;
    return `<td>${esc(cell)}</td>`;
  }).join("")}</tr>`).join("")}</tbody>`;
  return head + body;
}

function setView(viewName) {
  if (!$("view-" + viewName)) viewName = "chat";
  document.querySelectorAll("button[data-view]").forEach(button => {
    const isActive = button.dataset.view === viewName;
    button.classList.toggle("on", isActive);
    button.setAttribute("aria-current", isActive ? "page" : "false");
  });
  document.querySelectorAll(".view").forEach(view => view.classList.remove("on"));
  const view = $("view-" + viewName);
  if (view) view.classList.add("on");
  if (viewName === "scenes") ensureProfessionalBoard();
  $("viewTitle").textContent = (VIEW_META[viewName] || VIEW_META.chat)[0];
  $("viewSub").textContent = (VIEW_META[viewName] || VIEW_META.chat)[1];
  if (location.hash !== "#" + viewName) history.replaceState(null, "", "#" + viewName);
  closeCommandDrawer();
  refreshAll();
}

document.querySelectorAll("button[data-view]").forEach(button => {
  button.onclick = () => {
    if (button.dataset.action === "new-chat") {
      newChat();
      return;
    }
    setView(button.dataset.view);
  };
});

function toggleSidebar() {
  document.body.classList.toggle("sidebar-collapsed");
}

function md(text) {
  return esc(text || "")
    .replace(/```([\s\S]*?)```/g, "<pre>$1</pre>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(https?:\/\/[^\s<>"'）)]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\n/g, "<br>");
}

function addMessage(role, text, tools) {
  const inner = $("chatInner");
  if (!inner) return;
  if (inner.querySelector(".empty")) inner.innerHTML = "";
  const div = document.createElement("div");
  const isAssistant = role === "assistant";
  div.className = "msg " + (isAssistant ? "agent" : "user");
  const chips = (tools || []).map(t => `<span class="tool ${String(JSON.stringify(t.result || {})).includes("error") ? "err" : ""}">${esc(t.name)}</span>`).join("");
  div.innerHTML = `<div class="message-body">${chips ? `<div class="tool-row">${chips}</div>` : ""}<div class="mc">${md(text)}</div></div>`;
  inner.appendChild(div);
  $("chat").scrollTop = $("chat").scrollHeight;
}

function addAssistantStream() {
  const inner = $("chatInner");
  if (inner.querySelector(".empty")) inner.innerHTML = "";
  const div = document.createElement("div");
  div.className = "msg agent";
  div.innerHTML = `<div class="message-body"><div class="mc"></div></div>`;
  inner.appendChild(div);
  const target = div.querySelector(".mc");
  return text => {
    target.innerHTML = md(text);
    $("chat").scrollTop = $("chat").scrollHeight;
  };
}

function sendMessage() {
  const prompt = $("prompt");
  let text = prompt.value.trim();
  const ready = chatAttachments.filter(item => item.status === "ready");
  if ((!text && !ready.length) || busy) return;
  prompt.value = "";
  const wantsWebSearch = Boolean($("webSearchToggle")?.checked);
  if (wantsWebSearch) {
    text = `${text || "请阅读附件并联网检索相关资料。"}\n\n请先联网搜索可验证来源，回答中保留可点击网页链接，并标出哪些结论来自搜索结果。`;
  }
  const attachments = ready.map(item => ({
    name: item.name,
    type: item.type,
    size: item.size,
    document_id: item.document_id,
    chunk_count: item.chunk_count
  }));
  chatAttachments = chatAttachments.filter(item => item.status === "uploading");
  renderAttachmentTray();
  submitMessage(text || "请阅读附件并给出分析。", wantsWebSearch ? ["web_search"] : [], attachments);
}

async function readChatStream(response, onText, onMeta) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let text = "";
  let meta = {};
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      if (!block.trim() || block.includes("data: [DONE]")) continue;
      const event = (block.match(/^event:\s*(.+)$/m) || [])[1] || "message";
      const data = (block.match(/^data:\s*([\s\S]*)$/m) || [])[1] || "";
      try {
        const payload = JSON.parse(data);
        if (event === "clawos_meta") {
          meta = { ...meta, ...payload };
          onMeta(meta);
          continue;
        }
        const piece = payload.choices?.[0]?.delta?.content || "";
        text += piece;
        onText(text);
      } catch (err) {}
    }
  }
  return { text, meta };
}

async function submitMessage(text, confirmedTools, attachments) {
  busy = true;
  window.activeChatController = new AbortController();
  $("send").disabled = true;
  if ($("stop")) $("stop").disabled = false;
  const names = (attachments || []).map(item => item.name).filter(Boolean);
  const webHint = (confirmedTools || []).includes("web_search") ? "\n\n已开启联网搜索，回答会尽量保留来源链接。" : "";
  addMessage("user", text + webHint + (names.length ? `\n\n附件：${names.join("、")}` : ""));
  const update = addAssistantStream();
  try {
    const response = await fetch(API + "/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: window.activeChatController.signal,
      body: JSON.stringify({
        session_id: currentSession,
        stream: true,
        clawos_confirmed_tools: confirmedTools || [],
        clawos_attachments: attachments || [],
        messages: [{ role: "user", content: text }]
      })
    });
    if (!response.ok) throw new Error("chat " + response.status);
    const contentType = response.headers.get("content-type") || "";
    let data = null;
    let streamMeta = {};
    if (contentType.includes("text/event-stream")) {
      const result = await readChatStream(response, update, meta => {
        streamMeta = meta;
        if (meta.task_id) lastTaskId = meta.task_id;
      });
      data = { clawos: streamMeta, choices: [{ message: { content: result.text } }] };
    } else {
      data = await response.json();
      update(data.choices?.[0]?.message?.content || "");
    }
    const tools = data.clawos?.tool_calls || [];
    lastToolCalls = tools;
    lastTaskId = data.clawos?.task_id || lastTaskId;
    if (data.clawos?.needs_confirmation) {
      const toolNames = tools.map(t => t.name).filter(Boolean);
      const risks = [...new Set(tools.map(t => t.result?.risk_level).filter(Boolean))];
      pendingConfirmation = { text, tools: toolNames, attachments: attachments || [] };
      $("confirmText").textContent = `需要确认：${toolNames.join("、")}${risks.length ? ` · 风险 ${risks.join("/")}` : ""}`;
      $("confirmBar").classList.add("on");
    } else {
      pendingConfirmation = null;
      $("confirmBar").classList.remove("on");
    }
    renderLastTools();
    if (data.clawos?.reflection) renderLastReflection(data.clawos.reflection);
    await loadSessions();
    await refreshAll();
  } catch (err) {
    update(err.name === "AbortError" ? "已停止生成。" : "请求失败：" + err.message);
  } finally {
    busy = false;
    window.activeChatController = null;
    $("send").disabled = false;
    if ($("stop")) $("stop").disabled = true;
    $("prompt").focus();
  }
}

async function stopGeneration() {
  if (window.activeChatController) window.activeChatController.abort();
  if (lastTaskId) {
    try {
      await api(`/api/tasks/${lastTaskId}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "console stop generation", actor_id: "console" })
      });
    } catch (err) {}
  }
}

function confirmPending() {
  if (!pendingConfirmation || busy) return;
  const pending = pendingConfirmation;
  pendingConfirmation = null;
  $("confirmBar").classList.remove("on");
  submitMessage(pending.text, pending.tools, pending.attachments || []);
}

function cancelPending() {
  pendingConfirmation = null;
  $("confirmBar").classList.remove("on");
}

function newChat() {
  currentSession = "s_" + Date.now();
  $("chatInner").innerHTML = `<div class="empty"><b>新的任务空间</b><span>短期上下文已清空，长期 MemoryOS、技能库与反思经验继续共享。</span><div class="quick-grid"><button class="quick" onclick="usePrompt('分析当前项目，并给出下一步开发计划')">分析项目与开发计划</button><button class="quick" onclick="usePrompt('查看我的长期记忆和偏好')">检查 MemoryOS</button></div></div>`;
  loadSessions();
  setView("chat");
}

async function switchSession(id) {
  currentSession = id;
  startTaskStream();
  const data = await api("/api/history/" + encodeURIComponent(id));
  $("chatInner").innerHTML = "";
  (data.messages || []).forEach(message => addMessage(message.role === "assistant" ? "assistant" : "user", message.content));
  renderSessions(window._sessions || []);
  setView("chat");
}

async function loadSessions() {
  try {
    const data = await api("/api/sessions");
    window._sessions = data.sessions || [];
    renderSessions(window._sessions);
    renderSessionSearch();
    renderKnowledgeSessionSelect();
  } catch (err) {}
}

function cleanSessionTitle(raw) {
  const text = String(raw || "").trim();
  if (!text) return "未命名会话";
  if (/^[?？\uFFFD\s]+$/.test(text)) return "未命名会话";
  if ((text.match(/[?？\uFFFD]/g) || []).length >= Math.max(6, Math.floor(text.length * 0.6))) return "未命名会话";
  return text;
}

function sessionTitle(session) {
  return cleanSessionTitle(session.title || session.topic || session.last_message || session.session_id);
}

function sessionTags(session) {
  return (session.tags || []).slice(0, 4).map(tag => `<em>${esc(tag)}</em>`).join("");
}

function renderSessions(list) {
  const rows = list || [];
  $("sessions").innerHTML = rows.map(session => `<div class="session ${session.session_id === currentSession ? "on" : ""}" onclick="switchSession('${esc(session.session_id)}')"><b>${esc(sessionTitle(session).slice(0, 54))}</b>${session.tags?.length ? `<div class="session-tags">${sessionTags(session)}</div>` : ""}</div>`).join("") || '<div class="session">暂无会话</div>';
}

function renderSessionSearch() {
  const target = $("sessionSearchList");
  if (!target) return;
  const query = ($("sessionQuery")?.value || "").toLowerCase();
  const rows = (window._sessions || []).filter(session => {
    const haystack = [session.title, session.topic, session.last_message, session.session_id, ...(session.tags || [])].join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });
  target.innerHTML = rows.map(session => `<button class="session-result" onclick="switchSession('${esc(session.session_id)}')"><b>${esc(sessionTitle(session).slice(0, 96))}</b><span>${esc(session.updated_at || session.session_id)}</span>${session.tags?.length ? `<div class="session-tags">${sessionTags(session)}</div>` : ""}</button>`).join("") || '<div class="empty-state">暂无匹配会话</div>';
}

function chooseLocalFile() {
  $("filePicker")?.click();
}

function renderAttachmentTray() {
  const tray = $("attachmentTray");
  if (!tray) return;
  tray.classList.toggle("on", chatAttachments.length > 0);
  tray.innerHTML = chatAttachments.map(item => {
    const loading = item.status === "loading";
    const label = loading ? "上传解析中" : item.status === "error" ? "解析失败" : `${item.chunk_count || 0} chunks`;
    return `<div class="attachment-chip ${loading ? "loading" : ""} ${item.status === "error" ? "error" : ""}"><span class="attachment-spinner"></span><b>${esc(item.name)}</b><small>${esc(label)}</small><button type="button" onclick="removeAttachment('${esc(item.id)}')" title="移除附件">×</button></div>`;
  }).join("");
}

function removeAttachment(id) {
  chatAttachments = chatAttachments.filter(item => item.id !== id);
  renderAttachmentTray();
}

async function uploadDocuments(files, category) {
  const form = new FormData();
  files.forEach(file => form.append("files", file));
  form.append("category", category || "domain");
  const response = await fetch(API + "/api/documents/upload", { method: "POST", body: form });
  if (!response.ok) throw new Error("upload " + response.status);
  return await response.json();
}

async function handlePickedFiles(event) {
  const files = [...(event.target.files || [])].slice(0, 6);
  if (!files.length) return;
  const pending = files.map(file => ({
    id: "att_" + Date.now() + "_" + Math.random().toString(16).slice(2),
    name: file.name,
    type: file.type || "application/octet-stream",
    size: file.size,
    status: "loading",
    document_id: null,
    chunk_count: 0
  }));
  chatAttachments = [...chatAttachments, ...pending];
  renderAttachmentTray();
  try {
    const data = await uploadDocuments(files, "chat");
    (data.documents || []).forEach((doc, index) => {
      const item = pending[index];
      if (!item) return;
      item.document_id = doc.id;
      item.chunk_count = doc.chunk_count || 0;
      item.status = "ready";
      item.name = doc.filename || doc.title || item.name;
    });
    (data.errors || []).forEach((error, index) => {
      const item = pending[(data.documents || []).length + index];
      if (item) {
        item.status = "error";
        item.name = `${item.name || "文件"} · ${error.error}`;
      }
    });
  } catch (err) {
    pending.forEach(item => {
      item.status = "error";
      item.name = `${item.name} · 上传失败`;
    });
  }
  renderAttachmentTray();
  $("prompt").focus();
  event.target.value = "";
}

function setMemoryType(type) {
  if ($("memType")) $("memType").value = type;
  document.querySelectorAll(".library-tabs button[data-mem]").forEach(button => {
    button.classList.toggle("on", button.dataset.mem === type);
  });
}

function setKnowledgeCategory(category) {
  knowledgeCategory = category || "";
  if ($("knowledgeCategory")) $("knowledgeCategory").value = category || "domain";
  document.querySelectorAll(".library-tabs button[data-knowledge]").forEach(button => {
    button.classList.toggle("on", (button.dataset.knowledge === "all" && !knowledgeCategory) || button.dataset.knowledge === knowledgeCategory);
  });
  renderKnowledgeWorkspaceShell();
  loadKnowledge();
  loadKnowledgeDocuments();
  loadOcrQueue();
  loadKnowledgeGraph();
}

function knowledgeCategoryLabel(category) {
  return ({ research: "科研库", learning: "学习库", writing: "写作库", project: "项目库", domain: "通用库" }[category || ""] || "全部知识库");
}

const KNOWLEDGE_MODES = {
  all: {
    eyebrow: "Personal Knowledge Graph",
    title: "全部知识库",
    desc: "统一查看你的资料节点、图谱关系、上传入口和最近沉淀内容。",
    upload: "论文、课程笔记、项目文档、会议纪要都会进入当前库，并生成可检索节点。",
    actions: [["上传资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索节点", "searchKnowledge()", "secondary"]],
  },
  research: {
    eyebrow: "Research Library",
    title: "科研库",
    desc: "面向论文、实验、引用和研究问题，优先展示论文节点、证据关系和可复现材料。",
    upload: "上传论文 PDF、arXiv 笔记、实验记录或引用材料，自动沉淀为研究节点。",
    actions: [["上传论文", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["生成论文报告", "generateKnowledgeReport()", "secondary"]],
  },
  learning: {
    eyebrow: "Learning Library",
    title: "学习库",
    desc: "面向课程、路线、概念卡片和自测复盘，帮助你从资料走向掌握。",
    upload: "上传课程讲义、学习笔记、术语表或练习材料，形成学习路径节点。",
    actions: [["上传课程资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["生成学习笔记", "generateKnowledgeReport()", "secondary"]],
  },
  writing: {
    eyebrow: "Writing Library",
    title: "写作库",
    desc: "面向博客、答辩稿、商业计划书和表达素材，突出草稿、论点和引用。",
    upload: "上传草稿、素材、会议结论或参考文章，沉淀为可复用写作节点。",
    actions: [["上传写作素材", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["从会话生成草稿", "draftKnowledgeFromSelectedSession()", "secondary"]],
  },
  project: {
    eyebrow: "Project Library",
    title: "项目库",
    desc: "面向本地项目、交付包、runbook、验收报告和风险清单，服务真实交付。",
    upload: "上传项目文档、架构图说明、验收报告或 runbook，形成交付节点。",
    actions: [["上传项目资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["运行交付室", "runEnterpriseDeliveryRoom()", "secondary"]],
  },
};

function renderKnowledgeWorkspaceShell() {
  const mode = knowledgeCategory || "all";
  const config = KNOWLEDGE_MODES[mode] || KNOWLEDGE_MODES.all;
  const workspace = document.querySelector("#view-knowledge .knowledge-workspace");
  if (workspace) workspace.dataset.mode = mode;
  if ($("knowledgeFrontStage")) $("knowledgeFrontStage").dataset.mode = mode;
  if ($("knowledgeModeEyebrow")) $("knowledgeModeEyebrow").textContent = config.eyebrow;
  if ($("knowledgeModeTitle")) $("knowledgeModeTitle").textContent = config.title;
  if ($("knowledgeModeDesc")) $("knowledgeModeDesc").textContent = config.desc;
  if ($("knowledgeUploadHint")) $("knowledgeUploadHint").textContent = config.upload;
  if ($("knowledgeModeActions")) {
    $("knowledgeModeActions").innerHTML = config.actions.map(([label, action, kind]) => `<button class="${kind}" onclick="${action}">${esc(label)}</button>`).join("");
  }
}

function toggleKnowledgeAdminTools() {
  const workspace = document.querySelector("#view-knowledge .knowledge-workspace");
  if (workspace) workspace.classList.toggle("show-knowledge-admin");
}

function renderKnowledgeSessionSelect() {
  const select = $("knowledgeSessionSelect");
  if (!select) return;
  const sessions = window._sessions || [];
  select.innerHTML = sessions.map(session => `<option value="${esc(session.session_id)}">${esc(sessionTitle(session).slice(0, 48))}</option>`).join("") || '<option value="">暂无历史会话</option>';
}

function formatTags(raw) {
  try {
    const tags = Array.isArray(raw) ? raw : JSON.parse(raw || "[]");
    return tags.slice(0, 4).join(" / ");
  } catch (err) {
    return String(raw || "");
  }
}

async function loadKnowledge() {
  const target = $("knowledgeTable");
  if (!target) return;
  try {
    const query = knowledgeCategory ? "?category=" + encodeURIComponent(knowledgeCategory) : "";
    const data = await api("/api/knowledge" + query);
    knowledgeItems = data.items || [];
    target.innerHTML = table(["标题", "库", "来源", "标签", "访问", "操作"], knowledgeItems.map(item => [
      item.title,
      knowledgeCategoryLabel(item.category),
      item.source || "",
      formatTags(item.tags),
      item.access_count || 0,
      { html: `<button class="secondary" onclick="loadKnowledgeItem(${Number(item.id)})">编辑</button> <button class="secondary" onclick="appendKnowledgeToPrompt(${Number(item.id)})">追问</button> <button class="secondary" onclick="deleteKnowledgeItem(${Number(item.id)})">删除</button>` }
    ]));
    renderKnowledgeMap(knowledgeItems);
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `${knowledgeCategoryLabel(knowledgeCategory)} · ${knowledgeItems.length} 条资料`;
  } catch (err) {
    target.innerHTML = table(["标题", "库", "来源", "标签", "访问", "操作"], []);
    renderKnowledgeMap([]);
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "知识库加载失败：" + err.message;
  }
}

function renderKnowledgeMap(items) {
  const map = $("knowledgeMap");
  if (!map) return;
  const rows = (items || []).slice(0, 12);
  map.innerHTML = rows.map((item, index) => `<button class="map-node ${index === 0 ? "core" : ""}" style="left:${12 + (index % 4) * 25}%;top:${14 + Math.floor(index / 4) * 26}%"><b>${esc(String(item.title || "知识").slice(0, 18))}</b><span>${esc(knowledgeCategoryLabel(item.category))}</span></button>`).join("") || '<div class="empty-state">暂无知识节点</div>';
}

async function loadKnowledgeItem(id) {
  const item = knowledgeItems.find(row => Number(row.id) === Number(id));
  if (!item) return;
  editingKnowledgeId = id;
  $("knowledgeTitle").value = item.title || "";
  $("knowledgeContent").value = item.content || "";
  $("knowledgeSource").value = item.source || "";
  $("knowledgeCategory").value = item.category || "domain";
  $("knowledgeStatus").textContent = "正在编辑知识条目";
}

function clearKnowledgeEditor() {
  editingKnowledgeId = null;
  ["knowledgeTitle", "knowledgeContent", "knowledgeSource"].forEach(id => {
    if ($(id)) $(id).value = "";
  });
  if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "等待导入或编辑";
}

function inferKnowledgeTags(text) {
  const lower = String(text || "").toLowerCase();
  const tags = [];
  if (lower.includes("paper") || lower.includes("论文")) tags.push("paper");
  if (lower.includes("report") || lower.includes("报告")) tags.push("report");
  if (lower.includes("agent")) tags.push("agent");
  return tags.length ? tags : ["manual"];
}

async function saveKnowledge() {
  const title = $("knowledgeTitle").value.trim();
  const content = $("knowledgeContent").value.trim();
  if (!title || !content) {
    $("knowledgeStatus").textContent = "请先填写标题和内容";
    return;
  }
  const body = {
    title,
    content,
    category: $("knowledgeCategory").value || "domain",
    source: $("knowledgeSource").value.trim() || "manual",
    tags: inferKnowledgeTags(title + " " + content)
  };
  const path = editingKnowledgeId ? `/api/knowledge/${editingKnowledgeId}` : "/api/knowledge";
  await api(path, {
    method: editingKnowledgeId ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  clearKnowledgeEditor();
  knowledgeCategory = body.category === "domain" ? "" : body.category;
  await loadKnowledge();
  await searchKnowledge();
}

async function searchKnowledge() {
  const target = $("knowledgeSearchTable");
  if (!target) return;
  const query = $("knowledgeQuery").value.trim();
  if (!query) {
    target.innerHTML = table(["标题", "库", "内容", "来源"], []);
    return;
  }
  const category = knowledgeCategory ? "&category=" + encodeURIComponent(knowledgeCategory) : "";
  const data = await api("/api/knowledge/search?q=" + encodeURIComponent(query) + category + "&limit=12");
  target.innerHTML = table(["标题", "库", "内容", "来源"], (data.items || []).map(item => [
    item.title,
    knowledgeCategoryLabel(item.category),
    String(item.content || "").slice(0, 180),
    item.source || ""
  ]));
}

async function handleKnowledgeFiles(event) {
  const files = [...(event.target.files || [])];
  if (!files.length) return;
  const category = $("knowledgeCategory")?.value || knowledgeCategory || "domain";
  if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `正在上传并解析 ${files.length} 个文件`;
  try {
    const data = await uploadDocuments(files.slice(0, 12), category);
    const docs = data.documents || [];
    const errors = data.errors || [];
    const pdfDocs = docs.filter(doc => String(doc.status || "") === "ready" && String(doc.filename || doc.file_path || "").toLowerCase().endsWith(".pdf"));
    const chunks = docs.reduce((count, doc) => count + Number(doc.chunk_count || 0), 0);
    const next = pdfDocs.length ? "，已自动选中 PDF，可选择报告样式并点击生成报告。" : "。如需生成报告，请上传可读取的 PDF 资料。";
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `已解析 ${docs.length} 个文件，生成 ${chunks} 个分块${errors.length ? `，${errors.length} 个失败` : ""}${next}`;
    knowledgeCategory = category === "domain" ? "" : category;
    await loadKnowledge();
    await loadKnowledgeDocuments(pdfDocs[0]?.id);
    if (pdfDocs.length && $("reportResult")) $("reportResult").textContent = "已自动选中 PDF，选择样式后点击生成报告。";
    await searchKnowledge();
  } catch (err) {
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "文件解析失败：" + err.message;
  }
  event.target.value = "";
}

async function draftKnowledgeFromSelectedSession() {
  const sid = $("knowledgeSessionSelect")?.value;
  if (!sid) {
    $("knowledgeStatus").textContent = "请先选择一个历史会话";
    return;
  }
  const data = await api("/api/history/" + encodeURIComponent(sid) + "?limit=24");
  const session = (window._sessions || []).find(item => item.session_id === sid) || {};
  const lines = (data.messages || []).map(message => `${message.role === "assistant" ? "ClawOS" : "用户"}：${message.content}`).join("\n\n");
  $("knowledgeTitle").value = (sessionTitle(session) || "会话沉淀").slice(0, 80);
  $("knowledgeSource").value = "chat:" + sid;
  $("knowledgeContent").value = `# ${$("knowledgeTitle").value}\n\n## 对话摘要草稿\n\n${lines.slice(0, 10000)}`;
  $("knowledgeStatus").textContent = "已生成草稿，请编辑确认后保存";
  setView("knowledge");
}

async function appendKnowledgeToPrompt(id) {
  const item = knowledgeItems.find(row => Number(row.id) === Number(id));
  if (item) usePrompt(`请基于知识条目「${item.title}」回答：`);
  setView("chat");
}

async function deleteKnowledgeItem(id) {
  await api(`/api/knowledge/${Number(id)}`, { method: "DELETE" });
  await loadKnowledge();
  await searchKnowledge();
}

function renderObsidianCheck(data) {
  const target = $("obsidianCheckTable");
  if (!target) return;
  const checks = data?.checks || [];
  const rows = checks.map(check => [check.name || "", { html: statusBadge(check.passed ? "success" : "failed") }, check.detail || ""]);
  rows.unshift(["总分", `${Math.round(Number(data?.score || 0) * 100)} / 100`, `${data?.note_count || 0} notes · ${data?.wikilink_count || 0} links · ${data?.backlink_count || 0} backlinks · ${data?.graph?.edges || 0} graph edges`]);
  target.innerHTML = table(["项目", "状态", "说明"], rows);
  if ($("obsidianStatus")) $("obsidianStatus").textContent = data?.ok ? `通过 · ${Math.round(Number(data.score || 0) * 100)} 分` : `需补强 · ${Math.round(Number(data?.score || 0) * 100)} 分`;
}

async function checkObsidianVault() {
  const category = knowledgeCategory ? "?category=" + encodeURIComponent(knowledgeCategory) : "";
  if ($("obsidianStatus")) $("obsidianStatus").textContent = "正在检查双链笔记结构";
  try {
    const data = await api("/api/knowledge/obsidian/check" + category);
    renderObsidianCheck(data);
    await loadKnowledgeGraph();
  } catch (err) {
    $("obsidianStatus").textContent = "笔记库检查失败：" + err.message;
  }
}

async function exportObsidianVault() {
  const output_dir = ($("obsidianExportDir")?.value || "").trim();
  if ($("obsidianStatus")) $("obsidianStatus").textContent = "正在导出 Markdown 笔记库";
  try {
    const data = await api("/api/knowledge/obsidian/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: knowledgeCategory, output_dir })
    });
    renderObsidianCheck(data);
    $("obsidianStatus").textContent = `已导出 ${data.file_count || 0} 个文件：${data.output_dir || ""}`;
    await loadKnowledgeGraph();
  } catch (err) {
    $("obsidianStatus").textContent = "笔记库导出失败：" + err.message;
  }
}

function reportReadyDocuments() {
  return (knowledgeDocuments || []).filter(doc => String(doc.status || "") === "ready" && String(doc.filename || doc.file_path || "").toLowerCase().endsWith(".pdf"));
}

function renderDocumentReportSelect(preferredId) {
  const select = $("reportDocumentSelect");
  if (!select) return;
  const docs = reportReadyDocuments();
  const selected = String(preferredId || select.value || "");
  select.innerHTML = docs.map(doc => `<option value="${Number(doc.id)}">${esc((doc.title || doc.filename || "PDF 资料").slice(0, 64))}</option>`).join("") || '<option value="">请先上传 PDF 资料</option>';
  if (selected && docs.some(doc => String(doc.id) === selected)) select.value = selected;
  const result = $("reportResult");
  if (result && !docs.length) result.textContent = "当前库没有可生成报告的 PDF 资料。";
  else if (result && result.textContent === "当前库没有可生成报告的 PDF 资料。") result.textContent = "已找到 PDF 资料，选择样式后点击生成报告。";
}

async function loadKnowledgeDocuments(preferredId) {
  const query = knowledgeCategory ? "?category=" + encodeURIComponent(knowledgeCategory) : "";
  try {
    const data = await api("/api/documents" + query);
    knowledgeDocuments = data.documents || [];
    renderDocumentReportSelect(preferredId);
  } catch (err) {
    knowledgeDocuments = [];
    renderDocumentReportSelect();
    if ($("reportResult")) $("reportResult").textContent = "资料列表加载失败：" + err.message;
  }
}

function renderKnowledgeReportResult(data) {
  lastGeneratedReport = data;
  lastSavedReportKnowledgeId = null;
  const report = data.report || {};
  const doc = data.document || {};
  const library = data.library_document || {};
  const rows = [
    ["资料", library.title || doc.title || ""],
    ["Markdown", report.markdown_path || "未生成"],
    ["PDF", report.pdf_path || "未生成"],
    ["输出目录", report.output_dir || ""],
    ["样式", report.metadata?.report_style || ""],
    ["问题数", report.question_count || 0]
  ];
  $("reportResult").innerHTML = `<div class="report-flow"><b>报告已生成</b><span>下一步：保存到知识库，然后可导出 Markdown 笔记库或继续追问。</span><div class="report-flow-steps"><span class="done">1 生成报告</span><span>2 保存知识库</span><span>3 导出笔记库</span><span>4 继续追问</span></div><div class="action-row"><button class="primary" onclick="saveGeneratedReportToKnowledge()">保存到知识库</button><button class="secondary" onclick="exportObsidianVault()">导出笔记库</button></div></div>` + table(["项目", "结果"], rows) + `<div class="report-preview">${md(data.preview || "")}</div>`;
}

function reportGenerationError(err) {
  const message = String(err?.message || "").trim();
  if (message.includes("404")) return "报告生成失败：没有找到这份资料，请刷新资料列表后重试。";
  if (message.includes("415") || message.includes("unsupported")) return "报告生成失败：当前只支持可读取的 PDF 资料，请换一个 PDF 后重试。";
  return `报告生成失败：${message || "生成服务没有返回明确原因"}。请确认资料是可读取的 PDF，或换一个输出目录后重试。`;
}

async function generateKnowledgeReport() {
  const documentId = $("reportDocumentSelect")?.value;
  if (!documentId) {
    if ($("reportResult")) $("reportResult").textContent = "请先上传并选择一个 PDF 资料";
    return;
  }
  const depth = Number($("reportDepthPreset")?.value || 5);
  const body = {
    library_document_id: Number(documentId),
    report_style: $("reportStylePreset")?.value || "journal",
    depth,
    question_count: depth * 8,
    output_dir: ($("reportOutputDir")?.value || "output/reports").trim() || "output/reports",
    formats: ["markdown", "pdf"]
  };
  if ($("reportResult")) $("reportResult").textContent = "正在生成报告...";
  try {
    const data = await api("/api/workspace/research/learning-analysis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    renderKnowledgeReportResult(data);
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "报告已生成，可继续导出 Markdown 笔记库或在聊天中追问。";
  } catch (err) {
    if ($("reportResult")) $("reportResult").textContent = reportGenerationError(err);
  }
}

async function saveGeneratedReportToKnowledge() {
  if (!lastGeneratedReport) {
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "请先生成报告";
    return;
  }
  const report = lastGeneratedReport.report || {};
  const doc = lastGeneratedReport.library_document || lastGeneratedReport.document || {};
  const style = report.metadata?.report_style || $("reportStylePreset")?.value || "journal";
  const title = `${doc.title || "资料报告"} · ${style}`;
  const sourceTitle = String(doc.title || "").trim();
  const sourceLink = sourceTitle ? `Related source: [[${sourceTitle} #1]]` : "";
  const content = [`# ${title}`, "", `Markdown: ${report.markdown_path || ""}`, `PDF: ${report.pdf_path || ""}`, `Output: ${report.output_dir || ""}`, `Style: ${style}`, sourceLink, "", "## Preview", lastGeneratedReport.preview || ""].filter(Boolean).join("\n");
  const saved = await api("/api/knowledge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content, category: knowledgeCategory || doc.category || "research", source: report.markdown_path || "generated-report", tags: ["report", style, "generated"] })
  });
  lastSavedReportKnowledgeId = saved.item?.id || null;
  if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "报告已保存到知识库，可继续导出 Markdown 笔记库";
  await loadKnowledge();
  await loadKnowledgeGraph();
  if (lastSavedReportKnowledgeId) {
    const flow = $("reportResult")?.querySelector(".report-flow");
    if (flow) {
      flow.querySelector(".report-flow-steps")?.insertAdjacentHTML("beforeend", `<span class="done">已保存</span>`);
      flow.insertAdjacentHTML("beforeend", `<div class="action-row"><button class="primary" onclick="appendKnowledgeToPrompt(${Number(lastSavedReportKnowledgeId)})">继续追问这个报告</button></div>`);
    }
  }
}

function renderEnterpriseDeliveryResult(data) {
  lastEnterpriseDelivery = data;
  lastEnterpriseKnowledgeIds = [];
  const payload = data?.result || data?.data || data || {};
  const rows = [
    ["交付包目录", payload.package_dir || ""],
    ["成熟度", `${payload.readiness_score ?? "--"} / 100`],
    ["缺口", (payload.missing || []).join(", ") || "none"],
    ["知识条目", (payload.knowledge_items || []).length],
    ["能力证据", payload.evidence_counts?.capability ?? 0],
    ["验收证据", payload.evidence_counts?.validation ?? 0],
    ["风险证据", payload.evidence_counts?.risk ?? 0]
  ];
  const files = payload.files || {};
  const fileRows = Object.keys(files).map(key => [key, files[key]]);
  $("enterpriseDeliveryResult").innerHTML =
    `<div class="report-flow"><b>交付包已生成</b><span>下一步：保存到项目知识库，然后可在聊天中追问答辩、风险和演示主线。</span><div class="report-flow-steps"><span class="done">1 生成交付包</span><span>2 保存知识库</span><span>3 继续追问</span></div><div class="action-row"><button class="primary" onclick="saveEnterpriseDeliveryToKnowledge()">保存到知识库</button><button class="secondary" onclick="askEnterpriseDeliveryQuestion()">继续追问</button></div></div>` +
    table(["项目", "结果"], rows) +
    table(["文件", "路径"], fileRows);
}

function enterpriseDeliveryPayload() {
  return lastEnterpriseDelivery?.result || lastEnterpriseDelivery?.data || lastEnterpriseDelivery || {};
}

async function runEnterpriseDeliveryRoom() {
  const outputDir = ($("enterpriseOutputDir")?.value || "output/delivery").trim() || "output/delivery";
  const params = {
    output_dir: outputDir,
    project_name: ($("enterpriseProjectName")?.value || "ClawOS").trim() || "ClawOS",
    scenario: ($("enterpriseScenario")?.value || "MTClaw competition enterprise delivery").trim() || "MTClaw competition enterprise delivery"
  };
  if ($("enterpriseDeliveryStatus")) $("enterpriseDeliveryStatus").textContent = "正在生成企业交付包";
  if ($("enterpriseDeliveryResult")) $("enterpriseDeliveryResult").textContent = "正在读取项目材料、架构、验收证据和风险记录...";
  try {
    const data = await api("/api/skills/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "clawos_enterprise_delivery_room", params, plan_only: false })
    });
    const result = data?.outputs?.[0]?.result || data?.result || data;
    renderEnterpriseDeliveryResult({ result });
    if ($("enterpriseDeliveryStatus")) $("enterpriseDeliveryStatus").textContent = `已生成交付包 · readiness ${result.readiness_score ?? "--"}/100`;
  } catch (err) {
    if ($("enterpriseDeliveryStatus")) $("enterpriseDeliveryStatus").textContent = "企业交付包生成失败：" + err.message;
    if ($("enterpriseDeliveryResult")) $("enterpriseDeliveryResult").textContent = "生成失败：" + err.message;
  }
}

async function saveEnterpriseDeliveryToKnowledge() {
  const payload = enterpriseDeliveryPayload();
  const items = payload.knowledge_items || [];
  if (!items.length) {
    if ($("enterpriseDeliveryStatus")) $("enterpriseDeliveryStatus").textContent = "请先生成企业交付包";
    return;
  }
  if ($("enterpriseDeliveryStatus")) $("enterpriseDeliveryStatus").textContent = "正在保存交付包到项目知识库";
  const savedIds = [];
  for (const item of items) {
    const saved = await api("/api/knowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: item.title,
        content: item.content,
        category: item.category || "project",
        source: item.source || "enterprise-delivery",
        tags: item.tags || ["enterprise-delivery", "generated"],
        confidence: 0.9
      })
    });
    if (saved.item?.id) savedIds.push(saved.item.id);
  }
  lastEnterpriseKnowledgeIds = savedIds;
  knowledgeCategory = "project";
  if ($("knowledgeCategory")) $("knowledgeCategory").value = "project";
  if ($("enterpriseDeliveryStatus")) $("enterpriseDeliveryStatus").textContent = `已保存 ${savedIds.length} 个交付条目到项目知识库`;
  await loadKnowledge();
  await loadKnowledgeGraph();
  if ($("enterpriseDeliveryResult")) {
    const flow = $("enterpriseDeliveryResult").querySelector(".report-flow");
    if (flow && savedIds.length) {
      flow.querySelector(".report-flow-steps")?.insertAdjacentHTML("beforeend", `<span class="done">已保存 ${savedIds.length} 条</span>`);
    }
  }
}

function askEnterpriseDeliveryQuestion() {
  const payload = enterpriseDeliveryPayload();
  const title = payload.project_name || $("enterpriseProjectName")?.value || "ClawOS";
  const question = `请基于项目知识库中的 ${title} 企业交付包，模拟评委视角提出 5 个最尖锐问题，并给出有证据的答辩回答。`;
  usePrompt(question);
  setView("chat");
}

function formatMs(value) {
  const number = Number(value || 0);
  return `${Math.round(number)} ms`;
}

function renderComplexAcceptanceReport(data) {
  lastComplexAcceptanceReport = data;
  const target = $("acceptanceReportResult");
  if (!target) return;
  if (!data?.found) {
    target.innerHTML = `<div class="acceptance-report-card"><b>未找到验收报告</b><span>${esc(data?.message || "output 下还没有 DeepSeek+Qwen 验收报告。")}</span><code>${esc(data?.report_path || "")}</code></div>`;
    return;
  }
  const benchmark = data.benchmark || {};
  const metrics = benchmark.metrics || {};
  const caseRows = (data.cases || []).map(item => [
    item.scenario || item.name || "",
    { html: statusBadge(item.pass ? "pass" : "fail") },
    item.citation_hit ? "hit" : "miss",
    formatMs(item.latency_ms),
    `v${item.vector_rank || "-"} / r${item.rerank_rank || "-"}`
  ]);
  const metricRows = [
    ["Pass rate", `${Math.round(Number(metrics.pass_rate || 0) * 100)}%`],
    ["Citation hit", `${Math.round(Number(metrics.citation_hit_rate || 0) * 100)}%`],
    ["Latency P50", formatMs(metrics.latency_p50_ms)],
    ["Latency P95", formatMs(metrics.latency_p95_ms)],
    ["Judge grounded", `${Math.round(Number(metrics.judge_grounded_rate || 0) * 100)}%`],
    ["Cases", benchmark.case_count || (data.cases || []).length]
  ];
  target.innerHTML =
    `<div class="acceptance-report-card">
      <div><b>${esc(benchmark.name || "deepseek-qwen acceptance")}</b><span>${statusBadge(data.ok ? "pass" : "fail")} ${esc(data.model || "")}</span></div>
      <code>${esc(data.report_path || "")}</code>
    </div>` +
    `<div class="acceptance-metric-grid">${metricRows.map(row => `<div class="acceptance-metric"><span>${esc(row[0])}</span><b>${esc(row[1])}</b></div>`).join("")}</div>` +
    table(["Scenario", "Pass", "Citation", "Latency", "Retrieval"], caseRows);
}

async function loadComplexAcceptanceReport() {
  if ($("acceptanceReportStatus")) $("acceptanceReportStatus").textContent = "正在读取最新 DeepSeek + Qwen 复杂任务验收报告...";
  try {
    const data = await api("/api/acceptance/deepseek-qwen/latest");
    renderComplexAcceptanceReport(data);
    const metrics = data.benchmark?.metrics || {};
    if ($("acceptanceReportStatus")) {
      $("acceptanceReportStatus").textContent = data.found
        ? `5 类任务 ${metrics.passed_count || 0}/${data.benchmark?.case_count || 0} pass · citation ${Math.round(Number(metrics.citation_hit_rate || 0) * 100)}% · P95 ${formatMs(metrics.latency_p95_ms)}`
        : data.message || "未找到验收报告";
    }
  } catch (err) {
    if ($("acceptanceReportStatus")) $("acceptanceReportStatus").textContent = "验收卡片读取失败：" + err.message;
    if ($("acceptanceReportResult")) $("acceptanceReportResult").textContent = "读取失败：" + err.message;
  }
}

function renderLiveSearchReport(data) {
  lastLiveSearchReport = data;
  const target = $("liveSearchReportResult");
  if (!target) return;
  if (!data?.found) {
    target.innerHTML = `<div class="acceptance-report-card"><b>未找到联网验收报告</b><span>${esc(data?.message || "output/search_evidence 下还没有 live_search_report.json。")}</span><code>${esc(data?.report_path || "")}</code></div>`;
    return;
  }
  const providers = data.provider_health?.providers || [];
  const providerRows = providers.map(item => [
    item.provider || "",
    { html: statusBadge(item.status || "unknown") },
    `${Math.round(Number(item.success_rate || 0) * 100)}%`,
    formatMs(item.latency_p50_ms),
    formatMs(item.latency_p95_ms),
    item.last_error_type || "-"
  ]);
  const scenarioRows = Object.entries(data.by_scenario || {}).map(([name, item]) => [
    name,
    `${item.passed_count || 0}/${item.case_count || 0}`,
    `${Math.round(Number(item.pass_rate || 0) * 100)}%`,
    `${Math.round(Number(item.citation_hit_rate || 0) * 100)}%`,
    formatMs(item.latency_p50_ms)
  ]);
  const failedRows = (data.cases || []).filter(item => !item.pass).slice(0, 8).map(item => [
    item.scenario || "",
    item.name || "",
    item.provider || "-",
    item.failure_reason || "unknown",
    item.top_domain || "-"
  ]);
  const metricRows = [
    ["Provider success", `${Math.round(Number(data.provider_success_rate || 0) * 100)}%`],
    ["Pass rate", `${Math.round(Number(data.pass_rate || 0) * 100)}%`],
    ["Citation hit", `${Math.round(Number(data.citation_hit_rate || 0) * 100)}%`],
    ["Latency P50", formatMs(data.latency_p50_ms)],
    ["Latency P95", formatMs(data.latency_p95_ms)],
    ["Cases", data.case_count || 0]
  ];
  target.innerHTML =
    `<div class="acceptance-report-card">
      <div><b>${esc(data.name || "search-live-acceptance")}</b><span>${statusBadge(data.ok ? "pass" : "fail")} ${esc(data.mode || "live")}</span></div>
      <code>${esc(data.report_path || "")}</code>
    </div>` +
    `<div class="acceptance-metric-grid">${metricRows.map(row => `<div class="acceptance-metric"><span>${esc(row[0])}</span><b>${esc(row[1])}</b></div>`).join("")}</div>` +
    table(["Provider", "Health", "Success", "P50", "P95", "Last error"], providerRows) +
    table(["Scenario", "Pass", "Pass rate", "Citation", "P50"], scenarioRows) +
    (failedRows.length ? table(["Scenario", "Case", "Provider", "Failure", "Top domain"], failedRows) : `<div class="acceptance-report-card"><b>Failure reasons</b><span>所有 live case 当前通过，暂无失败原因。</span></div>`);
}

async function loadLiveSearchReport() {
  if ($("liveSearchReportStatus")) $("liveSearchReportStatus").textContent = "正在读取最新联网搜索 live report...";
  try {
    const data = await api("/api/search/live/latest");
    renderLiveSearchReport(data);
    if ($("liveSearchReportStatus")) {
      $("liveSearchReportStatus").textContent = data.found
        ? `provider ${Math.round(Number(data.provider_success_rate || 0) * 100)}% · pass ${data.passed_count || 0}/${data.case_count || 0} · citation ${Math.round(Number(data.citation_hit_rate || 0) * 100)}% · P95 ${formatMs(data.latency_p95_ms)}`
        : data.message || "未找到联网验收报告";
    }
  } catch (err) {
    if ($("liveSearchReportStatus")) $("liveSearchReportStatus").textContent = "联网报告读取失败：" + err.message;
    if ($("liveSearchReportResult")) $("liveSearchReportResult").textContent = "读取失败：" + err.message;
  }
}

function renderMeetingAudioResult(data) {
  const target = $("meetingAsrResult");
  if (!target) return;
  const card = data?.meeting_card || {};
  const transcription = data?.transcription || {};
  const artifacts = data?.artifacts || {};
  const actionRows = (card.actions || []).map(item => [
    item.owner || "unassigned",
    item.description || "",
    item.due_date || "",
    item.evidence || ""
  ]);
  target.innerHTML =
    `<div class="acceptance-report-card">
      <div><b>${esc(card.title || data?.meeting?.title || "Meeting card")}</b><span>${statusBadge(data?.transcript_status || card.transcript_status || "pending")} ${esc(transcription.engine || "")} ${esc(transcription.model || "")}</span></div>
      <code>${esc(artifacts.meeting_card?.path || "")}</code>
    </div>` +
    `<div class="acceptance-metric-grid">
      <div class="acceptance-metric"><span>Speakers</span><b>${esc(card.speaker_count ?? 0)}</b></div>
      <div class="acceptance-metric"><span>Segments</span><b>${esc((data?.segments || []).length)}</b></div>
      <div class="acceptance-metric"><span>Latency</span><b>${formatMs(transcription.latency_ms)}</b></div>
      <div class="acceptance-metric"><span>Knowledge</span><b>${esc(data?.knowledge_item?.id ? "saved" : "pending")}</b></div>
    </div>` +
    table(["Field", "Value"], [
      ["Summary", card.summary || ""],
      ["Decisions", (card.decisions || []).join(" / ")],
      ["Risks", (card.risks || []).join(" / ")],
      ["Run ID", data?.run_record?.run_id || ""],
      ["Transcript JSON", artifacts.transcript?.path || ""]
    ]) +
    table(["Owner", "Action", "Due", "Evidence"], actionRows);
}

async function runMeetingAudioUpload() {
  const audioInput = $("meetingAudioPicker");
  const transcriptInput = $("meetingTranscriptPicker");
  const status = $("meetingAsrStatus");
  const result = $("meetingAsrResult");
  const audio = audioInput?.files?.[0];
  if (!audio) {
    if (status) status.textContent = "请选择一个音频文件。";
    return;
  }
  const form = new FormData();
  form.append("audio", audio);
  form.append("title", ($("meetingAsrTitle")?.value || audio.name || "Meeting audio").trim());
  const transcriptText = ($("meetingTranscriptText")?.value || "").trim();
  if (transcriptText) form.append("transcript", transcriptText);
  if (transcriptInput?.files?.[0]) form.append("transcript_file", transcriptInput.files[0]);
  if (status) status.textContent = "正在上传并调用本地 ASR/VAD/会议卡片流水线...";
  if (result) result.textContent = "处理中，首次运行 small 模型可能需要更久。";
  try {
    const response = await fetch(API + "/api/workspace/meetings/audio/upload", { method: "POST", body: form });
    if (!response.ok) throw new Error("upload " + response.status);
    const data = await response.json();
    renderMeetingAudioResult(data);
    if (status) status.textContent = `已生成会议卡片，知识库 ${data.knowledge_item?.id ? "已保存" : "未保存"}，Run ${data.run_record?.run_id || "--"}`;
    await loadKnowledge().catch(() => {});
    await loadRuntimeRecords().catch(() => {});
  } catch (err) {
    if (status) status.textContent = "会议音频处理失败：" + err.message;
    if (result) result.textContent = "处理失败：" + err.message;
  }
}

function committeePayload() {
  return lastSelfReviewCommittee?.result || lastSelfReviewCommittee?.data || lastSelfReviewCommittee || {};
}

function renderCommitteeTimeline(items) {
  const rows = items || [];
  if (!rows.length) return "";
  return `<div class="committee-timeline">${rows.map(item => `
    <div class="committee-timeline-item ${esc(item.status || "")}">
      <div class="committee-timeline-dot">${esc(item.order || "")}</div>
      <div class="committee-timeline-body">
        <div class="committee-timeline-head"><b>${esc(item.role || "")}</b><span>${esc(item.phase || "")} · ${esc(item.status || "")}</span></div>
        <dl>
          <dt>Input</dt><dd>${esc(item.input || "")}</dd>
          <dt>Action</dt><dd>${esc(item.action || "")}</dd>
          <dt>Artifact</dt><dd>${esc(item.artifact || "none")}</dd>
          <dt>Score</dt><dd>${esc(item.score ?? "n/a")}</dd>
          <dt>Gate</dt><dd>${esc(item.gate || "n/a")}</dd>
          <dt>Rework</dt><dd>${esc(item.rework_round || "n/a")}</dd>
        </dl>
      </div>
    </div>
  `).join("")}</div>`;
}

function roleAvatar(agent) {
  const map = {
    PlannerAgent: "PL",
    ResearchAgent: "RS",
    BuilderAgent: "BD",
    ReviewerAgent: "RV",
    RiskAgent: "RK",
    JudgeAgent: "JD",
    QualityGate: "QG",
    Arbiter: "AR",
  };
  return map[agent] || String(agent || "?").slice(0, 2).toUpperCase();
}

function renderRoleSwimlanes(payload) {
  const roles = payload.roles || [];
  if (!roles.length) return "";
  const trace = payload.execution_trace || [];
  return `<div class="audit-swimlanes">${roles.map(role => {
    const roleSteps = trace.filter(step => String(step.agent || "").includes(role.agent));
    const latest = roleSteps[roleSteps.length - 1] || {};
    return `<div class="audit-lane ${esc(role.agent)}">
      <div class="audit-avatar">${esc(roleAvatar(role.agent))}</div>
      <div class="audit-lane-main">
        <div class="audit-lane-head"><b>${esc(role.agent)}</b><span>${esc(role.score ?? "--")}/100</span></div>
        <p>${esc((role.findings || [])[0] || latest.output || "No finding recorded.")}</p>
        <small>${esc(latest.phase || "role")} · ${esc(latest.status || "ready")}</small>
      </div>
    </div>`;
  }).join("")}</div>`;
}

function renderAuditTimeline(items) {
  const rows = items || [];
  if (!rows.length) return "";
  return `<div class="audit-timeline-rail">${rows.map(item => `
    <div class="audit-timeline-node ${esc(item.status || "")}">
      <div class="audit-avatar">${esc(roleAvatar(item.role))}</div>
      <b>${esc(item.role || "")}</b>
      <span>${esc(item.phase || "")}</span>
      <small>${esc(item.gate || item.status || "")}</small>
    </div>
  `).join("")}</div>`;
}

function renderDisputeCards(disagreements) {
  const rows = disagreements || [];
  if (!rows.length) return "";
  return `<div class="audit-dispute-grid">${rows.map(item => `
    <article class="audit-dispute-card ${item.requires_rework ? "needs-rework" : "accepted"}">
      <div class="audit-dispute-top"><span>${esc(item.id || "D")}</span><b>${esc(item.objector || "")}</b></div>
      <dl>
        <dt>Opposes</dt><dd>${esc(item.opposes || "")}</dd>
        <dt>Evidence</dt><dd>${esc(item.evidence || "")}</dd>
        <dt>裁决</dt><dd>${esc(item.decision_owner || "")}: ${esc(item.arbitration_decision || "")}</dd>
        <dt>返工</dt><dd>${item.requires_rework ? "required" : "not required"}${item.linked_rework_round ? ` · ${esc(item.linked_rework_round)}` : ""}</dd>
      </dl>
    </article>
  `).join("")}</div>`;
}

function renderArtifactDiff(reworkLoop) {
  const rounds = reworkLoop?.rounds || [];
  if (!rounds.length) return "";
  return `<div class="audit-artifact-diff">${rounds.map(item => {
    const diff = item.reviewer_diff || {};
    const v1 = diff.v1_sources || {};
    const v2 = item.v2_artifacts || diff.v2_artifacts || {};
    const keys = [...new Set([...Object.keys(v1), ...Object.keys(v2)])];
    return `<div class="audit-diff-round">
      <div class="audit-diff-head"><b>Round ${esc(item.round)} · ${esc(item.status || "")}</b><span>${esc(item.judge_decision || "")}</span></div>
      <div class="audit-diff-grid">${keys.map(key => `
        <div class="audit-diff-pair">
          <span>${esc(key)}</span>
          <code>v1: ${esc(v1[key] || "none")}</code>
          <code>v2: ${esc(v2[key] || "none")}</code>
        </div>
      `).join("")}</div>
    </div>`;
  }).join("")}</div>`;
}

function renderBuilderExecution(builderExecution) {
  const tasks = builderExecution?.tasks || [];
  if (!tasks.length) return "";
  return `<div class="audit-builder-execution">
    <div class="audit-builder-head"><b>Builder Execution</b><span>${esc(builderExecution.status || "")} · ${esc(builderExecution.done_count ?? 0)}/${esc(builderExecution.task_count ?? tasks.length)} done</span></div>
    <div class="audit-builder-grid">${tasks.map(item => `
      <div class="audit-builder-task ${esc(item.status || "")}">
        <span>${esc(item.id || "")}</span>
        <b>${esc(item.planner_task || "")}</b>
        <small>${esc(item.tool || "")} · ${esc(item.status || "")}</small>
        <p>${esc(item.output || "")}</p>
        <code>${esc(item.artifact || "no artifact")}</code>
      </div>
    `).join("")}</div>
  </div>`;
}

function renderCommitteeAuditBoard(payload) {
  const gate = payload.quality_gate || {};
  const rework = payload.rework_loop || {};
  const disagreements = payload.disagreement_log || [];
  return `<section class="committee-audit-board">
    <div class="audit-board-head">
      <div><b>Multi-Agent Audit Board</b><span>Role lanes, timeline, disputes, arbitration, rework, and V1/V2 artifact diff.</span></div>
      <div class="audit-board-kpis">
        <span>Score <b>${esc(payload.score ?? "--")}</b></span>
        <span>Gate <b>${esc(gate.status || "--")}</b></span>
        <span>Rework <b>${esc(rework.status || "--")}</b></span>
        <span>Disputes <b>${esc(disagreements.length)}</b></span>
      </div>
    </div>
    ${renderRoleSwimlanes(payload)}
    ${renderBuilderExecution(payload.builder_execution)}
    ${renderAuditTimeline(payload.timeline || [])}
    <div class="audit-board-columns">
      <div><h3>争议点与仲裁</h3>${renderDisputeCards(disagreements) || '<div class="empty-state">No disagreement recorded.</div>'}</div>
      <div><h3>V1 / V2 产物对比</h3>${renderArtifactDiff(rework) || '<div class="empty-state">No rework artifact diff recorded.</div>'}</div>
    </div>
  </section>`;
}

function renderRubricMatrix(matrix) {
  if (!matrix?.rows?.length) return "";
  const rows = matrix.rows.map(item => [
    item.category,
    item.weight,
    `${item.score}/100`,
    item.owner,
    item.evidence,
    item.risk,
    item.next_action
  ]);
  return `<div class="rubric-summary"><b>Enterprise Rubric ${esc(matrix.score ?? "--")}/${esc(matrix.max_score ?? 100)}</b><span>${esc(matrix.status || "")} · ${esc(matrix.summary || "")}</span></div>` +
    table(["Category", "Weight", "Score", "Owner", "Evidence", "Risk", "Next Action"], rows);
}

function renderSelfReviewCommitteeResult(data) {
  lastSelfReviewCommittee = data;
  lastCommitteeKnowledgeIds = [];
  const payload = committeePayload();
  const rows = [
    ["Score", `${payload.score ?? "--"} / 100`],
    ["Delivery readiness", `${payload.delivery_readiness_score ?? "--"} / 100`],
    ["Quality gate", payload.quality_gate?.status || ""],
    ["Report", payload.committee_report || ""],
    ["Knowledge items", (payload.knowledge_items || []).length],
    ["Rubric", payload.rubric_matrix ? `${payload.rubric_matrix.score}/${payload.rubric_matrix.max_score}` : ""],
    ["Roles", (payload.roles || []).map(role => `${role.agent}:${role.score}`).join(", ")]
  ];
  const priorityRows = (payload.priorities || []).map((item, index) => [index + 1, item]);
  const traceRows = (payload.execution_trace || []).map(step => [
    step.id || "",
    step.agent || "",
    step.phase || "",
    step.status || "",
    step.output || ""
  ]);
  const gateRows = [
    ["Status", payload.quality_gate?.status || ""],
    ["Thresholds", payload.quality_gate?.thresholds ? `final>=${payload.quality_gate.thresholds.final_min}, risk>=${payload.quality_gate.thresholds.risk_min}, judge>=${payload.quality_gate.thresholds.judge_min}` : ""],
    ["Failures", (payload.quality_gate?.failures || []).join(" | ") || "none"],
    ["Blocking agents", (payload.quality_gate?.blocking_agents || []).join(", ") || "none"]
  ];
  const arbitrationRows = (payload.arbitration_rounds || []).map(item => [
    item.round,
    item.arbiter,
    item.status,
    item.decision,
    (item.required_rework || []).join(" | ")
  ]);
  const disagreementRows = (payload.disagreement_log || []).map(item => [
    item.id || "",
    item.objector || "",
    item.opposes || "",
    item.evidence || "",
    item.decision_owner || "",
    item.arbitration_decision || "",
    item.requires_rework ? "yes" : "no"
  ]);
  const reworkRows = (payload.rework_loop?.rounds || []).map(item => [
    item.round,
    item.status,
    `${item.final_score}/100`,
    `risk ${item.risk_score} / judge ${item.judge_score}`,
    item.judge_decision || "",
    Object.values(item.v2_artifacts || {}).join(" | "),
    (item.reviewer_diff?.unresolved || item.hard_blockers || []).join(" | ") || (item.required_next || []).join(" | ")
  ]);
  const roleRows = (payload.roles || []).map(role => [
    role.agent,
    `${role.score}/100`,
    (role.findings || []).slice(0, 2).join(" | "),
    (role.actions || []).slice(0, 2).join(" | ")
  ]);
  if ($("committeeResult")) {
    $("committeeResult").innerHTML =
      `<div class="report-flow"><b>自评审委员会已完成</b><span>下一步：保存报告到项目知识库，并用评审问题反压 demo 和提交材料。</span><div class="report-flow-steps"><span class="done">1 固定角色评审</span><span>2 保存知识库</span><span>3 继续追问</span></div><div class="action-row"><button class="primary" onclick="saveSelfReviewCommitteeToKnowledge()">保存到知识库</button><button class="secondary" onclick="askSelfReviewCommitteeQuestion()">继续追问</button></div></div>` +
      table(["Item", "Result"], rows) +
      renderCommitteeAuditBoard(payload) +
      renderCommitteeTimeline(payload.timeline || []) +
      renderRubricMatrix(payload.rubric_matrix) +
      table(["Step", "Agent", "Phase", "Status", "Output"], traceRows) +
      table(["Gate", "Result"], gateRows) +
      table(["Round", "Arbiter", "Status", "Decision", "Required rework"], arbitrationRows) +
      table(["Dispute", "Objector", "Opposes", "Evidence", "Owner", "Decision", "Rework"], disagreementRows) +
      table(["Rework", "Status", "Score", "Rescore", "Judge", "V2 Artifacts", "Blocker / Next"], reworkRows) +
      table(["Role", "Score", "Findings", "Actions"], roleRows) +
      table(["Priority", "Action"], priorityRows);
  }
}

async function runSelfReviewCommittee() {
  const outputDir = ($("committeeOutputDir")?.value || $("enterpriseOutputDir")?.value || "output/delivery").trim() || "output/delivery";
  const params = {
    output_dir: outputDir,
    project_name: ($("enterpriseProjectName")?.value || "ClawOS").trim() || "ClawOS",
    scenario: ($("enterpriseScenario")?.value || "MTClaw competition enterprise delivery").trim() || "MTClaw competition enterprise delivery",
    focus: ($("committeeFocus")?.value || "competition final readiness").trim() || "competition final readiness"
  };
  const existingDelivery = enterpriseDeliveryPayload();
  if (existingDelivery?.files) params.delivery_package = existingDelivery;
  if ($("committeeStatus")) $("committeeStatus").textContent = "正在运行固定角色自评审委员会";
  if ($("committeeResult")) $("committeeResult").textContent = "Planner / Research / Builder / Reviewer / Risk / Judge 正在执行、评审和门禁交付包...";
  try {
    const data = await api("/api/skills/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "clawos_self_review_committee", params, plan_only: false })
    });
    const result = data?.outputs?.[0]?.result || data?.result || data;
    renderSelfReviewCommitteeResult({ result });
    const gate = result.quality_gate?.status || "unknown";
    if ($("committeeStatus")) $("committeeStatus").textContent = `执行编队完成 · score ${result.score ?? "--"}/100 · gate ${gate}`;
  } catch (err) {
    if ($("committeeStatus")) $("committeeStatus").textContent = "自评审委员会运行失败：" + err.message;
    if ($("committeeResult")) $("committeeResult").textContent = "运行失败：" + err.message;
  }
}

async function saveSelfReviewCommitteeToKnowledge() {
  const payload = committeePayload();
  const items = payload.knowledge_items || [];
  if (!items.length) {
    if ($("committeeStatus")) $("committeeStatus").textContent = "请先运行自评审委员会";
    return;
  }
  if ($("committeeStatus")) $("committeeStatus").textContent = "正在保存委员会报告到项目知识库";
  const savedIds = [];
  for (const item of items) {
    const saved = await api("/api/knowledge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: item.title,
        content: item.content,
        category: item.category || "project",
        source: item.source || "self-review-committee",
        tags: item.tags || ["multi-agent", "self-review", "generated"],
        confidence: 0.92
      })
    });
    if (saved.item?.id) savedIds.push(saved.item.id);
  }
  lastCommitteeKnowledgeIds = savedIds;
  knowledgeCategory = "project";
  if ($("knowledgeCategory")) $("knowledgeCategory").value = "project";
  if ($("committeeStatus")) $("committeeStatus").textContent = `已保存 ${savedIds.length} 个委员会条目到项目知识库`;
  await loadKnowledge();
  await loadKnowledgeGraph();
  const flow = $("committeeResult")?.querySelector(".report-flow");
  if (flow && savedIds.length) {
    flow.querySelector(".report-flow-steps")?.insertAdjacentHTML("beforeend", `<span class="done">已保存 ${savedIds.length} 条</span>`);
  }
}

function askSelfReviewCommitteeQuestion() {
  const payload = committeePayload();
  const title = payload.project_name || $("enterpriseProjectName")?.value || "ClawOS";
  usePrompt(`请基于 ${title} 自评审委员会报告，给出夺冠前最该优先关闭的 5 个问题，并按 P0/P1/P2 排序。`);
  setView("chat");
}

function reportPresetInfo() {
  const style = $("reportStylePreset")?.value || "journal";
  return {
    journal: { label: "论文分析", hint: "适合论文精读、证据追踪和复现检查。" },
    learning_notes: { label: "学习笔记", hint: "适合课程复习、概念拆解和自测问题。" },
    business_brief: { label: "商业简报", hint: "适合路演、汇报和项目价值表达。" },
    compact: { label: "紧凑版", hint: "适合快速交付一页摘要和行动清单。" }
  }[style] || { label: "论文分析", hint: "适合论文精读、证据追踪和复现检查。" };
}

function applyReportPreset() {
  const info = reportPresetInfo();
  if ($("reportStyleHint")) $("reportStyleHint").textContent = info.hint;
}

function useReportStylePrompt() {
  const info = reportPresetInfo();
  const depth = $("reportDepthPreset")?.value || "5";
  usePrompt(`请基于我上传或知识库中的论文资料，生成${info.label}风格的报告。要求：depth=${depth}，保留引用证据、关键结论、风险局限和下一步行动。`);
  setView("chat");
}

async function saveMemory() {
  const body = { memory_type: $("memType").value, key: $("memKey").value, value: $("memValue").value, source: $("memSource").value || "manual" };
  await api("/api/memory/items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  await loadMemory();
}

async function loadMemory() {
  const target = $("memoryTable");
  if (!target) return;
  try {
    const data = await api("/api/memory/items?include_disabled=true&limit=80");
    target.innerHTML = table(["类型", "键", "内容", "状态", "操作"], (data.items || []).map(item => [
      item.memory_type,
      item.key,
      item.value,
      item.enabled ? "启用" : "停用",
      { html: `<button class="secondary" onclick="toggleMemory(${Number(item.id)},${item.enabled ? "false" : "true"})">${item.enabled ? "停用" : "启用"}</button>` }
    ]));
    const reviews = await api("/api/memory/reviews?limit=50").catch(() => ({ reviews: [] }));
    if ($("memoryReviewTable")) $("memoryReviewTable").innerHTML = table(["ID", "类型", "内容", "状态", "操作"], (reviews.reviews || []).map(item => [item.id, item.memory_type || "", item.proposed_value || "", item.status || "", { html: `<button class="secondary" onclick="resolveMemoryReview(${Number(item.id)},'approved')">通过</button> <button class="secondary" onclick="resolveMemoryReview(${Number(item.id)},'rejected')">拒绝</button>` }]));
  } catch (err) {
    target.innerHTML = table(["类型", "键", "内容", "状态", "操作"], []);
  }
}

async function searchMemory() {
  const query = $("memQuery").value.trim();
  if (!query) return;
  const data = await api("/api/memory/search?q=" + encodeURIComponent(query));
  if ($("searchTable")) $("searchTable").innerHTML = table(["类型", "键", "内容"], (data.results || data.items || []).map(item => [item.memory_type, item.key, item.value]));
}

async function toggleMemory(id, enabled) {
  await api(`/api/memory/items/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
  await loadMemory();
}

async function resolveMemoryReview(id, status) {
  await api(`/api/memory/reviews/${id}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
  await loadMemory();
}

async function loadHealth() {
  try {
    const health = await api("/health");
    const ok = health.status === "ok" || health.ok;
    $("healthDot").className = "dot " + (ok ? "ok" : "bad");
    $("healthText").textContent = ok ? "运行正常" : "需要检查";
    $("modelBadge").textContent = `模型：${health.model_provider?.provider || health.provider || "-"}`;
    $("toolBadge").textContent = `工具：${health.tools || health.tool_count || "-"}`;
    const provider = health.model_provider || {};
    const label = provider.provider === "mock" ? "Mock/offline test 模式" : provider.provider === "qwen" ? "Local Qwen 模式" : "DeepSeek/API 模式";
    if ($("modelModeLabel")) $("modelModeLabel").textContent = label;
    if ($("modelModeDetail")) $("modelModeDetail").textContent = provider.model || provider.base_url || "configuration-first mode";
  } catch (err) {
    $("healthDot").className = "dot bad";
    $("healthText").textContent = "服务不可用";
  }
}

async function loadDash() {
  if (!$("metrics")) return;
  try {
    const tasks = await api("/api/tasks?limit=20").catch(() => ({ tasks: [] }));
    const tools = await api("/api/tools").catch(() => ({ tools: [] }));
    const knowledge = await api("/api/knowledge").catch(() => ({ count: 0, items: [] }));
    $("metrics").innerHTML = [
      ["任务", tasks.count ?? tasks.tasks?.length ?? 0],
      ["工具", tools.count ?? tools.tools?.length ?? 0],
      ["知识", knowledge.count ?? knowledge.items?.length ?? 0]
    ].map(([label, value]) => `<div class="metric"><div class="v">${esc(value)}</div><div class="l">${esc(label)}</div></div>`).join("");
    if ($("activityTable")) $("activityTable").innerHTML = table(["任务", "状态", "时间"], (tasks.tasks || []).slice(0, 8).map(task => [task.title, { html: statusBadge(task.status) }, task.started_at || ""]));
    if ($("runtimeKv")) $("runtimeKv").innerHTML = `<div class="kv"><span>API</span><b>${esc(API)}</b></div>`;
    await Promise.allSettled([loadModelHealth(), loadToolAccuracy(), loadRoutingStrategy()]);
  } catch (err) {}
}

async function loadModelHealth() {
  const target = $("modelHealthTable");
  if (!target) return;
  const data = await api("/api/model/health").catch(() => ({}));
  target.innerHTML = table(["项目", "状态", "说明"], [["primary", { html: statusBadge(data.ok ? "success" : "pending") }, data.provider || data.model || ""]]);
}

async function loadToolAccuracy() {
  const target = $("toolAccuracyTable");
  if (!target) return;
  const data = await api("/api/tools/accuracy").catch(() => ({ items: [] }));
  target.innerHTML = table(["工具", "准确率", "次数"], (data.items || data.tools || []).map(item => [item.tool || item.name, item.accuracy || item.success_rate || "", item.count || item.total || ""]));
}

function renderLastTools() {
  const target = $("lastTools");
  if (!target) return;
  target.innerHTML = lastToolCalls.length ? lastToolCalls.map(tool => `<div class="item"><b>${esc(tool.name || "tool")}</b><span>${esc(JSON.stringify(tool.result || {}).slice(0, 180))}</span></div>`).join("") : '<div class="item"><span>暂无工具调用</span></div>';
}

function renderLastReflection(reflection) {
  const target = $("lastReflection");
  if (!target) return;
  const card = reflection.card || {};
  target.innerHTML = `<div class="item"><b>${esc(card.outcome || "反思")}</b><span>${esc(card.task || "最近任务")}</span><span>${esc(card.lesson || "已写入 MemoryOS")}</span></div>`;
}

async function loadReflection() {
  if (!$("reflectionTable")) return;
  const cards = await api("/api/reflection/cards?limit=50").catch(() => ({ cards: [] }));
  $("reflectionTable").innerHTML = table(["任务", "结果", "经验"], (cards.cards || []).map(card => [card.task || "", card.outcome || "", card.lesson || ""]));
  const improvements = await api("/api/reflection/improvements?limit=50").catch(() => ({ items: [] }));
  if ($("reflectionReviewTable")) $("reflectionReviewTable").innerHTML = table(["ID", "状态", "建议", "操作"], (improvements.items || improvements.improvements || []).map(item => [item.id, item.status || "", item.proposal || item.summary || "", { html: `<button class="secondary" onclick="transitionReflection(${Number(item.id)},'reviewed')">审查</button> <button class="secondary" onclick="validateReflection(${Number(item.id)})">验证</button> <button class="secondary" onclick="publishReflection(${Number(item.id)})">发布</button> <button class="secondary" onclick="rollbackReflection(${Number(item.id)})">回滚</button>` }]));
}

async function triggerReflection() { await api("/api/reflection/trigger", { method: "POST" }).catch(() => ({})); await loadReflection(); }
async function transitionReflection(id, status) { await api(`/api/reflection/improvements/${id}/transition`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }).catch(() => ({})); await loadReflection(); }
async function validateReflection(id) { await transitionReflection(id, "validated"); }
async function publishReflection(id) { await transitionReflection(id, "published"); }
async function rollbackReflection(id) { await transitionReflection(id, "rolled_back"); }

function evolutionActions(run) {
  const id = Number(run.id);
  const status = String(run.status || "");
  const canShadow = status === "validated";
  const canCanary = status === "shadow" || status === "canary";
  const canActivate = status === "shadow" || status === "canary" || status === "validated";
  return [
    canShadow ? `<button class="secondary" onclick="shadowEvolutionRun(${id})">Shadow</button>` : "",
    canCanary ? `<button class="secondary" onclick="canaryEvolutionRun(${id})">Canary</button>` : "",
    canActivate ? `<button class="primary" onclick="activateEvolutionRun(${id})">Activate</button>` : "",
    `<button class="secondary" onclick="snapshotEvolutionQuality(${id})">质量快照</button>`
  ].filter(Boolean).join(" ");
}

async function loadEvolution() {
  if (!$("evolutionRunTable")) return;
  const data = await api("/api/self-evolution/board").catch(() => ({ runs: [], quality_snapshot: {} }));
  const runs = data.runs || [];
  if ($("evolutionScore")) $("evolutionScore").textContent = `Evolution readiness: ${data.enterprise_score ?? "--"}% · ${data.enterprise_ready ? "enterprise gate passed" : "needs observation"}`;
  const quality = data.quality_snapshot || {};
  if ($("evolutionQualityTable")) {
    $("evolutionQualityTable").innerHTML = table(["Signal", "Value"], Object.keys(quality).map(key => [key, quality[key]]));
  }
  $("evolutionRunTable").innerHTML = table(
    ["ID", "目标", "阶段", "流量", "门禁", "决策", "结论", "操作"],
    runs.map(run => [
      run.id,
      `${run.target_type}/${run.target_key}`,
      { html: statusBadge(run.release_stage || run.status) },
      `${run.traffic_percent || 0}%`,
      { html: statusBadge((run.gate_result || {}).passed ? "passed" : run.status === "candidate" ? "pending" : "failed") },
      run.publish_decision || "",
      run.conclusion || "",
      { html: evolutionActions(run) }
    ])
  );
  const selected = runs[0] || {};
  const checks = (selected.gate_result || {}).checks || [];
  if ($("evolutionGateTable")) {
    $("evolutionGateTable").innerHTML = table(
      ["Run", "Benchmark", "Metric", "Baseline", "Candidate", "Result"],
      checks.map(check => [selected.id || "", check.benchmark, check.metric, check.baseline, check.candidate, { html: statusBadge(check.passed ? "passed" : "failed") }])
    );
  }
}

async function queueEvolutionRun() {
  let baseline = {};
  try {
    baseline = JSON.parse($("evoBaselinePayload")?.value || "{}");
  } catch (err) {
    if ($("evolutionResult")) $("evolutionResult").textContent = "Baseline JSON 格式错误";
    return;
  }
  const targetType = $("evoTargetType")?.value || "retrieval_params";
  const targetKey = $("evoTargetKey")?.value || "default";
  const data = await api("/api/self-evolution/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target_type: targetType,
      target_key: targetKey,
      baseline_payload: baseline,
      candidate_payload: {},
      auto_queue: true,
      actor_id: "console"
    })
  });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await Promise.allSettled([loadEvolution(), loadTasks()]);
}

async function shadowEvolutionRun(id) {
  const data = await api(`/api/self-evolution/runs/${id}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console" }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}

async function canaryEvolutionRun(id) {
  const data = await api(`/api/self-evolution/runs/${id}/canary`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ traffic_percent: 10, actor_id: "console" }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}

async function activateEvolutionRun(id) {
  const data = await api(`/api/self-evolution/runs/${id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console", reason: "console activation after shadow/canary review" }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}

async function snapshotEvolutionQuality(id) {
  const data = await api(`/api/self-evolution/runs/${id}/quality-snapshot`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console" }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}

async function loadTools() {
  const target = $("toolsTable");
  if (!target) return;
  try {
    const data = await api("/api/tools");
    allTools = data.tools || data.items || [];
    renderTools();
  } catch (err) {
    target.innerHTML = table(["工具", "说明"], []);
  }
}

function renderTools() {
  const target = $("toolsTable");
  if (!target) return;
  const query = ($("toolQuery")?.value || "").toLowerCase();
  const rows = allTools.filter(tool => !query || JSON.stringify(tool).toLowerCase().includes(query));
  target.innerHTML = table(["工具", "说明", "风险"], rows.map(tool => [tool.name || tool.function?.name || "", tool.description || tool.function?.description || "", tool.risk_level || ""]));
}

async function loadToolExecutions() {
  const target = $("toolExecTable");
  if (!target) return;
  const data = await api("/api/tools/executions?limit=50").catch(() => ({ executions: [] }));
  target.innerHTML = table(["工具", "状态", "时间"], (data.executions || data.items || []).map(item => [item.tool || item.name || "", { html: statusBadge(item.status || "success") }, item.created_at || ""]));
}

function taskActions(task) {
  const id = Number(task.id);
  const terminal = ["succeeded", "failed", "canceled", "interrupted"].includes(task.status);
  return `<button class="secondary" onclick="showTask(${id})">查看</button> ${terminal ? "" : `<button class="secondary icon-text" onclick="cancelTask(${id})"><span class="ui-ico">■</span>取消</button>`} <button class="secondary icon-text" onclick="retryTask(${id})"><span class="ui-ico">↺</span>重试</button>`;
}

async function loadTasks() {
  try {
    const data = await api("/api/tasks?session_id=" + encodeURIComponent(currentSession) + "&limit=20");
    const rows = data.tasks || [];
    if (!lastTaskId && rows[0]) lastTaskId = rows[0].id;
    if ($("taskTable")) $("taskTable").innerHTML = table(["ID", "状态", "尝试", "标题", "来源", "开始", "操作"], rows.map(task => [task.id, { html: statusBadge(task.status) }, task.attempt || 1, task.title, task.source, task.started_at, { html: taskActions(task) }]));
    await loadTaskQueue();
    if (lastTaskId) await showTask(lastTaskId);
  } catch (err) {
    if ($("taskTable")) $("taskTable").innerHTML = table(["ID", "状态", "尝试", "标题", "来源", "开始", "操作"], []);
  }
}

async function loadTaskQueue() {
  const target = $("taskQueueTable");
  if (!target) return;
  try {
    const data = await api("/api/tasks/queue?limit=20");
    target.innerHTML = table(["ID", "状态", "尝试", "标题", "恢复状态", "操作"], (data.tasks || []).map(task => [task.id, { html: statusBadge(task.status) }, task.attempt || 1, task.title, task.resume_state || "", { html: `<button class="secondary" onclick="showTask(${Number(task.id)})">查看</button> <button class="primary" onclick="claimTask(${Number(task.id)})">领取</button>` }]));
  } catch (err) {
    target.innerHTML = table(["ID", "状态", "尝试", "标题", "恢复状态", "操作"], []);
  }
}

async function claimTask(id) {
  const data = await api("/api/tasks/queue/claim", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ worker_id: "console" }) });
  $("liveTaskState").textContent = data.task?.id ? `已领取任务 #${data.task.id}` : "队列暂无可领取任务";
  if (data.task?.id) lastTaskId = data.task.id;
  await loadTasks();
}

async function cancelTask(id) {
  await api(`/api/tasks/${id}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "console cancel", actor_id: "console" }) });
  await loadTasks();
}

async function retryTask(id) {
  const data = await api(`/api/tasks/${id}/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "console retry", actor_id: "console" }) });
  lastTaskId = data.task?.id || lastTaskId;
  await loadTasks();
}

async function recoverTasks() {
  const data = await api("/api/tasks/recover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console" }) });
  $("liveTaskState").textContent = `恢复完成：${data.count || 0} 个任务`;
  await loadTasks();
}

async function showTask(task_id) {
  if (!task_id || !$("taskStepTable")) return;
  lastTaskId = task_id;
  const data = await api("/api/tasks/" + encodeURIComponent(task_id));
  $("taskStepTable").innerHTML = table(["步骤", "状态", "开始", "完成", "输出"], (data.steps || []).map(step => [step.name, { html: statusBadge(step.status) }, step.started_at, step.completed_at || "", JSON.stringify(step.output || {}).slice(0, 220)]));
  $("taskEventTable").innerHTML = table(["事件", "消息", "时间", "数据"], (data.events || []).map(event => [event.event_type, event.message || "", event.created_at, JSON.stringify(event.data || {}).slice(0, 220)]));
}

function startTaskStream() {
  if (taskStream) {
    taskStream.close();
    taskStream = null;
  }
  if (!window.EventSource) {
    if ($("liveTaskState")) $("liveTaskState").textContent = "实时事件：轮询模式";
    return;
  }
  try {
    taskStream = new EventSource(`/api/tasks/stream?session_id=${encodeURIComponent(currentSession)}&after_id=${taskEventCursor}`);
    taskStream.addEventListener("task_events", event => {
      const rows = JSON.parse(event.data || "[]");
      if (rows.length) {
        taskEventCursor = Math.max(...rows.map(row => Number(row.id) || 0));
        if ($("liveTaskState")) $("liveTaskState").textContent = `实时事件：已同步到 #${taskEventCursor}`;
        loadTasks();
      }
    });
    taskStream.onerror = () => {
      if ($("liveTaskState")) $("liveTaskState").textContent = "实时事件：连接重试中";
    };
  } catch (err) {
    if ($("liveTaskState")) $("liveTaskState").textContent = "实时事件：不可用";
  }
}

async function loadBenchmarks() {
  if (!$("benchmarkSuiteTable")) return;
  try {
    const [suites, runs] = await Promise.all([api("/api/benchmarks/scenarios/suites"), api("/api/benchmarks/scenarios/runs")]);
    benchmarkSuites = suites.suites || [];
    $("benchmarkSuiteTable").innerHTML = table(["ID", "名称", "冻结", "用例数", "说明"], benchmarkSuites.map(item => [item.id, item.name, item.frozen ? "是" : "否", (item.cases || []).length, item.description]));
    $("benchmarkRunTable").innerHTML = table(["ID", "结果", "通过率", "P95", "场景", "时间"], (runs.runs || []).map(item => [item.id, { html: statusBadge(item.passed ? "success" : "failed") }, item.metrics?.pass_rate, item.metrics?.p95_latency_ms, (item.metrics?.scenarios || []).join(", "), item.created_at]));
  } catch (err) {}
}

async function runScenarioBenchmark() {
  const suiteId = benchmarkSuites[0]?.id;
  await api("/api/benchmarks/scenarios/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(suiteId ? { suite_id: suiteId } : {}) });
  await loadBenchmarks();
  await loadTasks();
}

async function loadCapabilities() {
  if (!$("capabilityTable")) return;
  try {
    const caps = await api("/api/workspace/capabilities");
    $("capabilityTable").innerHTML = table(["能力", "状态", "说明"], [
      ["本地文件/项目创建", { html: statusBadge(caps.local_file_operations?.project_create ? "success" : "failed") }, `根目录 ${caps.local_file_operations?.allowed_roots?.length || 0} 个，写操作需确认`],
      ["结构化文件生成", { html: statusBadge(caps.local_file_operations?.structured_file_generation?.length ? "success" : "failed") }, `支持 ${(caps.local_file_operations?.structured_file_generation || []).join(" / ")}，可用于会议纪要、数据整理、论文解析、表格和 PPT`],
      ["自带 XLSX 表格", { html: statusBadge(caps.office_artifacts?.xlsx?.create && caps.office_artifacts?.xlsx?.edit_cells ? "success" : "failed") }, "标准库 OpenXML，可生成表格并编辑单元格"],
      ["自带 PPTX 演示文稿", { html: statusBadge(caps.office_artifacts?.pptx?.create && caps.office_artifacts?.pptx?.replace_text ? "success" : "failed") }, "标准库 OpenXML，可生成幻灯片并替换文本"],
      ["联网搜索/网页抓取", { html: statusBadge("wait") }, "提供 web_search 和 web_fetch 工具；真实联网取决于运行环境网络权限"],
      ["搜索证据引擎", { html: statusBadge(caps.web_research?.source_ranking && caps.web_research?.citation_consistency_check ? "success" : "failed") }, `Provider ${(caps.web_research?.provider_router || []).join(" / ")}；缓存/重试/限流/可信度/时效性/引用门禁已接入`],
      ["PDF 文本识别", { html: statusBadge(caps.document_understanding?.pdf_text ? "success" : "failed") }, "依赖 pdftotext；低文本页标记为 OCR required"],
      ["论文学习解析文件", { html: statusBadge(caps.document_understanding?.paper_learning_analysis?.length ? "success" : "failed") }, `可生成 ${(caps.document_understanding?.paper_learning_analysis || []).join(" / ")} 自我提问式报告`],
      ["音频会议", { html: statusBadge(caps.meeting_audio?.audio_file_registration ? "success" : "failed") }, `Whisper ${caps.meeting_audio?.local_whisper_available ? "可用" : "未检测到"}`],
      ["Git 审批写操作", { html: statusBadge(caps.git?.approval_commit ? "success" : "failed") }, "审批后 commit，回滚使用 git revert"],
      ["Skill 治理", { html: statusBadge("success") }, "签名、依赖清单、fresh audit、canary 元数据"]
    ]);
    $("sceneBoundaryTable").innerHTML = table(["场景", "已交付", "仍需外部条件"], [
      ["会议", "音频登记、转写导入、说话人标签、会议纪要、ICS/EML 草稿", "真实 Whisper/说话人模型和自动发送连接器"],
      ["科研", "PDF 导入、OCR 需求检测、引用校验、对比矩阵、复现实验目录、论文学习解析文件", "本地 OCR 引擎和真实数据集运行"],
      ["办公", "XLSX 生成/单元格编辑、PPTX 生成/文本替换、产物记录", "复杂图表、母版设计和高级动画后续增强"],
      ["学习", "知识图谱、错题证据、长期掌握度", "更长周期学习样本"],
      ["Git", "补丁预览、审批提交、checkpoint、revert 回滚", "远程 PR/CI 连接器"],
      ["Skill", "签名、依赖、fresh-agent audit、canary", "真实流量灰度路由"]
    ]);
  } catch (err) {}
}

function ensureProfessionalBoard() {
  const target = $("professionalBoardGrid");
  if (!target || target.dataset.ready === "1") return;
  target.dataset.ready = "1";
  const boardTitle = "Professional Template Board";
  const boards = [
    { kind: "research", title: "Research Board", summary: "论文入库、引用问答、期刊级报告、复现实验计划", input: "PDF / 文献 / 研究问题", output: "报告、引用证据、复现实验目录", gate: "citation evidence + reproducibility gate", action: "Open research flow" },
    { kind: "learning", title: "Learning Board", summary: "概念图谱、掌握度证据、错题归因、间隔复习", input: "课程资料 / 错题 / 学习目标", output: "概念图、复习计划、自测题", gate: "mastery evidence + spaced review gate", action: "Open learning flow" },
    { kind: "code", title: "Code Board", summary: "仓库扫描、任务拆分、测试闭环、交接记录", input: "repo / issue / 交付目标", output: "风险清单、测试结果、交接摘要", gate: "tests + handoff gate", action: "Open code flow" },
    { kind: "office", title: "Office Board", summary: "简报、表格、幻灯片、会议纪要和导出检查", input: "会议 / 数据 / 汇报对象", output: "brief、sheet、slides、minutes", gate: "export quality gate", action: "Open office flow" }
  ];
  target.setAttribute("aria-label", boardTitle);
  target.innerHTML = boards.map(board => `<article class="board-card"><b>${board.title}</b><span>${board.summary}</span><dl><dt>输入</dt><dd>${board.input}</dd><dt>产物</dt><dd>${board.output}</dd><dt>质量门</dt><dd>${board.gate}</dd><dt>下一步</dt><dd>${board.action}</dd></dl><button class="primary icon-text" onclick="activateScenarioBoard('${board.kind}')"><span class="ui-ico">→</span>${board.action}</button></article>`).join("");
}

function activateScenarioBoard(kind) {
  const prompts = {
    research: "请按 Research Board 执行：论文入库、引用问答、期刊级报告、复现实验计划和证据质量门。",
    learning: "请按 Learning Board 执行：概念图谱、掌握度证据、错题归因、间隔复习计划和长期追踪。",
    code: "请按 Code Board 执行：仓库结构扫描、任务拆分、风险登记、测试闭环和交接记录。",
    office: "请按 Office Board 执行：简报、表格、幻灯片、会议纪要和导出质量检查。"
  };
  usePrompt(prompts[kind] || prompts.research);
  setView("chat");
}

function renderOpsDocuments() {
  const select = $("opsReportDocumentSelect");
  if (!select) return;
  const docs = (knowledgeDocuments || []).filter(doc => String(doc.status || "") === "ready");
  select.innerHTML = docs.length ? docs.map(doc => `<option value="${Number(doc.id)}">${esc(doc.title || doc.filename || ("doc " + doc.id))}</option>`).join("") : '<option value="">No ready documents</option>';
}

async function loadWorkerStatus() {
  const status = $("opsWorkerStatus");
  const target = $("opsWorkerTable");
  if (!status && !target) return;
  try {
    const data = await api("/api/tasks/worker/status");
    if (status) status.textContent = data.running ? `running · ${data.worker_id || "worker"}` : "stopped";
    if (target) target.innerHTML = table(["Field", "Value"], [["running", String(!!data.running)], ["processed", data.processed || 0], ["last_error", data.last_error || ""], ["last_result", JSON.stringify(data.last_result || {}).slice(0, 260)]]);
  } catch (err) {
    if (status) status.textContent = err.message;
  }
}

async function loadOps() {
  if (!$("view-ops")) return;
  try {
    const readiness = await api("/api/system/readiness");
    if ($("opsReadinessScore")) $("opsReadinessScore").textContent = `Readiness: ${readiness.percent}% · ${readiness.enterprise_ready ? "enterprise ops gate passed" : "needs attention"}`;
    if ($("opsReadinessTable")) $("opsReadinessTable").innerHTML = table(["Check", "Status", "Weight"], (readiness.checks || []).map(item => [item.label, { html: statusBadge(item.ok ? "success" : "failed") }, item.weight]));
  } catch (err) {
    if ($("opsReadinessScore")) $("opsReadinessScore").textContent = "Readiness failed: " + err.message;
  }
  await Promise.allSettled([loadWorkerStatus(), loadKnowledgeDocuments().then(renderOpsDocuments)]);
}

async function runConfigCheck() {
  try {
    const data = await api("/api/system/config/check");
    if ($("opsConfigStatus")) $("opsConfigStatus").textContent = data.ok ? "ok" : "needs attention";
    if ($("opsConfigTable")) $("opsConfigTable").innerHTML = table(["Item", "Status", "Detail"], (data.checks || []).map(item => [item.name || item.id || "", { html: statusBadge(item.ok ? "success" : "failed") }, item.message || item.detail || ""]));
  } catch (err) {
    if ($("opsConfigStatus")) $("opsConfigStatus").textContent = err.message;
  }
}

async function createBackup() {
  try {
    const data = await api("/api/system/backup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ output_dir: $("opsBackupDir")?.value || "output/backups", label: $("opsBackupLabel")?.value || "manual" }) });
    if ($("opsBackupResult")) $("opsBackupResult").textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    if ($("opsBackupResult")) $("opsBackupResult").textContent = err.message;
  }
}

async function restoreBackup() {
  try {
    const data = await api("/api/system/restore", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ backup_path: $("opsRestorePath")?.value || "", confirm: Boolean($("opsRestoreConfirm")?.checked), label: "pre-restore" }) });
    if ($("opsBackupResult")) $("opsBackupResult").textContent = JSON.stringify(data, null, 2);
    await refreshAll();
  } catch (err) {
    if ($("opsBackupResult")) $("opsBackupResult").textContent = err.message;
  }
}

async function startWorker() { await api("/api/tasks/worker/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ worker_id: "console-worker", interval_s: 0.5, max_attempts: 3 }) }); await loadWorkerStatus(); }
async function stopWorker() { await api("/api/tasks/worker/stop", { method: "POST" }); await loadWorkerStatus(); }
async function tickWorker() { const data = await api("/api/tasks/worker/tick", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ worker_id: "console-worker", max_attempts: 3 }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await Promise.allSettled([loadWorkerStatus(), loadTasks()]); }
async function queueReportJob() { const id = Number($("opsReportDocumentSelect")?.value || 0); if (!id) { if ($("opsJobResult")) $("opsJobResult").textContent = "Select a ready document first"; return; } const data = await api("/api/tasks/jobs/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ library_document_id: id, report_style: $("opsReportStyle")?.value || "journal", output_dir: $("opsReportOutputDir")?.value || "output/reports", formats: ["markdown", "pdf"] }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await loadTasks(); }
async function queueOcrJob() { const data = await api("/api/tasks/jobs/ocr-queue", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: $("opsOcrCategory")?.value || "", limit: Number($("opsOcrLimit")?.value || 12), force: true }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await loadTasks(); }
async function queueBatchIngestJob() { const files = ($("opsBatchFiles")?.value || "").split(/\n|,|;/).map(item => item.trim()).filter(Boolean); const data = await api("/api/tasks/jobs/batch-ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ files, category: $("opsBatchCategory")?.value || "domain" }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await loadTasks(); }

async function loadKnowledgeGraph() {
  const map = $("knowledgeMap");
  const edges = $("knowledgeEdges");
  if (!map || !edges) return;
  try {
    const query = knowledgeCategory ? "?category=" + encodeURIComponent(knowledgeCategory) : "";
    const graph = await api("/api/knowledge/graph" + query);
    const nodes = (graph.nodes || []).slice(0, 26);
    if (!nodes.length) return;
    const root = nodes.find(node => node.type === "category") || nodes[0];
    const ordered = [root, ...nodes.filter(node => node.id !== root.id)];
    const radius = 38;
    const pos = {};
    map.innerHTML = ordered.map((node, index) => {
      let left = 50;
      let top = 50;
      if (index > 0) {
        const angle = (Math.PI * 2 * (index - 1)) / Math.max(ordered.length - 1, 1) - Math.PI / 2;
        left = 50 + Math.cos(angle) * radius;
        top = 50 + Math.sin(angle) * Math.min(radius, 31);
      }
      pos[node.id] = { left, top };
      const cls = index === 0 ? "map-node core" : "map-node";
      const label = String(node.label || node.id || "node").slice(0, 18);
      return `<button class="${cls}" style="left:${left}%;top:${top}%" title="${esc(node.label || node.id)}"><b>${esc(label)}</b><span>${esc(node.type || "node")} · ${Number(node.weight || 1)}</span></button>`;
    }).join("");
    const color = type => ({ contains: "rgba(17,24,39,.22)", cites: "rgba(37,99,235,.38)", tagged: "rgba(22,163,74,.42)", links_to: "rgba(147,51,234,.38)", backlink: "rgba(220,38,38,.42)", sourced_from: "rgba(217,119,6,.42)", mentions: "rgba(8,145,178,.36)" }[type] || "rgba(17,24,39,.22)");
    edges.innerHTML = (graph.edges || []).filter(edge => pos[edge.source] && pos[edge.target]).slice(0, 80).map(edge => `<line x1="${pos[edge.source].left}%" y1="${pos[edge.source].top}%" x2="${pos[edge.target].left}%" y2="${pos[edge.target].top}%" stroke="${color(edge.type)}" stroke-width="${edge.type === "backlink" ? 2.4 : 1.6}"><title>${esc(edge.type || "edge")}</title></line>`).join("");
    const summary = `${knowledgeCategoryLabel(knowledgeCategory)} · ${nodes.length} 个节点 · ${graph.edges?.length || 0} 条关系`;
    if ($("knowledgeMapHint")) $("knowledgeMapHint").textContent = summary;
    if ($("knowledgeGraphSummary")) $("knowledgeGraphSummary").textContent = summary;
    if ($("knowledgeMapHint")) $("knowledgeMapHint").textContent = `${graph.category || "all"} · ${nodes.length} 个真实节点 · ${graph.edges?.length || 0} 条语义关系`;
  } catch (err) {}
}

async function loadOcrQueue() {
  const target = $("ocrQueueTable");
  if (!target) return;
  try {
    const query = knowledgeCategory ? "?category=" + encodeURIComponent(knowledgeCategory) : "";
    const data = await api("/api/documents/ocr-queue" + query);
    target.innerHTML = table(["文档", "库", "页码", "原因", "操作"], (data.documents || []).map(item => [item.title || item.filename || "", knowledgeCategoryLabel(item.category), Array.isArray(item.ocr_pages) ? item.ocr_pages.join(", ") : "", item.ocr_reason || "low_extractable_text", { html: `<button class="secondary" onclick="runDocumentOcr(${Number(item.id)})">运行 OCR</button>` }]));
  } catch (err) {
    target.innerHTML = table(["文档", "库", "页码", "原因", "操作"], []);
  }
}

async function runDocumentOcr(id) {
  const sidecar = window.prompt("可选：粘贴 OCR 文本；留空则尝试本地 sidecar 或 tesseract 引擎。", "") || "";
  if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "OCR 正在处理并重建索引";
  try {
    const data = await api(`/api/documents/${Number(id)}/ocr`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sidecar_text: sidecar, force: true }) });
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = data.ok ? `OCR 完成，生成 ${data.chunk_count || 0} 个分块` : `OCR 未完成：${data.reason || data.status}`;
    await Promise.allSettled([loadOcrQueue(), loadKnowledge(), loadKnowledgeGraph(), searchKnowledge()]);
  } catch (err) {
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "OCR 处理失败：" + err.message;
  }
}

async function askCitationAnswer() {
  const target = $("citationAnswerTable");
  if (!target) return;
  const query = ($("citationQuery")?.value || "").trim();
  if (!query) {
    target.innerHTML = table(["引用", "文档", "片段"], []);
    return;
  }
  const category = knowledgeCategory ? "&category=" + encodeURIComponent(knowledgeCategory) : "";
  try {
    const data = await api("/api/documents/citation-answer?q=" + encodeURIComponent(query) + category + "&limit=6");
    target.innerHTML = table(["引用", "文档", "片段"], (data.citations || []).map(item => [item.citation, item.title || "", item.snippet || ""]));
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `引用回答已生成 · ${data.count || 0} 条证据`;
  } catch (err) {
    target.innerHTML = table(["引用", "文档", "片段"], [["error", "", err.message]]);
  }
}

async function loadRoutingStrategy() {
  const target = $("routingPolicyTable");
  if (!target) return;
  try {
    const data = await api("/api/routing/policy?q=" + encodeURIComponent("科研 网页 文件 项目"));
    target.innerHTML = table(["场景", "分数", "模型策略", "检索", "确认"], (data.candidates || []).slice(0, 6).map(item => [item.scenario, Math.round((item.score || 0) * 100) + "%", item.model_profile || "--", item.retrieval || "--", (item.requires_confirmation || []).join(" / ") || "无需"]));
  } catch (err) {}
}

async function loadSecurityCenter() {
  const policyEl = $("securityPolicyTable");
  const boundaryEl = $("securityBoundaryTable");
  const auditEl = $("securityAuditTable");
  const grantEl = $("securityGrantTable");
  if (!policyEl && !boundaryEl && !auditEl && !grantEl) return;
  try {
    const checks = await Promise.all(["web_fetch", "shell_exec", "file_write", "git_workspace", "external_api"].map(tool => api("/api/security/policy/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool, arguments: tool === "web_fetch" ? { url: "https://example.com" } : { path: "./demo.txt", command: "git status" } }) }).then(result => ({ tool, ...result })).catch(err => ({ tool, allowed: false, decision: "error", risk_level: "unknown", reason: err.message }))));
    if (policyEl) policyEl.innerHTML = table(["能力", "决策", "风险", "原因"], checks.map(item => [item.tool, item.decision || String(!!item.allowed), item.risk_level || "unknown", item.reason || item.error || ""]));
    const caps = await api("/api/workspace/capabilities").catch(() => ({ local_file_operations: { allowed_roots: [] } }));
    if (boundaryEl) boundaryEl.innerHTML = table(["边界", "状态", "说明"], [["写入根目录", { html: statusBadge((caps.local_file_operations?.allowed_roots || []).length ? "success" : "failed") }, (caps.local_file_operations?.allowed_roots || []).join(" / ") || "未配置"], ["写操作确认", { html: statusBadge(caps.local_file_operations?.requires_confirmation_for_writes ? "success" : "failed") }, "文件写入、Git、外部动作进入确认流"], ["联网确认", { html: statusBadge("pending") }, "web_fetch 默认中风险确认，内网/localhost 拦截"], ["PDF OCR", { html: statusBadge(caps.document_understanding?.pdf_ocr ? "success" : "pending") }, caps.document_understanding?.pdf_ocr || "未启用"]]);
    const grants = await api("/api/security/policy/grants?include_expired=true").catch(() => ({ grants: [] }));
    if (grantEl) grantEl.innerHTML = table(["工具", "决策", "范围", "过期", "原因", "操作"], (grants.grants || []).map(grant => [grant.tool || "*", grant.decision || "", `${grant.scope_type || "tool"} ${grant.scope_value || ""}`, grant.expires_at || "长期", grant.reason || "", { html: `<button class="secondary" onclick="revokeSecurityGrant('${esc(grant.id || "")}')">撤销</button>` }]));
    const audit = await api("/api/security/audit?limit=80").catch(() => ({ events: [] }));
    if (auditEl) auditEl.innerHTML = table(["动作", "决策", "风险", "主体", "时间"], (audit.events || []).map(item => [item.action || item.tool || "", item.decision || "", item.risk_level || item.risk || "", item.actor_id || item.actor || "", item.created_at || ""]));
  } catch (err) {
    if (policyEl) policyEl.innerHTML = table(["能力", "决策", "风险", "原因"], [["security_center", "error", "unknown", err.message]]);
  }
}

async function saveSecurityGrant() {
  const body = { tool: $("securityGrantTool")?.value || "*", decision: $("securityGrantDecision")?.value || "confirm", scope_type: $("securityGrantScopeType")?.value || "tool", scope_value: $("securityGrantScopeValue")?.value || "", expires_in_minutes: $("securityGrantMinutes")?.value || "", reason: $("securityGrantReason")?.value || "manual permission grant", created_by: "console" };
  await api("/api/security/policy/grants", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  ["securityGrantScopeValue", "securityGrantMinutes", "securityGrantReason"].forEach(id => {
    if ($(id)) $(id).value = "";
  });
  await loadSecurityCenter();
}

async function revokeSecurityGrant(id) {
  if (!id) return;
  await api(`/api/security/policy/grants/${encodeURIComponent(id)}`, { method: "DELETE" });
  await loadSecurityCenter();
}

async function loadSkills() {
  if (!$("skillsTable")) return;
  const data = await api("/api/skills").catch(() => ({ skills: [] }));
  allSkills = data.skills || data.items || [];
  renderSkillsWorkbench();
  await renderSkillVersionTables();
}

function renderSkillsWorkbench() {
  const target = $("skillsTable");
  if (!target) return;
  const query = ($("skillQuery")?.value || "").toLowerCase();
  const status = $("skillStatusFilter")?.value || "";
  const category = $("skillCategory")?.value || "";
  const rows = allSkills.filter(skill => (!query || JSON.stringify(skill).toLowerCase().includes(query)) && (!status || skill.status === status) && (!category || skill.category === category));
  target.innerHTML = rows.map(skill => `<button class="skill-card ${skill.name === selectedSkillName ? "on" : ""}" onclick="selectSkill('${esc(skill.name)}')"><b>${esc(skill.display_name || skill.name)}</b><small>${esc(skill.description || "")}</small><em>${esc(skill.category || "general")} · ${esc(skill.status || "active")}</em></button>`).join("") || '<div class="empty-state">暂无技能</div>';
  if (!selectedSkillName && rows[0]) selectSkill(rows[0].name);
}

function selectSkill(name) {
  selectedSkillName = name;
  const skill = allSkills.find(item => item.name === name) || {};
  if ($("skillDetail")) $("skillDetail").innerHTML = `<div class="skill-meta"><b>${esc(skill.display_name || skill.name || "技能")}</b><span>${esc(skill.category || "")}</span></div><p>${esc(skill.description || "")}</p><ol class="skill-steps">${(skill.steps || []).map(step => `<li>${esc(step.tool || step.name || "step")}<code>${esc(JSON.stringify(step.args || {}, null, 2))}</code></li>`).join("")}</ol>`;
  renderSkillsWorkbench();
}

async function runSelectedSkill(planOnly) {
  if (!selectedSkillName) return;
  let params = {};
  try { params = JSON.parse($("skillParams")?.value || "{}"); } catch (err) { params = {}; }
  const data = await api("/api/skills/execute", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: selectedSkillName, params, plan_only: !!planOnly }) });
  if ($("skillRunResult")) $("skillRunResult").textContent = JSON.stringify(data, null, 2);
  await renderSkillVersionTables();
}

async function renderSkillVersionTables() {
  const versions = await api("/api/skills/evolution/versions").catch(() => ({ versions: [] }));
  const runs = await api("/api/skills/evolution/runs").catch(() => ({ runs: [] }));
  const reviews = await api("/api/skills/evolution/review-inbox").catch(() => ({ items: [] }));
  skillVersions = versions.versions || [];
  skillRuns = runs.runs || [];
  skillReviews = reviews.items || reviews.reviews || [];
  if ($("skillVersionTable")) $("skillVersionTable").innerHTML = table(["技能", "版本", "状态"], skillVersions.map(item => [item.skill_name || item.name || "", item.version || "", item.status || ""]));
  if ($("skillRunTable")) $("skillRunTable").innerHTML = table(["技能", "结果", "时间"], skillRuns.map(item => [item.skill_name || item.name || "", item.passed ?? item.status ?? "", item.created_at || ""]));
  if ($("skillReviewTable")) $("skillReviewTable").innerHTML = table(["技能", "状态", "操作"], skillReviews.map(item => [item.skill_name || item.name || "", item.status || "", { html: `<button class="secondary" onclick="promoteSkill('${esc(item.skill_name || item.name || "")}')">发布</button> <button class="secondary" onclick="reviewSkill('${esc(item.id || item.skill_name || "")}','needs_changes')">需修改</button>` }]));
}

async function promoteSkill(name) { await api("/api/skills/evolution/promote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }).catch(() => ({})); await renderSkillVersionTables(); }
async function reviewSkill(id, status) { await api("/api/skills/evolution/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, status }) }).catch(() => ({})); await renderSkillVersionTables(); }

function toggleCommandDrawer() {
  const drawer = $("commandDrawer");
  drawer.classList.toggle("on");
  drawer.setAttribute("aria-hidden", drawer.classList.contains("on") ? "false" : "true");
}

function closeCommandDrawer() {
  const drawer = $("commandDrawer");
  if (!drawer) return;
  drawer.classList.remove("on");
  drawer.setAttribute("aria-hidden", "true");
}

function openDrawerView(view) {
  setView(view);
  closeCommandDrawer();
}

function openModelSettings() {
  $("modelSettings").classList.add("on");
  $("modelSettings").setAttribute("aria-hidden", "false");
  loadModelSettings();
}

function closeModelSettings() {
  $("modelSettings").classList.remove("on");
  $("modelSettings").setAttribute("aria-hidden", "true");
}

function providerPreset(provider) {
  return {
    deepseek: { model: "deepseek-chat", base_url: "https://api.deepseek.com/v1", label: "API 模式" },
    qwen: { model: "qwen", base_url: "http://127.0.0.1:8000/v1", label: "本地模式" },
    qwen_api: { model: "qwen-plus", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", label: "API 模式" },
    glm: { model: "glm-4-flash", base_url: "https://open.bigmodel.cn/api/paas/v4", label: "API 模式" },
    mock: { model: "mock", base_url: "", label: "离线模式" }
  }[provider] || { model: "", base_url: "", label: "API 模式" };
}

function modelModeText(provider) {
  return providerPreset(provider).label;
}

function applyProviderPreset(force) {
  const provider = $("cfgProvider")?.value || "deepseek";
  const preset = providerPreset(provider);
  if (force || !$("cfgModel").value) $("cfgModel").value = preset.model;
  if (force || !$("cfgBaseUrl").value) $("cfgBaseUrl").value = preset.base_url;
  if ($("modelModeLabel")) $("modelModeLabel").textContent = modelModeText(provider);
}

async function loadModelSettings() {
  try {
    const data = await api("/api/config/model");
    if ($("cfgProvider")) $("cfgProvider").value = data.provider || "deepseek";
    if ($("cfgModel")) $("cfgModel").value = data.model || "";
    if ($("cfgBaseUrl")) $("cfgBaseUrl").value = data.base_url || "";
    if ($("cfgStatus")) $("cfgStatus").textContent = "配置已读取";
  } catch (err) {
    if ($("cfgStatus")) $("cfgStatus").textContent = "读取失败：" + err.message;
  }
}

async function saveModelSettings() {
  const body = { provider: $("cfgProvider")?.value, model: $("cfgModel")?.value, base_url: $("cfgBaseUrl")?.value, api_key: $("cfgApiKey")?.value };
  await api("/api/config/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if ($("cfgStatus")) $("cfgStatus").textContent = "已保存配置";
  if ($("localModelNote")) $("localModelNote").textContent = "Local Qwen 模式只保存端点；需要离线模型时请手动下载/启动。";
  closeModelSettings();
  await loadHealth();
}

function chooseFirstRunModel(provider) {
  const modal = $("modelSettings");
  if (modal) {
    modal.classList.add("on");
    modal.setAttribute("aria-hidden", "false");
  }
  if ($("cfgProvider")) $("cfgProvider").value = provider;
  applyProviderPreset(true);
  if ($("cfgStatus")) $("cfgStatus").textContent = "\u5df2\u9009\u62e9 " + modelModeText(provider);
}

async function refreshAll() {
  ensureProfessionalBoard();
  renderKnowledgeWorkspaceShell();
  await Promise.allSettled([loadHealth(), loadDash(), loadRoutingStrategy(), loadKnowledge(), loadKnowledgeDocuments(), loadKnowledgeGraph(), loadOcrQueue(), loadMemory(), loadReflection(), loadEvolution(), loadSkills(), loadTools(), loadToolExecutions(), loadTasks(), loadBenchmarks(), loadCapabilities(), loadSecurityCenter(), loadOps()]);
  if (window.loadRuntimeRecords) window.loadRuntimeRecords();
}

if ($("cfgProvider")) $("cfgProvider").addEventListener("change", () => applyProviderPreset(true));
applyReportPreset();
renderKnowledgeWorkspaceShell();
loadSessions();
startTaskStream();
const initialView = (location.hash || "").replace("#", "");
setView(initialView);
setInterval(loadHealth, 30000);
setInterval(() => {
  if (!taskStream) loadTasks();
}, 5000);
