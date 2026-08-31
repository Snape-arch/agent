"""Evaluate local rasterized Chinese/English PDF pages without uploading content."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.document_ocr_benchmark import evaluate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--pages", nargs="+", type=int, default=[1])
    parser.add_argument("--language", default="auto")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate(args.source, args.pages, args.out, language=args.language)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
