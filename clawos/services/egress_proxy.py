"""Authenticated default-deny egress proxy with DNS and credential controls."""

from __future__ import annotations

import fnmatch
import hmac
import http.client
import ipaddress
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


class EgressProxyPolicy:
    def __init__(
        self,
        *,
        allowed_hosts: list[str],
        allowed_ports: list[int] | None = None,
        credential_hosts: list[str] | None = None,
        allow_private_for_test: bool = False,
    ):
        self.allowed_hosts = tuple(
            str(item).lower() for item in allowed_hosts if str(item).strip()
        )
        self.allowed_ports = {
            int(item) for item in (allowed_ports or [80, 443])
        }
        self.credential_hosts = tuple(
            str(item).lower() for item in (credential_hosts or [])
        )
        self.allow_private_for_test = bool(allow_private_for_test)

    def evaluate(self, host: str, port: int) -> dict[str, Any]:
        normalized = str(host or "").strip().lower().rstrip(".")
        allowed = bool(normalized) and any(
            fnmatch.fnmatch(normalized, pattern)
            for pattern in self.allowed_hosts
        )
        reason = "host allowlisted" if allowed else "host is not allowlisted"
        addresses: list[str] = []
        if allowed and int(port) not in self.allowed_ports:
            allowed, reason = False, "port is not allowlisted"
        if allowed:
            try:
                addresses = sorted({
                    item[4][0]
                    for item in socket.getaddrinfo(
                        normalized, int(port), type=socket.SOCK_STREAM
                    )
                })
            except socket.gaierror:
                allowed, reason = False, "DNS resolution failed"
        if allowed and not self.allow_private_for_test:
            for value in addresses:
                address = ipaddress.ip_address(value)
                if (
                    address.is_private or address.is_loopback
                    or address.is_link_local or address.is_reserved
                    or address.is_multicast or address.is_unspecified
                ):
                    allowed, reason = False, "DNS resolved to a non-public address"
                    break
        credential_forwarding = allowed and any(
            fnmatch.fnmatch(normalized, pattern)
            for pattern in self.credential_hosts
        )
        return {
            "allowed": allowed, "host": normalized, "port": int(port),
            "resolved_addresses": addresses, "reason": reason,
            "credential_forwarding": credential_forwarding,
        }


