import { afterEach, describe, expect, it, vi } from 'vitest';
import { applyRunDelta, fetchRunPage, normalizeRun, subscribeToRunChanges, type RunDelta } from './api';
import { defaultParams, nextMetric } from './domain';

const metadata = { id: 'run', name: 'training', status: 'running' as const, params: defaultParams, createdAt: 'today', revision: 8 };
const snapshot = () => ({ ...normalizeRun({ ...metadata, cursor: 3, metrics: [nextMetric(defaultParams, 1), nextMetric(defaultParams, 9)], logs: ['created'], events: [{ id: 1, message: 'created', level: 'info', created_at: 'today' }] }), detailLoaded: true });
const delta = (cursor = 8): RunDelta => ({ id: 'run', run: metadata, cursor, hasMore: false, metrics: [], events: [], artifacts: [], removedMetrics: [], removedEvents: [], removedArtifacts: [] });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('Run incremental contracts', () => {
  it('corrects an old step, orders out-of-order points and deduplicates replays', () => {
    const update = { ...delta(), metrics: [{ ...nextMetric(defaultParams, 1), accuracy: .77 }, nextMetric(defaultParams, 4)], events: [{ id: 3, message: 'third', level: 'info', created_at: 'today' }, { id: 2, message: 'second', level: 'info', created_at: 'today' }] };
    const merged = applyRunDelta(snapshot(), update);
    expect(merged.metrics.map((point) => point.step)).toEqual([1, 4, 9]);
    expect(merged.metrics[0].accuracy).toBe(.77);
    expect(merged.logs).toEqual(['created', 'second', 'third']);
    expect(applyRunDelta(merged, update)).toBe(merged);
    expect(applyRunDelta(merged, { ...update, cursor: 4 })).toBe(merged);
  });

  it('applies removals and derives diagnostics from changed artifacts only', () => {
    const matrix = { id: 'matrix', name: 'matrix', type: 'confusion-matrix', mimeType: 'application/json', content: [[3, 1]], createdAt: 'today' };
    const merged = applyRunDelta(snapshot(), { ...delta(4), artifacts: [matrix], hasMore: true });
    // Metadata may refer to a newer revision; only the drained cursor is applied.
    expect(merged.cursor).toBe(4);
    expect(merged.confusion).toEqual([[3, 1]]);
    const removed = applyRunDelta(merged, { ...delta(8), removedMetrics: [1], removedEvents: [1], removedArtifacts: ['matrix'] });
    expect(removed.metrics.map((point) => point.step)).toEqual([9]);
    expect(removed.logs).toEqual([]);
    expect(removed.confusion).toEqual([]);
  });

  it('requests a bounded summary page with global search and cancellation', async () => {
    const response = { data: [{ ...metadata, latestMetric: nextMetric(defaultParams, 9), metricCount: 100, artifactCount: 2 }], pagination: { page: 2, total: 26 }, counts: { running: 26 } };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
    vi.stubGlobal('fetch', fetchMock);
    const page = await fetchRunPage(2, 'earlier run');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/runs?summary=1&page=2&pageSize=25&q=earlier+run');
    expect(page.data[0]).toMatchObject({ detailLoaded: false, metricCount: 100, artifacts: [], logs: [] });
    expect(page.data[0].metrics).toHaveLength(1);
    const controller = new AbortController();
    vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise((_resolve, reject) => init.signal.addEventListener('abort', () => reject(new DOMException('cancelled', 'AbortError'))))));
    const pending = fetchRunPage(1, '', controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('reconnects from the last cursor on EOF and stops reconnecting after cleanup', async () => {
    vi.useFakeTimers();
    const update = { ...delta(5), metrics: [nextMetric(defaultParams, 3)] };
    const bytes = new TextEncoder().encode(`id: 5\nevent: run-delta\ndata: ${JSON.stringify(update)}\n\n`);
    const fetchMock = vi.fn().mockImplementation(async () => new Response(new ReadableStream({ start(controller) { controller.enqueue(bytes.slice(0, 24)); controller.enqueue(bytes.slice(24)); controller.close(); } })));
    vi.stubGlobal('fetch', fetchMock);
    const callback = vi.fn();
    const close = subscribeToRunChanges('run', 3, callback);
    await vi.advanceTimersByTimeAsync(0);
    expect(callback).toHaveBeenCalledWith(update);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock.mock.calls[1][0]).toBe('/api/runs/run/stream?incremental=1&after=5');
    close();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
