import { defaultParams, runColors, type EmbeddingPoint, type ExperimentParams, type ExperimentRun, type RunArtifact, type SamplePrediction } from './domain';
import type { VisualizationSpec } from './visualizations/types';
import { integrated, researchContext, visionApiUrl, visionPayload } from './clawos';

export interface DatasetField { name: string; type: 'number' | 'string' | 'boolean' | 'datetime'; nullable: boolean }
export interface ImportedDataset { id: string; name: string; format: 'csv' | 'json' | 'parquet'; schema: DatasetField[]; rows: Array<Record<string, unknown>>; rowCount: number; createdAt: string }
export interface SavedVisualization { id: string; name: string; datasetId?: string; spec: VisualizationSpec & { charts?: VisualizationSpec[] }; shareToken: string; isPublic: boolean; version: number; updatedAt: string }
export interface ModelResource { name: string; mimeType: string; base64: string }
export interface AssetReference { kind: 'run' | 'scene' | 'scene-version' | 'generation' | 'asset-version' | 'evaluation-scenario'; id: string; role?: string; step?: number; version?: number }
export interface AssetComponent { id: string; type: 'mesh' | 'material' | 'texture'; version: number; metadata: Record<string, unknown>; createdAt: string }
export interface AssetRelease { id: string; status: 'pending' | 'approved' | 'rejected'; reviewer: string; note: string; createdAt: string; updatedAt: string }
export interface AssetProject { id: string; name: string; description: string; assetCount: number; createdAt: string; updatedAt: string }
export interface ModelAsset { id: string; name: string; format: 'glb' | 'gltf' | 'obj' | 'stl' | 'ply' | 'step' | 'iges' | 'brep'; version: number; parentId?: string; projectId?: string; folder: string; stage: 'raw' | 'edit' | 'lod' | 'release' | string; tags: string[]; thumbnailKey?: string; archivedAt?: string; deletedAt?: string; metadata: Record<string, unknown>; content?: { base64: string; byteSize?: number; binaryKey?: string; resources?: ModelResource[] }; components?: AssetComponent[]; releases?: AssetRelease[]; references?: AssetReference[]; createdAt: string; updatedAt: string }
export interface RunTimelineFrame { step: number; metrics: Partial<ExperimentRun['metrics'][number]>; artifacts: Array<{ id: string; name: string; type: string; mimeType: string; createdAt: string }>; assets: Array<{ linkId: string; role: string; sceneId?: string; metadata: Record<string, unknown>; asset: ModelAsset }> }
export interface RunTimeline { runId: string; frames: RunTimelineFrame[]; maxStep: number }
export interface StudioModifier { id: string; type: 'remesh' | 'repair'; targetFaces?: number; normals?: boolean; holes?: boolean }
export interface StudioPart { shape: 'box' | 'roundedBox' | 'sphere' | 'cylinder' | 'torus' | 'capsule'; name: string; size: number[]; position: number[]; rotation: number[]; color: string; material: string; bevel?: number; booleanOperation?: 'base' | 'union' | 'subtract' | 'intersect'; uv?: { repeatX: number; repeatY: number; strength: number }; groupId?: string; modifiers?: StudioModifier[] }
export interface StudioPlan { kind: 'model3d'; name: string; template: string; prompt: string; provider: string; parameters: { scale: number; complexity: number; curveStrength: number; connectionDensity: number; color: string; material: string; textureRepeatX?: number; textureRepeatY?: number; textureStrength?: number }; parts: StudioPart[]; agents: Array<{ id: string; name: string; status: string; message: string }>; validation: { valid: boolean; score: number; warnings: string[]; checks: string[] } }
export interface ExperimentAiPlan { kind: 'experiment'; prompt: string; patch: Partial<ExperimentParams>; params: ExperimentParams; configs: ExperimentParams[]; jobKind: 'single' | 'sweep' | 'grid'; execute: boolean; visualization: VisualizationSpec; explanation: string; provider: string }
export interface StudioGeneration { id: string; name: string; prompt: string; provider: string; plan: StudioPlan; validation: StudioPlan['validation']; assetId?: string; version: number; createdAt: string; updatedAt: string }
export interface AgentStage { id: string; cycle: number; stage: string; name: string; status: 'running' | 'completed' | 'failed'; attempt: number; maxAttempts: number; inputArtifactId?: string; outputArtifactId?: string; tokens: number; tokenSource: 'provider' | 'estimated-workload'; cost: number; durationMs: number; error?: string }
export interface AgentArtifact { id: string; stage: string; cycle: number; kind: string; payload: unknown; createdAt: string }
export interface StudioAgentRun { id: string; prompt: string; provider: string; model: string; status: string; cycle: number; maxCycles: number; totalTokens: number; totalCost: number; durationMs: number; result?: StudioPlan; error?: string; timeoutSeconds?: number; cancelRequested?: boolean; stages: AgentStage[]; artifacts: AgentArtifact[]; createdAt: string; updatedAt: string }
export interface Text3DProvider { id: string; label: string; kind: string; configured: boolean; imageConditioning: boolean; requiresGpu: boolean }
export interface Text3DJob { id: string; prompt: string; provider: string; status: string; progress: number; stage: string; previewAssetId?: string; assetId?: string; stats?: { vertices: number; faces: number; bytes: number; resolution?: number; generator?: string; nonParametric: boolean; pbrTextureBaked?: boolean }; error?: string; createdAt: string; updatedAt: string }
export interface SceneOperation { id: string; type: 'transform' | 'material' | 'csg' | 'duplicate' | 'delete' | 'group' | 'remesh' | 'repair' | 'visibility' | 'lock' | 'rename' | 'modifier'; targetIds: string[]; payload: Record<string, unknown>; enabled?: boolean }
export interface SceneCommandPreview { command: string; operations: SceneOperation[]; affectedNodeIds: string[]; previewPlan: StudioPlan; explanation: string }
export interface ModelSceneNode { id: string; index: number; name: string; parentId?: string; children: string[]; meshIndex?: number; materialIds: number[]; translation: number[]; rotation: number[]; scale: number[]; visible: boolean; locked: boolean; groupId?: string; vertexCount: number; faceCount: number; bounds?: { min: number[]; max: number[] }; modifiers: Array<Record<string, unknown>> }
export interface ModelSceneManifest { nodes: ModelSceneNode[]; materials: Array<{ id: number; name: string; color: number[]; metallic: number; roughness: number; doubleSided: boolean }>; nodeCount: number; meshCount: number; materialCount: number }
export interface ModelQualityReport { format: string; score: number; threshold: number; passed: boolean; issues: string[]; issueNodeIds: string[]; summary: { nodes: number; meshes: number; materials: number }; metrics?: Record<string, number> }
export interface ModelSceneVersion { id: string; version: number; assetId: string; operations: SceneOperation[]; quality: ModelQualityReport; createdAt: string }
export interface ModelSceneDiff { operations: number; nodesAdded: number; nodesRemoved: number; materialsAdded: number; facesDelta: number }
export interface ModelScene { id: string; name: string; sourceAssetId: string; currentAssetId: string; version: number; operations: SceneOperation[]; scene: ModelSceneManifest; quality: ModelQualityReport; versions?: ModelSceneVersion[]; asset?: ModelAsset; lodAssets?: ModelAsset[]; diff?: ModelSceneDiff; createdAt: string; updatedAt: string }
export interface ModelOperationJob { id: string; sceneId: string; status: 'queued'|'running'|'completed'|'failed'|'cancelled'; progress: number; stage: string; operations: SceneOperation[]; result?: ModelScene; error?: string; cancelRequested: boolean; createdAt: string; updatedAt: string }
export interface AssetSceneCommand { command: string; operations: SceneOperation[]; affectedNodeIds: string[]; explanation: string }
export interface SceneAgentDecision { id: string; stage: string; decision: string; reason: string; payload: Record<string, unknown>; createdAt: string }
export interface SceneAgentRun { id: string; sceneId: string; command: string; provider: string; model: string; status: 'queued'|'understanding'|'planning'|'awaiting-confirmation'|'previewing'|'ready'|'applying'|'completed'|'rejected'|'failed'|'cancelled'|'stale'; progress: number; stage: string; baseVersion: number; operations: SceneOperation[]; analysis: { understanding?: Record<string, unknown>; plan?: { explanation?: string; affectedNodeIds?: string[] }; risk?: { score: number; level: string; warnings: string[]; affectedNodeIds: string[]; heavyGeometry: boolean; estimatedSeconds: number; estimatedCost: number; requiresConfirmation: boolean; rollbackStrategy: string } }; preview?: { objectKey: string; quality: ModelQualityReport; scene: ModelSceneManifest; cycle: number; asset?: { name: string; format: ModelAsset['format']; base64: string; resources?: ModelResource[] } }; result?: ModelScene | { operations: SceneOperation[]; quality: ModelQualityReport }; error?: string; riskLevel: string; estimatedCost: number; estimatedSeconds: number; qualityCycles: number; maxCycles: number; cancelRequested: boolean; decisions: SceneAgentDecision[]; createdAt: string; updatedAt: string }
export interface GeometryProvider { id: string; label: string; kind: 'builtin'|'command'|'http'; exact: boolean; formats: ModelAsset['format'][]; operations: string[]; configured: boolean; preemptiveCancel: boolean; checkpointResume: boolean }
export interface GeometryJob { id: string; sceneId?: string; sourceAssetId: string; provider: string; operation: Record<string, unknown>; status: 'queued'|'previewing'|'provider-running'|'completed'|'failed'|'cancelled'; progress: number; stage: string; priority: number; previewAssetId?: string; resultAssetId?: string; checkpointKey?: string; result?: { asset?: ModelAsset; scene?: ModelScene; stats?: Record<string, unknown> } | ModelScene; error?: string; cancelRequested: boolean; timeoutSeconds: number; createdAt: string; updatedAt: string }

