"""Shared isolated acceptance clients, environment evidence and percentiles."""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def request(url: str, path: str, body: dict | None = None, token: str | None = None, timeout: float = 30) -> dict:
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = "Bearer " + token
    payload = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(url.rstrip('/') + path, data=payload, headers=headers), timeout=timeout) as response:
        return json.loads(response.read())


def authenticate(url: str, token: str | None = None, *, use_environment: bool = True) -> str:
    if token or (use_environment and os.environ.get("CLAWVISION_API_TOKEN")):
        return token or os.environ["CLAWVISION_API_TOKEN"]
    credentials = {"email": os.environ.get("CLAWVISION_ACCEPTANCE_EMAIL", "loadtest@clawvision.local"),
                   "password": os.environ.get("CLAWVISION_ACCEPTANCE_PASSWORD", "load-test-password-2026")}
    try:
        auth = request(url, "/api/auth/bootstrap", {**credentials, "tenantName": "Load Test"})
    except urllib.error.HTTPError as error:
        if error.code not in {400, 409}: raise
        error.close()
        auth = request(url, "/api/auth/login", credentials)
    return auth["data"]["token"]


def percentile(values: list[float], ratio: float = .95) -> float:
    if not values or not 0 < ratio <= 1: raise ValueError("percentile requires samples and 0 < ratio <= 1")
    return sorted(values)[max(0, math.ceil(len(values) * ratio) - 1)]


def write_report(report: dict, output: str | None) -> None:
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


def source_digest(repository: Path, directories: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for directory in directories for path in (repository / directory).rglob('*.py')):
        digest.update(path.relative_to(repository).as_posix().encode()); digest.update(b'\0')
        digest.update(path.read_bytes()); digest.update(b'\0')
    return digest.hexdigest()


def environment(health: dict, transport: str, repository: Path = ROOT) -> dict:
    cpu = platform.processor()
    if Path('/proc/cpuinfo').is_file():
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                cpu = line.split(':', 1)[-1].strip(); break
    comparable = {"os": platform.system(), "release": platform.release(), "architecture": platform.machine(),
                  "cpu": cpu, "cpus": os.cpu_count(), "python": platform.python_version(),
                  "database": health.get("databaseKind"), "objectStore": health.get("objectStore", {}).get("kind"),
                  "transport": transport, "label": os.environ.get("CLAWVISION_PERF_ENVIRONMENT", "local")}
    fingerprint = hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest()
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=repository, capture_output=True, text=True)
    return {**comparable, "fingerprint": fingerprint, "revision": revision.stdout.strip(),
            "dirty": bool(dirty.stdout.strip()), "apiSourceDigest": source_digest(repository, ('backend', 'workers')),
            "sdkDriverDigest": source_digest(ROOT, ('sdk',)), "recordedAt": datetime.now(timezone.utc).isoformat()}


@contextmanager
def local_worker(root: Path, repository: Path = ROOT):
    env = {key: value for key, value in os.environ.items() if key.lower() != 'path'}
    env['PATH'] = os.environ.get('PATH') or os.environ.get('Path', '')
    env.update({'DATABASE_URL': '', 'ARTIFACT_STORE': 'local', 'CLAWVISION_DATA_DIR': str(root),
                'CLAWVISION_OBJECT_DIR': str(root / 'objects'), 'CLAWVISION_AUTH_MODE': 'enabled',
                'CLAWVISION_EMBEDDED_WORKERS': 'false', 'CLAWVISION_WORKER_METRICS_PORT': '0'})
    with (root / 'worker.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, 'workers/task_worker.py'], cwd=repository, env=env, stdout=log, stderr=log)
        try: yield process
        finally:
            process.terminate()
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)


@contextmanager
def local_api(repository: Path = ROOT, data_directory: Path | None = None):
    """A fresh authenticated uvicorn service; never opens the workspace database."""
    repository = repository.resolve()
    if not (repository / 'backend/server.py').is_file(): raise ValueError('fixture repository has no API')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    with (nullcontext(str(data_directory)) if data_directory else tempfile.TemporaryDirectory(prefix='clawvision-acceptance-')) as folder:
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        env = {key: value for key, value in os.environ.items() if key.lower() != 'path'}
        env['PATH'] = os.environ.get('PATH') or os.environ.get('Path', '')
        env.update({'DATABASE_URL': '', 'ARTIFACT_STORE': 'local', 'PYTHONPATH': str(repository / 'backend'),
                    'CLAWVISION_DATA_DIR': str(root), 'CLAWVISION_OBJECT_DIR': str(root / 'objects'),
                    'CLAWVISION_AUTH_MODE': 'enabled', 'CLAWVISION_EMBEDDED_WORKERS': 'false'})
        with (root / 'api.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'asgi:app', '--host', '127.0.0.1', '--port', str(port)],
                                       cwd=repository, env=env, stdout=log, stderr=log)
            url = f'http://127.0.0.1:{port}'
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None: raise RuntimeError('isolated API exited during startup')
                    try:
                        if request(url, '/api/health', timeout=1).get('ok'): break
                    except (urllib.error.URLError, TimeoutError, ConnectionError): pass
                    time.sleep(.1)
                else: raise RuntimeError('isolated API startup timed out')
                yield url, root
            finally:
                process.terminate()
                try: process.wait(timeout=8)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
