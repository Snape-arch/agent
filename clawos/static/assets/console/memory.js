// memory behavior for the ClawOS workbench.
import { $, api, table } from './core.js';
export async function saveMemory() {
  const body = { memory_type: $("memType").value, key: $("memKey").value, value: $("memValue").value, source: $("memSource").value || "manual" };
  await api("/api/memory/items", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  await loadMemory();
}

export async function loadMemory() {
  const target = $("memoryTable");
  if (!target) return;
  try {
    const data = await api("/api/memory/items?include_disabled=true&limit=80");
    target.innerHTML = table(["类型", "键", "内容", "状态", "操作"], (data.items || []).map(item => [
      item.memory_type,
      item.key,
      item.value,
      item.enabled ? "启用" : "停用",
      { html: `<button class="secondary" onclick="toggleMemory(${Number(item.id)},${item.enabled ? "false" : "true"})">${item.enabled ? "停用" : "启用"}</button>` }
    ]));
    const reviews = await api("/api/memory/reviews?limit=50").catch(() => ({ reviews: [] }));
    if ($("memoryReviewTable")) $("memoryReviewTable").innerHTML = table(["ID", "类型", "内容", "状态", "操作"], (reviews.reviews || []).map(item => [item.id, item.memory_type || "", item.proposed_value || "", item.status || "", { html: `<button class="secondary" onclick="resolveMemoryReview(${Number(item.id)},'approved')">通过</button> <button class="secondary" onclick="resolveMemoryReview(${Number(item.id)},'rejected')">拒绝</button>` }]));
  } catch (err) {
    target.innerHTML = table(["类型", "键", "内容", "状态", "操作"], []);
  }
}

export async function searchMemory() {
  const query = $("memQuery").value.trim();
  if (!query) return;
  const data = await api("/api/memory/search?q=" + encodeURIComponent(query));
  if ($("searchTable")) $("searchTable").innerHTML = table(["类型", "键", "内容"], (data.results || data.items || []).map(item => [item.memory_type, item.key, item.value]));
}

export async function toggleMemory(id, enabled) {
  await api(`/api/memory/items/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
  await loadMemory();
}

export async function resolveMemoryReview(id, status) {
  await api(`/api/memory/reviews/${id}/resolve`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
  await loadMemory();
}
