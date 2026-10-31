import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, cancelText3DJob, fetchCurrentUser, fetchRuns, normalizeRun, requestBlob, setApiToken } from './api';
import { defaultParams, type RunArtifact } from './domain';

describe('API failure contracts', () => {
  beforeEach(() => vi.unstubAllGlobals());

  it('classifies a disconnected backend as offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(fetchRuns()).rejects.toMatchObject({ name: 'ApiError', kind: 'offline' });
  });

  it('aborts and classifies timed out requests', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    })));
    const pending = fetchRuns();
    const assertion = expect(pending).rejects.toMatchObject({ kind: 'timeout' });
    await vi.advanceTimersByTimeAsync(15_001);
    await assertion;
    vi.useRealTimers();
  });

  it('preserves permission-denied status and server detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'researcher role required' }), { status: 403 })));
    await expect(fetchCurrentUser()).rejects.toMatchObject({ kind: 'http', status: 403, message: 'researcher role required' });
  });

  it('sends authenticated cancellation requests', async () => {
    setApiToken('secret');
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { status: 'cancelled' } }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await cancelText3DJob('job-1');
    expect(fetchMock).toHaveBeenCalledWith('/api/studio/text-to-3d/job-1/cancel', expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ Authorization: 'Bearer secret' }) }));
  });

  it('exposes errors as a stable typed class', () => {
    expect(new ApiError('denied', 'http', 403)).toMatchObject({ kind: 'http', status: 403 });
  });

  it('authenticates binary downloads and keeps HTTP errors readable', async () => {
    setApiToken('binary-secret');
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response('PNG bytes', { headers: { 'Content-Type': 'image/png' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'synthetic artifact hash changed' }), { status: 409 }));
    vi.stubGlobal('fetch', fetchMock);
    const blob = await requestBlob('/api/evaluation/synthesis/job/frames/0/image');
    expect(blob.type).toBe('image/png'); expect(blob.size).toBe(9);
    expect(fetchMock).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer binary-secret' }) }));
    await expect(requestBlob('/api/evaluation/synthesis/job/export')).rejects.toMatchObject({ status: 409, message: 'synthetic artifact hash changed' });
  });
});

describe('real Run diagnostic data', () => {
  const run = { id: 'sdk-run', name: 'SDK training', status: 'completed' as const, source: 'sdk', params: defaultParams, createdAt: '2026-10-02', metrics: [], logs: [] };

  it('keeps missing diagnostics empty, including after a refresh', async () => {
    expect(normalizeRun(run)).toMatchObject({ confusion: [], samples: [], embedding: [], artifacts: [] });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: [run] }))));
    expect(await fetchRuns()).toEqual([normalizeRun(run)]);
  });

  it('uses only uploaded diagnostics and leaves other diagnostics absent', () => {
    const artifact: RunArtifact = { id: 'matrix', name: 'matrix', type: 'confusion-matrix', mimeType: 'application/json', content: [[3, 1], [0, 4]], createdAt: run.createdAt };
    expect(normalizeRun({ ...run, artifacts: [artifact] })).toMatchObject({ confusion: artifact.content, samples: [], embedding: [] });
  });
});