class AuditedEgressProxy:
    """Loopback proxy. Clients must present a per-run bearer capability."""

    def __init__(
        self, policy: EgressProxyPolicy, capability_token: str,
        *, max_body_bytes: int = 2 * 1024 * 1024,
    ):
        if len(str(capability_token or "")) < 24:
            raise ValueError("capability_token must contain at least 24 characters")
        self.policy = policy
        self._token = str(capability_token)
        self.max_body_bytes = max(1024, int(max_body_bytes))
        self.audit: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def address(self) -> tuple[str, int]:
        if not self._server:
            raise RuntimeError("proxy is not running")
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> "AuditedEgressProxy":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, _format: str, *args: Any) -> None:
                return

            def do_CONNECT(self) -> None:  # noqa: N802
                owner._handle_connect(self)

            def do_GET(self) -> None:  # noqa: N802
                owner._handle_http(self)

            def do_POST(self) -> None:  # noqa: N802
                owner._handle_http(self)

            def do_PUT(self) -> None:  # noqa: N802
                owner._handle_http(self)

            def do_PATCH(self) -> None:  # noqa: N802
                owner._handle_http(self)

            def do_DELETE(self) -> None:  # noqa: N802
                owner._handle_http(self)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="clawos-egress-proxy", daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    def _authorized(self, handler: BaseHTTPRequestHandler) -> bool:
        expected = f"Bearer {self._token}"
        supplied = str(handler.headers.get("Proxy-Authorization") or "")
        return hmac.compare_digest(supplied, expected)

    def _reject(
        self, handler: BaseHTTPRequestHandler, status: int, reason: str,
        *, decision: dict[str, Any] | None = None,
    ) -> None:
        body = reason.encode("utf-8")
        handler.send_response(status)
        handler.send_header("content-type", "text/plain; charset=utf-8")
        handler.send_header("content-length", str(len(body)))
        handler.send_header("connection", "close")
        handler.end_headers()
        handler.wfile.write(body)
        self._record(handler.command, decision or {}, "deny", reason, 0)

    def _handle_http(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authorized(handler):
            self._reject(handler, 407, "proxy authentication required")
            return
        parsed = urlsplit(handler.path)
        if parsed.scheme != "http" or not parsed.hostname:
            self._reject(handler, 400, "absolute http URL is required")
            return
        port = parsed.port or 80
        decision = self.policy.evaluate(parsed.hostname, port)
        if not decision["allowed"]:
            self._reject(handler, 403, decision["reason"], decision=decision)
            return
        length = int(handler.headers.get("content-length") or 0)
        if length > self.max_body_bytes:
            self._reject(handler, 413, "request body exceeds proxy limit",
                         decision=decision)
            return
        body = handler.rfile.read(length) if length else None
        headers = {
            key: value for key, value in handler.headers.items()
            if key.lower() not in {
                "proxy-authorization", "proxy-connection", "connection",
                "host", "content-length",
            }
        }
        if not decision["credential_forwarding"]:
            for key in list(headers):
                if key.lower() in {"authorization", "cookie"}:
                    headers.pop(key)
        host_header = parsed.hostname
        if port != 80:
            host_header = f"{host_header}:{port}"
        headers["Host"] = host_header
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        resolved = decision["resolved_addresses"][0]
        connection = http.client.HTTPConnection(
            resolved, port, timeout=15
        )
        try:
            connection.request(
                handler.command, target, body=body, headers=headers
            )
            response = connection.getresponse()
            payload = response.read(self.max_body_bytes + 1)
            if len(payload) > self.max_body_bytes:
                self._reject(handler, 502, "upstream response exceeds proxy limit",
                             decision=decision)
                return
            handler.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in {
                    "connection", "transfer-encoding", "content-length",
                }:
                    handler.send_header(key, value)
            handler.send_header("content-length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
            self._record(
                handler.command, decision, "allow",
                f"upstream status {response.status}", len(payload),
            )
        except (OSError, http.client.HTTPException) as exc:
            self._reject(
                handler, 502, f"upstream failed: {type(exc).__name__}",
                decision=decision,
            )
        finally:
            connection.close()

    def _handle_connect(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authorized(handler):
            self._reject(handler, 407, "proxy authentication required")
            return
        host, separator, port_text = handler.path.rpartition(":")
        if not separator:
            self._reject(handler, 400, "CONNECT requires host:port")
            return
        try:
            port = int(port_text)
        except ValueError:
            self._reject(handler, 400, "CONNECT port is invalid")
            return
        decision = self.policy.evaluate(host, port)
        if not decision["allowed"]:
            self._reject(handler, 403, decision["reason"], decision=decision)
            return
        try:
            resolved = decision["resolved_addresses"][0]
            upstream = socket.create_connection((resolved, port), timeout=15)
        except OSError as exc:
            self._reject(
                handler, 502, f"upstream failed: {type(exc).__name__}",
                decision=decision,
            )
            return
        transferred = 0
        try:
            handler.send_response(200, "Connection Established")
            handler.end_headers()
            sockets = [handler.connection, upstream]
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline and transferred <= self.max_body_bytes:
                readable, _, _ = select.select(sockets, [], [], 1)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        deadline = 0
                        break
                    target = upstream if source is handler.connection else handler.connection
                    target.sendall(data)
                    transferred += len(data)
        finally:
            upstream.close()
            self._record(
                "CONNECT", decision,
                "allow" if transferred <= self.max_body_bytes else "limit",
                "tunnel closed", transferred,
            )

    def _record(
        self, method: str, decision: dict[str, Any],
        outcome: str, reason: str, bytes_count: int,
    ) -> None:
        with self._lock:
            self.audit.append({
                "timestamp": time.time(), "method": method,
                "host": decision.get("host", ""),
                "port": decision.get("port", 0),
                "resolved_addresses": decision.get("resolved_addresses", []),
                "credential_forwarding": bool(
                    decision.get("credential_forwarding")
                ),
                "outcome": outcome, "reason": reason,
                "bytes": int(bytes_count),
            })
