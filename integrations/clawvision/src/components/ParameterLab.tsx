import { useEffect, useMemo, useState } from 'react';
import { integrated } from '../clawos';
import { Bookmark, Database, GitCompareArrows, Grid2X2, Play, RotateCcw, Save, Sparkles } from 'lucide-react';
import type { ExperimentParams, ExperimentRun } from '../domain';
import { fetchParameterSnapshots, fetchTrainingProviders, saveParameterSnapshot, type TrainingProvider } from '../api';
import {
  buildGrid,
  buildSweep,
  estimatePlan,
  isEnabled,
  parameterSchema,
  validateParameters,
  type ParameterDefinition,
  type ParameterKey,
} from '../parameterSchema';

export interface ParameterPlan {
  kind: 'single' | 'sweep' | 'grid';
  configs: ExperimentParams[];
  concurrency: number;
  estimateSeconds: number;
  estimatedCost: number;
  trainingProvider: 'simulator' | 'local-python' | 'local-conda';
}

interface Snapshot { id: string; name: string; params: ExperimentParams; createdAt?: string; }
const snapshotKey = 'clawvision.parameter-snapshots.v1';
const numericParameters = parameterSchema.filter((item) => ['number', 'integer'].includes(item.type) && item.id !== 'seed');

function controlValue(definition: ParameterDefinition, params: ExperimentParams) {
  return params[definition.id] as number | string | boolean;
}

function DynamicControl({ definition, params, onChange, error }: { definition: ParameterDefinition; params: ExperimentParams; onChange: (params: ExperimentParams) => void; error?: string }) {
  const enabled = isEnabled(definition, params);
  const value = controlValue(definition, params);
  const set = (next: number | string | boolean) => onChange({ ...params, [definition.id]: next });
  if (definition.type === 'enum') {
    return <label className={`schema-control ${enabled ? '' : 'disabled'}`}><span><b>{definition.label}</b><small>{definition.description}</small></span><select disabled={!enabled} value={String(value)} onChange={(event) => set(event.target.value)}>{definition.options?.map((option) => <option key={String(option.value)} value={String(option.value)}>{option.label}</option>)}</select>{!enabled && <em>{definition.dependsOn?.reason}</em>}</label>;
  }
  if (definition.type === 'boolean') {
    return <label className={`schema-control toggle-control ${enabled ? '' : 'disabled'}`}><span><b>{definition.label}</b><small>{definition.description}</small></span><input type="checkbox" disabled={!enabled} checked={Boolean(value)} onChange={(event) => set(event.target.checked)} />{!enabled && <em>{definition.dependsOn?.reason}</em>}</label>;
  }
  if (definition.id === 'seed') {
    return <label className="schema-control"><span><b>{definition.label}</b><small>{definition.description}</small></span><input className="schema-number" type="number" min={definition.min} max={definition.max} value={Number(value)} onChange={(event) => set(Number(event.target.value))} />{error && <em className="schema-error">{error}</em>}</label>;
  }
  const sliderValue = definition.scale === 'log10' ? Math.log10(Number(value)) : Number(value);
  const min = definition.scale === 'log10' ? Math.log10(definition.min!) : definition.min!;
  const max = definition.scale === 'log10' ? Math.log10(definition.max!) : definition.max!;
  const step = definition.scale === 'log10' ? 0.1 : definition.step!;
  const progress = (sliderValue - min) / (max - min) * 100;
  return <label className={`schema-control range-control ${enabled ? '' : 'disabled'}`}><span><b>{definition.label}</b><small>{definition.description}</small></span><input className="schema-number range-number" type="number" aria-label={`${definition.label} 精确值`} disabled={!enabled} min={definition.min} max={definition.max} step={definition.step} value={Number(value)} onChange={(event) => set(Number(event.target.value))} /><input type="range" disabled={!enabled} min={min} max={max} step={step} value={sliderValue} style={{ '--progress': `${progress}%` } as React.CSSProperties} onChange={(event) => set(definition.scale === 'log10' ? Number((10 ** Number(event.target.value)).toPrecision(3)) : Number(event.target.value))} />{error && <em className="schema-error">{error}</em>}{!enabled && <em>{definition.dependsOn?.reason}</em>}</label>;
}

