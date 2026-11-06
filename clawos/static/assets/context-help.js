/* Shared, text-only contextual help for server pages and the React workspace. */
(() => {
  const doc = document;
  if (doc.documentElement.hasAttribute('data-context-help-ready')) return;
  doc.documentElement.setAttribute('data-context-help-ready', '');
  let trigger = null, popup = null, timer = null, pinned = false, sequence = 0;
  let previousDescription = null;
  const targetOf = node => node instanceof Element ? node.closest('[data-context-help]') : null;
  const cancelClose = () => { clearTimeout(timer); timer = null; };
  function close() {
    cancelClose();
    if (trigger) {
      if (previousDescription === null) trigger.removeAttribute('aria-describedby');
      else trigger.setAttribute('aria-describedby', previousDescription);
    }
    popup?.remove(); popup = null; trigger = null; pinned = false;
  }
  function position() {
    if (!trigger || !popup) return;
    if (!trigger.isConnected) { close(); return; }
    const rect = trigger.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > innerHeight || rect.right < 0 || rect.left > innerWidth) { close(); return; }
    const width = popup.getBoundingClientRect().width;
    const height = popup.getBoundingClientRect().height;
    popup.style.left = Math.max(12, Math.min(rect.left, innerWidth - width - 12)) + 'px';
    popup.style.top = Math.max(12, rect.bottom + height + 10 <= innerHeight ? rect.bottom + 8 : rect.top - height - 8) + 'px';
  }
  function open(next) {
    if (!next?.getAttribute('data-context-help')?.trim()) return;
    cancelClose();
    if (trigger === next) return;
    close(); trigger = next;
    previousDescription = trigger.getAttribute('aria-describedby');
    popup = doc.createElement('div'); popup.className = 'context-help-popup';
    popup.id = 'context-help-' + (++sequence); popup.setAttribute('role', 'tooltip');
    popup.textContent = trigger.getAttribute('data-context-help');
    trigger.setAttribute('aria-describedby', [previousDescription, popup.id].filter(Boolean).join(' '));
    doc.body.append(popup); position();
  }
  function scheduleClose() { if (!pinned) { cancelClose(); timer = setTimeout(close, 150); } }
  doc.addEventListener('pointerover', event => {
    if (event.pointerType === 'touch') return;
    if (popup?.contains(event.target)) { cancelClose(); return; }
    const next = targetOf(event.target); if (next && (!pinned || next === trigger)) open(next);
  });
  doc.addEventListener('pointerout', event => {
    if (!trigger) return;
    if (trigger.contains(event.relatedTarget) || popup?.contains(event.relatedTarget)) return;
    if (trigger.contains(event.target) || popup?.contains(event.target)) scheduleClose();
  });
  doc.addEventListener('focusin', event => { const next = targetOf(event.target); if (next) open(next); });
  doc.addEventListener('focusout', event => { if (trigger?.contains(event.target)) scheduleClose(); });
  doc.addEventListener('click', event => {
    const next = targetOf(event.target);
    // Navigating steps can expose hover/focus help without stealing their action.
    if (!next || !next.classList.contains('context-help-trigger')) return;
    if (trigger === next && pinned) close(); else { open(next); pinned = true; }
  });
  doc.addEventListener('pointerdown', event => {
    if (trigger && !trigger.contains(event.target) && !popup?.contains(event.target)) close();
  });
  doc.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  addEventListener('resize', position);
  doc.addEventListener('scroll', position, true);
  new MutationObserver(() => {
    if (trigger && !trigger.isConnected) close();
    else if (trigger && popup && popup.textContent !== trigger.getAttribute('data-context-help')) {
      popup.textContent = trigger.getAttribute('data-context-help'); position();
    }
  }).observe(doc.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['data-context-help']});
})();
