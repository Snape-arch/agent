// security behavior for the ClawOS workbench.
import { $, api, esc, statusBadge, table } from './core.js';
export async function loadRoutingStrategy() {
  const target = $("routingPolicyTable");
  if (!target) return;
  try {
    const data = await api("/api/routing/policy?q=" + encodeURIComponent("科研 网页 文件 项目"));
    target.innerHTML = table(["场景", "分数", "模型策略", "检索", "确认"], (data.candidates || []).slice(0, 6).map(item => [item.scenario, Math.round((item.score || 0) * 100) + "%", item.model_profile || "--", item.retrieval || "--", (item.requires_confirmation || []).join(" / ") || "无需"]));
  } catch (err) {}
}

export async function loadSecurityCenter() {
  const policyEl = $("securityPolicyTable");
  const boundaryEl = $("securityBoundaryTable");
  const auditEl = $("securityAuditTable");
  const grantEl = $("securityGrantTable");
  if (!policyEl && !boundaryEl && !auditEl && !grantEl) return;
  try {
    const checks = await Promise.all(["web_fetch", "shell_exec", "file_write", "git_workspace", "external_api"].map(tool => api("/api/security/policy/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tool, arguments: tool === "web_fetch" ? { url: "https://example.com" } : { path: "./demo.txt", command: "git status" } }) }).then(result => ({ tool, ...result })).catch(err => ({ tool, allowed: false, decision: "error", risk_level: "unknown", reason: err.message }))));
    if (policyEl) policyEl.innerHTML = table(["能力", "决策", "风险", "原因"], checks.map(item => [item.tool, item.decision || String(!!item.allowed), item.risk_level || "unknown", item.reason || item.error || ""]));
    const caps = await api("/api/workspace/capabilities").catch(() => ({ local_file_operations: { allowed_roots: [] } }));
    if (boundaryEl) boundaryEl.innerHTML = table(["边界", "状态", "说明"], [["写入根目录", { html: statusBadge((caps.local_file_operations?.allowed_roots || []).length ? "success" : "failed") }, (caps.local_file_operations?.allowed_roots || []).join(" / ") || "未配置"], ["写操作确认", { html: statusBadge(caps.local_file_operations?.requires_confirmation_for_writes ? "success" : "failed") }, "文件写入、Git、外部动作进入确认流"], ["联网确认", { html: statusBadge("pending") }, "web_fetch 默认中风险确认，内网/localhost 拦截"], ["PDF OCR", { html: statusBadge(caps.document_understanding?.pdf_ocr ? "success" : "pending") }, caps.document_understanding?.pdf_ocr || "未启用"]]);
    const grants = await api("/api/security/policy/grants?include_expired=true").catch(() => ({ grants: [] }));
    if (grantEl) grantEl.innerHTML = table(["工具", "决策", "范围", "过期", "原因", "操作"], (grants.grants || []).map(grant => [grant.tool || "*", grant.decision || "", `${grant.scope_type || "tool"} ${grant.scope_value || ""}`, grant.expires_at || "长期", grant.reason || "", { html: `<button class="secondary" onclick="revokeSecurityGrant('${esc(grant.id || "")}')">撤销</button>` }]));
    const audit = await api("/api/security/audit?limit=80").catch(() => ({ events: [] }));
    if (auditEl) auditEl.innerHTML = table(["动作", "决策", "风险", "主体", "时间"], (audit.events || []).map(item => [item.action || item.tool || "", item.decision || "", item.risk_level || item.risk || "", item.actor_id || item.actor || "", item.created_at || ""]));
  } catch (err) {
    if (policyEl) policyEl.innerHTML = table(["能力", "决策", "风险", "原因"], [["security_center", "error", "unknown", err.message]]);
  }
}

export async function saveSecurityGrant() {
  const body = { tool: $("securityGrantTool")?.value || "*", decision: $("securityGrantDecision")?.value || "confirm", scope_type: $("securityGrantScopeType")?.value || "tool", scope_value: $("securityGrantScopeValue")?.value || "", expires_in_minutes: $("securityGrantMinutes")?.value || "", reason: $("securityGrantReason")?.value || "manual permission grant", created_by: "console" };
  await api("/api/security/policy/grants", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  ["securityGrantScopeValue", "securityGrantMinutes", "securityGrantReason"].forEach(id => {
    if ($(id)) $(id).value = "";
  });
  await loadSecurityCenter();
}

export async function revokeSecurityGrant(id) {
  if (!id) return;
  await api(`/api/security/policy/grants/${encodeURIComponent(id)}`, { method: "DELETE" });
  await loadSecurityCenter();
}
