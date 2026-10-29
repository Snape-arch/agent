/* Research discovery UI: untrusted provider strings are always text nodes. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let state = null, offset = 0, digestId = '', loading = false, busy = false;
  const pageSize = 20;
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
  for (const [id, delta] of [['watch-prev', -pageSize], ['watch-next', pageSize]]) $(id).addEventListener('click', async () => {
    if (loading) return; loading = true; const old = offset; offset = Math.max(0, offset + delta);
    try { await loadFeed(); } catch (error) { offset = old; notice(error.message); } finally { loading = false; }
  });
  refresh();
  setInterval(() => {
    if (!document.hidden && !busy && !document.activeElement?.closest('#watch-subscriptions,#watch-notifications,#watch-digests,#watch-feed,#watch-filter')) refresh(true, true);
  }, 30000);
})();
