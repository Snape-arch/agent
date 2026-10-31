import { lazy, Suspense } from 'react';
import type { AiStudioModelData } from '../renderers/AiStudioModelView';
import type { VisualizationPlugin } from '../types';

const AiStudioModelView = lazy(() => import('../renderers/AiStudioModelView').then((module) => ({ default: module.AiStudioModelView })));

const plugin: VisualizationPlugin<AiStudioModelData> = {
  id: 'core.ai-cad-studio-3d', version: '1.0.0', apiVersion: '1.0.0',
  dependencies: [{ name: 'react', range: '^18.3.0' }, { name: 'three', range: '^0.170.0' }],
  isolation: 'trusted', supportedArtifactTypes: ['ai-cad-studio-3d'],
  canRender: (input) => input.type === 'ai-cad-studio-3d' && typeof input.data === 'object' && input.data !== null && 'plan' in input.data,
  createDefaultSpec: (input) => ({ pluginId: 'core.ai-cad-studio-3d', title: input.name, options: { nodeTree: true, overlay: true } }),
  render: ({ input }) => <Suspense fallback={<div className="embedding-loading">正在加载 AI CAD 渲染器…</div>}><AiStudioModelView data={input.data} /></Suspense>,
};

export default plugin;
