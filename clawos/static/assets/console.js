const API = location.origin;
let currentSession = "default";
let busy = false;
let lastToolCalls = [];
let lastRoutingStrategy = null;
let dailyLocalAcceptanceSummary = "";
let localWorkbenchTimelineItems = [];
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
let lastKnowledgeGraph = { nodes: [], edges: [], category: "all" };

const $ = id => document.getElementById(id);
const VIEW_META = {
  chat: ["今日工作台", "任务、进度、交付与审批集中在一个工作面"],
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
  feishu: ["飞书连接器", "消息、纪要、审批与回执"],
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

const WORKBENCH_PROMPTS = {
  "编写与开发": "请分析当前项目，给出可执行的开发计划，完成编码、测试、审查与交付闭环。",
  "会议纪要": "请处理会议材料，输出结构化纪要、决策、行动项、负责人和日历跟进建议。",
  "数据分析": "请分析所附数据，完成清洗、统计、公式、图表、洞察和高质量工作簿交付。",
  "论文精读": "请精读所附论文，提取方法、实验、发现、局限与引用证据，并沉淀到知识库。"
};

function useWorkbenchPrompt(kind) {
  usePrompt(WORKBENCH_PROMPTS[kind] || "请描述需要完成的目标和交付物。");
  $("prompt")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function setAutonomyMode(mode) {
  const hints = {
    suggest: "只生成计划与建议，不执行写入或外部动作。",
    approve: "文件发布、外部沟通、数据写入等关键动作将请求批准。",
    auto: "仅在已授权范围内自动执行；越界动作仍会请求批准。"
  };
  document.querySelectorAll("[data-autonomy]").forEach(button => {
    const active = button.dataset.autonomy === mode;
    button.classList.toggle("on", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  if ($("autonomyHint")) $("autonomyHint").textContent = hints[mode] || hints.approve;
  localStorage.setItem("clawos-autonomy-mode", mode);
}

function workbenchProgress(task) {
  const raw = task.progress_percent ?? task.progress;
  const value = Number(raw);
  if (!Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
}

function workbenchStatusLabel(status) {
  const labels = {
    succeeded: "已完成", running: "进行中", in_progress: "进行中", processing: "处理中",
    queued: "排队中", pending: "待开始", waiting: "等待中", failed: "需处理",
    canceled: "已取消", cancelled: "已取消", interrupted: "可恢复"
  };
  return labels[String(status || "").toLowerCase()] || "已记录";
}

function renderWorkbenchTasks(tasks) {
  const target = $("workbenchTaskList");
  const sidebarTarget = $("chatTaskSidebarList");
  if (!target && !sidebarTarget) return;
  const activeStatuses = new Set(["running", "in_progress", "processing", "queued", "pending", "waiting", "interrupted"]);
  const rows = (tasks || []).filter(task => activeStatuses.has(String(task.status || "").toLowerCase())).slice(0, 3);
  if (!rows.length) {
    const emptyMarkup = `<div class="workbench-empty-state"><b>暂无运行中的任务</b><span>从上方输入目标，任务启动后会在这里显示真实进度与状态。</span></div>`;
    if (target) target.innerHTML = emptyMarkup;
    if (sidebarTarget) sidebarTarget.innerHTML = emptyMarkup;
    return;
  }
  const taskMarkup = rows.map((task, index) => {
    const progress = workbenchProgress(task);
    const id = Number(task.id) || 0;
    const progressMarkup = progress === null
      ? `<span class="task-live-state">${esc(workbenchStatusLabel(task.status))}</span>`
      : `<div class="task-progress" role="progressbar" aria-label="${esc(task.title || "任务")}进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress}"><span><i style="width:${progress}%"></i></span><b>${progress}%</b></div>`;
    return `<article class="active-task-row">
      <div class="task-index">${String(index + 1).padStart(2, "0")}</div>
      <div class="task-summary"><b>${esc(task.title || `任务 #${id}`)}</b><span>${esc(task.source || "ClawOS")} · ${esc(workbenchStatusLabel(task.status))}</span></div>
      ${progressMarkup}
      <button class="secondary compact" type="button" onclick="openWorkbenchTask(${id})">查看进度</button>
    </article>`;
  }).join("");
  if (target) target.innerHTML = taskMarkup;
  if (sidebarTarget) sidebarTarget.innerHTML = taskMarkup;
}

function toggleChatProgress(force) {
  const panel = $("chatProgressPanel");
  const toggle = document.querySelector(".chat-progress-toggle");
  if (!panel) return;
  const open = typeof force === "boolean" ? force : !panel.classList.contains("on");
  panel.classList.toggle("on", open);
  panel.setAttribute("aria-hidden", open ? "false" : "true");
  toggle?.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) window.setTimeout(() => panel.querySelector("button")?.focus(), 0);
  else toggle?.focus();
}

function openWorkbenchTask(id) {
  if (id) lastTaskId = id;
  setView("tasks");
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
  document.body.classList.remove("sidebar-open");
  closeCommandDrawer();
  refreshView(viewName);
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
  if (window.matchMedia("(max-width: 760px)").matches) document.body.classList.toggle("sidebar-open");
  else document.body.classList.toggle("sidebar-collapsed");
}

function safeMarkdownUrl(value) {
  const url = String(value || "").trim();
  return /^(https?:\/\/|mailto:)/i.test(url) ? url : "";
}

function renderMarkdownInline(value) {
  const codeSpans = [];
  let text = String(value || "").replace(/`([^`]+)`/g, (_, code) => {
    codeSpans.push(`<code>${esc(code)}</code>`);
    return `\uE000CODE${codeSpans.length - 1}\uE001`;
  });
  text = esc(text);
  text = text.replace(/\[([^\]]+)\]\(([^\s)]+)\)/g, (_, label, url) => {
    const safe = safeMarkdownUrl(url);
    return safe ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${label}</a>` : label;
  });
  text = text.replace(/(^|[\s(>])(https?:\/\/[^\s<]+[^\s<.,:;!?\])}])/g, (_, prefix, url) => `${prefix}<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(url)}</a>`);
  text = text
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\uE000CODE(\d+)\uE001/g, (_, index) => codeSpans[Number(index)] || "");
  return text;
}

function markdownTable(lines, start) {
  if (start + 1 >= lines.length || !lines[start].includes("|")) return null;
  const separator = lines[start + 1].trim();
  if (!/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(separator)) return null;
  const split = line => line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
  const head = split(lines[start]);
  const rows = [];
  let index = start + 2;
  while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
    rows.push(split(lines[index]));
    index += 1;
  }
  const header = `<thead><tr>${head.map(cell => `<th>${renderMarkdownInline(cell)}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${rows.map(row => `<tr>${head.map((_, column) => `<td>${renderMarkdownInline(row[column] || "")}</td>`).join("")}</tr>`).join("")}</tbody>`;
  return { html: `<div class="md-table-wrap"><table>${header}${body}</table></div>`, next: index };
}

function md(text) {
  const source = String(text || "").replace(/\r\n?/g, "\n");
  const codeBlocks = [];
  const withoutCode = source.replace(/```([^\n`]*)\n?([\s\S]*?)(?:```|$)/g, (_, language, code) => {
    const safeLanguage = String(language || "").trim().replace(/[^a-z0-9_+.#-]/gi, "").slice(0, 30);
    codeBlocks.push(`<figure class="md-code"><figcaption><span>${esc(safeLanguage || "代码")}</span><button type="button" class="md-copy" aria-label="复制代码">复制</button></figcaption><pre><code${safeLanguage ? ` class="language-${esc(safeLanguage)}"` : ""}>${esc(code.replace(/\n$/, ""))}</code></pre></figure>`);
    return `\n\uE000BLOCK${codeBlocks.length - 1}\uE001\n`;
  });
  const lines = withoutCode.split("\n");
  const html = [];
  let paragraph = [];
  let listType = "";
  const flushParagraph = () => {
    if (paragraph.length) html.push(`<p>${paragraph.map(renderMarkdownInline).join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (listType) html.push(`</${listType}>`);
    listType = "";
  };
  for (let index = 0; index < lines.length;) {
    const line = lines[index];
    const trimmed = line.trim();
    const table = markdownTable(lines, index);
    if (table) {
      flushParagraph(); closeList(); html.push(table.html); index = table.next; continue;
    }
    const block = trimmed.match(/^\uE000BLOCK(\d+)\uE001$/);
    if (block) {
      flushParagraph(); closeList(); html.push(codeBlocks[Number(block[1])] || ""); index += 1; continue;
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList(); const level = heading[1].length + 1; html.push(`<h${level}>${renderMarkdownInline(heading[2])}</h${level}>`); index += 1; continue;
    }
    const item = trimmed.match(/^([-*+]|\d+[.)])\s+(.+)$/);
    if (item) {
      flushParagraph(); const wanted = /^\d/.test(item[1]) ? "ol" : "ul"; if (listType !== wanted) { closeList(); listType = wanted; html.push(`<${wanted}>`); } html.push(`<li>${renderMarkdownInline(item[2])}</li>`); index += 1; continue;
    }
    if (/^>\s?/.test(trimmed)) {
      flushParagraph(); closeList(); html.push(`<blockquote>${renderMarkdownInline(trimmed.replace(/^>\s?/, ""))}</blockquote>`); index += 1; continue;
    }
    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      flushParagraph(); closeList(); html.push("<hr>"); index += 1; continue;
    }
    if (!trimmed) {
      flushParagraph(); closeList(); index += 1; continue;
    }
    closeList(); paragraph.push(line); index += 1;
  }
  flushParagraph(); closeList();
  return html.join("");
}

function enhanceMarkdown(container) {
  container?.querySelectorAll(".md-copy").forEach(button => {
    button.onclick = async () => {
      const code = button.closest(".md-code")?.querySelector("code")?.textContent || "";
      try {
        let copied = false;
        if (navigator.clipboard?.writeText) {
          try {
            await navigator.clipboard.writeText(code);
            copied = true;
          } catch (_) {
            copied = false;
          }
        }
        if (!copied) {
          const fallback = document.createElement("textarea");
          fallback.value = code;
          fallback.setAttribute("readonly", "");
          fallback.style.position = "fixed";
          fallback.style.opacity = "0";
          document.body.appendChild(fallback);
          fallback.select();
          const succeeded = document.execCommand("copy");
          fallback.remove();
          if (!succeeded) throw new Error("copy unavailable");
        }
        button.textContent = "已复制";
        window.setTimeout(() => { button.textContent = "复制"; }, 1400);
      } catch (_) {
        button.textContent = "复制失败";
      }
    };
  });
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
  enhanceMarkdown(div);
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
    enhanceMarkdown(target);
    $("chat").scrollTop = $("chat").scrollHeight;
  };
}

function formatArtifactBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function appendArtifactsToLastAssistant(artifacts) {
  const rows = Array.isArray(artifacts) ? artifacts : [];
  if (!rows.length) return;
  const messages = document.querySelectorAll("#chatInner .msg.agent");
  const message = messages[messages.length - 1];
  const body = message?.querySelector(".message-body");
  if (!body) return;
  body.querySelector(".chat-artifacts")?.remove();
  const panel = document.createElement("section");
  panel.className = "chat-artifacts";
  panel.setAttribute("aria-label", "生成的文件");
  panel.innerHTML = `<div class="chat-artifacts-head"><b>已生成文件</b><span>${rows.length} 个可交付产物</span></div><div class="chat-artifact-list">${rows.map(item => `
    <article class="chat-artifact-card">
      <div class="chat-artifact-icon" aria-hidden="true">${esc(String(item.format || "FILE").slice(0, 4).toUpperCase())}</div>
      <div class="chat-artifact-meta"><b>${esc(item.name || "未命名文件")}</b><span>${esc(formatArtifactBytes(item.bytes))} · ${esc(item.source_tool || "ClawOS")}</span></div>
      <div class="chat-artifact-actions">${["docx","xlsx","pptx"].includes(String(item.format || "").toLowerCase()) ? `<button type="button" onclick="openEmbeddedOfficeEditor('${esc(item.id)}')">编辑</button>` : ""}${item.preview_url ? `<a href="${esc(item.preview_url)}" target="_blank" rel="noopener noreferrer">预览</a>` : ""}<a class="primary" href="${esc(item.download_url)}" download>下载</a></div>
    </article>`).join("")}</div>`;
  body.appendChild(panel);
}

function appendCodingEvidenceToLastAssistant(toolCalls) {
  const calls = Array.isArray(toolCalls) ? toolCalls : [];
  const call = [...calls].reverse().find(item => item?.name === "coding_agent" && item?.result?.data?.workspace);
  if (!call) return;
  const data = call.result.data;
  const workspace = data.workspace || {};
  const changes = data.workspace_changes || {};
  const source = data.source_verification || {};
  const attempts = Array.isArray(data.attempts) ? data.attempts : [];
  const rounds = attempts.flatMap(item => item?.workflow?.rounds || []);
  const tests = rounds.flatMap(item => item?.tests || []);
  const sandbox = tests.find(item => item?.sandbox)?.sandbox || {};
  const egress = sandbox.egress || {};
  const messages = document.querySelectorAll("#chatInner .msg.agent");
  const body = messages[messages.length - 1]?.querySelector(".message-body");
  if (!body) return;
  body.querySelector(".chat-coding-evidence")?.remove();
  const panel = document.createElement("section");
  panel.className = "chat-coding-evidence";
  panel.setAttribute("aria-label", "编码执行证据");
  const sourceSafe = source.head_unchanged === true && source.working_tree_unchanged === true;
  panel.innerHTML = `<div class="chat-coding-evidence-head"><b>编码执行证据</b><span>${data.status === "passed" ? "验证通过" : esc(data.status || "已执行")}</span></div>
    <div class="chat-coding-evidence-grid">
      <div><span>隔离工作区</span><b>${workspace.isolated ? "已启用" : "未启用"}</b></div>
      <div><span>原项目目录</span><b>${sourceSafe ? "未改动" : "需要检查"}</b></div>
      <div><span>测试沙箱</span><b>${esc(sandbox.backend || "无测试证据")}</b></div>
      <div><span>外网策略</span><b>${egress.default_deny_external ? "默认拒绝" : "未验证"}</b></div>
    </div>
    <div class="chat-coding-evidence-files"><span>变更文件</span><code>${esc((changes.changed_files || []).join(", ") || "无")}</code></div>`;
  body.appendChild(panel);
}

function attachFeedbackControls(taskId) {
  if (!taskId) return;
  const messages = document.querySelectorAll("#chatInner .msg.agent");
  const message = messages[messages.length - 1];
  if (!message || message.querySelector(".message-feedback")) return;
  const toolbar = document.createElement("div");
  toolbar.className = "message-feedback";
  toolbar.dataset.taskId = String(taskId);
  toolbar.innerHTML = `
    <span>这次结果符合预期吗？</span>
    <button type="button" data-feedback-binary="true" aria-label="满意">&#128077;</button>
    <button type="button" data-feedback-binary="false" aria-label="不满意">&#128078;</button>
    <select aria-label="满意度评分">
      <option value="">评分</option>
      <option value="5">5 · 很满意</option>
      <option value="4">4 · 满意</option>
      <option value="3">3 · 一般</option>
      <option value="2">2 · 不满意</option>
      <option value="1">1 · 很不满意</option>
    </select>
    <label><input type="checkbox" data-quality-consent> 允许将本次问答匿名加入固定质量评测</label>
    <span class="feedback-status" role="status"></span>`;
  message.querySelector(".message-body")?.appendChild(toolbar);
  toolbar.querySelectorAll("[data-feedback-binary]").forEach(button => {
    button.addEventListener("click", () => submitTaskFeedback(taskId, {
      signal_type: "binary",
      value: button.dataset.feedbackBinary === "true"
    }, toolbar));
  });
  toolbar.querySelector("select")?.addEventListener("change", event => {
    if (!event.target.value) return;
    submitTaskFeedback(taskId, {
      signal_type: "rating",
      value: Number(event.target.value)
    }, toolbar);
  });
}

async function submitTaskFeedback(taskId, feedback, toolbar) {
  const status = toolbar.querySelector(".feedback-status");
  const controls = toolbar.querySelectorAll("button, select");
  controls.forEach(control => { control.disabled = true; });
  if (status) status.textContent = "正在记录…";
  try {
    await api("/api/agent-learning/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_id: Number(taskId),
        ...feedback,
        quality_consent: Boolean(toolbar.querySelector("[data-quality-consent]")?.checked),
        quality_answer: toolbar.closest(".msg.agent")?.querySelector(".mc")?.innerText || "",
        idempotency_key: `console:${taskId}:${feedback.signal_type}:${String(feedback.value)}`
      })
    });
    if (status) status.textContent = "已记录";
  } catch (err) {
    controls.forEach(control => { control.disabled = false; });
    if (status) status.textContent = "记录失败：" + err.message;
  }
}

function sendMessage() {
  const prompt = $("prompt");
  let text = prompt.value.trim();
  const ready = chatAttachments.filter(item => item.status === "ready");
  if ((!text && !ready.length) || busy) return;
  prompt.value = "";
  const wantsWebSearch = Boolean($("webSearchToggle")?.checked);
  const attachments = ready.map(item => ({
    name: item.name,
    type: item.type,
    size: item.size,
    document_id: item.document_id,
    chunk_count: item.chunk_count
  }));
  chatAttachments = chatAttachments.filter(item => item.status === "uploading");
  renderAttachmentTray();
  submitMessage(text || "请阅读附件并给出分析。", wantsWebSearch ? ["web_search", "web_fetch"] : [], attachments, wantsWebSearch ? "auto" : "off");
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

async function submitMessage(text, confirmedTools, attachments, webSearchMode = "off") {
  busy = true;
  window.activeChatController = new AbortController();
  $("send").disabled = true;
  if ($("stop")) $("stop").disabled = false;
  const names = (attachments || []).map(item => item.name).filter(Boolean);
  addMessage("user", text + (names.length ? `\n\n附件：${names.join("、")}` : ""));
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
        clawos_web_search_mode: webSearchMode,
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
    lastRoutingStrategy = data.clawos?.routing_strategy || null;
    lastTaskId = data.clawos?.task_id || lastTaskId;
    if (lastTaskId) attachFeedbackControls(lastTaskId);
    if (data.clawos?.needs_confirmation) {
      const toolNames = [...new Set((data.clawos?.confirmation_tools || tools.map(t => t.name)).filter(Boolean))];
      const risks = [...new Set(tools.map(t => t.result?.risk_level).filter(Boolean))];
      pendingConfirmation = { text, tools: toolNames, attachments: attachments || [], webSearchMode };
      const webOnly = toolNames.length && toolNames.every(name => ["web_search", "web_fetch", "scholarly_search", "scholarly_download"].includes(name));
      $("confirmText").textContent = webOnly
        ? `允许联网读取 ${toolNames.length} 类公开来源？确认后会自动继续。${risks.length ? ` 风险级别：${risks.join("/")}` : ""}`
        : `允许执行 ${toolNames.join("、") || "本地变更"}？确认后将写入文件、运行测试或生成产物。${risks.length ? ` 风险级别：${risks.join("/")}` : ""}`;
      $("confirmBar").classList.add("on");
    } else {
      pendingConfirmation = null;
      $("confirmBar").classList.remove("on");
    }
    appendArtifactsToLastAssistant(data.clawos?.artifacts || []);
    appendCodingEvidenceToLastAssistant(data.clawos?.tool_calls || []);
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
  submitMessage(pending.text, pending.tools, pending.attachments || [], pending.webSearchMode || "off");
}

function cancelPending() {
  pendingConfirmation = null;
  $("confirmBar").classList.remove("on");
}

function newChat() {
  currentSession = "s_" + Date.now();
  $("chatInner").innerHTML = `<div class="empty workbench-empty task-empty"><b>开始一个新任务</b><span>输入目标，或添加需要处理的文件。</span></div>`;
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

function sessionSummary(session) {
  const title = sessionTitle(session);
  const raw = cleanSessionTitle(session.last_message || session.topic || "");
  if (!raw || raw === "未命名会话" || raw === title) return "继续查看这段对话的上下文与结果";
  return raw.replace(/\s+/g, " ").slice(0, 88);
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
  target.innerHTML = rows.map(session => `<button class="session-result" onclick="switchSession('${esc(session.session_id)}')">
    <span class="session-result-copy"><b>${esc(sessionTitle(session).slice(0, 96))}</b><small>${esc(sessionSummary(session))}</small></span>
    <time>${esc(session.updated_at || session.session_id)}</time>
    <span class="session-continue">继续</span>
  </button>`).join("") || '<div class="empty-state">暂无匹配会话</div>';
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
    return `<div class="attachment-chip ${loading ? "loading" : ""} ${item.status === "error" ? "error" : ""}"><span class="attachment-spinner"></span><b>${esc(item.name)}</b><small>${esc(label)}</small><button type="button" onclick="removeAttachment('${esc(item.id)}')" title="移除附件"><span class="fluent-icon" aria-hidden="true">&#xE711;</span></button></div>`;
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
    actions: [["上传资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
  },
  research: {
    eyebrow: "科研资料",
    title: "科研库",
    desc: "面向论文、实验、引用和研究问题，优先展示论文节点、证据关系和可复现材料。",
    upload: "上传论文 PDF、arXiv 笔记、实验记录或引用材料，自动沉淀为研究节点。",
    actions: [["上传论文", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
  },
  learning: {
    eyebrow: "学习资料",
    title: "学习库",
    desc: "面向课程、路线、概念卡片和自测复盘，帮助你从资料走向掌握。",
    upload: "上传课程讲义、学习笔记、术语表或练习材料，形成学习路径节点。",
    actions: [["上传课程资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
  },
  writing: {
    eyebrow: "写作资料",
    title: "写作库",
    desc: "面向博客、答辩稿、商业计划书和表达素材，突出草稿、论点和引用。",
    upload: "上传草稿、素材、会议结论或参考文章，沉淀为可复用写作节点。",
    actions: [["上传写作素材", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["整理资料", "openKnowledgeOrganizer()", "secondary"]],
  },
  project: {
    eyebrow: "项目资料",
    title: "项目库",
    desc: "面向本地项目、交付包、runbook、验收报告和风险清单，服务真实交付。",
    upload: "上传项目文档、架构图说明、验收报告或 runbook，形成交付节点。",
    actions: [["上传项目资料", "document.getElementById('knowledgeFilePicker').click()", "primary"], ["检索资料", "focusKnowledgeSearch()", "secondary"]],
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
  updateKnowledgeFrontstageStats();
}

function toggleKnowledgeAdminTools() {
  const workspace = document.querySelector("#view-knowledge .knowledge-workspace");
  const expanded = workspace ? workspace.classList.toggle("show-knowledge-admin") : false;
  if ($("knowledgeAdminState")) $("knowledgeAdminState").textContent = expanded ? "已展开" : "已收起";
  if ($("knowledgeBackendState")) $("knowledgeBackendState").textContent = expanded ? "展开" : "收起";
  if ($("knowledgeAdminToggle")) $("knowledgeAdminToggle").textContent = expanded ? "收起后台" : "打开后台";
}

function updateKnowledgeFrontstageStats() {
  const mode = knowledgeCategory || "all";
  const config = KNOWLEDGE_MODES[mode] || KNOWLEDGE_MODES.all;
  const items = knowledgeItems || [];
  if ($("knowledgeActiveLibrary")) $("knowledgeActiveLibrary").textContent = config.title || "All knowledge";
  if ($("knowledgeNodeCount")) $("knowledgeNodeCount").textContent = String(items.length || 0);
  if ($("knowledgeRecentSource")) {
    const source = items.find(item => item.source)?.source || items[0]?.title || "No import";
    $("knowledgeRecentSource").textContent = String(source).slice(0, 24);
  }
  const workspace = document.querySelector("#view-knowledge .knowledge-workspace");
  const expanded = !!workspace?.classList.contains("show-knowledge-admin");
  if ($("knowledgeAdminState")) $("knowledgeAdminState").textContent = expanded ? "已展开" : "已收起";
  if ($("knowledgeBackendState")) $("knowledgeBackendState").textContent = expanded ? "展开" : "收起";
  if ($("knowledgeAdminToggle")) $("knowledgeAdminToggle").textContent = expanded ? "收起后台" : "打开后台";
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
    updateKnowledgeFrontstageStats();
    if ($("knowledgeTableHeading")) $("knowledgeTableHeading").textContent = "最近资料";
    if ($("knowledgeResultCount")) $("knowledgeResultCount").textContent = `${knowledgeItems.length} 条`;
    target.innerHTML = table(["标题", "知识库", "操作"], knowledgeItems.map(item => [
      item.title,
      knowledgeCategoryLabel(item.category),
      { html: `<button class="secondary" onclick="loadKnowledgeItem(${Number(item.id)})">打开</button> <button class="secondary" onclick="appendKnowledgeToPrompt(${Number(item.id)})">提问</button>` }
    ]));
    renderKnowledgeMap(knowledgeItems);
    loadKnowledgeGovernance();
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `${knowledgeCategoryLabel(knowledgeCategory)} · ${knowledgeItems.length} 条资料`;
  } catch (err) {
    target.innerHTML = table(["标题", "知识库", "操作"], []);
    renderKnowledgeMap([]);
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "知识库加载失败：" + err.message;
  }
}

async function loadKnowledgeGovernance() {
  if (!$("knowledgeHealthSummary")) return;
  try {
    const [stats, conflicts, quality, benchmark, candidates] = await Promise.all([
      api("/api/knowledge/v2/stats"),
      api("/api/knowledge/v2/conflicts?status=pending&limit=100"),
      api("/api/knowledge/v2/answer-quality/feedback?limit=1"),
      api("/api/knowledge/v2/answer-quality/latest"),
      api("/api/memory/candidates?limit=100")
    ]);
    const projection = stats.vector_projection || {};
    const indexState = projection.consistent ? "索引一致" : "索引待同步";
    $("knowledgeHealthSummary").textContent = `${stats.active || 0} 条有效 · ${stats.sources || 0} 个来源 · ${stats.pending_conflicts || 0} 个待审冲突 · ${indexState}`;
    if ($("knowledgeHealthGrid")) {
      $("knowledgeHealthGrid").innerHTML = [
        ["有效知识", stats.active || 0], ["来源证据", stats.sources || 0],
        ["待审冲突", stats.pending_conflicts || 0], ["过期版本", stats.expired || 0],
        ["实体关系", `${stats.entities || 0} / ${stats.relations || 0}`], ["利用事件", stats.usage_events || 0],
        ["向量投影", `${projection.knowledge_v2 || 0} / ${projection.expected_knowledge_v2 || stats.active || 0}`],
        ["索引状态", projection.consistent ? "一致" : `${projection.outbox_pending || 0} 条待同步`]
      ].map(([label, value]) => `<div><span>${esc(label)}</span><b>${esc(String(value))}</b></div>`).join("");
    }
    if ($("knowledgeConflictTable")) {
      $("knowledgeConflictTable").innerHTML = table(["知识", "冲突", "候选", "决策"], (conflicts.items || []).map(item => [
        item.title || `#${item.knowledge_id}`, item.conflict_type,
        String(item.candidate_statement || "").slice(0, 120),
        { html: `<button class="secondary" onclick="resolveKnowledgeConflict(${Number(item.id)},'keep_existing')">保留现有</button> <button class="primary" onclick="resolveKnowledgeConflict(${Number(item.id)},'accept_candidate')">接受候选</button>` }
      ]));
    }
    const qstats = quality.stats || {};
    const proxyCount = benchmark.case_count || qstats.proxy_count || 0;
    if ($("answerQualitySummary")) {
      $("answerQualitySummary").textContent = `${qstats.consented_user_count || 0} 条经同意的真实反馈 · ${proxyCount} 条固定代理评测；两者永不混算。`;
    }
    if ($("answerQualityGrid")) {
      const interval = (benchmark.confidence_intervals || {}).classification_accuracy || {};
      $("answerQualityGrid").innerHTML = [
        ["真实用户", qstats.consented_user_count || 0], ["代理评测", proxyCount],
        ["固定测试集", `${benchmark.fixed_test_count || 0} 条`], ["分类准确率 95% CI", `${Math.round((interval.lower || 0) * 1000) / 10}%–${Math.round((interval.upper || 0) * 1000) / 10}%`]
      ].map(([label, value]) => `<div><span>${esc(label)}</span><b>${esc(String(value))}</b></div>`).join("");
    }
    const memoryStats = candidates.stats || {};
    if ($("memoryCandidateSummary")) {
      $("memoryCandidateSummary").textContent = `${memoryStats.pending_review || 0} 条待审核 · ${memoryStats.blocked_sensitive || 0} 条敏感阻断 · ${memoryStats.promoted || 0} 条已晋升。`;
    }
    if ($("memoryCandidateTable")) {
      $("memoryCandidateTable").innerHTML = table(["类型", "候选", "状态", "操作"], (candidates.items || []).map(item => [
        item.candidate_type, String(item.content || "").slice(0, 120), item.status,
        { html: item.status === "pending_review"
          ? `<button class="secondary" onclick="reviewMemoryCandidate(${Number(item.id)},'reject')">拒绝</button> <button class="primary" onclick="reviewMemoryCandidate(${Number(item.id)},'approve')">批准</button>`
          : item.status === "approved" ? `<button class="primary" onclick="promoteMemoryCandidate(${Number(item.id)})">晋升</button>` : "—" }
      ]));
    }
  } catch (err) {
    $("knowledgeHealthSummary").textContent = "知识健康读取失败：" + err.message;
  }
}

async function reviewMemoryCandidate(id, decision) {
  if (!window.confirm(decision === "approve" ? "确认批准该长期记忆候选？批准后仍需单独晋升。" : "确认拒绝该长期记忆候选？")) return;
  await api(`/api/memory/candidates/${id}/review`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reviewer: "console-user", confirmed: true })
  });
  await loadKnowledgeGovernance();
}

async function promoteMemoryCandidate(id) {
  if (!window.confirm("确认把已批准候选写入长期记忆？该操作会保留来源与审核记录。")) return;
  await api(`/api/memory/candidates/${id}/promote`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: "console-user", confirmed: true })
  });
  await loadKnowledgeGovernance();
}

function openKnowledgeGovernance() {
  const panel = $("knowledgeGovernance");
  if (!panel) return;
  panel.classList.add("on");
  panel.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  loadKnowledgeGovernance();
}

function closeKnowledgeGovernance() {
  const panel = $("knowledgeGovernance");
  if (!panel) return;
  panel.classList.remove("on");
  panel.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
}

async function resolveKnowledgeConflict(id, decision) {
  await api(`/api/knowledge/v2/conflicts/${id}/resolve`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reviewer: "console-user", reason: "Reviewed in knowledge governance" })
  });
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = "冲突已审核，检索状态已更新。";
  await loadKnowledgeGovernance();
}

async function backfillKnowledgeV2() {
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = "正在增量迁移历史知识…";
  const result = await api("/api/knowledge/v2/backfill", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit: 10000 })
  });
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = `迁移 ${result.migrated || 0} 条，失败 ${result.failed || 0} 条。`;
  await loadKnowledgeGovernance();
}

