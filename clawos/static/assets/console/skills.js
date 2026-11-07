// skills behavior for the ClawOS workbench.
import { $, api, consoleState, esc, table } from './core.js';
export async function loadSkills() {
  if (!$("skillsTable")) return;
  const data = await api("/api/skills").catch(() => ({ skills: [] }));
  consoleState.skills.allSkills = data.skills || data.items || [];
  renderSkillsWorkbench();
  await renderSkillVersionTables();
}

export function renderSkillsWorkbench() {
  const target = $("skillsTable");
  if (!target) return;
  const query = ($("skillQuery")?.value || "").toLowerCase();
  const status = $("skillStatusFilter")?.value || "";
  const category = $("skillCategory")?.value || "";
  const rows = consoleState.skills.allSkills.filter(skill => (!query || JSON.stringify(skill).toLowerCase().includes(query)) && (!status || skill.status === status) && (!category || skill.category === category));
  target.innerHTML = rows.map(skill => `<button class="skill-card ${skill.name === consoleState.skills.selectedSkillName ? "on" : ""}" onclick="selectSkill('${esc(skill.name)}')"><b>${esc(skill.display_name || skill.name)}</b><small>${esc(skill.description || "")}</small><em>${esc(skill.category || "general")} · ${esc(skill.status || "active")}</em></button>`).join("") || '<div class="empty-state">暂无技能</div>';
  if (!consoleState.skills.selectedSkillName && rows[0]) selectSkill(rows[0].name);
}

export function selectSkill(name) {
  consoleState.skills.selectedSkillName = name;
  const skill = consoleState.skills.allSkills.find(item => item.name === name) || {};
  if ($("skillDetail")) $("skillDetail").innerHTML = `<div class="skill-meta"><b>${esc(skill.display_name || skill.name || "技能")}</b><span>${esc(skill.category || "")}</span></div><p>${esc(skill.description || "")}</p><ol class="skill-steps">${(skill.steps || []).map(step => `<li>${esc(step.tool || step.name || "step")}<code>${esc(JSON.stringify(step.args || {}, null, 2))}</code></li>`).join("")}</ol>`;
  renderSkillsWorkbench();
}

export async function runSelectedSkill(planOnly) {
  if (!consoleState.skills.selectedSkillName) return;
  let params = {};
  try { params = JSON.parse($("skillParams")?.value || "{}"); } catch (err) { params = {}; }
  const data = await api("/api/skills/execute", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: consoleState.skills.selectedSkillName, params, plan_only: !!planOnly }) });
  if ($("skillRunResult")) $("skillRunResult").textContent = JSON.stringify(data, null, 2);
  await renderSkillVersionTables();
}

export async function renderSkillVersionTables() {
  const versions = await api("/api/skills/evolution/versions").catch(() => ({ versions: [] }));
  const runs = await api("/api/skills/evolution/runs").catch(() => ({ runs: [] }));
  const reviews = await api("/api/skills/evolution/review-inbox").catch(() => ({ items: [] }));
  consoleState.skills.skillVersions = versions.versions || [];
  consoleState.skills.skillRuns = runs.runs || [];
  consoleState.skills.skillReviews = reviews.items || reviews.reviews || [];
  if ($("skillVersionTable")) $("skillVersionTable").innerHTML = table(["技能", "版本", "状态"], consoleState.skills.skillVersions.map(item => [item.skill_name || item.name || "", item.version || "", item.status || ""]));
  if ($("skillRunTable")) $("skillRunTable").innerHTML = table(["技能", "结果", "时间"], consoleState.skills.skillRuns.map(item => [item.skill_name || item.name || "", item.passed ?? item.status ?? "", item.created_at || ""]));
  if ($("skillReviewTable")) $("skillReviewTable").innerHTML = table(["技能", "状态", "操作"], consoleState.skills.skillReviews.map(item => [item.skill_name || item.name || "", item.status || "", { html: `<button class="secondary" onclick="signSkill(${Number(item.id)})">签名</button> <button class="secondary" onclick="auditSkill(${Number(item.id)})">独立审计</button> <button class="secondary" onclick="canarySkill(${Number(item.id)})">Canary</button> <button class="primary" onclick="promoteSkill(${Number(item.id)})">发布</button> <button class="secondary" onclick="reviewSkill('${esc(item.id || item.skill_name || "")}','needs_changes')">需修改</button>` }]));
}

export async function signSkill(id) { await api(`/api/skills/evolution/versions/${id}/sign`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ signer: "console" }) }).catch(() => ({})); await renderSkillVersionTables(); }

export async function auditSkill(id) { await api(`/api/skills/evolution/versions/${id}/fresh-audit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }).catch(() => ({})); await renderSkillVersionTables(); }

export async function canarySkill(id) { await api(`/api/skills/evolution/versions/${id}/canary`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ percent: 10, actor: "console" }) }).catch(() => ({})); await renderSkillVersionTables(); }

export async function promoteSkill(id) { await api(`/api/skills/evolution/versions/${id}/promote`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ actor: "console", confirmed: true }) }).catch(() => ({})); await renderSkillVersionTables(); }

export async function reviewSkill(id, status) { await api("/api/skills/evolution/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, status }) }).catch(() => ({})); await renderSkillVersionTables(); }
