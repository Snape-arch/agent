import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowRight, BookOpen, Braces, ChevronRight, Layers3, LoaderCircle, ScanEye, Search, Waves } from 'lucide-react';
import { defaultVisualState, switchVisualArm, teachingBase, teachingRequest, visualReportUrl, type Direction, type SavedVisual, type TeachingRecord, type VisualState } from '../visualizations/teachingData';
import { DiffusionVisual, LowRankVisual, RagVisual } from '../visualizations/TeachingVisuals';
import { pngFromSvg, serializeVisualSvg } from '../visualizations/exportVisual';
import { navigateWorkspace } from '../workspaceNavigation';

const topics=[
  {id:'rag' as Direction,lesson:'rag',icon:<Search/>,title:'追踪一条答案的来路',short:'检索与证据',question:'找到了相关内容，就能给出可信的答案吗？',copy:'把问题、检索片段、回答与来源检查展开，观察旧版资料怎样影响结果。',tags:['逐题观察','版本对照','失败分析']},
  {id:'peft' as Direction,lesson:'finetune',icon:<Braces/>,title:'拆开一次低秩更新',short:'矩阵与适配',question:'少量参数，怎样改变一个完整的权重矩阵？',copy:'从 A、B 两个小矩阵出发，逐格检查它们的乘积，再联系测试误差与参数成本。',tags:['矩阵热力图','逐格解释','真实曲线']},
  {id:'diffusion' as Direction,lesson:'diffusion',icon:<Waves/>,title:'沿着采样过程往回看',short:'分布与采样',question:'一步步靠近目标，究竟改变了什么？',copy:'拖动时间轴，观察数值积分中的均值与方差，再检查终点分位样本和目标的差异。',tags:['时间轴回放','分布对照','误差与成本']},
];
type ReportPage={items:{id:string;title:string;created:string}[];page:number;has_more:boolean;total:number};
function startingTopic():Direction {
  const params=new URLSearchParams(location.search),domain=params.get('domain'),lesson=params.get('lesson');
  return topics.find(t=>t.id===domain||t.lesson===lesson)?.id||'rag';
}
function armLabel(topic:Direction,arm:number,record?:TeachingRecord){
  const prefix=arm?'对照':'基线';if(!record)return prefix;
  const config=record.report.result.arms[arm].config;
  return prefix+' · '+(topic==='rag'?(config.current_only?'仅现行资料':'包含旧版资料'):topic==='peft'?'rank '+config.rank:config.steps+' 步');
}
function downloadBlob(blob:Blob,name:string){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);}

