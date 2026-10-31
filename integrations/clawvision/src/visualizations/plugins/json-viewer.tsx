import type { VisualizationPlugin } from '../types';

const plugin: VisualizationPlugin = {
  id: 'core.json-viewer',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['json', 'application/json'],
  canRender: (input) => ['json', 'application/json'].includes(input.type) || input.mimeType?.includes('json') === true,
  createDefaultSpec: (input) => ({ pluginId: 'core.json-viewer', title: input.name, options: { collapsed: false } }),
  render: ({ input }) => <pre className="json-viewer" aria-label={`${input.name} JSON`}><code>{JSON.stringify(input.data, null, 2)}</code></pre>,
};

export default plugin;
