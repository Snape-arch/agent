// evolution behavior for the ClawOS workbench.
import { $, api, consoleState, esc, statusBadge, table } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   loadTasks: typeof import('./tasks.js').loadTasks,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export function renderLastTools() {
  const target = $("lastTools");
  if (!target) return;
  const route = consoleState.tasks.lastRoutingStrategy
    ? `<div class="item"><b>场景路由 · ${esc(consoleState.tasks.lastRoutingStrategy.scenario || "general")}</b><span>${esc(consoleState.tasks.lastRoutingStrategy.mode || "")} · ${esc(consoleState.tasks.lastRoutingStrategy.model_profile || "balanced")} · 允许 ${Number(consoleState.tasks.lastRoutingStrategy.allowed_tools?.length || 0)} 个工具</span></div>`
    : "";
  const tools = consoleState.chat.lastToolCalls.length ? consoleState.chat.lastToolCalls.map(tool => `<div class="item"><b>${esc(tool.name || "tool")}</b><span>${esc(JSON.stringify(tool.result || {}).slice(0, 180))}</span></div>`).join("") : '<div class="item"><span>暂无工具调用</span></div>';
  target.innerHTML = route + tools;
}

export function renderLastReflection(reflection) {
  const target = $("lastReflection");
  if (!target) return;
  const card = reflection.card || {};
  target.innerHTML = `<div class="item"><b>${esc(card.outcome || "反思")}</b><span>${esc(card.task || "最近任务")}</span><span>${esc(card.lesson || "已写入 MemoryOS")}</span></div>`;
}

export async function loadReflection() {
  if (!$("reflectionTable")) return;
  try {
    const cards = await api("/api/reflection/list?limit=50");
    $("reflectionTable").innerHTML = table(["任务", "结果", "经验"], (cards.cards || []).map(card => [card.task || "", card.outcome || "", card.lesson || card.root_cause || ""]));
  } catch (error) { $("reflectionTable").textContent = "反思记录暂时无法读取：" + error.message; }
  const improvements = await api("/api/reflection/improvements?limit=50").catch(() => ({ items: [] }));
  if ($("reflectionReviewTable")) $("reflectionReviewTable").innerHTML = table(["ID", "状态", "建议", "操作"], (improvements.items || improvements.improvements || []).map(item => [item.id, item.status || "", item.proposal || item.summary || "", { html: `<button class="secondary" onclick="transitionReflection(${Number(item.id)},'reviewed')">审查</button> <button class="secondary" onclick="validateReflection(${Number(item.id)})">验证</button> <button class="secondary" onclick="publishReflection(${Number(item.id)})">发布</button> <button class="secondary" onclick="rollbackReflection(${Number(item.id)})">回滚</button>` }]));
}

export async function triggerReflection() { await api("/api/reflection/trigger", { method: "POST" }).catch(() => ({})); await loadReflection(); }

export async function transitionReflection(id, status) { await api(`/api/reflection/improvements/${id}/transition`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) }).catch(() => ({})); await loadReflection(); }

export async function validateReflection(id) { await transitionReflection(id, "validated"); }

export async function publishReflection(id) { await transitionReflection(id, "published"); }

export async function rollbackReflection(id) { await transitionReflection(id, "rolled_back"); }

export function evolutionActions(run) {
  const id = Number(run.id);
  const status = String(run.status || "");
  if (run.stale_baseline) return '<span>策略基线已变更，请创建新候选并重新验证</span>';
  const canShadow = status === "validated";
  const canCanary = status === "shadow" || status === "canary";
  const canActivate = status === "canary";
  const evidenceReady = Boolean(run.paired_quality_evidence?.passed);
  return [
    status === "candidate" ? `<button class="secondary" onclick="benchmarkEvolutionRun(${id})">运行回归</button>` : "",
    canShadow ? `<button class="secondary" onclick="shadowEvolutionRun(${id})">Shadow</button>` : "",
    canCanary ? `<button class="secondary" ${evidenceReady ? "" : 'disabled title="尚缺本阶段成对任务证据"'} onclick="canaryEvolutionRun(${id})">灰度</button>` : "",
    canActivate ? `<button class="primary" ${evidenceReady ? "" : 'disabled title="尚缺灰度阶段的新任务证据"'} onclick="activateEvolutionRun(${id})">激活</button>` : "",
    run.owns_active_policy ? `<button class="secondary" onclick="rollbackEvolutionRun(${id})">回滚</button>` : "",
    `<button class="secondary" onclick="snapshotEvolutionQuality(${id})">质量快照</button>`
  ].filter(Boolean).join(" ");
}

