"""Dependency-free source and packaging checks used before slower integration tests."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "backend", ROOT / "sdk", ROOT / "scripts", ROOT / "tests"]


def main() -> None:
    failures: list[str] = []
    files = [path for target in TARGETS for path in target.rglob("*.py") if "__pycache__" not in path.parts]
    for path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeError) as error:
            failures.append(f"{path.relative_to(ROOT)}: {error}")
    pyproject_path = ROOT / "pyproject.toml"
    if not pyproject_path.is_file():
        failures.append("pyproject.toml is missing")
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pyproject_match = re.search(r'(?m)^version = "([^"]+)"$', pyproject_path.read_text(encoding="utf-8")) if pyproject_path.is_file() else None
    sdk_match = re.search(r'(?m)^__version__ = "([^"]+)"$', (ROOT / "sdk" / "clawvision" / "__init__.py").read_text(encoding="utf-8"))
    versions = {"package.json": package.get("version"), "pyproject.toml": pyproject_match.group(1) if pyproject_match else None, "Python SDK": sdk_match.group(1) if sdk_match else None}
    if len(set(versions.values())) != 1 or None in versions.values():
        failures.append(f"release versions are inconsistent: {versions}")
    print(json.dumps({"ok": not failures, "pythonFiles": len(files), "failures": failures}, ensure_ascii=False))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
