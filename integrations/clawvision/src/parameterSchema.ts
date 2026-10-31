import { defaultParams, type ExperimentParams } from './domain';

export type ParameterKey = keyof ExperimentParams;
export type ParameterType = 'number' | 'integer' | 'enum' | 'boolean';

export interface ParameterDefinition<K extends ParameterKey = ParameterKey> {
  id: K;
  label: string;
  description: string;
  group: '优化策略' | '训练设置' | '运行环境';
  type: ParameterType;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  scale?: 'linear' | 'log10';
  options?: Array<{ label: string; value: ExperimentParams[K] }>;
  defaultValue: ExperimentParams[K];
  validate?: (value: ExperimentParams[K], params: ExperimentParams) => string | null;
  dependsOn?: { key: ParameterKey; predicate: (value: ExperimentParams[ParameterKey]) => boolean; reason: string };
}

export const parameterSchema: ParameterDefinition[] = [
  { id: 'optimizer', label: '优化器', description: '决定梯度更新策略', group: '优化策略', type: 'enum', defaultValue: defaultParams.optimizer, options: [{ label: 'AdamW', value: 'AdamW' }, { label: 'Adam', value: 'Adam' }, { label: 'SGD', value: 'SGD' }] },
  { id: 'learningRate', label: '学习率', description: '每一步参数更新幅度', group: '优化策略', type: 'number', unit: '', min: 0.0001, max: 0.02, step: 0.0001, scale: 'log10', defaultValue: defaultParams.learningRate, validate: (value) => Number(value) <= 0 ? '学习率必须大于 0' : null },
  { id: 'weightDecay', label: '权重衰减', description: 'L2 正则化强度', group: '优化策略', type: 'number', min: 0, max: 0.1, step: 0.005, defaultValue: defaultParams.weightDecay, dependsOn: { key: 'optimizer', predicate: (value) => value !== 'SGD', reason: '当前执行器仅为 Adam/AdamW 启用独立权重衰减' } },
  { id: 'dropout', label: 'Dropout', description: '训练时随机屏蔽比例', group: '优化策略', type: 'number', min: 0, max: 0.6, step: 0.05, defaultValue: defaultParams.dropout, validate: (value) => Number(value) >= 0.6 ? '高 Dropout 可能导致欠拟合' : null },
  { id: 'batchSize', label: 'Batch size', description: '单步使用的样本数量', group: '训练设置', type: 'integer', unit: 'samples', min: 16, max: 256, step: 16, defaultValue: defaultParams.batchSize, validate: (value) => Number(value) % 16 ? 'Batch size 必须为 16 的倍数' : null },
  { id: 'epochs', label: 'Epochs', description: '完整遍历数据集的次数', group: '训练设置', type: 'integer', unit: 'epochs', min: 10, max: 100, step: 5, defaultValue: defaultParams.epochs },
  { id: 'seed', label: '随机种子', description: '控制实验可复现性', group: '训练设置', type: 'integer', min: 1, max: 99999, step: 1, defaultValue: defaultParams.seed },
  { id: 'modelDepth', label: '模型规模', description: '影响精度、速度与显存', group: '运行环境', type: 'enum', defaultValue: defaultParams.modelDepth, options: [{ label: 'Small', value: 'small' }, { label: 'Base', value: 'base' }, { label: 'Large', value: 'large' }] },
  { id: 'mixedPrecision', label: '混合精度', description: '使用 FP16/BF16 提升吞吐', group: '运行环境', type: 'boolean', defaultValue: defaultParams.mixedPrecision, dependsOn: { key: 'batchSize', predicate: (value) => Number(value) >= 32, reason: 'Batch size ≥ 32 时混合精度收益更明显' } },
];

export function validateParameters(params: ExperimentParams) {
  const errors: Partial<Record<ParameterKey, string>> = {};
  for (const definition of parameterSchema) {
    const value = params[definition.id] as never;
    const issue = definition.validate?.(value, params);
    if (issue) errors[definition.id] = issue;
    if (typeof value === 'number' && definition.min != null && value < definition.min) errors[definition.id] = `最小值为 ${definition.min}`;
    if (typeof value === 'number' && definition.max != null && value > definition.max) errors[definition.id] = `最大值为 ${definition.max}`;
  }
  return errors;
}

export function isEnabled(definition: ParameterDefinition, params: ExperimentParams) {
  return !definition.dependsOn || definition.dependsOn.predicate(params[definition.dependsOn.key]);
}

export function estimatePlan(configs: ExperimentParams[], concurrency: number) {
  const seconds = configs.reduce((sum, params) => {
    const depth = params.modelDepth === 'large' ? 2.15 : params.modelDepth === 'small' ? 0.62 : 1;
    const precision = params.mixedPrecision ? 0.72 : 1;
    const batch = 64 / params.batchSize;
    return sum + params.epochs * 1.4 * depth * precision * Math.max(0.45, batch);
  }, 0) / Math.max(1, concurrency);
  return { seconds: Math.max(2, seconds), cost: Math.max(0.001, seconds / 3600 * 0.65) };
}

export function sweepValues(definition: ParameterDefinition, count: number) {
  if (definition.min == null || definition.max == null) return [];
  if (definition.scale === 'log10') {
    const min = Math.log10(definition.min);
    const max = Math.log10(definition.max);
    return Array.from({ length: count }, (_, index) => Number((10 ** (min + (max - min) * index / Math.max(1, count - 1))).toPrecision(3)));
  }
  return Array.from({ length: count }, (_, index) => Number((definition.min! + (definition.max! - definition.min!) * index / Math.max(1, count - 1)).toFixed(6)));
}

export function buildSweep(base: ExperimentParams, key: ParameterKey, count: number) {
  const definition = parameterSchema.find((item) => item.id === key)!;
  return sweepValues(definition, count).map((value) => ({ ...base, [key]: value } as ExperimentParams));
}

export function buildGrid(base: ExperimentParams, xKey: ParameterKey, yKey: ParameterKey, count: number) {
  const xDefinition = parameterSchema.find((item) => item.id === xKey)!;
  const yDefinition = parameterSchema.find((item) => item.id === yKey)!;
  return sweepValues(xDefinition, count).flatMap((x) => sweepValues(yDefinition, count).map((y) => ({ ...base, [xKey]: x, [yKey]: y } as ExperimentParams)));
}
