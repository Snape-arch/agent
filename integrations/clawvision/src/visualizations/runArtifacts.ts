import type { ExperimentRun } from '../domain';
import type { ArtifactSchema } from './types';

export function timeSeriesArtifact(runs: ExperimentRun[], metric: 'trainLoss' | 'valLoss' | 'accuracy', options: Record<string, unknown> = {}): ArtifactSchema {
  return { id: `timeseries-${metric}-${runs.map((run) => run.id).join('-')}`, type: 'timeseries', name: metric, data: { runs, metric }, metadata: options };
}

export function logArtifact(run: ExperimentRun): ArtifactSchema {
  return { id: `logs-${run.id}`, type: 'logs', name: '运行日志', data: { runId: run.id, lines: run.logs, status: run.status, latest: run.metrics.at(-1) } };
}

export function parameterTableArtifact(run: ExperimentRun): ArtifactSchema {
  return {
    id: `params-${run.id}`,
    type: 'table',
    name: '本次实验配置',
    data: {
      columns: [{ key: 'key', label: '参数' }, { key: 'value', label: '值' }],
      rows: Object.entries(run.params).filter(([key])=>!key.startsWith('_')).map(([key, value]) => ({
        key: ({learningRate:'学习率',batchSize:'批次大小',dropout:'Dropout',optimizer:'优化器',epochs:'训练轮数',seed:'随机种子',weightDecay:'权重衰减',mixedPrecision:'混合精度',modelDepth:'模型规模'} as Record<string,string>)[key] || key,
        value: typeof value==='boolean' ? value?'开启':'关闭' : value==null ? '—' : String(value),
      })),
    },
  };
}

export function compareTableArtifact(runs: ExperimentRun[]): ArtifactSchema {
  return {
    id: `compare-${runs.map((run) => run.id).join('-')}`,
    type: 'table',
    name: '参数与结果',
    data: {
      columns: [
        { key: 'run', label: 'Run' }, { key: 'optimizer', label: 'Optimizer' }, { key: 'learningRate', label: 'Learning rate' },
        { key: 'batch', label: 'Batch' }, { key: 'dropout', label: 'Dropout' }, { key: 'accuracy', label: 'Accuracy' }, { key: 'valLoss', label: 'Val loss' },
      ],
      rows: runs.map((run) => ({
        run: run.name, optimizer: run.params.optimizer, learningRate: run.params.learningRate, batch: run.params.batchSize,
        dropout: run.params.dropout, accuracy: run.metrics.at(-1)?.accuracy == null ? '—' : `${((run.metrics.at(-1)!.accuracy * 100).toFixed(1))}%`,
        valLoss: run.metrics.at(-1)?.valLoss == null ? '—' : run.metrics.at(-1)!.valLoss.toFixed(3),
      })),
    },
  };
}

export function diagnosticArtifacts(run: ExperimentRun): ArtifactSchema[] {
  const builtIns: ArtifactSchema[] = [
    { id: `confusion-${run.id}`, type: 'confusion-matrix', name: '混淆矩阵', data: run.confusion, metadata: { kicker: 'Classification' } },
    { id: `embedding-${run.id}`, type: 'embedding-3d', name: '3D Embedding', data: run.embedding, metadata: { kicker: 'Feature space' } },
    { id: `scatter-${run.id}`, type: 'scatter-2d', name: '2D Embedding', data: run.embedding, metadata: { kicker: 'Projection' } },
    { id: `samples-${run.id}`, type: 'image-grid', name: '样本预测', data: run.samples, metadata: { kicker: 'Prediction review', span: 2 } },
    { id: `json-${run.id}`, type: 'json', name: '参数 JSON', data: run.params, mimeType: 'application/json', metadata: { kicker: 'Raw data', span: 2 } },
  ];
  const uploaded = (run.artifacts ?? []).map((artifact): ArtifactSchema => ({
    id: artifact.id,
    type: artifact.type,
    name: artifact.name,
    mimeType: artifact.mimeType,
    data: artifact.content,
    metadata: { step: artifact.step, kicker: 'Uploaded artifact', span: 2 },
  }));
  const uploadedTypes = new Set(uploaded.map((artifact) => artifact.type));
  return [...builtIns.filter((artifact) => !uploadedTypes.has(artifact.type) && (
    !Array.isArray(artifact.data) || artifact.data.length > 0
  )), ...uploaded];
}
