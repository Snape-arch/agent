// review behavior for the ClawOS workbench.
import { $, API, api, consoleState, esc, formatMs, statusBadge, table, usePrompt } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   loadKnowledge: typeof import('./knowledge.js').loadKnowledge,
 *   loadKnowledgeGraph: typeof import('./knowledge.js').loadKnowledgeGraph,
 *   enterpriseDeliveryPayload: typeof import('./deliveries.js').enterpriseDeliveryPayload,
 *   setView: typeof import('./shell.js').setView,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export function renderComplexAcceptanceReport(data) {
  consoleState.review.lastComplexAcceptanceReport = data;
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

export async function loadComplexAcceptanceReport() {
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

export function renderLiveSearchReport(data) {
  consoleState.review.lastLiveSearchReport = data;
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

export async function loadLiveSearchReport() {
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

export function renderMeetingAudioResult(data) {
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

export async function runMeetingAudioUpload() {
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
    await featureActions.loadKnowledge().catch(() => {});
    await loadRuntimeRecords().catch(() => {});
  } catch (err) {
    if (status) status.textContent = "会议音频处理失败：" + err.message;
    if (result) result.textContent = "处理失败：" + err.message;
  }
}

export function committeePayload() {
  return consoleState.review.lastSelfReviewCommittee?.result || consoleState.review.lastSelfReviewCommittee?.data || consoleState.review.lastSelfReviewCommittee || {};
}

export function renderCommitteeTimeline(items) {
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

export function roleAvatar(agent) {
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

export function renderRoleSwimlanes(payload) {
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

export function renderAuditTimeline(items) {
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

export function renderDisputeCards(disagreements) {
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

export function renderArtifactDiff(reworkLoop) {
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

export function renderBuilderExecution(builderExecution) {
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

export function renderCommitteeAuditBoard(payload) {
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

export function renderRubricMatrix(matrix) {
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

export function renderSelfReviewCommitteeResult(data) {
  consoleState.review.lastSelfReviewCommittee = data;
  consoleState.review.lastCommitteeKnowledgeIds = [];
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

export async function runSelfReviewCommittee() {
  const outputDir = ($("committeeOutputDir")?.value || $("enterpriseOutputDir")?.value || "output/delivery").trim() || "output/delivery";
  const params = {
    output_dir: outputDir,
    project_name: ($("enterpriseProjectName")?.value || "ClawOS").trim() || "ClawOS",
    scenario: ($("enterpriseScenario")?.value || "MTClaw competition enterprise delivery").trim() || "MTClaw competition enterprise delivery",
    focus: ($("committeeFocus")?.value || "competition final readiness").trim() || "competition final readiness"
  };
  const existingDelivery = featureActions.enterpriseDeliveryPayload();
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

export async function saveSelfReviewCommitteeToKnowledge() {
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
  consoleState.review.lastCommitteeKnowledgeIds = savedIds;
  consoleState.knowledge.knowledgeCategory = "project";
  if ($("knowledgeCategory")) $("knowledgeCategory").value = "project";
  if ($("committeeStatus")) $("committeeStatus").textContent = `已保存 ${savedIds.length} 个委员会条目到项目知识库`;
  await featureActions.loadKnowledge();
  await featureActions.loadKnowledgeGraph();
  const flow = $("committeeResult")?.querySelector(".report-flow");
  if (flow && savedIds.length) {
    flow.querySelector(".report-flow-steps")?.insertAdjacentHTML("beforeend", `<span class="done">已保存 ${savedIds.length} 条</span>`);
  }
}

export function askSelfReviewCommitteeQuestion() {
  const payload = committeePayload();
  const title = payload.project_name || $("enterpriseProjectName")?.value || "ClawOS";
  usePrompt(`请基于 ${title} 自评审委员会报告，给出夺冠前最该优先关闭的 5 个问题，并按 P0/P1/P2 排序。`);
  featureActions.setView("chat");
}

export function reportPresetInfo() {
  const style = $("reportStylePreset")?.value || "journal";
  return {
    journal: { label: "论文分析", hint: "适合论文精读、证据追踪和复现检查。" },
    learning_notes: { label: "学习笔记", hint: "适合课程复习、概念拆解和自测问题。" },
    business_brief: { label: "商业简报", hint: "适合路演、汇报和项目价值表达。" },
    compact: { label: "紧凑版", hint: "适合快速交付一页摘要和行动清单。" }
  }[style] || { label: "论文分析", hint: "适合论文精读、证据追踪和复现检查。" };
}

export function applyReportPreset() {
  const info = reportPresetInfo();
  if ($("reportStyleHint")) $("reportStyleHint").textContent = info.hint;
}

export function useReportStylePrompt() {
  const info = reportPresetInfo();
  const depth = $("reportDepthPreset")?.value || "5";
  usePrompt(`请基于我上传或知识库中的论文资料，生成${info.label}风格的报告。要求：depth=${depth}，保留引用证据、关键结论、风险局限和下一步行动。`);
  featureActions.setView("chat");
}
