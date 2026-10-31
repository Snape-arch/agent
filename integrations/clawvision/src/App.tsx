import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  Beaker,
  Box,
  ChevronRight,
  CircleStop,
  Cpu,
  Database,
  FlaskConical,
  GitCompareArrows,
  Layers3,
  Menu,
  Plus,
  Search,
  Settings2,
  Sparkles,
} from 'lucide-react';
import { ParameterLab, type ParameterPlan } from './components/ParameterLab';
import { DataLab } from './components/DataLab';
import { ThreeLab } from './components/ThreeLab';
import { AiStudio } from './components/AiStudio';
import { AiExperimentCommand } from './components/AiExperimentCommand';
import { AssetWorkbench } from './components/AssetWorkbench';
import { ExperimentAssetTimeline } from './components/ExperimentAssetTimeline';
import { AuthGate } from './components/AuthGate';
import { ClawOSGate, IntegrationSettings } from './components/ClawOSGate';
import { integrated, researchContext } from './clawos';
import { WorkspaceSettings } from './components/WorkspaceSettings';
import { can } from './permissions';
import { PluginGallery, PluginHost } from './visualizations/PluginHost';
import { compareTableArtifact, diagnosticArtifacts, logArtifact, parameterTableArtifact, timeSeriesArtifact } from './visualizations/runArtifacts';
import {
  createParameterJob,
  stopRemoteRun,
  type RunCounts,
  type CurrentUser,
} from './api';
import {
  defaultParams,
  initialRuns,
  type ExperimentRun,
} from './domain';

import { useRunDetails, useRunPage } from './hooks/useRuns';

const EvaluationLab = lazy(() => import('./components/EvaluationLab').then((module) => ({ default: module.EvaluationLab })));

type View = 'home' | 'overview' | 'compare' | 'artifacts' | 'data' | 'three' | 'assets' | 'ai-studio' | 'settings' | 'evaluation';

const roleCopy: Record<CurrentUser['role'], { title: string; description: string }> = {
  viewer: { title: '查看项目进展', description: '从运行结果和已发布资产开始，不展示写入与管理入口。' },
  researcher: { title: '继续研究工作', description: '快速启动实验、比较结果，按需进入数据和 3D 工具。' },
  admin: { title: '管理团队工作区', description: '关注运行健康、资产交付和成员配置。' },
  owner: { title: '研究进展，一目了然。', description: '选择一个问题，记录每一次实验的参数、结果与产物。' },
};

export function RoleHome({ user, runs, onNavigate, onDemoToggle, demoMode = false, counts }: { user: CurrentUser; runs: ExperimentRun[]; onNavigate: (view: View) => void; onDemoToggle?: () => void; demoMode?: boolean; counts?: RunCounts }) {
  const runningCount = counts?.running ?? runs.filter((run) => run.status === 'running').length;
  const completedCount = counts?.completed ?? runs.filter((run) => run.status === 'completed').length;
  const totalCount = counts ? Object.values(counts).reduce((sum, value) => sum + (value ?? 0), 0) : runs.length;
  const actions = user.role === 'viewer' || demoMode
    ? [{ view: 'overview' as View, title: '查看最新结果', copy: '检查指标、日志和运行状态。', icon: <Activity /> }, { view: 'assets' as View, title: '浏览交付资产', copy: '查看已经产生的模型和版本。', icon: <Layers3 /> }]
    : [{ view: 'overview' as View, title: '运行实验', copy: '配置参数并跟踪实时训练结果。', icon: <Activity /> }, { view: 'compare' as View, title: '比较结果', copy: '对齐多个 Run 的指标与参数。', icon: <GitCompareArrows /> }, { view: 'assets' as View, title: '管理资产', copy: '整理模型、版本和交付状态。', icon: <Layers3 /> }];
  return <section className="role-home" aria-labelledby="role-home-title"><div className="role-hero"><span className="eyebrow">{integrated()?'本机研究空间':user.role.toUpperCase()+' WORKSPACE'}</span><h1 id="role-home-title">{roleCopy[user.role].title}</h1><p>{roleCopy[user.role].description}</p><div className="home-status" aria-label="项目摘要"><span><strong>{runningCount}</strong> 正在运行</span><span><strong>{completedCount}</strong> 已完成</span><span><strong>{totalCount}</strong> 全部 Run</span></div></div><h2>开始一次研究工作</h2><div className="role-actions">{actions.map((action) => <button key={action.view} onClick={() => onNavigate(action.view)}>{action.icon}<span><strong>{action.title}</strong><small>{action.copy}</small></span><ChevronRight aria-hidden="true" /></button>)}</div><div className="progressive-hint"><Sparkles size={16} /><span><strong>专业工具按需显示</strong>数据分析、3D、AI Studio 和诊断工具已收纳在左侧“更多工具”中。</span></div>{onDemoToggle && <button className="demo-toggle" onClick={onDemoToggle}>{demoMode ? '返回真实工作区' : '查看演示实验'}</button>}</section>;
}

