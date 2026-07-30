#!/usr/bin/env python3
"""Sign CI or reviewer JSON for the fail-closed coding review gate."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


CLAWOS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAWOS))

from services.coding_quality_service import CodingReviewGate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--key-env", default="CLAWOS_REVIEW_SIGNING_KEY"
    )
    args = parser.parse_args()
    key = os.environ.get(args.key_env, "")
    if not key:
        print(f"{args.key_env} is required", file=sys.stderr)
        return 2
    source = Path(args.input).expanduser().resolve()
    target = Path(args.output).expanduser().resolve()
    if source == target:
        print("input and output must differ", file=sys.stderr)
        return 2
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if isinstance(value, list):
        signed = [CodingReviewGate.sign(item, key) for item in value]
    elif isinstance(value, dict):
        signed = CodingReviewGate.sign(value, key)
    else:
        print("input must be a JSON object or array", file=sys.stderr)
        return 2
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(signed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
