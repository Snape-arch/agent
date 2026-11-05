import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {ResearchJourneyStudio} from './ResearchJourneyStudio';
import type {Journey,ModelJob} from './researchJourney';
import axe from 'axe-core';

// Synthetic protocol data: neither captured literature nor a real model acceptance.
const baseJourney:Journey={case_id:'case-old',case_hash:'synthetic-hash',overview_id:'overview-fixture',subscription_id:'subscription-fixture',boundary:'Synthetic',
  links:{overview:'/academy/research?report=overview-fixture',course:'/academy/lab?lesson=rag&researchCase=case-old',practice:'/academy/vision/?ragCase=case-old#rag-lab',mechanism:'/academy/vision/?ragCase=case-old#visuals',review:'/academy/research',agent:'/console#reflection'},
  papers:[{id:'dpr',name:'Synthetic DPR',title:'Synthetic paper for protocol tests',version:'2004.04906v3',date:'2020-04-10',category:'检索',abstract:'Synthetic author abstract',raw_sha256:'synthetic-pdf-hash',page_count:1,pdf_url:'/api/vision/research/cases/case-old/papers/dpr/pdf',note:{version:0,status:'unread',folder:'',tags:[],note:''},import_record:{}}],
  units:[{id:'evidence',title:'版本与原文定位',lesson:'rag',minutes:10,papers:['dpr'],explanation:'Synthetic explanation only.',prompt:'你怎样核对版本与证据？',view:'rag-lab'}]};
const question={id:'fact-dpr',label:'Synthetic factual question',query:'retrieval',kind:'fact' as const};
const modelJob:ModelJob={id:'job-synthetic',case_id:'case-old',created:1,status:'completed',hash:'synthetic-job-hash',result:{question,top_k:3,calls:[{arm:'full_text',provider:'fixture',model:'synthetic-model',duration_ms:1,usage:{total_tokens:42}}],arms:[{scope:'abstract',context_characters:0,references:[],answer:{outcome:'insufficient',reason:'Synthetic empty evidence scope',claims:[],withheld:[]}},{scope:'full_text',context_characters:80,references:[],answer:{outcome:'withheld',reason:'Synthetic contract fault',claims:[],withheld:[{id:'C1',text:'Synthetic withheld claim',reason:'unknown_citation'}]}}]}};
let journey:Journey,ready:boolean,jobs:ModelJob[],posts:{path:string;data:Record<string,unknown>}[],lost:boolean,failGet:boolean;
beforeEach(()=>{
  journey=structuredClone(baseJourney);ready=false;jobs=[];posts=[];lost=false;failGet=false;sessionStorage.clear();history.replaceState({},'','/academy/vision/?ragCase=case-old#journey');
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:RequestInit)=>{
    if(init?.method==='POST'){
      const data=JSON.parse(String(init.body));posts.push({path,data});
      if(path.endsWith('/note')){journey.papers[0].note={...journey.papers[0].note,...data,version:1} as Journey['papers'][0]['note'];}
      if(path.endsWith('/checkpoint'))journey.units[0].checkpoint={version:1,explanation:String(data.explanation)};
      if(path.endsWith('/import'))journey.papers[0].import_record={status:'completed',reader_url:'/academy/paper?document_id=7',material_url:'/academy/materials?material=material-fixture&step=guide',teacher_url:'/academy/materials?material=material-fixture&step=seminar'};
      if(path.endsWith('/answers')&&lost){lost=false;throw Error('Synthetic response lost');}
      return {ok:true,json:async()=>path.endsWith('/answers')?modelJob:path.endsWith('/reflection')?{card_id:'research-synthetic-card'}:path.endsWith('/checkpoint')?journey.units[0].checkpoint:path.endsWith('/note')?journey.papers[0].note:journey.papers[0].import_record};
    }
    if(path.endsWith('/journey')&&failGet)return {ok:false,json:async()=>({detail:'Synthetic source unavailable'})};
    return {ok:true,json:async()=>path.includes('/pdf-page/')?{page:1,pages:1,width:600,height:800,image:'data:image/png;base64,synthetic-fixture',text:[{text:'Synthetic PDF page text.'}],case_hash:'synthetic-hash',raw_sha256:'synthetic-pdf-hash'}:path.endsWith('/catalog')?{cases:[{id:'case-new',created:2},{id:'case-old',created:1}]}:path.endsWith('/journey')?structuredClone(journey):path.endsWith('/answer-bank')?{questions:[question]}:path.endsWith('/answer-status')?{ready,reason:ready?'Synthetic configured fixture; not real-model verification.':'Synthetic local model offline'}:path.endsWith('/answers')?{items:jobs}:modelJob};
  }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();history.replaceState({},'','/');});

