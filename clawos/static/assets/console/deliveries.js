// deliveries behavior for the ClawOS workbench.
import { $, api, consoleState, table, usePrompt } from './core.js';

let featureActions;

/**
 * Wire feature actions at the console composition root.
 * @param {{
 *   loadKnowledge: typeof import('./knowledge.js').loadKnowledge,
 *   loadKnowledgeGraph: typeof import('./knowledge.js').loadKnowledgeGraph,
 *   setView: typeof import('./shell.js').setView,
 * }} dependencies
 */
export function configure(dependencies) {
  featureActions = dependencies;
}

export function renderEnterpriseDeliveryResult(data) {
  consoleState.deliveries.lastEnterpriseDelivery = data;
  consoleState.deliveries.lastEnterpriseKnowledgeIds = [];
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

export function enterpriseDeliveryPayload() {
  return consoleState.deliveries.lastEnterpriseDelivery?.result || consoleState.deliveries.lastEnterpriseDelivery?.data || consoleState.deliveries.lastEnterpriseDelivery || {};
}

export async function runEnterpriseDeliveryRoom() {
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

export async function saveEnterpriseDeliveryToKnowledge() {
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
  consoleState.deliveries.lastEnterpriseKnowledgeIds = savedIds;
  consoleState.knowledge.knowledgeCategory = "project";
  if ($("knowledgeCategory")) $("knowledgeCategory").value = "project";
  if ($("enterpriseDeliveryStatus")) $("enterpriseDeliveryStatus").textContent = `已保存 ${savedIds.length} 个交付条目到项目知识库`;
  await featureActions.loadKnowledge();
  await featureActions.loadKnowledgeGraph();
  if ($("enterpriseDeliveryResult")) {
    const flow = $("enterpriseDeliveryResult").querySelector(".report-flow");
    if (flow && savedIds.length) {
      flow.querySelector(".report-flow-steps")?.insertAdjacentHTML("beforeend", `<span class="done">已保存 ${savedIds.length} 条</span>`);
    }
  }
}

export function askEnterpriseDeliveryQuestion() {
  const payload = enterpriseDeliveryPayload();
  const title = payload.project_name || $("enterpriseProjectName")?.value || "ClawOS";
  const question = `请基于项目知识库中的 ${title} 企业交付包，模拟评委视角提出 5 个最尖锐问题，并给出有证据的答辩回答。`;
  usePrompt(question);
  featureActions.setView("chat");
}