async function rebuildKnowledgeIndex() {
  if (!window.confirm("确认重建知识向量索引？知识原文不会删除，但重建期间语义检索可能短暂不可用。")) return;
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = "正在重建向量索引…";
  const result = await api("/api/knowledge/v2/index/rebuild", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed: true })
  });
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = result.consistent ? "索引重建完成且一致。" : "索引重建完成，但仍有待同步项目。";
  await loadKnowledgeGovernance();
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
  openKnowledgeOrganizer();
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
  closeKnowledgeOrganizer();
  await loadKnowledge();
}

async function searchKnowledge() {
  const target = $("knowledgeTable");
  if (!target) return;
  const query = $("knowledgeQuery").value.trim();
  if (!query) {
    $("knowledgeQuery")?.focus();
    return;
  }
  const category = knowledgeCategory ? "&category=" + encodeURIComponent(knowledgeCategory) : "";
  const data = await api("/api/knowledge/search?q=" + encodeURIComponent(query) + category + "&limit=12");
  const results = data.items || [];
  knowledgeItems = [...new Map([...knowledgeItems, ...results].map(item => [Number(item.id), item])).values()];
  if ($("knowledgeTableHeading")) $("knowledgeTableHeading").textContent = "检索结果";
  if ($("knowledgeResultCount")) $("knowledgeResultCount").textContent = `${results.length} 条`;
  target.innerHTML = table(["标题", "知识库", "操作"], results.map(item => [
    item.title,
    knowledgeCategoryLabel(item.category),
    { html: `<button class="secondary" onclick="loadKnowledgeItem(${Number(item.id)})">打开</button> <button class="secondary" onclick="appendKnowledgeToPrompt(${Number(item.id)})">提问</button>` }
  ]));
}