interface ApiRun {
  id: string;
  name: string;
  status: ExperimentRun['status'];
  source?: string;
  errorMessage?: string;
  params: ExperimentParams;
  createdAt: string;
  metrics: ExperimentRun['metrics'];
  logs: string[];
  artifacts?: RunArtifact[];
  revision?: number;
  cursor?: number;
  events?: ExperimentRun['events'];
}

export interface RunPagination { page: number; pageSize: number; total: number; pages: number; hasNext: boolean; hasPrevious: boolean }
export type RunCounts = Partial<Record<ExperimentRun['status'], number>>;
export interface RunPage { data: ExperimentRun[]; pagination: RunPagination; counts: RunCounts }
export interface RunDelta {
  id: string; run: Omit<ApiRun, 'metrics' | 'logs' | 'artifacts'>; cursor: number; hasMore: boolean;
  metrics: ExperimentRun['metrics']; events: NonNullable<ExperimentRun['events']>; artifacts: RunArtifact[];
  removedMetrics: number[]; removedEvents: number[]; removedArtifacts: string[];
}

export class ApiError extends Error {
  constructor(message: string, public readonly kind: 'offline' | 'timeout' | 'http', public readonly status?: number) {
    super(message); this.name = 'ApiError';
  }
}

async function requestTransport<T>(path: string, options?: RequestInit & { timeoutMs?: number }, binary = false): Promise<T> {
  const token = getApiToken();
  const controller = new AbortController();
  const cancel = () => controller.abort();
  if (options?.signal?.aborted) controller.abort();
  options?.signal?.addEventListener('abort', cancel, { once: true });
  const timeout = window.setTimeout(() => controller.abort(), options?.timeoutMs ?? 15_000);
  try {
    const response = await fetch(visionApiUrl(path), {
      ...options, signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options?.headers ?? {}) },
    });
    if (response.ok && binary) return await response.blob() as T;
    const payload = await response.json().catch(() => ({})) as { error?: string; detail?: string };
    if (!response.ok) throw new ApiError(payload.error ?? payload.detail ?? `API request failed: ${response.status}`, 'http', response.status);
    return visionPayload(payload) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (options?.signal?.aborted) throw new DOMException('Request cancelled', 'AbortError');
    if (controller.signal.aborted) throw new ApiError('API request timed out', 'timeout');
    throw new ApiError('Backend is offline', 'offline');
  } finally { window.clearTimeout(timeout); options?.signal?.removeEventListener('abort', cancel); }
}

