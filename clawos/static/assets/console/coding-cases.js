import { $ } from './core.js';

const endpoint = '/api/workspace/coding/autonomous';
const states = { resumable: '可续接', paused: '已暂停', completed: '已完成', passed: '已完成',
  exhausted: '预算耗尽', failed: '失败', test_boundary_failed: '测试边界检查失败' };
const issues = { workspace_missing: '原工作区已不存在', workspace_metadata_changed: '工作区归属已变化',
  workspace_changed: '原工作区存在改动', source_evidence_changed: '原源码证据已变化' };
const phases = {
  baseline_recorded: '记录基线', model_requested: '发起模型调用', model_answered: '收到模型回答',
  retrieval_requested: '读取源码', patch_requested: '验证补丁', turn_saved: '保存回合',
  paused: '暂停', resumed: '续接', baseline_rebuilt: '重建基线', baseline_rebuild_failed: '重建失败',
  budget_exhausted: '预算耗尽', test_boundary_failed: '测试边界检查失败', completed: '完成',
};
const session = { repo: '', selected: '', note: null, offset: null, query: '', busy: false };

function element(tag, content) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = String(content);
  return node;
}

function action(label, listener) {
  const button = element('button', label);
  button.type = 'button';
  button.className = 'secondary';
  button.addEventListener('click', listener);
  return button;
}

async function request(name, body = {}, repo = session.repo) {
  const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, repo_path: repo, action: name }) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `请求失败（${response.status}）`);
  if (!data) throw new Error('服务未返回有效结果');
  return data;
}

async function perform(message, operation) {
  if (session.busy) return;
  session.busy = true;
  $('codingStatus').textContent = message;
  const controls = [...document.querySelectorAll('.coding-cases form:not([method=dialog]) button, #codingResume, #codingRebuild, #codingMore')]
    .filter(node => !node.disabled);
  for (const button of controls) button.disabled = true;
  try {
    $('codingStatus').textContent = await operation() || '';
  } catch (error) {
    $('codingStatus').textContent = error.message || '操作失败';
  } finally {
    for (const button of controls) button.disabled = false;
    session.busy = false;
  }
}

function confirmAction(title, text) {
  const dialog = $('codingConfirm');
  $('codingConfirmTitle').textContent = title;
  $('codingConfirmText').textContent = text;
  dialog.returnValue = 'cancel';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
    dialog.showModal();
  });
}

function newId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
}

function setOptions(rows, selected = $('codingDecisionSource').value) {
  const select = $('codingDecisionSource');
  select.replaceChildren(new Option('选择检查点', ''), ...rows.map(row => new Option(
    `${row.objective} · ${row.checkpoint_id.slice(-8)}`, row.checkpoint_id)));
  if (selected && !rows.some(row => row.checkpoint_id === selected)) select.add(new Option(selected, selected));
  select.value = selected;
}

function showHistory(rows) {
  const items = rows.map(row => {
    const item = element('li');
    item.append(element('b', row.objective), element('p', states[row.status] || row.status),
      action('查看续接预检', () => perform('正在检查工作区…', async () => {
        await loadPreview(row.checkpoint_id);
        $('codingPreviewTitle').focus();
      })));
    item.lastChild.setAttribute('aria-label', `查看续接预检：${row.objective}`);
    return item;
  });
  $('codingHistory').replaceChildren(...(items.length ? items : [element('li', '此仓库暂无编码任务。')]));
  setOptions(rows);
}

async function loadPreview(id) {
  const data = await request('resume_preview', { checkpoint_id: id });
  const facts = element('dl');
  const row = (label, text) => facts.append(element('dt', label), element('dd', text));
  row('状态', states[data.status] || data.status);
  row('下一轮', data.next_turn);
  row('工作区', data.workspace);
  row('累计用量', `${data.budget.model_calls} 次模型调用 · ${data.budget.tool_calls} 次工具调用 · ${data.budget.tokens} token`);
  if (data.workspace_issue) row('预检发现', issues[data.workspace_issue] || data.workspace_issue);
  if (data.source_head_changed) row('源仓库', '当前提交与最初基线不同。');
  if (data.changed_paths.length) row('原工作区改动', data.changed_paths.join('、'));
  if (data.current_source_dirty_paths.length) row('源仓库未提交改动', data.current_source_dirty_paths.join('、'));
  if (data.tests_to_rerun_if_rebuilt.length) row('重建时重跑', data.tests_to_rerun_if_rebuilt.map(command => JSON.stringify(command)).join('、'));
  $('codingPreviewFacts').replaceChildren(facts);
  $('codingEvents').replaceChildren(...data.events.map(event => {
    const item = element('li', `第 ${event.turn} 轮 · ${phases[event.phase] || event.phase}`);
    if (event.timestamp) {
      const timestamp = element('time', new Date(event.timestamp).toLocaleString());
      timestamp.dateTime = event.timestamp;
      item.append(' · ', timestamp);
    }
    return item;
  }));
  $('codingResume').hidden = !data.can_resume;
  $('codingRebuild').hidden = !data.can_rebuild;
  $('codingPreview').hidden = false;
  session.selected = id;
}

function editNote(note = null) {
  session.note = note;
  $('codingNoteHeading').textContent = note ? '编辑项目笔记' : '添加项目笔记';
  $('codingTopic').value = note?.topic || '';
  $('codingNoteText').value = note?.note || '';
  $('codingScope').value = note?.scope || '';
  $('codingDecision').value = note?.decision?.rationale || '';
  const select = $('codingDecisionSource');
  const id = note?.decision?.checkpoint_id || '';
  if (id && ![...select.options].some(option => option.value === id)) select.add(new Option(id, id));
  select.value = id;
  if (note) {
    $('codingNoteEditor').open = true;
    $('codingTopic').focus();
  }
}

