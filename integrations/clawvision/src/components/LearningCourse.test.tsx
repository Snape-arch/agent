import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {LearningCourse} from './LearningCourse';
import {LearningContext} from './LearningContext';
import guides from '../../../../clawos/static/assets/learning-guides.json';
import type {Journey} from './researchJourney';

// Synthetic UI/contract data; these tests do not measure teaching effectiveness.
const journey={case_id:'synthetic-plan',case_hash:'synthetic-source',papers:[],units:Object.entries(guides.units).map(([id,g])=>({id,title:g.title,prompt:'Synthetic old prompt',explanation:'Synthetic',minutes:5,papers:[],lesson:'rag',view:'journey'}))} as unknown as Journey;
let payload:Record<string,unknown>[],failed:boolean;
beforeEach(()=>{history.replaceState({},'','/academy/vision/?ragCase=synthetic-plan#journey');sessionStorage.clear();payload=[];failed=false;vi.stubGlobal('fetch',vi.fn(async(_path:string,init:RequestInit)=>{payload.push(JSON.parse(String(init.body)));return {ok:!failed,json:async()=>failed?{detail:'Synthetic version conflict'}:{version:1}};}));});
afterEach(()=>{cleanup();vi.unstubAllGlobals();history.replaceState({},'','/');});
const mount=()=>render(<LearningCourse journey={structuredClone(journey)} reload={vi.fn(async()=>{})} onPaper={vi.fn()} onModel={vi.fn()}/>);
describe('Beginner learning route',()=>{
  it('opens optional save help without submitting or losing the current draft',()=>{
    mount();const draft='A retained learner draft while consulting optional save information.';
    fireEvent.change(screen.getByLabelText('我的解释'),{target:{value:draft}});
    fireEvent.click(screen.getByRole('button',{name:'保存说明'}));
    expect(fetch).not.toHaveBeenCalled();expect(screen.getByLabelText('我的解释')).toHaveValue(draft);
  });
  it('explains before asking and starts without model calls or automatic completion',()=>{
    mount();expect(screen.getByRole('heading',{name:'RAG到底在帮我们做什么？'})).toBeInTheDocument();expect(screen.getByText(guides.units.question.meaning)).toBeVisible();expect(screen.getByText(guides.units.question.reflection)).toBeVisible();expect(screen.getByRole('button',{name:'从第1步开始'})).toBeEnabled();expect(fetch).not.toHaveBeenCalled();
  });
  it('restores the exact step, preserves its draft across steps and browser-style remounts',()=>{
    history.replaceState({},'','/academy/vision/?ragCase=synthetic-plan&learnUnit=compare#journey');const view=mount();
    const draft='Synthetic unfinished comparison; keep the same query and candidate limit.';
    expect(screen.getByRole('heading',{name:guides.units.compare.question})).toBeInTheDocument();fireEvent.change(screen.getByLabelText('我的解释'),{target:{value:draft}});
    fireEvent.click(screen.getByRole('button',{name:/01 先理解RAG/}));expect(screen.getByLabelText('我的解释')).toHaveValue('');fireEvent.click(screen.getByRole('button',{name:/04 做一次范围对照/}));expect(screen.getByLabelText('我的解释')).toHaveValue(draft);view.unmount();mount();expect(screen.getByLabelText('我的解释')).toHaveValue(draft);expect(location.search).toContain('ragCase=synthetic-plan');expect(payload).toHaveLength(0);
  });
  it('keeps failed input and saves with the original source and version before offering continuation',async()=>{
    failed=true;mount();const draft='Synthetic explanation: retrieve supporting text before composing an answer.';
    fireEvent.change(screen.getByLabelText('我的解释'),{target:{value:draft}});fireEvent.click(screen.getByRole('button',{name:'保存这一步的解释'}));await screen.findByText(/Synthetic version conflict/);expect(screen.getByLabelText('我的解释')).toHaveValue(draft);expect(screen.queryByRole('button',{name:'继续下一步'})).not.toBeInTheDocument();expect(payload[0]).toEqual({case_hash:'synthetic-source',version:0,explanation:draft});
    failed=false;fireEvent.click(screen.getByRole('button',{name:'保存这一步的解释'}));await screen.findByText(/解释已保存。/);fireEvent.click(screen.getByRole('button',{name:'继续下一步'}));await waitFor(()=>expect(screen.getByRole('heading',{name:guides.units.representation.question})).toBeInTheDocument());expect(payload).toHaveLength(2);
  });
  it('takes a purposeful action and returns to the same step and plan',()=>{
    mount();fireEvent.click(screen.getByRole('button',{name:'看一次来源过滤的可视化'}));expect(location.hash).toBe('#visuals');expect(new URLSearchParams(location.search).get('learnUnit')).toBe('question');cleanup();render(<LearningContext mode="mechanism"/>);expect(screen.getByRole('link',{name:'看完结果，回第1步写解释'})).toHaveAttribute('href','/academy/vision/?ragCase=synthetic-plan&learnUnit=question#journey');expect(screen.getByText(/合成教学资料做CPU机制演示/)).toBeVisible();expect(payload).toHaveLength(0);
  });
  it('does not interpret invalid or inherited query keys as learning units',()=>{
    history.replaceState({},'','/academy/vision/?ragCase=synthetic-plan&learnUnit=constructor#visuals');render(<LearningContext mode="papers"/>);expect(screen.queryByLabelText('当前学习任务')).not.toBeInTheDocument();cleanup();mount();expect(screen.getByRole('heading',{name:guides.units.question.question})).toBeInTheDocument();
  });
});
