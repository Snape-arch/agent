import { useEffect, useState } from 'react';
import type { EvaluationPage } from '../evaluationApi';
import type { ScenePlan } from '../scenarioApi';
import { registerSynthesisDataset, type ImageVersion } from '../visionApi';
import { createSynthesisJob, exportSynthesisPackage, fetchSynthesisArtifact, fetchSynthesisFrames, fetchSynthesisJob, fetchSynthesisJobs, synthesisAction, type SynthesisFrame, type SynthesisJob } from '../synthesisApi';

const statusLabel = { queued: '排队中', running: '渲染中', completed: '已完成', failed: '失败', cancelled: '已取消' };
const reasonLabel: Record<string, string> = { 'insufficient-visible-pixels': '可见像素不足', 'excessive-occlusion': '遮挡过多', 'object-touches-image-border': '主体触及画面边界' };
const message = (value: unknown) => value instanceof Error ? value.message : '渲染操作失败';
function Artifact({ jobId, frame, kind }: { jobId: string; frame: SynthesisFrame; kind: 'image' | 'mask' | 'amodalMask' }) {
  const [url, setUrl] = useState(''), [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); let objectUrl = ''; setUrl(''); setError('');
    fetchSynthesisArtifact(jobId, frame.variantIndex, kind, controller.signal).then((blob) => {
      if (controller.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);
    }).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); });
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [jobId, frame.variantIndex, kind]);
  return error ? <p role="alert">{error}</p> : url ? <img src={url} alt={`变体 ${frame.variantIndex+1} ${kind === 'image' ? 'RGB 渲染图' : kind === 'mask' ? '可见区域掩码' : '遮挡前区域掩码'}`} /> : <p role="status">加载图片…</p>;
}
export function SynthesisWorkbench({ plan, canWrite }: { plan: ScenePlan; canWrite: boolean }) {
  const [start, setStart] = useState(1), [count, setCount] = useState(Math.min(12, plan.variantCount));
  const [pixels, setPixels] = useState(64), [fraction, setFraction] = useState(.2), [rejectClipped, setRejectClipped] = useState(true);
  const [jobs, setJobs] = useState<EvaluationPage<SynthesisJob>>(), [page, setPage] = useState(1), [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState(''), [job, setJob] = useState<SynthesisJob>();
  const [frames, setFrames] = useState<EvaluationPage<SynthesisFrame>>(), [framePage, setFramePage] = useState(1), [frame, setFrame] = useState<SynthesisFrame>();
  const [kind, setKind] = useState<'image' | 'mask' | 'amodalMask'>('image'), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [loading, setLoading] = useState(true), [framesLoading, setFramesLoading] = useState(false);
  const [registration,setRegistration] = useState<ImageVersion>();
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setJobs(undefined);
    fetchSynthesisJobs(plan.id, page, controller.signal).then(setJobs).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [plan.id, page, refresh]);
  useEffect(() => {
    setJob(undefined); setFrames(undefined); setFrame(undefined); setFramePage(1); setRegistration(undefined);
    if (!selected) return;
    const controller = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const { data } = await fetchSynthesisJob(selected, controller.signal);
        if (controller.signal.aborted) return;
        setJob(data);
        setJobs((current) => current ? { ...current, data: current.data.map((item) => item.id === data.id ? data : item) } : current);
        if (['queued', 'running'].includes(data.status)) timer = setTimeout(() => void poll(), 1500);
      } catch (reason) { if (!controller.signal.aborted) setError(message(reason)); }
    };
    void poll(); return () => { controller.abort(); clearTimeout(timer); };
  }, [selected, refresh]);
  useEffect(() => {
    if (!job) return;
    const controller = new AbortController(); setFramesLoading(true); setFrames(undefined);
    fetchSynthesisFrames(job.id, framePage, controller.signal).then(setFrames).catch((reason) => { if (!controller.signal.aborted) setError(message(reason)); })
      .finally(() => { if (!controller.signal.aborted) setFramesLoading(false); });
    return () => controller.abort();
  }, [job?.id, job?.completed, framePage, refresh]);
  const submit = async () => {
    if (!canWrite) return; setBusy(true); setError('');
    try {
      if (!Number.isInteger(start) || !Number.isInteger(count) || count < 1 || count > 64 || start < 1 || start+count-1 > plan.variantCount) throw new Error('请选择场景范围内的 1–64 个连续变体');
      const { data } = await createSynthesisJob(plan.id, { variantIndices: Array.from({ length: count }, (_, i) => start-1+i), minVisiblePixels: pixels, minVisibleFraction: fraction, rejectClipped });
      setSelected(data.id); setPage(1); setRefresh((value) => value+1);
    } catch (reason) { setError(message(reason)); } finally { setBusy(false); }
  };
  const action = async (value: 'cancel' | 'retry') => {
    if (!job || !canWrite) return; setBusy(true); setError('');
    try { await synthesisAction(job.id, value); setRefresh((current) => current+1); } catch (reason) { setError(message(reason)); } finally { setBusy(false); }
  };
  const download = async () => {
    if (!job) return; setBusy(true); setError('');
    try {
      const blob = await exportSynthesisPackage(job.id), url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = `${job.id}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) { setError(message(reason)); } finally { setBusy(false); }
  };
  const register = async () => {
    if (!job || !canWrite) return; setBusy(true); setError('');
    try { const {data}=await registerSynthesisDataset(job.id); setRegistration(data); window.dispatchEvent(new Event('vision-version-created')); }
    catch(reason){setError(message(reason));}finally{setBusy(false);}
  };
  return <div className="synthesis-workbench"><h3>渲染与合成标注</h3>
    <p>CPU 渲染生成 RGB、主体可见掩码、遮挡前掩码及边界框。分类标签沿用你确认的资产关联；不自动验证资产语义。</p>
    <p className="evaluation-note">此后端使用简化光照，与上方 Three.js PBR 预览不同。仅处理静态三角网格，不支持动画、贴图与压缩几何。</p>
    {error && <div className="evaluation-error" role="alert">{error}<button disabled={busy} onClick={() => { setError(''); setRefresh((value) => value+1); }}>重试渲染加载</button></div>}
    {canWrite && <form onSubmit={(event) => { event.preventDefault(); void submit(); }}><fieldset disabled={busy}><legend>生成合成数据</legend><div className="scene-form-grid">
      <label>起始变体（1–{plan.variantCount}）<input aria-label="渲染起始变体" type="number" required min={1} max={plan.variantCount} step={1} value={start} onChange={(event) => setStart(Number(event.target.value))} /></label>
      <label>本批数量（最多 64）<input aria-label="渲染变体数量" type="number" required min={1} max={Math.min(64, plan.variantCount-start+1)} step={1} value={count} onChange={(event) => setCount(Number(event.target.value))} /></label>
      <label>最少可见像素<input aria-label="最少可见像素" type="number" required min={1} max={262144} step={1} value={pixels} onChange={(event) => setPixels(Number(event.target.value))} /></label>
      <label>最小可见比例<input aria-label="最小可见比例" type="number" required min={0} max={1} step="any" value={fraction} onChange={(event) => setFraction(Number(event.target.value))} /></label>
    </div><label className="scene-confirm"><input type="checkbox" checked={rejectClipped} onChange={(event) => setRejectClipped(event.target.checked)} />剔除触及画面边界的主体</label>
      <button type="submit" disabled={busy}>开始渲染与标注</button></fieldset></form>}
    <h4>此场景的生成任务</h4>
    {loading ? <p role="status">加载渲染任务…</p> : !jobs?.data.length ? <p>尚无渲染任务。</p> : <div className="evaluation-list">{jobs.data.map((item) => <button key={item.id} disabled={busy} aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}><strong>{statusLabel[item.status]} · {item.completed}/{item.total} 张</strong><small>{item.id} · 通过 {item.accepted} 张</small></button>)}</div>}
    {jobs && <div className="evaluation-pager" aria-label="渲染任务分页"><span>{jobs.pagination.total} 条 · 第 {page} 页</span><button disabled={busy || loading || !jobs.pagination.hasPrevious} onClick={() => setPage(page-1)}>上一页</button><button disabled={busy || loading || !jobs.pagination.hasNext} onClick={() => setPage(page+1)}>下一页</button></div>}
    {job && <div className="synthesis-detail"><p role="status">{statusLabel[job.status]} · {job.completed}/{job.total} 张 · 通过 {job.accepted} · 剔除 {job.rejected}</p>
      <progress aria-label="渲染进度" value={job.completed} max={job.total} />
      {job.error && <p role="alert">{job.error}</p>}
      {job.digest && <code title={job.digest}>数据清单 SHA-256 {job.digest.slice(0, 20)}…</code>}
      <div className="evaluation-actions">{canWrite && ['queued', 'running'].includes(job.status) && <button disabled={busy} onClick={() => void action('cancel')}>取消渲染</button>}
        {canWrite && ['failed', 'cancelled'].includes(job.status) && <button disabled={busy} onClick={() => void action('retry')}>重试生成任务</button>}
        <button disabled={busy || job.status !== 'completed'} onClick={() => void download()}>下载合成数据包 ZIP</button>
        {canWrite && <button disabled={busy || job.status !== 'completed' || !job.accepted} onClick={() => void register()}>登记合成数据集版本</button>}</div>
      {registration && <p role="status">已登记 {registration.name} v{registration.version} · {registration.sampleCount} 张 · {registration.id}</p>}
      {framesLoading ? <p role="status">加载生成样本…</p> : frames && <div className="evaluation-table-scroll"><table><thead><tr><th>变体</th><th>筛选结果</th><th>可见比例</th><th>可见像素</th><th>操作</th></tr></thead><tbody>{frames.data.map((item) => <tr key={item.variantIndex}><td>{item.variantIndex+1}</td><td>{item.accepted ? '通过' : item.annotation.rejectionReasons.map((reason) => reasonLabel[reason] ?? reason).join('、')}</td><td>{(item.annotation.visibleFraction*100).toFixed(1)}%</td><td>{item.annotation.visiblePixels}</td><td><button onClick={() => setFrame(item)}>查看渲染与掩码</button></td></tr>)}</tbody></table></div>}
      {frames && <div className="evaluation-pager" aria-label="生成样本分页"><span>{frames.pagination.total} 张 · 第 {framePage} 页</span><button disabled={framesLoading || !frames.pagination.hasPrevious} onClick={() => { setFrame(undefined); setFramePage(framePage-1); }}>上一页</button><button disabled={framesLoading || !frames.pagination.hasNext} onClick={() => { setFrame(undefined); setFramePage(framePage+1); }}>下一页</button></div>}
      {frame && <div className="synthesis-frame"><label>查看产物<select aria-label="合成图片类型" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="image">RGB 渲染图</option><option value="mask">可见区域掩码</option><option value="amodalMask">遮挡前区域掩码</option></select></label>
        <Artifact jobId={job.id} frame={frame} kind={kind} /><p>标签 {frame.annotation.label} · 可见边界框 {JSON.stringify(frame.annotation.bbox)} · {frame.accepted ? '已通过筛选' : '已剔除'}</p>
        <code title={frame.artifacts[kind].sha256}>图片 SHA-256 {frame.artifacts[kind].sha256.slice(0, 20)}…</code></div>}
      {job.status === 'completed' && job.accepted === 0 && <p>本批全部被剔除，数据包仍保留审计结果。调整场景或筛选阈值后创建新任务。</p>}
      <p className="evaluation-note">ZIP 将通过与剔除样本分开放置，包含 COCO 标注、分类清单和血缘记录。用于合成训练；独立评估应另保留未参与失败分析的真实测试集。</p>
    </div>}
  </div>;
}