function clearKnowledgeSearch() {
  if ($("knowledgeQuery")) $("knowledgeQuery").value = "";
  loadKnowledge();
}

function focusKnowledgeSearch() {
  $("knowledgeQuery")?.focus();
}

let knowledgeOrganizerReturnFocus = null;

function openKnowledgeOrganizer() {
  const organizer = $("knowledgeOrganizer");
  if (!organizer) return;
  knowledgeOrganizerReturnFocus = document.activeElement;
  organizer.classList.add("on");
  organizer.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  window.setTimeout(() => $("knowledgeTitle")?.focus(), 0);
}

function closeKnowledgeOrganizer() {
  const organizer = $("knowledgeOrganizer");
  if (!organizer) return;
  organizer.classList.remove("on");
  organizer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
  if (knowledgeOrganizerReturnFocus?.focus) knowledgeOrganizerReturnFocus.focus();
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
  openKnowledgeOrganizer();
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
  form.append("confirmed", "true");
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
    if ($("modelBadge")) $("modelBadge").textContent = `模型：${health.model_provider?.provider || health.provider || "-"}`;
    if ($("toolBadge")) $("toolBadge").textContent = `工具：${health.tools || health.tool_count || "-"}`;
    if ($("workbenchRuntimeState")) $("workbenchRuntimeState").textContent = ok ? "服务可用" : "需要检查";
    const provider = health.model_provider || {};
    const label = provider.provider === "mock" ? "Mock/offline test 模式" : provider.provider === "qwen" ? "Local Qwen 模式" : "DeepSeek/API 模式";
    if ($("modelModeLabel")) $("modelModeLabel").textContent = label;
    if ($("modelModeDetail")) $("modelModeDetail").textContent = provider.model || provider.base_url || "configuration-first mode";
  } catch (err) {
    $("healthDot").className = "dot bad";
    $("healthText").textContent = "服务不可用";
    if ($("workbenchRuntimeState")) $("workbenchRuntimeState").textContent = "服务离线";
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
  const rows = [];
  ["routing", "upstream"].forEach(section => {
    const state = data[section] || {};
    const primary = state.primary || {};
    if (primary.provider || primary.model) {
      rows.push([
        `${section} primary`,
        { html: statusBadge(primary.configured ? "success" : "pending") },
        `${primary.provider || "-"} / ${primary.model || "-"}`
      ]);
    }
    (state.fallbacks || []).forEach((fallback, index) => rows.push([
      `${section} fallback ${index + 1}`,
      { html: statusBadge(fallback.configured ? "success" : "pending") },
      `${fallback.provider || "-"} / ${fallback.model || "-"}`
    ]));
  });
  const localAssets = data.local_model_assets || {};
  if (localAssets.mode) {
    const missing = (localAssets.assets || []).filter(item => !item.ok).map(item => item.id).join(", ");
    rows.push([
      "local qwen assets",
      { html: statusBadge(localAssets.ready ? "success" : "pending") },
      localAssets.ready ? localAssets.summary : `${localAssets.summary || "missing local assets"}${missing ? ` (${missing})` : ""}`
    ]);
  }
  target.innerHTML = table(["Item", "Status", "Detail"], rows.length ? rows : [["model", { html: statusBadge("pending") }, "No model provider configured"]]);
}

