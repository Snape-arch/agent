import { lazy, Suspense, useEffect, useState } from 'react';
import type { ModelAsset } from '../api';
import type { EvaluationPage, FailureCase } from '../evaluationApi';
import { SynthesisWorkbench } from './SynthesisWorkbench';
import {
  createScenePlan, defaultSceneConfig, exportScenePlan, fetchSceneAssets, fetchScenePlan, fetchScenePlans, fetchScenePreviewAsset,
  sceneParameters, type SceneConfig, type SceneParameter, type ScenePlan, type ScenePreviewAsset, type SceneSource, type SceneSummary,
} from '../scenarioApi';

const Preview = lazy(() => import('./ScenePlanPreview'));
const message = (value: unknown) => value instanceof Error ? value.message : '场景操作失败';
function download(plan: ScenePlan) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = `${plan.id}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function Page({ result, loading, onPage, label }: { result?: EvaluationPage<unknown>; loading: boolean; onPage: (page: number) => void; label: string }) {
  if (!result) return null;
  const p = result.pagination;
  return <div className="evaluation-pager" aria-label={label}><span>{p.total} 条 · 第 {p.page} / {Math.max(1, p.pages)} 页</span>
    <button disabled={loading || !p.hasPrevious} onClick={() => onPage(p.page - 1)}>上一页</button><button disabled={loading || !p.hasNext} onClick={() => onPage(p.page + 1)}>下一页</button></div>;
}

export function ScenarioWorkbench({ reportId, failure, canWrite, onBusyChange }: { reportId: string; failure?: FailureCase; canWrite: boolean; onBusyChange?: (busy: boolean) => void }) {
  const [source, setSource] = useState<Pick<SceneSource, 'sampleId' | 'label' | 'conditions'>>();
  const [config, setConfig] = useState<SceneConfig>(defaultSceneConfig), [name, setName] = useState('');
  const [assetId, setAssetId] = useState(''), [parentId, setParentId] = useState<string>();
  const [confirmed, setConfirmed] = useState(false);
  const [assets, setAssets] = useState<EvaluationPage<ModelAsset>>(), [assetPage, setAssetPage] = useState(1), [search, setSearch] = useState('');
  const [plans, setPlans] = useState<EvaluationPage<SceneSummary>>(), [page, setPage] = useState(1), [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState(''), [plan, setPlan] = useState<ScenePlan>(), [previewAsset, setPreviewAsset] = useState<ScenePreviewAsset>();
  const [variant, setVariant] = useState(0), [previewRequested, setPreviewRequested] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [assetsLoading, setAssetsLoading] = useState(false), [plansLoading, setPlansLoading] = useState(true), [previewLoading, setPreviewLoading] = useState(false);
  useEffect(() => {
    if (!failure) return;
    setSource(failure); setName(`${failure.sampleId} · 场景变体`); setParentId(undefined); setConfirmed(false); setConfig(defaultSceneConfig()); setNotice('');
  }, [failure]);
  useEffect(() => {
    const controller = new AbortController(); setPlansLoading(true); setPlans(undefined);
    fetchScenePlans(reportId, page, controller.signal).then(setPlans).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); })
      .finally(() => { if (!controller.signal.aborted) setPlansLoading(false); });
    return () => controller.abort();
  }, [reportId, page, refresh]);
  useEffect(() => {
    if (!canWrite || !source) return;
    const controller = new AbortController(); setAssetsLoading(true); setAssets(undefined);
    const timer = setTimeout(() => {
      fetchSceneAssets(assetPage, search, controller.signal).then(setAssets).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); })
        .finally(() => { if (!controller.signal.aborted) setAssetsLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [canWrite, Boolean(source), assetPage, search, refresh]);
  useEffect(() => {
    setPlan(undefined); setPreviewRequested(false); setPreviewAsset(undefined); setVariant(0);
    if (!selected) return;
    const controller = new AbortController();
    fetchScenePlan(selected, controller.signal).then(({ data }) => setPlan(data)).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); });
    return () => controller.abort();
  }, [selected, refresh]);
  useEffect(() => {
    setPreviewAsset(undefined); setPreviewLoading(false);
    if (!plan || !previewRequested) return;
    const controller = new AbortController(); setPreviewLoading(true);
    fetchScenePreviewAsset(plan.id, controller.signal).then(({ data }) => setPreviewAsset(data))
      .catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); })
      .finally(() => { if (!controller.signal.aborted) setPreviewLoading(false); });
    return () => controller.abort();
  }, [plan, previewRequested, refresh]);
  const save = async () => {
    if (!source || !assetId || !confirmed || !canWrite) return;
    setBusy(true); onBusyChange?.(true); setError(''); setNotice('');
    try {
      const { data } = await createScenePlan({ name, reportId, sampleId: source.sampleId, label: source.label, assetId, config, ...(parentId ? { parentId } : {}) });
      setSelected(data.id); setParentId(data.id); setPage(1); setRefresh((value) => value + 1);
      setNotice(`场景 v${data.version} 已保存：${data.variantCount} 个确定变体，尚未渲染或标注。`);
    } catch (reason) { setError(message(reason)); }
    finally { setBusy(false); onBusyChange?.(false); }
  };
  const clone = (value: ScenePlan) => {
    setSource(value.source); setName(value.name); setAssetId(value.assetId); setConfig(value.manifest.config);
    setParentId(value.id); setConfirmed(false); setNotice('已载入保存参数。修改后会创建新版本。');
  };
  const exportPlan = async () => {
    if (!plan) return; setBusy(true); onBusyChange?.(true); setError('');
    try { download((await exportScenePlan(plan.id)).data); } catch (reason) { setError(message(reason)); } finally { setBusy(false); onBusyChange?.(false); }
  };
  return <section id="evaluation-scene-workbench" className="card scene-workbench"><div className="card-head"><h2>5. 失败驱动的 3D 场景</h2></div>
    <p>为一个失败样本选择对应资产，保存受控场景和可复现的变体清单。资产与真实标签的对应关系由你确认。</p>
    {error && <div role="alert" className="evaluation-error">{error}<button disabled={busy} onClick={() => { setError(''); setRefresh((value) => value + 1); }}>重试场景加载</button></div>}
    {notice && <p role="status" className="evaluation-notice">{notice}</p>}
    {canWrite && !source && <p>在上方失败样本表中点击“关联 3D 场景”，开始规划。</p>}
    {canWrite && source && <form className="scene-plan-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <fieldset disabled={busy}><legend>{parentId ? '创建场景新版本' : '新建场景计划'} · {source.sampleId}</legend>
        <p>真实标签：<strong>{source.label}</strong> · {Object.entries(source.conditions).map(([key, value]) => `${key}=${value}`).join(' · ') || '未提供场景条件'}</p>
        <div className="scene-form-grid">
          <label>计划名称<input aria-label="场景计划名称" value={name} required maxLength={200} onChange={(event) => setName(event.target.value)} /></label>
          <label>搜索 3D 资产<input aria-label="搜索场景资产" value={search} onChange={(event) => { setSearch(event.target.value); setAssetPage(1); }} /></label>
          <label>资产版本<select aria-label="场景资产版本" value={assetId} required disabled={assetsLoading} onChange={(event) => { setAssetId(event.target.value); setConfirmed(false); }}>
            <option value="">选择 GLB / OBJ / STL</option>{assetId && !assets?.data.some((item) => item.id === assetId) && <option value={assetId}>{assetId}（已选择）</option>}
            {assets?.data.map((item) => <option key={item.id} value={item.id} disabled={!['glb', 'obj', 'stl'].includes(item.format)}>{item.name} · v{item.version} · {item.format.toUpperCase()} · {item.id}</option>)}
          </select></label>
          <label>随机种子<input aria-label="场景随机种子" type="number" min={0} max={4294967295} step={1} required value={config.seed} onChange={(event) => setConfig({ ...config, seed: Number(event.target.value) })} /></label>
          <label>变体数量（1–256）<input aria-label="场景变体数量" type="number" min={1} max={256} step={1} required value={config.count} onChange={(event) => setConfig({ ...config, count: Number(event.target.value) })} /></label>
          <label>模型颜色<input aria-label="场景模型颜色" type="color" value={config.materialColor} onChange={(event) => setConfig({ ...config, materialColor: event.target.value })} /></label>
          <label>背景颜色<input aria-label="场景背景颜色" type="color" value={config.background} onChange={(event) => setConfig({ ...config, background: event.target.value })} /></label>
        </div>
        {assetsLoading && <p role="status">正在加载资产…</p>}
        {!assetsLoading && assets && !assets.data.length && <p>没有匹配资产。请先在资产库导入自包含 GLB、OBJ 或 STL（不超过 16 MB）。</p>}
        <Page result={assets} loading={assetsLoading || busy} onPage={setAssetPage} label="场景资产分页" />
        <p className="evaluation-note">每一项设置最小值与最大值；相等表示固定值。角度与光照需要人工对应实际失败条件。</p>
        <div className="scene-range-grid">{(Object.entries(sceneParameters) as Array<[SceneParameter, typeof sceneParameters[SceneParameter]]>).map(([key, bounds]) => <div className="scene-range" key={key}><strong>{bounds.label}</strong>
          {([0, 1] as const).map((side) => <label key={side}>{side === 0 ? '最小' : '最大'}<input aria-label={`${bounds.label}${side === 0 ? '最小' : '最大'}`} type="number" required min={bounds.min} max={bounds.max} step="any" value={config.ranges[key][side]} onChange={(event) => {
            const range: [number, number] = [...config.ranges[key]]; range[side] = Number(event.target.value); setConfig({ ...config, ranges: { ...config.ranges, [key]: range } });
          }} /></label>)}
        </div>)}</div>
        <label className="scene-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />我确认所选资产代表真实标签“{source.label}”</label>
        <button type="submit" disabled={busy || assetsLoading || !assetId || !confirmed}>{busy ? '保存中…' : parentId ? '保存场景新版本' : '保存场景计划'}</button>
      </fieldset>
    </form>}
    <h3>此评估的场景计划</h3>
    {plansLoading ? <p role="status">正在加载场景计划…</p> : !plans?.data.length ? <p>尚无保存的场景计划。</p> : <div className="evaluation-list">{plans.data.map((item) => <button key={item.id} disabled={busy} aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}><strong>{item.name} · v{item.version}</strong><small>{item.source.sampleId} → {item.asset.name} v{item.asset.version} · {item.variantCount} 个变体</small></button>)}</div>}
    <Page result={plans} loading={busy || plansLoading} onPage={setPage} label="场景计划分页" />
    {selected && !plan && <p role="status">正在加载场景详情…</p>}
    {plan && <div className="scene-plan-detail"><h3>{plan.name} · v{plan.version}</h3>
      <p>{plan.source.sampleId} · 标签 {plan.source.label} · 资产 {plan.asset.name} v{plan.asset.version}</p>
      <code title={plan.digest}>计划 SHA-256 {plan.digest.slice(0, 20)}…</code><code title={plan.asset.sha256}>资产 SHA-256 {plan.asset.sha256.slice(0, 20)}…</code>
      {plan.parentId && <small>上一版本：{plan.parentId}</small>}
      <div className="evaluation-actions"><button disabled={busy} onClick={() => void exportPlan()}>导出场景清单</button>
        {canWrite && <button disabled={busy} onClick={() => clone(plan)}>修改并创建新版本</button>}
        <button disabled={previewLoading} onClick={() => setPreviewRequested((value) => !value)}>{previewRequested ? '关闭 3D 预览' : '加载 3D 预览'}</button></div>
      <label>查看保存的变体<select aria-label="场景预览变体" value={variant} onChange={(event) => setVariant(Number(event.target.value))}>{plan.manifest.variants.map((item) => <option key={item.index} value={item.index}>变体 {item.index + 1}</option>)}</select></label>
      <details><summary>此变体的精确参数</summary><pre>{JSON.stringify(plan.manifest.variants[variant]?.parameters, null, 2)}</pre></details>
      {previewLoading && <p role="status">正在读取并核验固定资产…</p>}
      {previewAsset && <Suspense fallback={<p role="status">正在加载 3D 预览…</p>}><Preview plan={plan} asset={previewAsset} variant={plan.manifest.variants[variant]} /></Suspense>}
      <p className="evaluation-note">此清单保存人工选择的场景变化，不证明已还原失败原因。</p>
      <SynthesisWorkbench key={plan.id} plan={plan} canWrite={canWrite} />
    </div>}
  </section>;
}
