"""Fail-closed publisher certificate intake for production VSIX signing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.vsix_release import VsixReleaseService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--trust-bundle", required=True)
    parser.add_argument(
        "--output",
        default=str(
            ROOT.parent / "output" / "evidence"
            / "publisher-certificate.json"
        ),
    )
    args = parser.parse_args()
    report = VsixReleaseService.validate_publisher_identity(
        Path(args.private_key).read_bytes(),
        Path(args.certificate).read_bytes(),
        Path(args.trust_bundle).read_bytes(),
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("trusted_publisher") else 2


if __name__ == "__main__":
    raise SystemExit(main())
