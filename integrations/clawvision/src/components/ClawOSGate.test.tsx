import { afterEach, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ClawOSGate } from './ClawOSGate';
afterEach(()=>{vi.unstubAllGlobals();history.replaceState({},'','/');});
it('checks status without starting a process until requested',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>({running:false,source_available:true})}).mockResolvedValueOnce({ok:true,json:async()=>({running:true,source_available:true})});vi.stubGlobal('fetch',fetcher);
  render(<ClawOSGate>{u=><p>已进入 {u.userId}</p>}</ClawOSGate>);
  const button=await screen.findByRole('button',{name:'进入实验工作区'});await waitFor(()=>expect(button).toBeEnabled());expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.click(button);await screen.findByText('已进入 local-user');expect(fetcher.mock.calls[1][0]).toBe('/api/vision/start');expect(fetcher.mock.calls[1][1].method).toBe('POST');
});
it('shows permission denial without falling back to standalone bootstrap',async()=>{
  const fetcher=vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'实验权限不足'})});vi.stubGlobal('fetch',fetcher);
  render(<ClawOSGate>{()=>null}</ClawOSGate>);await screen.findByText('实验权限不足');expect(fetcher).toHaveBeenCalledTimes(1);expect(screen.queryByText('初始化 Owner')).not.toBeInTheDocument();
});
