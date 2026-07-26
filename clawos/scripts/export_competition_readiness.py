#!/usr/bin/env python3
"""Export the evidence-based competition P0-P2 readiness pack."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from competition_readiness import CompetitionReadinessService
from memoryos.memory_store import MemoryStore
from validate_competition_architecture import validate


def _read_json(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run(args: argparse.Namespace) -> dict:
    db_path = Path(
        args.db
        or os.environ.get("CLAWOS_MEMORY_DB", "")
        or ROOT / "memoryos.db"
    ).expanduser().resolve()
    hardware_path = (
        Path(args.hardware_report).expanduser().resolve()
        if args.hardware_report else None
    )
    service = CompetitionReadinessService(MemoryStore(str(db_path)))
    snapshot = service.snapshot(
        architecture_report=validate(),
        hardware_evidence=_read_json(hardware_path),
    )
    output_dir = Path(args.out_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "competition_readiness.json"
    markdown_path = output_dir / "competition_readiness.md"
    json_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        service.to_markdown(snapshot),
        encoding="utf-8",
    )
    return {
        "snapshot": snapshot,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="")
    parser.add_argument("--hardware-report", default="")
    parser.add_argument("--out-dir", default="output")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = run(args)
    snapshot = result["snapshot"]
    print(json.dumps({
        "software_p0_p2_closed": snapshot["software_p0_p2_closed"],
        "competition_release_ready": snapshot["competition_release_ready"],
        "evidence_digest": snapshot["evidence_digest"],
        "json_path": result["json_path"],
        "markdown_path": result["markdown_path"],
        "next_actions": snapshot["next_actions"],
    }, ensure_ascii=False, indent=2))
    if args.strict and not snapshot["competition_release_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
