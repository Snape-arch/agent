import { useEffect, useRef, useState } from 'react';
import { ApiError, applyRunDelta, fetchRun, fetchRunChanges, fetchRunPage, subscribeToRunChanges, type RunPage } from '../api';
import type { ExperimentRun } from '../domain';

const emptyPage: RunPage = { data: [], pagination: { page: 1, pageSize: 25, total: 0, pages: 0, hasNext: false, hasPrevious: false }, counts: {} };

export function useRunPage(query: string) {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState(emptyPage);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [online, setOnline] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => { setSearch(query.trim()); setPage(1); }, 300);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    setLoading(true);
    const sync = async () => {
      try {
        const next = await fetchRunPage(page, search, controller.signal);
        if (controller.signal.aborted) return;
        // A deleted last page should return to the last available page.
        if (page > Math.max(1, next.pagination.pages)) { setPage(Math.max(1, next.pagination.pages)); return; }
        setResult(next); setError(''); setOnline(true);
      } catch (failure) {
        if (controller.signal.aborted) return;
        setError(failure instanceof Error ? failure.message : '无法加载实验'); setOnline(false);
      } finally {
        if (!controller.signal.aborted) { setLoaded(true); setLoading(false); timer = window.setTimeout(sync, 15_000); }
      }
    };
    void sync();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [page, search, refresh]);
  return { ...result, page, setPage, loaded, loading, searching: query.trim() !== search || loading, error, online, reload: (resetPage = false) => { if (resetPage) setPage(1); setRefresh((value) => value + 1); } };
}

// Cache only viewed Runs. Every active Run resumes from its last applied cursor.
export function useRunDetails(ids: string[], streamId = ids[0]) {
  const cache = useRef(new Map<string, ExperimentRun>());
  const [details, setDetails] = useState<Record<string, ExperimentRun>>({});
  const [error, setError] = useState('');
  const key = JSON.stringify([...new Set(ids.filter(Boolean))].sort());
  useEffect(() => {
    const active = JSON.parse(key) as string[];
    const controller = new AbortController();
    const subscriptions: Array<() => void> = [];
    const retries = new Set<number>();
    const retry = (callback: () => void) => {
      const timer = window.setTimeout(() => { retries.delete(timer); callback(); }, 5000);
      retries.add(timer);
    };
    const publish = (run: ExperimentRun) => {
      cache.current.delete(run.id); cache.current.set(run.id, run);
      if (cache.current.size > 40) {
        for (const id of cache.current.keys()) {
          if (!active.includes(id)) { cache.current.delete(id); if (cache.current.size <= 40) break; }
        }
      }
      setDetails(Object.fromEntries(cache.current));
    };
    setError('');
    for (const id of active) {
      const start = async () => {
        try {
          const run = cache.current.get(id) ?? await fetchRun(id, controller.signal);
          if (controller.signal.aborted) return;
          publish(run);
          if (id === streamId) subscriptions.push(subscribeToRunChanges(id, run.cursor ?? 0, (delta) => {
            if (controller.signal.aborted) return;
            const current = cache.current.get(id);
            if (current) publish(applyRunDelta(current, delta));
            setError('');
          }, () => { if (!controller.signal.aborted) setError('实时连接暂时中断，正在按游标重连'); }));
          else {
            // One SSE per workspace leaves HTTP/1.1 connections available for
            // search, uploads and controls even when comparing ten Runs.
            const poll = async () => {
              try {
                let more = true;
                while (more && !controller.signal.aborted) {
                  const current = cache.current.get(id)!;
                  const delta = await fetchRunChanges(id, current.cursor ?? 0, controller.signal);
                  if (controller.signal.aborted) return;
                  const updated = applyRunDelta(current, delta);
                  if (updated !== current) publish(updated);
                  more = delta.hasMore;
                }
                setError('');
              } catch (failure) {
                if (controller.signal.aborted) return;
                if (failure instanceof ApiError && failure.status === 400) {
                  try {
                    const fresh = await fetchRun(id, controller.signal);
                    if (!controller.signal.aborted) publish(fresh);
                  } catch { if (!controller.signal.aborted) setError('无法重新加载对比数据，正在重试'); }
                } else setError('对比数据暂时无法同步，正在重试');
              } finally {
                if (!controller.signal.aborted) retry(() => { void poll(); });
              }
            };
            void poll();
          }
        } catch (failure) {
          if (!controller.signal.aborted) {
            setError(failure instanceof Error ? failure.message : '无法加载 Run 详情');
            retry(() => { void start(); });
          }
        }
      };
      void start();
    }
    return () => { controller.abort(); subscriptions.forEach((cancel) => cancel()); retries.forEach((timer) => window.clearTimeout(timer)); };
  }, [key, streamId]);
  return { details, error };
}
