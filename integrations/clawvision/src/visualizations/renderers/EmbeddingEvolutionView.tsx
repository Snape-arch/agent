import { useEffect, useMemo, useState } from 'react';
import type { EmbeddingPoint } from '../../domain';
import { EmbeddingView } from '../../components/EmbeddingView';

export interface EmbeddingFrame { step: number; points: EmbeddingPoint[] }

export function EmbeddingEvolutionView({ frames }: { frames: EmbeddingFrame[] }) {
  const [index, setIndex] = useState(Math.max(0, frames.length - 1)); const [playing, setPlaying] = useState(false); const [overlay, setOverlay] = useState(false);
  useEffect(() => { if (!playing || frames.length < 2) return; const timer = window.setInterval(() => setIndex((value) => (value + 1) % frames.length), 650); return () => clearInterval(timer); }, [playing, frames.length]);
  const points = useMemo(() => overlay && index > 0 ? [...frames[0].points.map((point) => ({ ...point, correct: false })), ...frames[index].points] : frames[index]?.points ?? [], [frames, index, overlay]);
  return <div className="evolution-plugin"><EmbeddingView points={points} /><div className="timeline-controls"><button onClick={() => setPlaying((value) => !value)}>{playing ? '暂停' : '播放'}</button><input aria-label="Embedding 时间轴" type="range" min="0" max={Math.max(0, frames.length - 1)} value={index} onChange={(event) => { setPlaying(false); setIndex(Number(event.target.value)); }} /><span>step {frames[index]?.step ?? 0}</span><label><input type="checkbox" checked={overlay} onChange={(event) => setOverlay(event.target.checked)} />与初始状态叠加</label></div></div>;
}