export function request<T>(path: string, options?: RequestInit & { timeoutMs?: number }) { return requestTransport<T>(path, options); }
export function requestBlob(path: string, options?: RequestInit & { timeoutMs?: number }) { return requestTransport<Blob>(path, options, true); }

function streamSse<T>(path: string, eventName: string, onData: (value: T, close: () => void) => void, onError?: () => void, onEnd?: () => void) {
  const controller = new AbortController(); const token = getApiToken();
  void fetch(visionApiUrl(path), { signal: controller.signal, headers: token ? { Authorization: `Bearer ${token}` } : {} }).then(async (response) => {
    if (!response.ok || !response.body) throw new Error(`SSE request failed: ${response.status}`);
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
    while (!controller.signal.aborted) {
      const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split('\n\n'); buffer = frames.pop() ?? '';
      for (const frame of frames) {
        const lines = frame.split('\n'); const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
        const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
        if (event === eventName && data) onData(visionPayload(JSON.parse(data)) as T, () => controller.abort());
      }
    }
    if (!controller.signal.aborted) onEnd?.();
  }).catch((error) => { if (!controller.signal.aborted) onError?.(); });
  return () => controller.abort();
}

function artifactContent<T>(artifacts: RunArtifact[], type: string): T | undefined {
  return artifacts.find((artifact) => artifact.type === type)?.content as T | undefined;
}

