// chat behavior for the ClawOS workbench.
import { $, API, api, consoleState, enhanceMarkdown, esc, formatArtifactBytes, md } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   renderLastTools: typeof import('./evolution.js').renderLastTools,
 *   renderLastReflection: typeof import('./evolution.js').renderLastReflection,
 *   refreshAll: typeof import('./shell.js').refreshAll,
 *   setView: typeof import('./shell.js').setView,
 *   startTaskStream: typeof import('./tasks.js').startTaskStream,
 *   renderKnowledgeSessionSelect: typeof import('./knowledge.js').renderKnowledgeSessionSelect,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export function addMessage(role, text, tools) {
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

export function addAssistantStream() {
  const inner = $("chatInner");
  if (inner.querySelector(".empty")) inner.innerHTML = "";
  const div = document.createElement("div");
  div.className = "msg agent";
  div.innerHTML = '<div class="message-body"><div class="mc" aria-live="polite"></div><p class="chat-response-state">正在生成…</p></div>';
  inner.appendChild(div);
  const target = div.querySelector(".mc");
  const status = div.querySelector(".chat-response-state");
  const update = text => {
    const chat = $("chat");
    const follow = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 100;
    target.innerHTML = md(text);
    enhanceMarkdown(target);
    status.hidden = true;
    if (follow) chat.scrollTop = chat.scrollHeight;
  };
  update.note = text => { status.textContent = text; status.hidden = false; };
  return update;
}

export function appendArtifactsToLastAssistant(artifacts) {
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

export function appendCodingEvidenceToLastAssistant(toolCalls) {
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

export function attachFeedbackControls(taskId) {
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

export async function submitTaskFeedback(taskId, feedback, toolbar) {
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

export function sendMessage() {
  const prompt = $("prompt");
  let text = prompt.value.trim();
  const ready = consoleState.chat.chatAttachments.filter(item => item.status === "ready");
  if ((!text && !ready.length) || consoleState.chat.busy) return;
  prompt.value = "";
  const wantsWebSearch = Boolean($("webSearchToggle")?.checked);
  const attachments = ready.map(item => ({
    name: item.name,
    type: item.type,
    size: item.size,
    document_id: item.document_id,
    chunk_count: item.chunk_count
  }));
  consoleState.chat.chatAttachments = consoleState.chat.chatAttachments.filter(item => item.status === "uploading");
  renderAttachmentTray();
  submitMessage(text || "请阅读附件并给出分析。", wantsWebSearch ? ["web_search", "web_fetch"] : [], attachments, wantsWebSearch ? "auto" : "off");
}

export async function readChatStream(response, onText, onMeta) {
  return window.ClawChatContent.readStream(response, onText, onMeta);
}

export async function submitMessage(text, confirmedTools, attachments, webSearchMode = "off") {
  consoleState.chat.busy = true;
  consoleState.chat.lastTaskId = null;
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
        session_id: consoleState.chat.currentSession,
        stream: true,
        clawos_confirmed_tools: confirmedTools || [],
        clawos_web_search_mode: webSearchMode,
        clawos_attachments: attachments || [],
        messages: [{ role: "user", content: text }]
      })
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === "string" ? error.detail : `请求失败 (${response.status})`);
    }
    const contentType = response.headers.get("content-type") || "";
    let data = null;
    let streamMeta = {};
    if (contentType.includes("text/event-stream")) {
      const result = await readChatStream(response, update, meta => {
        streamMeta = meta;
        if (meta.task_id) consoleState.chat.lastTaskId = meta.task_id;
      });
      data = { clawos: streamMeta, choices: [{ message: { content: result.text } }] };
    } else {
      data = await response.json();
      update(data.choices?.[0]?.message?.content || "");
    }
    const tools = data.clawos?.tool_calls || [];
    consoleState.chat.lastToolCalls = tools;
    consoleState.tasks.lastRoutingStrategy = data.clawos?.routing_strategy || null;
    consoleState.chat.lastTaskId = data.clawos?.task_id || consoleState.chat.lastTaskId;
    if (consoleState.chat.lastTaskId) attachFeedbackControls(consoleState.chat.lastTaskId);
    if (data.clawos?.needs_confirmation) {
      const toolNames = [...new Set((data.clawos?.confirmation_tools || tools.map(t => t.name)).filter(Boolean))];
      const risks = [...new Set(tools.map(t => t.result?.risk_level).filter(Boolean))];
      consoleState.chat.pendingConfirmation = { text, tools: toolNames, attachments: attachments || [], webSearchMode };
      const webOnly = toolNames.length && toolNames.every(name => ["web_search", "web_fetch", "scholarly_search", "scholarly_download"].includes(name));
      $("confirmText").textContent = webOnly
        ? `允许联网读取 ${toolNames.length} 类公开来源？确认后会自动继续。${risks.length ? ` 风险级别：${risks.join("/")}` : ""}`
        : `允许执行 ${toolNames.join("、") || "本地变更"}？确认后将写入文件、运行测试或生成产物。${risks.length ? ` 风险级别：${risks.join("/")}` : ""}`;
      $("confirmBar").classList.add("on");
    } else {
      consoleState.chat.pendingConfirmation = null;
      $("confirmBar").classList.remove("on");
    }
    appendArtifactsToLastAssistant(data.clawos?.artifacts || []);
    appendCodingEvidenceToLastAssistant(data.clawos?.tool_calls || []);
    featureActions.renderLastTools();
    if (data.clawos?.reflection) featureActions.renderLastReflection(data.clawos.reflection);
    await loadSessions();
    await featureActions.refreshAll();
  } catch (err) {
    update.note(err.name === "AbortError" ? "已停止生成，已收到的内容保留。" : "请求失败：" + err.message);
  } finally {
    consoleState.chat.busy = false;
    window.activeChatController = null;
    $("send").disabled = false;
    if ($("stop")) $("stop").disabled = true;
    $("prompt").focus();
  }
}

