import { useEffect, useMemo, useRef, useState } from 'react';
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
  const [examples,setExamples]=useState(false);
  const selection=useRef(0);
  const [message, setMessage] = useState('GLB / GLTF / OBJ / STL · 支持 GLTF 外部资源、纹理、版本和参数对比');
  const embeddings = useMemo(embeddingFrames, []); const simulations = useMemo(simulationFrames, []);
  useEffect(() => { fetchModelAssets().then(({ data }) => setAssets(data)).catch(() => setMessage('资产服务暂时不可用；未自动替换为示例模型。')); }, []);
  useEffect(()=>()=>{if(textureUrl)URL.revokeObjectURL(textureUrl);},[textureUrl]);
  useEffect(()=>()=>{selection.current++;},[]);
  useEffect(()=>{const id=new URLSearchParams(location.search).get('modelAsset');if(id){if(/^[A-Za-z0-9_-]{1,100}$/.test(id))void selectAsset(id);else setMessage('模型记录编号无效，请从资产列表选择。');}},[]);

  function rememberAsset(id:string){const url=new URL(location.href);id?url.searchParams.set('modelAsset',id):url.searchParams.delete('modelAsset');history.replaceState({},'',url.pathname+url.search+url.hash);}

  const selectAsset = async (id: string) => {
    const version=++selection.current;
    if (!id) { setCurrent(undefined); setBefore(undefined);rememberAsset('');return; }
    rememberAsset(id);setCurrent(undefined);setBefore(undefined);setMessage('正在读取所选模型…');
    try{
      const response=await fetchModelAsset(id);if(version!==selection.current)return;
      setCurrent(response.data);setBefore(undefined);rememberAsset(response.data.id);setMessage('已加载 '+response.data.name+'，当前显示保存的模型内容。');
      if(response.data.parentId){const old=await fetchModelAsset(response.data.parentId);if(version===selection.current)setBefore(old.data);}
    }catch{if(version===selection.current)setMessage('所选模型或前一版本读取失败，请检查资产服务；未显示替代模型。');}
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const items = [...files];
    const primary = items.find((file) => ['glb', 'gltf', 'obj', 'stl', 'ply', 'step', 'stp', 'iges', 'igs'].includes(file.name.split('.').pop()?.toLowerCase() ?? ''));
    if (!primary) return setMessage('请选择 GLB、GLTF、OBJ、STL、PLY、STEP 或 IGES 主文件');
    const rawFormat = primary.name.split('.').pop()?.toLowerCase();
    const format = (rawFormat === 'stp' ? 'step' : rawFormat === 'igs' ? 'iges' : rawFormat) as ModelAsset['format'];
    setMessage(`正在上传 ${primary.name} 与 ${items.length - 1} 个依赖资源…`);
    const version=++selection.current;
    try {
      const resources: ModelResource[] = await Promise.all(items.filter((file) => file !== primary).map(async (file) => ({ name: file.webkitRelativePath || file.name, mimeType: file.type || mimeFor(file.name), base64: encodeBase64(await file.arrayBuffer()) })));
      const response = await createModelAsset({ name: primary.name, format, content: encodeBase64(await primary.arrayBuffer()), resources, metadata: { size: primary.size, lastModified: primary.lastModified, resourceCount: resources.length } });
      if(version!==selection.current)return;
      setAssets((existing) => [response.data, ...existing]); setCurrent(response.data);
      rememberAsset(response.data.id);
      setBefore(undefined);
      if (response.data.parentId) fetchModelAsset(response.data.parentId).then((item) => {if(version===selection.current)setBefore(item.data);}).catch(()=>{if(version===selection.current)setMessage('模型已上传，但前一版本未加载；可以重新选择此资产。');});
      setMessage(`${primary.name} v${response.data.version} 已保存 · ${resources.length} 个依赖资源`);
    } catch (error) { setMessage(error instanceof Error ? error.message : '上传失败'); }
  };

  const cadArtifact: ArtifactSchema = { id: 'cad-workbench', type: 'cad-model-3d', name: current?.name ?? '参数化几何示例', data: { name: current?.name ?? 'Parametric Assembly', format: current?.format, base64: current?.content?.base64, resources: current?.content?.resources, version: current?.version ?? 1, beforeBase64: before?.content?.base64, beforeResources: before?.content?.resources, textureUrl } };
  const embeddingArtifact: ArtifactSchema = { id: 'embedding-evolution', type: 'embedding-evolution-3d', name: '合成三维坐标演示', data: { frames: embeddings } };
  const simulationArtifact: ArtifactSchema = { id: 'simulation-replay', type: 'simulation-replay-3d', name: '构造轨迹演示', data: { frames: simulations } };
  return <div className="three-lab"><div className="page-heading"><div><div className="eyebrow">空间中的观察与理解</div><h1>三维与空间</h1><p role="status">{message}</p></div><div className="lab-actions"><label className="upload-btn"><Upload size={14} />上传模型与资源<input aria-label="上传模型与资源" multiple type="file" accept=".glb,.gltf,.obj,.stl,.ply,.step,.stp,.iges,.igs,.bin,.png,.jpg,.jpeg,.webp,.ktx2" onChange={(event) => upload(event.target.files)} /></label><label className="upload-btn"><ImagePlus size={14} />覆盖纹理<input type="file" accept="image/*" onChange={(event) => { const file = event.target.files?.[0]; if (file) setTextureUrl(URL.createObjectURL(file)); }} /></label><select aria-label="模型资产版本" value={current?.id ?? ''} onChange={(event) => selectAsset(event.target.value)}><option value="">{examples?'内置概念模型（示例）':'选择已上传模型'}</option>{assets.map((asset) => <option value={asset.id} key={asset.id}>{asset.name} · v{asset.version}</option>)}</select><button className="visual-secondary" onClick={()=>setExamples(v=>!v)}>{examples?'收起概念示例':'打开概念示例'}</button></div></div>
    {examples&&<div className="spatial-example-notice"><strong>内置概念示例</strong><span>参数几何、合成三维坐标与构造轨迹，仅用于理解交互；不是训练得到的Embedding、UMAP结果或真实物理仿真。</span></div>}
    {!current&&!examples?<section className="spatial-empty card"><Box size={32}/><h2>把结构放进空间里理解。</h2><p>选择已上传的模型，旋转、缩放并查看节点与版本；也可以显式打开合成概念示例，观察点云和轨迹。</p><button className="visual-primary" onClick={()=>setExamples(true)}>探索内置概念示例</button></section>:<><div className="asset-version-strip card"><Box size={15} /><div><strong>{current?.name ?? '参数化几何示例'}</strong><span>{current ? `${current.format.toUpperCase()} · 版本 ${current.version} · ${current.metadata.resourceCount ?? 0} 项依赖资源` : '构造几何 · 不是上传或训练产物'}</span></div>{before && <b>版本 {before.version} / {current?.version}</b>}</div><div className="three-plugin-grid"><section className="card cad-card"><div className="card-head"><div><span>{current?'已上传模型':'内置几何示例'}</span><h3>{cadArtifact.name}</h3></div></div><PluginHost input={cadArtifact} /></section>{examples&&<><section className="card"><div className="card-head"><div><span>合成坐标 · 非训练产物</span><h3>三维坐标随步骤变化</h3></div></div><PluginHost input={embeddingArtifact} /></section><section className="card span-2"><div className="card-head"><div><span>构造轨迹 · 非物理实测</span><h3>点云、轨迹与向量场</h3></div><Layers3 size={15} /></div><PluginHost input={simulationArtifact} /></section></>}</div></>}
  </div>;
}
