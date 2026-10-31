import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, CheckCircle2, Clock3, Copy, Download, ImagePlus, Play, Redo2, RotateCcw, Save, Send, Sparkles, Star, Trash2, Undo2 } from 'lucide-react';
import { applySceneOperations, cancelStudioAgentRun, cancelText3DJob, createModelAsset, createStudioAgentRun, createText3DJob, exportStudioAsset, fetchModelAsset, fetchStudioGenerations, fetchStudioTemplates, fetchText3DProviders, previewSceneCommand, saveStudioGeneration, sendStudioFeedback, streamStudioAgentRun, streamText3DJob, type ModelAsset, type SceneCommandPreview, type SceneOperation, type StudioAgentRun, type StudioGeneration, type StudioPlan, type Text3DJob, type Text3DProvider } from '../api';
import { PluginHost } from '../visualizations/PluginHost';
import type { ArtifactSchema } from '../visualizations/types';
import { SemanticSceneEditor } from './SemanticSceneEditor';

const starterPrompt = '生成一台银色四旋翼无人机，复杂度 7，曲面 0.65，连接密度 0.7，带相机云台';

function updatePlan(plan: StudioPlan, key: keyof StudioPlan['parameters'], value: string | number) {
  const parameters = { ...plan.parameters, [key]: value };
  const parts = key === 'color' || key === 'material'
    ? plan.parts.map((part, index) => ({ ...part, color: key === 'color' && index % 3 !== 1 ? String(value) : part.color, material: key === 'material' ? String(value) : part.material }))
    : plan.parts;
  return { ...plan, parameters, parts };
}

