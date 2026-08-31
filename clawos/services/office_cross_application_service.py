"""Cross-application DOCX rendering evidence for Word, WPS and LibreOffice."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .office_visual_quality_service import OfficeVisualQualityService


class OfficeCrossApplicationService:
    """Render the same DOCX in installed office engines and compare their output."""

    SCHEMA = "clawos.office-cross-application.v1"

    def evaluate(self, source_docx: str | Path, output_dir: str | Path) -> dict[str, Any]:
        source = Path(source_docx).resolve()
        output = Path(output_dir).resolve()
        if not source.is_file() or source.suffix.lower() != ".docx":
            raise ValueError("source_docx must be an existing DOCX")
        output.mkdir(parents=True, exist_ok=True)
        # Every run has fresh targets: an old successful PDF must never mask a
        # failed COM export that returned zero without producing a new file.
        output = output / f"run-{uuid.uuid4().hex}"
        output.mkdir()
        engines = {
            "libreoffice": self._safe_render("libreoffice", self._libreoffice, source, output / "libreoffice.pdf"),
            "microsoft_word": self._safe_render("microsoft_word", self._com_export, source, output / "microsoft-word.pdf", "word"),
            "wps_writer": self._safe_render("wps_writer", self._com_export, source, output / "wps-writer.pdf", "wps"),
        }
        completed = {name: row for name, row in engines.items() if row.get("status") == "completed"}
        for row in completed.values():
            row["critical_evidence"] = OfficeVisualQualityService.rendered_note_checks(source, row["pdf"])
        comparisons = []
        baseline = completed.get("microsoft_word") or completed.get("libreoffice") or next(iter(completed.values()), None)
        if baseline:
            for name, row in completed.items():
                if row is baseline:
                    continue
                comparisons.append(self._compare(Path(baseline["pdf"]), Path(row["pdf"]), baseline["engine"], name))
        required = {"libreoffice", "microsoft_word", "wps_writer"}
        checks = {
            "all_required_engines_rendered": required <= set(completed),
            "page_count_parity": bool(comparisons) and all(item["page_count_equal"] for item in comparisons),
            "text_token_retention": bool(comparisons) and all(item["text_token_recall"] >= 0.97 for item in comparisons),
            "visual_similarity": bool(comparisons) and all(item["visual_similarity"] >= 0.90 for item in comparisons),
            "critical_evidence_preserved": required <= set(completed) and all(
                check["passed"] for row in completed.values() for check in row["critical_evidence"]
            ),
        }

        return {
            "schema": self.SCHEMA, "source": str(source), "source_sha256": self._sha(source),
            "engines": engines, "comparisons": comparisons,
            "acceptance": {"passed": all(checks.values()), "checks": checks},
            "truth_boundary": "Renderer parity checks page count, extracted-token retention and normalized raster similarity. It does not prove every interactive editing behavior is identical.",
        }

    @staticmethod
    def _safe_render(engine: str, renderer: Any, *args: Any) -> dict[str, Any]:
        try:
            return renderer(*args)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"engine": engine, "status": "failed", "failure_category": "environment_failure",
                    "timed_out": isinstance(exc, subprocess.TimeoutExpired), "error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _libreoffice(source: Path, target: Path) -> dict[str, Any]:
        known = Path("C:/Program Files/LibreOffice/program/soffice.com")
        executable = str(known) if known.is_file() else (shutil.which("soffice.exe") or shutil.which("soffice") or "")
        if not executable:
            return {"engine": "libreoffice", "status": "unavailable"}
        with tempfile.TemporaryDirectory(prefix="clawos-lo-cross-render-") as td:
            root = Path(td); profile = root / "profile"
            result = subprocess.run([
                executable, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf",
                "--outdir", str(root), str(source),
            ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            produced = root / f"{source.stem}.pdf"
            if result.returncode or not produced.is_file():
                return {"engine": "libreoffice", "status": "failed", "exit_code": result.returncode, "error": (result.stderr or result.stdout)[-1500:]}
            shutil.copy2(produced, target)
        return OfficeCrossApplicationService._pdf_result("libreoffice", target)

    @staticmethod
    def _com_export(source: Path, target: Path, kind: str) -> dict[str, Any]:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            return {"engine": kind, "status": "unavailable", "error": "PowerShell unavailable"}
        progids = ["Word.Application"] if kind == "word" else ["KWPS.Application", "WPS.Application"]
        with tempfile.TemporaryDirectory(prefix=f"clawos-{kind}-cross-render-") as td:
            script = Path(td) / "export.ps1"
            script.write_text(
                "param([string]$InputPath,[string]$OutputPath,[string[]]$ProgIds)\n"
                "$ErrorActionPreference='Stop'\n$app=$null\n$doc=$null\n"
                "try {\n foreach($id in $ProgIds){ try {$app=New-Object -ComObject $id; if($app){break}} catch {} }\n"
                " if(-not $app){throw 'No compatible COM application registered'}\n"
                " try {$app.Visible=$false} catch {}\n"
                " $doc=$app.Documents.Open($InputPath,$false,$true)\n"
                " $doc.ExportAsFixedFormat($OutputPath,17)\n"
                "} finally { if($doc){try{$doc.Close(0)}catch{}}; if($app){try{$app.Quit()}catch{}} }\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
                 "-InputPath", str(source), "-OutputPath", str(target), "-ProgIds", *progids],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240,
            )
        engine = "microsoft_word" if kind == "word" else "wps_writer"
        if result.returncode or not target.is_file():
            return {"engine": engine, "status": "failed", "exit_code": result.returncode, "error": (result.stderr or result.stdout)[-1500:]}
        return OfficeCrossApplicationService._pdf_result(engine, target)

    @staticmethod
    def _pdf_result(engine: str, path: Path) -> dict[str, Any]:
        try:
            import fitz
            with fitz.open(str(path)) as document:
                pages = len(document); text_chars = sum(len(page.get_text("text") or "") for page in document)
        except Exception as exc:
            return {"engine": engine, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        return {"engine": engine, "status": "completed", "pdf": str(path), "sha256": OfficeCrossApplicationService._sha(path), "pages": pages, "text_chars": text_chars}

    @staticmethod
    def _compare(left: Path, right: Path, baseline: str, candidate: str) -> dict[str, Any]:
        import fitz
        from PIL import Image, ImageChops, ImageFilter

        with fitz.open(str(left)) as left_doc, fitz.open(str(right)) as right_doc:
            left_text = " ".join(page.get_text("text") or "" for page in left_doc)
            right_text = " ".join(page.get_text("text") or "" for page in right_doc)
            left_tokens, right_tokens = Counter(OfficeCrossApplicationService._tokens(left_text)), Counter(OfficeCrossApplicationService._tokens(right_text))
            matched = sum(min(count, right_tokens[token]) for token, count in left_tokens.items())
            recall = matched / max(1, sum(left_tokens.values()))
            similarities = []
            for index in range(min(len(left_doc), len(right_doc))):
                images = []
                for document in (left_doc, right_doc):
                    pixmap = document[index].get_pixmap(matrix=fitz.Matrix(1.2, 1.2), colorspace=fitz.csGRAY, alpha=False)
                    image = Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples).resize((612, 792))
                    images.append(image.filter(ImageFilter.GaussianBlur(radius=0.5)))
                difference = ImageChops.difference(images[0], images[1])
                mean = sum(value * count for value, count in enumerate(difference.histogram())) / max(1, difference.width * difference.height)
                similarities.append(max(0.0, 1.0 - mean / 255.0))
            return {
                "baseline": baseline, "candidate": candidate, "page_count_equal": len(left_doc) == len(right_doc),
                "baseline_pages": len(left_doc), "candidate_pages": len(right_doc), "text_token_recall": round(recall, 6),
                "visual_similarity": round(sum(similarities) / max(1, len(similarities)), 6),
            }

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return [token.casefold() for token in re.findall(r"[\w]+", value or "", re.UNICODE) if len(token) >= 2]

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
