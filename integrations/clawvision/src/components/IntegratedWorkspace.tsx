import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft, ArrowUpRight, BookOpen, Box, ChartNoAxesCombined, ChevronRight, Expand, FlaskConical, Focus, Layers3, Menu, NotebookPen, ScanEye, Settings2, SlidersHorizontal, Sparkles, X } from 'lucide-react';
import { ClawOSGate, IntegrationSettings } from './ClawOSGate';
import { currentWorkspaceView, navigateWorkspace, routeEvent, workspaceRoutes, type WorkspaceView, type LegacyView } from '../workspaceNavigation';
import type { CurrentUser } from '../api';
import './integrated-workspace.css';

const TeachingWorkbench=lazy(()=>import('./TeachingWorkbench').then(m=>({default:m.TeachingWorkbench})));
const VisualLearningStudio=lazy(()=>import('./VisualLearningStudio').then(m=>({default:m.VisualLearningStudio})));
const RagResearchStudio=lazy(()=>import('./RagResearchStudio').then(m=>({default:m.RagResearchStudio})));
const ResearchJourneyStudio=lazy(()=>import('./ResearchJourneyStudio').then(m=>({default:m.ResearchJourneyStudio})));
const icons:Record<string,ReactNode>={journey:<BookOpen/>,visuals:<ScanEye/>,'rag-lab':<BookOpen/>,teaching:<NotebookPen/>,data:<ChartNoAxesCombined/>,three:<Box/>,evaluation:<Focus/>,assets:<Layers3/>,'ai-studio':<Sparkles/>,overview:<SlidersHorizontal/>,compare:<ChartNoAxesCombined/>,artifacts:<FlaskConical/>,settings:<Settings2/>};

export function IntegratedWorkspace({renderWorkspace}:{renderWorkspace:(user:CurrentUser,view:LegacyView,navigate:(view:LegacyView)=>void)=>ReactNode}) {
  const [address,setAddress]=useState(location.search+location.hash),[focused,setFocused]=useState(false),[menu,setMenu]=useState(false);
  const view:WorkspaceView=currentWorkspaceView();
  const main=useRef<HTMLElement>(null),present=useRef<HTMLButtonElement>(null);
  const route=workspaceRoutes.find(r=>r.id===view)!;
  useEffect(()=>{
    const update=()=>{setAddress(location.search+location.hash);setMenu(false);};
    addEventListener('hashchange',update);addEventListener('popstate',update);addEventListener(routeEvent,update);
    return()=>{removeEventListener('hashchange',update);removeEventListener('popstate',update);removeEventListener(routeEvent,update);};
  },[]);
  useEffect(()=>{main.current?.scrollTo?.({top:0});},[view]);
  useEffect(()=>{if(!focused)return;const exit=(event:KeyboardEvent)=>{if(event.key==='Escape'){setFocused(false);present.current?.focus();}};addEventListener('keydown',exit);return()=>removeEventListener('keydown',exit);},[focused]);
  const toolsNavigation=<>{['分析与空间','实验追踪'].map(group=><section key={group}><h2>{group}</h2>{workspaceRoutes.filter(r=>r.group===group).map(r=><button key={r.id} data-testid={'unified-nav-'+r.id} aria-current={view===r.id?'page':undefined} onClick={()=>navigateWorkspace(r.id)}>{icons[r.id]}<span>{r.title}</span>{view===r.id&&<ChevronRight size={13}/>}</button>)}</section>)}</>;
  const navigate=(next:LegacyView)=>navigateWorkspace(next==='home'?'visuals':next);
  return <div className={`unified-workspace ${focused?'presentation-mode':''}`} data-testid="integrated-workspace">
    <a className="skip-link" href="#vision-content" onClick={e=>{e.preventDefault();main.current?.focus();}}>跳到主要内容</a>
    <aside className={`unified-sidebar ${menu?'menu-open':''}`}>
      <a className="unified-brand" href="/academy"><span className="unified-brand-symbol"><BookOpen size={21}/></span><span><strong>ClawOS</strong><small>学习 · 研究 · 创造</small></span></a>
      <a className="unified-back" href="/academy/lab"><ArrowLeft size={14}/>返回学习与教材</a>
      <nav id="unified-navigation" aria-label="可视化教学工作区">
        {['学习与探索'].map(group=><section key={group}><h2>{group}</h2>{workspaceRoutes.filter(r=>r.group===group).map(r=><button key={r.id} data-testid={'unified-nav-'+r.id} aria-current={view===r.id?'page':undefined} onClick={()=>navigateWorkspace(r.id)}>{icons[r.id]}<span>{r.title}</span>{view===r.id&&<ChevronRight size={13}/>}</button>)}</section>)}
        <details className="unified-navigation-more" key={route.group} open={route.group!=='学习与探索'}><summary>更多分析与实验工具</summary>{toolsNavigation}</details>
      </nav>
      <div className="unified-sidebar-footer"><a href="/academy/research"><BookOpen size={15}/>文献与综述<ArrowUpRight size={13}/></a><a href="/academy/notes"><NotebookPen size={15}/>学习笔记<ArrowUpRight size={13}/></a><p>ClawVision 可视化能力<br/>已整合至学习工作区</p></div>
    </aside>
    <div className="unified-main"><header className="unified-topbar"><button className="unified-menu" aria-label={menu?'收起导航':'展开导航'} aria-expanded={menu} aria-controls="unified-navigation" onClick={()=>setMenu(v=>!v)}>{menu?<X size={20}/>:<Menu size={20}/>}</button><div className="unified-breadcrumb"><span>学习空间</span><ChevronRight size={13}/><strong>{route.title}</strong></div><button ref={present} className="unified-present" aria-pressed={focused} onClick={()=>setFocused(v=>!v)}><Expand size={15}/>专注演示</button></header>
      {focused&&<button className="unified-exit-presentation" onClick={()=>{setFocused(false);present.current?.focus();}}><X size={16}/>退出专注演示 <kbd>Esc</kbd></button>}
      <main ref={main} id="vision-content" tabIndex={-1} className={'unified-content route-'+view}>
        <Suspense fallback={<div className="unified-loading" role="status">正在打开{route.title}…</div>}>
          {view==='visuals'?<VisualLearningStudio key={address.split('#')[0]}/>:view==='rag-lab'?<RagResearchStudio key={address.split('#')[0]}/>:view==='journey'?<ResearchJourneyStudio key={address.split('#')[0]}/>:view==='teaching'?<TeachingWorkbench key={address.split('#')[0]}/>:view==='settings'?<IntegrationSettings/>:<ClawOSGate inline>{user=>renderWorkspace(user,view,navigate)}</ClawOSGate>}
        </Suspense>
      </main>
    </div>
  </div>;
}
