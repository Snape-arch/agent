import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchRun, fetchRunChanges, fetchRunPage, normalizeRun, subscribeToRunChanges, type RunPage } from '../api';
import { defaultParams } from '../domain';
import { useRunDetails, useRunPage } from './useRuns';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), fetchRunPage: vi.fn(), fetchRun: vi.fn(), fetchRunChanges: vi.fn(), subscribeToRunChanges: vi.fn(() => () => {}) }));
const page = (index: number, id: string): RunPage => ({ data: [{ ...normalizeRun({ id, name: id, params: defaultParams, status: 'running', createdAt: 'today', metrics: [], logs: [] }), detailLoaded: false }], pagination: { page: index, pageSize: 25, total: 50, pages: 2, hasNext: index === 1, hasPrevious: index === 2 }, counts: { running: 50 } });
beforeEach(() => { vi.resetAllMocks(); vi.mocked(subscribeToRunChanges).mockReturnValue(() => {}); });
afterEach(() => vi.useRealTimers());

describe('Run workspace request lifecycle', () => {
  it('ignores late page responses and cancels obsolete requests', async () => {
    let resolveFirst!: (value: RunPage) => void;
    vi.mocked(fetchRunPage).mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; })).mockResolvedValue(page(2, 'second-page'));
    const { result } = renderHook(() => useRunPage(''));
    await waitFor(() => expect(fetchRunPage).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(fetchRunPage).mock.calls[0][2];
    act(() => result.current.setPage(2));
    await waitFor(() => expect(result.current.data[0]?.id).toBe('second-page'));
    expect(signal?.aborted).toBe(true);
    await act(async () => resolveFirst(page(1, 'stale-first-page')));
    expect(result.current.data[0].id).toBe('second-page');
  });

  it('debounces global search, resets its page and polls summaries at a controlled rate', async () => {
    vi.useFakeTimers();
    vi.mocked(fetchRunPage).mockResolvedValue(page(1, 'run'));
    const { result, rerender } = renderHook(({ query }) => useRunPage(query), { initialProps: { query: '' } });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    act(() => result.current.setPage(2));
    await act(async () => {});
    rerender({ query: 'old run' });
    await act(async () => { await vi.advanceTimersByTimeAsync(299); });
    expect(fetchRunPage).toHaveBeenLastCalledWith(2, '', expect.any(AbortSignal));
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetchRunPage).toHaveBeenLastCalledWith(1, 'old run', expect.any(AbortSignal));
    const count = vi.mocked(fetchRunPage).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(14_999); });
    expect(fetchRunPage).toHaveBeenCalledTimes(count);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetchRunPage).toHaveBeenCalledTimes(count + 1);
  });

  it('loads details only on demand, resumes cached cursors and releases subscriptions', async () => {
    const cancel = vi.fn();
    vi.mocked(subscribeToRunChanges).mockReturnValue(cancel);
    vi.mocked(fetchRun).mockImplementation(async (id) => ({ ...page(1, id).data[0], cursor: 7, detailLoaded: true }));
    const { result, rerender, unmount } = renderHook(({ ids }) => useRunDetails(ids), { initialProps: { ids: [] as string[] } });
    expect(fetchRun).not.toHaveBeenCalled();
    rerender({ ids: ['custom:run'] });
    await waitFor(() => expect(result.current.details['custom:run']?.cursor).toBe(7));
    expect(subscribeToRunChanges).toHaveBeenCalledWith('custom:run', 7, expect.any(Function), expect.any(Function));
    rerender({ ids: [] });
    expect(cancel).toHaveBeenCalledTimes(1);
    rerender({ ids: ['custom:run'] });
    await waitFor(() => expect(subscribeToRunChanges).toHaveBeenCalledTimes(2));
    expect(fetchRun).toHaveBeenCalledTimes(1);
    unmount();
    expect(cancel).toHaveBeenCalledTimes(2);
  });

  it('compares ten Runs with one SSE and bounded cursor polling for the others', async () => {
    const ids = Array.from({ length: 10 }, (_, index) => `run-${index}`);
    vi.mocked(fetchRun).mockImplementation(async (id) => ({ ...page(1, id).data[0], cursor: 7, detailLoaded: true }));
    vi.mocked(fetchRunChanges).mockImplementation(async (id, cursor) => ({ id, run: page(1, id).data[0], cursor, hasMore: false, metrics: [], events: [], artifacts: [], removedMetrics: [], removedEvents: [], removedArtifacts: [] }));
    const { result, unmount } = renderHook(() => useRunDetails(ids, 'run-5'));
    await waitFor(() => expect(Object.keys(result.current.details)).toHaveLength(10));
    expect(subscribeToRunChanges).toHaveBeenCalledTimes(1);
    expect(subscribeToRunChanges).toHaveBeenCalledWith('run-5', 7, expect.any(Function), expect.any(Function));
    expect(fetchRunChanges).toHaveBeenCalledTimes(9);
    unmount();
    expect(vi.mocked(fetchRunChanges).mock.calls.every((call) => call[2]?.aborted)).toBe(true);
  });
});
