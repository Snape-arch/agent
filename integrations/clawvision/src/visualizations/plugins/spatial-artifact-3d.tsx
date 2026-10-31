import { lazy, Suspense } from 'react';
import type { SimulationFrame } from '../renderers/SimulationReplayView';
import type { VisualizationPlugin } from '../types';

const SimulationReplayView = lazy(() => import('../renderers/SimulationReplayView').then((module) => ({ default: module.SimulationReplayView })));
type SpatialData = { step?: number; points?: Array<[number, number, number]>; trajectory?: Array<[number, number, number]>; vectors?: SimulationFrame['vectors']; frames?: SimulationFrame[] };
const supported = ['point-cloud-3d', 'trajectory-3d', 'vector-field-3d'];

const plugin: VisualizationPlugin<SpatialData> = {
  id: 'core.spatial-artifact-3d', version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }, { name: 'three', range: '^0.170.0' }], isolation: 'trusted', supportedArtifactTypes: supported,
  canRender: (input) => supported.includes(input.type) && Boolean(input.data),
  createDefaultSpec: (input) => ({ pluginId: 'core.spatial-artifact-3d', title: input.name }),
  render: ({ input }) => {
    const frames = input.data.frames?.length ? input.data.frames : [{ step: input.data.step ?? Number(input.metadata?.step ?? 0), points: input.data.points ?? [], trajectory: input.data.trajectory ?? [], vectors: input.data.vectors ?? [] }];
    return <Suspense fallback={<div className="embedding-loading">正在加载空间产物…</div>}><SimulationReplayView frames={frames} /></Suspense>;
  },
};
export default plugin;
