/** Render saved numerical evidence; never invent missing points or diagnostics. */
export type Direction = 'rag'|'peft'|'diffusion';
export type RagRow = {case_id:string;query:string;chunks:{id:string;title:string;text:string;score:number;current:boolean;start:number;end:number}[];response:{answer:string;abstain:boolean;citations:string[]};evaluation:{passed:boolean;failures:string[]}};
export type TeachingArm = {config:Record<string,number|boolean|string>;metric:number;metrics:Record<string,number>;curve:Record<string,number>[];evidence:{rows?:RagRow[];adapter_a?:number[][];adapter_b?:number[][];final_quantiles?:number[];target_quantiles?:number[]}};
export type TeachingRecord = {hash:string;reflection_version:number;report:{id:string;created:string;hypothesis:string;lesson:{id:string;title:string};result:{template:{id:Direction;title:string;unit:string};arms:TeachingArm[];boundary:string;execution:string;paper_reproduction_verified:boolean}}};
export type VisualState = {arm:number;kind:'rag-source';case_id:string}|{arm:number;kind:'low-rank';matrix:'a'|'b'|'update'|'total';row:number;column:number}|{arm:number;kind:'diffusion-timeline';frame:number};
export type SavedVisual = {id:string;name:string;created:string;state:VisualState;report_hash:string;report_id:string};
export const teachingBase='/api/vision/teaching';
export async function teachingRequest<T>(path:string,data?:unknown):Promise<T>{
  const response=await fetch(teachingBase+path,{credentials:'same-origin',method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
  let result;try{result=await response.json();}catch{throw Error('教学服务返回无效响应');}
  if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'教学可视化请求未完成');return result;
}
export const fmt=(value:number,digits=4)=>!Number.isFinite(value)?'—':value!==0&&(Math.abs(value)<.0001||Math.abs(value)>=1e6)?value.toExponential(Math.max(1,digits-1)):Number(value.toPrecision(digits)).toLocaleString('zh-CN',{maximumFractionDigits:6});
export function multiplyAdapters(a:number[][],b:number[][]):number[][] {
  if(!a.length||!b.length||a.length>32||b.length>32||!a[0].length||a[0].length>32||a.some(r=>r.length!==a[0].length||r.some(v=>!Number.isFinite(v)))||b.some(r=>r.length!==a.length||r.some(v=>!Number.isFinite(v))))throw Error('低秩矩阵维度或数值无效，不能绘图');
  return b.map(row=>a[0].map((_,column)=>row.reduce((sum,v,k)=>sum+v*a[k][column],0)));
}
export function adapterMatrix(arm:TeachingArm,kind:'a'|'b'|'update'|'total') {
  const a=arm.evidence.adapter_a,b=arm.evidence.adapter_b;
  if(!a||!b)throw Error('该记录未保存低秩矩阵');
  const update=multiplyAdapters(a,b);
  return kind==='a'?a:kind==='b'?b:kind==='update'?update:update.map((row,i)=>row.map((v,j)=>v+(i===j?.2:0)));
}
export function histogram(values:number[],min:number,max:number,bins=24){
  if(!Number.isFinite(min)||!Number.isFinite(max)||max<=min||bins<1||bins>100||values.some(v=>!Number.isFinite(v)))throw Error('分布数据无效');
  const counts=Array(bins).fill(0) as number[];
  for(const v of values){if(v>=min&&v<=max)counts[Math.min(bins-1,Math.floor((v-min)/(max-min)*bins))]++;}
  return counts.map((count,i)=>({x:min+(i+.5)*(max-min)/bins,count}));
}
export function defaultVisualState(record:TeachingRecord):VisualState {
  const type=record.report.result.template.id;
  return type==='rag'?{arm:1,kind:'rag-source',case_id:record.report.result.arms[1].evidence.rows?.[0]?.case_id||''}:type==='peft'?{arm:1,kind:'low-rank',matrix:'update',row:0,column:0}:{arm:1,kind:'diffusion-timeline',frame:0};
}
export function switchVisualArm(record:TeachingRecord,state:VisualState,arm:number):VisualState{
  if(arm!==0&&arm!==1)throw Error('只能选择基线或对照');
  if(state.kind==='rag-source')return {...state,arm};
  if(state.kind==='low-rank'){
    const matrix=adapterMatrix(record.report.result.arms[arm],state.matrix);
    return {...state,arm,row:Math.min(state.row,matrix.length-1),column:Math.min(state.column,matrix[0].length-1)};
  }
  const oldSteps=record.report.result.arms[state.arm].curve.length-1,newSteps=record.report.result.arms[arm].curve.length-1;
  return {...state,arm,frame:Math.min(newSteps,Math.round(state.frame/Math.max(1,oldSteps)*newSteps))};
}
export function visualReportUrl(record:TeachingRecord,view='visuals'){
  const url=new URL(location.href);url.searchParams.set('domain',record.report.result.template.id);url.searchParams.set('teachingReport',record.report.id);url.searchParams.delete('visualization');url.hash=view;return url.pathname+url.search+url.hash;
}
