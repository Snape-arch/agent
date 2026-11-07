import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from '../App';

// Synthetic protocol fixtures. These do not assert scholarly retrieval quality.
const question={id:'dpr',label:'Synthetic DPR similarity question',query:'dot product'};
const transfer=[{id:'new-scenario',question:'Synthetic independent transfer scenario'}];
const course={case:{id:'older-case',overview_id:'overview',subscription_id:'sub',prerequisites:['问题表示','来源核查'],boundary:'Synthetic',papers:[{id:'dpr',name:'Synthetic DPR',title:'Synthetic paper',version:'2004.04906v3',url:'https://arxiv.org/pdf/2004.04906v3',page_count:1,raw_sha256:'synthetic-pdf',abstract:'Synthetic author abstract'}],teaching_graph:{nodes:[{id:'representation',title:'检索表示',papers:['dpr'],explanation:'Synthetic concept'}],edges:[]}},hash:'case-hash',runs:[{id:'synthetic-run',hash:'run-hash',created:1}],runs_has_more:false,transfer_questions:transfer,overview_preview:{coverage:{papers:1,full_text_bound:1},groups:[],boundary:'Synthetic'}};
const hit={paper_id:'dpr',paper_name:'Synthetic DPR',page:1,start:0,end:21,text:'Synthetic dot product',score:1,rank:1,field:'full_text',anchor_overlap:true,source_url:'https://arxiv.org/pdf/2004.04906v3',raw_sha256:'synthetic-pdf',text_sha256:'synthetic-text'};
const run={run:{id:'synthetic-run',case_id:'older-case',case_hash:'case-hash',hypothesis:'Synthetic hypothesis',result:{questions:[question],arms:[0,1].map(i=>({scope:i?'full_text':'abstract',top_k:3,anchor_hits:i,passages:1,returned_characters:21,indexed_characters:21,rows:[{question_id:'dpr',hits:[{...hit,field:i?'full_text':'abstract'}],anchor_hit:!!i}]})),boundary:'Synthetic phrase coverage is not accuracy.'}},hash:'run-hash',version:0,transfer_questions:transfer,attempts:[]};
let posts:{path:string;data:Record<string,unknown>}[];
let currentRun:typeof run;
beforeEach(()=>{
  posts=[];currentRun=structuredClone(run);history.replaceState({},'','/academy/vision/?ragRun=synthetic-run#rag-lab');
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
    if(init?.method==='POST'){
      const data=JSON.parse(String(init.body));posts.push({path,data});
      return {ok:true,json:async()=>path.endsWith('/prepare')?course:path.endsWith('/views')?{id:'saved-view',run_id:'synthetic-run',run_hash:'run-hash',state:data.state}:currentRun};
    }
    return {ok:true,json:async()=>path.endsWith('/catalog')?{cases:[{id:'newer-case',hash:'newer-hash',created:2}],boundary:'Synthetic'}:path.includes('/views/')?{id:'saved-view',run_id:'synthetic-run',run_hash:'run-hash',state:{arm:0,question_id:'dpr'}}:path.includes('/runs/')?currentRun:course};
  }));
});
afterEach(()=>{vi.unstubAllGlobals();history.replaceState({},'','/');});

