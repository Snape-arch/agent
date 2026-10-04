/* Shared navigation uses ordinary links; no permissions or data are cached here. */
(function () {
  'use strict';
  const links = [
    ['/console', '工作空间', 'console'], ['/academy', '学习', 'academy'],
    ['/academy/notes', '文档', 'documents'], ['/meetings', '会议', 'meetings'],
    ['/data-lab', '数据', 'data'], ['/console?view=feishu', '飞书', 'feishu']
  ];
  const path = location.pathname;
  const active = path === '/academy/notes' ? 'documents' : path.startsWith('/academy') ? 'academy' :
    path === '/meetings' ? 'meetings' : path === '/data-lab' ? 'data' :
    document.querySelector('#view-feishu.on') ? 'feishu' : 'console';
  const nav = document.createElement('nav');
  nav.className = 'workspace-nav'; nav.setAttribute('aria-label', '全局工作空间');
  const brand = document.createElement('a'); brand.href = '/product'; brand.className = 'workspace-brand';
  const logo = document.createElement('img'); logo.src = '/assets/brand/clawos-logo-dark.png'; logo.alt = '';
  brand.append(logo, document.createTextNode('ClawOS')); nav.append(brand);
  const entries = document.createElement('div'); entries.className = 'workspace-links';
  for (const [href, label, key] of links) {
    const a = document.createElement('a'); a.href = href; a.textContent = label; a.dataset.workspace = key;
    if (key === active) a.setAttribute('aria-current', 'page');
    entries.append(a);
  }
  nav.append(entries); document.body.classList.add('workspace-linked');
  const skip=document.body.querySelector(':scope > .skip');
  if(skip)skip.after(nav);else document.body.prepend(nav);
  // Old Windows private-use glyphs are absent on many browser/OS combinations.
  // Label icon-only actions; omit decorative glyphs beside an existing label.
  function present(root) {
    const icons = [...(root.matches?.('.fluent-icon') ? [root] : []), ...root.querySelectorAll('.fluent-icon')];
    for (const icon of icons) {
      if (!/[\uE000-\uF8FF]/u.test(icon.textContent)) continue;
      const action = icon.closest('button,a,label');
      if (!action) { icon.remove(); continue; }
      const otherText = [...action.childNodes].filter(n => n !== icon).map(n => n.textContent).join('').trim();
      if (otherText) { icon.remove(); continue; }
      const label = action.getAttribute('aria-label') || action.getAttribute('title');
      if (!label) continue;
      icon.className = 'ui-action-label';
      const shortLabels = {'折叠论文目录':'目录','研究运行记录':'记录','清除画布':'清空','文本批注':'批注','导出笔记':'导出'};
      icon.textContent = shortLabels[label] || label.replace(/论文|侧栏|知识图谱|任务进度/g, '');
      action.setAttribute('aria-label', label);
    }
    const tables = [...(root.matches?.('table') ? [root] : []), ...root.querySelectorAll('table')];
    for (const table of tables) {
      if (!table.closest('.doc-block')) table.dataset.wide = String(table.querySelectorAll('thead th').length >= 6);
      if (table.closest('.doc-block,.md-table-wrap,.workspace-table-scroll,.table-scroll,.feishu-status-scroll')) continue;
      const section = table.closest('section,.section-block');
      const label = table.getAttribute('aria-label') || section?.querySelector('h2,h3')?.textContent.trim() || '数据表格';
      const scroll = document.createElement('div');
      scroll.className = 'workspace-table-scroll';
      scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', label); scroll.tabIndex = 0;
      table.before(scroll); scroll.append(table);
    }
  }
  present(document.body);
  // Examine only added elements, not text edits or the entire document per key.
  const observer = new MutationObserver(records => {
    for (const record of records) {
      const table = record.target.closest?.('table');
      if (table && !table.closest('.doc-block')) table.dataset.wide = String(table.querySelectorAll('thead th').length >= 6);
      for (const node of record.addedNodes) {
        if (node.nodeType === 1 && node.isConnected) present(node);
      }
    }
  });
  observer.observe(document.body, {childList: true, subtree: true});
  document.addEventListener('workspace-view', e => {
    const key = e.detail === 'feishu' ? 'feishu' : 'console';
    for (const a of entries.children) {
      if (a.dataset.workspace === key) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    }
  });
})();