export async function loadEvolution() {
  if (!$("evolutionRunTable")) return;
  const data = await api("/api/self-evolution/board").catch(() => ({ runs: [], quality_snapshot: {} }));
  const runs = data.runs || [];
  if ($("evolutionScore")) $("evolutionScore").textContent = `当前有效策略 ${data.active_count || 0} · 基线失效候选 ${data.stale_count || 0} · 保留回归、影子与灰度门禁`;
  const quality = data.quality_snapshot || {};
  if ($("evolutionQualityTable")) {
    $("evolutionQualityTable").innerHTML = table(["Signal", "Value"], Object.keys(quality).map(key => [key, quality[key]]));
  }
  $("evolutionRunTable").innerHTML = table(
    ["ID", "目标", "阶段", "流量", "门禁", "成对证据", "结论", "操作"],
    runs.map(run => [
      run.id,
      `${run.target_type}/${run.target_key}`,
      { html: statusBadge(run.effective_stage || run.release_stage || run.status) },
      `${run.traffic_percent || 0}%`,
      { html: statusBadge((run.gate_result || {}).passed ? "passed" : run.status === "candidate" ? "pending" : "failed") },
      `${run.paired_quality_evidence?.matched_task_count || 0} 个任务 · ${run.paired_quality_evidence?.passed ? "本阶段通过" : "等待或阻止晋级"}`,
      run.conclusion || "",
      { html: evolutionActions(run) }
    ])
  );
  await loadEvolutionExperiments();
  const selected = runs[0] || {};
  const checks = (selected.gate_result || {}).checks || [];
  if ($("evolutionGateTable")) {
    $("evolutionGateTable").innerHTML = table(
      ["Run", "Benchmark", "Metric", "Baseline", "Candidate", "Result"],
      checks.map(check => [selected.id || "", check.benchmark, check.metric, check.baseline, check.candidate, { html: statusBadge(check.passed ? "passed" : "failed") }])
    );
  }
}

