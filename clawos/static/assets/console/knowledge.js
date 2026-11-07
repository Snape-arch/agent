// knowledge behavior for the ClawOS workbench.
import { $, KNOWLEDGE_MODES, api, consoleState, esc, md, statusBadge, table, usePrompt } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   sessionTitle: typeof import('./chat.js').sessionTitle,
 *   uploadDocuments: typeof import('./chat.js').uploadDocuments,
 *   setView: typeof import('./shell.js').setView,
 *   toggleCommandDrawer: typeof import('./shell.js').toggleCommandDrawer,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export function setMemoryType(type) {
  if ($("memType")) $("memType").value = type;
  document.querySelectorAll(".library-tabs button[data-mem]").forEach(button => {
    button.classList.toggle("on", button.dataset.mem === type);
  });
}

export function setKnowledgeCategory(category) {
  consoleState.knowledge.knowledgeCategory = category || "";
  if ($("knowledgeCategory")) $("knowledgeCategory").value = category || "domain";
  document.querySelectorAll(".library-tabs button[data-knowledge]").forEach(button => {
    button.classList.toggle("on", (button.dataset.knowledge === "all" && !consoleState.knowledge.knowledgeCategory) || button.dataset.knowledge === consoleState.knowledge.knowledgeCategory);
  });
  renderKnowledgeWorkspaceShell();
  loadKnowledge();
  loadKnowledgeDocuments();
  loadOcrQueue();
  loadKnowledgeGraph();
}

export function knowledgeCategoryLabel(category) {
  return ({ research: "科研库", learning: "学习库", writing: "写作库", project: "项目库", domain: "通用库" }[category || ""] || "全部知识库");
}

export function renderKnowledgeWorkspaceShell() {
  const mode = consoleState.knowledge.knowledgeCategory || "all";
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

export function toggleKnowledgeAdminTools() {
  const workspace = document.querySelector("#view-knowledge .knowledge-workspace");
  const expanded = workspace ? workspace.classList.toggle("show-knowledge-admin") : false;
  if ($("knowledgeAdminState")) $("knowledgeAdminState").textContent = expanded ? "已展开" : "已收起";
  if ($("knowledgeBackendState")) $("knowledgeBackendState").textContent = expanded ? "展开" : "收起";
  if ($("knowledgeAdminToggle")) $("knowledgeAdminToggle").textContent = expanded ? "收起后台" : "打开后台";
}

export function updateKnowledgeFrontstageStats() {
  const mode = consoleState.knowledge.knowledgeCategory || "all";
  const config = KNOWLEDGE_MODES[mode] || KNOWLEDGE_MODES.all;
  const items = consoleState.knowledge.knowledgeItems || [];
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

export function renderKnowledgeSessionSelect() {
  const select = $("knowledgeSessionSelect");
  if (!select) return;
  const sessions = window._sessions || [];
  select.innerHTML = sessions.map(session => `<option value="${esc(session.session_id)}">${esc(featureActions.sessionTitle(session).slice(0, 48))}</option>`).join("") || '<option value="">暂无历史会话</option>';
}

export async function loadKnowledge() {
  const target = $("knowledgeTable");
  if (!target) return;
  try {
    const query = consoleState.knowledge.knowledgeCategory ? "?category=" + encodeURIComponent(consoleState.knowledge.knowledgeCategory) : "";
    const data = await api("/api/knowledge" + query);
    consoleState.knowledge.knowledgeItems = data.items || [];
    updateKnowledgeFrontstageStats();
    if ($("knowledgeTableHeading")) $("knowledgeTableHeading").textContent = "最近资料";
    if ($("knowledgeResultCount")) $("knowledgeResultCount").textContent = `${consoleState.knowledge.knowledgeItems.length} 条`;
    target.innerHTML = table(["标题", "知识库", "操作"], consoleState.knowledge.knowledgeItems.map(item => [
      item.title,
      knowledgeCategoryLabel(item.category),
      { html: `<button class="secondary" onclick="loadKnowledgeItem(${Number(item.id)})">打开</button> <button class="secondary" onclick="appendKnowledgeToPrompt(${Number(item.id)})">提问</button>` }
    ]));
    renderKnowledgeMap(consoleState.knowledge.knowledgeItems);
    loadKnowledgeGovernance();
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `${knowledgeCategoryLabel(consoleState.knowledge.knowledgeCategory)} · ${consoleState.knowledge.knowledgeItems.length} 条资料`;
  } catch (err) {
    target.innerHTML = table(["标题", "知识库", "操作"], []);
    renderKnowledgeMap([]);
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "知识库加载失败：" + err.message;
  }
}

export async function loadKnowledgeGovernance() {
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

export async function reviewMemoryCandidate(id, decision) {
  if (!window.confirm(decision === "approve" ? "确认批准该长期记忆候选？批准后仍需单独晋升。" : "确认拒绝该长期记忆候选？")) return;
  await api(`/api/memory/candidates/${id}/review`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reviewer: "console-user", confirmed: true })
  });
  await loadKnowledgeGovernance();
}

