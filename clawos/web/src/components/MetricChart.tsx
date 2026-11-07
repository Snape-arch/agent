import type { ExperimentRun, MetricPoint } from '../domain';

type MetricKey = 'trainLoss' | 'valLoss' | 'accuracy';

interface MetricChartProps {
  runs: ExperimentRun[];
  metric: MetricKey;
  height?: number;
  smoothing?: number;
}

function smooth(points: MetricPoint[], metric: MetricKey, windowSize: number) {
  if (windowSize <= 1) return points;
  return points.map((point, index) => {
    const start = Math.max(0, index - windowSize + 1);
    const window = points.slice(start, index + 1);
    return { ...point, [metric]: window.reduce((sum, item) => sum + item[metric], 0) / window.length };
  });
}

function pathFor(points: MetricPoint[], metric: MetricKey, width: number, height: number, maxSteps: number, min: number, max: number) {
  if (points.length < 2) return '';
  return points
    .map((point, index) => {
      const x = 44 + (point.step / Math.max(1, maxSteps)) * (width - 60);
      const value = point[metric];
      const y = 12 + (1 - (value - min) / Math.max(0.001, max - min)) * (height - 38);
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');
}

export function MetricChart({ runs, metric, height = 214, smoothing = 1 }: MetricChartProps) {
  const width = 720;
  const values = runs.flatMap((run) => run.metrics.map((point) => point[metric]));
  const rawMax = Math.max(...values, metric === 'accuracy' ? 1 : 1.1);
  const rawMin = Math.min(...values, metric === 'accuracy' ? 0.4 : 0);
  const min = metric === 'accuracy' ? Math.floor(rawMin * 10) / 10 : 0;
  const max = metric === 'accuracy' ? 1 : rawMax * 1.05;
  const maxSteps = Math.max(...runs.map((run) => run.params.epochs), 1);
  const labels = metric === 'accuracy' ? ['100%', `${Math.round(((max + min) / 2) * 100)}%`, `${Math.round(min * 100)}%`] : [max.toFixed(2), ((max + min) / 2).toFixed(2), min.toFixed(2)];

  return (
    <div className="metric-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${metric} 指标曲线`}>
        <defs>
          <linearGradient id={`area-${metric}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#7cf7c8" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#7cf7c8" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[12, height / 2, height - 26].map((y, index) => (
          <g key={y}>
            <line x1="44" y1={y} x2={width - 16} y2={y} stroke="rgba(255,255,255,.08)" strokeDasharray="3 5" />
            <text x="4" y={y + 4} fill="#9eb2aa" fontSize="12">{labels[index]}</text>
          </g>
        ))}
        {runs.map((run) => (
          <path
            key={run.id}
            d={pathFor(smooth(run.metrics, metric, smoothing), metric, width, height, maxSteps, min, max)}
            fill="none"
            stroke={run.color}
            strokeWidth={run.status === 'running' ? 3 : 2}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={run.status === 'stopped' ? 0.45 : 1}
          />
        ))}
        <text x="44" y={height - 5} fill="#9eb2aa" fontSize="12">1</text>
        <text x={width - 32} y={height - 5} fill="#9eb2aa" fontSize="12">{maxSteps} epochs</text>
      </svg>
    </div>
  );
}
