import type { EmbeddingPoint } from '../../domain';
import type { VisualizationPlugin } from '../types';

const colors = ['#7cf7c8', '#ffb86b', '#82aaff', '#ff7ca8', '#c9a7ff'];

const plugin: VisualizationPlugin<EmbeddingPoint[]> = {
  id: 'core.scatter-2d',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['scatter-2d', 'embedding-2d'],
  canRender: (input) => ['scatter-2d', 'embedding-2d'].includes(input.type) && Array.isArray(input.data),
  createDefaultSpec: (input) => ({ pluginId: 'core.scatter-2d', title: input.name, options: { x: 'x', y: 'y' } }),
  render: ({ input }) => {
    const points = input.data;
    const xs = points.map((point) => point.x);
    const ys = points.map((point) => point.y);
    const minX = Math.min(...xs, -1); const maxX = Math.max(...xs, 1);
    const minY = Math.min(...ys, -1); const maxY = Math.max(...ys, 1);
    const px = (value: number) => 24 + ((value - minX) / Math.max(0.001, maxX - minX)) * 552;
    const py = (value: number) => 18 + (1 - (value - minY) / Math.max(0.001, maxY - minY)) * 244;
    return <div className="scatter-wrap"><svg viewBox="0 0 600 280" role="img" aria-label={`${input.name} 二维散点图`}>
      <line x1="24" y1="262" x2="576" y2="262" className="scatter-axis" /><line x1="24" y1="18" x2="24" y2="262" className="scatter-axis" />
      {points.map((point, index) => <circle key={index} cx={px(point.x)} cy={py(point.y)} r={point.correct ? 3.2 : 4.2} fill={point.correct ? colors[point.cluster % colors.length] : '#ff4747'} opacity="0.82" />)}
    </svg></div>;
  },
};

export default plugin;
