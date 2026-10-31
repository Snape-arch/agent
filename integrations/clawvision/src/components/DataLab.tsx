import { useEffect, useMemo, useState, type DragEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Download, GripVertical, Link2, Plus, Save, Upload, X } from 'lucide-react';
import { fetchDatasetPage, fetchDataset, fetchVisualization, fetchSharedVisualization, importDataset, saveVisualization, type DatasetField, type DatasetSummary, type ImportedDataset } from '../api';
import { integrated } from '../clawos';
import { PluginHost } from '../visualizations/PluginHost';
import type { ArtifactSchema, VisualizationSpec } from '../visualizations/types';

type ChartType = 'line-chart' | 'bar-chart' | 'scatter-chart' | 'heatmap-chart' | 'boxplot-chart';
interface ChartConfig { id: string; type: ChartType; title: string; xField: string; yField: string; layout?: { w: number; h: number } }

const demoRows = Array.from({ length: 48 }, (_, index) => ({
  time: `2026-07-${String((index % 12) + 1).padStart(2, '0')}`,
  region: ['华东', '华南', '华北', '西部'][index % 4],
  model: ['small', 'base', 'large'][index % 3],
  accuracy: Number((.72 + (index % 12) * .018 + (index % 3) * .025).toFixed(3)),
  loss: Number((1.4 * Math.exp(-(index % 12) / 5) + (index % 4) * .04).toFixed(3)),
  samples: 800 + (index % 7) * 140,
}));
const demoSchema: DatasetField[] = [{ name: 'time', type: 'datetime', nullable: false }, { name: 'region', type: 'string', nullable: false }, { name: 'model', type: 'string', nullable: false }, { name: 'accuracy', type: 'number', nullable: false }, { name: 'loss', type: 'number', nullable: false }, { name: 'samples', type: 'number', nullable: false }];
const demoDataset: ImportedDataset = { id: 'demo-p5', name: '训练表现样例', format: 'json', schema: demoSchema, rows: demoRows, rowCount: demoRows.length, createdAt: new Date().toISOString() };
const emptyDataset:ImportedDataset={id:'',name:'尚未选择数据集',format:'json',schema:[],rows:[],rowCount:0,createdAt:''};
const initialCharts: ChartConfig[] = [
  { id: 'chart-line', type: 'line-chart', title: '准确率趋势', xField: 'time', yField: 'accuracy' },
  { id: 'chart-bar', type: 'bar-chart', title: '区域样本量', xField: 'region', yField: 'samples' },
  { id: 'chart-box', type: 'boxplot-chart', title: '模型 Loss 分布', xField: 'model', yField: 'loss' },
];

function encodeBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer); let binary = '';
  for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  return btoa(binary);
}
function download(name: string, blob: Blob) { const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 500); }

