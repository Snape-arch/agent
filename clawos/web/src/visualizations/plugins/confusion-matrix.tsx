import { ConfusionMatrix } from '../../components/ConfusionMatrix';
import type { VisualizationPlugin } from '../types';

const plugin: VisualizationPlugin<number[][]> = {
  id: 'core.confusion-matrix',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['confusion-matrix'],
  canRender: (input) => input.type === 'confusion-matrix' && Array.isArray(input.data) && (input.data as unknown[]).every(Array.isArray),
  createDefaultSpec: (input) => ({ pluginId: 'core.confusion-matrix', title: input.name }),
  render: ({ input }) => <ConfusionMatrix values={input.data} />,
};

export default plugin;
