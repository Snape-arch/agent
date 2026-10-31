import { request, requestBlob } from './api';
import type { EvaluationPage } from './evaluationApi';

export interface SynthesisInput { variantIndices: number[]; minVisiblePixels: number; minVisibleFraction: number; rejectClipped: boolean }
export interface SynthesisJob {
  id: string; scenarioId: string; taskId: string; status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  total: number; completed: number; accepted: number; rejected: number; attempts: number; digest: string | null; error: string | null;
  config: SynthesisInput & { renderer: string; shading: string; resolution: [number, number] }; createdAt: string; updatedAt: string;
}
export interface SynthesisFrame {
  variantIndex: number; accepted: boolean;
  annotation: { label: string; labelSource: 'user-associated-asset'; visiblePixels: number; amodalPixels: number; visibleFraction: number;
    bbox: [number, number, number, number] | null; amodalBbox: [number, number, number, number] | null; clipped: boolean; rejectionReasons: string[] };
  artifacts: Record<'image' | 'mask' | 'amodalMask', { url: string; sha256: string; byteSize: number }>;
}
const root = '/api/evaluation';
export function createSynthesisJob(scenarioId: string, input: SynthesisInput) { return request<{ data: SynthesisJob }>(`${root}/scenarios/${encodeURIComponent(scenarioId)}/renders`, { method: 'POST', body: JSON.stringify(input) }); }
export function fetchSynthesisJobs(scenarioId: string, page = 1, signal?: AbortSignal) { return request<EvaluationPage<SynthesisJob>>(`${root}/scenarios/${encodeURIComponent(scenarioId)}/renders?page=${page}&pageSize=25`, { signal }); }
export function fetchSynthesisJob(id: string, signal?: AbortSignal) { return request<{ data: SynthesisJob }>(`${root}/synthesis/${encodeURIComponent(id)}`, { signal }); }
export function fetchSynthesisFrames(id: string, page = 1, signal?: AbortSignal) { return request<EvaluationPage<SynthesisFrame>>(`${root}/synthesis/${encodeURIComponent(id)}/frames?page=${page}&pageSize=12`, { signal }); }
export function synthesisAction(id: string, action: 'cancel' | 'retry') { return request<{ data: SynthesisJob }>(`${root}/synthesis/${encodeURIComponent(id)}/${action}`, { method: 'POST', body: '{}' }); }
export function fetchSynthesisArtifact(id: string, index: number, kind: 'image' | 'mask' | 'amodalMask', signal?: AbortSignal) { return requestBlob(`${root}/synthesis/${encodeURIComponent(id)}/frames/${index}/${kind}`, { signal, timeoutMs: 60_000 }); }
export function exportSynthesisPackage(id: string) { return requestBlob(`${root}/synthesis/${encodeURIComponent(id)}/export`, { timeoutMs: 60_000 }); }
