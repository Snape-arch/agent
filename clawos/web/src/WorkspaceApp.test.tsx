import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkspaceApp } from './App';
import { fetchRun, fetchRunPage, normalizeRun, subscribeToRunChanges, type CurrentUser, type RunPage } from './api';
import { defaultParams } from './domain';

vi.mock('./api', async (original) => ({
  ...await original<typeof import('./api')>(),
  fetchRunPage: vi.fn(),
  fetchRun: vi.fn(),
  subscribeToRunChanges: vi.fn(() => () => {}),
  fetchTrainingProviders: vi.fn(async () => ({ data: [] })),
  fetchParameterSnapshots: vi.fn(async () => ({ data: [] })),
}));
vi.mock('./visualizations/PluginHost', () => ({
  PluginHost: () => <div>Chart</div>,
  PluginGallery: ({ inputs }: { inputs: Array<{ type: string }> }) => <div data-testid="diagnostic-types">{inputs.map((input) => input.type).join(',')}</div>,
}));
vi.mock('./components/ExperimentAssetTimeline', () => ({ ExperimentAssetTimeline: () => <div>Asset timeline</div> }));
vi.mock('./components/AiExperimentCommand', () => ({ AiExperimentCommand: () => null }));

const runPage = (data: RunPage['data'] = []): RunPage => ({ data, pagination: { page: 1, pageSize: 25, total: data.length, pages: data.length ? 1 : 0, hasNext: false, hasPrevious: false }, counts: { completed: data.length } });
const user: CurrentUser = { userId: 'owner', tenantId: 'lab', role: 'owner', scopes: ['*'] };

describe('workspace data provenance', () => {
  beforeEach(() => {
    history.replaceState(null, '', '/#home');
    vi.clearAllMocks();
    vi.mocked(fetchRun).mockImplementation(async (id) => ({ ...normalizeRun({ id, name: id === 'sdk' ? 'SDK run' : 'removed-run', status: 'completed', source: 'sdk', createdAt: '2026-10-02', params: defaultParams, metrics: [], logs: [], cursor: 0 }), detailLoaded: true }));
    vi.mocked(fetchRunPage).mockResolvedValue(runPage());
  });

  it('renders an empty workspace and permits creating its first Run', async () => {
    render(<WorkspaceApp user={user} />);
    await waitFor(() => expect(fetchRunPage).toHaveBeenCalled());
    expect(screen.queryByText('baseline-adamw')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('nav-overview'));
    expect(await screen.findByRole('heading', { name: '尚无实验' })).toBeVisible();
    expect(screen.getByRole('button', { name: '创建真实 Run 并对比' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '锁定当前 Run' })).toBeDisabled();
  });

  it('shows examples only after an explicit action and restores live data on exit', async () => {
    render(<WorkspaceApp user={user} />);
    await screen.findByText('已连接后端');
    fireEvent.click(screen.getByRole('button', { name: '查看演示实验' }));
    expect(screen.getByText(/演示模式：实验指标和诊断产物均为模拟数据/)).toBeVisible();
    fireEvent.click(screen.getByTestId('nav-overview'));
    expect(screen.getByRole('heading', { name: 'baseline-adamw' })).toBeVisible();
    expect(subscribeToRunChanges).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: '创建真实 Run 并对比' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '返回真实工作区' }));
    fireEvent.click(screen.getByTestId('nav-overview'));
    expect(screen.getByRole('heading', { name: '尚无实验' })).toBeVisible();
  });

  it('clears previously loaded Runs when the server returns an empty workspace', async () => {
    const run = normalizeRun({ id: 'removed', name: 'removed-run', status: 'completed', source: 'sdk', createdAt: '2026-10-02', params: defaultParams, metrics: [], logs: [] });
    const timeout = window.setTimeout.bind(window);
    const spy = vi.spyOn(window, 'setTimeout').mockImplementation((handler, delay, ...args) => timeout(handler, delay === 15_000 ? 50 : delay, ...args));
    vi.mocked(fetchRunPage).mockResolvedValueOnce(runPage([run])).mockResolvedValue(runPage());
    render(<WorkspaceApp user={user} />);
    await screen.findByText('已连接后端');
    fireEvent.click(screen.getByTestId('nav-overview'));
    expect(screen.getByRole('heading', { name: 'removed-run' })).toBeVisible();
    expect(await screen.findByRole('heading', { name: '尚无实验' }, { timeout: 3000 })).toBeVisible();
    expect(screen.queryByText('removed-run')).not.toBeInTheDocument();
    spy.mockRestore();
  });

  it('keeps an unavailable backend empty instead of filling it with examples', async () => {
    vi.mocked(fetchRunPage).mockRejectedValue(new Error('Backend is offline'));
    render(<WorkspaceApp user={user} />);
    fireEvent.click(screen.getByTestId('nav-overview'));
    expect(await screen.findByRole('heading', { name: '暂时无法加载实验' })).toBeVisible();
    expect(screen.getByRole('button', { name: '创建真实 Run 并对比' })).toBeDisabled();
    expect(screen.queryByText('baseline-adamw')).not.toBeInTheDocument();
  });

  it('does not render diagnostic charts or a fictional checkpoint for an SDK Run', async () => {
    vi.mocked(fetchRunPage).mockResolvedValue(runPage([normalizeRun({ id: 'sdk', name: 'SDK run', status: 'completed', source: 'sdk', createdAt: '2026-10-02', params: defaultParams, metrics: [], logs: [] })]));
    render(<WorkspaceApp user={user} />);
    await screen.findByText('已连接后端');
    fireEvent.click(screen.getByTestId('nav-more'));
    fireEvent.click(screen.getByRole('button', { name: '模型诊断' }));
    expect(screen.getByText(/此 Run 尚未上传诊断产物/)).toBeVisible();
    expect(screen.getByTestId('diagnostic-types')).toHaveTextContent('json');
    expect(screen.getByTestId('diagnostic-types')).not.toHaveTextContent('confusion-matrix');
    expect(screen.queryByText(/48.2 MB/)).not.toBeInTheDocument();
  });
});
