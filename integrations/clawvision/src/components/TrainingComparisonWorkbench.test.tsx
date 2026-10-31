import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TrainingComparisonWorkbench } from './TrainingComparisonWorkbench';
import * as api from '../visionApi';
import type { EvaluationReport } from '../evaluationApi';
vi.mock('../visionApi',()=>({createImageDataset:vi.fn(),createVisionExperiment:vi.fn(),fetchImageVersions:vi.fn(),fetchVisionExperiment:vi.fn(),fetchVisionExperiments:vi.fn(),visionExperimentAction:vi.fn()}));
const pagination={page:1,pageSize:25,total:3,pages:1,hasNext:false,hasPrevious:false};
const versions:api.ImageVersion[]=[['train','real','train'],['synth','synthetic','train'],['test','real','test']].map(([id,origin,purpose])=>({id,datasetId:'dataset-'+id,version:1,name:id,origin,purpose,digest:'a'.repeat(64),sampleCount:4,classes:['gear','bolt'],sourceJobId:null,createdAt:'now'})) as api.ImageVersion[];
const report:EvaluationReport={id:'report',name:'report',testSetId:'set',runId:'run-base',digest:'hash',createdAt:'now',
  summary:{accuracy:.75,macroF1:.7,total:4,correct:3,errors:1,errorRate:.25,groups:[],classMetrics:[],confusion:[]},
  provenance:{kind:'cpu-rgb-softmax/1',testSetDigest:'set-hash',datasetVersionId:'test',modelArtifact:null,run:{id:'run-base',name:'base',source:'cpu',status:'completed',revision:1,params:{}}}};
const job:api.VisionExperiment={id:'experiment',taskId:'task',realTrainVersionId:'train',syntheticVersionId:'synth',testVersionId:'test',testSetId:'set',attempts:1,createdAt:'now',
  config:{seed:42,epochs:50,learningRate:.1,regularization:.001},status:'completed',epochsCompleted:100,totalEpochs:100,baselineRunId:'run-base',candidateRunId:'run-candidate',error:null,
  result:{provider:'cpu-rgb-softmax/1',baseline:report,candidate:{...report,id:'candidate',runId:'run-candidate',summary:{...report.summary,accuracy:.5,macroF1:.45}},
    testSetId:'set',errorRateDelta:.25,macroF1Delta:-.25,bothCorrect:1,bothWrong:0,accuracyDelta:-.25,fixed:1,regressed:2,groups:[],trainingSamples:{baseline:4,candidate:7},modelSha256:{},leakageChecks:'hash'}};
describe('real training comparison workbench',()=>{
  beforeEach(()=>{
    vi.clearAllMocks();vi.mocked(api.fetchImageVersions).mockResolvedValue({data:versions,pagination});
    vi.mocked(api.fetchVisionExperiments).mockResolvedValue({data:[job],pagination:{...pagination,total:1}});
    vi.mocked(api.fetchVisionExperiment).mockResolvedValue({data:job});vi.mocked(api.createVisionExperiment).mockResolvedValue({data:job});
    vi.mocked(api.visionExperimentAction).mockResolvedValue({data:job});vi.mocked(api.createImageDataset).mockResolvedValue({data:versions[0]});
  });
  it('shows regressions honestly and gives viewers results without write forms',async()=>{
    render(<TrainingComparisonWorkbench canWrite={false}/>);
    fireEvent.click(await screen.findByRole('button',{name:/已完成 · 100\/100 轮/}));
    expect(await screen.findByTestId('real-training-comparison')).toHaveTextContent('-25.0 个百分点');
    expect(screen.getByTestId('real-training-comparison')).toHaveTextContent('1 / 2');
    expect(screen.queryByLabelText('真实图片版本 JSON')).not.toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'开始真实训练对比'})).not.toBeInTheDocument();
    expect(screen.getByRole('button',{name:'导出真实训练对比'})).toBeEnabled();
  });
  it('binds real train, synthetic train and held-out test versions with shared config',async()=>{
    render(<TrainingComparisonWorkbench canWrite/>);
    await screen.findByRole('option',{name:/train v1/});
    fireEvent.change(screen.getByLabelText('真实训练版本'),{target:{value:'train'}});
    fireEvent.change(screen.getByLabelText('合成训练版本'),{target:{value:'synth'}});
    fireEvent.change(screen.getByLabelText('独立真实测试版本'),{target:{value:'test'}});
    fireEvent.change(screen.getByLabelText('CPU epochs'),{target:{value:'20'}});
    fireEvent.click(screen.getByRole('button',{name:'开始真实训练对比'}));
    await waitFor(()=>expect(api.createVisionExperiment).toHaveBeenCalledWith('train','synth','test',{seed:42,epochs:20,learningRate:.1,regularization:.001}));
    await screen.findByTestId('real-training-comparison');
  });
  it('polls progress and allows explicit cancellation',async()=>{
    const running={...job,status:'running' as const,epochsCompleted:10,result:null};
    vi.mocked(api.fetchVisionExperiments).mockResolvedValue({data:[running],pagination});
    vi.mocked(api.fetchVisionExperiment).mockResolvedValueOnce({data:running}).mockResolvedValue({data:job});
    render(<TrainingComparisonWorkbench canWrite/>);
    fireEvent.click(await screen.findByRole('button',{name:/训练中 · 10\/100 轮/}));
    fireEvent.click(await screen.findByRole('button',{name:'取消真实训练对比'}));
    await waitFor(()=>expect(api.visionExperimentAction).toHaveBeenCalledWith('experiment','cancel'));
    await screen.findByTestId('real-training-comparison');
    expect(screen.queryByRole('button',{name:'取消真实训练对比'})).not.toBeInTheDocument();
  });
  it('imports image manifests and keeps upload failures visible',async()=>{
    render(<TrainingComparisonWorkbench canWrite/>);
    const body={name:'real dataset',purpose:'train',samples:[{id:'a',label:'gear',imageBase64:'image'}]};
    const file=Object.assign(new File(['manifest'],'images.json',{type:'application/json'}),{text:async()=>JSON.stringify(body)});
    fireEvent.change(screen.getByLabelText('真实图片版本 JSON'),{target:{files:[file]}});
    await waitFor(()=>expect(api.createImageDataset).toHaveBeenCalledWith(body));
    expect(await screen.findByText(/train v1 已冻结/)).toBeInTheDocument();
    vi.mocked(api.createImageDataset).mockRejectedValueOnce(new Error('duplicate decoded pixels'));
    fireEvent.change(screen.getByLabelText('真实图片版本 JSON'),{target:{files:[file]}});
    expect(await screen.findByRole('alert')).toHaveTextContent('duplicate decoded pixels');
  });
});
