import type { SandboxedPluginManifest, VisualizationPlugin } from './types';

function SandboxedFrame({ source, input }: { source: string; input: unknown }) {
  const payload = JSON.stringify(input).replace(/</g, '\\u003c');
  const script = source.replace(/<\/script/gi, '<\\/script');
  const srcDoc = `<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:"><div id="root"></div><script>const input=${payload};const root=document.getElementById('root');try{(${script})(root,input)}catch(error){root.textContent='Sandboxed plugin error: '+error.message}<\/script>`;
  return <iframe className="plugin-sandbox" sandbox="allow-scripts" referrerPolicy="no-referrer" srcDoc={srcDoc} title="第三方可视化插件沙箱" />;
}

export function createSandboxedPlugin(manifest: SandboxedPluginManifest): VisualizationPlugin {
  return {
    id: manifest.id,
    version: manifest.version,
    apiVersion: manifest.apiVersion,
    dependencies: manifest.dependencies ?? [],
    isolation: 'sandboxed-iframe',
    supportedArtifactTypes: manifest.supportedArtifactTypes,
    canRender: (input) => manifest.supportedArtifactTypes.includes(input.type),
    createDefaultSpec: (input) => ({ pluginId: manifest.id, title: input.name }),
    render: ({ input }) => <SandboxedFrame source={manifest.rendererSource} input={input} />,
  };
}
