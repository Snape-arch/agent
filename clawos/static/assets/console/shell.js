// shell behavior for the ClawOS workbench.
import { $, VIEW_META, WORKBENCH_PROMPTS, api, consoleState, esc, usePrompt, workbenchProgress, workbenchStatusLabel } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   sendMessage: typeof import('./chat.js').sendMessage,
 *   handlePickedFiles: typeof import('./chat.js').handlePickedFiles,
 *   ensureProfessionalBoard: typeof import('./tasks.js').ensureProfessionalBoard,
 *   loadTools: typeof import('./tasks.js').loadTools,
 *   loadToolExecutions: typeof import('./tasks.js').loadToolExecutions,
 *   loadTasks: typeof import('./tasks.js').loadTasks,
 *   loadBenchmarks: typeof import('./tasks.js').loadBenchmarks,
 *   loadCapabilities: typeof import('./tasks.js').loadCapabilities,
 *   loadHealth: typeof import('./operations.js').loadHealth,
 *   loadDash: typeof import('./operations.js').loadDash,
 *   loadOps: typeof import('./operations.js').loadOps,
 *   refreshOfflineReadiness: typeof import('./operations.js').refreshOfflineReadiness,
 *   loadLocalAcceptanceHistory: typeof import('./operations.js').loadLocalAcceptanceHistory,
 *   renderKnowledgeWorkspaceShell: typeof import('./knowledge.js').renderKnowledgeWorkspaceShell,
 *   loadKnowledge: typeof import('./knowledge.js').loadKnowledge,
 *   loadKnowledgeDocuments: typeof import('./knowledge.js').loadKnowledgeDocuments,
 *   loadKnowledgeGraph: typeof import('./knowledge.js').loadKnowledgeGraph,
 *   loadOcrQueue: typeof import('./knowledge.js').loadOcrQueue,
 *   loadRoutingStrategy: typeof import('./security.js').loadRoutingStrategy,
 *   loadSecurityCenter: typeof import('./security.js').loadSecurityCenter,
 *   loadMemory: typeof import('./memory.js').loadMemory,
 *   loadReflection: typeof import('./evolution.js').loadReflection,
 *   loadEvolution: typeof import('./evolution.js').loadEvolution,
 *   loadCompetitionReadiness: typeof import('./evolution.js').loadCompetitionReadiness,
 *   loadSkills: typeof import('./skills.js').loadSkills,
 *   loadFeishuCenter: typeof import('./feishu.js').loadFeishuCenter,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export function useWorkbenchPrompt(kind) {
  usePrompt(WORKBENCH_PROMPTS[kind] || "请描述需要完成的目标和交付物。");
  $("prompt")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function setAutonomyMode(mode) {
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

export function renderWorkbenchTasks(tasks) {
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

export function toggleChatProgress(force) {
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

export function openWorkbenchTask(id) {
  if (id) consoleState.chat.lastTaskId = id;
  setView("tasks");
}

export function projectPromptText(kind) {
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

export function prepareProjectPrompt(kind) {
  const text = projectPromptText(kind);
  usePrompt(text);
  if ($("projectRequestPreview")) $("projectRequestPreview").textContent = text;
  if ($("projectRequestCard")) $("projectRequestCard").classList.add("ready");
  if ($("projectStatus")) $("projectStatus").textContent = "已生成项目请求，可直接发送到对话，或继续修改项目目标。";
}

export function sendPreparedProjectPrompt() {
  const text = $("projectRequestPreview")?.textContent?.trim() || $("prompt")?.value?.trim() || "";
  if (!text || text.includes("点击上方任一项目动作")) {
    if ($("projectStatus")) $("projectStatus").textContent = "请先点击一个项目动作生成请求。";
    return;
  }
  usePrompt(text);
  setView("chat");
  if (!consoleState.chat.busy) featureActions.sendMessage();
}

export function handleProjectFiles(event) {
  featureActions.handlePickedFiles(event);
  const count = event.target.files?.length || 0;
  if ($("projectStatus")) $("projectStatus").textContent = count ? `已添加 ${count} 个项目文件到对话附件。` : "未选择文件。";
}

export function setView(viewName) {
  if (!$("view-" + viewName)) viewName = "chat";
  document.querySelectorAll("button[data-view]").forEach(button => {
    const isActive = button.dataset.view === viewName;
    button.classList.toggle("on", isActive);
    button.setAttribute("aria-current", isActive ? "page" : "false");
  });
  document.querySelectorAll(".view").forEach(view => view.classList.remove("on"));
  const view = $("view-" + viewName);
  if (view) view.classList.add("on");
  if (viewName === "scenes") featureActions.ensureProfessionalBoard();
  $("viewTitle").textContent = (VIEW_META[viewName] || VIEW_META.chat)[0];
  $("viewSub").textContent = (VIEW_META[viewName] || VIEW_META.chat)[1];
  if (location.hash !== "#" + viewName) history.replaceState(null, "", "#" + viewName);
  document.dispatchEvent(new CustomEvent('workspace-view', {detail:viewName}));
  document.body.classList.remove("sidebar-open");
  closeCommandDrawer();
  refreshView(viewName);
}

export function toggleSidebar() {
  if (window.matchMedia("(max-width: 760px)").matches) {
    document.body.classList.remove('sidebar-collapsed');
    document.body.classList.toggle("sidebar-open");
  }
  else document.body.classList.toggle("sidebar-collapsed");
  const collapsed = document.body.classList.contains('sidebar-collapsed');
  const button = document.querySelector('.side-collapse');
  button?.setAttribute('aria-label', collapsed ? '展开侧栏' : '收起侧栏');
  const label = button?.querySelector('.ui-action-label');
  if (label) label.textContent = collapsed ? '展开' : '收起';
}

export function toggleCommandDrawer() {
  const drawer = $("commandDrawer");
  drawer.classList.toggle("on");
  drawer.setAttribute("aria-hidden", drawer.classList.contains("on") ? "false" : "true");
}

export function closeCommandDrawer() {
  const drawer = $("commandDrawer");
  if (!drawer) return;
  drawer.classList.remove("on");
  drawer.setAttribute("aria-hidden", "true");
}

export function openDrawerView(view) {
  setView(view);
  closeCommandDrawer();
}

export function openModelSettings() {
  $("modelSettings").classList.add("on");
  $("modelSettings").setAttribute("aria-hidden", "false");
  loadModelSettings();
}

export function closeModelSettings() {
  $("modelSettings").classList.remove("on");
  $("modelSettings").setAttribute("aria-hidden", "true");
}

export function providerPreset(provider) {
  return {
    deepseek: { model: "deepseek-chat", base_url: "https://api.deepseek.com/v1", label: "API 模式" },
    qwen: { model: "qwen", base_url: "http://127.0.0.1:8000/v1", label: "本地模式" },
    qwen_api: { model: "qwen-plus", base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", label: "API 模式" },
    glm: { model: "glm-4-flash", base_url: "https://open.bigmodel.cn/api/paas/v4", label: "API 模式" },
    mock: { model: "mock", base_url: "", label: "离线模式" }
  }[provider] || { model: "", base_url: "", label: "API 模式" };
}

export function modelModeText(provider) {
  return providerPreset(provider).label;
}

export function applyProviderPreset(force) {
  const provider = $("cfgProvider")?.value || "deepseek";
  const preset = providerPreset(provider);
  if (force || !$("cfgModel").value) $("cfgModel").value = preset.model;
  if (force || !$("cfgBaseUrl").value) $("cfgBaseUrl").value = preset.base_url;
  if ($("modelModeLabel")) $("modelModeLabel").textContent = modelModeText(provider);
}

export async function loadModelSettings() {
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

export async function saveModelSettings() {
  const body = { provider: $("cfgProvider")?.value, model: $("cfgModel")?.value, base_url: $("cfgBaseUrl")?.value, api_key: $("cfgApiKey")?.value };
  await api("/api/config/model", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if ($("cfgStatus")) $("cfgStatus").textContent = "已保存配置";
  if ($("localModelNote")) $("localModelNote").textContent = "Local Qwen 模式只保存端点；需要离线模型时请手动下载/启动。";
  closeModelSettings();
  await featureActions.loadHealth();
}

export function chooseFirstRunModel(provider) {
  const modal = $("modelSettings");
  if (modal) {
    modal.classList.add("on");
    modal.setAttribute("aria-hidden", "false");
  }
  if ($("cfgProvider")) $("cfgProvider").value = provider;
  applyProviderPreset(true);
  if ($("cfgStatus")) $("cfgStatus").textContent = "\u5df2\u9009\u62e9 " + modelModeText(provider);
}

export async function refreshAll() {
  featureActions.ensureProfessionalBoard();
  featureActions.renderKnowledgeWorkspaceShell();
  await Promise.allSettled([featureActions.loadHealth(), featureActions.loadDash(), featureActions.loadRoutingStrategy(), featureActions.loadKnowledge(), featureActions.loadKnowledgeDocuments(), featureActions.loadKnowledgeGraph(), featureActions.loadOcrQueue(), featureActions.loadMemory(), featureActions.loadReflection(), featureActions.loadEvolution(), featureActions.loadCompetitionReadiness(), featureActions.loadSkills(), featureActions.loadTools(), featureActions.loadToolExecutions(), featureActions.loadTasks(), featureActions.loadBenchmarks(), featureActions.loadCapabilities(), featureActions.loadSecurityCenter(), featureActions.loadOps(), featureActions.refreshOfflineReadiness(), featureActions.loadLocalAcceptanceHistory()]);
  if (window.loadRuntimeRecords) window.loadRuntimeRecords();
}

export async function refreshView(viewName) {
  const common = [featureActions.loadHealth(), featureActions.loadRoutingStrategy()];
  const viewLoads = {
    chat: [featureActions.loadTasks()],
    search: [],
    knowledge: [featureActions.loadKnowledge(), featureActions.loadKnowledgeDocuments(), featureActions.loadKnowledgeGraph(), featureActions.loadOcrQueue()],
    projects: [featureActions.loadKnowledgeDocuments()],
    dash: [featureActions.loadDash(), featureActions.refreshOfflineReadiness(), featureActions.loadLocalAcceptanceHistory()],
    memory: [featureActions.loadMemory()],
    reflection: [featureActions.loadReflection()],
    evolution: [featureActions.loadEvolution(), featureActions.loadCompetitionReadiness()],
    skills: [featureActions.loadSkills()],
    tools: [featureActions.loadTools(), featureActions.loadToolExecutions()],
    tasks: [featureActions.loadTasks()],
    benchmarks: [featureActions.loadBenchmarks()],
    scenes: [featureActions.loadCapabilities()],
    security: [featureActions.loadSecurityCenter()],
    feishu: [featureActions.loadFeishuCenter()],
    ops: [featureActions.loadOps()]
  };
  await Promise.allSettled(common.concat(viewLoads[viewName] || []));
  if (["chat", "tasks"].includes(viewName) && window.loadRuntimeRecords) window.loadRuntimeRecords();
}
