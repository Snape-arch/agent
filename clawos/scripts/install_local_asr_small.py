#!/usr/bin/env python3
"""Install and warm up the default local ASR stack for ClawOS."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def default_model_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base).expanduser() / "ClawOS" / "asr_models"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small")
    parser.add_argument("--model-dir", default=str(default_model_dir()))
    parser.add_argument("--skip-pip", action="store_true")
    args = parser.parse_args()

    if not args.skip_pip:
        subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper>=1.2.0"], check=True)

    os.environ["CLAWOS_ASR_MODEL"] = args.model
    os.environ["CLAWOS_ASR_MODEL_DIR"] = str(Path(args.model_dir).expanduser().resolve())
    Path(args.model_dir).expanduser().mkdir(parents=True, exist_ok=True)

    from faster_whisper import WhisperModel

    WhisperModel(args.model, device="cpu", compute_type="int8", download_root=os.environ["CLAWOS_ASR_MODEL_DIR"])
    print(f"local ASR ready: faster-whisper model={args.model} dir={os.environ['CLAWOS_ASR_MODEL_DIR']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
