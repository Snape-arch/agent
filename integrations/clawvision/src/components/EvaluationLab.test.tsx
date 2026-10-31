import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EvaluationLab } from './EvaluationLab';
import { fetchRunPage } from '../api';
import { compareEvaluations, fetchEvaluation, fetchEvaluations, fetchFailureCases, fetchTestSets, type EvaluationReport, type TestSet } from '../evaluationApi';

vi.mock('./TrainingComparisonWorkbench', () => ({ TrainingComparisonWorkbench: () => null }));
vi.mock('./ScenarioWorkbench', () => ({ ScenarioWorkbench: () => null }));

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), fetchRunPage: vi.fn() }));
vi.mock('../evaluationApi', async (original) => ({ ...await original<typeof import('../evaluationApi')>(),
  fetchTestSets: vi.fn(), fetchEvaluations: vi.fn(), fetchEvaluation: vi.fn(), fetchFailureCases: vi.fn(), compareEvaluations: vi.fn(),
}));
const pagination = { page: 1, pageSize: 25, total: 1, pages: 1, hasNext: false, hasPrevious: false };
const testSet: TestSet = { id: 'fixed', name: '零件测试', task: 'classification', classes: ['A', 'B'], digest: 'a'.repeat(64), sampleCount: 4, datasetVersionId: null, createdAt: '2026-10-07' };
const report = (id: string): EvaluationReport => ({
  id, name: id, runId: id, testSetId: 'fixed', digest: 'b'.repeat(64), createdAt: '2026-10-07',
  provenance: { kind: 'uploaded-predictions', testSetDigest: testSet.digest, datasetVersionId: null, modelArtifact: null, run: { id, name: id, source: 'sdk', status: 'completed', revision: 0, params: {} } },
  summary: { total: 4, correct: 2, errors: 2, accuracy: .5, errorRate: .5, macroF1: .5, classMetrics: [], confusion: [], groups: [{ dimension: 'angle', value: 'front', total: 2, errors: 1, errorRate: .5 }] },
});
const base = report('baseline'), candidate = report('candidate');

describe('visual evaluation workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchTestSets).mockResolvedValue({ data: [testSet], pagination });
    vi.mocked(fetchEvaluations).mockResolvedValue({ data: [base, candidate], pagination: { ...pagination, total: 2 } });
    vi.mocked(fetchEvaluation).mockImplementation(async (id) => ({ data: id === base.id ? base : candidate }));
    vi.mocked(fetchFailureCases).mockResolvedValue({ data: [{ sampleId: 'part-1', label: 'A', predictedLabel: 'B', confidence: .9, correct: false, conditions: { angle: 'front' }, imageUri: null, contentHash: null }], pagination });
    vi.mocked(fetchRunPage).mockResolvedValue({ data: [], pagination: { ...pagination, total: 0 }, counts: {} });
    vi.mocked(compareEvaluations).mockResolvedValue({ data: { baseline: base, candidate, testSetId: 'fixed', accuracyDelta: .25, errorRateDelta: -.25, macroF1Delta: .1, fixed: 2, regressed: 1, bothCorrect: 1, bothWrong: 0, groups: [{ ...candidate.summary.groups[0], baselineErrors: 0, errorRateDelta: .5 }] } });
  });

  it('lets a viewer inspect failures and compare Runs without write controls', async () => {
    render(<EvaluationLab canWrite={false} />);
    expect(await screen.findByText('part-1')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '零件测试 4 个样本 · 2 类' }));
    expect(screen.getByText('part-1')).toBeVisible();
    expect(screen.queryByLabelText('测试集 JSON 文件')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('预测 JSON 文件')).not.toBeInTheDocument();
    expect(fetchRunPage).not.toHaveBeenCalled();
    const rows = screen.getByRole('heading', { name: '3. 评估记录' }).closest('section')!;
    fireEvent.click(within(rows).getAllByRole('button', { name: '设为基线' })[0]);
    fireEvent.click(within(rows).getAllByRole('button', { name: '设为候选' })[1]);
    fireEvent.click(screen.getByRole('button', { name: '比较两个 Run' }));
    const compared = await screen.findByTestId('evaluation-comparison');
    expect(compared).toHaveTextContent('新增退化1');
    expect(compared).toHaveTextContent('+50.0 个百分点');
    expect(compareEvaluations).toHaveBeenCalledWith('baseline', 'candidate');
  });

  it('queries scene slices and prevents comparing two evaluations of the same Run', async () => {
    render(<EvaluationLab canWrite={false} />);
    await screen.findByText('part-1');
    fireEvent.click(screen.getByRole('button', { name: '查看分组' }));
    await waitFor(() => expect(fetchFailureCases).toHaveBeenLastCalledWith('baseline', 1, expect.objectContaining({ dimension: 'angle', value: 'front' }), expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole('button', { name: '清除分组' }));
    const rows = screen.getByRole('heading', { name: '3. 评估记录' }).closest('section')!;
    fireEvent.click(within(rows).getAllByRole('button', { name: '设为基线' })[0]);
    fireEvent.click(within(rows).getAllByRole('button', { name: '设为候选' })[0]);
    expect(screen.getByRole('button', { name: '比较两个 Run' })).toBeDisabled();
  });

  it('shows an explicit load error with retry and keeps prediction upload disabled without a Run', async () => {
    vi.mocked(fetchTestSets).mockRejectedValueOnce(new Error('读取失败'));
    render(<EvaluationLab canWrite />);
    expect(await screen.findByRole('alert')).toHaveTextContent('读取失败');
    expect(screen.getByLabelText('预测 JSON 文件')).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '重试加载' }));
    await screen.findByText('part-1');
    expect(fetchTestSets).toHaveBeenCalledTimes(2);
  });
});
