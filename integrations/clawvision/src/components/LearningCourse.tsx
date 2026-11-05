import {useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,BookOpen,Check} from 'lucide-react';
import guides from '../../../../clawos/static/assets/learning-guides.json';
import {navigateWorkspace} from '../workspaceNavigation';
import {researchApi as api,type Journey,type Unit} from './researchJourney';
import './learning-course.css';

type Guide=typeof guides.units.question;
const guideFor=(id:string):Guide|undefined=>guides.units[id as keyof typeof guides.units];
export function LearningCourse({journey,reload,onPaper,onModel}:{journey:Journey;reload:()=>Promise<void>;onPaper:(id:string)=>void;onModel:()=>void}){
  const wanted=new URLSearchParams(location.search).get('learnUnit');
  const [active,setActive]=useState(journey.units.find(u=>u.id===wanted)?.id||journey.units.find(u=>!u.checkpoint)?.id||journey.units[0]?.id);
  const [drafts,setDrafts]=useState<Record<string,string>>({});
  const heading=useRef<HTMLHeadingElement>(null);
  const unit=journey.units.find(u=>u.id===active)||journey.units[0];if(!unit)return null;
  const guide=guideFor(unit.id),index=journey.units.indexOf(unit),saved=journey.units.filter(u=>u.checkpoint).length;
  const draftKey=(id:string)=>'clawos.course.draft.'+journey.case_hash+'.'+id;
  function choose(id:string){
    setActive(id);const url=new URL(location.href);url.searchParams.set('learnUnit',id);history.pushState({},'',url);
    requestAnimationFrame(()=>{heading.current?.focus({preventScroll:true});heading.current?.scrollIntoView({block:'start',behavior:window.matchMedia?.('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});});
  }
  function readDraft(u:Unit){if(drafts[u.id]!==undefined)return drafts[u.id];try{const value=sessionStorage.getItem(draftKey(u.id));if(value!==null)return value;}catch{/* optional browser storage */}return u.checkpoint?.explanation||'';}
  function changeDraft(id:string,text:string){setDrafts(old=>({...old,[id]:text}));try{sessionStorage.setItem(draftKey(id),text);}catch{/* in-memory draft remains */}}
  async function savedDraft(id:string){await reload();setDrafts(old=>{const next={...old};delete next[id];return next;});try{sessionStorage.removeItem(draftKey(id));}catch{/* optional storage */}}
  function action(){if(!guide)return;
    const url=new URL(location.href);url.searchParams.set('learnUnit',unit.id);history.replaceState({},'',url);
    if(guide.view==='paper')onPaper(guide.paper);
    else if(guide.view==='model')onModel();
    else navigateWorkspace(guide.view as 'visuals'|'rag-lab',{ragCase:journey.case_id,domain:'rag',learnUnit:unit.id,ragStep:guide.stage||null});
  }
  return <section className="learning-course" aria-labelledby="course-start-title">
    <header className="learning-start"><div><span className="visual-kicker">从这里开始 · RAG入门</span><h2 id="course-start-title">先理解，再观察，最后自己解释。</h2><p>这条路线带你回答一个问题：怎样让答案有资料依据？先完成当前这一步，论文和进阶工具需要时再打开。</p><p className="learning-record-count">已保存 {saved}/{journey.units.length} 份个人解释 · 保存进度不等于掌握度</p></div><button className="visual-primary" onClick={()=>choose(unit.id)}>{saved||index>0?'继续当前步骤':'从第1步开始'}<ArrowRight size={15}/></button></header>
    <div className="learning-course-layout"><nav className="learning-step-list" aria-label="RAG学习步骤"><ol>{journey.units.map((u,i)=><li key={u.id}><button aria-current={u.id===unit.id?'step':undefined} onClick={()=>choose(u.id)}><span>{String(i+1).padStart(2,'0')}</span><span><strong>{guideFor(u.id)?.title||u.title}</strong><small>{u.checkpoint?'已保存解释':`建议${u.minutes}分钟`}</small></span>{u.checkpoint&&<Check size={14} aria-label="已保存个人解释"/>}</button></li>)}</ol><p>可以回看任意一步。右侧会说明这一步的目的和怎么完成。</p></nav>
      <article className="learning-unit"><header><span className="visual-kicker">第 {index+1}/{journey.units.length} 步 · {unit.minutes}分钟建议</span><h3 ref={heading} tabIndex={-1}>{guide?.question||unit.title}</h3><p className="learning-goal"><strong>这一步学什么</strong>{guide?.goal||unit.explanation}</p></header>
        {guide&&<><section><h4>先弄懂</h4><p>{guide.meaning}</p></section><section className="learning-example"><h4>用一个例子理解</h4><p>{guide.example}</p></section><section><h4>现在做什么</h4><ol>{guide.steps.map(s=><li key={s}>{s}</li>)}</ol><button className="learning-action" onClick={action}><BookOpen size={15}/>{guide.action}<ArrowRight size={14}/></button><small className="learning-action-note">{guide.view==='paper'?'原文会在本页的文献区打开；看完可回到当前步骤。':guide.view==='model'?'这是可选练习；没有本地模型也可以继续学习。':'进入配套页面后会保留当前步骤，可从提示栏返回。'}</small></section><section><h4>做到什么算完成这一步</h4><ul>{guide.success.map(s=><li key={s}>{s}</li>)}</ul><p className="learning-misconception"><strong>容易混淆：</strong>{guide.misconception}</p></section></>}
        <LearningExplanation key={unit.id} unit={unit} journey={journey} initial={readDraft(unit)} onDraft={text=>changeDraft(unit.id,text)} onSaved={()=>savedDraft(unit.id)} next={index<journey.units.length-1?()=>choose(journey.units[index+1].id):undefined}/>
        <footer className="learning-unit-footer">{index>0&&<button onClick={()=>choose(journey.units[index-1].id)}><ArrowLeft size={14}/>回看上一步</button>}{index<journey.units.length-1?<button onClick={()=>choose(journey.units[index+1].id)}>先了解下一步<ArrowRight size={14}/></button>:<p>路线已走到最后一步。可以回看未保存的解释；教师复核和迁移练习仍需继续。</p>}</footer>
      </article></div>
  </section>;
}
function LearningExplanation({unit,journey,initial,onDraft,onSaved,next}:{unit:Unit;journey:Journey;initial:string;onDraft:(text:string)=>void;onSaved:()=>Promise<void>;next?:()=>void}){
  const [text,setText]=useState(initial),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[saved,setSaved]=useState(false);
  async function save(){setBusy(true);setMessage('正在保存个人解释…');try{await api(`/cases/${journey.case_id}/units/${unit.id}/checkpoint`,{case_hash:journey.case_hash,version:unit.checkpoint?.version||0,explanation:text});await onSaved();setSaved(true);setMessage('解释已保存。可以继续下一步，也可以按原文再修改。');}catch(e){setMessage((e as Error).message+' 当前输入已保留。');}finally{setBusy(false);}}
  return <section className="learning-explanation"><h4>用自己的话说一遍</h4><p>{guideFor(unit.id)?.reflection||unit.prompt}</p><form onSubmit={e=>{e.preventDefault();void save();}}><label>我的解释<textarea required minLength={10} maxLength={3000} disabled={busy} value={text} onChange={e=>{setText(e.target.value);onDraft(e.target.value);setSaved(false);}} placeholder="先说你的理解，再指出依据或尚不确定的地方。10字以上，不必写成论文。"/></label><div className="journey-actions"><button className="visual-primary" disabled={busy}>保存这一步的解释</button>{saved&&next&&<button type="button" onClick={next}>继续下一步<ArrowRight size={14}/></button>}</div></form><p role="status">{message}</p><small>这会保存个人学习记录，不调用模型，也不自动判定你已掌握。</small></section>;
}
