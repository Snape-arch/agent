from __future__ import annotations

import hashlib
import html
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any
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
        if end < len(clean):
            window = clean[start:end]
            boundary = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "), window.rfind("。"))
            if boundary >= int(size * 0.62):
                end = start + boundary + (1 if window[boundary:boundary + 1] in {"\n", "。"} else 2)
        chunks.append(clean[start:end].strip())
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
    try:
        from services.document_semantic_graph_service import DocumentSemanticGraphService

        graph = DocumentSemanticGraphService().parse_pdf(path)
        if str(graph.get("plain_text") or "").strip() or graph.get("ocr_pages"):
            grobid_meta = _extract_pdf_with_grobid(path)
            if grobid_meta:
                graph["scholarly_metadata"] = grobid_meta
                if grobid_meta.get("references"):
                    known = {_compact_reference(item.get("text", "")) for item in graph.get("references") or []}
                    for index, raw in enumerate(grobid_meta["references"], 1):
                        if _compact_reference(raw) not in known:
                            graph.setdefault("references", []).append({
                                "id": f"grobid-reference:{index}", "type": "reference", "text": raw,
                                "page": 0, "locator": f"grobid-reference={index}", "source": "grobid-tei",
                            })
            structure = {
                "title": (grobid_meta or {}).get("title", ""),
                "authors": (grobid_meta or {}).get("authors", []),
                "abstract": (grobid_meta or {}).get("abstract", ""),
                "sections": graph.get("sections") or [], "tables": graph.get("tables") or [],
                "figures": graph.get("figures") or [], "formulas": graph.get("formulas") or [],
                "footnotes": graph.get("footnotes") or [], "references": graph.get("references") or [],
                "relations": graph.get("relations") or [], "layout_pages": graph.get("pages") or [],
                "reading_order": "semantic_graph",
            }
            attempted_ocr = [item["page"] for item in graph.get("pages") or [] if (item.get("ocr") or {}).get("required")]
            ocr_pages = [item["page"] for item in graph.get("pages") or []
                         if (item.get("ocr") or {}).get("required") and (item.get("ocr") or {}).get("status") != "completed"]
            return str(graph["plain_text"]), {
                "extractor": "document-semantic-graph+pymupdf+pdfplumber" + ("+grobid" if grobid_meta else ""),
                "page_count": len(graph.get("pages") or []), "ocr_required": bool(ocr_pages),
                "ocr_pages": ocr_pages, "layout_aware": True, "structure": structure,
                "ocr_attempted_pages": attempted_ocr,
                "ocr_review_pages": [item["page"] for item in graph.get("ocr_pages") or [] if item.get("review_required")],
                "semantic_graph": graph, "semantic_quality": graph.get("quality") or {},
            }
    except (ImportError, OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        pass
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
    layout_pages: list[dict] = []
    with fitz.open(str(path)) as doc:
        for page_index, page in enumerate(doc, 1):
            blocks = page.get_text("blocks") or []
            lines: list[str] = []
            ordered_blocks, column_count = _order_pdf_text_blocks(blocks, float(page.rect.width or 0))
            page_layout = {"page": page_index, "column_count": column_count, "blocks": []}
            for order_index, block in enumerate(ordered_blocks, 1):
                text = str(block[4] or "").strip()
                if not text:
                    continue
                lines.append(text)
                page_layout["blocks"].append({
                    "order": order_index,
                    "bbox": [round(float(value), 2) for value in block[:4]],
                    "text": re.sub(r"\s+", " ", text)[:240],
                })
                compact = re.sub(r"\s+", " ", text)
                if len(compact) <= 90 and re.match(r"^(\d+(\.\d+)*\s+)?[A-Z\u4e00-\u9fff][\w\s:：\-]{4,}$", compact):
                    sections.append({"page": page_index, "title": compact[:120]})
            for image_index, _image in enumerate(page.get_images(full=True), 1):
                figures.append({"page": page_index, "index": image_index})
            pages.append("\n".join(lines))
            layout_pages.append(page_layout)
    return pages, {"structure": {"sections": sections[:80], "figures": figures[:200], "layout_pages": layout_pages[:200], "reading_order": "column_aware"}}


def _order_pdf_text_blocks(blocks: list, page_width: float) -> tuple[list, int]:
    """Approximate human reading order for common one- and two-column papers."""
    text_blocks = [block for block in blocks if len(block) >= 5 and str(block[4] or "").strip()]
    default_order = sorted(text_blocks, key=lambda item: (round(item[1], 1), round(item[0], 1)))
    if page_width <= 0 or len(text_blocks) < 4:
        return default_order, 1
    midpoint = page_width / 2
    spanning = [block for block in text_blocks if float(block[0]) <= page_width * 0.22 and float(block[2]) >= page_width * 0.78]
    non_spanning = [block for block in text_blocks if block not in spanning]
    left = [block for block in non_spanning if (float(block[0]) + float(block[2])) / 2 < midpoint]
    right = [block for block in non_spanning if (float(block[0]) + float(block[2])) / 2 >= midpoint]
    if len(left) < 2 or len(right) < 2:
        return default_order, 1
    if max(float(block[2]) for block in left) > min(float(block[0]) for block in right) + page_width * 0.08:
        return default_order, 1
    first_column_y = min(float(block[1]) for block in non_spanning)
    top_spanning = [block for block in spanning if float(block[1]) <= first_column_y + 8]
    remaining_spanning = [block for block in spanning if block not in top_spanning]
    ordered = (
        sorted(top_spanning, key=lambda item: (round(item[1], 1), round(item[0], 1)))
        + sorted(left, key=lambda item: (round(item[1], 1), round(item[0], 1)))
        + sorted(right, key=lambda item: (round(item[1], 1), round(item[0], 1)))
        + sorted(remaining_spanning, key=lambda item: (round(item[1], 1), round(item[0], 1)))
    )
    return ordered, 2


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


def _compact_reference(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())[:600]


def extract_docx_text(path: Path) -> tuple[str, dict]:
    try:
        from services.document_semantic_graph_service import DocumentSemanticGraphService

        graph = DocumentSemanticGraphService().parse_docx(path, recover_rendered_pages=True)
        if str(graph.get("plain_text") or "").strip():
            return str(graph["plain_text"]), {
                "extractor": "document-semantic-graph+docx-ooxml", "ocr_required": False,
                "page_count": len(graph.get("pages") or []), "layout_aware": True,
                "structure": {
                    "sections": graph.get("sections") or [], "tables": graph.get("tables") or [],
                    "figures": graph.get("figures") or [], "formulas": graph.get("formulas") or [],
                    "footnotes": graph.get("footnotes") or [], "references": graph.get("references") or [],
                    "comments": graph.get("comments") or [], "revisions": graph.get("revisions") or [],
                    "relations": graph.get("relations") or [],
                },
                "semantic_graph": graph, "semantic_quality": graph.get("quality") or {},
            }
    except (ImportError, OSError, RuntimeError, ValueError, zipfile.BadZipFile):
        pass
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
    semantic_graph = metadata.get("semantic_graph") if isinstance(metadata.get("semantic_graph"), dict) else {}
    if semantic_graph:
        try:
            from services.document_semantic_graph_service import DocumentSemanticGraphService
            chunks = DocumentSemanticGraphService().semantic_chunks(semantic_graph)
        except (ImportError, TypeError, ValueError):
            chunks = chunk_text_with_pages(text)
    else:
        chunks = chunk_text_with_pages(text)
    with store.transaction():
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
                store.delete_knowledge_by_source_prefix(f"doc:{document['id']}#")
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
            status="needs_ocr" if metadata.get("ocr_required") else ("needs_review" if metadata.get("ocr_review_pages") else "ready"),
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
            chunk_metadata = {
                "page_number": page_number, "page_chunk_index": page_chunk,
                "node_ids": chunk_info.get("node_ids") or [], "locators": chunk_info.get("locators") or [],
                "evidence_types": chunk_info.get("evidence_types") or [],
                "review_required": bool(chunk_info.get("review_required")),
                "recognition_confidence_min": chunk_info.get("recognition_confidence_min"),
            }
            store.add_document_chunk(document["id"], index, chunk, citation, metadata=chunk_metadata)
            # Keep uncertain OCR available for source inspection, but do not silently
            # promote its potentially corrupted numbers/conditions into knowledge.
            if chunk_metadata["review_required"]:
                continue
            item = store.add_knowledge(
                title=f"{document['title']} p.{page_number} #{page_chunk}" if page_number else f"{document['title']} #{index}",
                content=f"{chunk}\n\nSource: {citation}",
                category=category or "domain",
                source=citation,
                tags=["document", Path(source_path.name).suffix.lower().lstrip(".")],
                confidence=0.85,
            )
            knowledge_ids.append(int(item["id"]))
            try:
                from services.knowledge_core_service import KnowledgeCoreService
                core = KnowledgeCoreService(store)
                source_chunk_id = int(item.get("knowledge_v2_id") or 0)
                for claim in core.extract_claims(chunk):
                    claim_title = re.sub(r"\s+", " ", claim).strip()[:120]
                    core.absorb(
                        title=claim_title,
                        statement=claim,
                        category=category or "domain",
                        knowledge_type="claim",
                        source_ref=citation,
                        source_type="document_claim",
                        excerpt=claim,
                        locator=core.source_locator(citation),
                        confidence=0.82,
                        entities=core.infer_entities(document["title"], claim, [Path(source_path.name).suffix.lower().lstrip(".")]),
                        relations=[{"type": "derived_from", "target_kind": "knowledge", "target_id": source_chunk_id, "confidence": 1.0}] if source_chunk_id else [],
                        metadata={
                            "document_id": document["id"],
                            "chunk_index": index,
                            "page_number": page_number,
                            "claim_type": core.classify_claim(claim),
                            "semantic_node_ids": chunk_metadata["node_ids"],
                            "semantic_locators": chunk_metadata["locators"],
                            "evidence_types": chunk_metadata["evidence_types"],
                        },
                        changed_by="document_ingestion",
                    )
            except (ImportError, OSError, ValueError, TypeError):
                raise
        document["chunk_count"] = len(chunks)
        document["knowledge_ids"] = knowledge_ids
        document["metadata"] = metadata
        return document
