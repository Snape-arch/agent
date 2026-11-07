"""Pluggable professional geometry worker contracts with preemptive cancellation."""

from __future__ import annotations

import base64
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable


@dataclass
class GeometryResult:
    content: bytes
    format: str
    stats: dict


PROVIDERS = {
    "builtin-voxel": {"label": "Built-in watertight mesh", "kind": "builtin", "exact": False, "formats": ["glb", "gltf", "obj", "stl", "ply"], "operations": ["boolean", "bevel", "chamfer", "decimate", "remesh", "repair"]},
    "manifold": {"label": "Manifold professional mesh kernel", "kind": "command", "exact": False, "formats": ["glb", "gltf", "obj", "stl", "ply"], "operations": ["boolean", "repair", "decimate", "remesh", "uv-unwrap"]},
    "opencascade": {"label": "OpenCascade B-Rep kernel", "kind": "command", "exact": True, "formats": ["step", "iges", "brep", "glb", "gltf", "obj", "stl"], "operations": ["roundtrip", "exact-boolean", "fillet", "chamfer", "tessellate", "repair"]},
    "external": {"label": "External geometry service", "kind": "http", "exact": True, "formats": ["step", "iges", "ply", "glb", "gltf", "obj", "stl"], "operations": ["exact-boolean", "fillet", "chamfer", "uv-unwrap", "retopology", "convert", "repair"]},
}


def provider_catalog() -> list[dict]:
    items = []
    for provider_id, metadata in PROVIDERS.items():
        configured = provider_id == "builtin-voxel"
        if metadata["kind"] == "command": configured = bool(os.environ.get(f"GEOMETRY_{provider_id.upper()}_COMMAND"))
        elif metadata["kind"] == "http": configured = bool(os.environ.get("GEOMETRY_EXTERNAL_URL"))
        items.append({"id": provider_id, **metadata, "configured": configured, "preemptiveCancel": metadata["kind"] == "command", "checkpointResume": metadata["kind"] in {"command", "http"}})
    return items


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None: return
    process.terminate()
    try: process.wait(timeout=3)
    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)


def _command_provider(provider: str, request: dict, timeout: int, progress: Callable[[int, str, dict | None], None], cancelled: Callable[[], bool]) -> GeometryResult:
    command = os.environ.get(f"GEOMETRY_{provider.upper()}_COMMAND", "").strip()
    if not command: raise RuntimeError(f"{provider} is not configured; set GEOMETRY_{provider.upper()}_COMMAND")
    args = command if sys.platform == "win32" else shlex.split(command); flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", creationflags=flags)
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps(request, ensure_ascii=True)); process.stdin.close()
    events: queue.Queue = queue.Queue()
    def read_output():
        try:
            for line in process.stdout:
                if line.strip(): events.put(("event", line))
        finally: events.put(("eof", ""))
    reader = threading.Thread(target=read_output, daemon=True); reader.start(); deadline = time.monotonic() + timeout; final = None; eof = False
    try:
        while not eof or process.poll() is None:
            if cancelled(): _terminate(process); raise RuntimeError("cancelled")
            if time.monotonic() >= deadline: _terminate(process); raise TimeoutError(f"{provider} exceeded {timeout}s")
            try: kind, raw = events.get(timeout=.1)
            except queue.Empty: continue
            if kind == "eof": eof = True; continue
            event = json.loads(raw)
            if event.get("type") in {"progress", "checkpoint"}: progress(int(event.get("progress", 0)), str(event.get("stage") or provider), event.get("checkpoint") if isinstance(event.get("checkpoint"), dict) else None)
            elif event.get("type") == "result": final = event
        process.wait(timeout=3)
    finally:
        if process.poll() is None: _terminate(process)
    detail = process.stderr.read()[-2000:] if process.stderr and (process.returncode or not final) else ""
    if process.stdout: process.stdout.close()
    if process.stderr: process.stderr.close()
    if process.returncode or not final: raise RuntimeError(detail or f"{provider} returned no geometry")
    return GeometryResult(base64.b64decode(final["content"]), str(final.get("format") or "glb").lower(), {**(final.get("stats") or {}), "provider": provider, "professionalKernel": True})


def _safe_endpoint() -> str:
    endpoint = os.environ.get("GEOMETRY_EXTERNAL_URL", "").rstrip("/")
    if endpoint.startswith("https://") or endpoint.startswith("http://127.0.0.1") or endpoint.startswith("http://localhost"): return endpoint
    raise RuntimeError("GEOMETRY_EXTERNAL_URL must use HTTPS or localhost")


def _external_provider(request: dict, timeout: int, progress, cancelled) -> GeometryResult:
    endpoint = _safe_endpoint(); headers = {"Content-Type": "application/json", "Accept": "application/json"}; key = os.environ.get("GEOMETRY_EXTERNAL_API_KEY")
    if key: headers["Authorization"] = f"Bearer {key}"
    call = urllib.request.Request(endpoint + "/jobs", data=json.dumps(request).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(call, timeout=min(timeout, 60)) as response: created = json.loads(response.read().decode())
    if created.get("content"): return GeometryResult(base64.b64decode(created["content"]), str(created.get("format") or "glb"), {**created.get("stats", {}), "provider": "external", "professionalKernel": True})
    job_id = str(created.get("id") or ""); deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled():
            try: urllib.request.urlopen(urllib.request.Request(endpoint + f"/jobs/{job_id}", headers=headers, method="DELETE"), timeout=10).close()
            finally: raise RuntimeError("cancelled")
        with urllib.request.urlopen(urllib.request.Request(endpoint + f"/jobs/{job_id}", headers=headers), timeout=30) as response: item = json.loads(response.read().decode())
        progress(int(item.get("progress") or 0), str(item.get("stage") or "external-geometry"), item.get("checkpoint") if isinstance(item.get("checkpoint"), dict) else None)
        if item.get("status") == "completed": return GeometryResult(base64.b64decode(item["content"]), str(item.get("format") or "glb"), {**item.get("stats", {}), "provider": "external", "providerJobId": job_id, "professionalKernel": True})
        if item.get("status") in {"failed", "cancelled"}: raise RuntimeError(str(item.get("error") or item["status"]))
        time.sleep(max(.1, float(os.environ.get("GEOMETRY_POLL_SECONDS", "1"))))
    raise TimeoutError(f"external geometry job exceeded {timeout}s")


def run_provider(provider: str, request: dict, timeout: int, progress: Callable[[int, str, dict | None], None], cancelled: Callable[[], bool]) -> GeometryResult:
    if provider not in PROVIDERS or provider == "builtin-voxel": raise ValueError("a configured professional geometry provider is required")
    result = _command_provider(provider, request, timeout, progress, cancelled) if PROVIDERS[provider]["kind"] == "command" else _external_provider(request, timeout, progress, cancelled)
    if result.format not in {"glb", "gltf", "obj", "stl", "ply", "step", "iges", "brep"}: raise RuntimeError("geometry provider returned an unsupported format")
    return result