export async function loadCompetitionReadiness() {
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

export async function exportCompetitionReadiness() {
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

export async function queueEvolutionRun() {
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
  await Promise.allSettled([loadEvolution(), featureActions.loadTasks()]);
}

export async function shadowEvolutionRun(id) {
  const data = await api(`/api/self-evolution/runs/${id}/publish`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console" }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}

export async function canaryEvolutionRun(id) {
  const data = await api(`/api/self-evolution/runs/${id}/canary`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ traffic_percent: 10, actor_id: "console" }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}

export async function activateEvolutionRun(id) {
  const data = await api(`/api/self-evolution/runs/${id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console", reason: "console activation after shadow/canary review", confirmed: true }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}

export async function searchEvolutionCandidates() {
  const status = $("evolutionSearchStatus");
  try {
    const request = {target_type: $("evoTargetType").value, target_key: $("evoTargetKey").value || "default",
      baseline_payload: JSON.parse($("evoBaselinePayload").value || "{}"), mine_reflections: true};
    status.textContent = "正在生成候选…";
    const data = await api("/api/self-evolution/candidates", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(request)});
    consoleState.evolution.evolutionCandidateSearch = {request, candidates: data.candidates || []};
    $("evolutionCandidateGrid").innerHTML = consoleState.evolution.evolutionCandidateSearch.candidates.map((candidate, index) =>
      `<article class="evolution-candidate-card"><h3>${esc(candidate.name)}</h3><p>${esc(candidate.hypothesis)} · ${Number(candidate.evidence?.reflection_count || 0)} 条失败反思</p><p>候选 ${esc(candidate.payload_digest.slice(0,12))} · 效果待验证</p><details><summary>检查配置差异</summary><pre>${esc(JSON.stringify(candidate.payload,null,2))}</pre></details><button class="secondary" onclick="queueSearchedCandidate(${index})">提名并运行回归</button></article>`).join("");
    status.textContent = `${data.candidates?.length || 0} 个有界候选；仅配置提议，尚未验证质量提升。`;
  } catch (err) { status.textContent = "候选生成失败：" + err.message; }
}

export async function queueSearchedCandidate(index) {
  const snapshot = consoleState.evolution.evolutionCandidateSearch;
  if (!snapshot?.candidates[index]) return;
  try {
    const data = await api("/api/self-evolution/runs", {method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({...snapshot.request, mine_reflections:false, candidate_payload:snapshot.candidates[index].payload, auto_queue:true, actor_id:"console"})});
    $("evolutionSearchStatus").textContent = `候选 #${data.run.id} 已排队；后台回归通过后进入影子阶段。`;
    await loadEvolution();
  } catch (err) { $("evolutionSearchStatus").textContent = "提名失败：" + err.message; }
}

export async function loadEvolutionExperiments() {
  const generation = ++consoleState.evolution.evolutionExperimentLoadGeneration;
  const target = $("evolutionExperimentTable");
  if (!target) return;
  try {
    const data = await api("/api/self-evolution/experiments");
    if (generation !== consoleState.evolution.evolutionExperimentLoadGeneration) return;
    target.innerHTML = table(["实验", "目标", "状态", "任务 / 候选", "搜索 / 留出组", "离线结论", "操作"], (data.experiments || []).map(item => {
      const report = item.report || {};
      const id = Number(item.id);
      const actions = [`<button class="secondary" onclick="exportEvolutionExperiment(${id})">下载证据</button>`];
      const job = item.job || {};
      if (item.status === "frozen" || item.status === "paused" || job.recoverable) actions.unshift(`<button class="primary" onclick="replayEvolutionExperiment(${id})">${item.status === 'frozen' ? '成对回放' : '继续回放'}</button>`);
      if (item.status === "running") actions.unshift(`<button class="secondary" onclick="controlEvolutionExperiment(${id},'pause')">暂停</button>`);
      if (['frozen','running','paused'].includes(item.status)) actions.push(`<button class="secondary" onclick="controlEvolutionExperiment(${id},'cancel')">取消实验</button>`);
      if (item.status === 'completed') actions.push(`<button class="secondary" onclick="selectEvolutionReview(${id})">准备盲评</button>`);
      if (report.eligible_for_regression_queue) actions.unshift(`<button class="secondary" onclick="nominateEvolutionExperiment(${id})">提名候选</button>`);
      return [id, `${item.target_type}/${item.target_key}`, `${item.status} · ${job.checkpoint_count || 0} 个检查点${job.recoverable ? ' · 租约过期，可恢复' : ''}`, `${item.case_count} / ${item.candidate_count}`,
        `${report.search_groups ?? "—"} / ${report.holdout_groups ?? "—"}`,
        item.stale_evidence ? "源码或策略基线已变更；需新实验" : report.eligible_for_regression_queue ? "可提名；仍需回归和线上证据" : report.error || (item.status === "completed" ? "未通过；检查下载证据" : "等待回放"), {html:actions.join(" ")}];
    }));
  } catch (err) { $("evolutionExperimentStatus").textContent = "实验加载失败：" + err.message; }
}

export async function freezeEvolutionExperiment() {
  const status = $("evolutionExperimentStatus");
  const file = $("evolutionExperimentFile").files[0];
  if (!file) { status.textContent = "请先选择审核后的任务与资料 JSON。"; return; }
  if (file.size > 8 * 1024 * 1024) { status.textContent = "文件超过 8MiB。"; return; }
  try {
    const data = JSON.parse(await file.text());
    status.textContent = "正在冻结任务、资料与分组…";
    const result = await api("/api/self-evolution/experiments", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
    status.textContent = `实验 #${result.experiment.id} 已冻结，摘要 ${result.experiment.definition_digest.slice(0,12)}。`;
    await loadEvolutionExperiments();
  } catch (err) { status.textContent = "冻结失败：" + err.message; }
}

export async function replayEvolutionExperiment(id) {
  const status = $("evolutionExperimentStatus");
  const poll = setInterval(() => loadEvolutionExperiments(), 4000);
  try {
    status.textContent = `实验 #${id} 正在回放；检索使用隔离资料库，工具路由只计算合同。`;
    const data = await api(`/api/self-evolution/experiments/${id}/replay`, {method:"POST"});
    status.textContent = data.experiment.report.eligible_for_regression_queue ? `实验 #${id} 留出验证通过，可提名候选。` : `实验 #${id} 验证未通过，下载证据查看阻止原因。`;
    await loadEvolutionExperiments();
  } catch (err) { status.textContent = "回放未完成：" + err.message; await loadEvolutionExperiments(); }
  finally { clearInterval(poll); }
}

export async function controlEvolutionExperiment(id, action) {
  try {
    await api(`/api/self-evolution/experiments/${id}/control`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    $('evolutionExperimentStatus').textContent = action === 'pause' ? `实验 #${id} 已暂停，已保存的检查点可恢复。` : `实验 #${id} 已取消；留出题使用记录保留。`;
    await loadEvolutionExperiments();
  } catch (err) { $('evolutionExperimentStatus').textContent = '操作未完成：' + err.message; }
}

export function selectEvolutionReview(id) {
  $('evolutionReviewId').value = id;
  $('evolutionReviewResult').innerHTML = '';
  $('evolutionReviewId').focus();
  $('evolutionReviewStatus').textContent = `已选择实验 #${id}。可捕获主模型回答，或上传绑定摘要的外部成对输出。`;
  loadEvolutionCapture();
}

export async function importEvolutionReview(kind) {
  const status = $('evolutionReviewStatus');
  try {
    const id = Number($('evolutionReviewId').value), file = $('evolutionReviewFile').files[0];
    if (!Number.isInteger(id) || id < 1 || !file) throw Error('请选择实验并上传 JSON 文件。');
    if (file.size > 8*1024*1024) throw Error('文件超过 8MiB。');
    const endpoint = kind === 'outputs' ? 'review-outputs' : 'reviews';
    const data = await api(`/api/self-evolution/experiments/${id}/${endpoint}`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(JSON.parse(await file.text()))});
    status.textContent = kind === 'outputs' ? `输出已冻结，共 ${data.packet.entries.length} 题。可下载盲评包交给审核者。` : `已收录 ${data.summary.reviewer_count} 位具名审核者；${data.summary.reported_review_passed ? '报告评分通过，身份与模型执行仍待验证' : '尚未通过，检查样本、分歧和严重错误'}。`;
    if (data.summary) renderEvolutionReviewSummary(data.summary);
    else $('evolutionReviewResult').innerHTML = '';
  } catch (err) { status.textContent = '导入未完成：' + err.message; }
}

export function renderEvolutionReviewSummary(summary) {
  const authenticated = Number(summary.authenticated_reviewer_count || 0) > 0;
  const segments = (authenticated ? summary.authenticated_reviewed_gate : summary.reviewed_gate)?.segments || {};
  const rows = Object.entries(segments).map(([name, report]) => {
    const metrics = Object.values(report.metrics || {});
    const count = metrics.length ? Math.min(...metrics.map(item => Number(item.independent_clusters || 0))) : 0;
    const lower = metrics.length ? Math.min(...metrics.map(item => Number(item.confidence_lower || 0))) : 0;
    return [name, count, count < 30 ? '样本不足' : report.passed ? '未见显著退步' : '检测到退步', `${(lower * 100).toFixed(1)} 个百分点`];
  });
  const conflicts = (authenticated ? summary.authenticated_adjudication_required : summary.adjudication_required)?.length || 0;
  const critical = (authenticated ? summary.authenticated_critical_errors : summary.critical_errors)?.length || 0;
  const count = Number(authenticated ? summary.authenticated_reviewer_count : summary.reviewer_count);
  const passed = authenticated ? summary.authenticated_review_passed : summary.reported_review_passed;
  const state = passed ? '评分报告通过' : count < 2 ? '等待第二位审核者' : conflicts || critical ? '需要人工复核' : '任务类别门禁未通过';
  const provenance = summary.provider_execution_verified ? '应用已捕获主模型调用凭据' : '外部输出，模型执行未验证';
  $('evolutionReviewResult').innerHTML = `<div class="evolution-review-summary"><h3>${esc(state)}</h3><p>${esc(provenance)}；${authenticated ? '评审已绑定授权会话' : '评分为自报名称'}。真人独立性与专业资格仍待核验；当前报告评分不计入线上发布证据。</p><div class="evolution-review-metrics"><div><strong>${count || 0}</strong><span>${authenticated ? '已认证会话评审者' : '具名审核者'}</span></div><div><strong>${Number(summary.case_count || 0)}</strong><span>成对留出题</span></div><div><strong>${conflicts}</strong><span>需复核的分歧</span></div><div><strong>${critical}</strong><span>严重错误标记</span></div></div><p>当前评分快照已裁决 ${Number(summary.authenticated_resolved_entries || 0)} 题；新增评审会使旧裁决失效，原始记录保留。</p><h3>任务类别验收</h3><p>每类至少 30 个独立任务组；置信下界低于 −2 个百分点会阻止通过。</p><div class="evolution-review-gates" role="region" aria-label="任务类别评分" tabindex="0"><table class="table">${table(['任务类别','独立任务组','结论','提升置信下界'],rows)}</table></div><details><summary>原始评分门禁数据</summary><pre tabindex="0" aria-label="原始评审数据">${esc(JSON.stringify(summary,null,2))}</pre></details></div>`;
}

export function evolutionReviewId(){const id=Number($('evolutionReviewId').value);if(!Number.isSafeInteger(id)||id<1)throw Error('请选择实验。');return id;}

export async function loadEvolutionCapture(){
  try{const data=await api(`/api/self-evolution/experiments/${evolutionReviewId()}/model-capture`),tokens=Number($('evolutionCaptureTokens').value);
    $('evolutionCaptureStatus').textContent=`计划 ${data.plan.calls} 次调用 · 最大 ${data.plan.calls*tokens} 个输出 token · 状态 ${data.capture.status} · 已保存 ${data.capture.saved_answers} 个答案${data.capture.recoverable?' · 租约已过期，可显式继续':''}。`;
  }catch(error){$('evolutionCaptureStatus').textContent='预算读取未完成：'+error.message;}
}

export async function startEvolutionCapture(){
  const button=$('evolutionCaptureStart');let timer;
  try{const id=evolutionReviewId();button.disabled=true;$('evolutionCaptureStatus').textContent='捕获中，部分回答会逐条保存…';
    timer=setInterval(loadEvolutionCapture,3000);
    const data=await api(`/api/self-evolution/experiments/${id}/model-capture`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_calls:Number($('evolutionCaptureCalls').value),max_tokens:Number($('evolutionCaptureTokens').value),timeout:Number($('evolutionCaptureTimeout').value)})});
    $('evolutionReviewStatus').textContent=`模型回答已捕获并冻结，共 ${data.packet.entries.length} 题。可授权会话用户开始盲评。`;
  }catch(error){$('evolutionReviewStatus').textContent='捕获未完成：'+error.message;}
  finally{clearInterval(timer);button.disabled=false;loadEvolutionCapture();}
}

export async function pauseEvolutionCapture(){try{await api(`/api/self-evolution/experiments/${evolutionReviewId()}/model-capture/pause`,{method:'POST'});await loadEvolutionCapture();}catch(error){$('evolutionCaptureStatus').textContent='暂停未完成：'+error.message;}}

export async function exportEvolutionReceipts(){try{const id=evolutionReviewId(),data=await api(`/api/self-evolution/experiments/${id}/model-receipts`);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download=`evolution-model-receipts-${id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){$('evolutionCaptureStatus').textContent='凭据导出未完成：'+error.message;}}

export async function loadEvolutionReviewUsers(){try{const data=await api('/api/self-evolution/review-users');$('evolutionReviewUser').replaceChildren(...data.users.map(user=>{const option=document.createElement('option');option.value=user.id;option.textContent=`${user.name} · ${user.id.slice(0,8)}`;return option;}));$('evolutionGrantStatus').textContent=data.users.length?'已加载会话用户，请核对人员并选择实验角色。':'尚无协作会话用户，请先通过文档协作邀请加入。';}catch(error){$('evolutionGrantStatus').textContent=error.message;}}

export async function grantEvolutionReview(){try{const user=$('evolutionReviewUser').value;if(!user)throw Error('请选择会话用户。');await api(`/api/self-evolution/experiments/${evolutionReviewId()}/review-grants`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:user,role:$('evolutionReviewRole').value})});$('evolutionGrantStatus').textContent='实验授权已保存；既有评分与裁决记录保留。';}catch(error){$('evolutionGrantStatus').textContent='授权未完成：'+error.message;}}

export async function copyEvolutionReviewLink(){try{const url=new URL(`/evolution-review?experiment=${evolutionReviewId()}`,location.origin).href;await navigator.clipboard.writeText(url);$('evolutionGrantStatus').textContent='评审链接已复制。协作者需在已登录协作会话的浏览器打开。';}catch(error){$('evolutionGrantStatus').textContent='复制未完成：'+error.message;}}

export async function loadEvolutionReviewSummary(){try{const data=await api(`/api/self-evolution/experiments/${evolutionReviewId()}/review/summary`);renderEvolutionReviewSummary(data.summary);}catch(error){$('evolutionReviewStatus').textContent='结果读取未完成：'+error.message;}}

export async function exportEvolutionReview(kind) {
  try {
    const id = Number($('evolutionReviewId').value);
    if (!Number.isInteger(id) || id < 1) throw Error('请选择实验。');
    const data = await api(`/api/self-evolution/experiments/${id}/review/${kind}`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data[kind],null,2)],{type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = `evolution-review-${id}-${kind}.json`; link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    $('evolutionReviewStatus').textContent = kind === 'packet' ? '盲评包已导出，包含匿名 A/B 答案与正文摘要。' : '评审证据已导出，包含原始评分、分歧与来源绑定。';
  } catch (err) { $('evolutionReviewStatus').textContent = '导出未完成：' + err.message; }
}

export async function nominateEvolutionExperiment(id) {
  try {
    const data = await api(`/api/self-evolution/experiments/${id}/nominate`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({actor_id:"console"})});
    $("evolutionExperimentStatus").textContent = `候选 #${data.run.id} 已提名，请运行回归；离线回放不计入影子／灰度样本。`;
    await loadEvolution();
  } catch (err) { $("evolutionExperimentStatus").textContent = "提名失败：" + err.message; }
}

export async function exportEvolutionExperiment(id) {
  try {
    const data = await api(`/api/self-evolution/experiments/${id}`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data.experiment, null, 2)], {type:"application/json"}));
    const link = document.createElement("a"); link.href = url; link.download = `evolution-experiment-${id}.json`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) { $("evolutionExperimentStatus").textContent = "证据下载失败：" + err.message; }
}

export async function benchmarkEvolutionRun(id) {
  try {
    $("evolutionExperimentStatus").textContent = `候选 #${id} 正在运行隔离回归…`;
    const data = await api(`/api/self-evolution/runs/${id}/evaluate`, {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
    $("evolutionExperimentStatus").textContent = `候选 #${id}：${data.run.status}；仍需本阶段成对任务证据。`;
    await loadEvolution();
  } catch (err) { $("evolutionExperimentStatus").textContent = "回归未完成：" + err.message; }
}

export async function rollbackEvolutionRun(id) {
  try {
    await api(`/api/self-evolution/runs/${id}/rollback`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true,actor_id:'console'})});
    await loadEvolution();
  } catch (err) { alert('回滚未执行：' + err.message); }
}

export async function snapshotEvolutionQuality(id) {
  const data = await api(`/api/self-evolution/runs/${id}/quality-snapshot`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor_id: "console" }) });
  if ($("evolutionResult")) $("evolutionResult").textContent = JSON.stringify(data, null, 2);
  await loadEvolution();
}