export function DataLab() {
  const [dataset, setDataset] = useState<ImportedDataset>(integrated()?emptyDataset:demoDataset);
  const [charts, setCharts] = useState<ChartConfig[]>(integrated()?[]:initialCharts);
  const [selectedId, setSelectedId] = useState(integrated()?'':initialCharts[0].id);
  const [catalog,setCatalog]=useState<DatasetSummary[]>([]);const [page,setPage]=useState(1);const [next,setNext]=useState(false);const [loading,setLoading]=useState(false);
  const [filter, setFilter] = useState<{ field: string; value: unknown }>();
  const [draggedId, setDraggedId] = useState<string>();
  const [saved, setSaved] = useState<{ id: string; version: number; link: string }>();
  const [message, setMessage] = useState('CSV / JSON / Parquet · 自动识别字段类型');
  const selected = charts.find((chart) => chart.id === selectedId) ?? charts[0];
  const numericFields = dataset.schema.filter((field) => field.type === 'number');
  const filteredRows = useMemo(() => filter ? dataset.rows.filter((row) => String(row[filter.field]) === String(filter.value)) : dataset.rows, [dataset, filter]);

  function adopt(data:ImportedDataset,remember=true) {
    setDataset(data);setFilter(undefined);setSaved(undefined);
    const x=data.schema[0]?.name;const y=data.schema.find(f=>f.type==='number'&&f.name!==x)?.name ?? data.schema.find(f=>f.type==='number')?.name ?? data.schema[1]?.name;
    const chart:ChartConfig|undefined=x&&y?{id:crypto.randomUUID(),type:'line-chart',title:`${y} 趋势`,xField:x,yField:y}:undefined;
    setCharts(chart?[chart]:[]);setSelectedId(chart?.id ?? '');
    setMessage(data.id==='demo-p5'?'内置示例数据，不是导入数据或真实训练结果。':`已加载 ${data.name} · ${data.rowCount} 行，当前图表使用 ${data.rows.length} 行预览。`);
    if(integrated()&&remember){const url=new URL(location.href);url.searchParams.set('dataset',data.id);url.searchParams.delete('visualization');history.replaceState({},'',url);}
  }
  async function loadDataset(id:string) {setLoading(true);try{adopt((await fetchDataset(id)).data);}catch(e){setMessage(e instanceof Error?e.message:'数据集加载失败');}finally{setLoading(false);}}
  useEffect(()=>{
    if(!integrated())return;
    let active=true;setLoading(true);
    fetchDatasetPage(page).then(async result=>{
      if(!active)return;setCatalog(result.data);setNext(result.pagination.hasNext);
      const query=new URLSearchParams(location.search);const vid=query.get('visualization');
      if(vid){const {data}=await fetchVisualization(vid);if(!active)return;const spec=data.spec as unknown as {datasetSnapshot?:ImportedDataset;charts?:ChartConfig[]};
        if(spec.datasetSnapshot)adopt(spec.datasetSnapshot,false);if(spec.charts?.length){setCharts(spec.charts);setSelectedId(spec.charts[0].id);}setSaved({id:data.id,version:data.version,link:location.href});setMessage(`已恢复私有图表 v${data.version}`);return;}
      const did=query.get('dataset');if(did==='demo-p5'){if(active){adopt(demoDataset,false);setCharts(initialCharts);setSelectedId(initialCharts[0].id);}return;}
      if(did||result.data[0]){const data=await fetchDataset(did ?? result.data[0].id);if(active)adopt(data.data,false);}else setMessage('还没有已保存数据集。导入CSV、JSON或Parquet，或明确打开内置示例。');
    }).catch(e=>{if(active)setMessage(e instanceof Error?e.message:'数据目录加载失败；未使用示例数据替代。');}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[page]);

  useEffect(() => {
    const token = new URLSearchParams(location.search).get('shared');
    if (!token) return;
    fetchSharedVisualization(token).then(({ data }) => {
      const savedSpec = data.spec as unknown as Record<string, unknown>;
      const snapshot = savedSpec.datasetSnapshot as ImportedDataset | undefined;
      const restoredCharts = savedSpec.charts as ChartConfig[] | undefined;
      if (snapshot) setDataset(snapshot);
      if (restoredCharts?.length) { setCharts(restoredCharts); setSelectedId(restoredCharts[0].id); }
      setSaved({ id: data.id, version: data.version, link: location.href });
      setMessage(`已加载分享版本 v${data.version}`);
    }).catch(() => setMessage('分享链接无效或未公开'));
  }, []);

  const handleFile = async (file?: File) => {
    if (!file) return;
    const extension = file.name.split('.').pop()?.toLowerCase() as ImportedDataset['format'];
    if (!['csv', 'json', 'parquet'].includes(extension)) return setMessage('仅支持 CSV、JSON、Parquet');
    setMessage(`正在导入 ${file.name}…`);
    try {
      const content = extension === 'parquet' ? encodeBase64(await file.arrayBuffer()) : await file.text();
      const response = await importDataset(file.name, extension, content);
      adopt(response.data);setCatalog(current=>[response.data,...current.filter(x=>x.id!==response.data.id)].slice(0,30));
    } catch (error) { setMessage(error instanceof Error ? error.message : '导入失败'); }
  };

  const updateSelected = (patch: Partial<ChartConfig>) => setCharts((current) => current.map((chart) => chart.id === selected.id ? { ...chart, ...patch } : chart));
  const addChart = () => { const chart = { id: crypto.randomUUID(), type: 'scatter-chart' as ChartType, title: '新图表', xField: dataset.schema[0]?.name ?? '', yField: numericFields[0]?.name ?? '' }; setCharts((current) => [...current, chart]); setSelectedId(chart.id); };
  const onDrop = (event: DragEvent, targetId: string) => { event.preventDefault(); if (!draggedId || draggedId === targetId) return; setCharts((current) => { const next = [...current]; const from = next.findIndex((item) => item.id === draggedId); const to = next.findIndex((item) => item.id === targetId); const [item] = next.splice(from, 1); next.splice(to, 0, item); return next; }); setDraggedId(undefined); };
  const startResize = (event: ReactPointerEvent, chart: ChartConfig) => {
    event.preventDefault(); event.stopPropagation();
    const origin = { x: event.clientX, y: event.clientY, w: chart.layout?.w ?? 1, h: chart.layout?.h ?? 1 };
    const move = (pointer: PointerEvent) => setCharts((items) => items.map((item) => item.id === chart.id ? { ...item, layout: { w: Math.max(1, Math.min(2, origin.w + Math.round((pointer.clientX - origin.x) / 220))), h: Math.max(1, Math.min(3, origin.h + Math.round((pointer.clientY - origin.y) / 150))) } } : item));
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
  };
  const artifactFor = (chart: ChartConfig): ArtifactSchema => ({ id: chart.id, type: chart.type, name: chart.title, data: { rows: filteredRows }, metadata: { xField: chart.xField, yField: chart.yField } });

  const exportChart = async (format: 'svg' | 'png' | 'csv') => {
    if (format === 'csv') { const keys = dataset.schema.map((field) => field.name); const csv = [keys.join(','), ...filteredRows.map((row) => keys.map((key) => JSON.stringify(row[key] ?? '')).join(','))].join('\n'); return download(`${dataset.name}.csv`, new Blob([csv], { type: 'text/csv;charset=utf-8' })); }
    const svg = document.querySelector(`[data-chart-id="${selected.id}"] svg`);
    if (!(svg instanceof SVGElement)) return setMessage('当前图表没有可导出的 SVG');
    const source = new XMLSerializer().serializeToString(svg);
    if (format === 'svg') return download(`${selected.title}.svg`, new Blob([source], { type: 'image/svg+xml' }));
    const image = new Image(); const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml' }));
    image.onload = () => { const canvas = document.createElement('canvas'); canvas.width = 1280; canvas.height = 540; const context = canvas.getContext('2d'); if (context) { context.fillStyle = '#08110f'; context.fillRect(0, 0, canvas.width, canvas.height); context.drawImage(image, 0, 0, canvas.width, canvas.height); canvas.toBlob((blob) => blob && download(`${selected.title}.png`, blob), 'image/png'); } URL.revokeObjectURL(url); }; image.src = url;
  };
  const save = async () => {
    const spec = { pluginId: 'dashboard', charts, datasetSnapshot: dataset, filters: filter ? { [filter.field]: filter.value } : {}, version: 1 };
    const response = await saveVisualization({ id: saved?.id, name: `${dataset.name} Dashboard`, datasetId: dataset.id, spec, isPublic: !integrated() });
    const target=new URL(location.href);target.searchParams.delete('dataset');target.searchParams.delete('shared');target.searchParams.set('visualization',response.data.id);target.hash='data';
    const link = integrated()?target.href:`${location.origin}${location.pathname}?shared=${response.data.shareToken}`;
    setSaved({ id: response.data.id, version: response.data.version, link }); setMessage(`VisualizationSpec v${response.data.version} 已保存`);
  };

  return <div className="data-lab" data-testid="data-lab">
    <div className="page-heading"><div><div className="eyebrow">数据分析与可视化</div><h1>通用数据工作台</h1><p role="status">{message}</p></div><div className="lab-actions"><label className="upload-btn"><Upload size={14} />导入数据<input type="file" accept=".csv,.json,.parquet" onChange={(event) => handleFile(event.target.files?.[0])} /></label><button disabled={!dataset.id||dataset.id==='demo-p5'||loading} onClick={()=>{void save().catch(e=>setMessage(e instanceof Error?e.message:'保存失败'));}}><Save size={14} />保存图表</button></div></div>
    {integrated()&&<div className="dataset-picker"><label>已保存的数据集<select aria-label="已保存的数据集" disabled={loading} value={dataset.id} onChange={e=>{void loadDataset(e.target.value);}}><option value="">选择数据集</option>{dataset.id==='demo-p5'&&<option value="demo-p5">内置示例（非真实数据）</option>}{catalog.map(d=><option key={d.id} value={d.id}>{d.name} · {d.rowCount}行</option>)}</select></label><button disabled={page<=1||loading} onClick={()=>setPage(p=>p-1)}>上一页数据</button><button disabled={!next||loading} onClick={()=>setPage(p=>p+1)}>下一页数据</button><button onClick={()=>{adopt(demoDataset);setCharts(initialCharts);setSelectedId(initialCharts[0].id);}}>查看内置示例</button></div>}
    <div className="dataset-strip card"><div><strong>{dataset.name}</strong><span>{dataset.rowCount} 行 · {dataset.schema.length} 字段</span></div><div className="field-chips">{dataset.schema.map((field) => <span key={field.name}>{field.name}<b>{field.type}</b></span>)}</div>{filter && <button onClick={() => setFilter(undefined)}><X size={12} />{filter.field} = {String(filter.value)}</button>}</div>
    {saved && <div className="share-strip"><Link2 size={13} /><a href={saved.link}>{integrated()?'重新打开私有图表':'打开分享图表'}</a><span>v{saved.version}</span></div>}
    <div className="data-lab-layout">
      <aside className="chart-config card"><div className="card-head"><div><span>VISUALIZATION SPEC</span><h2>图表配置</h2></div></div>{selected && <>
        <label>标题<input value={selected.title} onChange={(event) => updateSelected({ title: event.target.value })} /></label>
        <label>图表类型<select value={selected.type} onChange={(event) => updateSelected({ type: event.target.value as ChartType })}><option value="line-chart">折线图</option><option value="bar-chart">柱状图</option><option value="scatter-chart">散点图</option><option value="heatmap-chart">热力图</option><option value="boxplot-chart">箱线图</option></select></label>
        <label>X 字段<select value={selected.xField} onChange={(event) => updateSelected({ xField: event.target.value })}>{dataset.schema.map((field) => <option key={field.name}>{field.name}</option>)}</select></label>
        <label>Y 字段<select value={selected.yField} onChange={(event) => updateSelected({ yField: event.target.value })}>{dataset.schema.map((field) => <option key={field.name}>{field.name}</option>)}</select></label>
        <div className="export-actions"><button onClick={() => exportChart('png')}><Download size={12} />PNG</button><button onClick={() => exportChart('svg')}>SVG</button><button onClick={() => exportChart('csv')}>CSV</button></div>
      </>}</aside>
      <div className="dashboard-grid-p5">{charts.map((chart) => <section style={{ gridColumn: `span ${chart.layout?.w ?? 1}`, gridRow: `span ${chart.layout?.h ?? 1}` }} className={`card dashboard-tile ${selectedId === chart.id ? 'selected' : ''}`} data-chart-id={chart.id} draggable onDragStart={() => setDraggedId(chart.id)} onDragOver={(event) => event.preventDefault()} onDrop={(event) => onDrop(event, chart.id)} onClick={() => setSelectedId(chart.id)} key={chart.id}><div className="card-head"><div><span>{chart.type}</span><h3>{chart.title}</h3></div><GripVertical size={15} /></div><PluginHost input={artifactFor(chart)} spec={{ pluginId: `core.${chart.type}`, options: { xField: chart.xField, yField: chart.yField } }} runtime={{ filters: filter ? { [filter.field]: filter.value } : {}, onFilterChange: (field, value) => setFilter({ field, value }) }} /><button className="dashboard-resize" aria-label="调整图表大小" onPointerDown={(event) => startResize(event, chart)} /></section>)}<button className="add-chart" onClick={addChart}><Plus size={16} />添加图表</button></div>
    </div>
  </div>;
}
