import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { teachingFixture } from '../test/teachingFixtures';
import { adapterMatrix, defaultVisualState, fmt, histogram, multiplyAdapters, switchVisualArm, type Direction, type VisualState } from './teachingData';
import { DiffusionVisual, LowRankVisual, RagVisual } from './TeachingVisuals';

afterEach(cleanup);
function Harness({topic}:{topic:Direction}){
  const record=teachingFixture(topic),[state,setState]=useState<VisualState>(defaultVisualState(record));
  return state.kind==='rag-source'?<RagVisual record={record} state={state} onChange={setState}/>:state.kind==='low-rank'?<LowRankVisual record={record} state={state} onChange={setState}/>:<DiffusionVisual record={record} state={state} onChange={setState}/>;
}
describe('Actual evidence transforms',()=>{
  it('reconstructs B×A with an independently known matrix product',()=>{
    expect(multiplyAdapters([[1,2,3],[4,5,6]],[[2,-1],[0,3]])).toEqual([[-2,-1,0],[12,15,18]]);
    const arm=teachingFixture('peft').report.result.arms[1];expect(adapterMatrix(arm,'total')[0][0]).toBeCloseTo(2.2);
  });
  it('rejects missing dimensions and nonfinite data instead of drawing defaults',()=>{
    expect(fmt(-4.8e-7)).toBe('-4.800e-7');expect(()=>multiplyAdapters([],[[1]])).toThrow();expect(()=>multiplyAdapters([[1,2]],[[1,2]])).toThrow();expect(()=>multiplyAdapters([[NaN]],[[1]])).toThrow();
  });
  it('preserves the same question, matrix element and normalized sampling progress across arms',()=>{
    expect(switchVisualArm(teachingFixture('rag'),{kind:'rag-source',arm:1,case_id:'missing'},0)).toMatchObject({case_id:'missing',arm:0});
    expect(switchVisualArm(teachingFixture('peft'),{kind:'low-rank',arm:1,matrix:'total',row:2,column:3},0)).toMatchObject({matrix:'total',row:2,column:3});
    expect(switchVisualArm(teachingFixture('diffusion'),{kind:'diffusion-timeline',arm:1,frame:2},0)).toMatchObject({frame:1});
  });
  it('counts all endpoint-inclusive histogram samples without duplicating the maximum',()=>{
    expect(histogram([0,1,2,3,4],0,4,2).map(b=>b.count)).toEqual([2,3]);
  });
});
describe('Interactive mechanism renderers',()=>{
  it('follows an actual case into its source and handles a missing-source case',()=>{
    render(<Harness topic="rag"/>);expect(screen.getByText('器材借用期限为7天。',{selector:'.source-excerpt p'})).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox'),{target:{value:'missing'}});
    expect(screen.getByText('未召回片段。此时应检查是否需要拒答。')).toBeInTheDocument();expect(screen.getByText(/拒答/,{selector:'.rag-answer p'})).toBeInTheDocument();
  });
  it('lets a keyboard user inspect matrix cells and select another saved matrix',()=>{
    render(<Harness topic="peft"/>);const cell=screen.getByRole('button',{name:/第1行第1列，数值/});
    fireEvent.keyDown(cell,{key:'ArrowRight'});expect(screen.getByRole('heading',{name:'第 1 行，第 2 列'})).toBeInTheDocument();
    expect(screen.getByRole('button',{name:/第1行第2列/})).toHaveFocus();
    fireEvent.click(screen.getByRole('button',{name:'A · 低维输入投影'}));expect(screen.getByRole('group',{name:/2行6列/})).toBeInTheDocument();
  });
  it('reads sampling moments from the selected saved step and provides an exact data table',()=>{
    render(<Harness topic="diffusion"/>);const slider=screen.getByRole('slider');fireEvent.change(slider,{target:{value:'1'}});
    expect(screen.getByText('扩散时间 t = 0.5')).toBeInTheDocument();expect(screen.getByRole('button',{name:'播放采样回放'})).toBeInTheDocument();
    fireEvent.click(screen.getByText('查看逐点数据'));expect(screen.getByRole('table')).toBeVisible();
  });
});
