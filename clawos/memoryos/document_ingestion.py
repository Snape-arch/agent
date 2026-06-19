from __future__ import annotations

import hashlib
import html
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree


TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".py", ".js", ".ts", ".html", ".htm"}


def safe_filename(name: str) -> str:
    stem = Path(name or "upload").name
    cleaned = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", stem).strip("._")
    return cleaned or "upload"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chunk_text(text: str, size: int = 1400, overlap: int = 180) -> list[str]:
    clean = "\n".join(line.rstrip() for line in str(text or "").splitlines()).strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + size)
        chunks.append(clean[start:end])
        if end >= len(clean):
            break
        start = max(start + 1, end - overlap)
    return chunks


def extract_text(path: Path) -> tuple[str, dict]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".docx":
        return extract_docx_text(path)
    if suffix in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        if suffix in {".html", ".htm"}:
            text = re.sub(r"<(script|style)[\s\S]*?</\1>", " ", text, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = html.unescape(text)
        return text, {"extractor": "text", "ocr_required": False}
    raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")


def extract_pdf_text(path: Path) -> tuple[str, dict]:
    executable = shutil.which("pdftotext")
    if executable:
        proc = subprocess.run(
            [executable, "-layout", str(path), "-"],
            capture_output=True,
            timeout=90,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:500])
        text = proc.stdout.decode("utf-8", errors="replace")
        pages = [p for p in text.split("\f") if p.strip()]
        ocr_pages = [i for i, page in enumerate(pages, 1) if len(page.strip()) < 20]
        return text, {
            "extractor": "pdftotext",
            "page_count": len(pages),
            "ocr_required": bool(ocr_pages),
            "ocr_pages": ocr_pages,
        }
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF extraction requires pdftotext or pypdf") from exc
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    ocr_pages = [i for i, page in enumerate(pages, 1) if len(page.strip()) < 20]
    return "\f".join(pages), {
        "extractor": "pypdf",
        "page_count": len(pages),
        "ocr_required": bool(ocr_pages),
        "ocr_pages": ocr_pages,
    }


def extract_docx_text(path: Path) -> tuple[str, dict]:
    paragraphs: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.startswith("word/") and n.endswith(".xml")]
        for name in ("word/document.xml", *[n for n in names if n != "word/document.xml"]):
            if name not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(name))
            for node in root.iter():
                if node.tag.endswith("}t") and node.text:
                    paragraphs.append(node.text)
                elif node.tag.endswith("}p"):
                    paragraphs.append("\n")
    text = " ".join(paragraphs)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip(), {"extractor": "docx-xml", "ocr_required": False}


def ingest_file(store, upload_dir: Path, source_path: Path, *, title: str = "", category: str = "domain") -> dict:
    upload_dir.mkdir(parents=True, exist_ok=True)
    digest = file_sha256(source_path)
    stored_name = f"{digest[:12]}_{safe_filename(source_path.name)}"
    stored_path = upload_dir / stored_name
    if source_path.resolve() != stored_path.resolve():
        shutil.copyfile(source_path, stored_path)
    text, metadata = extract_text(stored_path)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No extractable text found; OCR may be required")
    document = store.add_document(
        title=title or source_path.stem,
        filename=source_path.name,
        file_path=str(stored_path),
        file_hash=digest,
        mime_type=metadata.get("mime_type", ""),
        category=category or "domain",
        extractor=metadata.get("extractor", ""),
        status="ready",
        metadata=metadata,
    )
    knowledge_ids: list[int] = []
    for index, chunk in enumerate(chunks, 1):
        citation = f"doc:{document['id']}#chunk={index}"
        if index == 1 and hasattr(store, "delete_knowledge_by_source_prefix"):
            store.delete_knowledge_by_source_prefix(f"doc:{document['id']}#")
        store.add_document_chunk(document["id"], index, chunk, citation)
        item = store.add_knowledge(
            title=f"{document['title']} #{index}",
            content=f"{chunk}\n\nSource: {citation}",
            category=category or "domain",
            source=citation,
            tags=["document", Path(source_path.name).suffix.lower().lstrip(".")],
            confidence=0.85,
        )
        knowledge_ids.append(int(item["id"]))
    document["chunk_count"] = len(chunks)
    document["knowledge_ids"] = knowledge_ids
    document["metadata"] = metadata
    return document
