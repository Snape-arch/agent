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
  document.addEventListener('workspace-view', e => {
    const key = e.detail === 'feishu' ? 'feishu' : 'console';
    for (const a of entries.children) {
      if (a.dataset.workspace === key) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    }
  });
})();
