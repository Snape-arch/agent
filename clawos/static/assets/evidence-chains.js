(function () {
  const byId = (id) => document.getElementById(id);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);

  function ensureSurface() {
    if (byId("realEvidenceChainGrid")) return;
    const anchor = byId("runtimeRecordPanel");
    if (!anchor) return;
    anchor.insertAdjacentHTML("beforebegin", '<section class="real-evidence-section" aria-labelledby="realEvidenceHeading"><div class="real-evidence-head"><div><h2 id="realEvidenceHeading">真实任务证据</h2><p>只展示来源可核验、八阶段完整且通过质量门禁的真实运行。回归 fixture 与 Mock 不计入。</p></div><strong id="realEvidenceScore">0 / 5</strong></div><div class="real-evidence-grid" id="realEvidenceChainGrid" aria-live="polite"></div></section>');
  }

  function emptyCard(slot) {
    return `<article class="real-evidence-card is-empty"><div class="real-evidence-card-top"><span>${escapeHtml(slot.label)}</span><em>等待真实运行</em></div><p>完成真实任务后，这里会显示耗时、返工、门禁、产物哈希与知识沉淀。</p></article>`;
  }

  function verifiedCard(slot) {
    const item = slot.latest || {};
    const stages = item.stages || [];
    const artifacts = item.artifacts || [];
    return `<article class="real-evidence-card is-verified"><div class="real-evidence-card-top"><span>${escapeHtml(slot.label)}</span><em>已核验</em></div><h3>${escapeHtml(item.title || item.run_id)}</h3><div class="real-evidence-meta"><span>${escapeHtml(item.duration_ms || 0)} ms</span><span>${stages.length} / 8 阶段</span><span>${artifacts.length} 个产物</span></div><p>${escapeHtml(item.completed_at || "")}</p></article>`;
  }

  async function loadRealEvidenceChains() {
    ensureSurface();
    const target = byId("realEvidenceChainGrid");
    if (!target) return;
    target.innerHTML = '<div class="real-evidence-loading">正在核验真实运行记录…</div>';
    try {
      const response = await fetch("/api/runtime/evidence-chains", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      target.innerHTML = (data.slots || []).map((slot) => slot.state === "verified" ? verifiedCard(slot) : emptyCard(slot)).join("");
      const score = byId("realEvidenceScore");
      if (score) score.textContent = `${data.verified_count || 0} / ${data.required_count || 5}`;
    } catch (_error) {
      target.innerHTML = '<div class="real-evidence-loading is-error">证据服务暂不可用，未展示任何预制结果。</div>';
    }
  }

  window.loadRealEvidenceChains = loadRealEvidenceChains;
  setTimeout(loadRealEvidenceChains, 0);
})();
