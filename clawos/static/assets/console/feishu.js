// feishu behavior for the ClawOS workbench.
import { $, api, esc, statusBadge, table } from './core.js';
export async function loadFeishuCenter() {
  if (!$("feishuMessagesTable")) return;
  // §13 resource endpoints: each is a dedicated URL, not an action router.
  const get = (path) => api(path).catch(err => ({ error: err.message }));
  try {
    const [health, messages, summaries, approvals, dispatches, permissions] = await Promise.all([
      get("/api/feishu/health"),
      get("/api/feishu/messages?limit=50"),
      get("/api/feishu/summaries?limit=50"),
      get("/api/feishu/approvals?limit=50"),
      get("/api/feishu/dispatches?limit=50"),
      get('/api/feishu/permissions'),
    ]);
    const cfg = (health && health.config) || {};
    const cli = (health && health.client) || {};
    const populateTargets=()=>{const field=$('feishuTargetId');if(!field)return;const previous=field.value,targets=(permissions.targets||[]).filter(t=>t.type===$('feishuTargetType').value);field.innerHTML=targets.length?'<option value="">请选择白名单目标</option>'+targets.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.id)+'</option>').join(''):'<option value="">此类型尚未配置目标白名单</option>';if(targets.some(t=>t.id===previous))field.value=previous;};
    if($('feishuTargetType'))$('feishuTargetType').onchange=populateTargets;populateTargets();
    if ($('feishuPermissions')) $('feishuPermissions').innerHTML = '<h3>权限链路</h3><div class="feishu-status-scroll"><table class="table">'+table(['环节','状态','依据'],(permissions.checks||[]).map(c=>[c.name,c.ready?'已配置':'待配置',c.detail]))+'</table></div><p class="hint">'+esc(permissions.boundary||permissions.error||'')+'</p>';
    const summaryParam = new URLSearchParams(location.search).get('summary');
    if (summaryParam && /^\d+$/.test(summaryParam) && $('feishuSummaryId')) $('feishuSummaryId').value=summaryParam;
    // P1-2: disable outbound write buttons until the connector is configured.
    window.__feishuCfg = cfg;
    const feishuConfigured = !!(cfg.configured && cfg.live && cfg.live_ready && health.has_client);
    const caBtn = $("feishuCreateApprovalBtn");
    const sendBtn = $("feishuSendBtn");
    if (caBtn) caBtn.disabled = !feishuConfigured;
    if (sendBtn) sendBtn.disabled = !feishuConfigured;
    if ($("feishuHealth")) $("feishuHealth").innerHTML = '<p class="feishu-readiness"><strong>'+esc(cfg.live_ready ? '连接配置已就绪' : '当前仅可创建本地草稿')+'</strong><br>'+esc(cfg.live_ready ? '发送仍需白名单目标和原生审批通过。' : '请先配置应用、审批表单、发起人、审批人和允许发送的目标。')+'</p><details><summary>查看连接配置</summary><div class="feishu-status-scroll"><table class="table">'+table(["项", "值"], [
      ["事件模式(event_mode)", cfg.event_mode || "—"],
      ["实时发送", cfg.live ? "已开启" : "已关闭 · 仅本地草稿"],
      ["配置就绪", cfg.live_ready ? "已配置；平台权限仍需验证" : "配置不完整"],
      ["App 配置", cfg.configured ? "已配置" : "未配置(env)"],
      ["Client 连接", cli.connection || (health && health.has_client ? "已连接" : "无")],
      ["审批定义码", cfg.approval_code_present ? "已配置" : "—"],
      ["审批表单控件", cfg.approval_form_control_present ? "已配置" : "—"],
      ["发起人 open_id", cfg.approval_initiator_present ? "已配置" : "—"],
      ["允许聊天数", cfg.whitelist_chats ?? 0],
      ["允许目标数", cfg.whitelist_target_open_ids ?? 0],
      ["授权审批人数", cfg.approvers ?? 0],
      ["消息留存(天)", cfg.message_retention_days ?? "—"],
    ])+'</table></div></details>';
    if ($("feishuMessagesTable")) $("feishuMessagesTable").innerHTML = (messages && messages.length) ? table(["聊天", "发送者", "类型", "内容", "接收时间", "状态"], (messages || []).map(m => [m.chat_id, m.sender_id, m.message_type, m.text, m.create_time, { html: statusBadge(m.processed_status) }])) : '<tr><td colspan="6" class="empty-state">暂无消息</td></tr>';
    if ($("feishuSummariesTable")) $("feishuSummariesTable").innerHTML = (summaries && summaries.length) ? table(["ID", "主题", "结论数", "行动项数", "来源消息", "状态", "创建时间"], (summaries || []).map(s => [s.id, s.topic, (s.conclusions || []).length, (s.action_items || []).length, (s.source_message_ids || []).join(","), { html: statusBadge(s.status) }, s.created_at])) : '<tr><td colspan="7" class="empty-state">暂无纪要</td></tr>';
    const preview = (approvals || [])[0];
    const draft = Array.isArray(summaries) ? summaries.find(s=>String(s.id)===summaryParam) : null;
    if ($("feishuPreview")) $("feishuPreview").textContent = draft ? ('待审批草稿：'+draft.topic+'\n\n'+(draft.conclusions||[]).map(c=>c.text).join('\n\n')+'\n来源：'+(draft.source_message_ids||[]).join(', ')) : preview ? (preview.body_text || "（空正文）") : "暂无待审批/待发送内容。";
    if ($("feishuApprovalsTable")) $("feishuApprovalsTable").innerHTML = (approvals && approvals.length) ? table(["ID", "目标", "状态", "审批人", "已用", "有效期", "创建时间"], (approvals || []).map(a => {
      const expired = a.expires_at_epoch && a.expires_at_epoch < Math.floor(Date.now() / 1000);
      return [a.id, (a.target_type || "") + ":" + (a.target_id || ""), { html: statusBadge(a.status) }, a.approver_id, { html: statusBadge(a.used ? "used" : "no") }, { html: statusBadge(expired ? "expired" : "valid") }, a.created_at_epoch ? new Date(a.created_at_epoch * 1000).toLocaleString() : ""];
    })) : '<tr><td colspan="7" class="empty-state">暂无审批</td></tr>';
    if ($("feishuDispatchesTable")) $("feishuDispatchesTable").innerHTML = (dispatches && dispatches.length) ? table(["ID", "审批ID", "目标", "状态", "尝试", "飞书消息ID", "API码", "API消息", "追踪ID"], (dispatches || []).map(d => [d.id, d.approval_id, (d.target_type || "") + ":" + (d.target_id || ""), { html: statusBadge(d.status) }, d.attempts, d.feishu_message_id, d.api_code, d.api_msg, d.trace_id])) : '<tr><td colspan="9" class="empty-state">暂无发送回执</td></tr>';
  } catch (err) {
    if ($("feishuHealth")) $("feishuHealth").innerHTML = '<div class="feishu-status-scroll"><table class="table">'+table(["状态", "说明"], [["加载失败", err.message]])+'</table></div>';
  }
}

