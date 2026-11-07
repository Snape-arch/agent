import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SynthesisWorkbench } from './SynthesisWorkbench';
import * as api from '../synthesisApi';
import type { ScenePlan } from '../scenarioApi';
import { registerSynthesisDataset } from '../visionApi';
vi.mock('../visionApi',()=>({registerSynthesisDataset:vi.fn()}));

vi.mock('../synthesisApi', () => ({ createSynthesisJob: vi.fn(), exportSynthesisPackage: vi.fn(), fetchSynthesisArtifact: vi.fn(),
  fetchSynthesisFrames: vi.fn(), fetchSynthesisJob: vi.fn(), fetchSynthesisJobs: vi.fn(), synthesisAction: vi.fn() }));
const pagination = { page: 1, pageSize: 25, total: 1, pages: 1, hasNext: false, hasPrevious: false };
const plan = { id: 'scene', variantCount: 3 } as ScenePlan;
const job: api.SynthesisJob = { id: 'job', scenarioId: 'scene', taskId: 'task', status: 'completed', total: 3, completed: 3, accepted: 2, rejected: 1,
  attempts: 1, digest: 'a'.repeat(64), error: null, config: { variantIndices: [0,1,2], minVisiblePixels: 64, minVisibleFraction: .2, rejectClipped: true,
    renderer: 'cpu', shading: 'approx', resolution: [512,512] }, createdAt: 'now', updatedAt: 'now' };
const frame: api.SynthesisFrame = { variantIndex: 0, accepted: true, annotation: { label: 'gear', labelSource: 'user-associated-asset',
  visiblePixels: 300, amodalPixels: 400, visibleFraction: .75, bbox: [1,2,20,30], amodalBbox: [1,2,25,30], clipped: false, rejectionReasons: [] },
  artifacts: Object.fromEntries(['image','mask','amodalMask'].map((kind) => [kind,{ url: '/private/'+kind, sha256: 'b'.repeat(64), byteSize: 100 }])) as api.SynthesisFrame['artifacts'] };
