"""Opt-in download of pinned official OCR data into this workspace (not system-wide)."""
from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
from urllib.request import urlopen

REVISION = "87416418657359cb625c412a48b6e1d6d41c29bd"
MODELS = {
    "chi_sim": "a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["fast", "best"], default="fast")
    args = parser.parse_args()
    revisions = {name: ("tessdata_fast", REVISION, digest) for name, digest in MODELS.items()}
    if args.profile == "best":
        revisions["chi_sim"] = ("tessdata_best", "e12c65a915945e4c28e237a9b52bc4a8f39a0cec", "4fef2d1306c8e87616d4d3e4c6c67faf5d44be3342290cf8f2f0f6e3aa7e735b")
    target = Path(__file__).resolve().parents[2] / "tools/ocr" / ("tessdata" if args.profile == "fast" else "tessdata-best")
    target.mkdir(parents=True, exist_ok=True)
    results = []
    for language, (repository, revision, digest) in revisions.items():
        destination = target / f"{language}.traineddata"
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Refusing to overwrite different model: {destination}")
            results.append({"language": language, "status": "verified", "sha256": digest})
            continue
        url = f"https://raw.githubusercontent.com/tesseract-ocr/{repository}/{revision}/{language}.traineddata"
        with urlopen(url, timeout=60) as response:
            data = response.read(30_000_001)
        if len(data) > 30_000_000 or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Model checksum mismatch: {language}")
        # Exclusive creation prevents replacement of an existing user model.
        with destination.open("xb") as output:
            output.write(data)
        results.append({"language": language, "status": "installed", "sha256": digest})
    print(json.dumps({"profile": args.profile, "revisions": revisions, "models": results}, indent=2))


if __name__ == "__main__":
    main()
