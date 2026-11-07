import type { ReactNode } from 'react';

export const VISUALIZATION_API_VERSION = '1.0.0';

export interface PluginDependency {
  name: string;
  range: string;
  optional?: boolean;
}

export interface ArtifactSchema<T = unknown> {
  id: string;
  type: string;
  name: string;
  mimeType?: string;
  data: T;
  metadata?: Record<string, unknown>;
}

export interface VisualizationSpec {
  id?: string;
  pluginId: string;
  title?: string;
  options?: Record<string, unknown>;
  datasetId?: string;
  layout?: { x: number; y: number; w: number; h: number };
  filters?: Record<string, unknown>;
  version?: number;
}

export interface VisualizationRuntime {
  filters?: Record<string, unknown>;
  onFilterChange?: (field: string, value: unknown) => void;
}

export interface RendererProps<T = unknown> {
  input: ArtifactSchema<T>;
  spec: VisualizationSpec;
  runtime?: VisualizationRuntime;
}

export interface VisualizationPlugin<T = unknown> {
  id: string;
  version: string;
  apiVersion: string;
  dependencies: PluginDependency[];
  isolation: 'trusted' | 'sandboxed-iframe';
  supportedArtifactTypes: string[];
  canRender(input: ArtifactSchema): boolean;
  createDefaultSpec(input: ArtifactSchema): VisualizationSpec;
  render(props: RendererProps<T>): ReactNode;
}

export interface SandboxedPluginManifest {
  id: string;
  version: string;
  apiVersion: string;
  dependencies?: PluginDependency[];
  supportedArtifactTypes: string[];
  rendererSource: string;
}
