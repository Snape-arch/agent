#!/usr/bin/env python3
"""Small Windows launcher health check for local HTTP services."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--name", default="service")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument('--require-ready',action='store_true',help='Require ClawOS core readiness and matching startup/disk sources')
    args = parser.parse_args()

    deadline = time.monotonic() + max(args.timeout, 1.0)
    last_error = ""
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(args.url, headers={"Accept": "application/json"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=2.0) as response:
                body = response.read().decode("utf-8", errors="replace")
                payload = json.loads(body) if body else {}
                if 200 <= response.status < 300:
                    if args.require_ready and (not isinstance(payload,dict) or payload.get('core_ready') is not True or not isinstance(payload.get('release'),dict) or payload['release'].get('restart_required') is not False):
                        last_error='Core not ready or source version changed; restart/recheck this instance'
                        time.sleep(.5);continue
                    print(f"[OK] {args.name} healthy: {args.url}")
                    if isinstance(payload, dict):
                        status = payload.get("status")
                        if status:
                            print(f"     status={status}")
                    return 0
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)

    print(f"[ERROR] {args.name} health check failed: {args.url}")
    if last_error:
        print(f"        {last_error}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
