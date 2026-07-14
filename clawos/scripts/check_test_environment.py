#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import sys
from pathlib import Path


PACKAGES = ("fastapi", "httpx", "PyMuPDF", "pdfplumber", "pypdf", "openpyxl", "python-docx", "python-pptx")


def tool(name: str) -> dict:
    known = Path("C:/Program Files/LibreOffice/program/soffice.com") if name == "soffice" else None
    executable = str(known) if known and known.is_file() else (shutil.which(f"{name}.exe") or shutil.which(name))
    result = {"available": bool(executable), "path": executable or ""}
    if executable:
        completed = subprocess.run([executable, "--version" if name == "soffice" else "-v"], capture_output=True, text=True, timeout=20)
        result["version"] = (completed.stdout or completed.stderr).splitlines()[0] if (completed.stdout or completed.stderr) else ""
    return result


payload = {
    "schema": "clawos.test-environment.v1",
    "python": sys.version.split()[0],
    "executable": sys.executable,
    "packages": {name: importlib.metadata.version(name) for name in PACKAGES},
    "external_tools": {"pdftoppm": tool("pdftoppm"), "soffice": tool("soffice")},
}
payload["ready"] = all(item["available"] for item in payload["external_tools"].values())
print(json.dumps(payload, ensure_ascii=False, indent=2))
raise SystemExit(0 if payload["ready"] else 1)