describe('RAG real-literature workflow contracts',()=>{
  it('opens an older run independent of the latest catalog without starting workers or models',async()=>{
    render(<App/>);await screen.findByRole('heading',{name:question.label});
    expect(screen.getByRole('button',{name:/完整文本.*1\/10/})).toHaveAttribute('aria-pressed','true');
    fireEvent.click(screen.getByRole('button',{name:/作者摘要.*0\/10/}));
    expect(screen.getByRole('heading',{name:question.label})).toBeInTheDocument();
    expect(screen.getByLabelText('实验前预测')).toHaveValue('Synthetic hypothesis');expect(screen.getByRole('combobox',{name:/每题返回候选数/})).toHaveValue('3');expect(posts).toHaveLength(0);expect(vi.mocked(fetch).mock.calls.every(([p])=>String(p).startsWith('/api/vision/research/'))).toBe(true);
  });
  it('restores a private saved observation and does not load the latest case as a substitute',async()=>{
    history.replaceState({},'','/academy/vision/?ragView=saved-view#rag-lab');render(<App/>);
    await screen.findByRole('heading',{name:question.label});
    expect(screen.getByRole('button',{name:/作者摘要.*0\/10/})).toHaveAttribute('aria-pressed','true');
    expect(vi.mocked(fetch).mock.calls.some(([p])=>String(p).endsWith('/cases/newer-case'))).toBe(false);
  });
  it('refuses a mismatched source hash without displaying retrieval candidates',async()=>{
    currentRun.run.case_hash='wrong-source';render(<App/>);
    expect(await screen.findByRole('alert')).toHaveTextContent('来源摘要不一致');
    expect(screen.queryByRole('img',{name:'当前范围的BM25候选排序'})).not.toBeInTheDocument();
  });
  it('keeps the run request identity after a lost response',async()=>{
    const original=fetch;let failed=false;
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
      if(init?.method==='POST'&&path.endsWith('/runs')&&!failed){failed=true;posts.push({path,data:JSON.parse(String(init.body))});throw Error('Synthetic response lost');}
      return original(path,init);
    }));
    render(<App/>);await screen.findByRole('heading',{name:question.label});
    fireEvent.change(screen.getByLabelText('实验前预测'),{target:{value:'Synthetic prediction to compare the same source scopes.'}});
    fireEvent.click(screen.getByRole('button',{name:'运行范围对照'}));await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button',{name:'运行范围对照'}));
    await waitFor(()=>expect(posts).toHaveLength(2));expect(posts[0].data.request_id).toBe(posts[1].data.request_id);
  });
  it('preserves transfer inputs when another tab has advanced the version',async()=>{
    const original=fetch;
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>path.endsWith('/attempts')?{ok:false,status:409,json:async()=>({detail:'练习版本已变化，旧回答保留'})}:original(path,init)));
    render(<App/>);await screen.findByRole('heading',{name:question.label});
    const answer='Synthetic independent response, not a learning outcome.';
    fireEvent.change(screen.getByLabelText(/Synthetic independent transfer/),{target:{value:answer}});
    fireEvent.change(screen.getByLabelText(/学习反思：/),{target:{value:'Synthetic uncertainty reflection, not a teacher review.'}});
    fireEvent.click(screen.getByRole('button',{name:'追加保存回答与反思'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('练习版本已变化');
    expect(screen.getByLabelText(/Synthetic independent transfer/)).toHaveValue(answer);
  });

  it('discards an old source-page response after the searchable scope changes',async()=>{
    const original=fetch;let complete=()=>{};
    const delayed=new Promise(resolve=>{complete=()=>resolve({ok:true,json:async()=>({case_hash:'case-hash',paper_id:'dpr',page:1,pages:1,text:'Synthetic delayed page',source_url:hit.source_url,boundary:'Synthetic'})});});
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>path.includes('/pages/')?delayed:original(path,init)));
    render(<App/>);await screen.findByRole('heading',{name:question.label});
    fireEvent.click(screen.getAllByRole('button',{name:'定位PDF提取页'})[0]);
    fireEvent.click(screen.getByRole('button',{name:/作者摘要.*0\/10/}));
    await act(async()=>{complete();});expect(screen.queryByRole('region',{name:'PDF原文定位'})).not.toBeInTheDocument();
  });
  it('retries preparation with the same request after a lost response',async()=>{
    history.replaceState({},'','/academy/vision/#rag-lab');const original=fetch;let failed=false;
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
      if(path.endsWith('/catalog'))return {ok:true,json:async()=>({cases:[],boundary:'Synthetic'})};
      if(path.endsWith('/prepare')&&!failed){failed=true;posts.push({path,data:JSON.parse(String(init?.body))});throw Error('Synthetic preparation response lost');}
      return original(path,init);
    }));
    render(<App/>);await screen.findByRole('button',{name:'准备公开资料与实践课'});
    fireEvent.click(screen.getByRole('button',{name:'准备公开资料与实践课'}));await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button',{name:'准备公开资料与实践课'}));
    await waitFor(()=>expect(posts).toHaveLength(2));expect(posts[0].data.request_id).toBe(posts[1].data.request_id);
  });

  it('loads all crossed PDF pages and verifies the exact quoted interval',async()=>{
    for(const arm of currentRun.run.result.arms)arm.rows[0].hits[0]={...arm.rows[0].hits[0],text:'Synthetic\n\ndot product',end:22};
    const original=fetch;
    vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
      if(path.includes('/pages/')){
        const second=path.endsWith('/2');return {ok:true,json:async()=>({case_hash:'case-hash',raw_sha256:'synthetic-pdf',text_sha256:'synthetic-text',paper_id:'dpr',page:second?2:1,pages:2,start:second?11:0,end:second?22:9,text:second?'dot product':'Synthetic',source_url:hit.source_url,boundary:'Synthetic'})};
      }return original(path,init);
    }));
    render(<App/>);await screen.findByRole('heading',{name:question.label});
    fireEvent.click(screen.getAllByRole('button',{name:'定位PDF提取页'})[0]);
    expect(await screen.findByRole('heading',{name:'原文提取 · 第1–2/2页'})).toBeInTheDocument();
    expect(screen.getByRole('region',{name:'PDF原文定位'})).toHaveTextContent('Synthetic dot product');
    expect(screen.getByRole('region',{name:'PDF原文定位'}).querySelector('mark')).toHaveTextContent('Synthetic dot product');
  });
  it('reports owner denial without example content',async()=>{
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:403,json:async()=>({detail:'仅本机所有者可操作'})})));
    render(<App/>);expect(await screen.findByRole('alert')).toHaveTextContent('仅本机所有者');
    expect(screen.queryByRole('heading',{name:question.label})).not.toBeInTheDocument();
  });
});
