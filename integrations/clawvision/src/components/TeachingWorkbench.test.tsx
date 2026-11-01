import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TeachingWorkbench } from './TeachingWorkbench';
import { App } from '../App';

const template={id:'rag',lesson:'rag',title:'来源过滤实验',variable:'current_only',baseline:false,choices:[true],unit:'通过题数 / 6',hypothesis:'先写预测',method:'固定语料的真实字符检索。',boundary:'合成教学资料，不是论文复现。',lesson_snapshot:{title:'有证据的 RAG',prerequisites:['embedding']}};
const record={hash:'synthetic-report-hash',reflection_version:0,reflections:[],report:{id:'a'.repeat(32),created:'2026-11-01T02:00:00Z',hypothesis:'过滤过期来源应改善某些问题。',lesson:{id:'rag',title:'有证据的 RAG'},result:{template,delta:1,boundary:'合成样本不证明泛化。',arms:[{config:{current_only:false},metric:4,metrics:{passed:4,total:6},curve:[],evidence:{rows:[]}},{config:{current_only:true},metric:5,metrics:{passed:5,total:6},curve:[],evidence:{rows:[]}}]}}};
let posts:{path:string;data:Record<string,unknown>}[];
beforeEach(()=>{
  posts=[];history.replaceState({},'','/academy/vision/?domain=rag#teaching');
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
    if(init?.method==='POST')posts.push({path,data:JSON.parse(String(init.body))});
    const value=path.endsWith('/catalog')?{templates:[template]}:path.endsWith('/books')?[]:path.includes('/reports?page=')?{items:[],page:1,total:0,has_more:false}:record;
    return {ok:true,json:async()=>structuredClone(value)};
  }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();history.replaceState({},'','/');});

describe('Teaching evidence workbench',()=>{
  it('opens the course shell without starting or querying an experiment worker',async()=>{
    render(<App/>);await screen.findByText('固定语料的真实字符检索。');
    const paths=vi.mocked(fetch).mock.calls.map(([p])=>String(p));
    expect(paths.every(p=>p.startsWith('/api/vision/teaching/'))).toBe(true);
    expect(screen.getByText(/不需要启动模型或实验子服务/)).toBeInTheDocument();
  });
  it('moves keyboard focus to the notebook without navigating out of it',async()=>{
    render(<App/>);await screen.findByText('固定语料的真实字符检索。');
    fireEvent.click(screen.getByRole('link',{name:'跳到课程实验'}));
    expect(document.activeElement).toHaveAttribute('id','teaching-content');expect(location.hash).toBe('#teaching');
  });
  it('discloses mechanism limits and requires a pre-run prediction',async()=>{
    render(<TeachingWorkbench/>);expect(await screen.findByText('固定语料的真实字符检索。')).toBeInTheDocument();
    expect(screen.getByLabelText('实验前预测')).toBeRequired();expect(screen.getByText('合成教学资料，不是论文复现。')).toBeInTheDocument();
    expect(posts).toHaveLength(0);
  });
  it('submits one bounded intervention then renders persisted metrics and export',async()=>{
    render(<TeachingWorkbench/>);await screen.findByText('固定语料的真实字符检索。');
    fireEvent.change(screen.getByLabelText('实验前预测'),{target:{value:'过滤过期来源应改善某些问题。'}});
    fireEvent.click(screen.getByRole('button',{name:'运行基线与对照'}));
    await screen.findByText('把结果变成你的理解');expect(posts).toHaveLength(1);
    expect(posts[0].data).toMatchObject({template:'rag',value:true,seed:42,binding:null});expect(posts[0].data.request_id).toBeTruthy();
    expect(screen.getByRole('link',{name:'完整依据 JSON'})).toHaveAttribute('href','/api/vision/teaching/reports/'+record.report.id+'/export');
    expect(screen.getByText(/保存反思不会提高掌握分/)).toBeInTheDocument();
  });
  it('reloads the selected immutable report from the URL',async()=>{
    history.replaceState({},'','/academy/vision/?teachingReport='+record.report.id+'#teaching');render(<TeachingWorkbench/>);
    await screen.findByText('把结果变成你的理解');expect(screen.getByText(record.report.hypothesis)).toBeInTheDocument();expect(posts).toHaveLength(0);
  });
  it('retains the same request key when the response is lost',async()=>{
    const original=fetch;let failed=false;
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
      if(init?.method==='POST'&&!failed){failed=true;posts.push({path,data:JSON.parse(String(init.body))});throw Error('连接中断');}
      return original(path,init);
    }));
    render(<TeachingWorkbench/>);await screen.findByText('固定语料的真实字符检索。');
    fireEvent.change(screen.getByLabelText('实验前预测'),{target:{value:'过滤过期来源应改善某些问题。'}});
    fireEvent.click(screen.getByRole('button',{name:'运行基线与对照'}));await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button',{name:'运行基线与对照'}));await screen.findByText('把结果变成你的理解');
    expect(posts).toHaveLength(2);expect(posts[1].data.request_id).toBe(posts[0].data.request_id);
  });
  it('preserves reflection text on a conflict and exposes the error',async()=>{
    history.replaceState({},'','/academy/vision/?teachingReport='+record.report.id+'#teaching');const original=fetch;
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>path.endsWith('/reflections')?{ok:false,json:async()=>({detail:'报告或反思版本冲突，请重新打开记录'})}:original(path,init)));
    render(<TeachingWorkbench/>);await screen.findByText('把结果变成你的理解');
    for(const label of ['观察到了什么','为什么会这样','还不能得出什么结论'])fireEvent.change(screen.getByLabelText(label),{target:{value:'这是保留的学习解释，至少十个字。'}});
    fireEvent.click(screen.getByRole('button',{name:'保存学习反思'}));await screen.findByRole('alert');
    expect(screen.getByLabelText('观察到了什么')).toHaveValue('这是保留的学习解释，至少十个字。');
    await waitFor(()=>expect(screen.getByRole('button',{name:'保存学习反思'})).not.toBeDisabled());
  });
});
