from __future__ import annotations

import hashlib
import html
import os
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


def chunk_text_with_pages(text: str, size: int = 1400, overlap: int = 180) -> list[dict]:
    """Chunk text while preserving PDF page boundaries when form feeds exist."""
    pages = str(text or "").split("\f")
    if len(pages) <= 1:
        return [
            {"content": chunk, "page_number": 0, "page_chunk_index": index}
            for index, chunk in enumerate(chunk_text(text, size=size, overlap=overlap), 1)
        ]
    rows: list[dict] = []
    for page_number, page in enumerate(pages, 1):
        page_chunks = chunk_text(page, size=size, overlap=overlap)
        for page_chunk_index, chunk in enumerate(page_chunks, 1):
            rows.append({
                "content": chunk,
                "page_number": page_number,
                "page_chunk_index": page_chunk_index,
            })
    return rows


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
    enhanced_text, enhanced_meta = extract_pdf_text_enhanced(path)
    if enhanced_text.strip():
        return enhanced_text, enhanced_meta

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


def extract_pdf_text_enhanced(path: Path) -> tuple[str, dict]:
    """Try structure-aware offline PDF extraction before legacy text fallbacks."""
    engines: list[str] = []
    pages: list[str] = []
    structure: dict = {
        "sections": [],
        "tables": [],
        "figures": [],
        "references": [],
    }

    pymupdf_pages, pymupdf_meta = _extract_pdf_with_pymupdf(path)
    if pymupdf_pages:
        engines.append("pymupdf")
        pages = pymupdf_pages
        structure.update(pymupdf_meta.get("structure") or {})

    plumber_meta = _extract_pdf_with_pdfplumber(path)
    if plumber_meta:
        engines.append("pdfplumber")
        structure["tables"] = plumber_meta.get("tables", [])
        if not pages and plumber_meta.get("pages"):
            pages = plumber_meta["pages"]

    grobid_meta = _extract_pdf_with_grobid(path)
    if grobid_meta:
        engines.append("grobid")
        for key in ("title", "authors", "abstract", "sections", "references"):
            if grobid_meta.get(key):
                structure[key] = grobid_meta[key]

    if not pages:
        return "", {}
    ocr_pages = [i for i, page in enumerate(pages, 1) if len(page.strip()) < 20]
    return "\f".join(pages), {
        "extractor": "+".join(engines),
        "page_count": len(pages),
        "ocr_required": bool(ocr_pages),
        "ocr_pages": ocr_pages,
        "layout_aware": True,
        "structure": structure,
    }


def _extract_pdf_with_pymupdf(path: Path) -> tuple[list[str], dict]:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return [], {}
    pages: list[str] = []
    figures: list[dict] = []
    sections: list[dict] = []
    with fitz.open(str(path)) as doc:
        for page_index, page in enumerate(doc, 1):
            blocks = page.get_text("blocks") or []
            lines: list[str] = []
            for block in sorted(blocks, key=lambda item: (round(item[1], 1), round(item[0], 1))):
                text = str(block[4] or "").strip()
                if not text:
                    continue
                lines.append(text)
                compact = re.sub(r"\s+", " ", text)
                if len(compact) <= 90 and re.match(r"^(\d+(\.\d+)*\s+)?[A-Z\u4e00-\u9fff][\w\s:：\-]{4,}$", compact):
                    sections.append({"page": page_index, "title": compact[:120]})
            for image_index, _image in enumerate(page.get_images(full=True), 1):
                figures.append({"page": page_index, "index": image_index})
            pages.append("\n".join(lines))
    return pages, {"structure": {"sections": sections[:80], "figures": figures[:200]}}


def _extract_pdf_with_pdfplumber(path: Path) -> dict:
    try:
        import pdfplumber
    except Exception:
        return {}
    pages: list[str] = []
    tables: list[dict] = []
    with pdfplumber.open(str(path)) as pdf:
        for page_index, page in enumerate(pdf.pages, 1):
            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            pages.append(text)
            try:
                extracted = page.extract_tables() or []
            except Exception:
                extracted = []
            for table_index, table in enumerate(extracted, 1):
                rows = [[str(cell or "") for cell in row] for row in (table or [])]
                tables.append({"page": page_index, "index": table_index, "rows": rows[:20]})
    return {"pages": pages, "tables": tables[:100]}


def _extract_pdf_with_grobid(path: Path) -> dict:
    base_url = os.environ.get("GROBID_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        return {}
    try:
        import httpx
        from xml.etree import ElementTree as ET
    except Exception:
        return {}
    try:
        with path.open("rb") as handle:
            response = httpx.post(
                f"{base_url}/api/processFulltextDocument",
                files={"input": (path.name, handle, "application/pdf")},
                timeout=30,
            )
        if response.status_code >= 400:
            return {}
        root = ET.fromstring(response.text)
    except Exception:
        return {}
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    title = _tei_text(root.find(".//tei:titleStmt/tei:title", ns))
    authors = [_tei_text(node) for node in root.findall(".//tei:sourceDesc//tei:author", ns)]
    abstract = _tei_text(root.find(".//tei:abstract", ns))
    sections = [
        {"title": _tei_text(node)}
        for node in root.findall(".//tei:body//tei:head", ns)
        if _tei_text(node)
    ]
    references = [
        _tei_text(node)
        for node in root.findall(".//tei:listBibl//tei:biblStruct", ns)
        if _tei_text(node)
    ]
    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "sections": sections[:80],
        "references": references[:200],
    }


def _tei_text(node) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", " ".join(node.itertext())).strip()


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
    chunks = chunk_text_with_pages(text)
    if not chunks:
        if metadata.get("ocr_required"):
            document = store.add_document(
                title=title or source_path.stem,
                filename=source_path.name,
                file_path=str(stored_path),
                file_hash=digest,
                mime_type=metadata.get("mime_type", ""),
                category=category or "domain",
                extractor=metadata.get("extractor", ""),
                status="needs_ocr",
                metadata={**metadata, "ocr_reason": metadata.get("ocr_reason") or "no_extractable_text"},
            )
            document["chunk_count"] = 0
            document["knowledge_ids"] = []
            return document
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
    for index, chunk_info in enumerate(chunks, 1):
        chunk = chunk_info["content"]
        page_number = int(chunk_info.get("page_number") or 0)
        page_chunk = int(chunk_info.get("page_chunk_index") or index)
        citation = f"doc:{document['id']}#page={page_number}&chunk={page_chunk}" if page_number else f"doc:{document['id']}#chunk={index}"
        if index == 1 and hasattr(store, "delete_knowledge_by_source_prefix"):
            store.delete_knowledge_by_source_prefix(f"doc:{document['id']}#")
        store.add_document_chunk(document["id"], index, chunk, citation)
        item = store.add_knowledge(
            title=f"{document['title']} p.{page_number} #{page_chunk}" if page_number else f"{document['title']} #{index}",
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
