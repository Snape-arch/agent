"""Authenticated resumable SSE snapshots, compatible with multiple workers."""
import asyncio
import json
import time
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool


def document_delta(previous, current):
    old = {b['id']: b for b in previous['blocks']} if previous else {}
    return dict(id=current['id'], version=current['version'], role=current.get('role'),
                title=current['title'], context=current.get('context', ''), updated_at=current['updated_at'],
                blocks=[b for b in current['blocks'] if old.get(b['id']) != b],
                order=[b['id'] for b in current['blocks']],
                removed=[bid for bid in old if bid not in {b['id'] for b in current['blocks']}])


def event(name, data, version=None):
    return (('id: '+str(version)+'\n') if version is not None else '') + 'event: '+name+'\ndata: '+json.dumps(data,ensure_ascii=False,separators=(',', ':'))+'\n\n'


async def document_events(request, read, state, since=0, interval=.6, cursors=None):
    previous = None
    seen = since
    last_presence = 0
    while not await request.is_disconnected():
        try:
            # read always revalidates session and grant even when the version is unchanged.
            current = await run_in_threadpool(read, seen)
            if current is not None:
                if current['version'] != seen:
                    yield event('document', document_delta(previous,current), current['version'])
                previous, seen = current, current['version']
            now = time.monotonic()
            if cursors: yield event('cursors',await run_in_threadpool(cursors))
            if state and now-last_presence >= 3:
                yield event('presence', await run_in_threadpool(state))
                last_presence = now
            yield event('ready', dict(version=seen)) if previous is None else ': heartbeat\n\n'
        except HTTPException as exc:
            yield event('denied', dict(status=exc.status_code, message=exc.detail))
            return
        await asyncio.sleep(interval)
