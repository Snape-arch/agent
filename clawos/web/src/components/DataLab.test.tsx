import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {DataLab} from './DataLab';
import {fetchDatasetPage,fetchDataset,fetchVisualization,saveVisualization} from '../api';
vi.mock('../api',()=>({fetchDatasetPage:vi.fn(),fetchDataset:vi.fn(),fetchVisualization:vi.fn(),fetchSharedVisualization:vi.fn(),importDataset:vi.fn(),saveVisualization:vi.fn()}));
vi.mock('../visualizations/PluginHost',()=>({PluginHost:({input}:{input:{data:unknown}})=><div data-testid="dataset-chart">{JSON.stringify(input.data)}</div>}));
const dataset={id:'data_real',name:'已保存CSV',format:'csv',rowCount:3,createdAt:'2026-10-31',schema:[{name:'step',type:'number',nullable:false},{name:'value',type:'number',nullable:false}],rows:[{step:1,value:.3},{step:2,value:.5},{step:3,value:.7}]};
beforeEach(()=>{history.replaceState({},'','/academy/vision/?dataset=data_real#data');vi.mocked(fetchDatasetPage).mockResolvedValue({data:[dataset],pagination:{page:1,hasNext:false,hasPrevious:false}} as never);vi.mocked(fetchDataset).mockResolvedValue({data:dataset} as never);});
afterEach(()=>{vi.clearAllMocks();history.replaceState({},'','/');});
it('loads the persisted selected dataset rather than substituting demo rows',async()=>{
 render(<DataLab/>);await screen.findByText('已保存CSV');expect(fetchDataset).toHaveBeenCalledWith('data_real');expect(screen.getByTestId('dataset-chart')).toHaveTextContent('0.3');expect(screen.queryByText('训练表现样例')).not.toBeInTheDocument();
});
it('saves privately and restores the persisted visualization snapshot',async()=>{
 vi.mocked(saveVisualization).mockResolvedValue({data:{id:'viz_1',version:1,shareToken:'unused'}} as never);
 const first=render(<DataLab/>);await screen.findByText('已保存CSV');fireEvent.click(screen.getByRole('button',{name:'保存图表'}));
 const link=await screen.findByRole('link',{name:'重新打开私有图表'});expect(saveVisualization).toHaveBeenCalledWith(expect.objectContaining({isPublic:false,datasetId:'data_real'}));expect(link.getAttribute('href')).toContain('visualization=viz_1');expect(link.getAttribute('href')).not.toContain('shared=');
 first.unmount();history.replaceState({},'',link.getAttribute('href')!);
 vi.mocked(fetchVisualization).mockResolvedValue({data:{id:'viz_1',version:1,spec:{datasetSnapshot:dataset,charts:[{id:'c',title:'恢复后的图表',type:'line-chart',xField:'step',yField:'value'}]}}} as never);
 render(<DataLab/>);await screen.findByText('已恢复私有图表 v1');expect(screen.getByText('恢复后的图表')).toBeInTheDocument();
});
it('shows catalog failure and uses samples only after explicit selection',async()=>{
 vi.mocked(fetchDatasetPage).mockRejectedValueOnce(new Error('catalog offline'));render(<DataLab/>);await screen.findByText('catalog offline');expect(screen.queryByText('训练表现样例')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'查看内置示例'}));await waitFor(()=>expect(screen.getByText('训练表现样例')).toBeInTheDocument());expect(screen.getByRole('button',{name:'保存图表'})).toBeDisabled();expect(screen.getByText('内置示例数据，不是导入数据或真实训练结果。')).toBeInTheDocument();
});
