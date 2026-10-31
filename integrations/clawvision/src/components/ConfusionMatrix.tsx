export function ConfusionMatrix({ values }: { values: number[][] }) {
  const max = Math.max(...values.flat(), 1);
  return (
    <div className="matrix-wrap">
      <div className="matrix-axis matrix-y">真实标签</div>
      <div className="matrix-grid" style={{ gridTemplateColumns: `repeat(${values.length}, 1fr)` }}>
        {values.flatMap((row, rowIndex) => row.map((value, columnIndex) => (
          <div
            key={`${rowIndex}-${columnIndex}`}
            className="matrix-cell"
            style={{ background: `rgba(124,247,200,${0.08 + (value / max) * 0.78})`, color: value / max > 0.5 ? '#07100e' : '#c8ddd5' }}
            title={`真实 ${rowIndex} / 预测 ${columnIndex}: ${value}`}
          >
            {value}
          </div>
        )))}
      </div>
      <div className="matrix-axis matrix-x">预测标签 →</div>
    </div>
  );
}
