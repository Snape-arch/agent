"""ASGI transport for ClawVision with a compatibility bridge to legacy routes.

The public transport is ASGI/uvicorn. Domain services are transport-neutral,
while routes not yet extracted are forwarded to an isolated loopback legacy
handler so the migration can remain API-compatible and incremental.
"""

from __future__ import annotations

import asyncio
import http.client
import socket
import threading
from typing import Any

import server as legacy


class LegacyBridge:
    def __init__(self) -> None:
        self.httpd = legacy.ThreadingHTTPServer(("127.0.0.1", 0), legacy.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="clawvision-legacy-bridge", daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.httpd.server_port)

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class ClawVisionASGI:
    def __init__(self) -> None:
        self.bridge: LegacyBridge | None = None
        self._lock = threading.Lock()

    def _ensure_bridge(self) -> LegacyBridge:
        with self._lock:
            if self.bridge is None:
                legacy.initialize()
                self.bridge = LegacyBridge()
            return self.bridge

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope["type"] == "lifespan":
            return await self._lifespan(receive, send)
        if scope["type"] != "http":
            return await send({"type": "http.response.start", "status": 404, "headers": []})
        bridge = self._ensure_bridge()
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body"):
                break
        raw_path = scope.get("raw_path") or scope.get("path", "/").encode()
        query = scope.get("query_string", b"")
        target = raw_path.decode("latin-1") + (f"?{query.decode('latin-1')}" if query else "")
        headers = {key.decode("latin-1"): value.decode("latin-1") for key, value in scope.get("headers", [])}
        connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=900)
        upstream_socket = None
        response = None

        async def relay() -> None:
            nonlocal upstream_socket, response
            await asyncio.to_thread(connection.request, scope["method"], target, bytes(body), headers)
            # HTTP/1.0 getresponse() detaches the connection socket. Retain it
            # so a downstream disconnect can interrupt a blocked upstream read.
            upstream_socket = connection.sock
            response = await asyncio.to_thread(connection.getresponse)
            response_headers = [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in response.getheaders()
                if key.lower() not in {"connection", "transfer-encoding"}
            ]
            await send({"type": "http.response.start", "status": response.status, "headers": response_headers})
            while True:
                # read(n) waits for n bytes or EOF; read1(n) forwards available
                # bytes immediately, including small events in long-lived SSE.
                chunk = await asyncio.to_thread(response.read1, 64 * 1024)
                if not chunk:
                    break
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})

        async def disconnected() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass

        relay_task = asyncio.create_task(relay())
        disconnect_task = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait({relay_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED)
            if relay_task in done:
                await relay_task
            else:
                await disconnect_task
        finally:
            if upstream_socket is not None:
                try:
                    upstream_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            relay_task.cancel()
            disconnect_task.cancel()
            await asyncio.gather(relay_task, disconnect_task, return_exceptions=True)
            if response is not None:
                # BufferedReader.close() may wait for the executor's active
                # read to release its lock. Never hold the ASGI event loop.
                await asyncio.to_thread(response.close)
            await asyncio.to_thread(connection.close)

    async def _lifespan(self, receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                self._ensure_bridge()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await asyncio.to_thread(legacy.stop_synthesis_recovery)
                if self.bridge:
                    await asyncio.to_thread(self.bridge.close)
                    self.bridge = None
                await send({"type": "lifespan.shutdown.complete"})
                return


app = ClawVisionASGI()
