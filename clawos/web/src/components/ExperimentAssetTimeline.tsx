import { useEffect, useMemo, useState } from 'react';
import { Box, GitCompareArrows, Link2, TimerReset } from 'lucide-react';
import { fetchModelAsset, fetchModelAssets, fetchRunTimeline, linkRunAsset, type ModelAsset, type RunTimeline } from '../api';
import type { ExperimentRun } from '../domain';
import { PluginHost } from '../visualizations/PluginHost';
import type { ArtifactSchema } from '../visualizations/types';

export function ExperimentAssetTimeline({ run, baseline }: { run: ExperimentRun; baseline?: ExperimentRun }) {
  const [timeline, setTimeline] = useState<RunTimeline>();
  const [baselineTimeline, setBaselineTimeline] = useState<RunTimeline>();
  const [assets, setAssets] = useState<ModelAsset[]>([]);
  const [assetId, setAssetId] = useState('');
  const [step, setStep] = useState(0);
  const [activeAsset, setActiveAsset] = useState<ModelAsset>();
  const [beforeAsset, setBeforeAsset] = useState<ModelAsset>();
  const [message, setMessage] = useState('选择模型资产，将 checkpoint 与训练时间轴绑定。');

  const reload = () => Promise.all([fetchRunTimeline(run.id), baseline ? fetchRunTimeline(baseline.id) : Promise.resolve(undefined), fetchModelAssets()]).then(([current, before, catalog]) => {
    setTimeline(current.data); setBaselineTimeline(before?.data); setAssets(catalog.data); setStep((value) => value || current.data.maxStep);
  }).catch(() => setMessage('时间轴服务暂不可用'));
  useEffect(() => { void reload(); }, [run.id, baseline?.id]);

  const currentFrame = useMemo(() => timeline?.frames.filter((frame) => frame.step <= step).at(-1), [timeline, step]);
  const baselineFrame = useMemo(() => baselineTimeline?.frames.filter((frame) => frame.step <= step).at(-1), [baselineTimeline, step]);
  useEffect(() => {
    const currentId = currentFrame?.assets.at(-1)?.asset.id;
    const beforeId = baselineFrame?.assets.at(-1)?.asset.id;
    if (currentId) fetchModelAsset(currentId).then((result) => setActiveAsset(result.data)); else setActiveAsset(undefined);
    if (beforeId) fetchModelAsset(beforeId).then((result) => setBeforeAsset(result.data)); else setBeforeAsset(undefined);
  }, [currentFrame?.assets.at(-1)?.asset.id, baselineFrame?.assets.at(-1)?.asset.id]);

  const bind = async () => {
    if (!assetId) return;
    await linkRunAsset(run.id, { assetId, role: 'checkpoint', step, metadata: { source: 'experiment-timeline' } });
    setMessage(`已把资产绑定到 ${run.name} · step ${step}`); await reload();
  };
  const spatial = (run.artifacts ?? []).filter((artifact) => ['embedding-evolution-3d', 'point-cloud-3d', 'trajectory-3d', 'vector-field-3d', 'simulation-replay-3d'].includes(artifact.type) && (artifact.step ?? 0) <= step).at(-1);
  const modelArtifact: ArtifactSchema = { id: `run-model-${run.id}-${step}`, type: 'cad-model-3d', name: `${run.name} · step ${step}`, data: { name: activeAsset?.name ?? '尚未绑定模型', format: activeAsset?.format, base64: activeAsset?.content?.base64, resources: activeAsset?.content?.resources, version: activeAsset?.version, beforeBase64: beforeAsset?.content?.base64, beforeResources: beforeAsset?.content?.resources } };

  return <section className="card experiment-asset-timeline">
    <div className="card-head"><div><span>RUN × 3D UNIFIED TIMELINE</span><h3>实验、指标、Embedding 与模型版本联动</h3></div><div className="timeline-badges"><span><Box size={12} />{activeAsset?.name ?? '未绑定'}</span>{baseline && <span><GitCompareArrows size={12} />{baseline.name}</span>}</div></div>
    <div className="timeline-toolbar"><select aria-label="选择要绑定的模型资产" value={assetId} onChange={(event) => setAssetId(event.target.value)}><option value="">选择模型资产…</option>{assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name} · v{asset.version} · {asset.stage}</option>)}</select><button onClick={bind} disabled={!assetId}><Link2 size={13} />绑定 checkpoint</button><span>{message}</span></div>
    <label className="unified-timeline"><TimerReset size={15} /><input type="range" min="0" max={Math.max(timeline?.maxStep ?? 1, baselineTimeline?.maxStep ?? 1)} value={Math.min(step, Math.max(timeline?.maxStep ?? 1, baselineTimeline?.maxStep ?? 1))} onChange={(event) => setStep(Number(event.target.value))} /><b>step {step}</b><small>acc {currentFrame?.metrics.accuracy == null ? '—' : `${(currentFrame.metrics.accuracy * 100).toFixed(1)}%`}</small></label>
    <div className="timeline-view-grid"><PluginHost input={modelArtifact} />{spatial ? <PluginHost input={{ id: spatial.id, type: spatial.type, name: spatial.name, data: spatial.content, metadata: { step: spatial.step } }} /> : <div className="timeline-empty"><strong>SDK 可上报 Embedding / 点云 / 轨迹 / 向量场</strong><span>同一滑块将驱动曲线、模型与特征空间演化。</span></div>}</div>
  </section>;
}
