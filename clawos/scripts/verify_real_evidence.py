#!/usr/bin/env python3
"""Verify and optionally persist judge-safe real-task evidence manifests."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memoryos.memory_store import MemoryStore
from services.competition_evidence_service import CompetitionEvidenceService, sha256_file


def verify(path: Path) -> tuple[dict, dict]:
    run = json.loads(path.read_text(encoding="utf-8"))
    for item in run.get("artifacts") or []:
        uri = str(item.get("uri") or "").strip()
        artifact = Path(uri).expanduser()
        if not artifact.is_absolute():
            artifact = (path.parent / artifact).resolve()
        metadata = item.setdefault("metadata", {})
        if artifact.is_file():
            metadata["sha256"] = sha256_file(artifact)
            metadata["bytes"] = artifact.stat().st_size
        else:
            metadata.pop("sha256", None)
            metadata["missing"] = True
    validation = CompetitionEvidenceService.validate(run)
    run["verification"] = validation
    return run, validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="+", type=Path)
    parser.add_argument("--memory-db", default="", help="Persist only eligible chains to this MemoryOS database.")
    parser.add_argument("--out", default="", help="Write a combined verification report.")
    args = parser.parse_args()
    results = []
    store = MemoryStore(args.memory_db) if args.memory_db else None
    for manifest in args.manifests:
        run, validation = verify(manifest.resolve())
        if store and validation["eligible"]:
            store.save_run_record(run)
        results.append({"manifest": str(manifest), "run_id": run.get("run_id"), "validation": validation})
    report = {"ok": all(item["validation"]["eligible"] for item in results), "results": results}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
