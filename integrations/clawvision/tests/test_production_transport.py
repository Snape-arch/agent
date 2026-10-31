"""Real-socket regression tests for the production ASGI transport."""
from __future__ import annotations

import asyncio
import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import asgi  # noqa: E402


class BridgeDisconnectTests(unittest.TestCase):
    def test_disconnect_interrupts_an_idle_upstream_stream(self):
        upstream_closed = threading.Event()

        class StreamHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b"event: run\ndata: {}\n\n")
                self.wfile.flush()
                self.connection.settimeout(3)
                if self.connection.recv(1) == b"":
                    upstream_closed.set()

            def log_message(self, *args):
                pass

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), StreamHandler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        application = asgi.ClawVisionASGI()
        application._ensure_bridge = Mock(return_value=Mock(port=upstream.server_port))

        async def exercise():
            delivered = asyncio.Event()
            first_request = True

            async def receive():
                nonlocal first_request
                if first_request:
                    first_request = False
                    return {"type": "http.request", "body": b"", "more_body": False}
                await delivered.wait()
                await asyncio.sleep(0.05)
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.body" and message.get("body"):
                    self.assertIn(b"event: run", message["body"])
                    delivered.set()

            await asyncio.wait_for(application({"type": "http", "method": "GET", "path": "/stream", "headers": []}, receive, send), timeout=2)
            self.assertTrue(delivered.is_set())

        try:
            asyncio.run(exercise())
            self.assertTrue(upstream_closed.wait(1), "disconnect must close the upstream socket")
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=2)


@unittest.skipUnless(importlib.util.find_spec("uvicorn"), "install requirements-dev.txt for production transport acceptance")
class ProductionTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.log = open(Path(cls.directory.name) / "uvicorn.log", "w+", encoding="utf-8")
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            cls.port = reservation.getsockname()[1]
        env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "DATABASE_URL": f"sqlite:///{Path(cls.directory.name) / 'test.db'}",
               "CLAWVISION_DATA_DIR": cls.directory.name, "CLAWVISION_OBJECT_DIR": str(Path(cls.directory.name) / "objects"),
               "ARTIFACT_STORE": "local", "CLAWVISION_AUTH_MODE": "enabled", "CLAWVISION_EMBEDDED_WORKERS": "false"}
        cls.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "asgi:app", "--host", "127.0.0.1", "--port", str(cls.port)], cwd=ROOT, env=env, stdout=cls.log, stderr=cls.log)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    status, _ = cls.call("/api/health", authenticated=False)
                    if status == 200:
                        break
                except (OSError, http.client.HTTPException):
                    pass
                if cls.process.poll() is not None:
                    raise RuntimeError("uvicorn exited before becoming ready")
                time.sleep(0.05)
            else:
                raise RuntimeError("uvicorn startup timed out")
            status, payload = cls.call("/api/auth/bootstrap", {"email": "transport@example.com", "password": "transport-test-password", "tenantName": "Transport"}, authenticated=False)
            assert status == 201, (status, payload)
            cls.token = payload["data"]["token"]
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.log.close()
        cls.directory.cleanup()

    @classmethod
    def call(cls, path, body=None, authenticated=True):
        connection = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=3)
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + cls.token
        try:
            connection.request("POST" if body is not None else "GET", path, None if body is None else json.dumps(body), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_auth_and_live_events_through_uvicorn(self):
        self.assertEqual(self.call("/api/runs", authenticated=False)[0], 401)
        status, payload = self.call("/api/runs", {"name": "production-sse", "source": "sdk", "params": {"epochs": 2}})
        self.assertEqual(status, 201)
        run_id = payload["data"]["id"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        response = None
        buffer = b""

        def next_event():
            nonlocal buffer
            while b"\n\n" not in buffer:
                chunk = response.read1(64 * 1024)
                self.assertTrue(chunk, "stream closed before the next event")
                buffer += chunk
            frame, buffer = buffer.split(b"\n\n", 1)
            self.assertIn(b"event: run", frame)
            return json.loads(next(line[5:].strip() for line in frame.splitlines() if line.startswith(b"data:")))

        try:
            connection.request("GET", f"/api/runs/{run_id}/stream", headers={"Authorization": "Bearer " + self.token})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
            self.assertEqual(next_event()["id"], run_id)
            self.assertEqual(self.call(f"/api/runs/{run_id}/metrics", {"step": 1, "accuracy": 0.72, "trainLoss": 0.5})[0], 200)
            self.assertEqual(next_event()["metrics"][-1]["accuracy"], 0.72)
            self.assertEqual(self.call(f"/api/runs/{run_id}/stop", {"message": "acceptance complete"})[0], 200)
            self.assertEqual(next_event()["status"], "stopped")
            self.assertEqual(response.read(), b"")
        finally:
            if response is not None:
                response.close()
            connection.close()
        self.assertEqual(self.call("/api/health", authenticated=False)[0], 200)

    def test_idle_browser_disconnect_does_not_block_other_requests(self):
        _, payload = self.call("/api/runs", {"name": "cancel-sse", "source": "sdk", "params": {"epochs": 2}})
        run_id = payload["data"]["id"]
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request("GET", f"/api/runs/{run_id}/stream", headers={"Authorization": "Bearer " + self.token})
        response = connection.getresponse()
        self.assertIn(b"event: run", response.read1(64 * 1024))
        time.sleep(0.1)
        response.close()
        connection.close()
        self.assertEqual(self.call("/api/health", authenticated=False)[0], 200)
        self.assertEqual(self.call(f"/api/runs/{run_id}/stop", {"message": "disconnected"})[0], 200)

    def test_incremental_stream_drains_every_chunk_including_the_terminal_chunk(self):
        _, payload = self.call("/api/runs", {"name": "bounded-deltas", "params": {}})
        run_id, initial_cursor = payload["data"]["id"], payload["data"]["cursor"]
        self.assertEqual(self.call(f"/api/runs/{run_id}/batch", {"metrics": [{"step": step, "accuracy": .7} for step in range(205)]})[0], 200)
        _, stopped = self.call(f"/api/runs/{run_id}/stop", {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request("GET", f"/api/runs/{run_id}/stream?incremental=1&after={initial_cursor}", headers={"Authorization": "Bearer " + self.token})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            frames = response.read().decode().strip().split("\n\n")
            self.assertEqual(len(frames), 3)
            deltas = []
            for frame in frames:
                self.assertIn("event: run-delta", frame)
                deltas.append(json.loads(next(line[5:].strip() for line in frame.splitlines() if line.startswith("data:"))))
            self.assertEqual(sorted(point["step"] for delta in deltas for point in delta["metrics"]), list(range(205)))
            self.assertFalse(deltas[-1]["hasMore"])
            self.assertEqual(deltas[-1]["cursor"], stopped["data"]["cursor"])
            self.assertEqual(deltas[-1]["run"]["status"], "stopped")
            self.assertNotIn("logs", deltas[-1])
        finally:
            connection.close()
        self.assertEqual(self.call(f"/api/runs/{run_id}/changes?after={stopped['data']['cursor']}")[1]["data"]["metrics"], [])
        self.assertEqual(self.call(f"/api/runs/{run_id}/changes?after=-1")[0], 400)
        self.assertEqual(self.call(f"/api/runs/{run_id}/stream?incremental=1&after=-1")[0], 400)


if __name__ == "__main__":
    unittest.main()