export function VisualLearningStudio(){
  const topic=startingTopic(),meta=topics.find(t=>t.id===topic)!;
  const [record,setRecord]=useState<TeachingRecord>(),[state,setState]=useState<VisualState>(),[rows,setRows]=useState<ReportPage['items']>([]),[page,setPage]=useState(1),[more,setMore]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [creating,setCreating]=useState(false),[hypothesis,setHypothesis]=useState(''),[busy,setBusy]=useState(false),[snapshots,setSnapshots]=useState<SavedVisual[]>([]),[snapshotPage,setSnapshotPage]=useState(1),[moreSnapshots,setMoreSnapshots]=useState(false),[message,setMessage]=useState('');
  const visualRoot=useRef<HTMLDivElement>(null),pending=useRef<{body:string;key:string}>(),pendingSave=useRef<{body:string;key:string}>();
  useEffect(()=>{
    let live=true;
    async function load(){
      try{
        const data=await teachingRequest<ReportPage>('/reports?template='+topic+'&page=1');if(!live)return;
        setRows(data.items);setMore(data.has_more);
        const params=new URLSearchParams(location.search),snapshot=params.get('teachingVisualization'),rid=params.get('teachingReport')||data.items[0]?.id;
        let r:TeachingRecord|undefined,s:VisualState|undefined;
        if(snapshot){const value=await teachingRequest<{record:TeachingRecord;view:SavedVisual}>('/visualizations/'+encodeURIComponent(snapshot));r=value.record;s=value.view.state;}
        else if(rid)r=await teachingRequest<TeachingRecord>('/reports/'+encodeURIComponent(rid));
        if(!live)return;
        if(r){
          if(r.report.result.template.id!==topic||r.report.result.arms.length!==2)throw Error('所选记录与当前教学方向不一致，请重新选择来源。');
          setRecord(r);setState(s||defaultVisualState(r));
          const saved=await teachingRequest<{items:SavedVisual[];has_more:boolean}>('/reports/'+r.report.id+'/visualizations');if(live){setSnapshots(saved.items);setMoreSnapshots(saved.has_more);}
        }
      }catch(e){if(live)setError(e instanceof Error?e.message:'可视化来源未加载');}finally{if(live)setLoading(false);}
    }
    void load();return()=>{live=false;};
  },[topic]);
  const selectReport=(id:string)=>navigateWorkspace('visuals',{domain:topic,teachingReport:id,teachingVisualization:null});
  async function nextPage(){setBusy(true);setError('');try{const data=await teachingRequest<ReportPage>('/reports?template='+topic+'&page='+(page+1));setRows(current=>[...new Map([...current,...data.items].map(r=>[r.id,r])).values()]);setPage(data.page);setMore(data.has_more);}catch(e){setError(e instanceof Error?e.message:'来源列表未加载');}finally{setBusy(false);}}
  async function nextSnapshots(){if(!record)return;setBusy(true);setError('');try{const data=await teachingRequest<{items:SavedVisual[];has_more:boolean}>('/reports/'+record.report.id+'/visualizations?page='+(snapshotPage+1));setSnapshots(current=>[...new Map([...current,...data.items].map(s=>[s.id,s])).values()]);setSnapshotPage(v=>v+1);setMoreSnapshots(data.has_more);}catch(e){setError(e instanceof Error?e.message:'视图列表未加载');}finally{setBusy(false);}}
  async function run(){
    const input={template:topic,value:topic==='rag'?true:topic==='peft'?2:32,seed:42,hypothesis,binding:null};
    const body=JSON.stringify(input),key=pending.current?.body===body?pending.current.key:crypto.randomUUID();pending.current={body,key};setBusy(true);setError('');
    try{const result=await teachingRequest<TeachingRecord>('/reports',{...input,request_id:key});selectReport(result.report.id);}catch(e){setError(e instanceof Error?e.message:'实验未完成');}finally{setBusy(false);}
  }
  async function save(){
    if(!record||!state)return;setBusy(true);setError('');
    const input={name:meta.short+' · '+armLabel(topic,state.arm,record),report_hash:record.hash,state};const body=JSON.stringify(input),key=pendingSave.current?.body===body?pendingSave.current.key:crypto.randomUUID();pendingSave.current={body,key};
    try{const view=await teachingRequest<SavedVisual>('/reports/'+record.report.id+'/visualizations',{...input,request_id:key});navigateWorkspace('visuals',{domain:topic,teachingReport:record.report.id,teachingVisualization:view.id});}catch(e){setError(e instanceof Error?e.message:'视图未保存');}finally{setBusy(false);}
  }
  async function exportGraphic(png=false){
    if(!record)return;const svg=visualRoot.current?.querySelector<SVGSVGElement>('svg[data-visual-export]');if(!svg)return setError('当前没有可导出的图形。');
    try{
      const blob=serializeVisualSvg(svg,{report:record.report.id,sha256:record.hash,execution:record.report.result.execution,state,boundary:record.report.result.boundary}),name='clawos-'+topic+'-'+record.report.id.slice(0,8);
      if(!png){downloadBlob(blob,name+'.svg');setMessage('SVG已导出，包含实验来源与视图状态。');return;}
      const box=svg.viewBox.baseVal;downloadBlob(await pngFromSvg(blob,1280,box.height/box.width),name+'.png');setMessage('PNG已导出；精确数据与来源请同时保留JSON报告。');
    }catch(e){setError(e instanceof Error?e.message:'图形导出失败');}
  }
  return <section className="visual-studio" aria-labelledby="visual-studio-title"><header className="visual-studio-header"><div><span className="visual-kicker"><ScanEye size={14}/>可视化教学</span><h1 id="visual-studio-title">把抽象，变得可见。</h1><p>从一个问题开始。看清过程、动手比较，再回到证据。</p></div><a href="/academy/lab"><BookOpen size={15}/>课程与知识图谱<ChevronRight size={14}/></a></header>
    <div className="visual-topics" role="group" aria-label="选择可视化主题">{topics.map((t,i)=><button key={t.id} aria-pressed={topic===t.id} onClick={()=>navigateWorkspace('visuals',{domain:t.id,lesson:t.lesson,teachingReport:null,teachingVisualization:null})}><span className="topic-number">0{i+1}</span>{t.icon}<span><strong>{t.short}</strong><small>{t.question}</small></span><ArrowRight size={16}/></button>)}</div>
    {error&&<p className="visual-error" role="alert">{error}</p>}<p className="visual-message" role="status" aria-live="polite">{message}</p>
    <article className="visual-lesson"><header className="visual-lesson-heading"><div><span className="visual-kicker">{meta.tags.join(' / ')}</span><h2>{meta.title}</h2><p>{meta.copy}</p></div><button className="visual-secondary" onClick={()=>setCreating(v=>!v)}>{creating?'收起实验配置':'新建机制实验'}</button></header>
      {creating&&<form className="visual-run-form" onSubmit={e=>{e.preventDefault();void run();}}><div><h3>先写预测，再运行对照</h3><p>使用本节默认条件和合成教学资料，不调用大模型。更多参数及教材关联可在实验手册中设置。</p><a href={'/academy/vision/?domain='+topic+'#teaching'}>打开完整实验手册<ArrowRight size={14}/></a></div><label>实验前预测<textarea required minLength={10} maxLength={2000} value={hypothesis} disabled={busy} onChange={e=>setHypothesis(e.target.value)} placeholder="你预计哪里会改变？哪些结论还不能得出？"/></label><button className="visual-primary" disabled={busy}>{busy?<LoaderCircle className="visual-spinner" size={16}/>:<PlayIcon/>}运行本节默认对照</button></form>}
      <div className="visual-source-toolbar"><label>实验来源<select disabled={loading||busy||!record} value={record?.report.id||''} onChange={e=>selectReport(e.target.value)}>{!record&&<option value="">{loading?'正在读取已保存实验…':'尚无已保存实验'}</option>}{record&&!rows.some(r=>r.id===record.report.id)&&<option value={record.report.id}>{new Date(record.report.created).toLocaleString('zh-CN')} · 当前历史记录</option>}{rows.map(r=><option key={r.id} value={r.id}>{new Date(r.created).toLocaleString('zh-CN')} · {r.title}</option>)}</select></label>{more&&<button disabled={busy} onClick={()=>{void nextPage();}}>加载更多来源</button>}{record&&state&&<div className="visual-arm-switch" role="group" aria-label="选择基线或对照">{[0,1].map(arm=><button key={arm} aria-pressed={state.arm===arm} onClick={()=>setState(switchVisualArm(record,state,arm))}>{armLabel(topic,arm,record)}</button>)}</div>}</div>
      {loading?<div className="visual-loading" role="status"><LoaderCircle size={20} className="visual-spinner"/>正在读取实验依据…</div>:record&&state?<><div className="visual-provenance"><span className="source-dot"/>已保存实验 · 真实CPU计算 / 合成教学资料<span>来源摘要 {record.hash.slice(0,12)}…</span></div><div className="visual-canvas" ref={visualRoot}>{state.kind==='rag-source'?<RagVisual record={record} state={state} onChange={setState}/>:state.kind==='low-rank'?<LowRankVisual record={record} state={state} onChange={setState}/>:<DiffusionVisual record={record} state={state} onChange={setState}/>}</div><footer className="visual-evidence-footer"><p>{record.report.result.boundary}</p><div><button disabled={busy} className="visual-primary" onClick={()=>{void save();}}>保存当前视图</button><button onClick={()=>{void exportGraphic();}}><ArrowDownToLine size={14}/>主图 SVG</button><button onClick={()=>{void exportGraphic(true);}}>PNG</button><a href={teachingBase+'/reports/'+record.report.id+'/export'}>完整依据 JSON</a><a href={visualReportUrl(record,'teaching')}>写学习反思<ArrowRight size={14}/></a></div></footer>{snapshots.length>0&&<section className="visual-saved"><h3>保存的观察视图</h3>{snapshots.map(s=><a key={s.id} href={'/academy/vision/?domain='+topic+'&teachingReport='+record.report.id+'&teachingVisualization='+s.id+'#visuals'}><Layers3 size={14}/>{s.name}<small>{new Date(s.created).toLocaleString('zh-CN')}</small><ArrowRight size={14}/></a>)}{moreSnapshots&&<button disabled={busy} onClick={()=>{void nextSnapshots();}}>加载更多观察视图</button>}</section>}</>:error?<div className="visual-no-evidence"><h3>实验依据暂时不可读取。</h3><p>请检查上方错误。未使用示例或推测数值替代失败的请求。</p></div>:<div className="visual-no-evidence"><div className="empty-step-labels"><span>提出预测</span><ArrowRight size={18}/><span>运行对照</span><ArrowRight size={18}/><span>看见机制</span></div><h3>先产生一次可以回看的观察。</h3><p>当前没有这一方向的实验记录。运行上方默认对照后，矩阵、来源片段或采样步骤会直接使用保存的实际数值展开。</p><button className="visual-primary" onClick={()=>setCreating(true)}>开始这节可视化实验<ArrowRight size={15}/></button></div>}
    </article>
    <section className="visual-extension"><div><span className="visual-kicker">继续探索</span><h2>同一个工作区，更多观察方式。</h2><p>把机制理解延伸到自己的数据、模型与空间。所有工具共用导航，示例和实验结果各自标明来源。</p></div><div>{[{id:'data' as const,title:'数据图表',text:'折线、散点、热力与箱线联动',icon:<ScanEye/>},{id:'three' as const,title:'三维空间',text:'模型、点云、轨迹与参数观察',icon:<Layers3/>},{id:'evaluation' as const,title:'视觉诊断',text:'评估、失败样本与版本比较',icon:<Search/>}].map(t=><button key={t.id} onClick={()=>navigateWorkspace(t.id)}>{t.icon}<span><strong>{t.title}</strong><small>{t.text}</small></span><ArrowRight size={16}/></button>)}</div></section>
  </section>;
}
function PlayIcon(){return <ChevronRight size={16}/>;}