async function refreshOfflineReadiness() {
  const status = $("offlineReadinessStatus");
  const summary = $("offlineReadinessSummary");
  const grid = $("offlineReadinessGrid");
  if (!status || !summary || !grid) return;
  status.textContent = "Checking local-first workbench readiness.";
  try {
    const data = await api("/api/workbench/offline-readiness");
    const remaining = (data.remaining || []).length;
    status.textContent = `${data.standard || "offline readiness"} 路 ${data.ok ? "ready" : `${remaining} items need attention`}`;
    const model = data.model?.local_model_assets || {};
    const paper = data.paper || {};
    summary.innerHTML = [
      ["Workbench", `${data.percent || 0}%`],
      ["System", `${data.system?.percent || 0}%`],
      ["Paper", `${paper.percent || 0}%`],
      ["Model", model.ready ? "ready" : "pending"]
    ].map(([label, value]) => `<div><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join("");
    grid.innerHTML = (data.checks || []).map(item => `
      <div class="offline-readiness-check ${item.ok ? "ok" : "pending"}">
        <div><b>${esc(item.label || item.id || "check")}</b><span>${esc(item.detail || "")}</span></div>
        ${statusBadge(item.ok ? "success" : "pending")}
      </div>
    `).join("");
  } catch (err) {
    status.textContent = "Offline readiness failed: " + err.message;
    summary.innerHTML = "";
    grid.innerHTML = "";
  }
}
async function loadLocalRemediationGuide() {
  const target = $("localRemediationGuide");
  if (!target) return;
  const data = await api("/api/workbench/local-remediation-guide?limit=30").catch(() => ({ actions: [] }));
  const actions = data.actions || [];
  target.innerHTML = actions.length ? actions.map(action => {
    const scripts = Object.values(action.scripts || {}).filter(Boolean).join(" | ") || "No script required";
    const checks = (action.checks || []).join(" | ");
    const actionPayload = esc(JSON.stringify(action));
    const status = action.status || "open";
    const lastRecheck = action.last_recheck || {};
    const recheckText = lastRecheck.checked_at ? `Recheck: ${lastRecheck.ok ? "ok" : "needs attention"} ${lastRecheck.checked_at}` : "Recheck: not run";
    return `<div class="local-remediation-card ${esc(action.severity || "low")} ${esc(status)}">
      <div><b>${esc(action.gap || action.id || "readiness gap")}</b><span>${esc(action.why || "")}</span></div>
      <p>${esc(action.action || "")}</p>
      <small>Status: ${esc(status)} ${action.status_note ? "- " + esc(action.status_note) : ""}</small>
      <small>${esc(recheckText)}</small>
      <small>Scripts: ${esc(scripts)}</small>
      <small>Checks: ${esc(checks)}</small>
      <div class="local-remediation-actions">
        <button class="secondary" type="button" data-action='${actionPayload}' onclick="markLocalRemediationAction(this, 'reviewed')">Mark reviewed</button>
        <button class="secondary" type="button" data-action='${actionPayload}' onclick="markLocalRemediationAction(this, 'resolved')">Mark resolved</button>
        <button class="secondary" type="button" data-action='${actionPayload}' onclick="recheckLocalRemediationAction(this)">Recheck</button>
      </div>
    </div>`;
  }).join("") : '<div class="local-remediation-card"><b>No remediation actions</b><span>Run daily local acceptance to collect readiness gaps.</span></div>';
}

async function markLocalRemediationAction(button, status) {
  const raw = button?.dataset?.action || "{}";
  let action = {};
  try { action = JSON.parse(raw); } catch (err) { action = {}; }
  const state = $("offlineReadinessStatus");
  if (state) state.textContent = `Marking remediation ${status}.`;
  await api("/api/workbench/local-remediation-actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action_id: action.action_id || action.id, action, status })
  });
  if (state) state.textContent = `Remediation marked ${status}.`;
  await loadLocalRemediationGuide();
}
async function recheckLocalRemediationAction(button) {
  const raw = button?.dataset?.action || "{}";
  let action = {};
  try { action = JSON.parse(raw); } catch (err) { action = {}; }
  const state = $("offlineReadinessStatus");
  if (state) state.textContent = "Running safe local remediation recheck.";
  const data = await api("/api/workbench/local-remediation-actions/recheck", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action_id: action.action_id || action.id, action })
  });
  const result = data.recheck || {};
  if (state) state.textContent = `Remediation recheck ${result.ok ? "passed" : "needs attention"}.`;
  await loadLocalRemediationGuide();
}
async function loadLocalWorkbenchTimeline() {
  const target = $("localWorkbenchTimelineTable");
  if (!target) return;
  const data = await api("/api/workbench/local-timeline?limit=20").catch(() => ({ items: [] }));
  localWorkbenchTimelineItems = data.items || [];
  const rows = localWorkbenchTimelineItems.map((item, index) => [
    item.updated_at || "",
    item.label || item.kind || "event",
    { html: statusBadge(item.status === "pass" ? "success" : item.status === "fail" ? "failed" : item.status || "pending") },
    item.summary || item.title || item.run_id || "",
    item.detail || "",
    { html: `<button class="secondary" type="button" onclick="openLocalTimelineEvent(${index})">Open</button>` }
  ]);
  target.innerHTML = table(
    ["Time", "Event", "Status", "Summary", "Detail", "Open"],
    rows.length ? rows : [["", "No local workbench events", "", "", "", ""]]
  );
}

async function openLocalTimelineEvent(index) {
  const item = localWorkbenchTimelineItems[index] || {};
  const target = $("localWorkbenchTimelineDetail");
  if (!target) return;
  if (item.kind === "maintenance_report" && item.run_id) {
    await openLocalMaintenanceReport(item.run_id);
    target.textContent = `Opened maintenance report: ${item.run_id}`;
    return;
  }
  const payload = item.payload || {};
  const lines = [
    `Event: ${item.label || item.kind || "event"}`,
    `Run: ${item.run_id || ""}`,
    `Status: ${item.status || ""}`,
    `Time: ${item.updated_at || ""}`,
    `Summary: ${item.summary || ""}`,
    `Detail: ${item.detail || ""}`,
    "",
    JSON.stringify(payload, null, 2)
  ];
  target.textContent = lines.join("\n");
}
async function loadLocalAcceptanceHistory() {
  const target = $("localAcceptanceHistoryTable");
  if (!target) return;
  await loadLocalWorkbenchTimeline();
  await loadLocalRemediationGuide();
  await loadLocalMaintenanceReports();
  const [data, trendData] = await Promise.all([
    api("/api/workbench/local-acceptance-history?limit=12").catch(() => ({ runs: [] })),
    api("/api/workbench/local-acceptance-trends?limit=30").catch(() => ({ trend: {} }))
  ]);
  const trend = trendData.trend || {};
  const trendGrid = $("localAcceptanceTrendGrid");
  if (trendGrid) {
    const latest = trend.latest || {};
    const gaps = (trend.top_readiness_gaps || []).map(item => `${item.label}:${item.count}`).join(", ") || "none";
    trendGrid.innerHTML = [
      ["Latest", latest.status || "--"],
      ["Daily pass", `${Math.round((trend.daily_pass_rate || 0) * 100)}%`],
      ["Qwen streak", String(trend.qwen_failure_streak || 0)],
      ["Avg readiness", `${trend.average_workbench_percent || 0}%`],
      ["Top gaps", gaps]
    ].map(([label, value]) => `<div><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join("");
  }
  const rows = (data.runs || []).map(run => [
    run.updated_at || "",
    run.run_type === "workbench_qwen_smoke" ? "Qwen smoke" : "Daily check",
    { html: statusBadge(run.status === "pass" ? "success" : "failed") },
    `${run.workbench_percent || 0}%`,
    run.qwen_ok === null || run.qwen_ok === undefined ? "--" : (run.qwen_ok ? "ok" : (run.qwen_error || "failed")),
    run.summary || run.run_id || ""
  ]);
  target.innerHTML = table(["Time", "Type", "Status", "Readiness", "Qwen", "Summary"], rows.length ? rows : [["", "No local acceptance history", "", "", "", ""]]);
}
async function runDailyLocalAcceptance(includeQwenSmoke = false) {
  const status = $("offlineReadinessStatus");
  const summary = $("dailyAcceptanceSummary");
  if (status) status.textContent = includeQwenSmoke ? "Running daily local acceptance with Qwen smoke." : "Running daily local acceptance.";
  if (summary) summary.textContent = includeQwenSmoke ? "Running quick local checks and local Qwen smoke..." : "Running quick local checks...";
  try {
    const data = await api("/api/workbench/daily-local-acceptance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 5, full_suite: false, include_qwen_smoke: includeQwenSmoke })
    });
    dailyLocalAcceptanceSummary = data.summary || JSON.stringify(data, null, 2);
    if (summary) summary.textContent = dailyLocalAcceptanceSummary;
    if (status) status.textContent = `Daily local acceptance ${data.ok ? "passed" : "needs attention"}.`;
    await refreshOfflineReadiness();
    await loadLocalAcceptanceHistory();
  } catch (err) {
    dailyLocalAcceptanceSummary = "";
    if (summary) summary.textContent = "Daily local acceptance failed: " + err.message;
    if (status) status.textContent = "Daily local acceptance failed.";
  }
}

