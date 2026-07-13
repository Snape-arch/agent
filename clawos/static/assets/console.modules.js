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

function runtimeLabel(value, labels) {
  const key = String(value || "");
  return labels[key] || key || "未记录";
}

const boundaryLabels = {
  server_api: "API 服务",
  workflow_engine: "工作流引擎",
  agent_orchestration: "多代理编排",
  artifact_storage: "产物存储",
  evaluation_service: "评测服务",
};

const runTypeLabels = { multi_agent: "多代理协作", single_agent: "单代理执行", workflow: "工作流" };
const runStatusLabels = { succeeded: "已完成", running: "运行中", failed: "失败", revision_required: "需要修订", queued: "等待中", cancelled: "已取消" };
const failureCategoryLabels = { agent_disagreement: "代理分歧", tool_error: "工具异常", validation_error: "校验失败", timeout: "执行超时" };
const failureReasonLabels = {
  "Silent pass after partial rework": "局部返工后被静默放行",
  "JudgeAgent final approval before risk score threshold is met": "风险阈值未满足时裁决代理提前批准",
  "BuilderAgent release-ready claim": "构建代理提前声明可发布",
};

function renderRuntimeRecords(schema, runs, failures) {
  const target = $("runtimeRecordGrid");
  if (!target) return;
  const latest = (runs.runs || [])[0] || {};
  const failureRows = (failures.failure_cases || []).slice(0, 3);
  target.innerHTML = `
    <div class="runtime-record-card runtime-boundary-card">
      <div class="runtime-card-head"><span>01</span><div><b>服务边界</b><small>可审计的执行域</small></div><em>${(schema.service_boundaries || []).length} 项</em></div>
      <div class="runtime-chip-row">${(schema.service_boundaries || []).map(item => `<span title="${esc(item)}">${esc(runtimeLabel(item, boundaryLabels))}</span>`).join("")}</div>
    </div>
    <div class="runtime-record-card runtime-latest-card">
      <div class="runtime-card-head"><span>02</span><div><b>最近运行</b><small>来自统一运行记录</small></div><em>${latest.status ? "已记录" : "暂无记录"}</em></div>
      <div class="runtime-metric-grid">
        ${runtimeMetric("记录模型", runs.schema || schema.schema || "未记录")}
        ${runtimeMetric("执行类型", runtimeLabel(latest.run_type, runTypeLabels))}
        ${runtimeMetric("当前状态", runtimeLabel(latest.status, runStatusLabels))}
        ${runtimeMetric("产物数量", (latest.artifacts || []).length)}
      </div>
    </div>
    <div class="runtime-record-card failure-library-card">
      <div class="runtime-card-head"><span>03</span><div><b>失败样本</b><small>用于复盘与回归评测</small></div><em>${failureRows.length} 条</em></div>
      ${failureRows.length ? failureRows.map(item => `
        <div class="failure-sample">
          <span>${esc(runtimeLabel(item.category, failureCategoryLabels))}</span>
          <p>${esc(runtimeLabel(item.reason, failureReasonLabels))}</p>
        </div>
      `).join("") : '<div class="runtime-empty"><b>暂无失败样本</b><span>真实失败发生后会沉淀在这里。</span></div>'}
    </div>
  `;
}

async function loadRuntimeRecords() {
  if (!$("runtimeRecordGrid")) return;
  if ($("runtimeSchemaStatus")) $("runtimeSchemaStatus").textContent = "正在读取统一运行记录…";
  try {
    const [schema, runs, failures] = await Promise.all([
      api("/api/runtime/schema"),
      api("/api/runtime/runs/latest?limit=8"),
      api("/api/runtime/failure-cases?limit=12"),
    ]);
    if ($("runtimeSchemaStatus")) {
      $("runtimeSchemaStatus").textContent = `${schema.schema} · ${runs.count || 0} 次运行 · ${failures.count || 0} 条失败样本`;
    }
    renderRuntimeRecords(schema, runs, failures);
  } catch (err) {
    if ($("runtimeSchemaStatus")) $("runtimeSchemaStatus").textContent = "运行记录读取失败：" + err.message;
    if ($("runtimeRecordGrid")) $("runtimeRecordGrid").innerHTML = `<div class="runtime-record-card">${esc(err.message)}</div>`;
  }
}

window.loadRuntimeRecords = loadRuntimeRecords;
setTimeout(loadRuntimeRecords, 0);
