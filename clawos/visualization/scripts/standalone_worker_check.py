"""Black-box acceptance check for API + standalone durable worker."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ""


def call(path: str, body=None, token: str = ""):
    payload = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(BASE + path, data=payload, headers=headers,
                                     method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def main() -> None:
    global BASE
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    BASE = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="clawvision-worker-") as data_dir:
        # Windows environments can contain both Path and PATH. Normalize before
        # subprocess creation so the release check works in shells and CI alike.
        env = {key: value for key, value in os.environ.items() if key.lower() != "path"}
        env["PATH"] = os.environ.get("PATH") or os.environ.get("Path", "")
        env.update({"CLAWVISION_DATA_DIR": data_dir,
                    "CLAWVISION_OBJECT_DIR": str(Path(data_dir) / "objects"),
                    "CLAWVISION_PORT": str(port), "CLAWVISION_AUTH_MODE": "enabled",
                    "CLAWVISION_EMBEDDED_WORKERS": "false"})
        options = {"cwd": ROOT, "env": env, "stdout": subprocess.DEVNULL,
                   "stderr": subprocess.DEVNULL, "text": True}
        api = subprocess.Popen([sys.executable, "backend/server.py"], **options)
        worker = None
        try:
            for _ in range(300):
                try:
                    if call("/api/health")["ok"]:
                        break
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(.1)
            else:
                raise RuntimeError("API did not become ready")
            worker = subprocess.Popen([sys.executable, "workers/task_worker.py"], **options)
            auth = call("/api/auth/bootstrap", {"email": "worker@local.test",
                        "password": "standalone-worker-password", "tenantName": "Worker Test"})
            token = auth["data"]["token"]
            job = call("/api/jobs", {"name": "standalone", "kind": "single",
                       "trainingProvider": "simulator",
                       "configs": [{"epochs": 2, "learningRate": .001}]}, token)
            run_id = job["data"]["runIds"][0]
            status = "queued"
            for _ in range(100):
                status = call(f"/api/runs/{run_id}", token=token)["data"]["status"]
                if status in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(.1)
            tasks = call("/api/tasks", token=token)["data"]
            task = next(item for item in tasks if item["resourceId"] == run_id)
            assert status == "completed" and task["status"] == "completed", (status, task)
            print(json.dumps({"ok": True, "runStatus": status,
                              "taskStatus": task["status"], "attempts": task["attempts"]}))
        finally:
            processes = [process for process in (worker, api) if process is not None]
            for process in processes:
                process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