async function runLocalQwenSmokeCheck() {
  const status = $("offlineReadinessStatus");
  const summary = $("dailyAcceptanceSummary");
  if (status) status.textContent = "Running local Qwen smoke check.";
  if (summary) summary.textContent = "Calling local Qwen endpoint only...";
  try {
    const data = await api("/api/workbench/local-qwen-smoke", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timeout_s: 20 })
    });
    dailyLocalAcceptanceSummary = [
      "ClawOS Local Qwen Smoke",
      `Status: ${data.ok ? "ok" : "not ready"}`,
      `Endpoint: ${data.base_url || ""}`,
      `Model: ${data.model || ""}`,
      `Assets: ${data.assets_summary || ""}`,
      `Error: ${data.error || ""}`,
      `Preview: ${data.content_preview || ""}`
    ].join("\n");
    if (summary) summary.textContent = dailyLocalAcceptanceSummary;
    if (status) status.textContent = `Local Qwen smoke ${data.ok ? "passed" : "needs attention"}.`;
    await refreshOfflineReadiness();
    await loadLocalAcceptanceHistory();
  } catch (err) {
    dailyLocalAcceptanceSummary = "";
    if (summary) summary.textContent = "Local Qwen smoke failed: " + err.message;
    if (status) status.textContent = "Local Qwen smoke failed.";
  }
}
async function exportLocalMaintenanceReport() {
  const status = $("offlineReadinessStatus");
  const summary = $("dailyAcceptanceSummary");
  if (status) status.textContent = "Exporting local maintenance report.";
  if (summary) summary.textContent = "Writing local Markdown and JSON maintenance report...";
  try {
    const data = await api("/api/workbench/local-maintenance-report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit: 30 })
    });
    const jsonPath = data.artifacts?.json?.path || "";
    const markdownPath = data.artifacts?.markdown?.path || "";
    dailyLocalAcceptanceSummary = [
      "ClawOS Local Maintenance Report",
      `JSON: ${jsonPath}`,
      `Markdown: ${markdownPath}`,
      `Readiness: ${data.report?.readiness?.percent || 0}%`,
      `Remediation actions: ${data.report?.remediation?.count || 0}`,
      `Run: ${data.run?.run_id || "not persisted"}`
    ].join("\n");
    if (summary) summary.textContent = dailyLocalAcceptanceSummary;
    if (status) status.textContent = "Local maintenance report exported.";
    await loadLocalAcceptanceHistory();
    await loadLocalMaintenanceReports();
    if (data.run?.run_id) await openLocalMaintenanceReport(data.run.run_id);
  } catch (err) {
    dailyLocalAcceptanceSummary = "";
    if (summary) summary.textContent = "Local maintenance report export failed: " + err.message;
    if (status) status.textContent = "Local maintenance report export failed.";
  }
}
async function loadLocalMaintenanceReports() {
  const tableTarget = $("localMaintenanceReportTable");
  if (!tableTarget) return;
  const data = await api("/api/workbench/local-maintenance-reports?limit=8").catch(() => ({ reports: [] }));
  const rows = (data.reports || []).map(report => {
    const runId = String(report.run_id || "");
    return [
      report.updated_at || report.created_at || "",
      `${report.readiness_percent || 0}%`,
      report.history_count || 0,
      report.remediation_count || 0,
      report.markdown_path || "",
      { html: `<button class="secondary" type="button" onclick='openLocalMaintenanceReport(${JSON.stringify(runId)})'>View</button>` }
    ];
  });
  tableTarget.innerHTML = table(
    ["Time", "Readiness", "History", "Actions", "Markdown", "Open"],
    rows.length ? rows : [["", "No maintenance reports", "", "", "", ""]]
  );
}

async function openLocalMaintenanceReport(runId) {
  const preview = $("localMaintenanceReportPreview");
  if (!preview || !runId) return;
  preview.textContent = "Loading maintenance report...";
  try {
    const data = await api(`/api/workbench/local-maintenance-reports/${encodeURIComponent(runId)}`);
    const summary = data.summary || {};
    const reportRemediation = data.report_remediation || {};
    const currentRemediation = data.current_remediation || {};
    const currentActions = currentRemediation.actions || [];
    const rechecked = currentActions.filter(item => item.last_recheck && item.last_recheck.checked_at).length;
    preview.textContent = [
      `Run: ${summary.run_id || runId}`,
      `Readiness: ${summary.readiness_percent || 0}%`,
      `JSON: ${summary.json_path || ""}`,
      `Markdown: ${summary.markdown_path || ""}`,
      `Report remediation: reviewed ${reportRemediation.reviewed_count || 0}, resolved ${reportRemediation.resolved_count || 0}`,
      `Current remediation: reviewed ${currentRemediation.reviewed_count || 0}, resolved ${currentRemediation.resolved_count || 0}, rechecked ${rechecked}`,
      "",
      data.markdown || "No Markdown content."
    ].join("\n");
    const status = $("offlineReadinessStatus");
    if (status) status.textContent = "Local maintenance report loaded.";
  } catch (err) {
    preview.textContent = "Maintenance report load failed: " + err.message;
  }
}
async function copyDailyLocalAcceptanceSummary() {
  const summary = dailyLocalAcceptanceSummary || $("dailyAcceptanceSummary")?.textContent || "";
  if (!summary.trim()) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(summary);
  }
  const status = $("offlineReadinessStatus");
  if (status) status.textContent = "Daily local acceptance summary copied.";
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
  const route = lastRoutingStrategy
    ? `<div class="item"><b>场景路由 · ${esc(lastRoutingStrategy.scenario || "general")}</b><span>${esc(lastRoutingStrategy.mode || "")} · ${esc(lastRoutingStrategy.model_profile || "balanced")} · 允许 ${Number(lastRoutingStrategy.allowed_tools?.length || 0)} 个工具</span></div>`
    : "";
  const tools = lastToolCalls.length ? lastToolCalls.map(tool => `<div class="item"><b>${esc(tool.name || "tool")}</b><span>${esc(JSON.stringify(tool.result || {}).slice(0, 180))}</span></div>`).join("") : '<div class="item"><span>暂无工具调用</span></div>';
  target.innerHTML = route + tools;
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
  const canActivate = status === "canary";
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

async function loadCompetitionReadiness() {
  if (!$("competitionPhaseGrid")) return;
  const status = $("competitionReadinessStatus");
  if (status) status.textContent = "正在核对软件、数据、硬件和发布证据…";
  try {
    const data = await api("/api/competition/readiness");
    const claims = data.claims || {};
    if ($("competitionReadinessSummary")) {
      $("competitionReadinessSummary").innerHTML = table(["结论", "状态", "证据边界"], [
        ["软件 P0-P2", { html: statusBadge(data.software_p0_p2_closed ? "passed" : "failed") }, "版本化合同、真实本地数据和状态机"],
        ["比赛发布", { html: statusBadge(data.competition_release_ready ? "ready" : "blocked") }, data.hardware?.ready ? "目标硬件证据完整" : "仍缺目标硬件真实报告"],
        ["真实用户学习", { html: statusBadge(claims.real_user_learning_validated ? "ready" : "collecting") }, claims.real_user_learning_validated ? "Reward 与偏好门槛已达标" : "继续积累真实显式反馈"],
        ["在线 RL", { html: statusBadge(claims.online_rl ? "claimed" : "not claimed") }, "当前实现保持离线、门控和人工确认"]
      ]);
    }
    const phases = ["p0", "p1", "p2"].map(name => ({ name: name.toUpperCase(), ...(data[name] || {}) }));
    $("competitionPhaseGrid").innerHTML = phases.map(phase => {
      const checks = Object.entries(phase.checks || {});
      const passed = checks.filter(([, value]) => value).length;
      return `<article class="competition-phase-card"><div><span>${esc(phase.name)}</span>${statusBadge(phase.software_closed ? "software closed" : "blocked")}</div><b>${passed}/${checks.length} 门禁通过</b><ul>${checks.map(([name, value]) => `<li>${statusBadge(value ? "passed" : "failed")} ${esc(name)}</li>`).join("")}</ul></article>`;
    }).join("");
    const flows = data.p0?.demo_contracts?.flows || [];
    if ($("competitionDemoTable")) {
      $("competitionDemoTable").innerHTML = table(["场景", "演示链", "冻结用例", "合同"], flows.map(flow => [
        flow.scenario || "",
        flow.title || flow.id || "",
        (flow.benchmark_cases || []).length,
        { html: statusBadge(flow.backed_by_frozen_cases ? "backed" : "missing") }
      ]));
    }
    if ($("competitionNextActions")) {
      $("competitionNextActions").innerHTML = (data.next_actions || []).map(item => `<li>${esc(item)}</li>`).join("") || "<li>全部发布门禁已满足。</li>";
    }
    if (status) status.textContent = `证据摘要 ${String(data.evidence_digest || "").slice(0, 12)} · ${data.competition_release_ready ? "可进入比赛发布" : "保持门控"}`;
  } catch (err) {
    if (status) status.textContent = "Readiness 加载失败：" + err.message;
  }
}