function showNotes(data, append = false) {
  const rows = data.notes.map(note => {
    const item = element('li');
    const buttons = element('div');
    buttons.className = 'coding-actions';
    buttons.append(action('编辑', () => { if (!session.busy) editNote(note); }),
      action('删除', () => perform('', async () => {
        if (!await confirmAction('删除项目笔记', `删除「${note.topic}」？`)) return;
        await request('memory_delete', { note_id: note.id, confirmed: true });
        if (session.note?.id === note.id) editNote();
        await loadNotes(session.query);
        return '已删除笔记。';
      })));
    for (const button of buttons.children) button.setAttribute('aria-label', `${button.textContent}：${note.topic}`);
    item.append(element('b', note.topic), element('p', note.note));
    if (note.scope) item.append(element('p', `范围：${note.scope}`));
    if (note.decision) item.append(element('p', `决策理由：${note.decision.rationale}`));
    item.append(buttons);
    return item;
  });
  if (append) $('codingNotes').append(...rows);
  else $('codingNotes').replaceChildren(...(rows.length ? rows : [element('li', '没有匹配的笔记。')]));
  session.offset = data.next_offset;
  $('codingMore').hidden = session.offset === null;
}

async function loadNotes(query, offset = 0) {
  showNotes(await request('memory_list', { query, offset }), offset > 0);
  session.query = query;
}

function finishRun(result) {
  const status = states[result.status] || result.status;
  return result.error ? `${status}：${result.error}` : `任务${status}。`;
}

async function updateRun(result) {
  showHistory((await request('history')).checkpoints);
  if (result.checkpoint_id) {
    await loadPreview(result.checkpoint_id);
    $('codingPreviewTitle').focus();
  }
  return finishRun(result);
}

function submit(id, listener) {
  $(id).addEventListener('submit', event => { event.preventDefault(); listener(); });
}

export function bindCodingCases() {
  if (!$('codingRepoForm')) return;
  try { $('codingRepo').value = localStorage.getItem('clawos-coding-repo') || ''; } catch {}
  submit('codingRepoForm', () => perform('正在打开仓库记录…', async () => {
    const repo = $('codingRepo').value.trim();
    if (!repo) throw new Error('请输入 Git 仓库路径。');
    const [history, notes] = await Promise.all([request('history', {}, repo), request('memory_list', {}, repo)]);
    session.repo = repo;
    session.selected = '';
    session.query = '';
    $('codingQuery').value = '';
    $('codingPreview').hidden = true;
    editNote();
    showHistory(history.checkpoints);
    showNotes(notes);
    $('codingContent').hidden = false;
    try { localStorage.setItem('clawos-coding-repo', repo); } catch {}
  }));
  submit('codingStart', () => perform('正在准备任务…', async () => {
    const objective = $('codingGoal').value.trim();
    let commands;
    try { commands = $('codingTests').value.trim().split(/\r?\n/).filter(line => line.trim()).map(line => JSON.parse(line)); }
    catch { throw new Error('每行测试必须是 JSON 参数数组。'); }
    if (!objective || !commands.length || commands.length > 5 ||
        commands.some(command => !Array.isArray(command) || !command.length || command.some(arg => typeof arg !== 'string' || !arg.trim()))) {
      throw new Error('请输入任务目标及 1 至 5 组有效测试参数。');
    }
    if (!await confirmAction('开始编码任务', `仓库 ${session.repo}。在隔离工作区运行固定测试并验证代理生成的补丁。`)) return;
    $('codingStatus').textContent = '正在隔离工作区运行…';
    return updateRun(await request('start', { objective, task_id: newId(), session_id: newId(),
      test_commands: commands, pause_after: Number($('codingPause').value), confirmed: true }));
  }));
  for (const [id, strategy] of [['codingResume', 'continue'], ['codingRebuild', 'rebuild']]) {
    $(id).addEventListener('click', () => perform('', async () => {
      const rebuild = strategy === 'rebuild';
      if (!await confirmAction(rebuild ? '从当前源码重建' : '继续原工作区',
        rebuild ? '创建新的隔离工作区并重跑原测试。原工作区内的编辑会保留。' : '使用预检中的工作区、固定测试和剩余预算继续。')) return;
      $('codingStatus').textContent = '正在运行编码任务…';
      return updateRun(await request('resume', { checkpoint_id: session.selected, confirmed: true,
        session_id: newId(), resume_strategy: strategy }));
    }));
  }
  submit('codingSearch', () => perform('正在搜索笔记…', () => loadNotes($('codingQuery').value.trim())));
  $('codingMore').addEventListener('click', () => perform('正在读取笔记…', () => loadNotes(session.query, session.offset)));
  $('codingNoteReset').addEventListener('click', () => editNote());
  submit('codingNote', () => perform('正在保存笔记…', async () => {
    const rationale = $('codingDecision').value.trim();
    const checkpoint_id = $('codingDecisionSource').value;
    if (Boolean(rationale) !== Boolean(checkpoint_id)) throw new Error('请同时填写决策理由并关联检查点。');
    await request('memory_save', {
      topic: $('codingTopic').value.trim(), note: $('codingNoteText').value.trim(), scope: $('codingScope').value.trim(),
      note_id: session.note?.id, decision: rationale ? { rationale, checkpoint_id } : undefined, confirmed: true,
    });
    editNote();
    $('codingNoteEditor').open = false;
    $('codingQuery').value = '';
    await loadNotes('');
    $('codingNotes').querySelector('button')?.focus();
    return '已保存笔记。';
  }));
}
