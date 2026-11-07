import { lazy, Suspense } from 'react';
import type { EmbeddingPoint } from '../../domain';
import type { VisualizationPlugin } from '../types';

const EmbeddingView = lazy(() => import('../../components/EmbeddingView').then((module) => ({ default: module.EmbeddingView })));

const plugin: VisualizationPlugin<EmbeddingPoint[]> = {
  id: 'core.embedding-3d',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }, { name: 'three', range: '^0.170.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['embedding-3d'],
  canRender: (input) => input.type === 'embedding-3d' && Array.isArray(input.data),
  createDefaultSpec: (input) => ({ pluginId: 'core.embedding-3d', title: input.name }),
  render: ({ input }) => <Suspense fallback={<div className="embedding-loading">正在加载 3D 特征空间…</div>}><EmbeddingView points={input.data} /></Suspense>,
};

export default plugin;
