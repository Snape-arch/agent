import { useMemo, useState } from 'react';
import { Bot, Check, Play, Send, Sparkles } from 'lucide-react';
import { interpretNaturalLanguage, type ExperimentAiPlan } from '../api';
import { createArtifacts, nextMetric, type ExperimentParams } from '../domain';
import type { ParameterPlan } from './ParameterLab';
import { PluginHost } from '../visualizations/PluginHost';
import type { ArtifactSchema } from '../visualizations/types';

type Provider = 'local' | 'openai' | 'deepseek' | 'kimi' | 'qwen';

export function AiExperimentCommand({ params, onChange, onExecute }: {
  params: ExperimentParams;
  onChange: (params: ExperimentParams) => void;
  onExecute: (plan: ParameterPlan) => Promise<void>;
}) {
  const [prompt, setPrompt] = useState('把学习率改成 0.0005，Batch Size 改成 128，显示损失曲线并运行');
  const [provider, setProvider] = useState<Provider>('local');
  const [model, setModel] = useState('');
  const [plan, setPlan] = useState<ExperimentAiPlan>();
  const [message, setMessage] = useState('用自然语言修改参数、选择视图并创建实验。');
  const [busy, setBusy] = useState(false);

  const preview = useMemo<ArtifactSchema | undefined>(() => {
    if (!plan) return undefined;
    if (plan.visualization.pluginId === 'core.table') {
      const rows = Object.keys({ ...params, ...plan.params }).map((key) => ({
        key,
        parameter: key,
        before: String(params[key as keyof ExperimentParams]),
        after: String(plan.params[key as keyof ExperimentParams]),
        changed: params[key as keyof ExperimentParams] === plan.params[key as keyof ExperimentParams] ? '否' : '是',
      }));
      return {
        id: 'ai-experiment-table-preview', type: 'table', name: plan.visualization.title ?? '参数 Before / After',
        data: { columns: [{ key: 'parameter', label: '参数' }, { key: 'before', label: 'Before' }, { key: 'after', label: 'After' }, { key: 'changed', label: '已修改' }], rows },
      };
    }
    if (plan.visualization.pluginId === 'core.embedding-evolution-3d') {
      const frameCount = 6;
      const beforeAccuracy = nextMetric(params, params.epochs).accuracy;
      const afterAccuracy = nextMetric(plan.params, plan.params.epochs).accuracy;
      const frames = Array.from({ length: frameCount }, (_, index) => {
        const progress = index / (frameCount - 1);
        const accuracy = beforeAccuracy + (afterAccuracy - beforeAccuracy) * progress;
        return { step: Math.round(progress * plan.params.epochs), points: createArtifacts(plan.params.seed + index * 7, accuracy).embedding };
      });
      return { id: 'ai-experiment-embedding-preview', type: 'embedding-evolution-3d', name: plan.visualization.title ?? 'Embedding 演化预览', data: { frames } };
    }
    const steps = Array.from({ length: Math.min(plan.params.epochs, 40) }, (_, index) => index + 1);
    const rows = steps.flatMap((step) => {
      const before = nextMetric(params, step);
      const after = nextMetric(plan.params, step);
      return [{ ...before, series: 'Before' }, { ...after, series: 'After' }];
    });
    return {
      id: 'ai-experiment-preview', type: 'time-series', name: plan.visualization.title ?? '自然语言实验预览',
      data: { rows }, metadata: { xField: 'step', yFields: plan.visualization.options?.yFields ?? ['trainLoss', 'valLoss'], seriesField: 'series' },
    };
  }, [params, plan]);

  const runPlan = async (next: ExperimentAiPlan) => {
    const seconds = next.params.epochs * .045;
    const configs = next.configs ?? [next.params];
    const concurrency = Math.min(3, configs.length);
    await onExecute({
      kind: next.jobKind, configs, concurrency,
      estimateSeconds: seconds * configs.length / concurrency,
      estimatedCost: seconds * configs.length / 3600 * .65,
      trainingProvider: 'local-conda',
    });
  };

  const submit = async () => {
    setBusy(true);
    try {
      const response = await interpretNaturalLanguage({
        prompt, mode: 'experiment', currentParams: params, provider,
        model: provider === 'local' ? undefined : model || undefined,
      });
      const next = response.data as ExperimentAiPlan;
      setPlan(next);
      onChange(next.params);
      setMessage(next.explanation);
      if (next.execute) await runPlan(next);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '无法解析命令');
    } finally {
      setBusy(false);
    }
  };

  return <section className="ai-command card">
    <div className="ai-command-head"><div><span><Sparkles size={13} /> NATURAL LANGUAGE CONTROL</span><h3>自然语言实验控制台</h3><p>{message}</p></div>{plan && <b><Check size={13} /> 已应用 {Object.keys(plan.patch).length} 项参数</b>}</div>
    <div className="ai-provider-row">
      <label>推理引擎<select aria-label="实验 AI 提供商" value={provider} onChange={(event) => setProvider(event.target.value as Provider)}><option value="local">本地规则引擎</option><option value="openai">OpenAI</option><option value="deepseek">DeepSeek</option><option value="kimi">Kimi</option><option value="qwen">通义千问</option></select></label>
      {provider !== 'local' && <><label>模型<input aria-label="实验 AI 模型" value={model} onChange={(event) => setModel(event.target.value)} placeholder="输入模型名称" /></label><span className="server-credential-note">凭据由服务端安全配置</span></>}
    </div>
    <div className="ai-command-input"><Bot size={18} /><textarea aria-label="自然语言实验命令" value={prompt} onChange={(event) => setPrompt(event.target.value)} /><button onClick={submit} disabled={busy}><Send size={14} />{busy ? '解析中…' : '解析并应用'}</button></div>
    {plan && <div className="ai-command-result"><div className="command-chips">{Object.entries(plan.patch).map(([key, value]) => <span key={key}>{key}<b>{String(value)}</b></span>)}<span>view<b>{plan.visualization.pluginId.replace('core.', '')}</b></span><span>runs<b>{plan.configs?.length ?? 1}</b></span>{!plan.execute && <button onClick={() => runPlan(plan)}><Play size={12} />创建 Run</button>}</div>{preview && <PluginHost input={preview} spec={plan.visualization} />}</div>}
  </section>;
}
