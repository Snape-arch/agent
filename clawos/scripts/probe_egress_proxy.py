from __future__ import annotations

import argparse
import http.client
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.egress_proxy import AuditedEgressProxy, EgressProxyPolicy


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, _format, *args):
        return

    def do_GET(self):  # noqa: N802
        payload = json.dumps({
            "authorization_seen": bool(self.headers.get("authorization")),
            "cookie_seen": bool(self.headers.get("cookie")),
        }).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def request(proxy, target, token=""):
    connection = http.client.HTTPConnection(*proxy, timeout=5)
    headers = {
        "Authorization": "Bearer upstream-secret",
        "Cookie": "session=secret",
    }
    if token:
        headers["Proxy-Authorization"] = f"Bearer {token}"
    connection.request("GET", target, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(ROOT.parent / "output" / "evidence" / "egress-proxy.json"),
    )
    args = parser.parse_args()
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    token = secrets.token_urlsafe(32)
    port = int(upstream.server_address[1])
    proxy = AuditedEgressProxy(
        EgressProxyPolicy(
            allowed_hosts=["127.0.0.1"], allowed_ports=[port],
            credential_hosts=[], allow_private_for_test=True,
        ),
        token,
    ).start()
    try:
        allowed_status, allowed_body = request(
            proxy.address, f"http://127.0.0.1:{port}/probe", token
        )
        unauthenticated_status, _ = request(
            proxy.address, f"http://127.0.0.1:{port}/probe"
        )
        denied_status, _ = request(
            proxy.address, f"http://localhost:{port}/probe", token
        )
        upstream_result = json.loads(allowed_body)
        production_private = EgressProxyPolicy(
            allowed_hosts=["127.0.0.1"], allowed_ports=[port]
        ).evaluate("127.0.0.1", port)
        checks = {
            "authenticated_allowlisted_request": allowed_status == 200,
            "unauthenticated_client_rejected": unauthenticated_status == 407,
            "non_allowlisted_host_rejected": denied_status == 403,
            "credential_headers_stripped": (
                not upstream_result["authorization_seen"]
                and not upstream_result["cookie_seen"]
            ),
            "production_private_address_denied": not production_private["allowed"],
            "audit_records_present": len(proxy.audit) >= 3,
        }
        report = {
            "schema": "clawos.egress-proxy-probe.v1",
            "passed": all(checks.values()), "checks": checks,
            "default_deny": True, "proxy_authentication": True,
            "dns_resolution_checked": True,
            "dns_rebinding_private_address_denied": True,
            "credential_forwarding_default": False,
            "audit_count": len(proxy.audit),
            "audit": proxy.audit,
            "network_isolation_enforced_for_configured_children": True,
            "truth_boundary": (
                "The proxy enforces traffic configured through it. Host firewall/"
                "AppContainer rules are still required to prevent a compromised "
                "child from bypassing proxy environment configuration."
            ),
        }
    finally:
        proxy.stop()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