export function AiStudio() {
  const [prompt, setPrompt] = useState(starterPrompt);
  const [provider, setProvider] = useState('local');
  const [model, setModel] = useState('');
  const [plan, setPlan] = useState<StudioPlan>();
  const [beforePlan, setBeforePlan] = useState<StudioPlan>();
  const [templates, setTemplates] = useState<Array<{ id: string; name: string; description: string }>>([]);
  const [history, setHistory] = useState<StudioGeneration[]>([]);
  const [saved, setSaved] = useState<StudioGeneration>();
  const [textureUrl, setTextureUrl] = useState<string>();
  const [meshQuality, setMeshQuality] = useState<'standard' | 'high' | 'ultra'>('high');
  const [exportFormat, setExportFormat] = useState<'obj' | 'gltf' | 'glb'>('glb');
  const [meshAsset, setMeshAsset] = useState<ModelAsset>();
  const [selectedPartName, setSelectedPartName] = useState('');
  const [selectedPartNames, setSelectedPartNames] = useState<string[]>([]);
  const [editHistory, setEditHistory] = useState<StudioPlan[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const [sceneCommand, setSceneCommand] = useState('');
  const [commandPreview, setCommandPreview] = useState<SceneCommandPreview>();
  const [transformSpace, setTransformSpace] = useState<'world' | 'local'>('world');
  const [transformSnap, setTransformSnap] = useState(0.1);
  const [message, setMessage] = useState('描述模型，系统会生成结构化计划并立即渲染。');
  const [busy, setBusy] = useState(false);
  const [agentRun, setAgentRun] = useState<StudioAgentRun>();
  const stopStream = useRef<() => void>();
  const stopText3DStream = useRef<() => void>();
  const [text3DJob, setText3DJob] = useState<Text3DJob>();
  const [workerAsset, setWorkerAsset] = useState<ModelAsset>();
  const [previewMode, setPreviewMode] = useState<'parametric' | 'semantic'>('parametric');
  const [text3DProviders, setText3DProviders] = useState<Text3DProvider[]>([]);
  const [text3DProvider, setText3DProvider] = useState('local-semantic');
  const [referenceImage, setReferenceImage] = useState<string>();
  const loadedPreview = useRef<string>();

  useEffect(() => {
    Promise.all([fetchStudioTemplates(), fetchStudioGenerations(), fetchText3DProviders()]).then(([templateResult, historyResult, providerResult]) => { setTemplates(templateResult.data); setHistory(historyResult.data); setText3DProviders(providerResult.data); const preferred = providerResult.data.find((item) => item.id === 'meshy' && item.configured) ?? providerResult.data.find((item) => item.id === 'tripo' && item.configured); if (preferred) setText3DProvider(preferred.id); }).catch(() => setMessage('后端离线，AI Studio 需要启动 API 服务。'));
  }, []);
  useEffect(() => () => { stopStream.current?.(); stopText3DStream.current?.(); }, []);

  const effectivePlan = useMemo(() => {
    if (!plan) return undefined;
    const count = Math.max(2, Math.ceil(plan.parts.length * plan.parameters.complexity / 10));
    return { ...plan, parts: plan.parts.slice(0, count) };
  }, [plan]);

  const resetEditHistory = useCallback((next: StudioPlan) => { setPlan(next); setEditHistory([next]); setHistoryIndex(0); setCommandPreview(undefined); }, []);
  const commitPlan = useCallback((next: StudioPlan) => {
    setPlan(next); setEditHistory((items) => { const kept = items.slice(0, historyIndex + 1); kept.push(next); return kept.slice(-80); }); setHistoryIndex((index) => Math.min(index + 1, 79)); setCommandPreview(undefined);
  }, [historyIndex]);
  const undo = () => { if (historyIndex <= 0) return; const index = historyIndex - 1; setHistoryIndex(index); setPlan(editHistory[index]); };
  const redo = () => { if (historyIndex >= editHistory.length - 1) return; const index = historyIndex + 1; setHistoryIndex(index); setPlan(editHistory[index]); };

  const generate = async () => {
    setBusy(true); setMessage('正在执行 Prompt → Structure → Surface → Material → Quality…');
    try {
      stopStream.current?.();
      const response = await createStudioAgentRun({ prompt, provider, model: model || undefined, maxCycles: 3, qualityThreshold: 92, timeoutSeconds: 300 });
      setAgentRun(response.data); setSaved(undefined);
      stopStream.current = streamStudioAgentRun(response.data.id, (run) => {
        setAgentRun(run);
        const active = [...run.stages].reverse().find((stage) => stage.status === 'running');
        setMessage(active ? `${active.name} · cycle ${active.cycle + 1} · attempt ${active.attempt}/${active.maxAttempts}` : `Agent Pipeline：${run.status}`);
        if (run.status === 'completed' && run.result) {
          setBeforePlan(plan); resetEditHistory(run.result); setBusy(false);
          setMessage(`${run.result.name} 已生成 · ${run.result.parts.length} 个部件 · 质量 ${run.result.validation.score}/100 · ${run.totalTokens} tokens · $${run.totalCost.toFixed(6)}`);
        } else if (run.status === 'failed' || run.status === 'cancelled') { setBusy(false); setMessage(run.error ?? `Agent Pipeline ${run.status}`); }
      }, () => { setBusy(false); setMessage('Agent 流式连接中断，可从服务端中间产物恢复。'); });
    } catch (error) { setBusy(false); setMessage(error instanceof Error ? error.message : '生成失败'); }
  };

  const save = async () => {
    if (!plan) return;
    const response = await saveStudioGeneration({ id: saved?.id, name: plan.name, prompt, provider, plan, assetId: meshAsset?.id });
    setSaved(response.data); setHistory((items) => [response.data, ...items.filter((item) => item.id !== response.data.id)]); setMessage(`${plan.name} v${response.data.version} 已保存，可继续修改形成新版本。`);
  };

  const load = (item: StudioGeneration) => { setBeforePlan(plan); resetEditHistory(item.plan); setPrompt(item.prompt); setSaved(item); setMessage(`已恢复 ${item.name} v${item.version}`); };
  const chooseTemplate = (template: { name: string; description: string }) => { setPrompt(`生成${template.name}，${template.description}，复杂度 6，使用金属材质`); };
  const texture = (file?: File) => { if (!file) return; if (textureUrl) URL.revokeObjectURL(textureUrl); setTextureUrl(URL.createObjectURL(file)); setMessage(`纹理 ${file.name} 已映射到当前模型`); };
  const compileMesh = async () => {
    if (!effectivePlan) return;
    setBusy(true); setMessage(`正在编译 ${meshQuality} 高精度 ${exportFormat.toUpperCase()} 资产…`);
    try {
      const response = await exportStudioAsset(effectivePlan, meshQuality, exportFormat);
      setMeshAsset(response.data);
      const encoded = response.data.content?.base64;
      if (encoded) {
        const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
        const mime = exportFormat === 'glb' ? 'model/gltf-binary' : exportFormat === 'gltf' ? 'model/gltf+json' : 'model/obj';
        const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
        const anchor = document.createElement('a'); anchor.href = url; anchor.download = response.data.name; anchor.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      const stats = response.data.metadata;
      setMessage(`网格资产 v${response.data.version} 已保存 · ${String(stats.vertices)} vertices · ${String(stats.faces)} faces`);
    } catch (error) { setMessage(error instanceof Error ? error.message : '网格编译失败'); }
    finally { setBusy(false); }
  };
  const generateSemanticMesh = async () => {
    setBusy(true); setMessage('正在启动独立 Text-to-3D Worker…'); stopText3DStream.current?.();
    try {
      const response = await createText3DJob({ prompt, resolution: text3DProvider==='local-semantic'?48:38, provider: text3DProvider, imageBase64: referenceImage, timeoutSeconds: 900, memoryBudgetMb: 12288 }); setText3DJob(response.data);
      stopText3DStream.current = streamText3DJob(response.data.id, (job) => {
        setText3DJob(job); setMessage(`Text-to-3D Worker · ${job.stage} · ${job.progress}%`);
        if (job.previewAssetId && loadedPreview.current !== job.previewAssetId && !job.assetId) {
          loadedPreview.current = job.previewAssetId;
          fetchModelAsset(job.previewAssetId,false).then((asset) => { setWorkerAsset(asset.data); setPreviewMode('semantic'); });
        }
        if (job.status === 'completed' && job.assetId) {
          fetchModelAsset(job.assetId,false).then((asset) => { setWorkerAsset(asset.data); setPreviewMode('semantic'); setBusy(false); setMessage(`高质量 GLB 已替换预览 · ${job.stats?.vertices} vertices · ${job.stats?.faces} faces`); });
        } else if (job.status === 'failed' || job.status === 'cancelled') { setBusy(false); setMessage(job.error ?? `Text-to-3D Worker ${job.status}`); }
      }, () => { setBusy(false); setMessage('Text-to-3D Worker 流式连接中断'); });
    } catch (error) { setBusy(false); setMessage(error instanceof Error ? error.message : 'Text-to-3D Worker 启动失败'); }
  };
  const loadReferenceImage = (file?: File) => {
    if (!file) return; const reader = new FileReader();
    reader.onload = () => setReferenceImage(String(reader.result).split(',')[1]); reader.readAsDataURL(file);
  };
  const loadEditableModel = (input?: FileList|null) => {
    const files=[...(input??[])];if(!files.length)return;const total=files.reduce((sum,file)=>sum+file.size,0);if(total>256*1024*1024){setMessage('模型与依赖文件合计不能超过 256 MB');return;}
    const worker=new Worker(new URL('../workers/modelImportWorker.ts',import.meta.url),{type:'module'});setBusy(true);setMessage(`后台读取 ${files.length} 个模型文件…`);
    worker.onmessage=async(event:MessageEvent<{type:string;progress?:number;name?:string;message?:string;main?:{name:string;base64:string};format?:ModelAsset['format'];resources?:Array<{name:string;mimeType:string;base64:string}>}>)=>{
      const data=event.data;if(data.type==='progress'){setMessage(`后台读取 ${data.name} · ${data.progress}%`);return;}if(data.type==='error'){setMessage(data.message??'模型导入失败');setBusy(false);worker.terminate();return;}
      if(data.type==='complete'&&data.main&&data.format){try{const created=(await createModelAsset({name:data.main.name,format:data.format,content:data.main.base64,resources:data.resources,metadata:{source:'user-upload',assetStage:'raw',dependencyCount:data.resources?.length??0}})).data;setWorkerAsset(created);setPreviewMode('semantic');setMessage(`${data.main.name} 已导入，正在构建可编辑 Scene Graph`);}catch(error){setMessage(error instanceof Error?error.message:'模型导入失败');}finally{setBusy(false);worker.terminate();}}
    };worker.postMessage({files});
  };

  const selectedPart = plan?.parts.find((part) => part.name === selectedPartName) ?? plan?.parts[0];
  const updatePart = (patch: Partial<StudioPlan['parts'][number]>) => {
    if (!plan || !selectedPart) return;
    const names = selectedPartNames.length ? selectedPartNames : [selectedPart.name];
    commitPlan({ ...plan, parts: plan.parts.map((part) => names.includes(part.name) ? { ...part, ...patch } : part) });
    setSelectedPartName(selectedPart.name);
  };
  const applyRenderedPlan = useCallback((changed: StudioPlan) => commitPlan(changed), [commitPlan]);
  const previewCommand = async () => { if (!plan || !sceneCommand.trim()) return; try { const response = await previewSceneCommand(sceneCommand, plan); setCommandPreview(response.data); setMessage(`${response.data.explanation}；确认后才会写入新版本。`); } catch (error) { setMessage(error instanceof Error ? error.message : '无法解析编辑命令'); } };
  const confirmCommand = async () => { if (!plan || !commandPreview) return; const response = await applySceneOperations({ generationId: saved?.id, command: commandPreview.command, plan, operations: commandPreview.operations }); setBeforePlan(plan); commitPlan(response.data.plan); setSceneCommand(''); setMessage(`自然语言编辑已确认为场景 v${response.data.version}，可撤销。`); };
  const manualOperation = async (type: SceneOperation['type'], payload: Record<string, unknown> = {}) => { if (!plan || !selectedPart) return; const targets = selectedPartNames.length ? selectedPartNames : [selectedPart.name]; const operation: SceneOperation = { id: `op_${Date.now()}`, type, targetIds: targets, payload }; const response = await applySceneOperations({ generationId: saved?.id, command: `manual ${type}`, plan, operations: [operation] }); commitPlan(response.data.plan); };
  const movePart = (delta: number) => { if (!plan || !selectedPart) return; const index = plan.parts.findIndex((part) => part.name === selectedPart.name); const target = Math.max(0, Math.min(plan.parts.length - 1, index + delta)); const parts = [...plan.parts]; const [item] = parts.splice(index, 1); parts.splice(target, 0, item); commitPlan({ ...plan, parts }); };
  const artifact: ArtifactSchema | undefined = effectivePlan ? { id: 'ai-studio-current', type: 'ai-cad-studio-3d', name: effectivePlan.name, data: { plan: commandPreview?.previewPlan ?? effectivePlan, beforePlan, textureUrl, onPlanChange: applyRenderedPlan, highlightNames: commandPreview?.affectedNodeIds, transformSpace, transformSnap } } : undefined;
  const workerArtifact: ArtifactSchema | undefined = workerAsset ? { id: 'text3d-worker-current', type: 'cad-model-3d', name: workerAsset.name, data: { name: workerAsset.name, format: workerAsset.format, assetId:workerAsset.id,streamUrl:`/api/model-assets/${workerAsset.id}/content`,byteSize:Number(workerAsset.metadata.byteSize??workerAsset.content?.byteSize??0),version: workerAsset.version } } : undefined;

  return <div className="ai-studio-page" data-testid="ai-studio">
    <div className="page-heading"><div><div className="eyebrow"><Sparkles size={13} /> AI 3D STUDIO</div><h1>自然语言参数化 3D 工作室</h1><p>{message}</p></div><div className="studio-provider"><select aria-label="AI Provider" value={provider} onChange={(event) => setProvider(event.target.value)}><option value="local">本地规划器</option><option value="deepseek">DeepSeek</option><option value="kimi">Kimi</option><option value="qwen">Qwen</option><option value="openai">OpenAI</option></select>{provider !== 'local' && <><input aria-label="Model" placeholder="模型名称（可选）" value={model} onChange={(event) => setModel(event.target.value)} /><small>API 凭据由服务端环境变量提供</small></>}</div></div>
    <div className="studio-template-row">{templates.map((template) => <button key={template.id} onClick={() => chooseTemplate(template)}><strong>{template.name}</strong><span>{template.description}</span></button>)}</div>
    <div className="studio-prompt card"><Bot size={19} /><textarea aria-label="3D 模型描述" value={prompt} onChange={(event) => setPrompt(event.target.value)} /><div className="studio-generate-actions"><select aria-label="Text-to-3D Provider" value={text3DProvider} onChange={(event) => setText3DProvider(event.target.value)}>{text3DProviders.map((item) => <option key={item.id} value={item.id} disabled={!item.configured}>{item.label}{item.configured ? '' : '（未配置）'}</option>)}</select><label className="texture-upload"><ImagePlus size={14} />参考图<input type="file" accept="image/*" onChange={(event) => loadReferenceImage(event.target.files?.[0])} /></label><label className="texture-upload"><Download size={14}/>导入模型与依赖<input multiple type="file" accept=".glb,.gltf,.obj,.stl,.ply,.step,.stp,.iges,.igs,.brep,.brp,.bin,image/*,model/gltf-binary,model/gltf+json" onChange={(event)=>loadEditableModel(event.target.files)}/></label><button className="run-button" onClick={generate} disabled={busy}><Send size={15} />Agent 参数模型</button><button className="run-button secondary" onClick={generateSemanticMesh} disabled={busy}><Sparkles size={15} />Text-to-3D 网格</button>{busy && agentRun && !['completed','failed','cancelled'].includes(agentRun.status) && <button onClick={() => cancelStudioAgentRun(agentRun.id)}>取消 Agent</button>}{busy && text3DJob && !['completed','failed','cancelled'].includes(text3DJob.status) && <button onClick={() => cancelText3DJob(text3DJob.id)}>取消 3D</button>}</div></div>
    {plan && <div className="studio-prompt card scene-command"><Bot size={19} /><textarea aria-label="自然语言编辑 3D 场景" placeholder="例如：把左侧机翼向上移动 10cm；将相机云台旋转 15 度；把机身改成蓝色金属" value={sceneCommand} onChange={(event) => setSceneCommand(event.target.value)} /><div className="studio-generate-actions"><button onClick={previewCommand} disabled={!sceneCommand.trim()}>预览操作</button>{commandPreview && <><button className="run-button" onClick={confirmCommand}>确认并创建版本</button><button onClick={() => setCommandPreview(undefined)}>取消预览</button></>}</div></div>}
    {previewMode==='semantic'&&workerAsset?<SemanticSceneEditor asset={workerAsset} onAssetChange={setWorkerAsset}/>:<div className="studio-main">
      <section className="card studio-canvas"><div className="card-head"><div><span>{previewMode === 'semantic' ? 'NON-PARAMETRIC WORKER MESH' : 'PARAMETRIC SCENE'}</span><h3>{previewMode === 'semantic' ? workerAsset?.name : plan?.name ?? '等待生成'}</h3></div><div className="preview-switch">{artifact && <button className={previewMode === 'parametric' ? 'active' : ''} onClick={() => setPreviewMode('parametric')}>参数模型</button>}{workerArtifact && <button className={previewMode === 'semantic' ? 'active' : ''} onClick={() => setPreviewMode('semantic')}>语义网格</button>}{plan && <button onClick={() => { setBeforePlan(undefined); setPlan(undefined); }}><RotateCcw size={13} />清空</button>}</div></div>{previewMode === 'semantic' && workerArtifact ? <PluginHost input={workerArtifact} /> : artifact ? <PluginHost input={artifact} /> : <div className="studio-empty"><Sparkles size={34} /><strong>输入描述，或选择上方模板</strong><span>可选择 Agent 参数模型或独立 Text-to-3D Worker。</span></div>}{text3DJob && text3DJob.status !== 'completed' && <div className="worker-progress"><span style={{ width: `${text3DJob.progress}%` }} /><b>{text3DJob.stage} · {text3DJob.progress}%</b></div>}</section>
      <aside className="card studio-inspector"><div className="card-head"><div><span>NON-DESTRUCTIVE EDITOR</span><h3>场景图与修改器</h3></div><div className="preview-switch"><button aria-label="撤销" disabled={historyIndex <= 0} onClick={undo}><Undo2 size={14} /></button><button aria-label="重做" disabled={historyIndex >= editHistory.length - 1} onClick={redo}><Redo2 size={14} /></button></div></div>{plan ? <>
        <label>缩放 <b>{plan.parameters.scale.toFixed(2)}×</b><input type="range" min="0.4" max="2.5" step="0.05" value={plan.parameters.scale} onChange={(event) => commitPlan(updatePlan(plan, 'scale', Number(event.target.value)))} /></label>
        <label>复杂度 <b>{plan.parameters.complexity}/10</b><input type="range" min="1" max="10" step="1" value={plan.parameters.complexity} onChange={(event) => commitPlan(updatePlan(plan, 'complexity', Number(event.target.value)))} /></label>
        <label>曲面强度 <b>{plan.parameters.curveStrength.toFixed(2)}</b><input type="range" min="0" max="1" step="0.05" value={plan.parameters.curveStrength} onChange={(event) => commitPlan(updatePlan(plan, 'curveStrength', Number(event.target.value)))} /></label>
        <label>连接密度 <b>{plan.parameters.connectionDensity.toFixed(2)}</b><input type="range" min="0" max="1" step="0.05" value={plan.parameters.connectionDensity} onChange={(event) => commitPlan(updatePlan(plan, 'connectionDensity', Number(event.target.value)))} /></label>
        <label>主色<input type="color" value={plan.parameters.color} onChange={(event) => commitPlan(updatePlan(plan, 'color', event.target.value))} /></label>
        <label>材质<select value={plan.parameters.material} onChange={(event) => commitPlan(updatePlan(plan, 'material', event.target.value))}><option value="metal">Metal</option><option value="wood">Wood</option><option value="glass">Glass</option></select></label>
        <label className="texture-upload"><ImagePlus size={14} />上传纹理<input type="file" accept="image/*" onChange={(event) => texture(event.target.files?.[0])} /></label>
        <label>纹理横向重复 <b>{(plan.parameters.textureRepeatX ?? 1).toFixed(1)}</b><input type="range" min="0.5" max="8" step="0.5" value={plan.parameters.textureRepeatX ?? 1} onChange={(event) => commitPlan({ ...plan, parameters: { ...plan.parameters, textureRepeatX: Number(event.target.value) } })} /></label>
        <label>纹理纵向重复 <b>{(plan.parameters.textureRepeatY ?? 1).toFixed(1)}</b><input type="range" min="0.5" max="8" step="0.5" value={plan.parameters.textureRepeatY ?? 1} onChange={(event) => commitPlan({ ...plan, parameters: { ...plan.parameters, textureRepeatY: Number(event.target.value) } })} /></label>
        <label>纹理强度 <b>{(plan.parameters.textureStrength ?? .72).toFixed(2)}</b><input type="range" min="0" max="1" step="0.05" value={plan.parameters.textureStrength ?? .72} onChange={(event) => commitPlan({ ...plan, parameters: { ...plan.parameters, textureStrength: Number(event.target.value) } })} /></label>
        <label>多选节点<select multiple size={Math.min(6, plan.parts.length)} aria-label="编辑模型节点" value={selectedPartNames.length ? selectedPartNames : [selectedPart?.name ?? '']} onChange={(event) => { const names = [...event.target.selectedOptions].map((option) => option.value); setSelectedPartNames(names); setSelectedPartName(names[0] ?? ''); }}>{plan.parts.map((part) => <option key={part.name} value={part.name}>{part.groupId ? `[${part.groupId}] ` : ''}{part.name}</option>)}</select></label>
        <div className="studio-generate-actions"><button onClick={() => manualOperation('duplicate')}><Copy size={13} />复制</button><button onClick={() => manualOperation('group', { groupId: `group-${Date.now().toString(36)}` })}>成组</button><button onClick={() => manualOperation('delete')}><Trash2 size={13} />删除</button><button onClick={() => movePart(-1)}>CSG ↑</button><button onClick={() => movePart(1)}>CSG ↓</button></div>
        <label>坐标系<select value={transformSpace} onChange={(event) => setTransformSpace(event.target.value as typeof transformSpace)}><option value="world">World</option><option value="local">Local</option></select></label><label>吸附步长 <input type="number" min="0" max="5" step="0.01" value={transformSnap} onChange={(event) => setTransformSnap(Number(event.target.value))} /></label>
        {selectedPart && <><label>位置 X/Y/Z<div className="transform-vector">{selectedPart.position.map((value, index) => <input aria-label={`位置 ${'XYZ'[index]}`} key={index} type="number" step={transformSnap || .01} value={value} onChange={(event) => { const position = [...selectedPart.position]; position[index] = Number(event.target.value); updatePart({ position }); }} />)}</div></label><label>节点倒角 <b>{(selectedPart.bevel ?? .03).toFixed(3)}</b><input type="range" min="0" max="0.25" step="0.005" value={selectedPart.bevel ?? .03} onChange={(event) => updatePart({ bevel: Number(event.target.value), shape: selectedPart.shape === 'box' ? 'roundedBox' : selectedPart.shape })} /></label><label>CSG 操作<select aria-label="节点 CSG 操作" value={selectedPart.booleanOperation ?? 'union'} onChange={(event) => updatePart({ booleanOperation: event.target.value as NonNullable<typeof selectedPart.booleanOperation> })}><option value="base">Base</option><option value="union">Union</option><option value="subtract">Subtract</option><option value="intersect">Intersect</option></select></label><div className="studio-generate-actions"><button onClick={() => manualOperation('remesh', { targetFaces: 50000 })}>非破坏重拓扑</button><button onClick={() => manualOperation('repair', { normals: true, holes: true })}>修复网格</button></div></>}
        <label>网格精度<select aria-label="网格精度" value={meshQuality} onChange={(event) => setMeshQuality(event.target.value as typeof meshQuality)}><option value="standard">Standard</option><option value="high">High</option><option value="ultra">Ultra</option></select></label>
        <label>导出格式<select aria-label="3D 导出格式" value={exportFormat} onChange={(event) => setExportFormat(event.target.value as typeof exportFormat)}><option value="glb">GLB</option><option value="gltf">GLTF</option><option value="obj">OBJ</option></select></label>
        <button className="run-button" onClick={compileMesh} disabled={busy}><Download size={14} />生成并下载 {exportFormat.toUpperCase()}</button>
        <button className="run-button" onClick={save}><Save size={14} />{saved ? '保存新版本' : '保存模型版本'}</button>
      </> : <p className="muted-copy">生成后可实时调整尺寸、复杂度、曲面、连接、颜色、材质和纹理。</p>}</aside>
    </div>}
    {(plan || agentRun) && <div className="studio-lower-grid"><section className="card agent-panel"><div className="card-head"><div><span>RETRYABLE AGENT PIPELINE</span><h3>独立 Agent 与流式进度</h3></div><Play size={14} /></div>{agentRun ? <>{agentRun.stages.map((stage) => <div className={`agent-row ${stage.status}`} key={stage.id}><CheckCircle2 size={15} /><div><strong>{stage.name} · cycle {stage.cycle + 1}</strong><span>attempt {stage.attempt}/{stage.maxAttempts} · {stage.tokens} {stage.tokenSource === 'provider' ? 'provider tokens' : 'estimated workload tokens'} · ${stage.cost.toFixed(6)} · {stage.durationMs}ms{stage.error ? ` · ${stage.error}` : ''}</span></div><b>{stage.status}</b></div>)}<div className="agent-summary"><span>中间产物 {agentRun.artifacts.length}</span><span>总 Token {agentRun.totalTokens}</span><span>总成本 ${agentRun.totalCost.toFixed(6)}</span><span>总耗时 {agentRun.durationMs}ms</span></div></> : plan?.agents.map((agent) => <div className="agent-row" key={agent.id}><CheckCircle2 size={15} /><div><strong>{agent.name}</strong><span>{agent.message}</span></div><b>{agent.status}</b></div>)}</section>{plan && <section className="card quality-panel"><div className="quality-score"><strong>{plan.validation.score}</strong><span>质量评分</span></div>{plan.validation.checks.map((check) => <span key={check}><CheckCircle2 size={13} />{check}</span>)}{saved && <div className="feedback-row"><span>本次生成：</span>{[1, 2, 3, 4, 5].map((rating) => <button aria-label={`${rating} 星`} key={rating} onClick={() => sendStudioFeedback(saved.id, rating).then(() => setMessage(`已提交 ${rating} 星反馈`))}><Star size={14} /></button>)}</div>}</section>}</div>}
    {agentRun && <details className="card agent-artifacts"><summary>中间产物链 · {agentRun.artifacts.length} items</summary>{agentRun.artifacts.map((item) => <span key={item.id}>cycle {item.cycle + 1} · {item.stage} · {item.kind} · {item.id}</span>)}</details>}
    <section className="card studio-history"><div className="card-head"><div><span>VERSION HISTORY</span><h3>模型生成历史</h3></div><Clock3 size={14} /></div><div>{history.length ? history.map((item) => <button key={item.id} onClick={() => load(item)}><strong>{item.name}</strong><span>v{item.version} · {item.provider}</span><small>{item.prompt}</small></button>) : <p>保存后的模型会出现在这里。</p>}</div></section>
  </div>;
}
