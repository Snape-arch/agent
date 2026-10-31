import type { SamplePrediction } from '../../domain';
import type { VisualizationPlugin } from '../types';

type GridItem = SamplePrediction & { imageUrl?: string; label?: string; caption?: string };
const glyphs = ['◒', '△', '◇', '✦', '⬡'];

const plugin: VisualizationPlugin<GridItem[]> = {
  id: 'core.image-grid',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['image-grid', 'sample-predictions'],
  canRender: (input) => ['image-grid', 'sample-predictions'].includes(input.type) && Array.isArray(input.data),
  createDefaultSpec: (input) => ({ pluginId: 'core.image-grid', title: input.name }),
  render: ({ input }) => <div className="sample-grid">{input.data.map((item, index) => {
    const wrong = item.actual !== item.predicted;
    return <div className={`sample ${wrong ? 'wrong' : ''}`} key={item.id ?? index}>
      <div className="sample-image">{item.imageUrl ? <img src={item.imageUrl} alt={item.label ?? `样本 ${index + 1}`} /> : glyphs[item.actual] ?? '●'}</div>
      <div><strong>{item.label ?? `类别 ${item.predicted}`}</strong><span>{item.caption ?? `真实 ${item.actual} · ${item.confidence}%`}</span></div>
    </div>;
  })}</div>,
};

export default plugin;