export function getApiToken() { if(integrated())return null; const legacy=localStorage.getItem('clawvision.api-token'); if(legacy){sessionStorage.setItem('clawvision.api-token',legacy);localStorage.removeItem('clawvision.api-token');} return sessionStorage.getItem('clawvision.api-token'); }
export function setApiToken(token?: string) { if (token) sessionStorage.setItem('clawvision.api-token', token); else { sessionStorage.removeItem('clawvision.api-token'); localStorage.removeItem('clawvision.api-token'); } }
export async function login(email: string, password: string) { const response = await request<{ data: { token: string; userId: string; tenantId: string; role: string } }>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }); setApiToken(response.data.token); return response; }
export async function bootstrapOwner(email: string, password: string, tenantName: string) { const response = await request<{ data: { token: string; userId: string; tenantId: string; role: string } }>('/api/auth/bootstrap', { method: 'POST', body: JSON.stringify({ email, password, tenantName }) }); setApiToken(response.data.token); return response; }
export interface CurrentUser { userId:string;tenantId:string;role:'viewer'|'researcher'|'admin'|'owner';scopes:string[] }
export async function fetchCurrentUser(){return (await request<{data:CurrentUser}>('/api/auth/me')).data;}
export async function fetchMembers(){return (await request<{data:Array<{userId:string;email:string;role:string;active:boolean}>}>('/api/auth/members')).data;}
export async function createMember(input:{email:string;password:string;role:'viewer'|'researcher'|'admin'}){return request('/api/auth/members',{method:'POST',body:JSON.stringify(input)});}
export async function fetchQuota(){return (await request<{data:{limits:Record<string,number>;usage:Record<string,number>}}>('/api/quotas')).data;}
export interface ApiTokenInfo{id:string;name:string;scopes:string[];expiresAt?:string;revokedAt?:string;createdAt:string}
export async function fetchApiTokens(){return (await request<{data:ApiTokenInfo[]}>('/api/auth/tokens')).data;}
export async function createApiToken(name:string,expiresHours=720){return (await request<{data:{token:string}}>('/api/auth/tokens',{method:'POST',body:JSON.stringify({name,expiresHours})})).data.token;}
export async function revokeApiToken(id:string){return request(`/api/auth/tokens/${id}`,{method:'DELETE'});}
export function logout(){setApiToken();location.reload();}

export function normalizeRun(run: ApiRun, index = 0): ExperimentRun {
  const artifacts = run.artifacts ?? [];
  const params = { ...defaultParams, ...run.params };
  return {
    ...run,
    params,
    color: runColors[index % runColors.length],
    confusion: artifactContent<number[][]>(artifacts, 'confusion-matrix') ?? [],
    samples: artifactContent<SamplePrediction[]>(artifacts, 'sample-predictions') ?? [],
    embedding: artifactContent<EmbeddingPoint[]>(artifacts, 'embedding-3d') ?? [],
    artifacts,
  };
}

export async function fetchRuns() {
  const response = await request<{ data: ApiRun[] }>('/api/runs');
  return response.data.map(normalizeRun);
}

export async function fetchRunPage(page = 1, q = '', signal?: AbortSignal): Promise<RunPage> {
  const query = new URLSearchParams({ summary: '1', page: String(page), pageSize: '25', q });
  type Summary = Omit<ApiRun, 'metrics' | 'logs'> & { latestMetric?: ExperimentRun['metrics'][number]; metricCount: number; artifactCount: number };
  const response = await request<{ data: Summary[]; pagination: RunPagination; counts: RunCounts }>(`/api/runs?${query}`, { signal });
  return { ...response, data: response.data.map((run, index) => ({ ...normalizeRun({ ...run, metrics: run.latestMetric ? [run.latestMetric] : [], logs: [] }, index), detailLoaded: false })) };
}

export async function fetchRun(id: string, signal?: AbortSignal): Promise<ExperimentRun> {
  const response = await request<{ data: ApiRun }>(`/api/runs/${encodeURIComponent(id)}`, { signal });
  return { ...normalizeRun(response.data), detailLoaded: true };
}

export async function fetchRunChanges(id: string, after: number, signal?: AbortSignal): Promise<RunDelta> {
  return (await request<{ data: RunDelta }>(`/api/runs/${encodeURIComponent(id)}/changes?after=${after}&limit=100`, { signal })).data;
}

export function applyRunDelta(run: ExperimentRun, delta: RunDelta): ExperimentRun {
  if (delta.id !== run.id || delta.cursor <= (run.cursor ?? 0)) return run;
  const metrics = new Map(run.metrics.map((point) => [point.step, point]));
  const events = new Map((run.events ?? []).map((event) => [event.id, event]));
  const artifacts = new Map((run.artifacts ?? []).map((artifact) => [artifact.id, artifact]));
  delta.removedMetrics.forEach((step) => metrics.delete(step));
  delta.removedEvents.forEach((id) => events.delete(id));
  delta.removedArtifacts.forEach((id) => artifacts.delete(id));
  delta.metrics.forEach((point) => metrics.set(point.step, point));
  delta.events.forEach((event) => events.set(event.id, event));
  delta.artifacts.forEach((artifact) => artifacts.set(artifact.id, artifact));
  const orderedEvents = [...events.values()].sort((a, b) => a.id - b.id);
  const normalized = normalizeRun({ ...run, ...delta.run, metrics: [...metrics.values()].sort((a, b) => a.step - b.step), events: orderedEvents,
    logs: orderedEvents.map((event) => event.message), artifacts: [...artifacts.values()].sort((a, b) => a.createdAt.localeCompare(b.createdAt) || a.id.localeCompare(b.id)), cursor: delta.cursor });
  return { ...normalized, color: run.color, detailLoaded: true };
}

