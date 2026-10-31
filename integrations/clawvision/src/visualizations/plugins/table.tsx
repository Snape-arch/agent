import type { VisualizationPlugin } from '../types';

interface TableData { columns: Array<{ key: string; label: string }>; rows: Array<Record<string, unknown>> }

const plugin: VisualizationPlugin<TableData> = {
  id: 'core.table',
  version: '1.0.0', apiVersion: '1.0.0', dependencies: [{ name: 'react', range: '^18.3.0' }], isolation: 'trusted',
  supportedArtifactTypes: ['table'],
  canRender: (input) => input.type === 'table' && Array.isArray((input.data as TableData | undefined)?.columns) && Array.isArray((input.data as TableData | undefined)?.rows),
  createDefaultSpec: (input) => ({ pluginId: 'core.table', title: input.name }),
  render: ({ input }) => <div className="plugin-table-wrap"><table className="plugin-table" aria-label={input.name}>
    <thead><tr>{input.data.columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
    <tbody>{input.data.rows.map((row, index) => <tr key={String(row.id ?? row.key ?? index)}>{input.data.columns.map((column) => <td key={column.key}>{String(row[column.key] ?? '—')}</td>)}</tr>)}</tbody>
  </table></div>,
};

export default plugin;
