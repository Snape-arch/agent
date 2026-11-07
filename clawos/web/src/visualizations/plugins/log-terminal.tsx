import type { MetricPoint, RunStatus } from '../../domain';
import type { VisualizationPlugin } from '../types';

interface LogData { runId?: string; lines: string[]; status?: RunStatus; latest?: MetricPoint }

const plugin: VisualizationPlugin<LogData> = {
  id: 'core.log-terminal',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['logs', 'text/x-log'],
  canRender: (input) => ['logs', 'text/x-log'].includes(input.type) && Array.isArray((input.data as LogData | undefined)?.lines),
  createDefaultSpec: (input) => ({ pluginId: 'core.log-terminal', title: input.name }),
  render: ({ input }) => <div className="console"><div className="console-line muted">$ clawvision watch {input.data.runId?.slice(0, 12) ?? 'artifact'}</div>{input.data.lines.map((line, index) => <div className="console-line" key={`${line}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span>{line}</div>)}{input.data.status === 'running' && <div className="console-line active"><span>›</span>epoch {input.data.latest?.step} · val_accuracy {input.data.latest?.accuracy == null ? '—' : `${(input.data.latest.accuracy * 100).toFixed(1)}%`}<b className="cursor" /></div>}</div>,
};

export default plugin;
