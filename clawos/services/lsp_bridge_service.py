"""Bounded Language Server Protocol stdio bridge.

The bridge launches only an explicitly configured command. It performs a real
JSON-RPC initialize handshake and never reports availability from file
extensions or configuration alone.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class LanguageServerBridge:
    def __init__(
        self, command: list[str], *, timeout_seconds: float = 5.0
    ):
        if not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("an explicit language-server command is required")
        self.command = list(command)
        self.timeout_seconds = max(0.2, min(float(timeout_seconds), 60.0))
        self._process: subprocess.Popen | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._request_id = 0
        self._reader: threading.Thread | None = None
        self._root = ""
        self._server_capabilities: dict[str, Any] = {}

    def start(self, repo_path: str | Path) -> dict[str, Any]:
        repo = Path(repo_path).expanduser().resolve()
        if not repo.is_dir():
            raise ValueError("repository does not exist")
        if self._process is not None:
            return self.status()
        try:
            self._process = subprocess.Popen(
                self.command,
                cwd=repo,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self._process = None
            return {
                "available": False,
                "initialized": False,
                "error": f"{type(exc).__name__}: {exc}",
                "command": self.command,
            }
        self._root = repo.as_uri()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        try:
            response = self.request("initialize", {
                "processId": None,
                "rootUri": self._root,
                "capabilities": {
                    "textDocument": {
                        "documentSymbol": {},
                        "publishDiagnostics": {},
                    }
                },
                "workspaceFolders": [{"uri": self._root, "name": repo.name}],
            })
            self._server_capabilities = dict(
                (response.get("result") or {}).get("capabilities") or {}
            )
            self.notify("initialized", {})
            return self.status()
        except (RuntimeError, TimeoutError) as exc:
            self.stop()
            return {
                "available": False,
                "initialized": False,
                "error": str(exc),
                "command": self.command,
            }

    def status(self) -> dict[str, Any]:
        running = bool(self._process and self._process.poll() is None)
        return {
            "available": running and bool(self._server_capabilities),
            "initialized": running and bool(self._server_capabilities),
            "command": self.command,
            "root_uri": self._root,
            "capabilities": self._server_capabilities,
            "transport": "stdio-jsonrpc",
        }

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._process or self._process.poll() is not None:
            raise RuntimeError("language server is not running")
        self._request_id += 1
        request_id = self._request_id
        self._send({
            "jsonrpc": "2.0", "id": request_id,
            "method": method, "params": params,
        })
        deadline = time.monotonic() + self.timeout_seconds
        deferred = []
        try:
            while time.monotonic() < deadline:
                try:
                    message = self._messages.get(
                        timeout=max(0.01, deadline - time.monotonic())
                    )
                except queue.Empty:
                    break
                if message.get("id") == request_id:
                    if message.get("error"):
                        raise RuntimeError(
                            f"LSP {method} failed: {message['error']}"
                        )
                    return message
                deferred.append(message)
        finally:
            for message in deferred:
                self._messages.put(message)
        raise TimeoutError(f"LSP {method} timed out")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def document_symbols(
        self, path: str | Path, *, language_id: str = ""
    ) -> list[dict[str, Any]]:
        file_path = Path(path).expanduser().resolve()
        text = file_path.read_text(encoding="utf-8", errors="replace")
        uri = file_path.as_uri()
        self.notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id or file_path.suffix.lstrip("."),
                "version": 1,
                "text": text,
            }
        })
        result = self.request(
            "textDocument/documentSymbol", {"textDocument": {"uri": uri}}
        )
        return list(result.get("result") or [])

    def stop(self) -> None:
        process = self._process
        if not process:
            return
        try:
            if process.poll() is None:
                try:
                    self.request("shutdown", {})
                    self.notify("exit", {})
                    process.wait(timeout=1)
                except (RuntimeError, TimeoutError, subprocess.TimeoutExpired):
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    try:
                        stream.close()
                    except OSError:
                        pass
            self._process = None
            self._server_capabilities = {}

    def _send(self, payload: dict[str, Any]) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("language server is not running")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._process.stdin.write(
            f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        )
        self._process.stdin.flush()

    def _read_loop(self) -> None:
        stream = self._process.stdout if self._process else None
        if stream is None:
            return
        while self._process and self._process.poll() is None:
            headers: dict[str, str] = {}
            while True:
                line = stream.readline()
                if not line:
                    return
                if line in {b"\r\n", b"\n"}:
                    break
                key, _, value = line.decode("ascii", errors="replace").partition(":")
                headers[key.lower().strip()] = value.strip()
            try:
                length = int(headers.get("content-length", "0"))
                payload = json.loads(stream.read(length).decode("utf-8"))
            except (ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                self._messages.put(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop()
