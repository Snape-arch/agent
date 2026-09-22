"""One conservative boundary between source inspection and usable evidence."""
from __future__ import annotations

from copy import deepcopy
import json
import re


def source_usable(connection, source: str) -> bool:
    """Recheck authoritative SQLite review state, not a vector cache's metadata."""
    match = re.match(r"^doc:(\d+)(?:#|$)", str(source))
    if not match:
        return True
    rows = connection.execute("SELECT citation,metadata FROM document_chunks WHERE document_id=?", (int(match[1]),)).fetchall()
    document = connection.execute("SELECT status,metadata FROM documents WHERE id=?", (int(match[1]),)).fetchone()
    if not document or not rows:
        return False
    exact = [row for row in rows if row["citation"] == source]
    # A fragment citation must resolve exactly, never to another surviving chunk.
    if '#' in str(source) and not exact:
        return False
    for row in exact or rows:
        try:
            if json.loads(row["metadata"]).get("review_required"):
                return False
        except (ValueError, TypeError, AttributeError):
            return False
    return True


def table_pending(table: dict) -> bool:
    return bool(table.get("review_required") or any(c.get("review_required") for c in table.get("cells", [])))


def safe_graph(graph: dict) -> dict:
    result = deepcopy(graph)
    blocked = {t["id"] for t in result.get("tables", []) if table_pending(t)}
    def usable(node):
        return not (node.get("review_required") or node.get("superseded_by_table")
                    or node.get("type") == "ocr_word"
                    or any(str(node.get("id", "")).startswith(t + ":") or node.get("id") == t for t in blocked))
    result["tables"] = [t for t in result.get("tables", []) if t.get("id") not in blocked]
    result["nodes"] = [n for n in result.get("nodes", []) if usable(n)]
    result["evidence_units"] = [n for n in result.get("evidence_units", []) if usable(n)]
    result["plain_text"] = "\n".join(n.get("text", "") for n in result["evidence_units"])
    result.pop("recognition_text", None)
    result.pop("ocr_pages", None)
    for page in result.get("pages", []):
        page.pop("ocr", None)
    # Alternate OCR hypotheses and superseded text are inspection-only, even
    # after correction. Do not leak them in a tool's otherwise safe JSON payload.
    def scrub(value):
        if isinstance(value, dict):
            for key in ("verification", "original_text", "human_review", "recognition_preview", "words", "lines", "reading_text"):
                value.pop(key, None)
            for child in value.values():
                scrub(child)
        elif isinstance(value, list):
            for child in value:
                scrub(child)
    scrub(result)
    allowed = {n.get("id") for n in result["nodes"]}
    result["relations"] = [r for r in result.get("relations", []) if r.get("source") in allowed and r.get("target") in allowed]
    result["withheld_table_count"] = len(blocked)
    return result


def safe_document(document: dict) -> dict:
    result = deepcopy(document)
    meta = result.get("metadata") or {}
    graph = meta.get("semantic_graph")
    if graph:
        graph = safe_graph(graph)
        meta["semantic_graph"] = graph
        structure = meta.get("structure") or {}
        for key in ("tables", "sections", "figures", "formulas", "references", "footnotes", "relations"):
            structure[key] = graph.get(key, [])
        # layout_pages is another copy of the raw OCR response.
        structure["layout_pages"] = graph.get("pages", [])
        meta["structure"] = structure
    result["metadata"] = meta
    return result