export async function stopGeneration() {
  if (window.activeChatController) window.activeChatController.abort();
  if (consoleState.chat.lastTaskId) {
    try {
      await api(`/api/tasks/${consoleState.chat.lastTaskId}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "console stop generation", actor_id: "console" })
      });
    } catch (err) {}
  }
}

export function confirmPending() {
  if (!consoleState.chat.pendingConfirmation || consoleState.chat.busy) return;
  const pending = consoleState.chat.pendingConfirmation;
  consoleState.chat.pendingConfirmation = null;
  $("confirmBar").classList.remove("on");
  submitMessage(pending.text, pending.tools, pending.attachments || [], pending.webSearchMode || "off");
}

export function cancelPending() {
  consoleState.chat.pendingConfirmation = null;
  $("confirmBar").classList.remove("on");
}

export function emptyConversation() {
  return `<div class="empty workbench-empty task-empty"><b>开始一个新任务</b><span>描述你的目标，或选择一个常用任务。</span><div class="workbench-quick" aria-label="常用任务">${["编写与开发","会议纪要","数据分析","论文精读"].map(kind=>`<button type="button" onclick="useWorkbenchPrompt('${kind}')"><b>${kind}</b><span>${({"编写与开发":"分析项目、修改代码、运行测试","会议纪要":"整理决策和后续行动","数据分析":"清洗数据、统计和生成图表","论文精读":"阅读原文、核对证据、撰写报告"})[kind]}</span></button>`).join("")}</div></div>`;
}

export function newChat() {
  if (consoleState.chat.busy) return;
  consoleState.chat.historyRequest++;
  consoleState.chat.historyPage = null;
  consoleState.chat.currentSession = "s_" + Date.now();
  try { localStorage.setItem('clawos-last-session', consoleState.chat.currentSession); } catch (_) {}
  $("chatInner").innerHTML = emptyConversation();
  loadSessions();
  featureActions.setView("chat");
}

export async function switchSession(id) {
  if (consoleState.chat.busy) return;
  const request = ++consoleState.chat.historyRequest;
  try {
    const data = await api("/api/history/" + encodeURIComponent(id));
    if (request !== consoleState.chat.historyRequest || consoleState.chat.busy) return;
    consoleState.chat.currentSession = id;
    try { localStorage.setItem('clawos-last-session', id); } catch (_) {}
    featureActions.startTaskStream();
    consoleState.chat.historyPage = data;
    $("chatInner").innerHTML = data.messages?.length ? "" : emptyConversation();
    (data.messages || []).forEach(message => addMessage(message.role, message.content));
    renderHistoryControls();
    renderSessions(window._sessions || []);
    featureActions.setView("chat");
  } catch (err) {
    if (request === consoleState.chat.historyRequest) alert('历史记录加载失败：' + err.message);
  }
}

export function renderHistoryControls() {
  $('historyControls')?.remove();
  const controls = document.createElement('div');
  controls.id = 'historyControls';
  controls.className = 'history-controls';
  const visible = $('chatInner').querySelectorAll('.msg').length;
  if (!visible) return;
  controls.innerHTML = `<span role="status">已显示 ${visible} / ${Math.max(visible,Number(consoleState.chat.historyPage?.total || visible))} 条记录</span>
    <button type="button" class="secondary" id="historyOlder" ${!consoleState.chat.historyPage?.has_more || visible >= 1000 ? 'hidden' : ''}>加载更早记录</button>
    <a href="/api/history/${encodeURIComponent(consoleState.chat.currentSession)}/export?format=markdown" download>导出 Markdown</a>
    <a href="/api/history/${encodeURIComponent(consoleState.chat.currentSession)}/export?format=json" download>导出 JSON</a>
    ${visible >= 1000 ? '<small>页面最多显示 1000 条，完整记录可导出。</small>' : ''}`;
  $('chatInner').prepend(controls);
  $('historyOlder').onclick = loadOlderHistory;
}

export async function loadOlderHistory() {
  if (consoleState.chat.busy || !consoleState.chat.historyPage?.has_more) return;
  const id = consoleState.chat.currentSession, request = consoleState.chat.historyRequest, button = $('historyOlder');
  button.disabled = true;
  try {
    const data = await api(`/api/history/${encodeURIComponent(id)}?before_id=${consoleState.chat.historyPage.next_before_id}`);
    if (id !== consoleState.chat.currentSession || request !== consoleState.chat.historyRequest || consoleState.chat.busy) return;
    const container = $('chatInner'), first = container.querySelector('.msg');
    const height = $('chat').scrollHeight, top = $('chat').scrollTop;
    const fragment = document.createDocumentFragment();
    for (const message of data.messages || []) {
      addMessage(message.role, message.content);
      fragment.append(container.lastElementChild);
    }
    container.insertBefore(fragment, first);
    consoleState.chat.historyPage = data;
    renderHistoryControls();
    $('chat').scrollTop = top + $('chat').scrollHeight - height;
    $('historyOlder')?.focus();
  } catch (err) { if (id === consoleState.chat.currentSession) alert('更早记录加载失败：' + err.message); }
  finally { if (button.isConnected) button.disabled = false; }
}

export async function loadSessions() {
  try {
    const data = await api("/api/sessions");
    window._sessions = data.sessions || [];
    renderSessions(window._sessions);
    renderSessionSearch();
    featureActions.renderKnowledgeSessionSelect();
  } catch (err) {}
}

export function cleanSessionTitle(raw) {
  const text = String(raw || "").trim();
  if (!text) return "未命名会话";
  if (/^[?？\uFFFD\s]+$/.test(text)) return "未命名会话";
  if ((text.match(/[?？\uFFFD]/g) || []).length >= Math.max(6, Math.floor(text.length * 0.6))) return "未命名会话";
  return text;
}

export function sessionTitle(session) {
  return cleanSessionTitle(session.title || session.topic || session.last_message || session.session_id);
}

export function sessionTags(session) {
  return (session.tags || []).slice(0, 4).map(tag => `<em>${esc(tag)}</em>`).join("");
}

export function sessionSummary(session) {
  const title = sessionTitle(session);
  const raw = cleanSessionTitle(session.last_message || session.topic || "");
  if (!raw || raw === "未命名会话" || raw === title) return "继续查看这段对话的上下文与结果";
  return raw.replace(/\s+/g, " ").slice(0, 88);
}

export function renderSessions(list) {
  const rows = list || [];
  $("sessions").innerHTML = rows.map(session => `<button type="button" class="session ${session.session_id === consoleState.chat.currentSession ? "on" : ""}" data-session="${esc(session.session_id)}"><b>${esc(sessionTitle(session).slice(0, 54))}</b>${session.tags?.length ? `<span class="session-tags">${sessionTags(session)}</span>` : ""}</button>`).join("") || '<div class="session">暂无会话</div>';
  $('sessions').onclick = event => { const item = event.target.closest('[data-session]'); if (item) switchSession(item.dataset.session); };
}

export function renderSessionSearch() {
  const target = $("sessionSearchList");
  if (!target) return;
  const query = ($("sessionQuery")?.value || "").toLowerCase();
  const rows = consoleState.chat.sessionSearchRows?.query === query.trim() && query.trim() ? consoleState.chat.sessionSearchRows.rows : (window._sessions || []).filter(session => {
    const haystack = [session.title, session.topic, session.last_message, session.session_id, ...(session.tags || [])].join(" ").toLowerCase();
    return !query || haystack.includes(query);
  });
  target.innerHTML = rows.map(session => `<button type="button" class="session-result" data-session="${esc(session.session_id)}">
    <span class="session-result-copy"><b>${esc(sessionTitle(session).slice(0, 96))}</b><small>${esc(sessionSummary(session))}</small></span>
    <time>${esc(session.updated_at || session.session_id)}</time>
    <span class="session-continue">继续</span>
  </button>`).join("") || '<div class="empty-state">暂无匹配会话</div>';
  target.onclick = event => { const item = event.target.closest('[data-session]'); if (item) switchSession(item.dataset.session); };
}

export function searchSessionHistory() {
  clearTimeout(consoleState.chat.sessionSearchTimer);
  const request = ++consoleState.chat.sessionSearchRequest, query = $('sessionQuery').value.trim();
  consoleState.chat.sessionSearchTimer = setTimeout(async () => {
    try {
      const data = await api('/api/sessions?q=' + encodeURIComponent(query));
      if (request !== consoleState.chat.sessionSearchRequest) return;
      consoleState.chat.sessionSearchRows = {query:query.toLowerCase(), rows:data.sessions || []};
      renderSessionSearch();
    } catch (err) { if (request === consoleState.chat.sessionSearchRequest) $('sessionSearchList').textContent = '搜索失败：' + err.message; }
  }, 250);
}

export function chooseLocalFile() {
  $("filePicker")?.click();
}

export function renderAttachmentTray() {
  const tray = $("attachmentTray");
  if (!tray) return;
  tray.classList.toggle("on", consoleState.chat.chatAttachments.length > 0);
  tray.innerHTML = consoleState.chat.chatAttachments.map(item => {
    const loading = item.status === "loading";
    const label = loading ? "上传解析中" : item.status === "error" ? "解析失败" : `${item.chunk_count || 0} chunks`;
    return `<div class="attachment-chip ${loading ? "loading" : ""} ${item.status === "error" ? "error" : ""}"><span class="attachment-spinner"></span><b>${esc(item.name)}</b><small>${esc(label)}</small><button type="button" onclick="removeAttachment('${esc(item.id)}')" title="移除附件"><span aria-hidden="true">×</span></button></div>`;
  }).join("");
}

export function removeAttachment(id) {
  consoleState.chat.chatAttachments = consoleState.chat.chatAttachments.filter(item => item.id !== id);
  renderAttachmentTray();
}

export async function uploadDocuments(files, category) {
  const form = new FormData();
  files.forEach(file => form.append("files", file));
  form.append("category", category || "domain");
  const response = await fetch(API + "/api/documents/upload", { method: "POST", body: form });
  if (!response.ok) throw new Error("upload " + response.status);
  return await response.json();
}

export async function handlePickedFiles(event) {
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
  consoleState.chat.chatAttachments = [...consoleState.chat.chatAttachments, ...pending];
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
