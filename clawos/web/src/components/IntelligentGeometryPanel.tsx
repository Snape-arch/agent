import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Bot, CheckCircle2, Cpu, Play, ShieldCheck, Square, Undo2 } from 'lucide-react';
import {
  cancelGeometryJob,
  createSceneAgentRun,
  createSceneGeometryJob,
  fetchGeometryJob,
  fetchGeometryProviders,
  fetchModelAsset,
  fetchModelScene,
  sceneAgentAction,
  streamSceneAgentRun,
  type GeometryJob,
  type GeometryProvider,
  type ModelAsset,
  type ModelScene,
  type SceneAgentRun,
} from '../api';

const agentTerminal = new Set(['ready', 'completed', 'awaiting-confirmation', 'rejected', 'failed', 'cancelled', 'stale']);
const geometryTerminal = new Set(['completed', 'failed', 'cancelled']);

interface Props {
  scene: ModelScene;
  selectedIds: string[];
  onPreview: (asset?: ModelAsset) => void;
  onCompleted: (scene: ModelScene) => void;
}

export function IntelligentGeometryPanel({ scene, selectedIds, onPreview, onCompleted }: Props) {
  const [command, setCommand] = useState('把最大的部件向上移动 5cm，并改成蓝色金属');
  const [agent, setAgent] = useState<SceneAgentRun>();
  const [providers, setProviders] = useState<GeometryProvider[]>([]);
  const [provider, setProvider] = useState('builtin-voxel');
  const [geometry, setGeometry] = useState<GeometryJob>();
  const stopStream = useRef<() => void>();

  useEffect(() => {
    fetchGeometryProviders().then(({ data }) => {
      setProviders(data);
      const preferred = data.find((item) => item.configured && item.exact) ?? data.find((item) => item.configured);
      if (preferred) setProvider(preferred.id);
    }).catch(() => setProviders([]));
    return () => stopStream.current?.();
  }, []);

  useEffect(() => {
    const preview = agent?.preview?.asset;
    if (!preview) return;
    const now = new Date().toISOString();
    onPreview({ id: `agent-preview-${agent.id}`, name: preview.name, format: preview.format, version: scene.version, folder: '/', stage: 'preview', tags: ['agent-preview'], metadata: { agentRunId: agent.id }, content: { base64: preview.base64, resources: preview.resources }, createdAt: now, updatedAt: now });
  }, [agent?.preview?.objectKey]);

  const watchAgent = (id: string) => {
    stopStream.current?.();
    stopStream.current = streamSceneAgentRun(id, setAgent, () => undefined);
  };

  const startAgent = async () => {
    if (!command.trim()) return;
    onPreview(undefined);
    const run = (await createSceneAgentRun(scene.id, { command, maxCycles: 3 })).data;
    setAgent(run);
    watchAgent(run.id);
  };

  const act = async (action: 'confirm' | 'apply' | 'reject' | 'cancel') => {
    if (!agent) return;
    const run = (await sceneAgentAction(agent.id, action)).data;
    setAgent(run);
    if (action === 'confirm') watchAgent(agent.id);
    if (action === 'apply' && run.status === 'completed') {
      onPreview(undefined);
      onCompleted((await fetchModelScene(scene.id, true)).data);
    }
    if (action === 'reject' || action === 'cancel') onPreview(undefined);
  };

  const watchGeometry = async (id: string) => {
    let job = (await fetchGeometryJob(id)).data;
    let previewId = '';
    while (!geometryTerminal.has(job.status)) {
      setGeometry(job);
      if (job.previewAssetId && job.previewAssetId !== previewId) {
        previewId = job.previewAssetId;
        onPreview((await fetchModelAsset(previewId)).data);
      }
      await new Promise((resolve) => window.setTimeout(resolve, 300));
      job = (await fetchGeometryJob(id)).data;
    }
    setGeometry(job);
    if (job.status === 'completed') {
      onPreview(undefined);
      onCompleted((await fetchModelScene(scene.id, true)).data);
    }
  };

  const runGeometry = async (kind: string) => {
    const targetIds = kind === 'exact-boolean' ? selectedIds.slice(0, 2) : selectedIds;
    const operation: Record<string, unknown> = { kind, targetIds, outputFormat: 'glb' };
    if (kind === 'exact-boolean') operation.operator = 'subtract';
    if (kind === 'fillet') operation.radius = 0.02;
    if (kind === 'chamfer') operation.amount = 0.02;
    if (kind === 'retopology') operation.targetFaces = 8000;
    const job = (await createSceneGeometryJob(scene.id, { provider, operation, timeoutSeconds: 1800 })).data;
    setGeometry(job);
    void watchGeometry(job.id);
  };

  const selectedProvider = providers.find((item) => item.id === provider);
  const supports = (operation: string) => !!selectedProvider?.operations.includes(operation);
  const risk = agent?.analysis.risk;
  const canStartBoolean = selectedIds.length === 2;
  const agentMessage = agent ? `${agent.stage} · ${agent.progress}%` : '先分析结构、风险与成本，再生成隔离预览。';
  const decisions = useMemo(() => agent?.decisions.slice(-5).reverse() ?? [], [agent?.decisions]);

  return <section className="card intelligent-geometry-panel">
    <div className="intelligent-column">
      <div className="card-head"><div><span>P3 / SEMANTIC EDIT AGENT</span><h3><Bot size={16} /> 可审计语义编辑</h3></div>{agent && <b className={`risk-${agent.riskLevel}`}>{agent.riskLevel}</b>}</div>
      <textarea aria-label="语义编辑 Agent 命令" value={command} onChange={(event) => setCommand(event.target.value)} />
      <div className="studio-generate-actions">
        <button className="run-button" disabled={!command.trim() || (!!agent && !agentTerminal.has(agent.status))} onClick={startAgent}><Play size={13} />分析并预览</button>
        {agent?.status === 'awaiting-confirmation' && <button onClick={() => act('confirm')}><AlertTriangle size={13} />确认高风险操作</button>}
        {agent?.status === 'ready' && <button className="run-button" onClick={() => act('apply')}><CheckCircle2 size={13} />写入新版本</button>}
        {agent && !['completed', 'rejected', 'failed', 'cancelled', 'stale'].includes(agent.status) && <button onClick={() => act('cancel')}><Square size={12} />取消</button>}
        {agent && ['ready', 'awaiting-confirmation'].includes(agent.status) && <button onClick={() => act('reject')}><Undo2 size={13} />退回并保留源版本</button>}
      </div>
      <div className="agent-summary"><strong>{agentMessage}</strong>{risk && <><span>影响 {risk.affectedNodeIds.length} 节点 · 风险 {risk.score}/100</span><span>预计 {risk.estimatedSeconds}s · ${risk.estimatedCost.toFixed(4)}</span><span><ShieldCheck size={12} />{risk.rollbackStrategy}</span>{risk.warnings.map((warning) => <span key={warning} className="warning">! {warning}</span>)}</>}</div>
      <div className="agent-decisions">{decisions.map((item) => <div key={item.id}><b>{item.stage}</b><span>{item.decision} · {item.reason}</span></div>)}</div>
      {agent?.error && <p className="error-text">{agent.error}</p>}
    </div>
    <div className="intelligent-column">
      <div className="card-head"><div><span>P4 / PROFESSIONAL GEOMETRY WORKER</span><h3><Cpu size={16} /> 精确几何与交换格式</h3></div>{selectedProvider?.exact && <b>EXACT</b>}</div>
      <label>Worker Provider<select value={provider} onChange={(event) => setProvider(event.target.value)}>{providers.map((item) => <option key={item.id} value={item.id} disabled={!item.configured}>{item.label}{item.configured ? '' : '（未配置）'}</option>)}</select></label>
      <small>{selectedProvider ? `${selectedProvider.operations.join(' · ')} · ${selectedProvider.formats.map((item) => item.toUpperCase()).join('/')}` : '正在读取 Provider…'}</small>
      <div className="modifier-buttons geometry-actions">
        <button disabled={!canStartBoolean || !supports('exact-boolean') || !!geometry && !geometryTerminal.has(geometry.status)} onClick={() => runGeometry('exact-boolean')}>Exact Boolean</button>
        <button disabled={!selectedIds.length || !supports('fillet')} onClick={() => runGeometry('fillet')}>True Fillet</button>
        <button disabled={!selectedIds.length || !supports('chamfer')} onClick={() => runGeometry('chamfer')}>Chamfer</button>
        <button disabled={!selectedIds.length || !supports('uv-unwrap')} onClick={() => runGeometry('uv-unwrap')}>UV Unwrap</button>
        <button disabled={!selectedIds.length || !supports('retopology')} onClick={() => runGeometry('retopology')}>Retopology</button>
        <button disabled={!selectedIds.length || !supports('repair')} onClick={() => runGeometry('repair')}>Self-intersection Repair</button>
      </div>
      {geometry && <div className="geometry-progress"><span style={{ width: `${geometry.progress}%` }} /><b>{geometry.stage} · {geometry.progress}%</b><small>{geometry.previewAssetId ? '低清预览已就绪；源版本尚未修改。' : '任务排队或正在准备预览。'}</small>{!geometryTerminal.has(geometry.status) && <button onClick={() => cancelGeometryJob(geometry.id).then(({ data }) => setGeometry(data))}>抢占式取消</button>}{geometry.checkpointKey && <small>Checkpoint: {geometry.checkpointKey}</small>}{geometry.error && <small className="error-text">{geometry.error}</small>}</div>}
    </div>
  </section>;
}
