import { request, type RunPagination } from './api';

export interface EvaluationSample { id: string; label: string; conditions?: Record<string, string>; imageUri?: string | null; contentHash?: string | null }
export interface TestSetInput { name: string; task?: 'classification'; classes?: string[]; samples: EvaluationSample[]; datasetVersionId?: string }
export interface TestSet { id: string; name: string; task: 'classification'; digest: string; classes: string[]; sampleCount: number; datasetVersionId: string | null; createdAt: string }
export interface Prediction { sampleId: string; label: string; confidence?: number }
export interface EvaluationInput { testSetId: string; runId: string; predictions: Prediction[]; name?: string; modelArtifactId?: string }
export interface ErrorGroup { dimension: string; value: string; total: number; errors: number; errorRate: number }
export interface EvaluationReport {
  id: string; name: string; testSetId: string; runId: string; digest: string; createdAt: string;
  summary: {
    total: number; correct: number; errors: number; accuracy: number; errorRate: number; macroF1: number;
    groups: ErrorGroup[];
    classMetrics: Array<{ label: string; support: number; precision: number | null; recall: number | null; f1: number | null }>;
    confusion: Array<{ actual: string; predicted: string; count: number }>;
  };
  provenance: {
    kind: 'uploaded-predictions' | 'cpu-rgb-softmax/1'; testSetDigest: string; datasetVersionId: string | null;
    run: { id: string; name: string; source: string; status: string; revision: number; params: Record<string, unknown> };
    modelArtifact: { id: string; name: string; type: string; created_at: string } | null;
  };
}
export interface FailureCase { sampleId: string; label: string; predictedLabel: string; confidence: number | null; correct: boolean; conditions: Record<string, string>; imageUri: string | null; contentHash: string | null }
export interface EvaluationComparison {
  baseline: EvaluationReport; candidate: EvaluationReport; testSetId: string;
  accuracyDelta: number; errorRateDelta: number; macroF1Delta: number;
  fixed: number; regressed: number; bothCorrect: number; bothWrong: number;
  groups: Array<ErrorGroup & { baselineErrors: number; errorRateDelta: number }>;
}
export interface EvaluationPage<T> { data: T[]; pagination: RunPagination }

const root = '/api/evaluation';
export function fetchTestSets(page = 1, signal?: AbortSignal) { return request<EvaluationPage<TestSet>>(`${root}/test-sets?page=${page}&pageSize=25`, { signal }); }
export function createTestSet(input: TestSetInput) { return request<{ data: TestSet }>(`${root}/test-sets`, { method: 'POST', body: JSON.stringify(input), timeoutMs: 60_000 }); }
export function exportTestSet(id: string) { return request<{ data: TestSet & { samples: EvaluationSample[] } }>(`${root}/test-sets/${encodeURIComponent(id)}/export`); }
export function fetchEvaluations(testSetId: string, page = 1, signal?: AbortSignal) {
  const query = new URLSearchParams({ testSetId, page: String(page), pageSize: '25' });
  return request<EvaluationPage<EvaluationReport>>(`${root}/reports?${query}`, { signal });
}
export function fetchEvaluation(id: string, signal?: AbortSignal) { return request<{ data: EvaluationReport }>(`${root}/reports/${encodeURIComponent(id)}`, { signal }); }
export function createEvaluation(input: EvaluationInput) { return request<{ data: EvaluationReport }>(`${root}/reports`, { method: 'POST', body: JSON.stringify(input), timeoutMs: 60_000 }); }
export function fetchFailureCases(id: string, page = 1, group?: Pick<ErrorGroup, 'dimension' | 'value'>, signal?: AbortSignal) {
  const query = new URLSearchParams({ page: String(page), pageSize: '25', failuresOnly: 'true' });
  if (group) { query.set('dimension', group.dimension); query.set('value', group.value); }
  return request<EvaluationPage<FailureCase>>(`${root}/reports/${encodeURIComponent(id)}/cases?${query}`, { signal });
}
export function compareEvaluations(baselineId: string, candidateId: string, signal?: AbortSignal) {
  return request<{ data: EvaluationComparison }>(`${root}/compare?${new URLSearchParams({ baselineId, candidateId })}`, { signal });
}
