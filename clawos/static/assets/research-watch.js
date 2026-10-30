/* Research discovery UI: untrusted provider strings are always text nodes. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let state = null, offset = 0, digestId = '', loading = false, busy = false;
  const pageSize = 20;
  const selected = new Set();
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function when(epoch) {
    return epoch ? new Date(epoch * 1000).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false}) : '尚无';
  }
  function notice(text) { $('notice').textContent = text; }
  async function api(path = '', data) {
    const response = await fetch('/api/research/watch' + path, {
      credentials: 'same-origin', headers: data === undefined ? {} : {'Content-Type': 'application/json'},
      method: data === undefined ? 'GET' : 'POST', body: data === undefined ? undefined : JSON.stringify(data)
    });
    let value;
    try { value = await response.json(); } catch (_) { throw new Error('服务响应异常，请稍后重试。'); }
    if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '请求未成功。');
    return value;
  }
  function button(label, action) {
    const b = el('button', label); b.type = 'button';
    b.addEventListener('click', async () => {
      if (busy) return;
      busy = true; b.disabled = true;
      try { await action(); } catch (error) { notice(error.message); }
      finally { busy = false; b.disabled = false; }
    });
    return b;
  }
  function link(label, url) {
    try {
      const target = new URL(url);
      if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password) throw new Error();
      const a = el('a', label); a.href = target.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
    } catch (_) { return el('span', label); }
  }
  function renderSubscriptions() {
    const root = $('watch-subscriptions'); root.replaceChildren();
    const filter = $('watch-filter'), selected = filter.value;
    filter.replaceChildren(new Option('全部方向', ''));
    state.subscriptions.forEach(sub => {
      filter.add(new Option(sub.name, sub.id));
      const card = el('article', undefined, 'watch-sub'); card.append(el('h3', sub.name));
      card.append(el('div', sub.query, 'watch-meta'));
      card.append(el('div', `${sub.enabled ? '自动采集' : '已暂停'} · 每 ${sub.interval_hours} 小时`, 'watch-meta'));
      sub.jobs.forEach(job => {
        const names = {pending: '等待检查', collecting: '采集中', backlog: '分页积压，尚未完成窗口', idle: '本轮窗口完成', error: '来源请求失败，将重试'};
        const info = el('div', undefined, 'watch-job' + (job.last_error ? ' error' : ''));
        let status = sub.enabled ? names[job.status] || job.status : '已暂停';
        if (job.status === 'collecting' && job.lease_until < state.server_time) status = '原任务租约已到期，等待接管';
        info.append(el('strong', `${state.sources[job.source].name} · ${status}`));
        info.append(el('div', `最近成功响应：${when(job.last_success)}`));
        info.append(el('div', `窗口已完成至：${when(job.watermark)}`));
        if (sub.enabled) info.append(el('div', `下次检查：${when(job.next_due)}${job.next_due <= state.server_time ? '（等待调度）' : ''}`));
        info.append(el('div', `累计读取 ${job.scanned} 条 · 新发现 ${job.new_count} 篇`));
        if (job.last_error) info.append(el('div', `错误类型：${job.last_error}；失败不推进采集窗口。`));
        card.append(info);
      });
      const actions = el('div', undefined, 'watch-actions');
      if (sub.enabled) actions.append(button('检查更新', async () => {
        await api(`/subscriptions/${sub.id}/collect`, {}); notice('已安排检查；来源失败退避与进行中的任务仍有效。'); await refresh(false);
      }));
      actions.append(button(sub.enabled ? '暂停' : '恢复', async () => {
        await api(`/subscriptions/${sub.id}/${sub.enabled ? 'pause' : 'resume'}`, {}); await refresh(false);
      }));
      actions.append(button('删除订阅', async () => {
        if (!window.confirm('删除此订阅？已形成的日报和来源快照会保留。')) return;
        await api(`/subscriptions/${sub.id}/delete`, {}); offset = 0; digestId = ''; await refresh(true);
      }));
      card.append(actions); root.append(card);
    });
    if (!state.subscriptions.length) root.append(el('p', '还没有订阅。先设置一个具体研究问题。', 'muted'));
    if (state.subscriptions.some(s => s.id === selected)) filter.value = selected;
  }
  function paperCard(item) {
    const p = item.paper, card = el('article', undefined, 'watch-paper');
    const selectLabel = el('label', undefined, 'watch-check'), check = el('input'); check.type = 'checkbox'; check.checked = selected.has(item.paper_id);
    check.addEventListener('change', () => { if (check.checked) selected.add(item.paper_id); else selected.delete(item.paper_id); selectionText(); });
    selectLabel.append(check, document.createTextNode('纳入综述：' + p.title)); card.append(selectLabel);
    card.append(el('div', `${item.subscription_name} · ${when(item.discovered)} 发现`, 'watch-meta'));
    if (item.subscriptions && item.subscriptions.length > 1) card.append(el('div', '同时属于：' + item.subscriptions.map(s => s.name).join('、'), 'watch-meta'));
    const h = el('h3'); h.append(link(p.title, p.url)); card.append(h);
    if (p.source === 'arxiv') card.append(el('span', '预印本 · 同行评审状态未核验', 'watch-tag preprint'));
    item.classification.forEach(c => card.append(el('span', c.name + (c.review_required ? ' · 待复核' : ' · 人工确认'), 'watch-tag')));
    card.append(el('div', `${p.authors.slice(0, 4).join('、') || '作者未提供'} · 发表/投稿：${p.published || '未知'} · ${p.source}`, 'watch-meta'));
    card.append(el('blockquote', item.summary.text)); card.append(el('p', item.summary.boundary, 'watch-meta'));
    const evidence = el('details', undefined, 'watch-evidence'); evidence.append(el('summary', '查看摘录依据与归类原因'));
    evidence.append(el('div', `依据字段：${item.summary.basis === 'abstract' ? '来源摘要' : '来源标题'}；字符位置 ${item.summary.evidence.start}–${item.summary.evidence.end}；采集于 ${when(item.captured)}`));
    evidence.append(el('div', '来源快照摘要：')); evidence.append(el('code', item.summary.evidence.content_sha256));
    evidence.append(el('div', p.doi ? `DOI：${p.doi}` : p.arxiv_id ? `arXiv：${p.arxiv_id}` : '来源未提供稳定文献标识'));
    evidence.append(el('div', '论文ID（用于全文绑定）：' + item.paper_id));
    item.classification.forEach(c => evidence.append(el('div', c.method === 'manual' ? `${c.name}：由用户修正。` : `${c.name}：${c.evidence.map(e => `${e.term} 命中 ${e.field}`).join('；') || '未命中设置的方向关键词。'}`)));
    const source = el('a', '打开完整元数据快照'); source.href = '/api/research/watch/snapshots/' + encodeURIComponent(item.snapshot_id); source.target = '_blank'; source.rel = 'noopener'; evidence.append(source);
    card.append(evidence);
    const sub = state.subscriptions.find(s => s.id === item.subscription_id);
    if (sub) {
      const edit = el('details', undefined, 'watch-evidence'); edit.append(el('summary', '修正归类'));
      const form = el('form', undefined, 'watch-classification');
      const fieldset = el('fieldset'); fieldset.append(el('legend', '选择这篇论文所属方向'));
      [...new Set(sub.directions.map(d => d.name).concat('待归类'))].forEach(name => {
        const label = el('label'), input = el('input'); input.type = 'checkbox'; input.name = 'label'; input.value = name;
        input.checked = item.classification.some(c => c.name === name); label.append(input, document.createTextNode(name)); fieldset.append(label);
      });
      form.append(fieldset); const save = el('button', '保存归类'); save.type = 'submit'; form.append(save);
      form.addEventListener('submit', async event => {
        event.preventDefault(); save.disabled = true;
        try { await api(`/classifications/${item.subscription_id}/${item.paper_id}`, {labels: new FormData(form).getAll('label')}); notice('归类已保存。'); await loadFeed(); }
        catch (error) { notice(error.message); } finally { save.disabled = false; }
      }); edit.append(form); card.append(edit);
    }
    return card;
  }
  async function loadFeed() {
    const query = `?offset=${offset}&limit=${pageSize}`;
    const data = await api(digestId ? `/digests/${digestId}${query}` : `/feed${query}&subscription_id=${encodeURIComponent($('watch-filter').value)}`);
    $('watch-feed-heading').textContent = digestId ? `${data.digest.day} · 发现日报` : '最新发现';
    $('watch-feed-boundary').textContent = digestId ? data.boundary : '按本系统发现时间排序；不等于论文发表时间。自动归类需要复核。';
    $('watch-feed').replaceChildren(...data.items.map(paperCard));
    if (!data.items.length) $('watch-feed').append(el('p', '尚无发现。采集状态与来源错误会显示在订阅卡片中；没有结果不代表该领域没有新论文。', 'muted'));
    $('watch-prev').disabled = offset === 0; $('watch-next').disabled = data.items.length < pageSize;
    $('watch-page').textContent = `第 ${offset / pageSize + 1} 页`;
  }
  function renderMessages() {
    $('watch-unread').textContent = `${state.unread} 条未读`;
    const root = $('watch-notifications'); root.replaceChildren();
    state.notifications.forEach(n => {
      const row = el('div', undefined, 'watch-message');
      const sub = state.subscriptions.find(s => s.id === n.subscription_id);
      row.append(el('div', `${n.read_at ? '已读' : '未读'} · ${sub ? sub.name : '已删除订阅'} 新发现 ${n.new_count} 篇 · ${when(n.created)}`));
      row.append(button('查看日报', async () => {
        digestId = n.digest_id; offset = 0; await loadFeed();
        await api(`/notifications/${n.id}/read`, {}); await refresh(false);
        $('watch-feed-heading').scrollIntoView({behavior: 'smooth', block: 'start'});
      })); root.append(row);
    });
    if (!state.notifications.length) root.append(el('p', '有新发现后，会在这里通知你。', 'muted'));
    const digests = $('watch-digests'); digests.replaceChildren();
    state.digests.forEach(d => { const row = el('div', undefined, 'watch-message'); row.append(button(`${d.day} · ${d.paper_count} 篇`, async () => { digestId = d.id; offset = 0; await loadFeed(); $('watch-feed-heading').scrollIntoView({behavior: 'smooth'}); })); digests.append(row); });
    if (!state.digests.length) digests.append(el('p', '首次发现后自动形成当日清单。', 'muted'));
  }
  async function refresh(feed = true, quiet = false) {
    if (loading) return;
    loading = true;
    try {
      state = await api();
      $('watch-runtime').textContent = state.worker.running ? '自动检查已运行 · 日报时区：北京时间' : '自动检查未运行；当前可查看历史。新代码需正常启动服务后启用。';
      if (state.worker.fixture) $('watch-runtime').textContent = '独立验收预览 · 人工夹具数据，不代表真实科研结果。';
      if (state.worker.last_error) $('watch-runtime').textContent += ` · 调度异常：${state.worker.last_error}`;
      renderSubscriptions(); renderMessages(); if (feed) await loadFeed();
    } catch (error) { if (!quiet) notice(error.message); else $('watch-runtime').textContent = '连接中断，历史界面保留；自动采集状态暂不可确认。'; }
    finally { loading = false; }
  }
  $('watch-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, b = form.querySelector('button'); b.disabled = true;
    try {
      const values = new FormData(form);
      const directions = values.get('directions').split(/\r?\n/).filter(s => s.trim()).map(line => {
        const parts = line.split(/[:：]/); if (parts.length < 2) throw new Error('归类格式应为“方向名称: 关键词, 关键词”。');
        return {name: parts.shift().trim(), terms: parts.join(':').split(/[,，]/).map(t => t.trim()).filter(Boolean)};
      });
      await api('/subscriptions', {name: values.get('name'), query: values.get('query'), interval_hours: Number(values.get('interval_hours')), sources: values.getAll('sources'), directions});
      notice('订阅已创建。后台将开始采集，来源失败会保留原因并自动重试。'); form.reset(); offset = 0; digestId = ''; await refresh();
    } catch (error) { notice(error.message); } finally { b.disabled = false; }
  });
  $('watch-refresh').addEventListener('click', () => refresh());
  $('watch-filter').addEventListener('change', () => { digestId = ''; offset = 0; loadFeed().catch(e => notice(e.message)); });
  function selectionText() { $('synthesis-selection').textContent = selected.size ? `已勾选 ${selected.size} 篇（跨页面保留）；生成时仍需属于当前筛选范围。` : '未勾选时使用当前筛选订阅中的全部论文，最多100篇，不会静默截断。'; }
  async function synthesisHistory() {
    const data = await api('/syntheses'), control = $('synthesis-history'), value = control.value;
    control.replaceChildren(new Option('选择已保存的综述', ''));
    data.items.forEach(r => control.add(new Option(`${r.title} · ${when(r.created)}`, r.id))); control.value = value;
  }
  function download(name, text, type) {
    const url = URL.createObjectURL(new Blob([text], {type})), a = el('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function renderSynthesis(value) {
    const r = value.report, root = $('synthesis-report'); root.replaceChildren(el('h3', r.title), el('p', r.boundary, 'watch-policy'));
    root.append(el('p', `${r.coverage.papers} 篇文献 · ${r.coverage.with_abstract} 篇有摘要 · ${r.coverage.full_text_bound} 篇绑定解析全文 · 最多展示200条关系候选`, 'watch-meta'));
    const actions = el('div', undefined, 'watch-actions');
    actions.append(button('导出 Markdown', async () => { const out = await api(`/syntheses/${r.id}/export`); download('research-overview.md', out.markdown, 'text/markdown;charset=utf-8'); }));
    actions.append(button('导出含依据 JSON', async () => { const out = await api(`/syntheses/${r.id}/export`); download('research-evidence.json', JSON.stringify(out.data, null, 2), 'application/json'); })); root.append(actions);
    const labels = {problem:'研究问题',method:'方法路线',evidence:'评测依据',finding:'作者报告的发现',limitation:'局限与缺口'};
    for (const group of r.groups) {
      const section = el('section', undefined, 'watch-overview-group'); section.append(el('h3', `${group.name} · ${group.paper_ids.length} 篇`));
      for (const [key, label] of Object.entries(labels)) {
        const detail = el('details'); detail.append(el('summary', `${label} · ${group.sections[key].length} 条依据`));
        if (!group.sections[key].length) detail.append(el('p', '所选来源未提取到该项；不表示领域没有相关研究或论文不存在该内容。', 'muted'));
        for (const claim of group.sections[key]) {
          const paper = r.papers.find(p => p.id === claim.paper_id), evidence = claim.evidence;
          const article = el('article', undefined, 'watch-synthesis-claim'); article.append(el('blockquote', claim.text));
          article.append(el('div', `${paper.title} · ${evidence.basis === 'parsed_full_text' ? '解析全文' : '来源摘要'}`, 'watch-meta'));
          const location = el('details', undefined, 'watch-evidence'); location.append(el('summary', '查看来源定位'), el('p', `${evidence.field}[${evidence.start}:${evidence.end}] · ${evidence.snapshot_id || evidence.citation || ''}`), el('code', evidence.sha256)); article.append(location); detail.append(article);
        } section.append(detail);
      }
      section.append(el('p', `缺项待补证据：${group.gaps.length} 篇。未提取到局限不等于没有局限。`, 'watch-meta')); root.append(section);
    }
    const timeline = el('section'); timeline.append(el('h3', '发表／投稿时间线'));
    const list = el('ol', undefined, 'watch-timeline');
    for (const t of r.timeline) list.append(el('li', `${t.date.value || '日期未知'}（${{day:'日',month:'月',year:'年',unknown:'未知'}[t.date.precision]}精度） · ${t.title}`)); timeline.append(list); root.append(timeline);
    const relations = el('section'); relations.append(el('h3', '研究关联与复核'), el('p', '方向重叠仅生成相关候选。确认扩展、比较或冲突需要两端原文证据和人工理由；确认记录仍是人工判断。', 'muted'));
    if (!r.edges.length) relations.append(el('p', '尚无方向重叠候选；这不表示论文间没有学术关联。'));
    for (const edge of r.edges) {
      const left = r.papers.find(p => p.id === edge.source), right = r.papers.find(p => p.id === edge.target), review = value.reviews?.[edge.id];
      const detail = el('details'); detail.append(el('summary', `${left.title} ↔ ${right.title} · ${review ? (review.status === 'confirmed' ? '人工确认' : '已拒绝') : '待复核'}`)); detail.append(el('p', edge.reason));
      const form = el('form'), type = el('select'), status = el('select');
      for (const [k, text] of Object.entries({related:'相关工作',compares:'比较',extends:'扩展',contradicts:'结论冲突'})) type.add(new Option(text, k));
      type.value = review?.kind || 'related'; status.add(new Option('确认关系', 'confirmed')); status.add(new Option('拒绝候选', 'rejected')); status.value = review?.status || 'confirmed';
      function field(name, control) { const label = el('label', name); label.append(control); form.append(label); }
      field('关系类型', type); field('复核结论', status);
      const direction = el('select'); direction.add(new Option('左文 → 右文（扩展时：右文扩展左文）', 'forward')); direction.add(new Option('右文 → 左文（扩展时：左文扩展右文）', 'reverse')); direction.value = review?.direction || 'forward'; field('关系方向（不按发表时间自动推断）', direction);
      const reason = el('textarea'); reason.required = true; reason.minLength = 8; reason.maxLength = 1000; reason.value = review?.reason || ''; field('复核理由（至少8字）', reason);
      const quotes = [];
      for (const paper of [left, right]) {
        const source = el('select'), quote = el('textarea'); quote.maxLength = 1200;
        paper.sources.forEach((s,i) => source.add(new Option(`${s.basis === 'parsed_full_text' ? '解析全文：' + s.citation : '来源摘要'}（${s.text.length}字）`, String(i))));
        const previous = review?.evidence.find(e => e.paper_id === paper.id); source.value = String(previous?.source_index || 0); quote.value = previous?.quote || '';
        field(paper.title + ' · 证据来源', source);
        const preview = el('details'); preview.append(el('summary', '展开冻结来源文本'), el('pre', paper.sources[Number(source.value)].text, 'watch-source-text'));
        source.addEventListener('change', () => preview.querySelector('pre').textContent = paper.sources[Number(source.value)].text); form.append(preview);
        field('粘贴此来源中的连续原文（确认时至少12字）', quote); quotes.push({paper,source,quote});
      }
      const save = el('button', '保存复核'); save.type = 'submit'; form.append(save);
      form.addEventListener('submit', async event => {
        event.preventDefault(); save.disabled = true;
        try { await api(`/syntheses/${r.id}/relations/${edge.id}`, {kind:type.value,status:status.value,direction:direction.value,reason:reason.value,version:review?.version || 0,
          evidence:quotes.filter(q => q.quote.value).map(q => ({paper_id:q.paper.id,source_index:Number(q.source.value),quote:q.quote.value}))});
          renderSynthesis(await api(`/syntheses/${r.id}`)); notice('人工关系复核已保存，未修改原综述快照。');
        } catch (error) { notice(error.message); } finally { save.disabled = false; }
      }); detail.append(form); relations.append(detail);
    } root.append(relations);
  }
  $('synthesis-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, save = form.querySelector('button[type="submit"]'); save.disabled = true;
    try {
      const values = new FormData(form), documents = {};
      for (const line of values.get('documents').split(/\r?\n/).filter(s => s.trim())) {
        const match = line.trim().match(/^([a-f0-9]{32})\s*=\s*([1-9]\d*)$/); if (!match) throw new Error('全文绑定格式应为“论文ID = 文档ID”。'); documents[match[1]] = Number(match[2]);
      }
      const result = await api('/syntheses', {title:values.get('title'),subscription_id:$('watch-filter').value,paper_ids:[...selected],documents});
      renderSynthesis(result); await synthesisHistory(); $('synthesis-history').value = result.id; notice('综述已冻结保存，可查看时间线、补充关系复核并导出。');
    } catch (error) { notice(error.message); } finally { save.disabled = false; }
  });
  $('synthesis-clear').addEventListener('click', () => { selected.clear(); selectionText(); loadFeed().catch(e => notice(e.message)); });
  $('synthesis-history').addEventListener('change', async event => { if (!event.target.value) return; try { renderSynthesis(await api(`/syntheses/${event.target.value}`)); } catch (error) { notice(error.message); } });
  synthesisHistory().catch(e => notice(e.message));
  for (const [id, delta] of [['watch-prev', -pageSize], ['watch-next', pageSize]]) $(id).addEventListener('click', async () => {
    if (loading) return; loading = true; const old = offset; offset = Math.max(0, offset + delta);
    try { await loadFeed(); } catch (error) { offset = old; notice(error.message); } finally { loading = false; }
  });
  refresh();
  setInterval(() => {
    if (!document.hidden && !busy && !document.activeElement?.closest('#watch-subscriptions,#watch-notifications,#watch-digests,#watch-feed,#watch-filter')) refresh(true, true);
  }, 30000);
})();