describe('One paper/teaching/evolution journey',()=>{
  it('restores the selected plan, keeps visual/course/source links and never auto starts work',async()=>{
    render(<ResearchJourneyStudio/>);await screen.findByText('Synthetic DPR');expect(screen.getByLabelText('当前研究学习计划')).toHaveValue('case-old');
    await screen.findByText('Synthetic local model offline');expect(posts).toHaveLength(0);expect(screen.getByRole('button',{name:'运行本地模型对照'})).toBeDisabled();
    expect(screen.getByRole('link',{name:'继续教材与教师学习链路'})).toHaveAttribute('href',journey.links.course);expect(screen.getByRole('link',{name:'打开原Agent工作台'})).toHaveAttribute('href','/console#reflection');
    fireEvent.click(screen.getByText('版本与原文定位'));fireEvent.click(screen.getByRole('button',{name:'打开配套实验'}));expect(location.search).toContain('ragCase=case-old');expect(location.hash).toBe('#rag-lab');
  });
  it('persists private reading notes and imports into existing reader/material/calibration',async()=>{
    render(<ResearchJourneyStudio/>);await screen.findByText('Synthetic DPR');fireEvent.click(screen.getByText('整理这篇论文 · 待阅读'));
    fireEvent.change(screen.getByLabelText('资料夹'),{target:{value:'检索学习'}});fireEvent.change(screen.getByLabelText('阅读笔记'),{target:{value:'Synthetic source-grounded personal note.'}});fireEvent.click(screen.getByRole('button',{name:'保存整理'}));
    await waitFor(()=>expect(journey.papers[0].note.version).toBe(1));await screen.findByDisplayValue('检索学习');expect(posts[0].data.case_hash).toBe('synthetic-hash');
    fireEvent.click(screen.getByRole('button',{name:'导入论文库与教材学习'}));const reader=await screen.findByRole('link',{name:'论文导读与笔记'});expect(reader).toHaveAttribute('href','/academy/paper?document_id=7&researchCase=case-old');expect(screen.getByRole('link',{name:'教师校准'})).toHaveAttribute('href',expect.stringContaining('step=seminar&researchCase=case-old'));
    expect(posts.filter(p=>p.path.endsWith('/import'))).toHaveLength(1);expect(posts.at(-1)?.data.confirmed).toBe(true);
  });
  it('reads a captured PDF in the full content pane and filters without a model',async()=>{
    render(<ResearchJourneyStudio/>);await screen.findByText('Synthetic DPR');fireEvent.click(screen.getByRole('button',{name:'展开原文'}));expect(await screen.findByRole('img',{name:'Synthetic DPR PDF原文第1页，共1页'})).toHaveAttribute('src','data:image/png;base64,synthetic-fixture');
    expect(screen.getByRole('link',{name:'固定版本PDF'})).toHaveAttribute('href',journey.papers[0].pdf_url+'?download=true');fireEvent.change(screen.getByRole('searchbox'),{target:{value:'absent'}});expect(screen.getByText('没有匹配的论文，请调整筛选。')).toBeInTheDocument();expect(posts).toHaveLength(0);
  });
  it('saves self explanation without grading or publishing any agent policy',async()=>{
    render(<ResearchJourneyStudio/>);await screen.findByText('Synthetic DPR');fireEvent.click(screen.getByText('版本与原文定位'));fireEvent.change(screen.getByRole('textbox',{name:'你怎样核对版本与证据？'}),{target:{value:'这是本人解释，定位证据并不能直接证明语义成立。'}});fireEvent.click(screen.getByRole('button',{name:'保存我的解释'}));
    await screen.findByText('已保存解释');expect(posts).toHaveLength(1);expect(posts[0].path).toContain('/units/evidence/checkpoint');expect(posts[0].data.version).toBe(0);
  });
  it('reuses an uncertain submission ID and maps model receipts to the actual called arm',async()=>{
    ready=true;lost=true;render(<ResearchJourneyStudio/>);await screen.findByText('Synthetic configured fixture; not real-model verification.');
    fireEvent.click(screen.getByRole('button',{name:'运行本地模型对照'}));await screen.findByText('Synthetic response lost');fireEvent.click(screen.getByRole('button',{name:'恢复上次提交'}));await screen.findByText('Synthetic withheld claim',{exact:false});
    const submissions=posts.filter(p=>p.path.endsWith('/answers'));expect(submissions).toHaveLength(2);expect(submissions[0].data).toEqual(submissions[1].data);
    const abstract=screen.getByRole('heading',{name:'作者摘要'}).closest('section')!;expect(within(abstract).getByText('未调用模型',{exact:false})).toBeInTheDocument();
    const full=screen.getByRole('heading',{name:'捕获全文'}).closest('section')!;expect(within(full).getByText('synthetic-model',{exact:false})).toHaveTextContent('42');
    fireEvent.click(screen.getByRole('button',{name:'提交契约失败供Agent审查'}));await screen.findByText('已提交到原Agent Reflection：',{exact:false});expect(posts.at(-1)?.path).toContain('/reflection');
  });
  it('shows inaccessible source errors without synthetic lessons and passes DOM accessibility checks',async()=>{
    failGet=true;const first=render(<ResearchJourneyStudio/>);await screen.findByRole('alert');expect(screen.queryByText('Synthetic DPR')).not.toBeInTheDocument();expect(posts).toHaveLength(0);first.unmount();
    failGet=false;const view=render(<main><ResearchJourneyStudio/></main>);await screen.findByText('Synthetic DPR');await screen.findByText('Synthetic local model offline');
    const result=await axe.run(view.container,{rules:{'color-contrast':{enabled:false},'region':{enabled:false}}});expect(result.violations.map(v=>v.id)).toEqual([]);
  });
});
