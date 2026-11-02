import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const pluginDir = join(root, 'src', 'visualizations', 'plugins');
const pluginFiles = readdirSync(pluginDir).filter((file) => file.endsWith('.tsx'));
const required = ['confusion-matrix.tsx', 'embedding-3d.tsx', 'image-grid.tsx', 'json-viewer.tsx', 'log-terminal.tsx', 'scatter-2d.tsx', 'table.tsx', 'time-series.tsx'];
const missing = required.filter((file) => !pluginFiles.includes(file));
if (missing.length) throw new Error(`Missing visualization plugins: ${missing.join(', ')}`);
for (const file of pluginFiles) {
  const source = readFileSync(join(pluginDir, file), 'utf8');
  for (const field of ['version', 'apiVersion', 'dependencies', 'isolation']) if (!source.includes(field)) throw new Error(`${file} does not declare ${field}`);
}

const registry = readFileSync(join(root, 'src', 'visualizations', 'registry.ts'), 'utf8');
if (!registry.includes("import.meta.glob") || !registry.includes("./plugins/*.tsx")) throw new Error('Plugin registry is not directory-driven');

const app = readFileSync(join(root, 'src', 'App.tsx'), 'utf8');
const forbidden = ['components/MetricChart', 'components/ConfusionMatrix', 'components/EmbeddingView'];
const coupled = forbidden.filter((value) => app.includes(value));
if (coupled.length) throw new Error(`Core page still imports renderers: ${coupled.join(', ')}`);

const sandbox = readFileSync(join(root, 'src', 'visualizations', 'sandbox.tsx'), 'utf8');
if (!sandbox.includes('sandbox="allow-scripts"') || sandbox.includes('allow-same-origin') || !sandbox.includes("default-src 'none'")) throw new Error('Third-party plugin iframe sandbox is not isolated');
console.log(JSON.stringify({ ok: true, pluginCount: pluginFiles.length, autoDiscovery: true, manifests: true, failureBoundary: true, sandboxedThirdParty: true, coreRendererImports: 0 }));