export function subscribeToRunChanges(id: string, after: number, onDelta: (delta: RunDelta) => void, onError: () => void = () => {}) {
  let cursor = after, stopped = false, delay = 1000, timer: number | undefined;
  let cancelStream: (() => void) | undefined;
  const schedule = (failed = false, terminal = false) => {
    if (stopped) return;
    if (failed) { onError(); delay = Math.min(delay * 2, 15_000); }
    timer = window.setTimeout(connect, terminal ? 15_000 : delay);
  };
  const connect = () => {
    let terminal = false;
    cancelStream = streamSse<RunDelta>(`/api/runs/${encodeURIComponent(id)}/stream?incremental=1&after=${cursor}`, 'run-delta', (delta) => {
      cursor = Math.max(cursor, delta.cursor); delay = 1000;
      terminal = ['completed', 'stopped', 'failed'].includes(delta.run.status);
      onDelta(delta);
    }, () => schedule(true), () => schedule(false, terminal));
  };
  connect();
  return () => { stopped = true; window.clearTimeout(timer); cancelStream?.(); };
}

export async function createRemoteRun(name: string, params: ExperimentParams, source = 'ui-simulator') {
  const response = await request<{ data: ApiRun }>('/api/runs', { method: 'POST', body: JSON.stringify({ name, params, source }) });
  return normalizeRun(response.data);
}

export interface CreateJobInput {
  name: string;
  kind: 'single' | 'sweep' | 'grid';
  baselineRunId?: string;
  configs: ExperimentParams[];
  concurrency: number;
  estimateSeconds: number;
  estimatedCost: number;
  trainingProvider?: 'simulator' | 'local-python' | 'local-conda';
  timeoutSeconds?: number;
}

export interface TrainingProvider { id: CreateJobInput['trainingProvider']; label: string; kind: string; configured: boolean; gpu: boolean; environment?: string }
export async function fetchTrainingProviders() { return request<{ data: TrainingProvider[] }>('/api/training/providers'); }

export async function createParameterJob(input: CreateJobInput) {
  const result = await request<{ data: { id: string; runIds: string[]; totalRuns: number; concurrency: number }; readingContext?:{requested:number;attached:number} }>('/api/jobs', { method: 'POST', body: JSON.stringify(input) });
  const context = integrated() ? researchContext() : undefined;
  if (context) {
    let attached=0;
    // Preserve failures separately: an already-created experiment must not be
    // silently retried or presented as having saved its reading provenance.
    for (const runId of result.data.runIds) {
      try { await request(`/api/runs/${encodeURIComponent(runId)}/artifacts`,{method:'POST',body:JSON.stringify({
        name:'clawos-reading-context.json',type:'json',mimeType:'application/json',content:{
          schema:'clawos.reading-context.v1',domain:context.id,readingPackVersion:'domain-reading.v1',
          sourcePage:'/academy/research#domain-heading',question:context.question,kind:'user_selected_reading_reference',paperReproductionVerified:false,
        }})});attached++; } catch { /* Report partial attachment without duplicating the job. */ }
    }
    result.readingContext={requested:result.data.runIds.length,attached};
  }
  return result;
}

export async function importDataset(name: string, format: ImportedDataset['format'], content: string) {
  return request<{ data: ImportedDataset }>('/api/datasets', { method: 'POST', body: JSON.stringify({ name, format, content }) });
}

export type DatasetSummary=Omit<ImportedDataset,'rows'>;
export async function fetchDatasetPage(page=1) { return request<{data:DatasetSummary[];pagination:{page:number;hasNext:boolean;hasPrevious:boolean}}>('/api/datasets?page='+page+'&pageSize=30&summary=1'); }
export async function fetchDataset(id:string) { return request<{data:ImportedDataset}>('/api/datasets/'+encodeURIComponent(id)); }
export async function fetchVisualization(id:string) { return request<{data:SavedVisualization}>('/api/visualization-specs/'+encodeURIComponent(id)); }

export async function saveVisualization(input: { id?: string; name: string; datasetId?: string; spec: Record<string, unknown>; isPublic?: boolean }) {
  return request<{ data: SavedVisualization }>('/api/visualization-specs', { method: 'POST', body: JSON.stringify(input) });
}

export async function fetchSharedVisualization(token: string) {
  return request<{ data: SavedVisualization }>(`/api/shared/${token}`);
}

