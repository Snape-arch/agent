import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from '../App';
import { teachingFixture } from '../test/teachingFixtures';
import { defaultVisualState, type Direction, type SavedVisual } from '../visualizations/teachingData';

let posts:{path:string;data:Record<string,unknown>}[];
let saved:SavedVisual;
beforeEach(()=>{
  posts=[];history.replaceState({},'','/academy/vision/?domain=rag#visuals');
  saved={id:'synthetic-view',name:'测试观察视图',created:'2026-11-02T01:00:00Z',report_id:teachingFixture('rag').report.id,report_hash:'test-only-rag',state:defaultVisualState(teachingFixture('rag'))};
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
    const domain=(new URLSearchParams(location.search).get('domain')||'rag') as Direction,record=teachingFixture(domain);
    if(init?.method==='POST'){
      const data=JSON.parse(String(init.body));posts.push({path,data});
      if(path.endsWith('/visualizations'))saved={...saved,name:data.name,state:data.state,report_id:record.report.id,report_hash:data.report_hash};
      return {ok:true,json:async()=>path.endsWith('/visualizations')?saved:record};
    }
    return {ok:true,json:async()=>path.includes('/reports?')?{items:[{id:record.report.id,title:record.report.result.template.title,created:record.report.created}],page:1,has_more:false,total:1}:path.includes('/visualizations/')?{view:saved,record}:path.endsWith('/visualizations')?{items:[],has_more:false}:record};
  }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();history.replaceState({},'','/');});
describe('Source-backed visual classroom',()=>{
  it('opens real saved evidence without a worker call or an automatic experiment',async()=>{
    render(<App/>);await screen.findByRole('heading',{name:'器材借用期限是多少天？'});
    expect(screen.getByText('现行版本')).toBeInTheDocument();expect(posts).toHaveLength(0);
    fireEvent.change(screen.getByRole('combobox',{name:'观察哪一个问题'}),{target:{value:'missing'}});fireEvent.click(screen.getByRole('button',{name:'基线 · 包含旧版资料'}));expect(screen.getByRole('heading',{name:'停车价格是多少？'})).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'对照 · 仅现行资料'}));fireEvent.change(screen.getByRole('combobox',{name:'观察哪一个问题'}),{target:{value:'loan'}});
    expect(vi.mocked(fetch).mock.calls.every(([p])=>String(p).startsWith('/api/vision/teaching/'))).toBe(true);
    fireEvent.click(screen.getByRole('button',{name:'基线 · 包含旧版资料'}));expect(screen.getByText('已停用版本')).toBeInTheDocument();expect(screen.getByRole('heading',{name:'这一题仍然有问题'})).toBeInTheDocument();
  });
  it('changes topic in the same navigation shell and reads that topic’s saved matrices',async()=>{
    render(<App/>);await screen.findByRole('heading',{name:'器材借用期限是多少天？'});
    fireEvent.click(screen.getByRole('button',{name:/矩阵与适配.*少量参数/}));
    await screen.findByRole('heading',{name:'第 1 行，第 1 列'});expect(screen.getByRole('navigation',{name:'可视化教学工作区'})).toBeInTheDocument();
    expect(location.search).toContain('domain=peft');expect(screen.queryByText('已停用版本')).not.toBeInTheDocument();
  });
  it('saves the selected matrix and cell with the exact report hash then restores it',async()=>{
    history.replaceState({},'','/academy/vision/?domain=peft#visuals');render(<App/>);
    await screen.findByRole('heading',{name:'第 1 行，第 1 列'});fireEvent.click(screen.getByRole('button',{name:'W = W₀ + ΔW'}));
    fireEvent.keyDown(screen.getByRole('button',{name:/第1行第1列/}),{key:'ArrowRight'});
    fireEvent.click(screen.getByRole('button',{name:'保存当前视图'}));
    await waitFor(()=>expect(location.search).toContain('teachingVisualization=synthetic-view'));
    expect(posts[0].data).toMatchObject({report_hash:'test-only-peft',state:{kind:'low-rank',arm:1,matrix:'total',row:0,column:1}});
    await screen.findByRole('heading',{name:'第 1 行，第 2 列'});
  });
  it('does not substitute examples when source loading is denied',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,json:async()=>({detail:'实验权限不足'})})));
    render(<App/>);expect(await screen.findByRole('alert')).toHaveTextContent('实验权限不足');
    expect(screen.getByRole('heading',{name:'实验依据暂时不可读取。'})).toBeInTheDocument();expect(screen.queryByRole('img',{name:/矩阵/})).not.toBeInTheDocument();
  });
  it('requires a prediction and retains an idempotency key after a lost response',async()=>{
    const original=fetch;let failed=false;
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{if(init?.method==='POST'&&!failed){failed=true;posts.push({path,data:JSON.parse(String(init.body))});throw Error('响应丢失');}return original(path,init);}));
    render(<App/>);await screen.findByRole('heading',{name:'器材借用期限是多少天？'});fireEvent.click(screen.getByRole('button',{name:'新建机制实验'}));
    const prediction=screen.getByLabelText('实验前预测');expect(prediction).toBeRequired();fireEvent.change(prediction,{target:{value:'先写实际预测，核查旧版本来源与拒答之间的差异。'}});
    fireEvent.click(screen.getByRole('button',{name:'运行本节默认对照'}));await screen.findByRole('alert');fireEvent.click(screen.getByRole('button',{name:'运行本节默认对照'}));
    await waitFor(()=>expect(posts).toHaveLength(2));expect(posts[0].data.request_id).toBe(posts[1].data.request_id);
  });
});
