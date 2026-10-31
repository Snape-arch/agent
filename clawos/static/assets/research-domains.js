/* Curated public literature: lazy loading, literal source text, no DB writes. */
(() => {
  'use strict';
  const root = document.getElementById('domain-library');
  const state = document.getElementById('domain-library-status');
  const trigger = document.getElementById('domain-load');
  const statuses = {covered:'有代表入口', partial:'部分覆盖', gap:'初稿遗漏', out_of_scope:'初稿范围外'};
  const kinds = {reading_order:'阅读顺序', problem_progression:'问题演进', parallel_approaches:'并行路线'};
  const declared = {author_described_simplification:'作者称其为简化形式', author_described_builds_on:'作者称其基于前者', author_described_shared_training:'作者称训练过程相同'};
  const node = (tag, text, cls) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (cls) el.className = cls; return el; };
  async function api(path) {
    const r = await fetch('/api/research/watch/domains' + path, {credentials:'same-origin'});
    const v = await r.json(); if (!r.ok) throw new Error(typeof v.detail === 'string' ? v.detail : '阅读包暂时不可用'); return v;
  }
  function link(label, url) {
    const p = new URL(url); if (p.protocol !== 'https:' || p.username || p.password) return node('span', label);
    const a = node('a', label); a.href = p.href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
  }
  function details(title) { const e = node('details'); e.append(node('summary', title)); return e; }
  function refs(ids, papers) {
    const p = node('p', undefined, 'domain-refs'); p.append(document.createTextNode('参读：'));
    ids.forEach((id, i) => { if (i) p.append(document.createTextNode(' · ')); p.append(link(papers[id].name, papers[id].url)); }); return p;
  }
  function source(e, title) {
    const box = details(title); box.append(node('blockquote', e.quote), link('打开来源', e.source_url));
    box.append(node('p', `捕获：${e.captured} · ${e.field}[${e.start}:${e.end}]`, 'watch-meta'));
    box.append(node('code', '原始来源 SHA256 ' + e.raw_sha256));
    box.append(node('p', '这里只核对原文片段的位置和哈希，不认证中文解释或方法继承。', 'muted')); return box;
  }
  function paper(p) {
    const box = node('article', undefined, 'domain-paper'); box.append(link(p.name, p.url), node('span', p.date + ' · ' + p.version, 'watch-meta'), node('p', p.summary));
    box.append(source(p.evidence, '查看摘要依据')); return box;
  }
  function download(value, domainId, ext) {
    const blob = new Blob([value], {type:ext === 'md' ? 'text/markdown;charset=utf-8' : 'application/json'});
    const url = URL.createObjectURL(blob); const a = node('a'); a.href = url; a.download = 'research-domain-' + domainId + '.' + ext;
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function render(v, root) {
    const d = v.domain, papers = Object.fromEntries([...d.papers,...d.supplements].map(p => [p.id,p]));
    root.replaceChildren(node('p', '阅读准备：' + d.prerequisites.join(' → '), 'domain-prerequisites'));
    root.append(node('h4', '01 · 代表论文与分类'));
    for (const category of d.categories) {
      const group = details(category); d.papers.filter(p => p.category === category).forEach(p => group.append(paper(p))); root.append(group);
    }
    root.append(node('h4', '02 · 阅读与问题链条'), node('p', '箭头表示阅读顺序或问题关联，不代表引用、因果或方法继承。', 'muted'));
    for (const path of d.paths) {
      const p = node('article', undefined, 'domain-path'); p.append(node('strong', path.name + ' · ' + kinds[path.kind]), node('p', path.papers.map(id => papers[id].name).join(path.kind === 'parallel_approaches' ? ' / ' : ' → ')), node('p', path.reason), refs(path.papers, papers)); root.append(p);
    }
    if (d.declared_relations?.length) {
      root.append(node('h4','作者原文明确描述的关系'), node('p','目标论文作者的表述，不等于独立考证或实验复现。','muted'));
      d.declared_relations.forEach(r => { const box = node('article',undefined,'domain-path'); box.append(node('p',papers[r.source].name+' → '+papers[r.target].name+' · '+declared[r.kind]),source(r.evidence,'查看作者原文')); root.append(box); });
    }
    root.append(node('h4', '03 · 冻结初稿'));
    d.overview.forEach(c => { root.append(node('p', c.text), refs(c.papers, papers)); });
    root.append(node('h4', '04 · 外部综述对照'), link(d.survey.title, d.survey.url), node('p', d.survey.venue + ' · DOI ' + d.survey.doi, 'watch-meta'));
    root.append(node('p', d.id === 'diffusion' ? '正式期刊记录已核对；正文对照使用arXiv v15修订版，与期刊原版分开记录。' : '已核对出版记录及开放全文。', 'muted'));
    root.append(node('p', '下面评估初稿的结构覆盖，判断由助手拟定。对照后补篇不会回填初稿成绩，也不计算学术准确率。', 'muted'));
    const table = node('table'), caption = node('caption', d.name + ' · 初稿覆盖与补充'); table.append(caption);
    const head = node('thead'), hr = node('tr'); ['对照维度','初稿状态','判断与补充'].forEach(x => { const th = node('th', x); th.scope = 'col'; hr.append(th); }); head.append(hr); table.append(head);
    const body = node('tbody');
    d.validation.forEach(c => {
      const tr = node('tr'), th = node('th', c.axis); th.scope = 'row'; tr.append(th, node('td', statuses[c.initial_status]));
      const td = node('td', c.assessment); if (c.papers.length) td.append(refs(c.papers, papers)); if (c.supplements.length) td.append(refs(c.supplements, papers));
      td.append(source(c.evidence, '综述 §' + c.section + ' · 分类依据')); tr.append(td); body.append(tr);
    }); table.append(body);
    const scroll = node('div', undefined, 'domain-table-wrap'); scroll.tabIndex = 0; scroll.setAttribute('role','region'); scroll.setAttribute('aria-label',d.name + '综述对照表，可横向滚动'); scroll.append(table); root.append(scroll);
    root.append(node('h4', '05 · 对照后新增'), node('p', d.follow_up)); d.supplements.forEach(p => root.append(paper(p)));
    root.append(node('h4', '初稿边界与后续扩展'), node('p','以下保留初稿范围记录。补读增加了代表入口，并未完整覆盖这些方向。','muted')); const limits = node('ul'); d.limits.forEach(x => limits.append(node('li',x))); root.append(limits);
    const controls = node('div', undefined, 'watch-actions');
    for (const [ext,label] of [['md','导出阅读报告'],['json','导出来源与对照数据']]) {
      const b = node('button', label); b.type = 'button'; b.addEventListener('click', async () => {
        b.disabled = true; try { const data = await api('/'+d.id+'/export'); download(ext === 'md' ? data.markdown : JSON.stringify(data,null,2),d.id,ext); state.textContent = '阅读包已导出；个人文献库未改动。'; }
        catch (e) { state.textContent = e.message; } finally { b.disabled = false; }
      }); controls.append(b);
    } root.append(controls);
  }
  trigger.addEventListener('click', async () => {
    trigger.disabled = true; state.textContent = '正在载入方向目录…';
    try {
      const pack = await api(''); root.replaceChildren();
      for (const d of pack.domains) {
        const box = details(d.name + ' · ' + d.initial_papers + '篇初稿 + ' + d.supplements + '篇补充'), content = node('div'); box.append(content);
        let loaded = false, loading = false;
        box.addEventListener('toggle', async () => {
          if (!box.open || loaded || loading) return; loading = true; content.textContent = '正在载入文献与对照…';
          try { render(await api('/'+d.id), content); loaded = true; }
          catch (e) { content.textContent = e.message; } finally { loading = false; }
        }); root.append(box);
      }
      state.textContent = '三个方向，30篇论文，3份外部综述。展开方向查看分类、初稿、遗漏和补读。'; trigger.hidden = true;
    } catch (e) { state.textContent = e.message; trigger.disabled = false; }
  });
})();