export async function createModelAsset(input: { name: string; format: ModelAsset['format']; content: string; resources?: ModelResource[]; metadata?: Record<string, unknown> }) {
  return request<{ data: ModelAsset }>('/api/model-assets', { method: 'POST', body: JSON.stringify(input) });
}

export async function interpretNaturalLanguage(input: { prompt: string; mode: 'experiment' | 'model3d'; currentParams?: ExperimentParams; provider?: string; credentialRef?: string; model?: string }) {
  return request<{ data: StudioPlan | ExperimentAiPlan }>('/api/ai/interpret', { method: 'POST', body: JSON.stringify(input) });
}

export async function fetchStudioTemplates() {
  return request<{ data: Array<{ id: string; name: string; description: string }> }>('/api/studio/templates');
}

export async function fetchStudioGenerations() {
  return request<{ data: StudioGeneration[] }>('/api/studio/generations');
}

export async function createStudioAgentRun(input: { prompt: string; provider: string; credentialRef?: string; model?: string; maxCycles?: number; qualityThreshold?: number; timeoutSeconds?: number }) {
  return request<{ data: StudioAgentRun }>('/api/studio/agent-runs', { method: 'POST', body: JSON.stringify(input) });
}

export function streamStudioAgentRun(id: string, onUpdate: (run: StudioAgentRun) => void, onError: () => void) {
  return streamSse<StudioAgentRun>(`/api/studio/agent-runs/${id}/stream`, 'pipeline', (run, close) => { onUpdate(run); if (['completed', 'failed', 'cancelled'].includes(run.status)) close(); }, onError);
}

export async function fetchText3DProviders() {
  return request<{ data: Text3DProvider[] }>('/api/studio/text-to-3d/providers');
}

export async function createText3DJob(input: { prompt: string; resolution?: number; provider?: string; imageBase64?: string; timeoutSeconds?: number; memoryBudgetMb?: number }) {
  return request<{ data: Text3DJob }>('/api/studio/text-to-3d', { method: 'POST', body: JSON.stringify(input) });
}

export async function cancelStudioAgentRun(id: string) { return request<{ data: StudioAgentRun }>(`/api/studio/agent-runs/${id}/cancel`, { method: 'POST', body: '{}' }); }
export async function cancelText3DJob(id: string) { return request<{ data: Text3DJob }>(`/api/studio/text-to-3d/${id}/cancel`, { method: 'POST', body: '{}' }); }

export function streamText3DJob(id: string, onUpdate: (job: Text3DJob) => void, onError: () => void) {
  return streamSse<Text3DJob>(`/api/studio/text-to-3d/${id}/stream`, 'text3d', (job, close) => { onUpdate(job); if (['completed', 'failed', 'cancelled'].includes(job.status)) close(); }, onError);
}

export async function saveStudioGeneration(input: { id?: string; name: string; prompt: string; provider: string; plan: StudioPlan; assetId?: string }) {
  return request<{ data: StudioGeneration }>('/api/studio/generations', { method: 'POST', body: JSON.stringify(input) });
}

export async function previewSceneCommand(command: string, plan: StudioPlan) {
  return request<{ data: SceneCommandPreview }>('/api/studio/scene-command', { method: 'POST', body: JSON.stringify({ command, plan }) });
}

export async function applySceneOperations(input: { generationId?: string; command?: string; plan: StudioPlan; operations: SceneOperation[] }) {
  return request<{ data: { id: string; generationId: string; version: number; plan: StudioPlan; operations: SceneOperation[] } }>('/api/studio/scenes/apply', { method: 'POST', body: JSON.stringify(input) });
}

export async function sendStudioFeedback(id: string, rating: number, comment = '') {
  return request<{ ok: boolean }>(`/api/studio/generations/${id}/feedback`, { method: 'POST', body: JSON.stringify({ rating, comment }) });
}

export async function compileStudioMesh(plan: StudioPlan, quality: 'standard' | 'high' | 'ultra') {
  return request<{ data: ModelAsset }>('/api/studio/mesh', { method: 'POST', body: JSON.stringify({ plan, quality }) });
}

export async function exportStudioAsset(plan: StudioPlan, quality: 'standard' | 'high' | 'ultra', format: 'obj' | 'gltf' | 'glb') {
  return request<{ data: ModelAsset }>('/api/studio/export', { method: 'POST', body: JSON.stringify({ plan, quality, format }) });
}

export async function saveParameterSnapshot(input: { name: string; runId?: string; params: ExperimentParams }) {
  return request<{ data: { id: string; name: string; runId?: string; params: ExperimentParams; createdAt: string } }>('/api/parameter-snapshots', { method: 'POST', body: JSON.stringify(input) });
}

export async function fetchParameterSnapshots() {
  return request<{ data: Array<{ id: string; name: string; runId?: string; params: ExperimentParams; createdAt: string }> }>('/api/parameter-snapshots');
}