export async function promoteMemoryCandidate(id) {
  if (!window.confirm("确认把已批准候选写入长期记忆？该操作会保留来源与审核记录。")) return;
  await api(`/api/memory/candidates/${id}/promote`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ actor_id: "console-user", confirmed: true })
  });
  await loadKnowledgeGovernance();
}

export function openKnowledgeGovernance() {
  const panel = $("knowledgeGovernance");
  if (!panel) return;
  panel.classList.add("on");
  panel.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  loadKnowledgeGovernance();
}

export function closeKnowledgeGovernance() {
  const panel = $("knowledgeGovernance");
  if (!panel) return;
  panel.classList.remove("on");
  panel.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
}

export async function resolveKnowledgeConflict(id, decision) {
  await api(`/api/knowledge/v2/conflicts/${id}/resolve`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, reviewer: "console-user", reason: "Reviewed in knowledge governance" })
  });
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = "冲突已审核，检索状态已更新。";
  await loadKnowledgeGovernance();
}

export async function backfillKnowledgeV2() {
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = "正在增量迁移历史知识…";
  const result = await api("/api/knowledge/v2/backfill", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ limit: 10000 })
  });
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = `迁移 ${result.migrated || 0} 条，失败 ${result.failed || 0} 条。`;
  await loadKnowledgeGovernance();
}

export async function rebuildKnowledgeIndex() {
  if (!window.confirm("确认重建知识向量索引？知识原文不会删除，但重建期间语义检索可能短暂不可用。")) return;
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = "正在重建向量索引…";
  const result = await api("/api/knowledge/v2/index/rebuild", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed: true })
  });
  if ($("knowledgeGovernanceStatus")) $("knowledgeGovernanceStatus").textContent = result.consistent ? "索引重建完成且一致。" : "索引重建完成，但仍有待同步项目。";
  await loadKnowledgeGovernance();
}

export function renderKnowledgeMap(items) {
  const map = $("knowledgeMap");
  if (!map) return;
  const rows = (items || []).slice(0, 12);
  map.innerHTML = rows.map((item, index) => `<button class="map-node ${index === 0 ? "core" : ""}" style="left:${12 + (index % 4) * 25}%;top:${14 + Math.floor(index / 4) * 26}%"><b>${esc(String(item.title || "知识").slice(0, 18))}</b><span>${esc(knowledgeCategoryLabel(item.category))}</span></button>`).join("") || '<div class="empty-state">暂无知识节点</div>';
}

export async function loadKnowledgeItem(id) {
  const item = consoleState.knowledge.knowledgeItems.find(row => Number(row.id) === Number(id));
  if (!item) return;
  openKnowledgeOrganizer();
  consoleState.knowledge.editingKnowledgeId = id;
  $("knowledgeTitle").value = item.title || "";
  $("knowledgeContent").value = item.content || "";
  $("knowledgeSource").value = item.source || "";
  $("knowledgeCategory").value = item.category || "domain";
  $("knowledgeStatus").textContent = "正在编辑知识条目";
}

export function clearKnowledgeEditor() {
  consoleState.knowledge.editingKnowledgeId = null;
  ["knowledgeTitle", "knowledgeContent", "knowledgeSource"].forEach(id => {
    if ($(id)) $(id).value = "";
  });
  if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "等待导入或编辑";
}

export function inferKnowledgeTags(text) {
  const lower = String(text || "").toLowerCase();
  const tags = [];
  if (lower.includes("paper") || lower.includes("论文")) tags.push("paper");
  if (lower.includes("report") || lower.includes("报告")) tags.push("report");
  if (lower.includes("agent")) tags.push("agent");
  return tags.length ? tags : ["manual"];
}

