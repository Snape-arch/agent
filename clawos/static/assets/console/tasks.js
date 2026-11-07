// tasks behavior for the ClawOS workbench.
import { $, api, consoleState, esc, statusBadge, table, usePrompt } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   renderWorkbenchTasks: typeof import('./shell.js').renderWorkbenchTasks,
 *   setView: typeof import('./shell.js').setView,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export async function loadTools() {
  const target = $("toolsTable");
  if (!target) return;
  try {
    const data = await api("/api/tools");
    consoleState.tasks.allTools = data.tools || data.items || [];
    renderTools();
  } catch (err) {
    target.innerHTML = table(["工具", "说明"], []);
  }
}

export function renderTools() {
  const target = $("toolsTable");
  if (!target) return;
  const query = ($("toolQuery")?.value || "").toLowerCase();
  const rows = consoleState.tasks.allTools.filter(tool => !query || JSON.stringify(tool).toLowerCase().includes(query));
  target.innerHTML = table(["工具", "说明", "风险"], rows.map(tool => [tool.name || tool.function?.name || "", tool.description || tool.function?.description || "", tool.risk_level || ""]));
}

export async function loadToolExecutions() {
  const target = $("toolExecTable");
  if (!target) return;
  const data = await api("/api/tools/executions?limit=50").catch(() => ({ executions: [] }));
  target.innerHTML = table(["工具", "状态", "时间"], (data.executions || data.items || []).map(item => [item.tool || item.name || "", { html: statusBadge(item.status || "success") }, item.created_at || ""]));
}

export function taskActions(task) {
  const id = Number(task.id);
  const terminal = ["succeeded", "failed", "canceled", "interrupted"].includes(task.status);
  return `<button class="secondary" onclick="showTask(${id})">查看</button> ${terminal ? "" : `<button class="secondary icon-text" onclick="cancelTask(${id})"><span class="fluent-icon" aria-hidden="true">&#xE71A;</span>取消</button>`} <button class="secondary icon-text" onclick="retryTask(${id})"><span class="fluent-icon" aria-hidden="true">&#xE777;</span>重试</button>`;
}

export async function loadTasks() {
  try {
    const data = await api("/api/tasks?session_id=" + encodeURIComponent(consoleState.chat.currentSession) + "&limit=20");
    const rows = data.tasks || [];
    featureActions.renderWorkbenchTasks(rows);
    if (!consoleState.chat.lastTaskId && rows[0]) consoleState.chat.lastTaskId = rows[0].id;
    if ($("taskTable")) $("taskTable").innerHTML = table(["ID", "状态", "尝试", "标题", "来源", "开始", "操作"], rows.map(task => [task.id, { html: statusBadge(task.status) }, task.attempt || 1, task.title, task.source, task.started_at, { html: taskActions(task) }]));
    await loadTaskQueue();
    if (consoleState.chat.lastTaskId) await showTask(consoleState.chat.lastTaskId);
  } catch (err) {
    featureActions.renderWorkbenchTasks([]);
    if ($("taskTable")) $("taskTable").innerHTML = table(["ID", "状态", "尝试", "标题", "来源", "开始", "操作"], []);
  }
}

export async function loadTaskQueue() {
  const target = $("taskQueueTable");
  if (!target) return;
  try {
    const data = await api("/api/tasks/queue?limit=20");
    target.innerHTML = table(["ID", "状态", "尝试", "标题", "恢复状态", "操作"], (data.tasks || []).map(task => [task.id, { html: statusBadge(task.status) }, task.attempt || 1, task.title, task.resume_state || "", { html: `<button class="secondary" onclick="showTask(${Number(task.id)})">查看</button> <button class="primary" onclick="claimTask(${Number(task.id)})">领取</button>` }]));
  } catch (err) {
    target.innerHTML = table(["ID", "状态", "尝试", "标题", "恢复状态", "操作"], []);
  }
}

export async function claimTask(id) {
  const data = await api("/api/tasks/queue/claim", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ worker_id: "console" }) });
  $("liveTaskState").textContent = data.task?.id ? `已领取任务 #${data.task.id}` : "队列暂无可领取任务";
  if (data.task?.id) consoleState.chat.lastTaskId = data.task.id;
  await loadTasks();
}

export async function cancelTask(id) {
  await api(`/api/tasks/${id}/cancel`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "console cancel", actor_id: "console" }) });
  await loadTasks();
}

export async function retryTask(id) {
  const data = await api(`/api/tasks/${id}/retry`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "console retry", actor_id: "console" }) });
  consoleState.chat.lastTaskId = data.task?.id || consoleState.chat.lastTaskId;
  await loadTasks();
}

