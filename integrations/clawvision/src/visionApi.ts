import { request } from './api';
import type { EvaluationComparison, EvaluationPage } from './evaluationApi';
export interface ImageVersion { id:string; datasetId:string; version:number; name:string; origin:'real'|'synthetic'; purpose:'train'|'test'; digest:string; sampleCount:number; classes:string[]; sourceJobId:string|null; createdAt:string }
export interface TrainingConfig { seed:number; epochs:number; learningRate:number; regularization:number }
export interface VisionExperiment { id:string; taskId:string; status:'queued'|'running'|'completed'|'failed'|'cancelled'; realTrainVersionId:string; syntheticVersionId:string; testVersionId:string;
  baselineRunId:string; candidateRunId:string; testSetId:string; config:TrainingConfig; epochsCompleted:number; totalEpochs:number; attempts:number; error:string|null; createdAt:string;
  result:(EvaluationComparison & { provider:string; trainingSamples:{baseline:number;candidate:number}; modelSha256:Record<string,string>; leakageChecks:string })|null }
const root='/api/evaluation';
export function registerSynthesisDataset(id:string) { return request<{data:ImageVersion}>(`${root}/synthesis/${encodeURIComponent(id)}/dataset-version`,{method:'POST',body:'{}',timeoutMs:60_000}); }
export function createImageDataset(body:unknown) { return request<{data:ImageVersion}>(`${root}/image-datasets`,{method:'POST',body:JSON.stringify(body),timeoutMs:120_000}); }
export function fetchImageVersions(page=1,signal?:AbortSignal) { return request<EvaluationPage<ImageVersion>>(`${root}/image-versions?page=${page}&pageSize=25`,{signal}); }
export function createVisionExperiment(realTrainVersionId:string,syntheticVersionId:string,testVersionId:string,config:TrainingConfig) { return request<{data:VisionExperiment}>(`${root}/experiments`,{method:'POST',body:JSON.stringify({realTrainVersionId,syntheticVersionId,testVersionId,config})}); }
export function fetchVisionExperiments(page=1,signal?:AbortSignal) { return request<EvaluationPage<VisionExperiment>>(`${root}/experiments?page=${page}&pageSize=25`,{signal}); }
export function fetchVisionExperiment(id:string,signal?:AbortSignal) { return request<{data:VisionExperiment}>(`${root}/experiments/${encodeURIComponent(id)}`,{signal}); }
export function visionExperimentAction(id:string,action:'cancel'|'retry') { return request<{data:VisionExperiment}>(`${root}/experiments/${encodeURIComponent(id)}/${action}`,{method:'POST',body:'{}'}); }
