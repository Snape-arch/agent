from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


CLAWOS_ROOT = Path(__file__).resolve().parents[1]
if str(CLAWOS_ROOT) not in sys.path:
    sys.path.insert(0, str(CLAWOS_ROOT))

from services.answer_quality_benchmark import DEFAULT_CORPUS, run_answer_quality_benchmark, write_default_corpus
from services.artifact_storage import ArtifactStorage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--out", default=str(CLAWOS_ROOT.parent / "output" / "answer_quality"))
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    if args.generate:
        write_default_corpus(args.corpus)
    report = run_answer_quality_benchmark(args.corpus)
    report["artifact"] = ArtifactStorage(args.out).write_json("answer_quality_report.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
