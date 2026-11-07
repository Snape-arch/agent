"""Black-box smoke test for the production Docker Compose stack."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("CLAWVISION_BASE_URL", "http://127.0.0.1:8080")
EMAIL = os.environ.get("CLAWVISION_SMOKE_EMAIL", "smoke@clawvision.local")
PASSWORD = os.environ.get("CLAWVISION_SMOKE_PASSWORD", "compose-smoke-password")


TOKEN = ""


def call(path: str, body=None, method: str | None = None, authenticated: bool = True):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if authenticated and TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


health = call("/api/health", authenticated=False)
assert health["ok"] and health["databaseKind"] == "postgresql" and health["objectStore"]["kind"] == "s3", health
try:
    bootstrap = call("/api/auth/bootstrap", {"email": EMAIL, "password": PASSWORD, "tenantName": "Compose Smoke"}, authenticated=False)
except urllib.error.HTTPError as error:
    if error.code != 400:
        raise
    bootstrap = call("/api/auth/login", {"email": EMAIL, "password": PASSWORD}, authenticated=False)
TOKEN = bootstrap["data"]["token"]
project = call("/api/asset-projects", {"name": "compose-smoke"})["data"]
run = call("/api/runs", {"name": "compose-smoke", "params": {"epochs": 1}, "source": "compose-smoke"})["data"]
asset = call("/api/model-assets", {"name": "smoke.obj", "format": "obj", "content": base64.b64encode(b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n").decode(), "metadata": {"projectId": project["id"], "tags": ["smoke"]}})["data"]
call(f"/api/runs/{run['id']}/assets", {"assetId": asset["id"], "role": "checkpoint", "step": 1})
timeline = call(f"/api/runs/{run['id']}/timeline")["data"]
assert timeline["frames"][-1]["assets"][0]["asset"]["id"] == asset["id"], timeline
dataset = call("/api/datasets", {
    "name": "s3-partitioned-smoke",
    "partitionBy": ["split"],
    "files": [
        {"format": "json", "partitions": {"split": "train"}, "content": [{"step": 1, "loss": 0.8}]},
        {"format": "json", "partitions": {"split": "eval"}, "content": [{"step": 2, "loss": 0.5}]},
    ],
})["data"]
analysis = call("/api/analysis/query", {
    "sources": [{"datasetId": dataset["id"], "alias": "metrics"}],
    "filters": [{"field": "split", "operator": "eq", "value": "eval"}],
    "select": ["step", "loss", "split"],
    "cache": False,
})["data"]
assert analysis["rows"] == [{"step": 2, "loss": 0.5, "split": "eval"}], analysis
assert analysis["stats"]["provider"] == "duckdb-catalog" and analysis["stats"]["sourceFiles"] == 2, analysis
assert "READ_PARQUET" in analysis["plan"], analysis
print(json.dumps({"ok": True, "database": health["databaseKind"], "store": health["objectStore"]["kind"], "project": project["id"], "run": run["id"], "asset": asset["id"], "dataset": dataset["id"], "s3DirectScan": True}))