export async function saveKnowledge() {
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
  const path = consoleState.knowledge.editingKnowledgeId ? `/api/knowledge/${consoleState.knowledge.editingKnowledgeId}` : "/api/knowledge";
  await api(path, {
    method: consoleState.knowledge.editingKnowledgeId ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  clearKnowledgeEditor();
  consoleState.knowledge.knowledgeCategory = body.category === "domain" ? "" : body.category;
  closeKnowledgeOrganizer();
  await loadKnowledge();
}

export async function searchKnowledge() {
  const target = $("knowledgeTable");
  if (!target) return;
  const query = $("knowledgeQuery").value.trim();
  if (!query) {
    $("knowledgeQuery")?.focus();
    return;
  }
  const category = consoleState.knowledge.knowledgeCategory ? "&category=" + encodeURIComponent(consoleState.knowledge.knowledgeCategory) : "";
  const data = await api("/api/knowledge/search?q=" + encodeURIComponent(query) + category + "&limit=12");
  const results = data.items || [];
  consoleState.knowledge.knowledgeItems = [...new Map([...consoleState.knowledge.knowledgeItems, ...results].map(item => [Number(item.id), item])).values()];
  if ($("knowledgeTableHeading")) $("knowledgeTableHeading").textContent = "检索结果";
  if ($("knowledgeResultCount")) $("knowledgeResultCount").textContent = `${results.length} 条`;
  target.innerHTML = table(["标题", "知识库", "操作"], results.map(item => [
    item.title,
    knowledgeCategoryLabel(item.category),
    { html: `<button class="secondary" onclick="loadKnowledgeItem(${Number(item.id)})">打开</button> <button class="secondary" onclick="appendKnowledgeToPrompt(${Number(item.id)})">提问</button>` }
  ]));
}

export function clearKnowledgeSearch() {
  if ($("knowledgeQuery")) $("knowledgeQuery").value = "";
  loadKnowledge();
}

export function focusKnowledgeSearch() {
  $("knowledgeQuery")?.focus();
}

export function openKnowledgeOrganizer() {
  const organizer = $("knowledgeOrganizer");
  if (!organizer) return;
  consoleState.knowledge.knowledgeOrganizerReturnFocus = document.activeElement;
  organizer.classList.add("on");
  organizer.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  window.setTimeout(() => $("knowledgeTitle")?.focus(), 0);
}

export function closeKnowledgeOrganizer() {
  const organizer = $("knowledgeOrganizer");
  if (!organizer) return;
  organizer.classList.remove("on");
  organizer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
  if (consoleState.knowledge.knowledgeOrganizerReturnFocus?.focus) consoleState.knowledge.knowledgeOrganizerReturnFocus.focus();
}

export async function handleKnowledgeFiles(event) {
  const files = [...(event.target.files || [])];
  if (!files.length) return;
  const category = $("knowledgeCategory")?.value || consoleState.knowledge.knowledgeCategory || "domain";
  if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `正在上传并解析 ${files.length} 个文件`;
  try {
    const data = await featureActions.uploadDocuments(files.slice(0, 12), category);
    const docs = data.documents || [];
    const errors = data.errors || [];
    const pdfDocs = docs.filter(doc => String(doc.status || "") === "ready" && String(doc.filename || doc.file_path || "").toLowerCase().endsWith(".pdf"));
    const chunks = docs.reduce((count, doc) => count + Number(doc.chunk_count || 0), 0);
    const next = pdfDocs.length ? "，已自动选中 PDF，可选择报告样式并点击生成报告。" : "。如需生成报告，请上传可读取的 PDF 资料。";
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `已解析 ${docs.length} 个文件，生成 ${chunks} 个分块${errors.length ? `，${errors.length} 个失败` : ""}${next}`;
    consoleState.knowledge.knowledgeCategory = category === "domain" ? "" : category;
    await loadKnowledge();
    await loadKnowledgeDocuments(pdfDocs[0]?.id);
    if (pdfDocs.length && $("reportResult")) $("reportResult").textContent = "已自动选中 PDF，选择样式后点击生成报告。";
    await searchKnowledge();
  } catch (err) {
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "文件解析失败：" + err.message;
  }
  event.target.value = "";
}

export async function draftKnowledgeFromSelectedSession() {
  openKnowledgeOrganizer();
  const sid = $("knowledgeSessionSelect")?.value;
  if (!sid) {
    $("knowledgeStatus").textContent = "请先选择一个历史会话";
    return;
  }
  const data = await api("/api/history/" + encodeURIComponent(sid) + "?limit=24");
  const session = (window._sessions || []).find(item => item.session_id === sid) || {};
  const lines = (data.messages || []).map(message => `${message.role === "assistant" ? "ClawOS" : "用户"}：${message.content}`).join("\n\n");
  $("knowledgeTitle").value = (featureActions.sessionTitle(session) || "会话沉淀").slice(0, 80);
  $("knowledgeSource").value = "chat:" + sid;
  $("knowledgeContent").value = `# ${$("knowledgeTitle").value}\n\n## 对话摘要草稿\n\n${lines.slice(0, 10000)}`;
  $("knowledgeStatus").textContent = "已生成草稿，请编辑确认后保存";
  featureActions.setView("knowledge");
}

export async function appendKnowledgeToPrompt(id) {
  const item = consoleState.knowledge.knowledgeItems.find(row => Number(row.id) === Number(id));
  if (item) usePrompt(`请基于知识条目「${item.title}」回答：`);
  featureActions.setView("chat");
}

export async function deleteKnowledgeItem(id) {
  await api(`/api/knowledge/${Number(id)}`, { method: "DELETE" });
  await loadKnowledge();
  await searchKnowledge();
}

export function renderObsidianCheck(data) {
  const target = $("obsidianCheckTable");
  if (!target) return;
  const checks = data?.checks || [];
  const rows = checks.map(check => [check.name || "", { html: statusBadge(check.passed ? "success" : "failed") }, check.detail || ""]);
  rows.unshift(["总分", `${Math.round(Number(data?.score || 0) * 100)} / 100`, `${data?.note_count || 0} notes · ${data?.wikilink_count || 0} links · ${data?.backlink_count || 0} backlinks · ${data?.graph?.edges || 0} graph edges`]);
  target.innerHTML = table(["项目", "状态", "说明"], rows);
  if ($("obsidianStatus")) $("obsidianStatus").textContent = data?.ok ? `通过 · ${Math.round(Number(data.score || 0) * 100)} 分` : `需补强 · ${Math.round(Number(data?.score || 0) * 100)} 分`;
}

export async function checkObsidianVault() {
  const category = consoleState.knowledge.knowledgeCategory ? "?category=" + encodeURIComponent(consoleState.knowledge.knowledgeCategory) : "";
  if ($("obsidianStatus")) $("obsidianStatus").textContent = "正在检查双链笔记结构";
  try {
    const data = await api("/api/knowledge/obsidian/check" + category);
    renderObsidianCheck(data);
    await loadKnowledgeGraph();
  } catch (err) {
    $("obsidianStatus").textContent = "笔记库检查失败：" + err.message;
  }
}

export async function exportObsidianVault() {
  const output_dir = ($("obsidianExportDir")?.value || "").trim();
  if ($("obsidianStatus")) $("obsidianStatus").textContent = "正在导出 Markdown 笔记库";
  try {
    const data = await api("/api/knowledge/obsidian/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: consoleState.knowledge.knowledgeCategory, output_dir })
    });
    renderObsidianCheck(data);
    $("obsidianStatus").textContent = `已导出 ${data.file_count || 0} 个文件：${data.output_dir || ""}`;
    await loadKnowledgeGraph();
  } catch (err) {
    $("obsidianStatus").textContent = "笔记库导出失败：" + err.message;
  }
}

export function reportReadyDocuments() {
  return (consoleState.knowledge.knowledgeDocuments || []).filter(doc => String(doc.status || "") === "ready" && String(doc.filename || doc.file_path || "").toLowerCase().endsWith(".pdf"));
}

export function renderDocumentReportSelect(preferredId) {
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

export async function loadKnowledgeDocuments(preferredId) {
  const query = consoleState.knowledge.knowledgeCategory ? "?category=" + encodeURIComponent(consoleState.knowledge.knowledgeCategory) : "";
  try {
    const data = await api("/api/documents" + query);
    consoleState.knowledge.knowledgeDocuments = data.documents || [];
    renderDocumentReportSelect(preferredId);
  } catch (err) {
    consoleState.knowledge.knowledgeDocuments = [];
    renderDocumentReportSelect();
    if ($("reportResult")) $("reportResult").textContent = "资料列表加载失败：" + err.message;
  }
}

export function renderKnowledgeReportResult(data) {
  consoleState.knowledge.lastGeneratedReport = data;
  consoleState.knowledge.lastSavedReportKnowledgeId = null;
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

export function reportGenerationError(err) {
  const message = String(err?.message || "").trim();
  if (message.includes("404")) return "报告生成失败：没有找到这份资料，请刷新资料列表后重试。";
  if (message.includes("415") || message.includes("unsupported")) return "报告生成失败：当前只支持可读取的 PDF 资料，请换一个 PDF 后重试。";
  return `报告生成失败：${message || "生成服务没有返回明确原因"}。请确认资料是可读取的 PDF，或换一个输出目录后重试。`;
}

export async function generateKnowledgeReport() {
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

export async function saveGeneratedReportToKnowledge() {
  if (!consoleState.knowledge.lastGeneratedReport) {
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "请先生成报告";
    return;
  }
  const report = consoleState.knowledge.lastGeneratedReport.report || {};
  const doc = consoleState.knowledge.lastGeneratedReport.library_document || consoleState.knowledge.lastGeneratedReport.document || {};
  const style = report.metadata?.report_style || $("reportStylePreset")?.value || "journal";
  const title = `${doc.title || "资料报告"} · ${style}`;
  const sourceTitle = String(doc.title || "").trim();
  const sourceLink = sourceTitle ? `Related source: [[${sourceTitle} #1]]` : "";
  const content = [`# ${title}`, "", `Markdown: ${report.markdown_path || ""}`, `PDF: ${report.pdf_path || ""}`, `Output: ${report.output_dir || ""}`, `Style: ${style}`, sourceLink, "", "## Preview", consoleState.knowledge.lastGeneratedReport.preview || ""].filter(Boolean).join("\n");
  const saved = await api("/api/knowledge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, content, category: consoleState.knowledge.knowledgeCategory || doc.category || "research", source: report.markdown_path || "generated-report", tags: ["report", style, "generated"] })
  });
  consoleState.knowledge.lastSavedReportKnowledgeId = saved.item?.id || null;
  if ($("knowledgeStatus")) $("knowledgeStatus").textContent = "报告已保存到知识库，可继续导出 Markdown 笔记库";
  await loadKnowledge();
  await loadKnowledgeGraph();
  if (consoleState.knowledge.lastSavedReportKnowledgeId) {
    const flow = $("reportResult")?.querySelector(".report-flow");
    if (flow) {
      flow.querySelector(".report-flow-steps")?.insertAdjacentHTML("beforeend", `<span class="done">已保存</span>`);
      flow.insertAdjacentHTML("beforeend", `<div class="action-row"><button class="primary" onclick="appendKnowledgeToPrompt(${Number(consoleState.knowledge.lastSavedReportKnowledgeId)})">继续追问这个报告</button></div>`);
    }
  }
}

export async function loadKnowledgeGraph() {
  const map = $("knowledgeMap");
  const edges = $("knowledgeEdges");
  if (!map || !edges) return;
  try {
    const query = consoleState.knowledge.knowledgeCategory ? "?category=" + encodeURIComponent(consoleState.knowledge.knowledgeCategory) : "";
    const graph = await api("/api/knowledge/graph" + query);
    consoleState.knowledge.lastKnowledgeGraph = { nodes: graph.nodes || [], edges: graph.edges || [], category: graph.category || "all" };
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
    const summary = `${knowledgeCategoryLabel(consoleState.knowledge.knowledgeCategory)} · ${nodes.length} 个节点 · ${graph.edges?.length || 0} 条关系`;
    if ($("knowledgeMapHint")) $("knowledgeMapHint").textContent = summary;
    if ($("knowledgeGraphSummary")) $("knowledgeGraphSummary").textContent = summary;
    if ($("knowledgeMapHint")) $("knowledgeMapHint").textContent = `${graph.category || "all"} · ${nodes.length} 个真实节点 · ${graph.edges?.length || 0} 条语义关系`;
    if ($("knowledgeGraphExplorer")?.classList.contains("on")) renderKnowledgeGraphExplorer();
  } catch (err) {}
}

export function openKnowledgeBackstage() {
  featureActions.toggleCommandDrawer();
}

export function openKnowledgeGraphExplorer() {
  const explorer = $("knowledgeGraphExplorer");
  if (!explorer) return;
  explorer.classList.add("on");
  explorer.setAttribute("aria-hidden", "false");
  document.body.classList.add("graph-explorer-open");
  renderKnowledgeGraphExplorer();
  if (!consoleState.knowledge.lastKnowledgeGraph.nodes.length) loadKnowledgeGraph();
  window.setTimeout(() => explorer.querySelector("button, input, select")?.focus(), 0);
}

export function closeKnowledgeGraphExplorer() {
  const explorer = $("knowledgeGraphExplorer");
  if (!explorer) return;
  explorer.classList.remove("on");
  explorer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("graph-explorer-open");
}

export function graphNodeColor(type) {
  return ({ category: "#315cf5", knowledge: "#17865d", document: "#e87524", tag: "#7659d6" }[type] || "#697386");
}

export function graphTypeLabel(type) {
  return ({ category: "分类", knowledge: "知识", document: "文档", tag: "标签", source: "来源", concept: "概念" }[type] || "节点");
}

export function graphRelationLabel(type) {
  return ({ contains: "包含", cites: "引用", tagged: "标签", links_to: "链接", backlink: "反向链接", sourced_from: "来源", mentions: "提及" }[type] || "关系");
}

export function isPrivateKnowledgePath(value) {
  return /(?:^[a-z]:[\\/]|^\\\\|^\/(?:users|home|var|tmp)\/|file:\/\/)/i.test(String(value || "").trim());
}

export function publicKnowledgeNodeLabel(node) {
  const raw = String(node?.label || node?.title || node?.id || "知识节点").trim();
  if (node?.type === "source" || isPrivateKnowledgePath(raw)) return "本地导入资料";
  return raw.slice(0, 28);
}

export function publicKnowledgeNodeDescription(node) {
  const raw = String(node?.summary || node?.source || "该节点来自本地知识库，可沿关系继续探索。").trim();
  return isPrivateKnowledgePath(raw) ? "本地导入资料，路径信息已隐藏。" : raw;
}

export function renderKnowledgeGraphExplorer() {
  const stage = $("graphExplorerNodes");
  const edgesTarget = $("graphExplorerEdges");
  if (!stage || !edgesTarget) return;
  const type = $("graphTypeFilter")?.value || "";
  const relation = $("graphRelationFilter")?.value || "";
  const query = ($("graphNodeQuery")?.value || "").trim().toLowerCase();
  const sourceNodes = consoleState.knowledge.lastKnowledgeGraph.nodes || [];
  const visibleNodes = sourceNodes.filter(node => (!type || node.type === type) && (!query || JSON.stringify(node).toLowerCase().includes(query))).slice(0, 56);
  const visibleIds = new Set(visibleNodes.map(node => String(node.id)));
  const visibleEdges = (consoleState.knowledge.lastKnowledgeGraph.edges || []).filter(edge => visibleIds.has(String(edge.source)) && visibleIds.has(String(edge.target)) && (!relation || edge.type === relation)).slice(0, 140);
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
  if ($("graphExplorerSummary")) $("graphExplorerSummary").textContent = `${knowledgeCategoryLabel(consoleState.knowledge.knowledgeCategory)} · ${sourceNodes.length} 个节点 · ${(consoleState.knowledge.lastKnowledgeGraph.edges || []).length} 条关系`;
}

export function selectKnowledgeGraphNode(encodedId) {
  const id = decodeURIComponent(encodedId || "");
  const node = (consoleState.knowledge.lastKnowledgeGraph.nodes || []).find(item => String(item.id) === id);
  const inspector = $("graphInspector");
  if (!node || !inspector) return;
  const connected = (consoleState.knowledge.lastKnowledgeGraph.edges || []).filter(edge => String(edge.source) === id || String(edge.target) === id);
  const relationCounts = connected.reduce((acc, edge) => { acc[edge.type || "relation"] = (acc[edge.type || "relation"] || 0) + 1; return acc; }, {});
  inspector.innerHTML = `<span class="eyebrow">节点详情</span><div class="graph-inspector-type" style="--node-color:${graphNodeColor(node.type)}">${esc(graphTypeLabel(node.type))}</div><h3>${esc(publicKnowledgeNodeLabel(node))}</h3><p>${esc(publicKnowledgeNodeDescription(node))}</p><dl><div><dt>权重</dt><dd>${esc(node.weight || 1)}</dd></div><div><dt>相邻关系</dt><dd>${connected.length}</dd></div><div><dt>关系类型</dt><dd>${esc(Object.entries(relationCounts).map(([key, value]) => `${graphRelationLabel(key)} ${value}`).join(" · ") || "暂无")}</dd></div></dl><button class="primary" type="button" onclick="closeKnowledgeGraphExplorer()">返回知识库</button>`;
  document.querySelectorAll(".graph-node").forEach(button => button.classList.toggle("on", decodeURIComponent((button.getAttribute("onclick") || "").split("'")[1] || "") === id));
}

export async function loadOcrQueue() {
  const target = $("ocrQueueTable");
  if (!target) return;
  try {
    const query = consoleState.knowledge.knowledgeCategory ? "?category=" + encodeURIComponent(consoleState.knowledge.knowledgeCategory) : "";
    const data = await api("/api/documents/ocr-queue" + query);
    target.innerHTML = table(["文档", "库", "页码", "原因", "操作"], (data.documents || []).map(item => [item.title || item.filename || "", knowledgeCategoryLabel(item.category), Array.isArray(item.ocr_pages) ? item.ocr_pages.join(", ") : "", item.ocr_reason || "low_extractable_text", { html: `<button class="secondary" onclick="openDocumentReview(${Number(item.id)})">对照原图复核</button> <button class="secondary" onclick="runDocumentOcr(${Number(item.id)})">重新 OCR</button>` }]));
  } catch (err) {
    target.innerHTML = table(["文档", "库", "页码", "原因", "操作"], []);
  }
}

export async function openDocumentReview(id) {
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
      const effort = data.review_effort || {};
      const timing = effort.timed_submissions ? ` · 已记录 ${effort.timed_submissions} 次真实操作，共 ${(effort.active_review_ms / 1000).toFixed(1)} 秒、修改 ${effort.corrected_cell_count} 格` : " · 尚无真实复核耗时样本";
      status.textContent = `${data.items.filter(item => item.state !== "rejected").length} 条待复核 · ${data.items.filter(item => item.state === "rejected").length} 条已拒绝 · ${data.history.length} 条历史记录${timing}。请核对整行和表头，尤其是数字、单位和否定词。`;
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
        section.appendChild(title); const inputs = new Map(); let loaded = 0; let reviewStartedAt = null;
        for (const cell of item.cells) {
          const row = document.createElement("div"); row.style.cssText = "display:grid;grid-template-columns:minmax(160px,1fr) minmax(180px,1fr);gap:12px;margin:12px 0";
          const source = document.createElement("div");
          const label = document.createElement("p"); label.textContent = `第 ${cell.page} 页 · ${cell.is_header ? "表头" : cell.header || "正文"}`; source.appendChild(label);
          const img = document.createElement("img"); img.src = cell.crop_url; img.alt = "原始 PDF 单元格裁剪"; img.style.cssText = "max-width:100%;border:1px solid #8885";
          img.onload = () => { loaded += 1; if (loaded === item.cells.length) reviewStartedAt = performance.now(); }; img.onerror = () => { status.textContent = "原图加载失败，不能确认。请检查源文件后重试。"; };
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
              const activeReviewMs = Math.max(0, Math.round(performance.now() - (reviewStartedAt || performance.now())));
              await api(`/api/documents/${Number(id)}/review`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({chunk_id:item.chunk_id,revision:data.revision,values:Object.fromEntries([...inputs].map(([key,input])=>[key,input.value])),confirmed:true,action,active_review_ms:activeReviewMs})});
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

export async function runDocumentOcr(id) {
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

export async function askCitationAnswer() {
  const target = $("citationAnswerTable");
  if (!target) return;
  const query = ($("citationQuery")?.value || "").trim();
  if (!query) {
    target.innerHTML = table(["引用", "文档", "片段"], []);
    return;
  }
  const category = consoleState.knowledge.knowledgeCategory ? "&category=" + encodeURIComponent(consoleState.knowledge.knowledgeCategory) : "";
  try {
    const data = await api("/api/documents/citation-answer?q=" + encodeURIComponent(query) + category + "&limit=6");
    target.innerHTML = table(["引用", "文档", "片段"], (data.citations || []).map(item => [item.citation, item.title || "", item.snippet || ""]));
    if ($("knowledgeStatus")) $("knowledgeStatus").textContent = `引用回答已生成 · ${data.count || 0} 条证据`;
  } catch (err) {
    target.innerHTML = table(["引用", "文档", "片段"], [["error", "", err.message]]);
  }
}
