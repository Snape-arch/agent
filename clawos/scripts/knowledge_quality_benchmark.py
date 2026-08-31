from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CLAWOS_ROOT = Path(__file__).resolve().parents[1]
if str(CLAWOS_ROOT) not in sys.path:
    sys.path.insert(0, str(CLAWOS_ROOT))

from services.artifact_storage import ArtifactStorage
from services.knowledge_quality_benchmark import DEFAULT_CORPUS, run_knowledge_quality_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reviewed ClawOS knowledge quality benchmark.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--out", default=str(CLAWOS_ROOT.parent / "output" / "knowledge_quality"))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = run_knowledge_quality_benchmark(args.corpus)
    artifact = ArtifactStorage(args.out).write_json("knowledge_quality_report.json", report)
    report["artifact"] = artifact
    print(json.dumps(report, ensure_ascii=False))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