export async function fetchModelAssets(filters: { q?: string; projectId?: string; stage?: string; folder?: string; tag?: string; archived?: boolean; deleted?: boolean } = {}) {
  const query = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== '') query.set(key, String(value)); });
  return request<{ data: ModelAsset[] }>(`/api/model-assets${query.size ? `?${query}` : ''}`);
}

export async function fetchModelAsset(id: string, includeContent = true) {
  return request<{ data: ModelAsset }>(`/api/model-assets/${id}${includeContent?'':'?content=false'}`);
}

export async function fetchAssetProjects() { return request<{ data: AssetProject[] }>('/api/asset-projects'); }
export async function createAssetProject(name: string, description = '') { return request<{ data: AssetProject }>('/api/asset-projects', { method: 'POST', body: JSON.stringify({ name, description }) }); }
export async function updateModelAsset(id: string, patch: { name?: string; projectId?: string; folder?: string; stage?: string; tags?: string[]; thumbnailBase64?: string }) { return request<{ data: ModelAsset }>(`/api/model-assets/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }); }
export async function batchUpdateModelAssets(ids: string[], patch: { projectId?: string; folder?: string; stage?: string; tags?: string[] }, renamePrefix?: string) { return request<{ data: { updated: string[]; count: number } }>('/api/model-assets/batch', { method: 'POST', body: JSON.stringify({ ids, patch, renamePrefix }) }); }
export async function archiveModelAsset(id: string, archive = true) { return request<{ data: ModelAsset }>(`/api/model-assets/${id}/${archive ? 'archive' : 'restore'}`, { method: 'POST', body: '{}' }); }
export async function deleteModelAsset(id: string, purge = false) { return request<{ data: { id: string; deletedAt?: string; purged?: boolean } }>(`/api/model-assets/${id}${purge ? '?purge=true' : ''}`, { method: 'DELETE' }); }
export async function garbageCollectAssets(graceHours = 168) { return request<{ data: { purged: string[]; protected: string[]; graceHours: number } }>('/api/model-assets/garbage-collect', { method: 'POST', body: JSON.stringify({ graceHours }) }); }
export async function createAssetComponent(id: string, type: AssetComponent['type'], content: unknown, metadata: Record<string, unknown> = {}) { return request<{ data: AssetComponent }>(`/api/model-assets/${id}/components`, { method: 'POST', body: JSON.stringify({ type, content, metadata }) }); }
export async function createAssetRelease(id: string, status: AssetRelease['status'], reviewer = '', note = '') { return request<{ data: AssetRelease }>(`/api/model-assets/${id}/releases`, { method: 'POST', body: JSON.stringify({ status, reviewer, note }) }); }
export async function linkRunAsset(runId: string, input: { assetId: string; sceneId?: string; role: 'input' | 'checkpoint' | 'output' | 'baseline' | 'overlay' | 'simulation'; step?: number; metadata?: Record<string, unknown> }) { return request<{ data: { id: string } }>(`/api/runs/${runId}/assets`, { method: 'POST', body: JSON.stringify(input) }); }
export async function fetchRunTimeline(runId: string) { return request<{ data: RunTimeline }>(`/api/runs/${runId}/timeline`); }

export async function fetchModelScenes() { return request<{ data: ModelScene[] }>('/api/model-scenes'); }
export async function fetchModelScene(id: string, versions = false) { return request<{ data: ModelScene }>(`/api/model-scenes/${id}${versions ? '/versions' : ''}`); }
export async function importModelScene(assetId: string, name?: string) { return request<{ data: ModelScene }>(`/api/model-assets/${assetId}/scene`, { method: 'POST', body: JSON.stringify({ name }) }); }
export async function interpretModelSceneCommand(sceneId: string, command: string) { return request<{ data: AssetSceneCommand }>(`/api/model-scenes/${sceneId}/command`, { method: 'POST', body: JSON.stringify({ command }) }); }
export async function previewModelSceneOperations(sceneId: string, operations: SceneOperation[]) { return request<{ data: { sceneId: string; operations: SceneOperation[]; scene: ModelSceneManifest; quality: ModelQualityReport; modifierStats: Array<Record<string, unknown>>; asset: { name: string; format: ModelAsset['format']; base64: string; resources: ModelResource[] } } }>(`/api/model-scenes/${sceneId}/preview`, { method: 'POST', body: JSON.stringify({ operations }) }); }
export async function applyModelSceneOperations(sceneId: string, operations: SceneOperation[], command = 'manual edit', replace = false) { return request<{ data: ModelScene }>(`/api/model-scenes/${sceneId}/operations`, { method: 'POST', body: JSON.stringify({ operations, command, replace }) }); }
export async function queueModelSceneOperations(sceneId: string, operations: SceneOperation[], command = 'background mesh operation') { return request<{ data: ModelOperationJob }>(`/api/model-scenes/${sceneId}/operations/async`, { method: 'POST', body: JSON.stringify({ operations, command }) }); }
export async function fetchModelOperationJob(id: string) { return request<{ data: ModelOperationJob }>(`/api/model-operation-jobs/${id}`); }
export async function cancelModelOperationJob(id: string) { return request<{ data: ModelOperationJob }>(`/api/model-operation-jobs/${id}/cancel`, { method: 'POST', body: '{}' }); }
export async function restoreModelSceneVersion(sceneId: string, version: number) { return request<{ data: ModelScene }>(`/api/model-scenes/${sceneId}/restore`, { method: 'POST', body: JSON.stringify({ version }) }); }
export async function repairModelScene(sceneId: string, decimate = false, targetFaces = 50000) { return request<{ data: ModelScene }>(`/api/model-scenes/${sceneId}/repair`, { method: 'POST', body: JSON.stringify({ decimate, targetFaces }) }); }
export async function exportModelScene(sceneId: string) { return request<{ data: ModelAsset }>(`/api/model-scenes/${sceneId}/export`, { method: 'POST', body: '{}' }); }
export async function createSceneAgentRun(sceneId: string, input: { command: string; provider?: string; model?: string; maxCycles?: number }) { return request<{ data: SceneAgentRun }>(`/api/model-scenes/${sceneId}/agent-runs`, { method: 'POST', body: JSON.stringify(input) }); }
export async function fetchSceneAgentRun(id: string) { return request<{ data: SceneAgentRun }>(`/api/scene-agent-runs/${id}`); }
export async function sceneAgentAction(id: string, action: 'confirm'|'apply'|'reject'|'cancel') { return request<{ data: SceneAgentRun }>(`/api/scene-agent-runs/${id}/${action}`, { method: 'POST', body: '{}' }); }
export function streamSceneAgentRun(id: string, onUpdate: (run: SceneAgentRun) => void, onError: () => void) { return streamSse<SceneAgentRun>(`/api/scene-agent-runs/${id}/stream`, 'scene-agent', (run, close) => { onUpdate(run); if (['ready','completed','awaiting-confirmation','rejected','failed','cancelled','stale'].includes(run.status)) close(); }, onError); }
export async function fetchGeometryProviders() { return request<{ data: GeometryProvider[] }>('/api/geometry/providers'); }
export async function createSceneGeometryJob(sceneId: string, input: { provider: string; operation: Record<string, unknown>; priority?: number; timeoutSeconds?: number; checkpointKey?: string }) { return request<{ data: GeometryJob }>(`/api/model-scenes/${sceneId}/geometry-jobs`, { method: 'POST', body: JSON.stringify(input) }); }
export async function createAssetGeometryJob(assetId: string, input: { provider: string; operation?: Record<string, unknown>; outputFormat?: ModelAsset['format']; priority?: number; timeoutSeconds?: number; checkpointKey?: string }) { return request<{ data: GeometryJob }>(`/api/model-assets/${assetId}/geometry-jobs`, { method: 'POST', body: JSON.stringify(input) }); }
export async function fetchGeometryJob(id: string) { return request<{ data: GeometryJob }>(`/api/geometry-jobs/${id}`); }
export async function cancelGeometryJob(id: string) { return request<{ data: GeometryJob }>(`/api/geometry-jobs/${id}/cancel`, { method: 'POST', body: '{}' }); }

export async function logRemoteMetric(runId: string, point: ExperimentRun['metrics'][number]) {
  return request(`/api/runs/${runId}/metrics`, { method: 'POST', body: JSON.stringify(point) });
}

export async function logRemoteEvent(runId: string, message: string, level = 'info') {
  return request(`/api/runs/${runId}/events`, { method: 'POST', body: JSON.stringify({ message, level }) });
}

export async function logRemoteArtifact(runId: string, name: string, type: string, content: unknown, step?: number) {
  return request(`/api/runs/${runId}/artifacts`, { method: 'POST', body: JSON.stringify({ name, type, content, step, mimeType: 'application/json' }) });
}

export async function finishRemoteRun(runId: string, message = '训练正常结束') {
  return request(`/api/runs/${runId}/finish`, { method: 'POST', body: JSON.stringify({ message }) });
}

export async function failRemoteRun(runId: string, error: string) {
  return request(`/api/runs/${runId}/fail`, { method: 'POST', body: JSON.stringify({ error }) });
}

export async function stopRemoteRun(runId: string) {
  return request(`/api/runs/${runId}/stop`, { method: 'POST', body: JSON.stringify({ message: '实验已由用户停止' }) });
}

export function subscribeToRun(runId: string, onRun: (run: ExperimentRun) => void) {
  return streamSse<ApiRun>(`/api/runs/${runId}/stream`, 'run', (run) => onRun(normalizeRun(run)));
}
