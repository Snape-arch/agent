import asyncio
import json
from pathlib import Path
import sys
import unittest

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from document_soak_stream import UnexpectedStreamEnd, exception_evidence, read_attempt


class Bytes(httpx.AsyncByteStream):
    def __init__(self, chunks=(), clock=None, hang=False, failure=None):
        self.chunks, self.clock, self.hang, self.failure = chunks, clock, hang, failure
        self.cancelled, self.closed = 0, False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.clock is not None:
                self.clock[0] += 2
            yield chunk
        if self.failure is not None:
            raise self.failure
        if self.hang:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise httpx.ReadError('synthetic cancellation cleanup') from OSError(995, 'synthetic cancelled I/O')

    async def aclose(self):
        self.closed = True


class DocumentSoakStreamTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, body, reconnect=1, since=0, callback=None, stopped=lambda: False):
        events, state = [], {}
        def collect(name, value):
            events.append((name, value))
            if callback:
                callback(name, value)
        transport = httpx.MockTransport(lambda req: httpx.Response(200, stream=body))
        async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1', trust_env=False) as client:
            outcome = await read_attempt(client, '/events', since, reconnect, 100,
                                         stopped, collect, state, 0,
                                         clock=lambda: body.clock[0] if body.clock is not None else 0)
        return outcome, events, state

    async def test_reconnect_finishes_multiline_frame_even_when_boundary_passed_in_middle(self):
        clock = [0]
        body = Bytes([b'event: document\ndata: {"version":\n', b'data: 2}\n\n'], clock, hang=True)
        outcome, events, state = await self.exercise(body, since=1)
        self.assertEqual(outcome, ('scheduled', 2))
        self.assertEqual(events[0], ('document', {'version': 2}))
        self.assertEqual(state['completed_frames'], 1)
        self.assertTrue(body.closed)
        self.assertEqual(body.cancelled, 0)

    async def test_old_timeout_can_surface_readerror_but_cooperative_close_never_cancels(self):
        # A deterministic cancellation counterexample, not a claim about the old
        # real three-hour failure's missing exception chain.
        old = Bytes([b': heartbeat\n\n'], hang=True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=old)), trust_env=False) as client:
            async def consume_forever():
                async with client.stream('GET', 'http://127.0.0.1/events') as response:
                    async for _ in response.aiter_lines():
                        pass
            with self.assertRaises(httpx.ReadError):
                await asyncio.wait_for(consume_forever(), .01)
        self.assertEqual(old.cancelled, 1)
        new = Bytes([b': heartbeat\n\n'], clock=[0], hang=True)
        result, _, _ = await self.exercise(new)
        self.assertEqual(result[0], 'scheduled')
        self.assertEqual(new.cancelled, 0)
        self.assertTrue(new.closed)

    async def test_readerror_and_readtimeout_are_not_reclassified_as_scheduled_reconnects(self):
        for failure in (httpx.ReadError('transport failure'), httpx.ReadTimeout('silent stream')):
            with self.subTest(kind=type(failure).__name__):
                body = Bytes(failure=failure)
                with self.assertRaises(type(failure)):
                    await self.exercise(body)
                self.assertTrue(body.closed)

    async def test_real_tcp_premature_eof_fails_instead_of_silently_reconnecting(self):
        async def connection(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n: heartbeat\n\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(connection, '127.0.0.1', 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
                with self.assertRaises(UnexpectedStreamEnd):
                    await read_attempt(client, '/events', 0, 100, float('inf'), lambda: False,
                                       lambda *_: None, {}, 0)

    async def test_duplicate_versions_and_malformed_json_fail(self):
        for chunk in (b'event: document\ndata: {"version": 2}\n\n', b'event: document\ndata: invalid\n\n'):
            with self.subTest(frame=chunk):
                with self.assertRaises(ValueError):
                    await self.exercise(Bytes([chunk], clock=[0]), since=2)

    async def test_access_denial_is_a_failure_even_at_scheduled_boundary(self):
        def reject(name, value):
            if name == 'denied':
                raise PermissionError('revoked')
        with self.assertRaises(PermissionError):
            await self.exercise(Bytes([b'event: denied\ndata: {"status":403}\n\n'], clock=[0]), callback=reject)

    async def test_diagnostics_preserve_chain_and_codes_without_messages_urls_headers_or_locals(self):
        private = 'Bearer PRIVATE_SESSION_COOKIE'
        try:
            try:
                raise OSError(995, private)
            except OSError as cause:
                raise httpx.ReadError(private, request=httpx.Request('GET', 'https://private.invalid/?token=SECRET')) from cause
        except httpx.ReadError as exc:
            evidence = exception_evidence(exc)
        self.assertEqual([r['type'] for r in evidence['chain']], ['ReadError', 'OSError'])
        self.assertEqual(evidence['chain'][1]['errno'], 995)
        encoded = json.dumps(evidence)
        for forbidden in (private, 'private.invalid', 'SECRET', str(Path(__file__).parent)):
            self.assertNotIn(forbidden, encoded)
        self.assertTrue(evidence['chain'][0]['frames'])

    async def test_external_shutdown_does_not_count_as_scheduled_reconnect(self):
        result, _, state = await self.exercise(Bytes([b': heartbeat\n\n'], clock=[0]), stopped=lambda: True)
        self.assertEqual(result[0], 'stopped')
        self.assertEqual(state['completed_frames'], 0)


if __name__ == '__main__':
    unittest.main()
