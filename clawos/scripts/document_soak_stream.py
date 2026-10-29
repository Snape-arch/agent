"""Frame-boundary SSE reconnects and bounded, credential-free diagnostics."""
import asyncio
import json
from pathlib import Path
import time
import traceback


class UnexpectedStreamEnd(RuntimeError):
    pass


def exception_evidence(exc):
    """Keep types/codes/stack locations, never exception messages or locals."""
    chain, seen = [], set()
    while exc is not None and id(exc) not in seen and len(chain) < 8:
        seen.add(id(exc))
        item = dict(type=type(exc).__name__, frames=[
            dict(file=Path(frame.filename).name, line=frame.lineno, function=frame.name)
            for frame in traceback.extract_tb(exc.__traceback__)[-12:]])
        for name in ('errno', 'winerror'):
            value = getattr(exc, name, None)
            if type(value) is int:
                item[name] = value
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if type(status) is int:
            item['http_status'] = status
        chain.append(item)
        exc = exc.__cause__ or exc.__context__
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return dict(chain=chain, task_cancelling=task.cancelling() if task else 0)


async def read_attempt(client, path, since, reconnect_seconds, end_deadline,
                       stopped, on_event, state, load_started, clock=time.monotonic):
    """Close a healthy response only between complete frames; never cancel its read.

    A real transport error, premature EOF, malformed event or HTTP denial always
    propagates. The client's read timeout and the external per-client coverage
    guard remain active if no complete frame arrives at the requested boundary.
    """
    started = clock()
    reconnect_at = started + reconnect_seconds
    state.update(attempt=state.get('attempt', 0) + 1, phase='opening',
                 attempt_started_elapsed_seconds=round(started-load_started, 3),
                 last_version=since, completed_frames=0, finish_reason=None)
    reason = None
    async with client.stream('GET', path, headers={'Last-Event-ID': str(since)}) as response:
        response.raise_for_status()
        state['phase'] = 'reading'
        name, data, size = '', [], 0
        async for line in response.aiter_lines():
            if stopped():
                reason = 'stopped'
                break
            size += len(line)
            if size > 8 * 1024 * 1024:
                raise ValueError('sse_frame_too_large')
            if line.startswith('event:'):
                name = line[6:].strip()
            elif line.startswith('data:'):
                data.append(line[5:].removeprefix(' '))
            elif not line:
                if data:
                    value = json.loads('\n'.join(data))
                    if not isinstance(value, dict):
                        raise ValueError('sse_event_not_object')
                    if name == 'document':
                        version = value.get('version')
                        if type(version) is not int or version <= since:
                            raise ValueError('non_monotonic_event')
                        on_event(name, value)
                        since = version
                    else:
                        on_event(name, value)
                on_event('heartbeat', {})
                now = clock()
                state.update(last_frame_elapsed_seconds=round(now-load_started, 3),
                             last_version=since, completed_frames=state['completed_frames']+1)
                name, data, size = '', [], 0
                if now >= end_deadline:
                    reason = 'deadline'
                    break
                if now >= reconnect_at:
                    reason = 'scheduled'
                    break
        if reason is None:
            state['phase'] = 'unexpected_eof'
            raise UnexpectedStreamEnd('sse_closed_before_requested_boundary')
        state['phase'] = 'closing'
    state.update(phase='closed', finish_reason=reason,
                 duration_seconds=round(clock()-started, 3))
    return reason, since
