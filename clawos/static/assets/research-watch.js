/* Research discovery UI: untrusted provider strings are always text nodes. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let state = null, offset = 0, digestId = '', loading = false, busy = false;
  const pageSize = 20;
  const selected = new Set();
  let aiPoll = null, aiReport = '';
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
    const metadataPanel = el('details', undefined, 'watch-evidence'); metadataPanel.append(el('summary','引用与版本元数据'));
    const metadataView = el('div');
    async function loadMetadata() {
      const data = await api(`/papers/${item.paper_id}/metadata`); metadataView.replaceChildren();
      if (data.omitted_artifacts) metadataView.append(el('p',`另有 ${data.omitted_artifacts} 个记录未在此视图展示。`));
      for (const record of data.records) {
        const version = record.arxiv_id ? record.arxiv_id + (record.arxiv_version ? 'v'+record.arxiv_version : '（版本号未知）') : record.doi;
        metadataView.append(el('p',`${record.source} · ${version} · 更新：${record.updated || '未知'} · 本次采集：${when(record.captured)}`,'watch-meta'));
        metadataView.append(el('p',record.references_available ? `已收录 ${record.references.length} 条参考文献；其中 ${record.references.filter(r => r.doi).length} 条有DOI${record.references_truncated ? '，来源或本地收录不完整' : ''}。` : '参考文献元数据缺失或不可用，不能认为没有引用。','watch-meta'));
      }
    }
    metadataPanel.append(button('查看已采集的元数据',loadMetadata),metadataView);
    const metadataForm=el('form'), metadataSource=el('select'), version=el('input'); metadataSource.add(new Option('Crossref · DOI参考文献与版本关系','crossref'));metadataSource.add(new Option('arXiv · 指定修订版或最新元数据','arxiv'));metadataSource.value=p.arxiv_id ? 'arxiv' : 'crossref';
    metadataSource.setAttribute('aria-label','元数据来源');const sourceLabel=el('label','元数据来源');sourceLabel.append(metadataSource);metadataForm.append(sourceLabel);
    const versionLabel=el('label','arXiv版本号（留空获取最新；不会补造未采集版本）');version.type='number';version.min='1';version.max='9999';version.step='1';versionLabel.append(version);metadataForm.append(versionLabel);versionLabel.hidden=metadataSource.value!=='arxiv';metadataSource.addEventListener('change',()=>versionLabel.hidden=metadataSource.value!=='arxiv');
    const refreshMeta=el('button','刷新此论文元数据');refreshMeta.type='submit';metadataForm.append(refreshMeta);
    metadataForm.addEventListener('submit',async event=>{
      event.preventDefault();refreshMeta.disabled=true;
      try { const result=await api(`/papers/${item.paper_id}/metadata`,{source:metadataSource.value,version:metadataSource.value==='arxiv' && version.value ? Number(version.value) : null});
        if (result.paper_id!==item.paper_id) { if (selected.delete(item.paper_id)) selected.add(result.paper_id);await loadFeed(); }
        else await loadMetadata(); notice(result.boundary);
      } catch (error) { notice(error.message); } finally { refreshMeta.disabled=false; }
    });metadataPanel.append(el('p','只按已有DOI/arXiv标识查询，不下载全文、不按同名猜测。旧日报与综述不会改写。','muted'),metadataForm);card.append(metadataPanel);
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
    $('watch-unread').textContent = `${state.unread+(state.review_updates?.unread || 0)} 条未读`;
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
    for (const n of state.review_updates?.items || []) {
      const row=el('div',undefined,'watch-message');row.append(el('div',`${n.read_at ? '已读' : '未读'} · 综述证据更新 · ${n.title} · ${when(n.created)}`));
      row.append(button('查看综述变化',async()=>{await openReport(n.report_id);await renderDelta(n.update_id,$('synthesis-report').querySelector('.watch-update-delta'));await api(`/update-notifications/${n.id}/read`,{});await refresh(false);}));root.append(row);
    }
    if (!state.notifications.length && !state.review_updates?.items.length) root.append(el('p', '有新发现或综述证据更新后，会在这里通知你。', 'muted'));
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
      if (state.worker.public_metadata_preview) $('watch-runtime').textContent = '独立公开元数据预览 · 来源记录已保存，不代表生产部署或学术质量认证。';
      if (state.worker.controlled_clock_replay) $('watch-runtime').textContent = '独立公开语料回放 · 调度使用受控时钟，页面可出现测试时间；没有实际等待6小时，不代表实时采集、模型或长期运行验收。';
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
  async function openReport(id) {
    renderSynthesis(await api(`/syntheses/${id}`));await synthesisHistory();$('synthesis-history').value=id;
    $('synthesis-report').scrollIntoView({behavior:'smooth',block:'start'});
  }
  function batches(root,items,render,size=20) {
    let shown=0;const list=el('div'),more=el('button','显示更多变化');more.type='button';
    function append(){for(const item of items.slice(shown,shown+size))list.append(render(item));shown+=size;more.hidden=shown>=items.length;}
    more.addEventListener('click',append);append();root.append(list,more);
  }
  async function renderDelta(uid,root) {
    const value=await api(`/updates/${uid}`),d=value.delta;root.replaceChildren(el('h4','这次更新了什么'),el('p',d.boundary,'watch-policy'));
    const c=d.counts;root.append(el('p',`新增 ${c.added_papers} 篇 · 当前范围未包含 ${c.removed_papers} 篇 · 归并 ${c.merged_papers || 0} 个原标识 · ${c.changed_papers} 篇资料变化 · 新增 ${c.added_excerpts} 条分类摘录 · ${c.added_relations} 条新增来源关系`,'watch-update-counts'));
    root.append(el('p',`比较时间：${when(value.created)}。分类摘录可能重复命中不同栏目，计数不是独立学术发现数量。`,'watch-meta'));
    const actions=el('div',undefined,'watch-actions');actions.append(button('查看原综述',()=>openReport(value.base_id)),button('查看新综述',()=>openReport(value.report_id)),
      button('导出更新 Markdown',async()=>{const out=await api(`/updates/${uid}/export`);download('research-update.md',out.markdown,'text/markdown;charset=utf-8');}),
      button('导出更新依据 JSON',async()=>{const out=await api(`/updates/${uid}/export`);download('research-update.json',JSON.stringify(out.data,null,2),'application/json');}));root.append(actions);
    function quote(claim){const e=claim.evidence,box=el('div');box.append(el('blockquote',claim.text),el('p',`原文位置 ${e.start}–${e.end} · ${e.basis}`,'watch-meta'),el('code','SHA256 '+e.sha256));if(e.snapshot_id){const a=el('a','查看该版本来源快照');a.href='/api/research/watch/snapshots/'+encodeURIComponent(e.snapshot_id);a.target='_blank';a.rel='noopener';const p=el('p');p.append(a);box.append(p);}return box;}
    function lazy(title,build){const details=el('details');details.append(el('summary',title));let built=false;details.addEventListener('toggle',()=>{if(details.open&&!built){built=true;build(details);}});return details;}
    const labels={problem:'研究问题',method:'方法',evidence:'评测',finding:'作者报告的发现',limitation:'局限'};
    for(const [key,label] of [['added','新增论文'],['removed','当前范围未包含的原论文']]){
      root.append(el('h4',label+` · ${d[key].length}`));batches(root,d[key],p=>lazy(p.title,box=>{box.append(el('p',p.doi || p.arxiv_id || p.paper_id,'watch-meta'));for(const [kind,claims] of Object.entries(p.sections)){if(claims.length)box.append(el('h5',labels[kind] || kind));for(const claim of claims)box.append(quote(claim));}}));
    }
    root.append(el('h4','原论文的证据与资料变化'));
    for(const p of d.merged || [])root.append(el('p',`${p.before.title} → ${p.after.title}：${p.boundary}`,'watch-meta'));
    batches(root,d.papers,p=>lazy(p.after.title,box=>{
      const fields={title:'标题',doi:'DOI',arxiv_id:'arXiv标识',date:'发表时间',groups:'归类方向',authors:'作者',categories:'来源分类'};
      box.append(el('p',`${p.text_changed ? '原文资料变化；' : ''}${p.bibliography_changed ? '引用或版本元数据变化；' : ''}${p.fields.map(k=>fields[k] || k).join('、')}`,'watch-meta'));
      for(const k of p.fields)box.append(el('p',`${fields[k] || k}：${JSON.stringify(p.before[k==='date' ? 'date' : k])} → ${JSON.stringify(p.after[k==='date' ? 'date' : k])}`));
      for(const [kind,section] of Object.entries(p.sections)){for(const [key,label] of [['added','新版本新增摘录'],['removed','原版本摘录（本版未提取）']]){if(section[key].length)box.append(el('h5',`${labels[kind] || kind} · ${label}`));for(const claim of section[key])box.append(quote(claim));}}
      if(!Object.values(p.sections).some(s=>s.added.length||s.removed.length))box.append(el('p','分类摘录没有变化；不据此推断学术结论改变。','muted'));
    }));
    for(const [key,label] of [['added','新增来源关系'],['removed','本版未包含的原来源关系']]){
      root.append(lazy(label+` · ${d.relations[key].length}`,group=>{batches(group,d.relations[key],e=>lazy(`${e.source_label || e.source} → ${e.target_label || e.target}`,box=>{box.append(el('p',e.kind+' · '+e.boundary,'watch-meta'));for(const ref of [...e.evidence,...(e.prior_evidence ? [e.prior_evidence] : [])]){const a=el('a','来源字段 '+ref.field);a.href='/api/research/watch/snapshots/'+encodeURIComponent(ref.snapshot_id);a.target='_blank';a.rel='noopener';const row=el('p');row.append(a);box.append(row);}}),40);}));
    }
    if(JSON.stringify(d.coverage_before)!==JSON.stringify(d.coverage_after))root.append(lazy('来源覆盖与预算变化',box=>{box.append(el('p','来源缺失或预算省略可能改变关系范围，不能当作撤稿或反证。','muted'),el('pre',JSON.stringify({before:d.coverage_before,after:d.coverage_after},null,2),'watch-source-text'));}));
  }
  function renderUpdateControls(r,root) {
    const section=el('section',undefined,'watch-updates'),controls=el('div'),delta=el('div',undefined,'watch-update-delta');
    section.append(el('h3','持续更新这份综述'),el('p','只检查已经采集到的资料，不额外联网采集或自动调用模型。已绑定本地全文会重新取证；旧AI正文和人工关系复核保留在原版本。','muted'),controls,delta);root.append(section);
    async function load(){
      const value=await api(`/syntheses/${r.id}/updates`),t=value.track;controls.replaceChildren();
      controls.append(button('刷新更新状态',load));
      if(value.previous)controls.append(button('与上一版比较',()=>renderDelta(value.previous.id,delta)));
      if(value.next)controls.append(button('查看下一版本',()=>openReport(value.next.report_id)));
      if(r.lineage)controls.append(el('p',`第 ${r.lineage.generation} 版 · 上一版本保留`,'watch-meta'),button('查看初始综述',()=>openReport(r.lineage.root_report_id)));
      if(t && t.head_id!==r.id){controls.append(el('p','这是历史版本。'),button('打开最新综述',()=>openReport(t.head_id)));}
      else {
        const mode=r.selection?.mode || 'explicit';controls.append(el('p',mode==='explicit' ? '范围：原来明确选择的论文；不自动扩大选篇。' : mode==='subscription' ? '范围：原订阅，包含后来发现的论文。' : '范围：你的全部有效订阅，包含后来发现的论文。','watch-meta'));
        controls.append(el('p',`最近检查：${when(t?.checked)}${t?.enabled ? ' · 下次检查：'+when(t.next_due) : ' · 自动检查未开启'}${t?.last_error ? ' · 检查失败：'+t.last_error+'；原版本保留，15分钟后重试。' : ''}`,'watch-meta'));
        const check=button('检查并生成更新版本',async()=>{const out=await api(`/syntheses/${r.id}/updates/check`,{version:t?.version || 0});if(out.changed){await openReport(out.head_id);await renderDelta(out.update.id,$('synthesis-report').querySelector('.watch-update-delta'));notice('已保存新版本和证据差异，原综述保留。');await refresh(false);}else{notice('当前采集资料没有变化，未生成重复版本或通知。');await load();}});controls.append(check);
        const form=el('form'),enabled=el('input');enabled.type='checkbox';enabled.checked=!!t?.enabled;const label=el('label',undefined,'watch-check');label.append(enabled,document.createTextNode('自动检查综述更新'));form.append(label);
        const interval=el('select');interval.setAttribute('aria-label','综述检查频率');for(const [n,name] of [[6,'每6小时'],[12,'每12小时'],[24,'每天'],[48,'每2天'],[168,'每周']]){const o=el('option',name);o.value=n;interval.append(o);}interval.value=t?.interval_hours || 6;form.append(interval);
        form.append(button('保存更新设置',async()=>{await api(`/syntheses/${r.id}/updates/settings`,{enabled:enabled.checked,interval_hours:Number(interval.value),version:t?.version || 0});await load();notice('更新设置已保存。仅应用运行期间检查；来源延迟和采集积压仍影响发现时间。');}));controls.append(form);
      }
      if(value.updates.length)controls.append(el('p','最近50次版本变化；旧版本可沿前后版本继续查看。','watch-meta'));
      for(const u of value.updates)controls.append(button('查看版本变化 · '+when(u.created),()=>renderDelta(u.id,delta)));
    }
    load().catch(e=>controls.replaceChildren(el('p',e.message,'muted')));
  }
  function renderSynthesis(value) {
    const r = value.report, root = $('synthesis-report'); root.replaceChildren(el('h3', r.title), el('p', r.boundary, 'watch-policy'));
    if (aiPoll) clearTimeout(aiPoll); aiReport = r.id;
    root.append(el('p', `${r.coverage.papers} 篇文献 · ${r.coverage.with_abstract} 篇有摘要 · ${r.coverage.full_text_bound} 篇绑定解析全文 · 最多展示200条关系候选`, 'watch-meta'));
    const actions = el('div', undefined, 'watch-actions');
    actions.append(button('导出 Markdown', async () => { const out = await api(`/syntheses/${r.id}/export`); download('research-overview.md', out.markdown, 'text/markdown;charset=utf-8'); }));
    actions.append(button('导出含依据 JSON', async () => { const out = await api(`/syntheses/${r.id}/export`); download('research-evidence.json', JSON.stringify(out.data, null, 2), 'application/json'); })); root.append(actions);
    actions.append(button('评审这份证据报告',()=>window.dispatchEvent(new CustomEvent('research-review-source',{detail:{kind:'report',report_id:r.id}}))));
    renderUpdateControls(r,root);
    const graph=r.bibliography_graph;
    if (graph) {
      const section=el('section',undefined,'watch-bibliography');section.append(el('h3','来源引用与版本网络'),el('p',graph.boundary,'muted'));
      const coverage=graph.coverage;section.append(el('p',`${coverage.observed_artifacts} 个已采集文献形态 · ${coverage.edges} 条来源关系 · ${coverage.unresolved_reference_occurrences} 次引用指向范围外DOI · ${coverage.references_without_doi} 条参考文献缺DOI`,'watch-meta'));
      if (coverage.omitted_edges || coverage.omitted_artifacts) section.append(el('p',`当前预算未展示：${coverage.omitted_edges} 条关系、${coverage.omitted_artifacts} 个文献形态。`,'watch-meta'));
      section.append(el('p',`缺少参考文献元数据的记录：${coverage.missing_reference_metadata_records}；不完整参考文献记录：${coverage.partial_reference_records}。缺失不能当作零引用。`,'watch-meta'));
      if (coverage.partial_relation_records) section.append(el('p',`${coverage.partial_relation_records} 个记录的版本关联超出采集预算，未完整展示。`,'watch-meta'));
      for (const family of graph.families) section.append(el('p',`arXiv ${family.arxiv_id} · 已采集版本：${family.observed_versions.map(v=>'v'+v).join(' → ')}`));
      const nodes=new Map(graph.nodes.map(n=>[n.id,n]));
      const names={cites:'参考文献引用',doi_association:'arXiv元数据DOI关联','is-preprint-of':'预印本 → 出版文献关联','is-version-of':'来源版本关联','is-identical-to':'来源标识同一性声明',observed_revision_order:'已采集修订版顺序'};
      const filterLabel=el('label','关系类型'),filter=el('select');filter.setAttribute('aria-label','关系类型');
      for (const [value,text] of [['all','全部来源关系'],['versions','版本与预印本关联'],['cites','参考文献引用']]) { const option=el('option',text);option.value=value;filter.append(option); }
      filterLabel.append(filter);section.append(filterLabel);
      let shown=0,visibleEdges=graph.edges;const list=el('div'), more=el('button','显示更多关系');more.type='button';
      function appendEdges() {
        for (const edge of visibleEdges.slice(shown,shown+40)) {
          const detail=el('details');const a=nodes.get(edge.source),b=nodes.get(edge.target);
          const nodeLabel=(node,id)=>(node?.title || id)+(node?.version ? ' · v'+node.version : '');
          detail.append(el('summary',`${names[edge.kind] || edge.kind}：${nodeLabel(a,edge.source)} → ${nodeLabel(b,edge.target)}`));
          detail.append(el('p',`${edge.source} → ${edge.target}`,'watch-meta'),el('p',edge.boundary || '来源元数据报告，非独立学术认证。','muted'));
          if (edge.missing_intermediate_count) detail.append(el('p',`中间有 ${edge.missing_intermediate_count} 个版本未采集。`));
          for (const e of [...edge.evidence,...(edge.prior_evidence ? [edge.prior_evidence] : [])]) { const prefix=edge.prior_evidence ? (e===edge.prior_evidence ? '先前版本来源' : '当前版本来源') : '查看来源快照';const a=el('a',`${prefix} · ${e.field}${e.index===null ? '' : '['+e.index+']'}`);a.href='/api/research/watch/snapshots/'+encodeURIComponent(e.snapshot_id);a.target='_blank';a.rel='noopener';const row=el('p');row.append(a);detail.append(row); }
          list.append(detail);
        } shown+=40;more.disabled=shown>=visibleEdges.length;more.hidden=more.disabled;
      }
      filter.addEventListener('change',()=>{ visibleEdges=graph.edges.filter(e=>filter.value==='all' || (filter.value==='cites' ? e.kind==='cites' : e.kind!=='cites'));shown=0;list.replaceChildren();appendEdges();if (!visibleEdges.length) list.append(el('p','当前筛选没有来源关系。','muted')); });
      appendEdges();more.addEventListener('click',appendEdges);section.append(list,more);if (!graph.edges.length) section.append(el('p','当前快照尚无可解析来源关系。可刷新论文元数据后重新生成综述。','muted'));root.append(section);
    }
    const aiSection = el('section', undefined, 'watch-ai-synthesis');
    aiSection.append(el('h3','AI 综合综述'),el('p','使用本地模型综合冻结证据，再校验引用、数值并单独请求模型复核。不进行外部模型回退；正文仍需人工审阅。','muted'));
    const aiStatus = el('p','检查本地模型状态…','watch-meta'), aiOutput = el('div'); aiOutput.setAttribute('aria-live','polite');
    const startAI = button('使用本地模型生成综合综述',async () => {
      const job = await api(`/syntheses/${r.id}/ai`,{confirmed:true}); await showAI(job); notice('AI综合已排队，最多两次模型调用；可取消。');
    }); startAI.disabled = true;
    aiSection.append(aiStatus,startAI,button('重新检查模型状态',async () => renderSynthesis(await api(`/syntheses/${r.id}`))),aiOutput); root.append(aiSection);
    const names = {overview:'核心概览',questions:'核心问题',methods:'方法与分歧',evidence:'实验证据',disagreements:'结论差异',limitations:'局限',next_questions:'值得研究的问题'};
    async function showAI(job) {
      if (aiReport !== r.id) return;
      aiOutput.replaceChildren(el('p',`任务状态：${{queued:'等待模型',running:'生成与复核中',completed:'草稿已形成',failed:'未完成',cancelled:'已取消'}[job.status] || job.status}`));
      if (job.result?.outcome === 'insufficient_evidence') aiOutput.firstChild.textContent = '任务状态：证据不足，未形成正文。';
      if (['queued','running'].includes(job.status)) {
        aiOutput.append(button('取消本次综合',async () => { await api(`/ai/jobs/${job.id}/cancel`,{}); await showAI(await api(`/ai/jobs/${job.id}`)); }));
        if (aiPoll) clearTimeout(aiPoll);
        aiPoll = setTimeout(async () => { try { await showAI(await api(`/ai/jobs/${job.id}`)); } catch (e) { notice(e.message); } },2500);
      }
      if (job.error) aiOutput.append(el('p','失败类型：'+job.error+'。未用规则摘录冒充成功生成。','muted'));
      const result = job.result;
      if (!result || job.status !== 'completed') return;
      if($('notice').textContent.startsWith('AI综合已排队'))notice(result.review_queue?.length ? `综合已完成，${result.review_queue.length} 项主张暂缓，未进入正文。` : '综合草稿已完成，仍需人工复核。');
      aiOutput.append(button(result.review_queue?.length ? '评审暂缓主张与现有正文' : '评审这份AI草稿',()=>window.dispatchEvent(new CustomEvent('research-review-source',{detail:{kind:'ai',report_id:r.id,job_id:job.id}}))));
      aiOutput.append(el('p',result.boundary,'watch-policy'));
      aiOutput.append(el('p',`本次选用 ${result.coverage.selected_excerpts}/${result.coverage.available_excerpts} 条证据，覆盖 ${result.coverage.selected_papers}/${result.coverage.corpus_papers} 篇；${result.excluded.length} 条判断未采用。`,'watch-meta'));
      for (const [key,label] of Object.entries(names)) {
        aiOutput.append(el('h4',label));
        if (!result.sections[key].length) aiOutput.append(el('p','证据不足或未通过检查，留空。','muted'));
        for (const claim of result.sections[key]) {
          const article = el('article'); article.append(el('p',claim.text));
          article.append(el('span',claim.kind === 'inference' ? '研究推断 · 待人工复核' : '模型综合 · 待人工复核','watch-tag'));
          const detail = el('details'); detail.append(el('summary','查看此判断的原文依据'));
          for (const cid of claim.citations) {
            const ref = result.references.find(e => e.id === cid); detail.append(el('p',`${cid} · ${ref.title} · ${ref.evidence.basis === 'parsed_full_text' ? '解析全文' : '摘要'}`),el('blockquote',ref.quote));
            detail.append(el('div',`${ref.evidence.field}[${ref.evidence.start}:${ref.evidence.end}]`,'watch-meta'));
          } article.append(detail); aiOutput.append(article);
        }
      }
      if(result.review_queue?.length){
        const queue=el('section');queue.className='watch-claim-queue';queue.append(el('h4',`暂缓主张 · ${result.review_queue.length} 项（未进入正文）`),el('p','触发风险不等于学术错误。保留原主张与其引用，可送入独立评审；评审不会自动改写原报告。','muted'));
        const reasons={unsupported_quantity:'数值未被本项引用覆盖',missing_or_unknown_citation:'引用缺失或无效',model_uncertain:'模型复核尚不确定',model_unsupported:'模型复核未支持该主张',comparison_requires_two_papers:'比较需要两篇论文的依据'};
        for(const claim of result.review_queue){const detail=el('details');detail.append(el('summary',claim.text));const signals=claim.boundary_audit?.signals || [];detail.append(el('p',signals.map(s=>s.label).join('；') || reasons[claim.reason] || '主张边界仍需人工复核。','watch-meta'));for(const id of claim.evidence_ids){const ref=result.references.find(e=>e.id===id);if(!ref)continue;detail.append(el('p',`${id} · ${ref.title}`),el('blockquote',ref.quote),el('p',`${ref.evidence.field}[${ref.evidence.start}:${ref.evidence.end}]`,'watch-meta'));}if(!claim.evidence_ids.length)detail.append(el('p','没有可定位的有效引用；不能据此确认主张。','muted'));queue.append(detail);}aiOutput.append(queue);
      }
    }
    (async () => {
      try { const status = await api('/ai/status'); if (aiReport !== r.id) return; startAI.disabled = !status.ready; aiStatus.textContent = status.ready ? `本地模型：${status.model || '已配置'} · 每次最多两次调用` : status.reason || '本地模型尚未就绪';
        const jobs = await api(`/syntheses/${r.id}/ai`); if (jobs.items.length) await showAI(jobs.items[0]);
      } catch (error) { aiStatus.textContent = error.message; }
    })();
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
    const relations = el('section'); relations.append(el('h3', '学术关系候选与人工复核'), el('p', '与来源引用、版本网络分开。方向重叠仅生成相关候选。确认扩展、比较或冲突需要两端原文证据和人工理由；确认记录仍是人工判断。', 'muted'));
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
