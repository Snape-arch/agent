import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ThreeLab } from './ThreeLab';
import { fetchModelAsset,fetchModelAssets } from '../api';
vi.mock('../api',async original=>({...await original<typeof import('../api')>(),fetchModelAssets:vi.fn(),fetchModelAsset:vi.fn()}));
vi.mock('../visualizations/PluginHost',()=>({PluginHost:({input}:{input:{name:string}})=><p>渲染器：{input.name}</p>}));
beforeEach(()=>{history.replaceState({},'','/academy/vision/#three');vi.mocked(fetchModelAssets).mockResolvedValue({data:[]});});afterEach(()=>{cleanup();history.replaceState({},'','/');});
it('keeps constructed point clouds out of the asset view until explicitly selected',async()=>{
  render(<ThreeLab/>);await screen.findByText('把结构放进空间里理解。');expect(screen.queryByText(/渲染器/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'探索内置概念示例'}));
  expect(screen.getByText(/不是训练得到的Embedding、UMAP结果或真实物理仿真/)).toBeInTheDocument();expect(screen.getByText('渲染器：合成三维坐标演示')).toBeInTheDocument();
});
it('does not turn an asset service failure into a claimed model preview',async()=>{
  vi.mocked(fetchModelAssets).mockRejectedValue(Error('Synthetic offline failure'));render(<ThreeLab/>);
  await screen.findByText('资产服务暂时不可用；未自动替换为示例模型。');expect(screen.queryByText(/渲染器/)).not.toBeInTheDocument();
});
it('reopens the selected model from the shared workspace URL after navigation or refresh',async()=>{
  history.replaceState({},'','/academy/vision/?modelAsset=asset_saved#three');
  vi.mocked(fetchModelAsset).mockResolvedValue({data:{id:'asset_saved',name:'saved-model.obj',format:'obj',version:2,metadata:{},content:{base64:'fixture'}}} as never);
  render(<ThreeLab/>);await screen.findByText('已加载 saved-model.obj，当前显示保存的模型内容。');
  expect(fetchModelAsset).toHaveBeenCalledWith('asset_saved');expect(screen.getByText('渲染器：saved-model.obj')).toBeInTheDocument();
});
it('retains a model selection even if the page is refreshed before the content response',async()=>{
  vi.mocked(fetchModelAssets).mockResolvedValue({data:[{id:'asset_pending',name:'pending.obj',version:1}]} as never);
  vi.mocked(fetchModelAsset).mockImplementation(()=>new Promise(()=>{}));
  render(<ThreeLab/>);await screen.findByRole('option',{name:'pending.obj · v1'});
  fireEvent.change(screen.getByRole('combobox',{name:'模型资产版本'}),{target:{value:'asset_pending'}});
  expect(location.search).toContain('modelAsset=asset_pending');expect(screen.getByText('正在读取所选模型…')).toBeInTheDocument();
});
