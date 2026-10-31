import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ScenarioWorkbench } from './ScenarioWorkbench';
import { createScenePlan, defaultSceneConfig, exportScenePlan, fetchSceneAssets, fetchScenePlan, fetchScenePlans, fetchScenePreviewAsset, type ScenePlan } from '../scenarioApi';
import type { FailureCase } from '../evaluationApi';
import type { ModelAsset } from '../api';

vi.mock('../scenarioApi', async (original) => ({ ...await original<typeof import('../scenarioApi')>(),
  createScenePlan: vi.fn(), exportScenePlan: vi.fn(), fetchSceneAssets: vi.fn(), fetchScenePlan: vi.fn(), fetchScenePlans: vi.fn(), fetchScenePreviewAsset: vi.fn(),
}));
vi.mock('./ScenePlanPreview', () => ({ default: ({ variant }: { variant: { index: number } }) => <div data-testid="scene-preview">变体 index {variant.index}</div> }));
vi.mock('./SynthesisWorkbench', () => ({ SynthesisWorkbench: () => null }));
const pagination = { page: 1, pageSize: 25, total: 1, pages: 1, hasNext: false, hasPrevious: false };
const failure: FailureCase = { sampleId: 'bad-1', label: 'gear', predictedLabel: 'bolt', confidence: .9, correct: false, conditions: { angle: 'side' }, imageUri: null, contentHash: null };
const config = defaultSceneConfig();
const plan: ScenePlan = {
  id: 'scenario-1', name: '反光侧视角', reportId: 'report', assetId: 'asset-1', parentId: null, version: 1, digest: 'a'.repeat(64), createdAt: '2026-10-07', variantCount: 2,
  source: { reportId: 'report', reportDigest: 'r', testSetId: 'set', testSetDigest: 's', runId: 'run', sampleId: 'bad-1', label: 'gear', predictedLabel: 'bolt', conditions: { angle: 'side' }, association: 'user-confirmed' },
  asset: { id: 'asset-1', name: '零件模型', version: 2, format: 'obj', sha256: 'b'.repeat(64), byteSize: 128 },
  manifest: { schemaVersion: 'clawvision.scene-plan/1', kind: 'unrendered-scene-plan', sampling: 'sha256-counter-v1', source: {} as ScenePlan['source'], asset: {} as ScenePlan['asset'], conventions: {}, config,
    variants: [{ index: 0, parameters: Object.fromEntries(Object.keys(config.ranges).map((key) => [key, 1])) as ScenePlan['manifest']['variants'][0]['parameters'] },
      { index: 1, parameters: Object.fromEntries(Object.keys(config.ranges).map((key) => [key, 2])) as ScenePlan['manifest']['variants'][0]['parameters'] }] },
};
plan.manifest.source = plan.source; plan.manifest.asset = plan.asset;
const asset: ModelAsset = { id: 'asset-1', name: '零件模型', format: 'obj', version: 2, folder: '/', stage: 'raw', tags: [], metadata: {}, createdAt: 'now', updatedAt: 'now' };

describe('failure-driven 3D scene workbench', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchScenePlans).mockResolvedValue({ data: [plan], pagination });
    vi.mocked(fetchScenePlan).mockResolvedValue({ data: plan });
    vi.mocked(fetchSceneAssets).mockResolvedValue({ data: [asset], pagination });
    vi.mocked(createScenePlan).mockResolvedValue({ data: plan });
    vi.mocked(exportScenePlan).mockResolvedValue({ data: plan });
    vi.mocked(fetchScenePreviewAsset).mockResolvedValue({ data: { assetId: 'asset-1', format: 'obj', sha256: plan.asset.sha256, base64: '' } });
  });
  const selectPlan = async () => fireEvent.click(await screen.findByRole('button', { name: '反光侧视角 · v1 bad-1 → 零件模型 v2 · 2 个变体' }));

  it('gives viewers saved parameters and lazy verified previews without write controls', async () => {
    render(<ScenarioWorkbench reportId="report" canWrite={false} />);
    await selectPlan();
    await screen.findByRole('button', { name: '加载 3D 预览' });
    expect(fetchSceneAssets).not.toHaveBeenCalled(); expect(fetchScenePreviewAsset).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('场景计划名称')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '修改并创建新版本' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '加载 3D 预览' }));
    expect(await screen.findByTestId('scene-preview')).toHaveTextContent('index 0');
    fireEvent.change(screen.getByLabelText('场景预览变体'), { target: { value: '1' } });
    expect(screen.getByTestId('scene-preview')).toHaveTextContent('index 1');
    fireEvent.click(screen.getByRole('button', { name: '关闭 3D 预览' }));
    expect(screen.queryByTestId('scene-preview')).not.toBeInTheDocument();
  });

  it('requires an explicit asset-label confirmation and saves the selected failure and seed', async () => {
    render(<ScenarioWorkbench reportId="report" failure={failure} canWrite />);
    const select = await screen.findByRole('option', { name: /零件模型.*OBJ/ });
    fireEvent.change(select.closest('select')!, { target: { value: 'asset-1' } });
    expect(screen.getByRole('button', { name: '保存场景计划' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('场景随机种子'), { target: { value: '123' } });
    fireEvent.click(screen.getByRole('checkbox', { name: '我确认所选资产代表真实标签“gear”' }));
    fireEvent.click(screen.getByRole('button', { name: '保存场景计划' }));
    await waitFor(() => expect(createScenePlan).toHaveBeenCalledWith(expect.objectContaining({ reportId: 'report', sampleId: 'bad-1', assetId: 'asset-1', label: 'gear', config: expect.objectContaining({ seed: 123 }) })));
    expect(await screen.findByText(/场景 v1 已保存/)).toBeVisible();
  });

  it('creates a new version from saved parameters and requires renewed confirmation', async () => {
    render(<ScenarioWorkbench reportId="report" canWrite />);
    await selectPlan(); fireEvent.click(await screen.findByRole('button', { name: '修改并创建新版本' }));
    await screen.findByRole('option', { name: /零件模型.*OBJ/ });
    expect(screen.getByRole('button', { name: '保存场景新版本' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('相机方位角（°）最小'), { target: { value: '-90' } });
    fireEvent.click(screen.getByRole('checkbox')); fireEvent.click(screen.getByRole('button', { name: '保存场景新版本' }));
    await waitFor(() => expect(createScenePlan).toHaveBeenCalledWith(expect.objectContaining({ parentId: plan.id, config: expect.objectContaining({ ranges: expect.objectContaining({ cameraAzimuth: [-90, 40] }) }) })));
    expect(plan.manifest.config.ranges.cameraAzimuth).toEqual([-40, 40]);
  });

  it('recovers from list failures and shows asset hash mismatch errors explicitly', async () => {
    vi.mocked(fetchScenePlans).mockRejectedValueOnce(new Error('场景列表读取失败'));
    vi.mocked(fetchScenePreviewAsset).mockRejectedValueOnce(new Error('固定资产哈希不匹配'));
    render(<ScenarioWorkbench reportId="report" canWrite={false} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('场景列表读取失败');
    fireEvent.click(screen.getByRole('button', { name: '重试场景加载' })); await selectPlan();
    fireEvent.click(await screen.findByRole('button', { name: '加载 3D 预览' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('固定资产哈希不匹配');
    expect(screen.queryByTestId('scene-preview')).not.toBeInTheDocument();
  });
});