async function exportCompetitionReadiness() {
  const status = $("competitionReadinessStatus");
  try {
    const data = await api("/api/competition/readiness/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmed: true })
    });
    if (status) status.textContent = `验收包已导出 · ${data.markdown_path || ""}`;
    await loadCompetitionReadiness();
  } catch (err) {
    if (status) status.textContent = "导出失败：" + err.message;
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
  const data = await api(`/api/self-evolution/runs/${id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console", reason: "console activation after shadow/canary review", confirmed: true }) });
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
  return `<button class="secondary" onclick="showTask(${id})">查看</button> ${terminal ? "" : `<button class="secondary icon-text" onclick="cancelTask(${id})"><span class="fluent-icon" aria-hidden="true">&#xE71A;</span>取消</button>`} <button class="secondary icon-text" onclick="retryTask(${id})"><span class="fluent-icon" aria-hidden="true">&#xE777;</span>重试</button>`;
}

async function loadTasks() {
  try {
    const data = await api("/api/tasks?session_id=" + encodeURIComponent(currentSession) + "&limit=20");
    const rows = data.tasks || [];
    renderWorkbenchTasks(rows);
    if (!lastTaskId && rows[0]) lastTaskId = rows[0].id;
    if ($("taskTable")) $("taskTable").innerHTML = table(["ID", "状态", "尝试", "标题", "来源", "开始", "操作"], rows.map(task => [task.id, { html: statusBadge(task.status) }, task.attempt || 1, task.title, task.source, task.started_at, { html: taskActions(task) }]));
    await loadTaskQueue();
    if (lastTaskId) await showTask(lastTaskId);
  } catch (err) {
    renderWorkbenchTasks([]);
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
      ["Skill 治理", { html: statusBadge("success") }, "Keyring/环境签名、依赖清单、独立进程 fresh audit、稳定分桶 canary"]
    ]);
    $("sceneBoundaryTable").innerHTML = table(["场景", "已交付", "仍需外部条件"], [
      ["会议", "音频登记、转写导入、说话人标签、会议纪要、ICS/EML 草稿", "真实 Whisper/说话人模型和自动发送连接器"],
      ["科研", "PDF 导入、OCR 需求检测、引用校验、对比矩阵、复现实验目录、论文学习解析文件", "本地 OCR 引擎和真实数据集运行"],
      ["办公", "XLSX 生成/单元格编辑、PPTX 生成/文本替换、产物记录", "复杂图表、母版设计和高级动画后续增强"],
      ["学习", "知识图谱、错题证据、长期掌握度", "更长周期学习样本"],
      ["Git", "补丁预览、审批提交、checkpoint、revert 回滚", "远程 PR/CI 连接器"],
      ["Skill", "签名、依赖、独立 fresh-agent audit、真实稳定分桶 canary", "高风险 Skill 仍禁止自动灰度"]
    ]);
  } catch (err) {}
}

function ensureProfessionalBoard() {
  const target = $("professionalBoardGrid");
  if (!target || target.dataset.ready === "1") return;
  target.dataset.ready = "1";
  const boardTitle = "专业场景工作流";
  const boards = [
    { index: "01", kind: "research", meta: "研究与证据", title: "科研工作流", summary: "从论文入库到可追溯结论，保留引用与复现实验依据。", tags: ["论文入库", "引用问答", "复现实验"], gate: "引用完整 · 复现可审计", action: "进入科研工作流" },
    { index: "02", kind: "learning", meta: "学习与掌握", title: "学习工作流", summary: "把课程资料转化为概念图谱、错题归因与长期复习计划。", tags: ["概念图谱", "错题归因", "间隔复习"], gate: "掌握度证据 · 复习闭环", action: "进入学习工作流" },
    { index: "03", kind: "code", meta: "开发与交付", title: "开发工作流", summary: "围绕仓库完成任务拆分、风险识别、测试与可接续交付。", tags: ["仓库扫描", "测试闭环", "交接记录"], gate: "测试通过 · 交接完整", action: "进入开发工作流" },
    { index: "04", kind: "office", meta: "办公与表达", title: "办公工作流", summary: "生成简报、表格、演示与会议纪要，并完成格式质量检查。", tags: ["数据分析", "演示文稿", "会议纪要"], gate: "格式有效 · 视觉验收", action: "进入办公工作流" }
  ];
  target.setAttribute("aria-label", boardTitle);
  target.innerHTML = boards.map(board => `<article class="board-card board-${board.kind}">
    <div class="board-card-top"><span class="board-index">${board.index}</span><span class="board-meta">${board.meta}</span></div>
    <h3>${board.title}</h3><p>${board.summary}</p>
    <div class="board-capabilities">${board.tags.map(tag => `<span>${tag}</span>`).join("")}</div>
    <div class="board-quality"><span>质量门</span><b>${board.gate}</b></div>
    <button class="board-action" onclick="activateScenarioBoard('${board.kind}')">${board.action}</button>
  </article>`).join("");
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
    lastKnowledgeGraph = { nodes: graph.nodes || [], edges: graph.edges || [], category: graph.category || "all" };
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
    if ($("knowledgeGraphExplorer")?.classList.contains("on")) renderKnowledgeGraphExplorer();
  } catch (err) {}
}

function openKnowledgeBackstage() {
  toggleCommandDrawer();
}

function openKnowledgeGraphExplorer() {
  const explorer = $("knowledgeGraphExplorer");
  if (!explorer) return;
  explorer.classList.add("on");
  explorer.setAttribute("aria-hidden", "false");
  document.body.classList.add("graph-explorer-open");
  renderKnowledgeGraphExplorer();
  if (!lastKnowledgeGraph.nodes.length) loadKnowledgeGraph();
  window.setTimeout(() => explorer.querySelector("button, input, select")?.focus(), 0);
}

function closeKnowledgeGraphExplorer() {
  const explorer = $("knowledgeGraphExplorer");
  if (!explorer) return;
  explorer.classList.remove("on");
  explorer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("graph-explorer-open");
}

function graphNodeColor(type) {
  return ({ category: "#315cf5", knowledge: "#17865d", document: "#e87524", tag: "#7659d6" }[type] || "#697386");
}

function graphTypeLabel(type) {
  return ({ category: "分类", knowledge: "知识", document: "文档", tag: "标签", source: "来源", concept: "概念" }[type] || "节点");
}

function graphRelationLabel(type) {
  return ({ contains: "包含", cites: "引用", tagged: "标签", links_to: "链接", backlink: "反向链接", sourced_from: "来源", mentions: "提及" }[type] || "关系");
}

function isPrivateKnowledgePath(value) {
  return /(?:^[a-z]:[\\/]|^\\\\|^\/(?:users|home|var|tmp)\/|file:\/\/)/i.test(String(value || "").trim());
}

function publicKnowledgeNodeLabel(node) {
  const raw = String(node?.label || node?.title || node?.id || "知识节点").trim();
  if (node?.type === "source" || isPrivateKnowledgePath(raw)) return "本地导入资料";
  return raw.slice(0, 28);
}

function publicKnowledgeNodeDescription(node) {
  const raw = String(node?.summary || node?.source || "该节点来自本地知识库，可沿关系继续探索。").trim();
  return isPrivateKnowledgePath(raw) ? "本地导入资料，路径信息已隐藏。" : raw;
}

function renderKnowledgeGraphExplorer() {
  const stage = $("graphExplorerNodes");
  const edgesTarget = $("graphExplorerEdges");
  if (!stage || !edgesTarget) return;
  const type = $("graphTypeFilter")?.value || "";
  const relation = $("graphRelationFilter")?.value || "";
  const query = ($("graphNodeQuery")?.value || "").trim().toLowerCase();
  const sourceNodes = lastKnowledgeGraph.nodes || [];
  const visibleNodes = sourceNodes.filter(node => (!type || node.type === type) && (!query || JSON.stringify(node).toLowerCase().includes(query))).slice(0, 56);
  const visibleIds = new Set(visibleNodes.map(node => String(node.id)));
  const visibleEdges = (lastKnowledgeGraph.edges || []).filter(edge => visibleIds.has(String(edge.source)) && visibleIds.has(String(edge.target)) && (!relation || edge.type === relation)).slice(0, 140);
  const centerX = 48;
  const centerY = 48;
  const positions = {};
  visibleNodes.forEach((node, index) => {
    const band = Math.floor(index / 14);
    const bandStart = band * 14;
    const bandSize = Math.min(14, visibleNodes.length - bandStart);
    const angle = ((index - bandStart) / Math.max(bandSize, 1)) * Math.PI * 2 - Math.PI / 2;
    const radiusX = 18 + band * 13;
    const radiusY = 15 + band * 11;
    positions[String(node.id)] = { left: centerX + Math.cos(angle) * radiusX, top: centerY + Math.sin(angle) * radiusY };
  });
  const edgeColor = edgeType => ({ contains: "#aeb7c5", cites: "#6f8cff", tagged: "#64b990", links_to: "#9a84e5", backlink: "#e36c78", sourced_from: "#e7a269", mentions: "#61aec2" }[edgeType] || "#c2c8d0");
  edgesTarget.innerHTML = visibleEdges.map(edge => {
    const from = positions[String(edge.source)];
    const to = positions[String(edge.target)];
    if (!from || !to) return "";
    return `<line x1="${from.left}%" y1="${from.top}%" x2="${to.left}%" y2="${to.top}%" stroke="${edgeColor(edge.type)}" stroke-width="1.35" opacity=".72"><title>${esc(edge.type || "relation")}</title></line>`;
  }).join("");
  stage.innerHTML = visibleNodes.map(node => {
    const pos = positions[String(node.id)] || { left: centerX, top: centerY };
    const label = publicKnowledgeNodeLabel(node).slice(0, 24);
    const nodeId = encodeURIComponent(String(node.id || ""));
    return `<button class="graph-node graph-node-${esc(node.type || "other")}" style="left:${pos.left}%;top:${pos.top}%;--node-color:${graphNodeColor(node.type)}" onclick="selectKnowledgeGraphNode('${nodeId}')" title="${esc(label)}"><span></span><b>${esc(label)}</b><small>${esc(graphTypeLabel(node.type))}</small></button>`;
  }).join("") || '<div class="graph-empty">没有匹配的节点，调整筛选条件后重试。</div>';
  if ($("graphExplorerStats")) $("graphExplorerStats").textContent = `${visibleNodes.length} 节点 · ${visibleEdges.length} 关系`;
  if ($("graphExplorerSummary")) $("graphExplorerSummary").textContent = `${knowledgeCategoryLabel(knowledgeCategory)} · ${sourceNodes.length} 个节点 · ${(lastKnowledgeGraph.edges || []).length} 条关系`;
}