export function ParameterLab({ params, onChange, onSubmit, backendOnline, selectedRun, baselineRun, onSetBaseline }: {
  params: ExperimentParams;
  onChange: (params: ExperimentParams) => void;
  onSubmit: (plan: ParameterPlan) => Promise<void>;
  backendOnline: boolean;
  selectedRun?: ExperimentRun;
  baselineRun?: ExperimentRun;
  onSetBaseline: (run: ExperimentRun) => void;
}) {
  const [mode, setMode] = useState<ParameterPlan['kind']>('single');
  const [sweepKey, setSweepKey] = useState<ParameterKey>('learningRate');
  const [gridYKey, setGridYKey] = useState<ParameterKey>('batchSize');
  const [count, setCount] = useState(3);
  const [concurrency, setConcurrency] = useState(2);
  const [submitting, setSubmitting] = useState(false);
  const [providers, setProviders] = useState<TrainingProvider[]>([]);
  const [trainingProvider, setTrainingProvider] = useState<ParameterPlan['trainingProvider']>('simulator');
  const [snapshots, setSnapshots] = useState<Snapshot[]>(() => {
    try { return JSON.parse(localStorage.getItem(snapshotKey) ?? '[]'); } catch { return []; }
  });
  useEffect(() => localStorage.setItem(snapshotKey, JSON.stringify(snapshots)), [snapshots]);
  useEffect(() => { fetchParameterSnapshots().then(({ data }) => { if (data.length) setSnapshots(data); }).catch(() => undefined); }, []);
  useEffect(() => { fetchTrainingProviders().then(({ data }) => { setProviders(data); if (!integrated() && data.some((item) => item.id === 'local-conda' && item.configured)) setTrainingProvider('local-conda'); }).catch(() => undefined); }, []);
  const errors = validateParameters(params);
  const configs = useMemo(() => mode === 'single' ? [params] : mode === 'sweep' ? buildSweep(params, sweepKey, count) : buildGrid(params, sweepKey, gridYKey, count), [count, gridYKey, mode, params, sweepKey]);
  const estimate = useMemo(() => estimatePlan(configs, concurrency), [configs, concurrency]);
  const changed = baselineRun ? parameterSchema.filter((item) => baselineRun.params[item.id] !== params[item.id]) : [];
  const groups = ['优化策略', '训练设置', '运行环境'] as const;

  const submit = async () => {
    if (Object.values(errors).some(Boolean) || !backendOnline) return;
    setSubmitting(true);
    try { await onSubmit({ kind: mode, configs, concurrency, estimateSeconds: estimate.seconds, estimatedCost: estimate.cost, trainingProvider }); } finally { setSubmitting(false); }
  };
  const saveSnapshot = () => {
    const name = `快照 ${snapshots.length + 1}`;
    saveParameterSnapshot({ name, runId: selectedRun?.id, params }).then(({ data }) => setSnapshots((current) => [data, ...current].slice(0, 12))).catch(() => setSnapshots((current) => [{ id: crypto.randomUUID(), name, params }, ...current].slice(0, 12)));
  };

  return <aside className="parameter-panel p3-panel">
    <div className="queue-config"><label>Training Provider<select aria-label="训练执行器" value={trainingProvider} onChange={(event) => setTrainingProvider(event.target.value as ParameterPlan['trainingProvider'])}>{providers.length ? providers.map((item) => <option key={item.id} value={item.id} disabled={!item.configured}>{item.label}{item.gpu ? ' · GPU' : ''}</option>) : <option value="simulator">Simulator</option>}</select></label></div>
    <div className="panel-kicker"><Grid2X2 size={14} /> PARAMETER LAB · P3</div>
    <div className="baseline-box">
      <div><span>BASELINE</span><strong>{baselineRun?.name ?? '尚未锁定'}</strong></div>
      <button disabled={!selectedRun} onClick={() => { if (selectedRun) { onSetBaseline(selectedRun); onChange(selectedRun.params); } }}><Bookmark size={13} />锁定当前 Run</button>
    </div>
    {baselineRun && <div className="before-after"><GitCompareArrows size={14} /><div><strong>Before / After</strong><span>{changed.length ? `${changed.length} 个参数已改变：${changed.slice(0, 3).map((item) => item.label).join('、')}` : '参数与 Baseline 一致'}</span></div></div>}
    <div className="lab-mode">{(['single','sweep','grid'] as const).map((item) => <button key={item} className={mode === item ? 'active' : ''} onClick={() => setMode(item)}>{item === 'single' ? '单次' : item === 'sweep' ? '单参数 Sweep' : '二维网格'}</button>)}</div>
    {groups.map((group) => <div className="control-group schema-group" key={group}><div className="control-group-title">{group}</div>{parameterSchema.filter((item) => item.group === group).map((definition) => <DynamicControl key={definition.id} definition={definition} params={params} onChange={onChange} error={errors[definition.id]} />)}</div>)}
    {mode !== 'single' && <div className="search-config"><label>X 参数<select value={sweepKey} onChange={(event) => setSweepKey(event.target.value as ParameterKey)}>{numericParameters.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>{mode === 'grid' && <label>Y 参数<select value={gridYKey} onChange={(event) => setGridYKey(event.target.value as ParameterKey)}>{numericParameters.filter((item) => item.id !== sweepKey).map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label>}<label>采样点<select value={count} onChange={(event) => setCount(Number(event.target.value))}><option value="3">3</option><option value="4">4</option><option value="5">5</option></select></label></div>}
    <div className="queue-config"><label>并发限制<select value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))}><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></label><span>{configs.length} Runs</span></div>
    <div className="estimate-box"><Sparkles size={14} /><div><strong>预计 {Math.ceil(estimate.seconds)} 秒 · ¥{estimate.cost.toFixed(3)}</strong><span>按 {concurrency} 并发、模型规模和训练轮数估算</span></div></div>
    <div className="snapshot-actions"><button onClick={saveSnapshot}><Save size={13} />保存快照</button><button onClick={() => onChange(parameterSchema.reduce((next, item) => ({ ...next, [item.id]: item.defaultValue }), {} as ExperimentParams))}><RotateCcw size={13} />恢复默认</button></div>
    {snapshots.length > 0 && <div className="snapshot-list">{snapshots.map((snapshot) => <button key={snapshot.id} onClick={() => onChange(snapshot.params)}>{snapshot.name}<span>{snapshot.params.optimizer} · {snapshot.params.learningRate}</span></button>)}</div>}
    <button className="run-button" onClick={submit} disabled={submitting || !backendOnline || Object.values(errors).some(Boolean)}><Play size={16} fill="currentColor" />{submitting ? '正在创建队列…' : mode === 'single' ? integrated() ? trainingProvider==='simulator' ? '创建模拟实验并对比' : '创建训练任务并对比' : '创建真实 Run 并对比' : `提交 ${configs.length} 个 Run`}</button>
    <div className="local-note"><Database size={13} />{backendOnline ? '队列与参数计划将持久化' : '需要启动后端才能执行真实实验'}</div>
  </aside>;
}
