import { useEffect, useState, type ReactNode } from 'react';
import type { CurrentUser } from '../api';
import { researchContext } from '../clawos';

type Runtime = {running:boolean;error?:string;source_available:boolean};
async function runtime(action='runtime'):Promise<Runtime> {
  const response=await fetch('/api/vision/'+action,{credentials:'same-origin',method:action==='runtime'?'GET':'POST',
    headers:action==='runtime'?{}:{'Content-Type':'application/json'},body:action==='runtime'?undefined:'{}'});
  const data=await response.json();if(!response.ok)throw new Error(data.detail || '实验服务暂时不可用');return data;
}
export function IntegrationSettings() {
  const [message,setMessage]=useState('实验服务由本机所有者启动。运行记录、数据集与资产使用独立实验存储。');
  const [busy,setBusy]=useState(false);
  return <section className="role-home"><span className="eyebrow">工作区设置</span><h1>实验与研究，各有依据。</h1><p>当前使用ClawOS本机所有者身份。文档协作授权不包含实验控制；多用户实验权限尚未接入。</p><p>停止服务会中断当前计算，请先保存结果。真实训练、外部Provider和专业几何依赖按各自条件配置与验收。</p><button className="stop-btn" disabled={busy} onClick={async()=>{setBusy(true);try{await runtime('stop');location.reload();}catch(e){setMessage(e instanceof Error?e.message:'服务停止失败');}finally{setBusy(false);}}}>停止实验服务</button><p role="status">{message}</p></section>;
}
export function ClawOSGate({children,inline=false}:{children:(user:CurrentUser)=>ReactNode;inline?:boolean}) {
  const [state,setState]=useState<Runtime>();const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  useEffect(()=>{runtime().then(setState).catch(e=>setError(e.message));},[]);
  if(state?.running)return <>{children({userId:'local-user',tenantId:'default',role:'owner',scopes:['*']})}</>;
  if(inline)return <section className="unified-runtime-gate"><span className="visual-kicker">本机实验服务</span><h1>继续到你的数据与模型。</h1><p>数据图表、模型资产和三维工具使用独立实验存储。启用后仍留在当前工作区，导航与课程上下文保持一致。</p><div className="runtime-capabilities"><article><strong>数据与图表</strong><p>导入、联动分析、私有图表与导出</p></article><article><strong>模型与空间</strong><p>资产版本、三维交互、评估与诊断</p></article></div><button className="visual-primary" disabled={busy||!state?.source_available} onClick={async()=>{setBusy(true);setError('');try{setState(await runtime('start'));}catch(e){setError(e instanceof Error?e.message:'启动失败');}finally{setBusy(false);}}}>{busy?'正在启用本机实验服务…':'启用本机实验服务'}</button><p className="runtime-boundary">仅本机所有者可用。不会自动加载模型权重；可视化课堂与课程手册无需启动此服务。</p><p role="status">{error||(!state?'正在检查实验服务…':'服务未运行，启用后打开当前工具。')}</p></section>;
  const context=researchContext();
  return <main className="clawos-launch"><a className="clawos-back" href="/academy">ClawOS / 研究与教学</a><section><span className="eyebrow">CLAWVISION · 实验工作区</span><h1>把想法，变成<br/>可复核的实验。</h1><p>从参数和数据开始，把运行过程、比较结果与模型资产留在同一个工作空间。</p>{context&&<aside className="research-context"><strong>来自 {context.name} 文献阅读包</strong><p>{context.question}</p><a href="/academy/research#domain-heading">返回文献与综述对照</a></aside>}<div className="launch-capabilities"><article><span>01</span><h2>实验与比较</h2><p>配置参数，记录指标与产物，对齐多次运行。</p></article><article><span>02</span><h2>数据与图表</h2><p>导入数据、筛选聚合，让分析有可回看的依据。</p></article><article><span>03</span><h2>空间与视觉</h2><p>连接3D资产、场景、合成数据和视觉评估。</p></article></div><button className="run-button" disabled={busy||!state?.source_available} onClick={async()=>{setBusy(true);setError('');try{setState(await runtime('start'));}catch(e){setError(e instanceof Error?e.message:'启动失败');}finally{setBusy(false);}}}>{busy?'正在启动独立实验服务…':'进入实验工作区'}</button><p className="launch-note">本机所有者专用。服务按需启动，使用独立存储；不会自动加载模型权重。模拟实验与真实训练分开标注。</p><p role="status">{error || (!state?'正在检查实验服务…':'实验服务未运行，点击上方按钮启动。')}</p></section></main>;
}
