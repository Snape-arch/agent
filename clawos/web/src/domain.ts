export type RunStatus = 'queued' | 'running' | 'completed' | 'stopped' | 'failed';

export interface RunArtifact {
  id: string;
  name: string;
  type: string;
  mimeType: string;
  step?: number;
  content: unknown;
  createdAt: string;
}

export interface ExperimentParams {
  learningRate: number;
  batchSize: number;
  dropout: number;
  optimizer: 'AdamW' | 'Adam' | 'SGD';
  epochs: number;
  seed: number;
  weightDecay: number;
  mixedPrecision: boolean;
  modelDepth: 'small' | 'base' | 'large';
}

export interface MetricPoint {
  step: number;
  trainLoss: number;
  valLoss: number;
  accuracy: number;
  learningRate: number;
  gpu: number;
}

export interface SamplePrediction {
  id: number;
  actual: number;
  predicted: number;
  confidence: number;
}

export interface EmbeddingPoint {
  x: number;
  y: number;
  z: number;
  cluster: number;
  correct: boolean;
}

export interface ExperimentRun {
  id: string;
  name: string;
  status: RunStatus;
  source?: string;
  errorMessage?: string;
  createdAt: string;
  params: ExperimentParams;
  metrics: MetricPoint[];
  logs: string[];
  confusion: number[][];
  samples: SamplePrediction[];
  embedding: EmbeddingPoint[];
  artifacts?: RunArtifact[];
  color: string;
  revision?: number;
  cursor?: number;
  detailLoaded?: boolean;
  metricCount?: number;
  artifactCount?: number;
  events?: RunEvent[];
}

export interface RunEvent { id: number; message: string; level: string; created_at: string }

export const runColors = ['#7cf7c8', '#ffb86b', '#82aaff', '#ff7ca8', '#c9a7ff'];

function random(seed: number) {
  const value = Math.sin(seed * 12.9898) * 43758.5453;
  return value - Math.floor(value);
}

export function createArtifacts(seed: number, accuracy: number) {
  const confusion = Array.from({ length: 5 }, (_, row) =>
    Array.from({ length: 5 }, (_, col) => {
      const diagonal = row === col;
      return Math.max(1, Math.round((diagonal ? 68 + accuracy * 28 : 2 + (1 - accuracy) * 16) * (0.82 + random(seed + row * 7 + col) * 0.34)));
    }),
  );
  const samples = Array.from({ length: 12 }, (_, index) => {
    const actual = index % 5;
    const correct = random(seed + index * 19) < accuracy;
    return {
      id: index,
      actual,
      predicted: correct ? actual : (actual + 1 + Math.floor(random(seed + index * 31) * 4)) % 5,
      confidence: Math.round((correct ? 72 + random(seed + index) * 26 : 38 + random(seed + index) * 35)),
    };
  });
  const embedding = Array.from({ length: 180 }, (_, index) => {
    const cluster = index % 5;
    const angle = (cluster / 5) * Math.PI * 2;
    const jitter = (axis: number) => (random(seed + index * (17 + cluster) + axis * 997) - 0.5) * 1.7;
    return {
      x: Math.cos(angle) * 3.2 + jitter(1),
      y: Math.sin(angle) * 3.2 + jitter(2),
      z: (cluster - 2) * 0.65 + jitter(3),
      cluster,
      correct: random(seed + index * 23) < accuracy,
    };
  });
  return { confusion, samples, embedding };
}

export function nextMetric(params: ExperimentParams, step: number): MetricPoint {
  const progress = step / params.epochs;
  const lrQuality = Math.exp(-Math.abs(Math.log10(params.learningRate) + 3) * 0.32);
  const batchQuality = 1 - Math.abs(params.batchSize - 64) / 380;
  const dropoutQuality = 1 - Math.abs(params.dropout - 0.2) * 0.8;
  const optimizerQuality = params.optimizer === 'AdamW' ? 1 : params.optimizer === 'Adam' ? 0.965 : 0.9;
  const quality = Math.max(0.68, lrQuality * batchQuality * dropoutQuality * optimizerQuality);
  const noise = (random(params.seed + step * 13) - 0.5) * 0.075;
  const trainLoss = Math.max(0.045, 2.15 * Math.exp(-progress * (4.5 + quality * 2.2)) + 0.08 + noise);
  const overfit = Math.max(0, progress - 0.7) * Math.max(0, 0.16 - params.dropout) * 1.8;
  const valLoss = Math.max(0.07, trainLoss * 1.14 + 0.06 + overfit + Math.abs(noise) * 0.45);
  const accuracy = Math.min(0.992, 0.46 + (0.49 * quality) * (1 - Math.exp(-progress * 5.3)) - overfit * 0.45 + noise * 0.12);
  return {
    step,
    trainLoss: Number(trainLoss.toFixed(4)),
    valLoss: Number(valLoss.toFixed(4)),
    accuracy: Number(Math.max(0.42, accuracy).toFixed(4)),
    learningRate: params.learningRate * (0.5 + 0.5 * Math.cos(Math.PI * progress)),
    gpu: Math.round(Math.min(99, 44 + params.batchSize * 0.43 + random(params.seed + step) * 12)),
  };
}

export function createRun(name: string, params: ExperimentParams, color: string, completed = false): ExperimentRun {
  const metricCount = completed ? params.epochs : 1;
  const metrics = Array.from({ length: metricCount }, (_, index) => nextMetric(params, index + 1));
  const lastAccuracy = metrics.at(-1)?.accuracy ?? 0.5;
  const artifacts = createArtifacts(params.seed, lastAccuracy);
  return {
    id: `run_${Date.now().toString(36)}_${params.seed}`,
    name,
    status: completed ? 'completed' : 'running',
    source: 'ui-simulator',
    createdAt: new Date().toISOString(),
    params,
    metrics,
    logs: completed
      ? ['环境检查完成 · CUDA available', '数据集加载完成 · 12,800 samples', '最佳 checkpoint 已保存', '训练正常结束']
      : ['环境检查完成 · CUDA available', '数据集加载完成 · 12,800 samples', '训练任务已启动'],
    ...artifacts,
    artifacts: [],
    color,
  };
}

export const defaultParams: ExperimentParams = {
  learningRate: 0.001,
  batchSize: 64,
  dropout: 0.2,
  optimizer: 'AdamW',
  epochs: 40,
  seed: 42,
  weightDecay: 0.01,
  mixedPrecision: true,
  modelDepth: 'base',
};

export function initialRuns(): ExperimentRun[] {
  return [
    createRun('baseline-adamw', { ...defaultParams, seed: 42 }, runColors[0], true),
    createRun('larger-batch', { ...defaultParams, batchSize: 128, dropout: 0.1, seed: 87 }, runColors[1], true),
  ].map((run) => ({ ...run, source: 'local-demo' }));
}