function latest(run?: ExperimentRun) {
  return run?.metrics.at(-1);
}

function syntheticRun(run?: ExperimentRun) {
  return Boolean(run && (run.params as ExperimentParamsWithExecution)._execution?.synthetic);
}
type ExperimentParamsWithExecution = ExperimentRun['params'] & {_execution?:{provider:string;synthetic:boolean}};

function formatPercent(value?: number) {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value?: number | null, digits = 3) {
  return value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function Stat({ label, value, note, accent }: { label: string; value: string; note: string; accent?: boolean }) {
  return (
    <div className={`stat ${accent ? 'stat-accent' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

function RunList({ runs, selectedId, onSelect }: { runs: ExperimentRun[]; selectedId: string; onSelect: (id: string) => void }) {
  return (
    <div className="run-list">
      {runs.map((run) => {
        const metric = latest(run);
        return (
          <button key={run.id} className={`run-row ${selectedId === run.id ? 'active' : ''}`} onClick={() => onSelect(run.id)}>
            <span className="run-dot" style={{ background: run.color }} />
            <span className="run-name"><strong>{run.name}</strong><small>{run.params.optimizer} · lr {run.params.learningRate}</small></span>
            <span className={`status-pill ${run.status}`}>{run.status === 'queued' ? '排队' : run.status === 'running' ? '运行中' : run.status === 'completed' ? '完成' : run.status === 'failed' ? '失败' : '停止'}</span>
            <span className="run-accuracy">{formatPercent(metric?.accuracy)}</span>
            <ChevronRight size={14} />
          </button>
        );
      })}
    </div>
  );
}

function Overview({ runs, selected, onStop, canControl=true }: { runs: ExperimentRun[]; selected: ExperimentRun; onStop: () => void; canControl?: boolean }) {
  const point = latest(selected);
  const comparedRuns = [selected, ...runs.filter((run) => run.id !== selected.id)].filter((run) => run.detailLoaded !== false).slice(0, 3);
  return (
    <>
      <div className="page-heading"><div><div className="eyebrow"><span className="live-dot" /> EXPERIMENT / IMAGE CLASSIFICATION</div><h1>{selected.name}</h1><p>实时追踪训练表现、资源利用率与参数影响。</p></div>{selected.status === 'running' && canControl ? <button className="stop-btn" onClick={onStop}><CircleStop size={15} />停止运行</button> : <div className="completed-badge">{{ queued: 'Run 排队中', running: '只读 · 正在运行', completed: '✓ Run 已完成', stopped: 'Run 已停止', failed: 'Run 已失败' }[selected.status]}</div>}</div>
      <div className="stat-grid">
        <Stat label="验证准确率" value={formatPercent(point?.accuracy)} note={selected.status === 'running' ? `epoch ${point?.step}/${selected.params.epochs}` : '最终结果'} accent />
        <Stat label="训练损失" value={formatNumber(point?.trainLoss)} note="越低越好" />
        <Stat label="验证损失" value={formatNumber(point?.valLoss)} note="泛化表现" />
        <Stat label="GPU 利用率" value={point?.gpu == null ? '—' : `${point.gpu}%`} note={`batch ${selected.params.batchSize}`} />
      </div>
      <div className="dashboard-grid">
        <section className="card chart-card span-2"><div className="card-head"><div><span>LEARNING CURVE</span><h3>验证准确率</h3></div><div className="legend">{comparedRuns.map((run) => <span key={run.id}><i style={{ background: run.color }} />{run.name}</span>)}</div></div><PluginHost input={timeSeriesArtifact(comparedRuns, 'accuracy')} /></section>
        <section className="card console-card"><div className="card-head"><div><span>LIVE EVENTS</span><h3>运行日志</h3></div></div><PluginHost input={logArtifact(selected)} /></section>
        <section className="card"><div className="card-head"><div><span>LOSS PROFILE</span><h3>训练 / 验证损失</h3></div></div><PluginHost input={timeSeriesArtifact([selected], 'valLoss', { height: 185 })} /></section>
        <section className="card"><div className="card-head"><div><span>RUN PARAMETERS</span><h3>本次实验配置</h3></div></div><PluginHost input={parameterTableArtifact(selected)} /></section>
      </div>
    </>
  );
}

function Compare({ runs, focusIds, onSelection }: { runs: ExperimentRun[]; focusIds?: string[]; onSelection: (ids: string[]) => void }) {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => focusIds?.length ? focusIds : runs.slice(0, 4).map((run) => run.id));
  const [smoothing, setSmoothing] = useState(3);
  useEffect(() => {
    setSelectedIds((current) => current.length ? current : runs.slice(0, 4).map((run) => run.id));
  }, [runs.map((run) => run.id).join(':')]);
  useEffect(() => {
    if (focusIds?.length) setSelectedIds(focusIds);
  }, [focusIds?.join(':')]);
  useEffect(() => onSelection(selectedIds), [selectedIds.join(':')]);
  const displayed = selectedIds.map((id) => runs.find((run) => run.id === id)).filter((run): run is ExperimentRun => Boolean(run) && run?.detailLoaded !== false).slice(0, 10);
  const toggleRun = (id: string) => setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : current.length < 10 ? [...current, id] : current);
  const best = [...displayed].sort((a, b) => (latest(b)?.accuracy ?? 0) - (latest(a)?.accuracy ?? 0))[0];
  return (
    <>
      <div className="page-heading"><div><div className="eyebrow">COMPARE / {displayed.length} RUNS</div><h1>实验对比</h1><p>将参数差异与模型表现放在同一视图中。</p></div><div className="best-badge"><Sparkles size={14} />最佳：{best?.name}</div></div>
      <section className="compare-toolbar card">
        <div className="run-picker">{runs.map((run) => <button key={run.id} className={selectedIds.includes(run.id) ? 'selected' : ''} onClick={() => toggleRun(run.id)}><i style={{ background: run.color }} />{run.name}<b>{formatPercent(latest(run)?.accuracy)}</b></button>)}</div>
        <label>曲线平滑<select value={smoothing} onChange={(event) => setSmoothing(Number(event.target.value))}><option value="1">关闭</option><option value="3">3 steps</option><option value="5">5 steps</option></select></label>
      </section>
      <section className="card compare-chart"><div className="card-head"><div><span>ALIGNED METRICS</span><h3>验证准确率对比</h3></div><div className="legend">{displayed.map((run) => <span key={run.id}><i style={{ background: run.color }} />{run.name}</span>)}</div></div>{displayed.length ? <PluginHost input={timeSeriesArtifact(displayed, 'accuracy', { height: 270, smoothing })} /> : <div className="empty-compare">请选择至少一个 Run</div>}</section>
      <section className="card table-card"><div className="card-head"><div><span>PARAMETER DIFF</span><h3>参数与结果</h3></div></div><PluginHost input={compareTableArtifact(displayed)} /></section>
      {displayed.length > 0 && displayed.at(-1)!.source !== 'local-demo' && <ExperimentAssetTimeline run={displayed.at(-1)!} baseline={displayed.length > 1 ? displayed[0] : undefined} />}
    </>
  );
}

function Artifacts({ selected }: { selected: ExperimentRun }) {
  const hasDiagnostics = selected.confusion.length > 0 || selected.samples.length > 0 || selected.embedding.length > 0 || (selected.artifacts?.length ?? 0) > 0;
  return (
    <>
      <div className="page-heading"><div><div className="eyebrow">ARTIFACTS / {selected.name}</div><h1>模型诊断</h1><p>从类别错误、样本预测和特征空间三个角度检查结果。</p></div><div className="completed-badge"><Layers3 size={14} />{selected.artifacts?.length ?? 0} 个已上传产物</div></div>
      {!hasDiagnostics && <div className="run-empty" role="status">此 Run 尚未上传诊断产物。上传混淆矩阵、样本预测或 Embedding 后即可查看。</div>}
      <PluginGallery inputs={diagnosticArtifacts(selected)} />
      {selected.source !== 'local-demo' && <ExperimentAssetTimeline run={selected} />}
    </>
  );
}

export function WorkspaceApp({ user }: { user: CurrentUser }) {
  const views:View[]=['home','overview','compare','artifacts','data','three','assets','ai-studio','settings','evaluation'];
  const initialHash=location.hash.slice(1) as View;
  const [view, setViewState] = useState<View>(() => new URLSearchParams(location.search).has('shared') ? 'data' : views.includes(initialHash) ? initialHash : 'home');
  const setView=(next:View)=>{if(!['home','overview','compare','artifacts'].includes(next))setDemoMode(false);setViewState(next);if(location.hash!==`#${next}`)history.pushState({view:next},'',`#${next}`);};
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const demoRuns = useMemo(initialRuns, []);
  const [selectedId, setSelectedId] = useState('');
  const [draftParams, setDraftParams] = useState(defaultParams);
  const [query, setQuery] = useState('');
  const [baselineRunId, setBaselineRunId] = useState<string>();
  const [comparisonFocusIds, setComparisonFocusIds] = useState<string[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [actionError, setActionError] = useState('');
  const pageState = useRunPage(demoMode ? '' : query);
  const { loaded: runsLoaded, online: backendOnline } = pageState;
  const pageSelected = pageState.data.find((run) => run.id === selectedId) ?? pageState.data[0];
  const detailIds = demoMode || pageState.searching ? [] : [
    ...(view === 'overview' ? [pageSelected?.id ?? '', ...pageState.data.filter((run) => run.id !== pageSelected?.id).slice(0, 2).map((run) => run.id)] : []),
    ...(view === 'artifacts' ? [pageSelected?.id ?? ''] : []),
    ...(view === 'compare' ? compareIds : []),
    ...(baselineRunId && view === 'overview' ? [baselineRunId] : []),
  ];
  const { details, error: detailError } = useRunDetails(detailIds, view === 'compare' ? compareIds[0] : pageSelected?.id);
  const runs = pageState.data.map((summary) => details[summary.id] ? { ...details[summary.id], color: summary.color } : summary);
  const visibleRuns = demoMode ? demoRuns : runs;
  const comparisonRuns = demoMode ? demoRuns : [...runs, ...[...new Set([...compareIds, ...comparisonFocusIds])].filter((id) => !runs.some((run) => run.id === id)).map((id) => details[id]).filter((run): run is ExperimentRun => Boolean(run))];
  const syncError = pageState.error || detailError || actionError;
  const mobileToggleRef = useRef<HTMLButtonElement>(null);
  const mobileNavRef = useRef<HTMLElement>(null);
  const selected = visibleRuns.find((run) => run.id === selectedId) ?? visibleRuns[0];
  const baselineRun = baselineRunId ? details[baselineRunId] ?? runs.find((run) => run.id === baselineRunId) : undefined;

  useEffect(()=>{
    if(!location.hash)history.replaceState({view},'',`#${view}`);
    const navigateHistory=()=>{const next=location.hash.slice(1) as View;if(views.includes(next))setViewState(next);};
    addEventListener('popstate',navigateHistory);return()=>removeEventListener('popstate',navigateHistory);
  },[]);

  useEffect(()=>{
    document.querySelectorAll('.lab-workspace .card-head h3').forEach((heading)=>heading.setAttribute('aria-level','2'));
  },[view]);

  useEffect(()=>{
    if(!mobileNavOpen)return;
    const previous=document.activeElement as HTMLElement|null;
    mobileNavRef.current?.querySelector<HTMLElement>('button,summary')?.focus();
    const keydown=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){setMobileNavOpen(false);mobileToggleRef.current?.focus();return;}
      if(event.key!=='Tab'||!mobileNavRef.current)return;
      const items=[...mobileNavRef.current.querySelectorAll<HTMLElement>('button:not([disabled]),summary,[href],input:not([disabled])')];
      if(!items.length)return;const first=items[0],last=items.at(-1)!;
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    };
    document.addEventListener('keydown',keydown);document.body.classList.add('nav-open');
    return()=>{document.removeEventListener('keydown',keydown);document.body.classList.remove('nav-open');if(previous&&previous===mobileToggleRef.current)previous.focus();};
  },[mobileNavOpen]);

  const filteredRuns = demoMode ? demoRuns.filter((run) => run.name.toLowerCase().includes(query.toLowerCase())) : pageState.data;

  const stopRun = async () => {
    if (!selected || demoMode) return;
    try { await stopRemoteRun(selected.id); setActionError(''); pageState.reload(); }
    catch (error) { setActionError(error instanceof Error ? error.message : '停止失败'); }
  };

  const submitParameterPlan = async (plan: ParameterPlan) => {
    const response = await createParameterJob({
      name: `${plan.kind}-${new Date().toISOString().slice(11, 19).replaceAll(':', '')}`,
      kind: plan.kind,
      baselineRunId,
      configs: plan.configs,
      concurrency: plan.concurrency,
      estimateSeconds: plan.estimateSeconds,
      estimatedCost: plan.estimatedCost,
      trainingProvider: plan.trainingProvider,
    });
    if(response.readingContext && response.readingContext.attached < response.readingContext.requested)
      setActionError('实验已创建，但部分文献来源关联未保存，请在实验产物中核对；不要重复创建实验。');
    pageState.reload(true);
    const focus = [...(baselineRunId ? [baselineRunId] : []), ...response.data.runIds].slice(0, 10);
    setComparisonFocusIds(focus);
    setCompareIds(focus);
    setSelectedId(response.data.runIds[0]);
    setView('compare');
  };

  const toggleDemo = () => { setDemoMode((value) => !value); setView('home'); };

  return (
    <div className="app-shell" data-testid="workspace-app">
      <a className="skip-link" href="#workspace-content">跳到主要内容</a>
      <button ref={mobileToggleRef} className="mobile-nav-toggle" aria-expanded={mobileNavOpen} aria-controls="primary-navigation" onClick={() => setMobileNavOpen((value) => !value)}><Menu size={18} />导航</button>
      {mobileNavOpen&&<button className="nav-scrim" aria-label="关闭导航" onClick={()=>setMobileNavOpen(false)}/>}
      <aside ref={mobileNavRef} aria-label="工作区导航面板" className={`sidebar ${mobileNavOpen ? 'mobile-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><FlaskConical size={20} /></div><div><strong>ClawVision</strong><span>实验与验证</span></div></div>
        {integrated()&&<div className="clawos-navigation"><a href="/academy">ClawOS 研究与教学</a><a href="/academy/lab">学习与教材</a><a href="/academy/research#domain-heading">文献与综述</a><a href="/academy/notes">研究笔记</a></div>}
        {!demoMode && can(user,'runs:create') && <button className="new-experiment" onClick={() => { setView('overview'); setMobileNavOpen(false); }}><Plus size={15} />新建实验</button>}
        <nav id="primary-navigation" aria-label="主导航">
          <button data-testid="nav-home" aria-current={view === 'home' ? 'page' : undefined} className={view === 'home' ? 'active' : ''} onClick={() => setView('home')}><Sparkles size={17} />我的首页</button>
          <div className="nav-label">工作区</div>
          <button data-testid="nav-overview" className={view === 'overview' ? 'active' : ''} onClick={() => setView('overview')}><Activity size={17} />运行概览</button>
          <button data-testid="nav-assets" className={view === 'assets' ? 'active' : ''} onClick={() => setView('assets')}><Layers3 size={17} />资产工作台</button>
          <button data-testid="nav-evaluation" aria-current={view === 'evaluation' ? 'page' : undefined} className={view === 'evaluation' ? 'active' : ''} onClick={() => setView('evaluation')}><GitCompareArrows size={17} />视觉评估</button>
          <details className="advanced-nav" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}><summary data-testid="nav-more"><span><Menu size={17} />更多工具</span><ChevronRight size={14} /></summary><div>
            <button data-testid="nav-compare" className={view === 'compare' ? 'active' : ''} onClick={() => setView('compare')}><GitCompareArrows size={17} />实验对比<span className="nav-count">{demoMode ? demoRuns.length : Object.values(pageState.counts).reduce((sum, count) => sum + (count ?? 0), 0)}</span></button>
            <button className={view === 'artifacts' ? 'active' : ''} onClick={() => setView('artifacts')}><Layers3 size={17} />模型诊断</button>
            <button data-testid="nav-data" className={view === 'data' ? 'active' : ''} onClick={() => setView('data')}><Database size={17} />通用数据</button>
            <button data-testid="nav-three" className={view === 'three' ? 'active' : ''} onClick={() => setView('three')}><Box size={17} />3D 实验</button>
            <button data-testid="nav-ai-studio" className={view === 'ai-studio' ? 'active' : ''} onClick={() => setView('ai-studio')}><Sparkles size={17} />AI 3D Studio</button>
          </div></details>
          {!integrated()&&<><div className="nav-label">项目</div>
          <button><Beaker size={17} />图像分类</button>
          <button disabled title="尚未开放"><Cpu size={17} />LLM 微调<span className="soon">尚未开放</span></button></>}
        </nav>
        <div className="sidebar-foot"><div className="storage"><span><Database size={13} />实验存储</span><strong>SQLite</strong></div>{!integrated()&&<div className="storage-bar"><i /></div>}{can(user,'workspace:admin') && <button className={view==='settings'?'active':''} onClick={()=>setView('settings')}><Settings2 size={15} />项目设置</button>}</div>
      </aside>

      <div className="workspace">
        <header className="topbar"><div className="breadcrumb"><span>{integrated()?'ClawOS':'Projects'}</span><ChevronRight size={13} /><strong>{integrated()?'实验工作区':'vision-classifier'}</strong></div><label className="search"><Search size={14} /><input placeholder="搜索 Run" value={query} onChange={(event) => setQuery(event.target.value)} /></label><div className={`top-status ${backendOnline ? '' : 'offline'}`}><span className="connection-dot" />{demoMode ? '演示实验' : backendOnline ? '已连接后端' : runsLoaded ? '后端连接异常' : '正在连接…'}</div><div className="avatar">CV</div></header>
        {demoMode && <div className="workspace-notice" role="status">演示模式：实验指标和诊断产物均为模拟数据。<button onClick={toggleDemo}>返回真实工作区</button></div>}
        {!demoMode && ['overview','compare','artifacts'].includes(view) && syntheticRun(selected) && <div className="workspace-notice" role="status">模拟实验：当前准确率、损失和GPU数值由确定性模拟器生成，仅用于验证流程，不代表真实训练或设备实测。</div>}
        {!demoMode && syncError && <div className="workspace-notice" role="status">无法同步实验：{syncError}。{runs.length > 0 ? '当前显示上次成功加载的数据。' : '连接恢复后将自动重试。'}</div>}
        <div className={`workspace-body ${view === 'home' || view === 'data' || view === 'three' || view === 'assets' || view === 'ai-studio' || view === 'evaluation' ? 'lab-workspace' : ''}`}>
          {view !== 'home' && view !== 'data' && view !== 'three' && view !== 'assets' && view !== 'evaluation' && <aside className="runs-panel"><div className="runs-head"><div><span>RUNS</span><strong>{demoMode ? filteredRuns.length : pageState.pagination.total} 次实验</strong></div></div><RunList runs={filteredRuns} selectedId={selected?.id ?? ''} onSelect={setSelectedId} />{!demoMode && <div className="run-pagination" aria-label="Run 分页"><span>{pageState.loading ? '正在加载…' : `第 ${pageState.page} / ${Math.max(1, pageState.pagination.pages)} 页`}</span><div><button disabled={pageState.loading || !pageState.pagination.hasPrevious} onClick={() => pageState.setPage((page) => page - 1)}>上一页</button><button disabled={pageState.loading || !pageState.pagination.hasNext} onClick={() => pageState.setPage((page) => page + 1)}>下一页</button></div></div>}</aside>}
          <main className="content" id="workspace-content" tabIndex={-1}>
            {view === 'home' && <>{researchContext()&&<aside className="research-context"><strong>研究方向：{researchContext()?.name}</strong><p>{researchContext()?.question}</p><a href="/academy/research#domain-heading">查看来源文献与综述对照</a><small>方向来自阅读入口，尚不代表论文实验已复现。</small></aside>}<RoleHome user={user} runs={visibleRuns} onNavigate={setView} onDemoToggle={demoMode ? undefined : toggleDemo} demoMode={demoMode} counts={demoMode ? undefined : pageState.counts} /></>}
            {view === 'overview' && <>{!demoMode && can(user,'runs:create') && <AiExperimentCommand params={draftParams} onChange={setDraftParams} onExecute={submitParameterPlan} />}{selected?.detailLoaded === false ? <div className="run-empty" role="status">正在加载 Run 详情…</div> : selected ? <Overview runs={visibleRuns} selected={selected} onStop={stopRun} canControl={!demoMode && can(user,'runs:create')} /> : <div className="run-empty" role="status"><h1>{!runsLoaded ? '正在加载实验…' : syncError ? '暂时无法加载实验' : '尚无实验'}</h1><p>{!runsLoaded ? '正在连接工作区。' : syncError ? '请检查后端连接，恢复后会自动重试。' : can(user,'runs:create') ? '在右侧配置参数，创建第一个 Run。' : '团队创建实验后，结果将显示在这里。'}</p></div>}</>}
            {view === 'compare' && <Compare runs={comparisonRuns} focusIds={demoMode ? undefined : comparisonFocusIds} onSelection={setCompareIds} />}
            {view === 'artifacts' && (selected?.detailLoaded === false ? <div className="run-empty" role="status">正在加载 Run 详情…</div> : selected ? <Artifacts selected={selected} /> : <div className="run-empty" role="status"><h1>尚无实验诊断</h1><p>选择已上传诊断产物的 Run 后即可查看。</p></div>)}
            {view === 'data' && <><h2 className="sr-only">数据图表与配置</h2><DataLab /></>}
            {view === 'three' && <><h2 className="sr-only">3D 模型、训练空间与仿真视图</h2><ThreeLab /></>}
            {view === 'assets' && <div className={`asset-permission ${can(user,'assets:write')?'':'read-only'} ${can(user,'assets:approve')?'can-approve':''}`}><AssetWorkbench canWrite={can(user,'assets:write')} canApprove={can(user,'assets:approve')} /></div>}
            {view === 'ai-studio' && <><h2 className="sr-only">AI 3D 创作工具</h2><AiStudio /></>}
            {view === 'evaluation' && <Suspense fallback={<p role="status">正在加载视觉评估…</p>}><EvaluationLab canWrite={can(user,'runs:create')} /></Suspense>}
            {view === 'settings' && can(user,'workspace:admin') && (integrated()?<IntegrationSettings/>:<WorkspaceSettings />)}
          </main>
          {!demoMode && can(user,'runs:create') && view !== 'home' && view !== 'data' && view !== 'three' && view !== 'assets' && view !== 'ai-studio' && view !== 'evaluation' && <ParameterLab params={draftParams} onChange={setDraftParams} onSubmit={submitParameterPlan} backendOnline={backendOnline} selectedRun={selected} baselineRun={baselineRun} onSetBaseline={(run) => setBaselineRunId(run.id)} />}
        </div>
      </div>
    </div>
  );
}

export function App(){const Gate=integrated()?ClawOSGate:AuthGate;return <Gate>{(user)=> <WorkspaceApp user={user}/>}</Gate>;}
