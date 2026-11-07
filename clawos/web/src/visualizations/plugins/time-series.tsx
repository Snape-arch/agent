import { MetricChart } from '../../components/MetricChart';
import type { ExperimentRun } from '../../domain';
import type { VisualizationPlugin } from '../types';

interface TimeSeriesData { runs: ExperimentRun[]; metric: 'trainLoss' | 'valLoss' | 'accuracy' }

const plugin: VisualizationPlugin<TimeSeriesData> = {
  id: 'core.time-series',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['timeseries'],
  canRender: (input) => input.type === 'timeseries' && Array.isArray((input.data as TimeSeriesData | undefined)?.runs),
  createDefaultSpec: (input) => ({ pluginId: 'core.time-series', title: input.name, options: { height: input.metadata?.height ?? 214, smoothing: input.metadata?.smoothing ?? 1 } }),
  render: ({ input, spec }) => <MetricChart runs={input.data.runs} metric={input.data.metric} height={Number(spec.options?.height ?? 214)} smoothing={Number(spec.options?.smoothing ?? 1)} />,
};

export default plugin;
