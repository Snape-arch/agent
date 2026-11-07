import type { ArtifactSchema, SandboxedPluginManifest, VisualizationPlugin } from './types';
import { VISUALIZATION_API_VERSION } from './types';
import { createSandboxedPlugin } from './sandbox';

const dependencyCatalog: Record<string, string> = { react: '18.3.1', three: '0.170.0', lucide: '0.468.0' };

function major(version: string) { return version.split('.')[0]; }

export class VisualizationRegistry {
  private readonly plugins = new Map<string, VisualizationPlugin>();

  register(plugin: VisualizationPlugin) {
    if (this.plugins.has(plugin.id)) throw new Error(`Visualization plugin already registered: ${plugin.id}`);
    if (major(plugin.apiVersion) !== major(VISUALIZATION_API_VERSION)) throw new Error(`${plugin.id} requires incompatible visualization API ${plugin.apiVersion}`);
    const missing = plugin.dependencies.filter((dependency) => !dependency.optional && !(dependency.name in dependencyCatalog));
    if (missing.length) throw new Error(`${plugin.id} has missing dependencies: ${missing.map((item) => item.name).join(', ')}`);
    this.plugins.set(plugin.id, plugin);
    return this;
  }

  registerSandboxed(manifest: SandboxedPluginManifest) {
    return this.register(createSandboxedPlugin(manifest));
  }

  get(id: string) {
    return this.plugins.get(id);
  }

  resolve(input: ArtifactSchema) {
    return [...this.plugins.values()].find((plugin) => plugin.supportedArtifactTypes.includes(input.type) && plugin.canRender(input))
      ?? [...this.plugins.values()].find((plugin) => plugin.canRender(input));
  }

  list() {
    return [...this.plugins.values()];
  }
}

export const visualizationRegistry = new VisualizationRegistry();

const pluginModules = import.meta.glob<{ default: VisualizationPlugin }>('./plugins/*.tsx', { eager: true });
Object.values(pluginModules).forEach((module) => visualizationRegistry.register(module.default));
