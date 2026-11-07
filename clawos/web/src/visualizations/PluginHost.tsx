import { Component, type ErrorInfo, type ReactNode } from 'react';
import type { ArtifactSchema, VisualizationRuntime, VisualizationSpec, VisualizationPlugin } from './types';
import { visualizationRegistry } from './registry';

class PluginErrorBoundary extends Component<{ pluginId: string; children: ReactNode }, { error?: Error }> {
  state: { error?: Error } = {};
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(`Visualization plugin failed: ${this.props.pluginId}`, error, info.componentStack); }
  render() { return this.state.error ? <div className="plugin-error"><strong>插件加载失败</strong><span>{this.props.pluginId}</span><small>{this.state.error.message}</small><button onClick={() => this.setState({ error: undefined })}>重试</button></div> : this.props.children; }
}

function PluginRenderer({ plugin, input, spec, runtime }: { plugin: VisualizationPlugin; input: ArtifactSchema; spec: VisualizationSpec; runtime?: VisualizationRuntime }) {
  return plugin.render({ input, spec, runtime });
}

export function PluginHost({ input, pluginId, spec, runtime }: { input: ArtifactSchema; pluginId?: string; spec?: VisualizationSpec; runtime?: VisualizationRuntime }) {
  const plugin = pluginId ? visualizationRegistry.get(pluginId) : visualizationRegistry.resolve(input);
  if (!plugin) return <div className="plugin-empty">没有可渲染 {input.type} 的插件</div>;
  const resolvedSpec = spec ?? plugin.createDefaultSpec(input);
  return <div className="plugin-host" data-plugin-id={plugin.id} data-plugin-version={plugin.version}><PluginErrorBoundary pluginId={plugin.id}><PluginRenderer plugin={plugin} input={input} spec={resolvedSpec} runtime={runtime} /></PluginErrorBoundary></div>;
}

export function PluginGallery({ inputs }: { inputs: ArtifactSchema[] }) {
  return <div className="artifact-grid">{inputs.map((input) => {
    const plugin = visualizationRegistry.resolve(input);
    if (!plugin) return null;
    const span = input.metadata?.span === 2 ? 'span-2' : '';
    return <section className={`card plugin-card ${span}`} key={input.id}>
      <div className="card-head"><div><span>{String(input.metadata?.kicker ?? input.type).toUpperCase()}</span><h3>{input.name}</h3></div><small className="plugin-id">{plugin.id}</small></div>
      <PluginHost input={input} />
    </section>;
  })}</div>;
}