function selectKnowledgeGraphNode(encodedId) {
  const id = decodeURIComponent(encodedId || "");
  const node = (lastKnowledgeGraph.nodes || []).find(item => String(item.id) === id);
  const inspector = $("graphInspector");
  if (!node || !inspector) return;
  const connected = (lastKnowledgeGraph.edges || []).filter(edge => String(edge.source) === id || String(edge.target) === id);
  const relationCounts = connected.reduce((acc, edge) => { acc[edge.type || "relation"] = (acc[edge.type || "relation"] || 0) + 1; return acc; }, {});
  inspector.innerHTML = `<span class="eyebrow">节点详情</span><div class="graph-inspector-type" style="--node-color:${graphNodeColor(node.type)}">${esc(graphTypeLabel(node.type))}</div><h3>${esc(publicKnowledgeNodeLabel(node))}</h3><p>${esc(publicKnowledgeNodeDescription(node))}</p><dl><div><dt>权重</dt><dd>${esc(node.weight || 1)}</dd></div><div><dt>相邻关系</dt><dd>${connected.length}</dd></div><div><dt>关系类型</dt><dd>${esc(Object.entries(relationCounts).map(([key, value]) => `${graphRelationLabel(key)} ${value}`).join(" · ") || "暂无")}</dd></div></dl><button class="primary" type="button" onclick="closeKnowledgeGraphExplorer()">返回知识库</button>`;
  document.querySelectorAll(".graph-node").forEach(button => button.classList.toggle("on", decodeURIComponent((button.getAttribute("onclick") || "").split("'")[1] || "") === id));
}

async function loadOcrQueue() {
  const target = $("ocrQueueTable");
  if (!target) return;
  try {
    const query = knowledgeCategory ? "?category=" + encodeURIComponent(knowledgeCategory) : "";
    const data = await api("/api/documents/ocr-queue" + query);
    target.innerHTML = table(["文档", "库", "页码", "原因", "操作"], (data.documents || []).map(item => [item.title || item.filename || "", knowledgeCategoryLabel(item.category), Array.isArray(item.ocr_pages) ? item.ocr_pages.join(", ") : "", item.ocr_reason || "low_extractable_text", { html: `<button class="secondary" onclick="openDocumentReview(${Number(item.id)})">对照原图复核</button> <button class="secondary" onclick="runDocumentOcr(${Number(item.id)})">重新 OCR</button>` }]));
  } catch (err) {
    target.innerHTML = table(["文档", "库", "页码", "原因", "操作"], []);
  }
}

async function openDocumentReview(id) {
  const dialog = document.createElement("dialog");
  dialog.style.cssText = "width:min(1000px,92vw);max-height:88vh;overflow:auto;padding:24px;border-radius:12px";
  document.body.appendChild(dialog);
  const close = document.createElement("button"); close.textContent = "关闭";
  close.onclick = () => dialog.close(); dialog.appendChild(close);
  const body = document.createElement("div"); dialog.appendChild(body);
  dialog.addEventListener("close", () => dialog.remove()); dialog.showModal();
  async function render() {
    body.replaceChildren();
    const status = document.createElement("p"); body.appendChild(status); status.textContent = "正在加载复核证据…";
    try {
      const data = await api(`/api/documents/${Number(id)}/review`);
      status.textContent = `${data.items.filter(item => item.state !== "rejected").length} 条待复核 · ${data.items.filter(item => item.state === "rejected").length} 条已拒绝 · ${data.history.length} 条历史记录。请核对整行和表头，尤其是数字、单位和否定词。`;
      const publish = document.createElement("button"); publish.textContent = "将已确认内容写入知识库";
      publish.onclick = async () => {
        if (!window.confirm("只发布已对照原图确认的内容；待复核或拒绝的内容不会发布。继续？")) return;
        publish.disabled = true;
        try {
          const result = await api(`/api/documents/${Number(id)}/review/publish`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({confirmed:true})});
          status.textContent = `已发布 ${result.count} 条已确认内容（重复操作不会重复入库）。`;
          await Promise.allSettled([loadKnowledge(), searchKnowledge()]);
        } catch (err) { status.textContent = err.message; }
        finally { publish.disabled = false; }
      };
      body.appendChild(publish);
      for (const item of data.items) {
        const section = document.createElement("section"); section.style.cssText = "border-top:1px solid #8885;margin-top:20px;padding-top:12px";
        const title = document.createElement("h3"); title.textContent = `第 ${item.cells[0]?.page || "?"} 页 · 证据 ${item.chunk_id} · ${item.state === "rejected" ? "已拒绝，可重新核对" : "待确认"}`;
        section.appendChild(title); const inputs = new Map(); let loaded = 0;
        for (const cell of item.cells) {
          const row = document.createElement("div"); row.style.cssText = "display:grid;grid-template-columns:minmax(160px,1fr) minmax(180px,1fr);gap:12px;margin:12px 0";
          const source = document.createElement("div");
          const label = document.createElement("p"); label.textContent = `第 ${cell.page} 页 · ${cell.is_header ? "表头" : cell.header || "正文"}`; source.appendChild(label);
          const img = document.createElement("img"); img.src = cell.crop_url; img.alt = "原始 PDF 单元格裁剪"; img.style.cssText = "max-width:100%;border:1px solid #8885";
          img.onload = () => { loaded += 1; }; img.onerror = () => { status.textContent = "原图加载失败，不能确认。请检查源文件后重试。"; };
          source.appendChild(img); row.appendChild(source);
          const editor = document.createElement("div");
          const input = document.createElement("textarea"); input.value = cell.text; input.rows = 3; input.style.width = "100%";
          input.setAttribute("aria-label", `确认值 ${cell.header || cell.id}`); inputs.set(cell.id, input); editor.appendChild(input);
          const candidates = document.createElement("p"); candidates.style.fontSize = "12px";
          candidates.textContent = (cell.verification?.candidates || []).map((v, index) => `识别视图 ${index + 1}：${v.status === "completed" ? v.text : "识别未完成"}`).join("；") || "没有第二识别视图；仍需对照原图。";
          editor.appendChild(candidates); row.appendChild(editor); section.appendChild(row);
        }
        const label = document.createElement("label"); const checked = document.createElement("input"); checked.type = "checkbox";
        label.append(checked, document.createTextNode(" 我已对照原图核对整行、表头、数字、单位和条件")); section.appendChild(label);
        for (const action of ["approve", "reject"]) {
          const button = document.createElement("button"); button.textContent = action === "approve" ? "保存确认值" : "拒绝使用此行";
          button.onclick = async () => {
            if (!checked.checked || loaded !== item.cells.length) { status.textContent = "请等待原图加载完成，并勾选核对确认。"; return; }
            button.disabled = true;
            try {
              await api(`/api/documents/${Number(id)}/review`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({chunk_id:item.chunk_id,revision:data.revision,values:Object.fromEntries([...inputs].map(([key,input])=>[key,input.value])),confirmed:true,action})});
              await render(); await loadOcrQueue();
            } catch (err) { status.textContent = `${err.message}；请关闭后重新加载复核窗口。`; button.disabled = false; }
          }; section.appendChild(button);
        }
        body.appendChild(section);
      }
    } catch (err) { status.textContent = err.message; }
  }
  await render();
}

