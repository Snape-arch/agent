"""Opt-in public-source smoke / isolated UI preview. Never opens the daily DB."""
import argparse
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.research_watch import ResearchWatch, ResearchWatchWorker
from services.research_watch_sources import WatchSources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Explicitly query the public Crossref/arXiv APIs')
    parser.add_argument('--preview-port', type=int, default=0)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.live:
        now = time.time(); source = WatchSources(); report = {'kind': 'public_metadata_smoke', 'started': now, 'sources': {}}
        with tempfile.TemporaryDirectory(dir=root) as td:
            store = MemoryStore(str(Path(td)/'isolated.db'))
            for name in ('crossref', 'arxiv'):
                try:
                    result = source.page(name, 'retrieval augmented generation', now-30*86400, now, size=5)
                    report['sources'][name] = dict(ok=True, count=len(result['rows']), window_complete=result['complete'])
                    (root/f'{name}-public-page.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                    # Replay the captured page through the actual durable chain, twice.
                    class Replay:
                        def page(self, *_):
                            return dict(result, cursor='', complete=True)
                    watch = ResearchWatch(store, Replay(), source_interval=0)
                    sid = watch.create('local-user', dict(name='Public source smoke '+name, query='retrieval augmented generation',
                        directions=[dict(name='RAG', terms=['retrieval', 'generation'])], sources=[name]))['id']
                    first = watch.tick(1)
                    watch.action('local-user', sid, 'collect'); second = watch.tick(1)
                    if first[0].get('error') or second[0].get('error') or second[0]['new_count'] != 0:
                        raise AssertionError('public page replay failed')
                    report['sources'][name].update(first=first, replay=second, snapshots_verified=True,
                        boundary='Only this captured page was replayed; the real provider window may remain incomplete.')
                    for item in watch.feed('local-user', sid)['items']:
                        e = item['summary']['evidence']; snapshot = watch.snapshot('local-user', e['snapshot_id'])
                        if snapshot['paper'][e['field']][e['start']:e['end']] != e['quote'] or snapshot['hash'] != e['content_sha256']:
                            raise AssertionError('source extract mismatch')
                except Exception as exc:
                    report['sources'][name] = dict(ok=False, error=type(exc).__name__, http_status=getattr(exc, 'code', None))
        report['duration_seconds'] = round(time.time()-now, 3)
        (root/'live-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        return
    if not 1024 <= args.preview_port <= 65535:
        parser.error('Set --live or --preview-port (1024..65535)')
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    from services.research_watch_api import research_watch_router
    database = root/'preview.db'
    if database.exists():
        raise SystemExit('Preview output must be new; do not reuse prior evidence')
    store = MemoryStore(str(database))
    class Fixture:
        def page(self, source, query, *_):
            return dict(rows=[dict(title='[人工验收样例] Retrieval evidence study', doi='10.9999/clawos-fixture',
                authors=['Synthetic Fixture'], abstract='This is an artificial UI acceptance record. It does not establish research or teaching effectiveness.',
                published='2026-10-01', url='https://example.org/research-fixture', categories=['cs.IR'], source_id='fixture')], cursor='', complete=True)
    service = ResearchWatch(store, Fixture(), source_interval=0); worker = ResearchWatchWorker(service)
    class LocalIdentity:
        def identity(self, request):
            if request.client.host != '127.0.0.1' or request.headers.get('authorization') or request.headers.get('x-forwarded-for'):
                raise HTTPException(401, 'isolated local preview only')
            return {'id': 'local-user'}
    @asynccontextmanager
    async def lifespan(app):
        worker.start()
        yield
        await worker.close()
    app = FastAPI(lifespan=lifespan)
    static = Path(__file__).resolve().parents[1]/'static'
    app.include_router(research_watch_router(lambda: service, LocalIdentity,
        lambda: dict(running=bool(worker.task and not worker.task.done()), last_error='', fixture=True)))
    @app.get('/academy/research')
    def preview():
        return FileResponse(static/'academy-research.html')
    app.mount('/assets', StaticFiles(directory=static/'assets'), name='assets')
    print('ISOLATED FIXTURE PREVIEW', args.preview_port, flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.preview_port, access_log=False)


if __name__ == '__main__':
    main()
