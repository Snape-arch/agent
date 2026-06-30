window.ClawOSConsoleModules = [
  {
    id: "runtime-records",
    layer: "system-back",
    owns: ["runtimeRecordPanel", "runtimeRecordGrid"],
    api: ["/api/runtime/schema", "/api/runtime/runs/latest", "/api/runtime/failure-cases"],
    purpose: "Render unified Run / Artifact / Evidence / FailureCase records.",
  },
  {
    id: "acceptance-report-card",
    layer: "work-front",
    owns: ["acceptanceReportStatus", "acceptanceReportResult"],
    api: ["/api/acceptance/deepseek-qwen/latest"],
    purpose: "Render compact DeepSeek + Qwen acceptance evidence.",
  },
  {
    id: "multi-agent-audit-board",
    layer: "work-front",
    owns: ["committeeResult"],
    api: ["/api/skills/execute"],
    purpose: "Render role lanes, timeline, disputes, arbitration, and v1/v2 diffs.",
  },
];

function runtimeMetric(label, value) {
  return `<div class="runtime-metric"><span>${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function renderRuntimeRecords(schema, runs, failures) {
  const target = $("runtimeRecordGrid");
  if (!target) return;
  const latest = (runs.runs || [])[0] || {};
  const failureRows = (failures.failure_cases || []).slice(0, 3);
  target.innerHTML = `
    <div class="runtime-record-card">
      <b>Service Boundaries</b>
      <div class="runtime-chip-row">${(schema.service_boundaries || []).map(item => `<span>${esc(item)}</span>`).join("")}</div>
    </div>
    <div class="runtime-record-card">
      <b>Latest Run</b>
      <div class="runtime-metric-grid">
        ${runtimeMetric("schema", runs.schema || schema.schema || "")}
        ${runtimeMetric("type", latest.run_type || "none")}
        ${runtimeMetric("status", latest.status || "none")}
        ${runtimeMetric("artifacts", (latest.artifacts || []).length)}
      </div>
    </div>
    <div class="runtime-record-card failure-library-card">
      <b>Failure Library</b>
      ${failureRows.length ? failureRows.map(item => `
        <div class="failure-sample">
          <span>${esc(item.category || "failure")}</span>
          <p>${esc(item.reason || "")}</p>
        </div>
      `).join("") : '<p class="hint">No saved failure sample yet.</p>'}
    </div>
  `;
}

async function loadRuntimeRecords() {
  if (!$("runtimeRecordGrid")) return;
  if ($("runtimeSchemaStatus")) $("runtimeSchemaStatus").textContent = "正在读取统一 Run/Artifact/Evidence schema...";
  try {
    const [schema, runs, failures] = await Promise.all([
      api("/api/runtime/schema"),
      api("/api/runtime/runs/latest?limit=8"),
      api("/api/runtime/failure-cases?limit=12"),
    ]);
    if ($("runtimeSchemaStatus")) {
      $("runtimeSchemaStatus").textContent = `${schema.schema} · ${runs.count || 0} runs · ${failures.count || 0} failure samples`;
    }
    renderRuntimeRecords(schema, runs, failures);
  } catch (err) {
    if ($("runtimeSchemaStatus")) $("runtimeSchemaStatus").textContent = "运行记录读取失败：" + err.message;
    if ($("runtimeRecordGrid")) $("runtimeRecordGrid").innerHTML = `<div class="runtime-record-card">${esc(err.message)}</div>`;
  }
}

window.loadRuntimeRecords = loadRuntimeRecords;
setTimeout(loadRuntimeRecords, 0);
