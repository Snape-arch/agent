import { request, type ModelAsset } from './api';
import type { EvaluationPage } from './evaluationApi';

export const sceneParameters = {
  cameraAzimuth: { label: '相机方位角（°）', min: -180, max: 180, initial: [-40, 40] },
  cameraElevation: { label: '相机仰角（°）', min: -80, max: 80, initial: [10, 40] },
  cameraDistance: { label: '相机距离（模型半径）', min: 1.5, max: 10, initial: [3, 4] },
  lightAzimuth: { label: '主光方位角（°）', min: -180, max: 180, initial: [-60, 60] },
  lightElevation: { label: '主光仰角（°）', min: -80, max: 80, initial: [20, 70] },
  lightIntensity: { label: '主光强度', min: 0, max: 10, initial: [1, 3] },
  roughness: { label: '表面粗糙度', min: 0, max: 1, initial: [.2, .8] },
  metalness: { label: '金属度', min: 0, max: 1, initial: [0, .7] },
  occluderSize: { label: '遮挡块边长（模型半径）', min: 0, max: 1.5, initial: [0, .5] },
} as const;
export type SceneParameter = keyof typeof sceneParameters;
export interface SceneConfig {
  seed: number; count: number; ranges: Record<SceneParameter, [number, number]>; materialColor: string; background: string;
}
export const defaultSceneConfig = (): SceneConfig => ({ seed: 42, count: 12, materialColor: '#7cf7c8', background: '#152620',
  ranges: Object.fromEntries(Object.entries(sceneParameters).map(([key, value]) => [key, [...value.initial]])) as SceneConfig['ranges'] });
export interface SceneSource {
  reportId: string; reportDigest: string; testSetId: string; testSetDigest: string; runId: string;
  sampleId: string; label: string; predictedLabel: string; conditions: Record<string, string>; association: 'user-confirmed';
}
export interface SceneAsset { id: string; name: string; version: number; format: 'glb' | 'obj' | 'stl'; sha256: string; byteSize: number }
export interface SceneVariant { index: number; parameters: Record<SceneParameter, number> }
export interface SceneSummary {
  id: string; name: string; reportId: string; assetId: string; parentId: string | null; version: number; digest: string;
  createdAt: string; source: SceneSource; asset: SceneAsset; variantCount: number;
}
export interface ScenePlan extends SceneSummary {
  manifest: { schemaVersion: 'clawvision.scene-plan/1'; kind: 'unrendered-scene-plan'; sampling: string;
    source: SceneSource; asset: SceneAsset; conventions: Record<string, unknown>; config: SceneConfig; variants: SceneVariant[] };
}
export interface ScenePlanInput { name: string; reportId: string; sampleId: string; assetId: string; label: string; config: SceneConfig; parentId?: string }
export interface ScenePreviewAsset { assetId: string; format: SceneAsset['format']; sha256: string; base64: string }
const root = '/api/evaluation/scenarios';
export function fetchSceneAssets(page = 1, search = '', signal?: AbortSignal) {
  return request<EvaluationPage<ModelAsset>>(`/api/model-assets?${new URLSearchParams({ page: String(page), pageSize: '25', q: search })}`, { signal });
}
export function fetchScenePlans(reportId: string, page = 1, signal?: AbortSignal) {
  return request<EvaluationPage<SceneSummary>>(`${root}?${new URLSearchParams({ reportId, page: String(page), pageSize: '25' })}`, { signal });
}
export function fetchScenePlan(id: string, signal?: AbortSignal) { return request<{ data: ScenePlan }>(`${root}/${encodeURIComponent(id)}`, { signal }); }
export function exportScenePlan(id: string) { return request<{ data: ScenePlan }>(`${root}/${encodeURIComponent(id)}/export`); }
export function fetchScenePreviewAsset(id: string, signal?: AbortSignal) { return request<{ data: ScenePreviewAsset }>(`${root}/${encodeURIComponent(id)}/asset`, { signal, timeoutMs: 60_000 }); }
export function createScenePlan(input: ScenePlanInput) { return request<{ data: ScenePlan }>(root, { method: 'POST', body: JSON.stringify(input), timeoutMs: 60_000 }); }
