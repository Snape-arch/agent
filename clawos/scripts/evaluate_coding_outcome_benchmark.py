#!/usr/bin/env python3
"""Evaluate paired real-repository coding cases with a fail-closed contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CLAWOS = Path(__file__).resolve().parents[1]
ROOT = CLAWOS.parent
sys.path.insert(0, str(CLAWOS))

from services.coding_quality_service import CodingOutcomeBenchmark


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument(
        "--output",
        default=str(ROOT / "output" / "coding-benchmark" / "latest.json"),
    )
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--minimum-cases", type=int, default=30)
    parser.add_argument("--confirmed", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    source = Path(args.cases).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"unable to read benchmark cases: {exc}", file=sys.stderr)
        return 3
    cases = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        print("benchmark input must be a list or an object with cases", file=sys.stderr)
        return 3
    result = CodingOutcomeBenchmark().evaluate(
        cases,
        minimum_cases=args.minimum_cases,
        bootstrap_samples=args.bootstrap_samples,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.confirmed:
        target = Path(args.output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.strict and not result["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