const BrowserURL = URL;
describe('synthetic render workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('URL', Object.assign(class extends BrowserURL {}, { createObjectURL: vi.fn(() => 'blob:private-image'), revokeObjectURL: vi.fn() }));
    vi.mocked(api.fetchSynthesisJobs).mockResolvedValue({ data: [job], pagination });
    vi.mocked(api.fetchSynthesisJob).mockResolvedValue({ data: job });
    vi.mocked(api.fetchSynthesisFrames).mockResolvedValue({ data: [frame], pagination });
    vi.mocked(api.fetchSynthesisArtifact).mockResolvedValue(new Blob(['image'],{type:'image/png'}));
    vi.mocked(api.createSynthesisJob).mockResolvedValue({ data: job });
    vi.mocked(api.synthesisAction).mockResolvedValue({ data: job });
    vi.mocked(api.exportSynthesisPackage).mockRejectedValue(new Error('hash verification failed'));
  });
  afterEach(() => vi.unstubAllGlobals());
  const select = async () => fireEvent.click(await screen.findByRole('button',{name: /已完成 · 3\/3 张/}));

  it('lets viewers inspect authenticated image types, disposes URLs and reports download failures', async () => {
    const { unmount } = render(<SynthesisWorkbench plan={plan} canWrite={false} />);
    expect(screen.queryByRole('button',{name:'开始渲染与标注'})).not.toBeInTheDocument();
    await select();
    expect(api.fetchSynthesisArtifact).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button',{name:'查看渲染与掩码'}));
    expect(await screen.findByRole('img',{name:'变体 1 RGB 渲染图'})).toHaveAttribute('src','blob:private-image');
    fireEvent.change(screen.getByLabelText('合成图片类型'),{target:{value:'mask'}});
    await screen.findByRole('img',{name:'变体 1 可见区域掩码'});
    expect(api.fetchSynthesisArtifact).toHaveBeenLastCalledWith('job',0,'mask',expect.any(AbortSignal));
    expect(URL.revokeObjectURL).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'下载合成数据包 ZIP'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('hash verification failed');
    unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it('submits zero-based variants and quality thresholds with selected values', async () => {
    render(<SynthesisWorkbench plan={plan} canWrite />);
    fireEvent.change(screen.getByLabelText('渲染起始变体'),{target:{value:'2'}});
    fireEvent.change(screen.getByLabelText('渲染变体数量'),{target:{value:'2'}});
    fireEvent.change(screen.getByLabelText('最少可见像素'),{target:{value:'500'}});
    fireEvent.change(screen.getByLabelText('最小可见比例'),{target:{value:'.6'}});
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button',{name:'开始渲染与标注'}));
    await waitFor(() => expect(api.createSynthesisJob).toHaveBeenCalledWith('scene',{variantIndices:[1,2],minVisiblePixels:500,minVisibleFraction:.6,rejectClipped:false}));
    await screen.findByRole('button',{name:'查看渲染与掩码'});
    expect(screen.getByRole('progressbar')).toHaveAttribute('value','3');
  });

  it('registers only completed accepted images as an immutable dataset version',async()=>{
    vi.mocked(registerSynthesisDataset).mockResolvedValue({data:{id:'version',datasetId:'dataset',version:1,name:'registered',origin:'synthetic',purpose:'train',sampleCount:2,classes:['gear'],sourceJobId:'job',digest:'a'.repeat(64),createdAt:'now'}});
    render(<SynthesisWorkbench plan={plan} canWrite/>);await select();
    fireEvent.click(await screen.findByRole('button',{name:'登记合成数据集版本'}));
    await waitFor(()=>expect(registerSynthesisDataset).toHaveBeenCalledWith('job'));
    expect(await screen.findByText(/已登记 registered v1 · 2 张/)).toBeInTheDocument();
  });

  it('polls running tasks to completion and enables cancellation', async () => {
    const running = { ...job,status:'running' as const,completed:1,accepted:1,rejected:0 };
    vi.mocked(api.fetchSynthesisJobs).mockResolvedValue({data:[running],pagination});
    vi.mocked(api.fetchSynthesisJob).mockResolvedValueOnce({data:running}).mockResolvedValue({data:job});
    render(<SynthesisWorkbench plan={plan} canWrite />);
    fireEvent.click(await screen.findByRole('button',{name:/渲染中 · 1\/3 张/}));
    expect(await screen.findByRole('button',{name:'取消渲染'})).toBeEnabled();
    await waitFor(() => expect(screen.getByRole('button',{name:'下载合成数据包 ZIP'})).toBeEnabled(),{timeout:2500});
    expect(screen.queryByRole('button',{name:'取消渲染'})).not.toBeInTheDocument();
    expect(api.fetchSynthesisJob).toHaveBeenCalledTimes(2);
  });

  it('allows explicit retry and displays a batch with zero accepted samples', async () => {
    const failed = { ...job,status:'failed' as const,completed:1,error:'worker interrupted' };
    vi.mocked(api.fetchSynthesisJobs).mockResolvedValue({data:[failed],pagination});
    vi.mocked(api.fetchSynthesisJob).mockResolvedValue({data:failed});
    render(<SynthesisWorkbench plan={plan} canWrite />);
    fireEvent.click(await screen.findByRole('button',{name:/失败 · 1\/3 张/}));
    fireEvent.click(await screen.findByRole('button',{name:'重试生成任务'}));
    await waitFor(() => expect(api.synthesisAction).toHaveBeenCalledWith('job','retry'));
    vi.mocked(api.fetchSynthesisJob).mockResolvedValue({data:{...job,accepted:0,rejected:3}});
    await screen.findByRole('button',{name:'重试生成任务'});
    fireEvent.click(screen.getByRole('button',{name:'重试生成任务'}));
    expect(await screen.findByText(/本批全部被剔除/)).toBeInTheDocument();
  });
});
