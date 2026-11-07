import { useEffect, useState } from 'react';
import type { EvaluationPage } from '../evaluationApi';
import * as api from '../visionApi';
const labels={queued:'排队中',running:'训练中',completed:'已完成',failed:'失败',cancelled:'已取消'};
const errorText=(e:unknown)=>e instanceof Error?e.message:'训练对比操作失败';
const percent=(v:number)=>`${(v*100).toFixed(1)}%`;
export function TrainingComparisonWorkbench({canWrite}:{canWrite:boolean}) {
  const [versions,setVersions]=useState<EvaluationPage<api.ImageVersion>>(),[versionPage,setVersionPage]=useState(1),[refresh,setRefresh]=useState(0);
  const [options,setOptions]=useState<api.ImageVersion[]>([]),[train,setTrain]=useState(''),[synthetic,setSynthetic]=useState(''),[test,setTest]=useState('');
  const [cfg,setCfg]=useState<api.TrainingConfig>({seed:42,epochs:50,learningRate:.1,regularization:.001});
  const [jobs,setJobs]=useState<EvaluationPage<api.VisionExperiment>>(),[page,setPage]=useState(1),[selected,setSelected]=useState(''),[job,setJob]=useState<api.VisionExperiment>();
  const [busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[notice,setNotice]=useState('');
  useEffect(()=>{const created=()=>setRefresh(v=>v+1);window.addEventListener('vision-version-created',created);return()=>window.removeEventListener('vision-version-created',created);},[]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);
    api.fetchImageVersions(versionPage,controller.signal).then(value=>{setVersions(value);setOptions(old=>[...new Map([...old.filter(v=>[train,synthetic,test].includes(v.id)),...value.data].map(v=>[v.id,v])).values()]);})
      .catch(e=>{if(!controller.signal.aborted)setError(errorText(e));}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[versionPage,refresh,train,synthetic,test]);
  useEffect(()=>{const controller=new AbortController();setJobs(undefined);api.fetchVisionExperiments(page,controller.signal).then(setJobs).catch(e=>{if(!controller.signal.aborted)setError(errorText(e));});return()=>controller.abort();},[page,refresh]);
  useEffect(()=>{
    setJob(undefined);if(!selected)return;const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    const poll=async()=>{try{const {data}=await api.fetchVisionExperiment(selected,controller.signal);if(controller.signal.aborted)return;
      setJob(data);setJobs(old=>old?{...old,data:old.data.map(v=>v.id===data.id?data:v)}:old);if(['queued','running'].includes(data.status))timer=setTimeout(()=>void poll(),1500);
    }catch(e){if(!controller.signal.aborted)setError(errorText(e));}};
    void poll();return()=>{controller.abort();clearTimeout(timer);};
  },[selected,refresh]);
  const upload=async(file?:File)=>{
    if(!file||!canWrite)return;setBusy(true);setError('');setNotice('');
    try{if(file.size>96*1024*1024)throw new Error('图片清单文件不得超过 96 MiB');const {data}=await api.createImageDataset(JSON.parse(await file.text()));
      setNotice(`${data.name} v${data.version} 已冻结 · ${data.sampleCount} 张`);setVersionPage(1);setRefresh(v=>v+1);
    }catch(e){setError(errorText(e));}finally{setBusy(false);}
  };
  const start=async()=>{if(!canWrite)return;setBusy(true);setError('');try{const {data}=await api.createVisionExperiment(train,synthetic,test,cfg);setSelected(data.id);setPage(1);setRefresh(v=>v+1);}catch(e){setError(errorText(e));}finally{setBusy(false);}};
  const action=async(value:'cancel'|'retry')=>{if(!job||!canWrite)return;setBusy(true);setError('');try{await api.visionExperimentAction(job.id,value);setRefresh(v=>v+1);}catch(e){setError(errorText(e));}finally{setBusy(false);}};
  const download=()=>{if(!job)return;const url=URL.createObjectURL(new Blob([JSON.stringify(job,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`${job.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  const select=(label:string,value:string,set:(v:string)=>void,origin:api.ImageVersion['origin'],purpose:api.ImageVersion['purpose'])=><label>{label}<select aria-label={label} required value={value} onChange={e=>set(e.target.value)}><option value="">请选择固定版本</option>{options.filter(v=>v.origin===origin&&v.purpose===purpose).map(v=><option key={v.id} value={v.id}>{v.name} v{v.version} · {v.sampleCount} 张 · {v.id}</option>)}</select></label>;
  return <section className="card training-comparison"><div className="card-head"><h2>6. 数据版本与真实训练对比</h2></div>
    <p>CPU 基线从 RGB 网格与颜色统计特征学习分类权重。分别训练“仅真实数据”和“真实＋合成数据”，用同一份独立真实测试图片推理并对比。</p>
    <p className="evaluation-note">两组使用相同算法、种子和超参数；固定轮数，测试集不参与拟合或模型选择。这是轻量分类基线，复杂视觉任务仍需专用模型。</p>
    {error&&<div role="alert" className="evaluation-error">{error}<button disabled={busy} onClick={()=>{setError('');setRefresh(v=>v+1);}}>重新加载训练数据</button></div>}{notice&&<p role="status">{notice}</p>}
    {canWrite&&<label>导入真实图片版本 JSON<input aria-label="真实图片版本 JSON" type="file" accept=".json,application/json" disabled={busy} onChange={e=>{void upload(e.target.files?.[0]);e.target.value='';}}/></label>}
    <details><summary>真实图片清单格式</summary><pre>{JSON.stringify({name:'独立真实测试集',purpose:'test',samples:[{id:'part-001',label:'gear',imageBase64:'PNG/JPEG 的 base64',conditions:{lighting:'low'}}]},null,2)}</pre><p>训练版本 purpose 为 train，测试版本为 test；真实训练图片须覆盖至少两个类别。在 JSON 中提供 datasetId 可创建同一数据集的新版本。</p></details>
    <h3>固定图片版本</h3>{loading?<p role="status">加载图片版本…</p>:!versions?.data.length?<p>尚无图片版本。导入真实训练与测试清单，并在已完成合成任务中点击“登记合成数据集版本”。</p>:<div className="evaluation-table-scroll"><table><thead><tr><th>数据集 / 版本</th><th>来源 / 用途</th><th>图片</th><th>摘要</th></tr></thead><tbody>{versions.data.map(v=><tr key={v.id}><td>{v.name} v{v.version}<small>{v.id}</small></td><td>{v.origin==='real'?'真实':'合成'} / {v.purpose==='train'?'训练':'测试'}</td><td>{v.sampleCount}</td><td><code title={v.digest}>{v.digest.slice(0,12)}…</code></td></tr>)}</tbody></table></div>}
    {versions&&<div className="evaluation-pager" aria-label="图片版本分页"><span>{versions.pagination.total} 条 · 第 {versionPage} 页</span><button disabled={busy||loading||!versions.pagination.hasPrevious} onClick={()=>setVersionPage(v=>v-1)}>上一页</button><button disabled={busy||loading||!versions.pagination.hasNext} onClick={()=>setVersionPage(v=>v+1)}>下一页</button></div>}
    {canWrite&&<form onSubmit={e=>{e.preventDefault();void start();}}><fieldset disabled={busy}><legend>启动固定条件对比</legend><div className="scene-form-grid">
      {select('真实训练版本',train,setTrain,'real','train')}{select('合成训练版本',synthetic,setSynthetic,'synthetic','train')}{select('独立真实测试版本',test,setTest,'real','test')}
      {(['seed','epochs','learningRate','regularization'] as const).map(k=><label key={k}>{{seed:'随机种子',epochs:'固定训练轮数',learningRate:'学习率',regularization:'L2 正则化'}[k]}<input aria-label={`CPU ${k}`} type="number" required value={cfg[k]} min={k==='epochs'?1:k==='learningRate'?.0001:0} max={k==='epochs'?200:k==='seed'?4294967295:1} step={['seed','epochs'].includes(k)?1:'any'} onChange={e=>setCfg(v=>({...v,[k]:Number(e.target.value)}))}/></label>)}
    </div><button disabled={busy||!train||!synthetic||!test} type="submit">开始真实训练对比</button></fieldset></form>}
    <h3>训练对比记录</h3>{!jobs?<p role="status">加载训练对比…</p>:!jobs.data.length?<p>尚无真实训练对比。</p>:<div className="evaluation-list">{jobs.data.map(v=><button key={v.id} aria-pressed={selected===v.id} disabled={busy} onClick={()=>{setError('');setSelected(v.id);}}><strong>{labels[v.status]} · {v.epochsCompleted}/{v.totalEpochs} 轮</strong><small>{v.id}</small></button>)}</div>}
    {jobs&&<div className="evaluation-pager" aria-label="训练对比分页"><span>{jobs.pagination.total} 条 · 第 {page} 页</span><button disabled={busy||!jobs.pagination.hasPrevious} onClick={()=>setPage(v=>v-1)}>上一页</button><button disabled={busy||!jobs.pagination.hasNext} onClick={()=>setPage(v=>v+1)}>下一页</button></div>}
    {job&&<div><p role="status">{labels[job.status]} · {job.epochsCompleted}/{job.totalEpochs} 轮</p><progress aria-label="真实训练进度" value={job.epochsCompleted} max={job.totalEpochs}/><p>基线 Run：{job.baselineRunId} · 候选 Run：{job.candidateRunId}</p>{job.error&&<p role="alert">{job.error}</p>}
      <div className="evaluation-actions">{canWrite&&['queued','running'].includes(job.status)&&<button disabled={busy} onClick={()=>void action('cancel')}>取消真实训练对比</button>}{canWrite&&['failed','cancelled'].includes(job.status)&&<button disabled={busy} onClick={()=>void action('retry')}>断点重试真实训练</button>}<button disabled={!job.result} onClick={download}>导出真实训练对比</button></div>
      {job.result&&<div data-testid="real-training-comparison"><div className="evaluation-metrics"><div><span>基线准确率</span><strong>{percent(job.result.baseline.summary.accuracy)}</strong></div><div><span>候选准确率</span><strong>{percent(job.result.candidate.summary.accuracy)}</strong></div><div><span>准确率变化</span><strong>{job.result.accuracyDelta>0?'+':''}{(job.result.accuracyDelta*100).toFixed(1)} 个百分点</strong></div><div><span>修复 / 退化</span><strong>{job.result.fixed} / {job.result.regressed}</strong></div></div>
        <p>训练图片：基线 {job.result.trainingSamples.baseline} 张，候选 {job.result.trainingSamples.candidate} 张；同一测试集 {job.result.baseline.summary.total} 张。</p><p>Macro F1：{job.result.baseline.summary.macroF1.toFixed(3)} → {job.result.candidate.summary.macroF1.toFixed(3)}</p>
        <div className="evaluation-table-scroll"><table><thead><tr><th>条件</th><th>样本</th><th>基线错误</th><th>候选错误</th></tr></thead><tbody>{job.result.groups.map(v=><tr key={JSON.stringify([v.dimension,v.value])}><td>{v.dimension} = {v.value}</td><td>{v.total}</td><td>{v.baselineErrors}</td><td>{v.errors}</td></tr>)}</tbody></table></div>
        <p className="evaluation-note">变化只反映这份测试集和当前算法，不保证合成数据带来提升。系统检查已知设计版本及精确图片哈希，近重复图片和未知来源仍需人工核查；反复调参后应另留新的未参与设计测试集。</p></div>}
    </div>}
  </section>;
}