async function runDocumentOcr(id) {
  const sidecar = window.prompt("重新 OCR 会重建提取结果，并使旧的复核确认失效。留空使用本地 OCR；仅无待复核证据时可粘贴替换文本。取消则不执行。", "");
  if (sidecar === null) return;
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

async function loadFeishuCenter() {
  if (!$("feishuMessagesTable")) return;
  // §13 resource endpoints: each is a dedicated URL, not an action router.
  const get = (path) => api(path).catch(err => ({ error: err.message }));
  try {
    const [health, messages, summaries, approvals, dispatches] = await Promise.all([
      get("/api/feishu/health"),
      get("/api/feishu/messages?limit=50"),
      get("/api/feishu/summaries?limit=50"),
      get("/api/feishu/approvals?limit=50"),
      get("/api/feishu/dispatches?limit=50"),
    ]);
    const cfg = (health && health.config) || {};
    const cli = (health && health.client) || {};
    // P1-2: disable outbound write buttons until the connector is configured.
    window.__feishuCfg = cfg;
    const feishuConfigured = !!cfg.configured;
    const caBtn = $("feishuCreateApprovalBtn");
    const sendBtn = $("feishuSendBtn");
    if (caBtn) caBtn.disabled = !feishuConfigured;
    if (sendBtn) sendBtn.disabled = !feishuConfigured;
    if ($("feishuHealth")) $("feishuHealth").innerHTML = table(["项", "值"], [
      ["事件模式(event_mode)", cfg.event_mode || "—"],
      ["实时发送(live)", { html: statusBadge(cfg.live ? "ok" : "pending") }],
      ["实时就绪(live_ready)", { html: statusBadge(cfg.live_ready ? "ok" : "pending") }],
      ["App 配置", cfg.configured ? "已配置" : "未配置(env)"],
      ["Client 连接", cli.connection || (health && health.has_client ? "已连接" : "无")],
      ["审批定义码", cfg.approval_code_present ? "已配置" : "—"],
      ["审批表单控件", cfg.approval_form_control_present ? "已配置" : "—"],
      ["发起人 open_id", cfg.approval_initiator_present ? "已配置" : "—"],
      ["允许聊天数", cfg.whitelist_chats ?? 0],
      ["允许目标数", cfg.whitelist_target_open_ids ?? 0],
      ["授权审批人数", cfg.approvers ?? 0],
      ["消息留存(天)", cfg.message_retention_days ?? "—"],
    ]);
    if ($("feishuMessagesTable")) $("feishuMessagesTable").innerHTML = (messages && messages.length) ? table(["聊天", "发送者", "类型", "内容", "接收时间", "状态"], (messages || []).map(m => [m.chat_id, m.sender_id, m.message_type, m.text, m.create_time, { html: statusBadge(m.processed_status) }])) : '<tr><td colspan="6" class="empty-state">暂无消息</td></tr>';
    if ($("feishuSummariesTable")) $("feishuSummariesTable").innerHTML = (summaries && summaries.length) ? table(["ID", "主题", "结论数", "行动项数", "来源消息", "状态", "创建时间"], (summaries || []).map(s => [s.id, s.topic, (s.conclusions || []).length, (s.action_items || []).length, (s.source_message_ids || []).join(","), { html: statusBadge(s.status) }, s.created_at])) : '<tr><td colspan="7" class="empty-state">暂无纪要</td></tr>';
    const preview = (approvals || [])[0];
    if ($("feishuPreview")) $("feishuPreview").textContent = preview ? (preview.body_text || "（空正文）") : "暂无待审批/待发送内容。";
    if ($("feishuApprovalsTable")) $("feishuApprovalsTable").innerHTML = (approvals && approvals.length) ? table(["ID", "目标", "状态", "审批人", "已用", "有效期", "创建时间"], (approvals || []).map(a => {
      const expired = a.expires_at_epoch && a.expires_at_epoch < Math.floor(Date.now() / 1000);
      return [a.id, (a.target_type || "") + ":" + (a.target_id || ""), { html: statusBadge(a.status) }, a.approver_id, { html: statusBadge(a.used ? "used" : "no") }, { html: statusBadge(expired ? "expired" : "valid") }, a.created_at_epoch ? new Date(a.created_at_epoch * 1000).toLocaleString() : ""];
    })) : '<tr><td colspan="7" class="empty-state">暂无审批</td></tr>';
    if ($("feishuDispatchesTable")) $("feishuDispatchesTable").innerHTML = (dispatches && dispatches.length) ? table(["ID", "审批ID", "目标", "状态", "尝试", "飞书消息ID", "API码", "API消息", "追踪ID"], (dispatches || []).map(d => [d.id, d.approval_id, (d.target_type || "") + ":" + (d.target_id || ""), { html: statusBadge(d.status) }, d.attempts, d.feishu_message_id, d.api_code, d.api_msg, d.trace_id])) : '<tr><td colspan="9" class="empty-state">暂无发送回执</td></tr>';
  } catch (err) {
    if ($("feishuHealth")) $("feishuHealth").innerHTML = table(["状态", "说明"], [["加载失败", err.message]]);
  }
}

async function feishuRequest(method, path, payload) {
  const statusEl = $("feishuActionStatus");
  if (statusEl) statusEl.textContent = "处理中…";
  try {
    const opts = { method };
    if (payload !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(payload);
    }
    const res = await api(path, opts);
    if (statusEl) statusEl.textContent = "成功：" + JSON.stringify(res).slice(0, 240);
    await loadFeishuCenter();
  } catch (err) {
    if (statusEl) statusEl.textContent = "失败：" + err.message;
  }
}

async function feishuCreateSummary() {
  const ids = ($("feishuMsgIds").value || "").split(",").map(s => s.trim()).filter(Boolean).map(Number);
  await feishuRequest("POST", "/api/feishu/summaries", { message_ids: ids });
}

async function feishuCreateApproval() {
  const targetType = ($("feishuTargetType").value || "chat").trim();
  const targetId = ($("feishuTargetId").value || "").trim();
  if (!targetId) { alert("请填写 target_id（须为白名单内的 chat_id 或 open_id）"); return; }
  // P1-2: 不再静默提交 confirmed:true；必须人类显式确认。审批人由飞书实例决定，不手填。
  const ok = confirm(
    `确认创建飞书出站审批？\n\n目标：${targetType}:${targetId}\n\n` +
    `创建后须经飞书原生审批通过才会对外发送；目标必须在白名单内，否则会被服务端拒绝（409）。`
  );
  if (!ok) return;
  await feishuRequest("POST", "/api/feishu/approvals", {
    confirmed: true,
    summary_id: Number($("feishuSummaryId").value),
    target_type: targetType,
    target_id: targetId,
  });
}

async function feishuSyncApproval() {
  const id = Number($("feishuApprovalId").value);
  await feishuRequest("POST", `/api/feishu/approvals/${id}/sync`);
}

async function feishuSendApproved() {
  const id = Number($("feishuApprovalId").value);
  if (!id) { alert("请填写 approval_id"); return; }
  // P1-2: 发送是真实对外动作，必须人类显式确认；at-most-once，超时记为结果未知且不自动重发。
  const ok = confirm(
    `确认向飞书发送已批准的审批 #${id}？\n\n` +
    `该操作只会执行一次（at-most-once）。若飞书 API 超时，结果将记为“未知”并保留本地回执，不会自动重发。`
  );
  if (!ok) return;
  await feishuRequest("POST", `/api/feishu/approvals/${id}/send`, { confirmed: true });
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
  if ($("skillReviewTable")) $("skillReviewTable").innerHTML = table(["技能", "状态", "操作"], skillReviews.map(item => [item.skill_name || item.name || "", item.status || "", { html: `<button class="secondary" onclick="signSkill(${Number(item.id)})">签名</button> <button class="secondary" onclick="auditSkill(${Number(item.id)})">独立审计</button> <button class="secondary" onclick="canarySkill(${Number(item.id)})">Canary</button> <button class="primary" onclick="promoteSkill(${Number(item.id)})">发布</button> <button class="secondary" onclick="reviewSkill('${esc(item.id || item.skill_name || "")}','needs_changes')">需修改</button>` }]));
}

async function signSkill(id) { await api(`/api/skills/evolution/versions/${id}/sign`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ signer: "console" }) }).catch(() => ({})); await renderSkillVersionTables(); }
async function auditSkill(id) { await api(`/api/skills/evolution/versions/${id}/fresh-audit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }).catch(() => ({})); await renderSkillVersionTables(); }
async function canarySkill(id) { await api(`/api/skills/evolution/versions/${id}/canary`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ percent: 10, actor: "console" }) }).catch(() => ({})); await renderSkillVersionTables(); }
async function promoteSkill(id) { await api(`/api/skills/evolution/versions/${id}/promote`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor: "console", confirmed: true }) }).catch(() => ({})); await renderSkillVersionTables(); }
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
  await Promise.allSettled([loadHealth(), loadDash(), loadRoutingStrategy(), loadKnowledge(), loadKnowledgeDocuments(), loadKnowledgeGraph(), loadOcrQueue(), loadMemory(), loadReflection(), loadEvolution(), loadCompetitionReadiness(), loadSkills(), loadTools(), loadToolExecutions(), loadTasks(), loadBenchmarks(), loadCapabilities(), loadSecurityCenter(), loadOps(), refreshOfflineReadiness(), loadLocalAcceptanceHistory()]);
  if (window.loadRuntimeRecords) window.loadRuntimeRecords();
}

async function refreshView(viewName) {
  const common = [loadHealth(), loadRoutingStrategy()];
  const viewLoads = {
    chat: [loadTasks()],
    search: [],
    knowledge: [loadKnowledge(), loadKnowledgeDocuments(), loadKnowledgeGraph(), loadOcrQueue()],
    projects: [loadKnowledgeDocuments()],
    dash: [loadDash(), refreshOfflineReadiness(), loadLocalAcceptanceHistory()],
    memory: [loadMemory()],
    reflection: [loadReflection()],
    evolution: [loadEvolution(), loadCompetitionReadiness()],
    skills: [loadSkills()],
    tools: [loadTools(), loadToolExecutions()],
    tasks: [loadTasks()],
    benchmarks: [loadBenchmarks()],
    scenes: [loadCapabilities()],
    security: [loadSecurityCenter()],
    feishu: [loadFeishuCenter()],
    ops: [loadOps()]
  };
  await Promise.allSettled(common.concat(viewLoads[viewName] || []));
  if (["chat", "tasks"].includes(viewName) && window.loadRuntimeRecords) window.loadRuntimeRecords();
}

let embeddedOfficeInstance = null;
function loadOfficeEditorScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script"); script.src = url; script.onload = resolve; script.onerror = reject; document.head.appendChild(script);
  });
}
async function openEmbeddedOfficeEditor(artifactId) {
  const modal = $("officeEditorModal"), mount = $("office-editor-mount"), status = $("officeEditorStatus");
  modal?.classList.add("on"); modal?.setAttribute("aria-hidden", "false");
  if (mount) mount.innerHTML = ""; if (status) status.textContent = "正在建立安全编辑会话…";
  try {
    const caps = await fetch("/api/office/editor/capabilities").then(r => r.json());
    const provider = ["onlyoffice", "wps", "collabora"].find(name => caps.configured?.includes(name));
    if (!provider) throw new Error("尚未配置 WPS、ONLYOFFICE 或 Collabora 编辑服务");
    const response = await fetch("/api/office/editor/session", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({artifact_id:artifactId,provider,mode:"edit"})});
    const session = await response.json(); if (!response.ok) throw new Error(session.detail || "编辑会话创建失败");
    const config = session.mount; if (status) status.textContent = `${provider} · 会话将在 15 分钟后过期`;
    if (config.type === "onlyoffice-docsapi") {
      if (!window.DocsAPI) await loadOfficeEditorScript(config.script_url);
      embeddedOfficeInstance = new window.DocsAPI.DocEditor("office-editor-mount", config.config);
    } else if (config.type === "wps-jssdk") {
      if (!window.WebOfficeSDK) await loadOfficeEditorScript(config.sdk_url);
      embeddedOfficeInstance = window.WebOfficeSDK.init(config.config);
    } else {
      mount.innerHTML = `<iframe title="Office editor" src="${esc(config.iframe_url)}" allow="clipboard-read; clipboard-write"></iframe>`;
    }
  } catch (error) { if (status) status.textContent = error.message || String(error); }
}
function closeEmbeddedOfficeEditor() {
  try { embeddedOfficeInstance?.destroy?.(); } catch (_) {}
  embeddedOfficeInstance = null; $("office-editor-mount")?.replaceChildren();
  $("officeEditorModal")?.classList.remove("on"); $("officeEditorModal")?.setAttribute("aria-hidden", "true");
}

if ($("cfgProvider")) $("cfgProvider").addEventListener("change", () => applyProviderPreset(true));
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if ($("knowledgeOrganizer")?.classList.contains("on")) closeKnowledgeOrganizer();
  else if ($("knowledgeGraphExplorer")?.classList.contains("on")) closeKnowledgeGraphExplorer();
  else if ($("chatProgressPanel")?.classList.contains("on")) toggleChatProgress(false);
  else if ($("modelSettings")?.classList.contains("on")) closeModelSettings();
  else if ($("commandDrawer")?.classList.contains("on")) closeCommandDrawer();
  else if ($("officeEditorModal")?.classList.contains("on")) closeEmbeddedOfficeEditor();
});
applyReportPreset();
renderKnowledgeWorkspaceShell();
setAutonomyMode(localStorage.getItem("clawos-autonomy-mode") || "approve");
loadSessions();
startTaskStream();
const initialView = (location.hash || "").replace("#", "");
setView(initialView);
setInterval(loadHealth, 30000);
setInterval(() => {
  if (!taskStream) loadTasks();
}, 5000);