export async function recoverTasks() {
  const data = await api("/api/tasks/recover", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console" }) });
  $("liveTaskState").textContent = `恢复完成：${data.count || 0} 个任务`;
  await loadTasks();
}

export async function showTask(task_id) {
  if (!task_id || !$("taskStepTable")) return;
  consoleState.chat.lastTaskId = task_id;
  const data = await api("/api/tasks/" + encodeURIComponent(task_id));
  $("taskStepTable").innerHTML = table(["步骤", "状态", "开始", "完成", "输出"], (data.steps || []).map(step => [step.name, { html: statusBadge(step.status) }, step.started_at, step.completed_at || "", JSON.stringify(step.output || {}).slice(0, 220)]));
  $("taskEventTable").innerHTML = table(["事件", "消息", "时间", "数据"], (data.events || []).map(event => [event.event_type, event.message || "", event.created_at, JSON.stringify(event.data || {}).slice(0, 220)]));
}

export function startTaskStream() {
  if (consoleState.tasks.taskStream) {
    consoleState.tasks.taskStream.close();
    consoleState.tasks.taskStream = null;
  }
  if (!window.EventSource) {
    if ($("liveTaskState")) $("liveTaskState").textContent = "实时事件：轮询模式";
    return;
  }
  try {
    consoleState.tasks.taskStream = new EventSource(`/api/tasks/stream?session_id=${encodeURIComponent(consoleState.chat.currentSession)}&after_id=${consoleState.tasks.taskEventCursor}`);
    consoleState.tasks.taskStream.addEventListener("task_events", event => {
      const rows = JSON.parse(event.data || "[]");
      if (rows.length) {
        consoleState.tasks.taskEventCursor = Math.max(...rows.map(row => Number(row.id) || 0));
        if ($("liveTaskState")) $("liveTaskState").textContent = `实时事件：已同步到 #${consoleState.tasks.taskEventCursor}`;
        loadTasks();
      }
    });
    consoleState.tasks.taskStream.onerror = () => {
      if ($("liveTaskState")) $("liveTaskState").textContent = "实时事件：连接重试中";
    };
  } catch (err) {
    if ($("liveTaskState")) $("liveTaskState").textContent = "实时事件：不可用";
  }
}

export async function loadBenchmarks() {
  if (!$("benchmarkSuiteTable")) return;
  try {
    const [suites, runs] = await Promise.all([api("/api/benchmarks/scenarios/suites"), api("/api/benchmarks/scenarios/runs")]);
    consoleState.tasks.benchmarkSuites = suites.suites || [];
    $("benchmarkSuiteTable").innerHTML = table(["ID", "名称", "冻结", "用例数", "说明"], consoleState.tasks.benchmarkSuites.map(item => [item.id, item.name, item.frozen ? "是" : "否", (item.cases || []).length, item.description]));
    $("benchmarkRunTable").innerHTML = table(["ID", "结果", "通过率", "P95", "场景", "时间"], (runs.runs || []).map(item => [item.id, { html: statusBadge(item.passed ? "success" : "failed") }, item.metrics?.pass_rate, item.metrics?.p95_latency_ms, (item.metrics?.scenarios || []).join(", "), item.created_at]));
  } catch (err) {}
}

export async function runScenarioBenchmark() {
  const suiteId = consoleState.tasks.benchmarkSuites[0]?.id;
  await api("/api/benchmarks/scenarios/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(suiteId ? { suite_id: suiteId } : {}) });
  await loadBenchmarks();
  await loadTasks();
}

export async function loadCapabilities() {
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

export function ensureProfessionalBoard() {
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

export function activateScenarioBoard(kind) {
  const prompts = {
    research: "请按 Research Board 执行：论文入库、引用问答、期刊级报告、复现实验计划和证据质量门。",
    learning: "请按 Learning Board 执行：概念图谱、掌握度证据、错题归因、间隔复习计划和长期追踪。",
    code: "请按 Code Board 执行：仓库结构扫描、任务拆分、风险登记、测试闭环和交接记录。",
    office: "请按 Office Board 执行：简报、表格、幻灯片、会议纪要和导出质量检查。"
  };
  usePrompt(prompts[kind] || prompts.research);
  featureActions.setView("chat");
}

export function renderOpsDocuments() {
  const select = $("opsReportDocumentSelect");
  if (!select) return;
  const docs = (consoleState.knowledge.knowledgeDocuments || []).filter(doc => String(doc.status || "") === "ready");
  select.innerHTML = docs.length ? docs.map(doc => `<option value="${Number(doc.id)}">${esc(doc.title || doc.filename || ("doc " + doc.id))}</option>`).join("") : '<option value="">No ready documents</option>';
}

export async function loadWorkerStatus() {
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
