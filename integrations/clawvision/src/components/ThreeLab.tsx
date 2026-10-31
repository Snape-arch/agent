import { useEffect, useMemo, useState } from 'react';
import { Box, ImagePlus, Layers3, Upload } from 'lucide-react';
import { createModelAsset, fetchModelAsset, fetchModelAssets, type ModelAsset, type ModelResource } from '../api';
import type { EmbeddingPoint } from '../domain';
import { PluginHost } from '../visualizations/PluginHost';
import type { EmbeddingFrame } from '../visualizations/renderers/EmbeddingEvolutionView';
import type { SimulationFrame } from '../visualizations/renderers/SimulationReplayView';
import type { ArtifactSchema } from '../visualizations/types';

function encodeBase64(buffer: ArrayBuffer) { const bytes = new Uint8Array(buffer); let binary = ''; for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000)); return btoa(binary); }
function noise(seed: number) { const value = Math.sin(seed * 12.9898) * 43758.5453; return value - Math.floor(value); }
function mimeFor(name: string) { const extension = name.split('.').pop()?.toLowerCase(); return ({ bin: 'application/octet-stream', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', ktx2: 'image/ktx2' } as Record<string, string>)[extension ?? ''] ?? 'application/octet-stream'; }

function embeddingFrames(): EmbeddingFrame[] {
  return Array.from({ length: 9 }, (_, frame) => ({ step: frame * 5, points: Array.from({ length: 120 }, (_, index): EmbeddingPoint => { const cluster = index % 5; const angle = cluster / 5 * Math.PI * 2; const separation = 1.2 + frame * .28; const jitter = (axis: number) => (noise(index * 31 + axis * 997 + frame * 7) - .5) * (2.2 - frame * .16); return { x: Math.cos(angle) * separation + jitter(1), y: Math.sin(angle) * separation + jitter(2), z: (cluster - 2) * .35 + jitter(3), cluster, correct: noise(index * 19 + frame) > .12 }; }) }));
}
function simulationFrames(): SimulationFrame[] {
  return Array.from({ length: 16 }, (_, frame) => { const t = frame / 15 * Math.PI * 2; const trajectory = Array.from({ length: 36 }, (_, index): [number, number, number] => { const a = index / 35 * Math.PI * 4; return [Math.cos(a) * (2 + .3 * Math.sin(t)), (index / 35 - .5) * 4, Math.sin(a) * (2 + .3 * Math.cos(t))]; }); return { step: frame, trajectory, points: Array.from({ length: 90 }, (_, index): [number, number, number] => { const a = index / 90 * Math.PI * 2 + t; const radius = 1.2 + noise(index + frame * 17) * 2; return [Math.cos(a) * radius, (noise(index * 3 + frame) - .5) * 4, Math.sin(a) * radius]; }), vectors: Array.from({ length: 18 }, (_, index) => { const a = index / 18 * Math.PI * 2; return { origin: [Math.cos(a) * 2.5, 0, Math.sin(a) * 2.5] as [number, number, number], direction: [-Math.sin(a), .25 * Math.sin(t), Math.cos(a)] as [number, number, number] }; }) }; });
}

export function ThreeLab() {
  const [assets, setAssets] = useState<ModelAsset[]>([]);
  const [current, setCurrent] = useState<ModelAsset>();
  const [before, setBefore] = useState<ModelAsset>();
  const [textureUrl, setTextureUrl] = useState<string>();
  const [message, setMessage] = useState('GLB / GLTF / OBJ / STL · 支持 GLTF 外部资源、纹理、版本和参数对比');
  const embeddings = useMemo(embeddingFrames, []); const simulations = useMemo(simulationFrames, []);
  useEffect(() => { fetchModelAssets().then(({ data }) => setAssets(data)).catch(() => setMessage('后端离线 · 使用内置参数模型')); }, []);

  const selectAsset = async (id: string) => {
    if (!id) { setCurrent(undefined); setBefore(undefined); return; }
    const response = await fetchModelAsset(id); setCurrent(response.data);
    if (response.data.parentId) fetchModelAsset(response.data.parentId).then((item) => setBefore(item.data)); else setBefore(undefined);
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const items = [...files];
    const primary = items.find((file) => ['glb', 'gltf', 'obj', 'stl', 'ply', 'step', 'stp', 'iges', 'igs'].includes(file.name.split('.').pop()?.toLowerCase() ?? ''));
    if (!primary) return setMessage('请选择 GLB、GLTF、OBJ、STL、PLY、STEP 或 IGES 主文件');
    const rawFormat = primary.name.split('.').pop()?.toLowerCase();
    const format = (rawFormat === 'stp' ? 'step' : rawFormat === 'igs' ? 'iges' : rawFormat) as ModelAsset['format'];
    setMessage(`正在上传 ${primary.name} 与 ${items.length - 1} 个依赖资源…`);
    try {
      const resources: ModelResource[] = await Promise.all(items.filter((file) => file !== primary).map(async (file) => ({ name: file.webkitRelativePath || file.name, mimeType: file.type || mimeFor(file.name), base64: encodeBase64(await file.arrayBuffer()) })));
      const response = await createModelAsset({ name: primary.name, format, content: encodeBase64(await primary.arrayBuffer()), resources, metadata: { size: primary.size, lastModified: primary.lastModified, resourceCount: resources.length } });
      setAssets((existing) => [response.data, ...existing]); setCurrent(response.data);
      if (response.data.parentId) fetchModelAsset(response.data.parentId).then((item) => setBefore(item.data));
      setMessage(`${primary.name} v${response.data.version} 已保存 · ${resources.length} 个依赖资源`);
    } catch (error) { setMessage(error instanceof Error ? error.message : '上传失败'); }
  };

  const cadArtifact: ArtifactSchema = { id: 'cad-workbench', type: 'cad-model-3d', name: current?.name ?? '内置 CAD 参数模型', data: { name: current?.name ?? 'Parametric Assembly', format: current?.format, base64: current?.content?.base64, resources: current?.content?.resources, version: current?.version ?? 1, beforeBase64: before?.content?.base64, beforeResources: before?.content?.resources, textureUrl } };
  const embeddingArtifact: ArtifactSchema = { id: 'embedding-evolution', type: 'embedding-evolution-3d', name: '训练 Embedding 演化', data: { frames: embeddings } };
  const simulationArtifact: ArtifactSchema = { id: 'simulation-replay', type: 'simulation-replay-3d', name: '仿真环境状态回放', data: { frames: simulations } };
  return <div className="three-lab"><div className="page-heading"><div><div className="eyebrow">P6 / 3D EXPERIMENT & MODEL</div><h1>3D 实验与模型工作台</h1><p>{message}</p></div><div className="lab-actions"><label className="upload-btn"><Upload size={14} />上传模型与资源<input multiple type="file" accept=".glb,.gltf,.obj,.stl,.ply,.step,.stp,.iges,.igs,.bin,.png,.jpg,.jpeg,.webp,.ktx2" onChange={(event) => upload(event.target.files)} /></label><label className="upload-btn"><ImagePlus size={14} />覆盖纹理<input type="file" accept="image/*" onChange={(event) => { const file = event.target.files?.[0]; if (file) { if (textureUrl) URL.revokeObjectURL(textureUrl); setTextureUrl(URL.createObjectURL(file)); } }} /></label><select aria-label="模型资产版本" value={current?.id ?? ''} onChange={(event) => selectAsset(event.target.value)}><option value="">内置模型</option>{assets.map((asset) => <option value={asset.id} key={asset.id}>{asset.name} · v{asset.version}</option>)}</select></div></div>
    <div className="asset-version-strip card"><Box size={15} /><div><strong>{current?.name ?? 'Parametric Assembly'}</strong><span>{current ? `${current.format.toUpperCase()} · version ${current.version} · ${current.metadata.resourceCount ?? 0} resources` : 'procedural · version 1'}</span></div>{before && <b>Before v{before.version} / After v{current?.version}</b>}</div>
    <div className="three-plugin-grid"><section className="card cad-card"><div className="card-head"><div><span>CAD PARAMETER MODEL</span><h3>{cadArtifact.name}</h3></div><small>core.cad-model-3d</small></div><PluginHost input={cadArtifact} /></section><section className="card"><div className="card-head"><div><span>TRAINING SPACE</span><h3>{embeddingArtifact.name}</h3></div><small>core.embedding-evolution-3d</small></div><PluginHost input={embeddingArtifact} /></section><section className="card span-2"><div className="card-head"><div><span>SIMULATION STATE</span><h3>{simulationArtifact.name}</h3></div><Layers3 size={15} /></div><PluginHost input={simulationArtifact} /></section></div>
  </div>;
}
