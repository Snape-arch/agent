import type { RendererProps } from './types';

export interface DataChartData { rows: Array<Record<string, unknown>> }
export type DataChartKind = 'line-chart' | 'bar-chart' | 'scatter-chart' | 'heatmap-chart' | 'boxplot-chart';

const width = 640; const height = 270; const left = 48; const right = 18; const top = 18; const bottom = 38;
const plotWidth = width - left - right; const plotHeight = height - top - bottom;
const number = (value: unknown) => Number.isFinite(Number(value)) ? Number(value) : 0;
const unique = (values: unknown[]) => [...new Set(values.map(String))].slice(0, 24);
const quantile = (values: number[], q: number) => { const sorted = [...values].sort((a, b) => a - b); const index = (sorted.length - 1) * q; const lo = Math.floor(index); const hi = Math.ceil(index); return sorted[lo] + (sorted[hi] - sorted[lo]) * (index - lo); };

export function renderDataChart(kind: DataChartKind, { input, spec, runtime }: RendererProps<DataChartData>) {
  const rows = input.data.rows;
  const xField = String(spec.options?.xField ?? Object.keys(rows[0] ?? {})[0] ?? 'x');
  const yField = String(spec.options?.yField ?? Object.keys(rows[0] ?? {})[1] ?? 'y');
  const emit = (value: unknown) => runtime?.onFilterChange?.(xField, value);
  if (!rows.length) return <div className="plugin-empty">数据为空</div>;
  const xs = rows.map((row) => row[xField]);
  const ys = rows.map((row) => number(row[yField]));
  const minY = Math.min(...ys, 0); const maxY = Math.max(...ys, 1);
  const py = (value: number) => top + (1 - (value - minY) / Math.max(.0001, maxY - minY)) * plotHeight;
  const axis = <><line x1={left} y1={top + plotHeight} x2={left + plotWidth} y2={top + plotHeight} className="data-axis" /><line x1={left} y1={top} x2={left} y2={top + plotHeight} className="data-axis" /><text x="5" y={top + 7} className="data-label">{maxY.toFixed(1)}</text><text x="5" y={top + plotHeight} className="data-label">{minY.toFixed(1)}</text><text x={left} y={height - 8} className="data-label">{xField}</text><text x={width - 70} y={height - 8} className="data-label">{yField}</text></>;

  if (kind === 'line-chart' || kind === 'scatter-chart') {
    const numericX = xs.every((value) => Number.isFinite(Number(value)));
    const xNumbers = numericX ? xs.map(Number) : xs.map((_, index) => index);
    const minX = Math.min(...xNumbers); const maxX = Math.max(...xNumbers, minX + 1);
    const px = (value: number) => left + ((value - minX) / Math.max(.0001, maxX - minX)) * plotWidth;
    const points = rows.map((row, index) => ({ x: px(xNumbers[index]), y: py(number(row[yField])), row })).sort((a, b) => a.x - b.x);
    const path = points.map((point, index) => `${index ? 'L' : 'M'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
    return <svg className="data-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${input.name} ${kind}`}>{axis}{kind === 'line-chart' && <path d={path} className="data-line" />}{points.map((point, index) => <circle key={index} cx={point.x} cy={point.y} r={kind === 'scatter-chart' ? 4 : 3} className="data-mark" onClick={() => emit(point.row[xField])}><title>{`${xField}: ${String(point.row[xField])}; ${yField}: ${String(point.row[yField])}`}</title></circle>)}</svg>;
  }

  const categories = unique(xs);
  if (kind === 'bar-chart') {
    const sums = categories.map((category) => rows.filter((row) => String(row[xField]) === category).reduce((sum, row) => sum + number(row[yField]), 0));
    const topValue = Math.max(...sums, 1); const slot = plotWidth / categories.length;
    const barAxis = <><line x1={left} y1={top + plotHeight} x2={left + plotWidth} y2={top + plotHeight} className="data-axis" /><line x1={left} y1={top} x2={left} y2={top + plotHeight} className="data-axis" /><text x="5" y={top + 7} className="data-label">{topValue.toFixed(1)}</text><text x="5" y={top + plotHeight} className="data-label">0.0</text><text x={left} y={height - 8} className="data-label">{xField}</text><text x={width - 70} y={height - 8} className="data-label">{yField}</text></>;
    return <svg className="data-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${input.name} 柱状图`}>{barAxis}{sums.map((value, index) => { const barHeight = value / topValue * plotHeight; return <g key={categories[index]} onClick={() => emit(categories[index])}><rect x={left + index * slot + 4} y={top + plotHeight - barHeight} width={Math.max(2, slot - 8)} height={barHeight} className="data-bar"><title>{`${categories[index]}: ${value}`}</title></rect><text x={left + index * slot + slot / 2} y={height - 20} textAnchor="middle" className="data-label">{categories[index].slice(0, 8)}</text></g>; })}</svg>;
  }

  if (kind === 'heatmap-chart') {
    const yCategories = unique(rows.map((row) => row[yField])); const cellW = plotWidth / categories.length; const cellH = plotHeight / yCategories.length;
    const counts = categories.flatMap((x) => yCategories.map((y) => rows.filter((row) => String(row[xField]) === x && String(row[yField]) === y).length)); const maxCount = Math.max(...counts, 1);
    return <svg className="data-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${input.name} 热力图`}>{categories.flatMap((x, xi) => yCategories.map((y, yi) => { const count = rows.filter((row) => String(row[xField]) === x && String(row[yField]) === y).length; return <rect key={`${x}-${y}`} x={left + xi * cellW} y={top + yi * cellH} width={cellW - 2} height={cellH - 2} fill={`rgba(124,247,200,${.08 + count / maxCount * .78})`} onClick={() => emit(x)}><title>{`${x} / ${y}: ${count}`}</title></rect>; }))}<text x={left} y={height - 8} className="data-label">{xField} × {yField}</text></svg>;
  }

  const groups = categories.map((category) => ({ category, values: rows.filter((row) => String(row[xField]) === category).map((row) => number(row[yField])) })); const slot = plotWidth / groups.length;
  return <svg className="data-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${input.name} 箱线图`}>{axis}{groups.map((group, index) => { const q1 = quantile(group.values, .25), median = quantile(group.values, .5), q3 = quantile(group.values, .75), min = Math.min(...group.values), max = Math.max(...group.values); const cx = left + slot * index + slot / 2; return <g key={group.category} onClick={() => emit(group.category)}><line x1={cx} y1={py(max)} x2={cx} y2={py(min)} className="box-whisker" /><rect x={cx - Math.min(22, slot * .3)} y={py(q3)} width={Math.min(44, slot * .6)} height={Math.max(2, py(q1) - py(q3))} className="box-body"><title>{`${group.category}: ${min} / ${q1} / ${median} / ${q3} / ${max}`}</title></rect><line x1={cx - Math.min(22, slot * .3)} y1={py(median)} x2={cx + Math.min(22, slot * .3)} y2={py(median)} className="box-median" /><text x={cx} y={height - 20} textAnchor="middle" className="data-label">{group.category.slice(0, 8)}</text></g>; })}</svg>;
}