export async function feishuRequest(method, path, payload) {
  const statusEl = $("feishuActionStatus");
  if (statusEl) statusEl.textContent = "处理中…";
  try {
    const opts = { method };
    if (payload !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(payload);
    }
    const res = await api(path, opts);
    if (statusEl) statusEl.textContent = "成功：" + JSON.stringify(res).slice(0, 240);
    await loadFeishuCenter();
  } catch (err) {
    if (statusEl) statusEl.textContent = "失败：" + err.message;
  }
}

export async function feishuCreateSummary() {
  const ids = ($("feishuMsgIds").value || "").split(",").map(s => s.trim()).filter(Boolean).map(Number);
  await feishuRequest("POST", "/api/feishu/summaries", { message_ids: ids });
}

export async function feishuCreateApproval() {
  const targetType = ($("feishuTargetType").value || "chat").trim();
  const targetId = ($("feishuTargetId").value || "").trim();
  if (!targetId) { alert("请选择白名单内的发送目标；暂无目标时请先配置连接器。"); return; }
  // P1-2: 不再静默提交 confirmed:true；必须人类显式确认。审批人由飞书实例决定，不手填。
  const ok = confirm(
    `确认创建飞书出站审批？\n\n目标：${targetType}:${targetId}\n\n` +
    `创建后须经飞书原生审批通过才会对外发送；目标必须在白名单内，否则会被服务端拒绝（409）。`
  );
  if (!ok) return;
  await feishuRequest("POST", "/api/feishu/approvals", {
    confirmed: true,
    summary_id: Number($("feishuSummaryId").value),
    target_type: targetType,
    target_id: targetId,
  });
}

export async function feishuSyncApproval() {
  const id = Number($("feishuApprovalId").value);
  await feishuRequest("POST", `/api/feishu/approvals/${id}/sync`);
}

export async function feishuSendApproved() {
  const id = Number($("feishuApprovalId").value);
  if (!id) { alert("请填写 approval_id"); return; }
  // P1-2: 发送是真实对外动作，必须人类显式确认；at-most-once，超时记为结果未知且不自动重发。
  const ok = confirm(
    `确认向飞书发送已批准的审批 #${id}？\n\n` +
    `该操作只会执行一次（at-most-once）。若飞书 API 超时，结果将记为“未知”并保留本地回执，不会自动重发。`
  );
  if (!ok) return;
  await feishuRequest("POST", `/api/feishu/approvals/${id}/send`, { confirmed: true });
}
