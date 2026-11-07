"""Controlled local/Conda training providers using a streaming JSONL contract."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
PROCESSES: dict[str, subprocess.Popen] = {}
LOCK = threading.RLock()


def provider_catalog() -> list[dict]:
    conda = shutil.which("conda") or os.environ.get("CONDA_EXE")
    env = os.environ.get("CLAWVISION_TRAINING_CONDA_ENV", "fepf")
    return [
        {"id": "simulator", "label": "Deterministic simulator", "kind": "builtin", "configured": True, "gpu": False},
        {"id": "local-python", "label": "Local Python / PyTorch", "kind": "process", "configured": True, "gpu": False},
        {"id": "local-conda", "label": f"Conda ({env}) / GPU", "kind": "process", "configured": bool(conda), "gpu": True, "environment": env},
    ]


def cancel(job_id: str) -> bool:
    with LOCK: process = PROCESSES.get(job_id)
    if not process or process.poll() is not None: return False
    process.terminate()
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired: process.kill()
    return True


def run(job_id: str, provider: str, params: dict, on_event: Callable[[dict], None], timeout: int = 900) -> dict:
    # Operator-controlled override also allows isolated JSONL acceptance probes.
    script = Path(os.environ.get("CLAWVISION_TRAINING_SCRIPT") or ROOT / "workers" / "pytorch_trainer.py").resolve()
    if not script.is_file(): raise RuntimeError("configured training script is unavailable")
    spec = json.dumps({"params": params, "device": "auto"}, separators=(",", ":"))
    if provider == "local-conda":
        conda = shutil.which("conda") or os.environ.get("CONDA_EXE")
        if not conda: raise RuntimeError("Conda executable is unavailable")
        command = [conda, "run", "--no-capture-output", "-n", os.environ.get("CLAWVISION_TRAINING_CONDA_ENV", "fepf"), "python", str(script), "--spec", spec]
    elif provider == "local-python": command = [sys.executable, str(script), "--spec", spec]
    else: raise ValueError(f"unsupported real training provider: {provider}")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    with LOCK: PROCESSES[job_id] = process
    result: dict = {}; started = time.monotonic()
    try:
        assert process.stdout
        while True:
            if time.monotonic() - started > timeout:
                cancel(job_id); raise TimeoutError(f"training exceeded {timeout} seconds")
            line = process.stdout.readline()
            if line:
                try: event = json.loads(line)
                except json.JSONDecodeError: event = {"type": "log", "level": "info", "message": line.rstrip()}
                on_event(event)
                if event.get("type") == "result": result = event
            elif process.poll() is not None: break
            else: time.sleep(.02)
        if process.returncode: raise RuntimeError(f"training worker exited with code {process.returncode}")
        return result
    finally:
        if process.stdout: process.stdout.close()
        with LOCK: PROCESSES.pop(job_id, None)
