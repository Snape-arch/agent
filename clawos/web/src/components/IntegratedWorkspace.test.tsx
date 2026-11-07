import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { IntegratedWorkspace } from './IntegratedWorkspace';
import { workspaceRoutes } from '../workspaceNavigation';
vi.mock('./VisualLearningStudio',()=>({VisualLearningStudio:()=> <h1>课堂图解</h1>}));
vi.mock('./TeachingWorkbench',()=>({TeachingWorkbench:()=> <h1>实验记录</h1>}));
beforeEach(()=>{history.replaceState({},'','/academy/vision/#visuals');vi.stubGlobal('fetch',vi.fn(async(path:string)=>({ok:true,json:async()=>({running:path==='/api/vision/start',source_available:true})})));});
afterEach(()=>{cleanup();vi.unstubAllGlobals();history.replaceState({},'','/');});
const mount=()=>render(<IntegratedWorkspace renderWorkspace={(u,v)=> <h1>工作工具 {v} · {u.userId}</h1>}/>);
describe('One integrated education shell',()=>{
  it('starts in the visual classroom with every tool reachable and no runtime request',async()=>{
    mount();await screen.findByRole('heading',{name:'课堂图解'});expect(fetch).not.toHaveBeenCalled();
    for(const route of workspaceRoutes)expect(screen.getByTestId('unified-nav-'+route.id)).toBeInTheDocument();
    expect(screen.getAllByRole('main')).toHaveLength(1);
  });
  it('keeps the same navigation while the worker is stopped and starts only after a click',async()=>{
    mount();await screen.findByRole('heading',{name:'课堂图解'});expect(screen.getByTestId('unified-nav-three')).not.toBeVisible();fireEvent.click(screen.getByText('更多分析与实验工具'));expect(screen.getByTestId('unified-nav-three')).toBeVisible();fireEvent.click(screen.getByTestId('unified-nav-three'));
    const start=await screen.findByRole('button',{name:'启用本机实验服务'});await waitFor(()=>expect(start).toBeEnabled());
    expect(screen.getByRole('navigation',{name:'可视化教学工作区'})).toBeInTheDocument();expect(vi.mocked(fetch).mock.calls.map(c=>c[0])).toEqual(['/api/vision/runtime']);
    fireEvent.click(start);await screen.findByRole('heading',{name:'工作工具 three · local-user'});
    fireEvent.click(screen.getByTestId('unified-nav-data'));await screen.findByRole('heading',{name:'工作工具 data · local-user'});
    expect(vi.mocked(fetch).mock.calls.filter(c=>c[0]==='/api/vision/start')).toHaveLength(1);
  });
  it('restores presentation mode with Escape and preserves keyboard access to the main area',async()=>{
    mount();await screen.findByRole('heading',{name:'课堂图解'});fireEvent.click(screen.getByRole('button',{name:'专注演示'}));
    expect(screen.getByTestId('integrated-workspace')).toHaveClass('presentation-mode');
    fireEvent.keyDown(window,{key:'Escape'});expect(screen.getByTestId('integrated-workspace')).not.toHaveClass('presentation-mode');
    fireEvent.click(screen.getByRole('link',{name:'跳到主要内容'}));expect(screen.getByRole('main')).toHaveFocus();expect(location.hash).toBe('#visuals');
  });
});
