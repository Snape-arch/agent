// operations behavior for the ClawOS workbench.
import { $, API, api, consoleState, esc, statusBadge, table } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   loadRoutingStrategy: typeof import('./security.js').loadRoutingStrategy,
 *   loadWorkerStatus: typeof import('./tasks.js').loadWorkerStatus,
 *   renderOpsDocuments: typeof import('./tasks.js').renderOpsDocuments,
 *   loadTasks: typeof import('./tasks.js').loadTasks,
 *   loadKnowledgeDocuments: typeof import('./knowledge.js').loadKnowledgeDocuments,
 *   refreshAll: typeof import('./shell.js').refreshAll,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export async function loadHealth() {
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

export async function loadDash() {
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
    await Promise.allSettled([loadModelHealth(), loadToolAccuracy(), featureActions.loadRoutingStrategy()]);
  } catch (err) {}
}

export async function loadModelHealth() {
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

export async function refreshOfflineReadiness() {
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

export async function loadLocalRemediationGuide() {
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

export async function markLocalRemediationAction(button, status) {
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

export async function recheckLocalRemediationAction(button) {
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

export async function loadLocalWorkbenchTimeline() {
  const target = $("localWorkbenchTimelineTable");
  if (!target) return;
  const data = await api("/api/workbench/local-timeline?limit=20").catch(() => ({ items: [] }));
  consoleState.operations.localWorkbenchTimelineItems = data.items || [];
  const rows = consoleState.operations.localWorkbenchTimelineItems.map((item, index) => [
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

export async function openLocalTimelineEvent(index) {
  const item = consoleState.operations.localWorkbenchTimelineItems[index] || {};
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

export async function loadLocalAcceptanceHistory() {
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

export async function runDailyLocalAcceptance(includeQwenSmoke = false) {
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
    consoleState.operations.dailyLocalAcceptanceSummary = data.summary || JSON.stringify(data, null, 2);
    if (summary) summary.textContent = consoleState.operations.dailyLocalAcceptanceSummary;
    if (status) status.textContent = `Daily local acceptance ${data.ok ? "passed" : "needs attention"}.`;
    await refreshOfflineReadiness();
    await loadLocalAcceptanceHistory();
  } catch (err) {
    consoleState.operations.dailyLocalAcceptanceSummary = "";
    if (summary) summary.textContent = "Daily local acceptance failed: " + err.message;
    if (status) status.textContent = "Daily local acceptance failed.";
  }
}

export async function runLocalQwenSmokeCheck() {
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
    consoleState.operations.dailyLocalAcceptanceSummary = [
      "ClawOS Local Qwen Smoke",
      `Status: ${data.ok ? "ok" : "not ready"}`,
      `Endpoint: ${data.base_url || ""}`,
      `Model: ${data.model || ""}`,
      `Assets: ${data.assets_summary || ""}`,
      `Error: ${data.error || ""}`,
      `Preview: ${data.content_preview || ""}`
    ].join("\n");
    if (summary) summary.textContent = consoleState.operations.dailyLocalAcceptanceSummary;
    if (status) status.textContent = `Local Qwen smoke ${data.ok ? "passed" : "needs attention"}.`;
    await refreshOfflineReadiness();
    await loadLocalAcceptanceHistory();
  } catch (err) {
    consoleState.operations.dailyLocalAcceptanceSummary = "";
    if (summary) summary.textContent = "Local Qwen smoke failed: " + err.message;
    if (status) status.textContent = "Local Qwen smoke failed.";
  }
}

export async function exportLocalMaintenanceReport() {
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
    consoleState.operations.dailyLocalAcceptanceSummary = [
      "ClawOS Local Maintenance Report",
      `JSON: ${jsonPath}`,
      `Markdown: ${markdownPath}`,
      `Readiness: ${data.report?.readiness?.percent || 0}%`,
      `Remediation actions: ${data.report?.remediation?.count || 0}`,
      `Run: ${data.run?.run_id || "not persisted"}`
    ].join("\n");
    if (summary) summary.textContent = consoleState.operations.dailyLocalAcceptanceSummary;
    if (status) status.textContent = "Local maintenance report exported.";
    await loadLocalAcceptanceHistory();
    await loadLocalMaintenanceReports();
    if (data.run?.run_id) await openLocalMaintenanceReport(data.run.run_id);
  } catch (err) {
    consoleState.operations.dailyLocalAcceptanceSummary = "";
    if (summary) summary.textContent = "Local maintenance report export failed: " + err.message;
    if (status) status.textContent = "Local maintenance report export failed.";
  }
}

export async function loadLocalMaintenanceReports() {
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

export async function openLocalMaintenanceReport(runId) {
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

export async function copyDailyLocalAcceptanceSummary() {
  const summary = consoleState.operations.dailyLocalAcceptanceSummary || $("dailyAcceptanceSummary")?.textContent || "";
  if (!summary.trim()) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(summary);
  }
  const status = $("offlineReadinessStatus");
  if (status) status.textContent = "Daily local acceptance summary copied.";
}

export async function loadToolAccuracy() {
  const target = $("toolAccuracyTable");
  if (!target) return;
  const data = await api("/api/tools/accuracy").catch(() => ({ items: [] }));
  target.innerHTML = table(["工具", "准确率", "次数"], (data.items || data.tools || []).map(item => [item.tool || item.name, item.accuracy || item.success_rate || "", item.count || item.total || ""]));
}

export async function loadOps() {
  if (!$("view-ops")) return;
  try {
    const readiness = await api("/api/system/readiness");
    if ($("opsReadinessScore")) $("opsReadinessScore").textContent = `Readiness: ${readiness.percent}% · ${readiness.enterprise_ready ? "enterprise ops gate passed" : "needs attention"}`;
    if ($("opsReadinessTable")) $("opsReadinessTable").innerHTML = table(["Check", "Status", "Weight"], (readiness.checks || []).map(item => [item.label, { html: statusBadge(item.ok ? "success" : "failed") }, item.weight]));
  } catch (err) {
    if ($("opsReadinessScore")) $("opsReadinessScore").textContent = "Readiness failed: " + err.message;
  }
  await Promise.allSettled([featureActions.loadWorkerStatus(), featureActions.loadKnowledgeDocuments().then(featureActions.renderOpsDocuments)]);
}

export async function runConfigCheck() {
  try {
    const data = await api("/api/system/config/check");
    if ($("opsConfigStatus")) $("opsConfigStatus").textContent = data.ok ? "ok" : "needs attention";
    if ($("opsConfigTable")) $("opsConfigTable").innerHTML = table(["Item", "Status", "Detail"], (data.checks || []).map(item => [item.name || item.id || "", { html: statusBadge(item.ok ? "success" : "failed") }, item.message || item.detail || ""]));
  } catch (err) {
    if ($("opsConfigStatus")) $("opsConfigStatus").textContent = err.message;
  }
}

export async function createBackup() {
  try {
    const data = await api("/api/system/backup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ output_dir: $("opsBackupDir")?.value || "output/backups", label: $("opsBackupLabel")?.value || "manual" }) });
    if ($("opsBackupResult")) $("opsBackupResult").textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    if ($("opsBackupResult")) $("opsBackupResult").textContent = err.message;
  }
}

export async function restoreBackup() {
  try {
    const data = await api("/api/system/restore", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ backup_path: $("opsRestorePath")?.value || "", confirm: Boolean($("opsRestoreConfirm")?.checked), label: "pre-restore" }) });
    if ($("opsBackupResult")) $("opsBackupResult").textContent = JSON.stringify(data, null, 2);
    await featureActions.refreshAll();
  } catch (err) {
    if ($("opsBackupResult")) $("opsBackupResult").textContent = err.message;
  }
}

export async function startWorker() { await api("/api/tasks/worker/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ worker_id: "console-worker", interval_s: 0.5, max_attempts: 3 }) }); await featureActions.loadWorkerStatus(); }

export async function stopWorker() { await api("/api/tasks/worker/stop", { method: "POST" }); await featureActions.loadWorkerStatus(); }

export async function tickWorker() { const data = await api("/api/tasks/worker/tick", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ worker_id: "console-worker", max_attempts: 3 }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await Promise.allSettled([featureActions.loadWorkerStatus(), featureActions.loadTasks()]); }

export async function queueReportJob() { const id = Number($("opsReportDocumentSelect")?.value || 0); if (!id) { if ($("opsJobResult")) $("opsJobResult").textContent = "Select a ready document first"; return; } const data = await api("/api/tasks/jobs/report", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ library_document_id: id, report_style: $("opsReportStyle")?.value || "journal", output_dir: $("opsReportOutputDir")?.value || "output/reports", formats: ["markdown", "pdf"] }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await featureActions.loadTasks(); }

export async function queueOcrJob() { const data = await api("/api/tasks/jobs/ocr-queue", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ category: $("opsOcrCategory")?.value || "", limit: Number($("opsOcrLimit")?.value || 12), force: true }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await featureActions.loadTasks(); }

export async function queueBatchIngestJob() { const files = ($("opsBatchFiles")?.value || "").split(/\n|,|;/).map(item => item.trim()).filter(Boolean); const data = await api("/api/tasks/jobs/batch-ingest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ files, category: $("opsBatchCategory")?.value || "domain" }) }); if ($("opsJobResult")) $("opsJobResult").textContent = JSON.stringify(data, null, 2); await featureActions.loadTasks(); }
