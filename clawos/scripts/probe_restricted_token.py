from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.os_sandbox import WindowsRestrictedTokenSandbox


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(ROOT.parent))
    parser.add_argument(
        "--sandbox-root",
        default=str(ROOT.parent / "output" / "restricted-token-sandbox"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT.parent / "output" / "evidence"
                    / "restricted-token.json"),
    )
    args = parser.parse_args()
    report = WindowsRestrictedTokenSandbox().run_probe(
        args.workspace, args.sandbox_root
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
