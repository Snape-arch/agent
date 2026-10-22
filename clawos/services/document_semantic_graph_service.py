from __future__ import annotations

import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W, "r": R, "m": M, "a": A, "wp": WP}


def _compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _bbox(values: Any) -> list[float]:
    try:
        return [round(float(item), 2) for item in list(values)[:4]]
    except (TypeError, ValueError):
        return []


def _node_id(prefix: str, page: int, index: int) -> str:
    return f"{prefix}:p{int(page)}:{int(index)}"


def _label(value: str) -> str:
    match = re.search(r"(?i)(?<![A-Za-z])(fig(?:ure)?\.?|table|图|表)\s*([A-Z]?\d+(?:[.-]\d+)*)", value or "")
    if not match:
        return ""
    kind = "figure" if match.group(1).lower().startswith("fig") or match.group(1) == "图" else "table"
    return f"{kind}:{match.group(2).lower()}"


class DocumentSemanticGraphService:
    """Layout-preserving PDF/DOCX parser with explicit semantic relations."""

    SCHEMA = "clawos.document-semantic-graph.v1"

    def __init__(self, *, ocr_language: str | None = None, tessdata_dir: str | Path | None = None):
        from services.document_ocr_service import DocumentOCRService
        self.ocr_service = DocumentOCRService(language=ocr_language, tessdata_dir=tessdata_dir)

    def parse(self, path: str | Path) -> dict[str, Any]:
        source = Path(path)
        suffix = source.suffix.lower()
        if suffix == ".pdf":
            return self.parse_pdf(source)
        if suffix == ".docx":
            return self.parse_docx(source)
        raise ValueError(f"unsupported semantic document format: {suffix}")

    def parse_pdf(self, path: str | Path) -> dict[str, Any]:
        try:
            import fitz
        except Exception as exc:
            raise RuntimeError("PyMuPDF is required for layout-preserving PDF parsing") from exc

        path = Path(path)
        nodes: list[dict[str, Any]] = []
        pages: list[dict[str, Any]] = []
        figures: list[dict[str, Any]] = []
        formulas: list[dict[str, Any]] = []
        footnotes: list[dict[str, Any]] = []
        references: list[dict[str, Any]] = []
        ocr_pages: list[dict[str, Any]] = []
        font_sizes: list[float] = []
        raw_pages: list[dict[str, Any]] = []
        with fitz.open(str(path)) as document:
            for page_number, page in enumerate(document, 1):
                page_dict = page.get_text("dict") or {}
                raw_blocks = []
                for raw in page_dict.get("blocks") or []:
                    if int(raw.get("type", 0)) != 0:
                        continue
                    lines, spans, text_rows = [], [], []
                    for line in raw.get("lines") or []:
                        line_text = "".join(str(span.get("text") or "") for span in line.get("spans") or [])
                        if line_text.strip():
                            lines.append({"text": line_text, "bbox": _bbox(line.get("bbox"))})
                            text_rows.append(line_text)
                        for span in line.get("spans") or []:
                            text = str(span.get("text") or "")
                            size = round(float(span.get("size") or 0), 2)
                            if text.strip() and size > 0:
                                font_sizes.append(size)
                            spans.append({
                                "text": text, "bbox": _bbox(span.get("bbox")), "font": str(span.get("font") or ""),
                                "size": size, "flags": int(span.get("flags") or 0), "color": int(span.get("color") or 0),
                            })
                    text = "\n".join(text_rows).strip()
                    if text:
                        raw_blocks.append({"bbox": _bbox(raw.get("bbox")), "text": text, "lines": lines, "spans": spans})
                ordered, columns = self._pdf_reading_order(raw_blocks, float(page.rect.width or 0))
                raw_pages.append({
                    "page": page_number, "width": round(float(page.rect.width), 2),
                    "height": round(float(page.rect.height), 2), "rotation": int(page.rotation or 0),
                    "columns": columns, "blocks": ordered, "page_object": page,
                })
                image_info = page.get_image_info(xrefs=True) if hasattr(page, "get_image_info") else []
                raw_pages[-1]["images"] = image_info or []
                raw_pages[-1]["unrotated_size"] = [page.cropbox.width, page.cropbox.height]
                for image_index, image in enumerate(image_info or [], 1):
                    node = {
                        "id": _node_id("figure", page_number, image_index), "type": "figure", "page": page_number,
                        "bbox": _bbox(image.get("bbox")), "xref": int(image.get("xref") or 0),
                        "width": int(image.get("width") or 0), "height": int(image.get("height") or 0),
                        "locator": f"page={page_number}&figure={image_index}",
                    }
                    figures.append(node)
                    nodes.append(node)

        body_size = statistics.median(font_sizes) if font_sizes else 10.0
        section_stack: list[tuple[int, str]] = []
        current_section = ""
        in_references = False
        for raw_page in raw_pages:
            page_number = raw_page["page"]
            height = float(raw_page["height"] or 1)
            page_nodes = []
            text_length = 0
            for order, block in enumerate(raw_page["blocks"], 1):
                text = _compact(block["text"])
                text_length += len(text)
                sizes = [float(span.get("size") or 0) for span in block["spans"] if span.get("text", "").strip()]
                max_size = max(sizes, default=body_size)
                mean_size = statistics.mean(sizes) if sizes else body_size
                bbox = block["bbox"]
                block_type = "paragraph"
                heading_level = 0
                if self._is_heading(text, max_size, body_size):
                    block_type = "heading"
                    heading_level = self._heading_level(text, max_size, body_size)
                    current_section = text
                    section_stack = [item for item in section_stack if item[0] < heading_level]
                    section_stack.append((heading_level, text))
                    if re.fullmatch(r"(?i)(references|bibliography|参考文献|参考资料)", re.sub(r"^\d+(?:\.\d+)*\s*", "", text).strip()):
                        in_references = True
                    elif in_references and re.match(r"^(?:[A-Z]|\d+)\s*[.)]?\s*\S+", text, re.I):
                        in_references = False
                elif self._is_formula(text, block, raw_page["width"]):
                    block_type = "formula"
                elif re.match(r"(?i)^(fig(?:ure)?|图)\s*[A-Z]?\d+", text):
                    block_type = "figure_caption"
                elif re.match(r"(?i)^(table|表)\s*[A-Z]?\d+", text):
                    block_type = "table_caption"
                elif re.match(r"(?i)^Permission to make (?:digital|copies)", text):
                    block_type = "page_notice"
                elif (
                    mean_size <= body_size * 0.82
                    and bool(bbox)
                    and bbox[1] >= height * 0.72
                    and 20 <= len(text) <= 900
                ):
                    block_type = "footnote"
                elif in_references and len(text) >= 16:
                    block_type = "reference"
                node = {
                    "id": _node_id(block_type, page_number, order), "type": block_type, "page": page_number,
                    "order": order, "bbox": bbox, "text": text, "raw_text": block["text"],
                    "style": {"max_font_size": round(max_size, 2), "mean_font_size": round(mean_size, 2),
                              "fonts": sorted({span["font"] for span in block["spans"] if span.get("font")})},
                    "heading_level": heading_level, "section_path": [item[1] for item in section_stack],
                    "locator": f"page={page_number}&block={order}", "spans": block["spans"],
                }
                nodes.append(node)
                page_nodes.append(node["id"])
                if block_type == "formula":
                    formulas.append({**node, "representation": "pdf_region+positioned_text", "formula_text": block["text"],
                                     "visual_region": {"page": page_number, "bbox": bbox}})
                elif block_type == "footnote":
                    footnotes.append(node)
                elif block_type == "reference":
                    references.append(node)
            reason = self._pdf_ocr_reason(raw_page, text_length)
            ocr = {"page": page_number, "required": bool(reason), "status": "not_required", "words": []}
            if ocr["required"]:
                ocr = self._ocr_pdf_page(path, page_number)
                ocr.update(required=True, trigger=reason)
                ocr_pages.append(ocr)
                for index, word in enumerate(ocr.get("words") or [], 1):
                    node = {
                        **word,
                        "id": _node_id("ocr_word", page_number, index), "type": "ocr_word", "page": page_number,
                        "text": word["text"], "bbox": word["bbox"], "confidence": word["confidence"],
                        "locator": f"page={page_number}&ocr_word={index}",
                    }
                    nodes.append(node)
                for index, line in enumerate(ocr.get("lines") or [], 1):
                    if any(self._same_positioned_text(line, block) for block in raw_page["blocks"]):
                        continue
                    node = {**line, "id": _node_id("ocr_line", page_number, index), "type": "ocr_line",
                            "page": page_number, "locator": f"page={page_number}&ocr_line={index}",
                            "word_ids": [_node_id("ocr_word", page_number, i) for i in line["word_indices"]],
                            "coordinate_space": "unrotated_page_points", "language": ocr.get("language", "")}
                    nodes.append(node)
                    page_nodes.append(node["id"])
            pages.append({
                "page": page_number, "width": raw_page["width"], "height": raw_page["height"],
                "rotation": raw_page["rotation"], "column_count": raw_page["columns"],
                "reading_order": page_nodes, "ocr": ocr,
            })

        references = self._expand_pdf_references(nodes, pages, references)
        tables = self._pdf_tables(path, [n for n in nodes if n["type"] == "table_caption"])
        tables.extend(table for ocr in ocr_pages for table in ocr.get("tables", []))
        nodes.extend(tables)
        relations = self._relations(nodes, figures, tables)
        relations.extend({"type": "word_of", "source": word_id, "target": node["id"]}
                         for node in nodes if node["type"] == "ocr_line" for word_id in node["word_ids"])
        self._attach_table_structure(nodes, relations, tables)
        for page in pages:
            if not page["ocr"].get("required"):
                continue
            visible = [n for n in nodes if n.get("page") == page["page"] and n.get("text") and n["type"] not in {"ocr_word", "table_cell", "table", "table_row_group"} and not n.get("superseded_by_table")]
            visible.sort(key=lambda n: (n["bbox"][1], n["bbox"][0]))
            page["reading_order"] = [n["id"] for n in visible]
        order = {key: i for page in pages for i,key in enumerate(page["reading_order"])}
        nodes.sort(key=lambda n: (n.get("page",0), order.get(n["id"],100000)))
        evidence_units = self._evidence_units(nodes)
        graph = {
            "schema": self.SCHEMA, "format": "pdf", "source": str(path), "pages": pages,
            "nodes": nodes, "relations": relations,
            "sections": [node for node in nodes if node["type"] == "heading"],
            "tables": tables, "figures": figures,
            "formulas": formulas, "footnotes": footnotes, "references": references,
            "comments": [], "revisions": [], "evidence_units": evidence_units, "ocr_pages": ocr_pages,
            "recognition_text": "\f".join(page["ocr"].get("reading_text", "") for page in pages),
            "plain_text": "\f".join("\n".join(
                (node.get("text") if node.get("type") == "ocr_line" else node.get("raw_text") or node.get("text")) or "" for node in nodes
                if node.get("page") == page["page"] and node.get("type") not in {"figure", "table", "table_cell", "table_row_group", "ocr_word"} and not node.get("superseded_by_table")
            ) for page in pages),
            "quality": self._quality("pdf", pages, nodes, tables, figures, formulas, footnotes, references, ocr_pages),
        }
        return graph

    @staticmethod
    def _pdf_ocr_reason(page: dict, text_length: int) -> str:
        if text_length < 20:
            return "insufficient_native_text"
        width, height = page["unrotated_size"]
        area = max(1.0, width * height)
        for image in page.get("images", []):
            box = image.get("bbox", [])
            if len(box) != 4:
                continue
            x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), min(width, box[2]), min(height, box[3])
            if max(0, x1-x0) * max(0, y1-y0) < area * 0.20:
                continue
            # A substantial raster region with no native body text must be inspected,
            # even when a digital page header exceeds the legacy character threshold.
            inside = sum(len(span.get("text", "").strip())
                         for block in page["blocks"] for span in block["spans"]
                         if len(span.get("bbox", [])) == 4
                         and x0 <= (span["bbox"][0]+span["bbox"][2])/2 <= x1
                         and y0 + (y1-y0)*0.15 <= (span["bbox"][1]+span["bbox"][3])/2 <= y1 - (y1-y0)*0.15)
            if inside < 20:
                return "uncovered_raster_region"
        return ""

    @staticmethod
    def _same_positioned_text(line: dict, block: dict) -> bool:
        box = line.get("bbox", [])
        if len(box) != 4:
            return False
        for native in block.get("lines", []):
            other = native.get("bbox", [])
            if len(other) != 4:
                continue
            overlap = max(0, min(box[2], other[2])-max(box[0], other[0])) * max(0, min(box[3], other[3])-max(box[1], other[1]))
            area = max(1, (box[2]-box[0]) * (box[3]-box[1]))
            if overlap / area >= 0.5 and _compact(line.get("text")).casefold() == _compact(native.get("text")).casefold():
                return True
        return False

    def parse_docx(self, path: str | Path, *, recover_rendered_pages: bool = False) -> dict[str, Any]:
        path = Path(path)
        with zipfile.ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        if "word/document.xml" not in parts:
            raise ValueError("DOCX has no word/document.xml")
        document = ET.fromstring(parts["word/document.xml"])
        styles = self._docx_styles(parts)
        comments_map = self._docx_comments(parts)
        notes = self._docx_notes(parts)
        relationships = self._docx_relationships(parts)
        nodes: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        comments: list[dict[str, Any]] = []
        revisions: list[dict[str, Any]] = []
        formulas: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        figures: list[dict[str, Any]] = []
        footnotes: list[dict[str, Any]] = []
        section_stack: list[tuple[int, str]] = []
        page = 1
        paragraph_index = table_index = figure_index = 0
        body = document.find("w:body", NS)
        for child in list(body) if body is not None else []:
            if child.tag == f"{{{W}}}p":
                paragraph_index += 1
                parsed = self._docx_paragraph(child, paragraph_index, page, styles, relationships)
                page += int(parsed.pop("page_breaks", 0))
                if not parsed.get("text") and not parsed.get("formulas") and not parsed.get("figures"):
                    continue
                if parsed["type"] == "heading":
                    level = int(parsed.get("heading_level") or 1)
                    section_stack = [item for item in section_stack if item[0] < level]
                    section_stack.append((level, parsed["text"]))
                parsed["section_path"] = [item[1] for item in section_stack]
                nodes.append(parsed)
                for formula in parsed.pop("formulas", []):
                    formula["section_path"] = list(parsed["section_path"])
                    nodes.append(formula); formulas.append(formula)
                    relations.append({"type": "contained_by", "source": formula["id"], "target": parsed["id"], "confidence": 1.0})
                for figure in parsed.pop("figures", []):
                    figure_index += 1
                    figure["id"] = _node_id("figure", int(figure.get("page") or parsed["page"]), figure_index)
                    figure["section_path"] = list(parsed["section_path"])
                    nodes.append(figure); figures.append(figure)
                    relations.append({"type": "contained_by", "source": figure["id"], "target": parsed["id"], "confidence": 1.0})
                for revision in parsed.pop("revisions", []):
                    revision["target_id"] = parsed["id"]
                    revisions.append(revision)
                    relations.append({"type": "revises", "source": revision["id"], "target": parsed["id"], "confidence": 1.0})
                for comment_id, anchor in parsed.pop("comment_anchors", {}).items():
                    row = {**comments_map.get(comment_id, {"id": comment_id, "text": ""}),
                           "anchor_text": anchor, "target_id": parsed["id"], "page": parsed["page"]}
                    comments.append(row)
                    relations.append({"type": "comments_on", "source": f"comment:{comment_id}", "target": parsed["id"], "confidence": 1.0})
                for note_id in parsed.pop("footnote_refs", []):
                    row = {**notes.get(("footnote", note_id), {"text": ""}), "target_id": parsed["id"], "page": parsed["page"]}
                    row["id"] = f"footnote:{note_id}"
                    footnotes.append(row)
                    relations.append({"type": "footnote_for", "source": row["id"], "target": parsed["id"], "confidence": 1.0})
            elif child.tag == f"{{{W}}}tbl":
                table_index += 1
                table = self._docx_table(child, table_index, page, section_stack)
                tables.append(table); nodes.append(table)

        layout_recovery = {"status": "not_requested", "engine": "", "page_count": max(1, page), "mapped_ratio": 0.0}
        if recover_rendered_pages:
            layout_recovery = self._recover_docx_rendered_pages(path, nodes)
            page = int(layout_recovery.get("page_count") or page)
            node_pages = {node["id"]: int(node.get("page") or 1) for node in nodes}
            for item in comments + revisions + footnotes:
                if item.get("target_id") in node_pages:
                    item["page"] = node_pages[item["target_id"]]
        relations.extend(self._relations(nodes, figures, tables))
        bookmarks = {
            name: node["id"] for node in nodes for name in (node.get("bookmarks") or []) if name
        }
        for relation in relations:
            target = str(relation.get("target") or "")
            if relation.get("type") == "cross_reference" and target.startswith("bookmark:"):
                name = target.split(":", 1)[1]
                if name in bookmarks:
                    relation["bookmark"] = name
                    relation["target"] = bookmarks[name]
        references = self._docx_reference_nodes(nodes)
        evidence_units = self._evidence_units(nodes) + [
            {"id": item["id"], "type": "footnote", "text": item.get("text", ""), "page": item.get("page", 0),
             "locator": f"footnote={item['id'].split(':')[-1]}", "section_path": []}
            for item in footnotes if item.get("text")
        ]
        pages = [
            {"page": number,
             "layout_status": "rendered_page_recovered" if layout_recovery.get("status") == "completed" else "logical_page_from_breaks",
             "reading_order": [node["id"] for node in nodes if int(node.get("page") or 1) == number]}
            for number in range(1, max(1, page) + 1)
        ]
        return {
            "schema": self.SCHEMA, "format": "docx", "source": str(path), "pages": pages,
            "nodes": nodes, "relations": relations,
            "sections": [node for node in nodes if node.get("type") == "heading"],
            "tables": tables, "figures": figures, "formulas": formulas,
            "footnotes": footnotes, "references": references,
            "comments": comments, "revisions": revisions, "evidence_units": evidence_units,
            "layout_recovery": layout_recovery,
            "plain_text": "\n".join(node.get("text", "") for node in nodes if node.get("text")),
            "quality": self._quality("docx", pages, nodes, tables, figures, formulas, footnotes, references, []),
        }

    def semantic_chunks(self, graph: dict[str, Any], size: int = 1800) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for unit in graph.get("evidence_units") or []:
            text = str(unit.get("text") or "").strip()
            if not text:
                continue
            key = (int(unit.get("page") or 0), tuple(unit.get("section_path") or []), bool(unit.get("review_required")))
            if current is None or current["key"] != key or key[2] or len(current["content"]) + len(text) > size:
                if current:
                    rows.append(current)
                current = {"key": key, "content": text, "page_number": key[0], "node_ids": [unit["id"]],
                           "locators": [unit.get("locator", "")], "evidence_types": [unit.get("type", "")],
                           "review_required": key[2], "recognition_confidences": []}
            else:
                current["content"] += "\n" + text
                current["node_ids"].append(unit["id"])
                current["locators"].append(unit.get("locator", ""))
                current["evidence_types"].append(unit.get("type", ""))
            if "recognition_confidence" in unit:
                current["recognition_confidences"].append(unit["recognition_confidence"])
        if current:
            rows.append(current)
        for index, row in enumerate(rows, 1):
            row.pop("key", None)
            row["page_chunk_index"] = sum(1 for other in rows[:index] if other.get("page_number") == row.get("page_number"))
            row["node_ids"] = list(dict.fromkeys(row["node_ids"]))
            row["locators"] = list(dict.fromkeys(item for item in row["locators"] if item))
            row["evidence_types"] = sorted(set(row["evidence_types"]))
            confidences = row.pop("recognition_confidences")
            if confidences:
                row["recognition_confidence_min"] = min(confidences)
        return rows

    @staticmethod
    def _pdf_reading_order(blocks: list[dict[str, Any]], page_width: float) -> tuple[list[dict[str, Any]], int]:
        default = sorted(blocks, key=lambda item: (item["bbox"][1], item["bbox"][0]))
        if page_width <= 0 or len(blocks) < 4:
            return default, 1
        midpoint = page_width / 2
        spanning = [item for item in blocks if item["bbox"][0] <= page_width * 0.2 and item["bbox"][2] >= page_width * 0.8]
        columns = [item for item in blocks if item not in spanning]
        left = [item for item in columns if (item["bbox"][0] + item["bbox"][2]) / 2 < midpoint]
        right = [item for item in columns if item not in left]
        if len(left) < 2 or len(right) < 2 or max(item["bbox"][2] for item in left) > min(item["bbox"][0] for item in right) + page_width * 0.06:
            return default, 1
        ordered: list[dict[str, Any]] = []
        boundaries = sorted(spanning, key=lambda item: item["bbox"][1])
        previous_y = -math.inf
        for boundary in boundaries:
            cutoff = boundary["bbox"][1]
            ordered.extend(sorted([item for item in left if previous_y <= item["bbox"][1] < cutoff], key=lambda item: item["bbox"][1]))
            ordered.extend(sorted([item for item in right if previous_y <= item["bbox"][1] < cutoff], key=lambda item: item["bbox"][1]))
            ordered.append(boundary)
            previous_y = boundary["bbox"][3]
        ordered.extend(sorted([item for item in left if item["bbox"][1] >= previous_y], key=lambda item: item["bbox"][1]))
        ordered.extend(sorted([item for item in right if item["bbox"][1] >= previous_y], key=lambda item: item["bbox"][1]))
        seen = {id(item) for item in ordered}
        ordered.extend(item for item in default if id(item) not in seen)
        return ordered, 2

    @staticmethod
    def _is_heading(text: str, max_size: float, body_size: float) -> bool:
        clean = _compact(text)
        numbered = bool(re.match(r"^(?:\d{1,2}(?:\.\d{1,2}){0,4}|[IVX]+)[.)]?\s+(?=[A-Za-z一-鿿])", clean, re.I))
        named = bool(re.fullmatch(r"(?i)(abstract|introduction|background|method(?:s|ology)?|experiments?|results?|discussion|limitations?|conclusion|references|appendix|摘要|引言|方法|实验|结果|讨论|局限|结论|参考文献)", clean))
        excluded = bool(re.search(r"(?i)(?:@|\barxiv:|\buniversity\b|\binstitute\b|\bcorresponding authors?\b)", clean))
        numeric_tokens = len(re.findall(r"(?:^|\s)[+\-−]?\d+(?:\.\d+)?(?=\s|$)", clean))
        numeric_dense = numeric_tokens >= 3 and numeric_tokens / max(1, len(clean.split())) >= 0.45
        return 2 <= len(clean) <= 160 and not excluded and not numeric_dense and (named or numbered or max_size >= body_size * 1.16)

    @staticmethod
    def _heading_level(text: str, max_size: float, body_size: float) -> int:
        match = re.match(r"^(\d+(?:\.\d+)*)", text)
        if match:
            return min(6, match.group(1).count(".") + 1)
        return 1 if max_size >= body_size * 1.55 else (2 if max_size >= body_size * 1.28 else 3)

    @staticmethod
    def _is_formula(text: str, block: dict[str, Any], page_width: float) -> bool:
        compact = _compact(text)
        fonts = " ".join(span.get("font", "") for span in block.get("spans") or []).lower()
        math_chars = len(re.findall(r"[=/+*∑∏∫√≤≥±×÷∞∂∇α-ωΑ-Ω_^{}]", compact))
        centered = bool(block.get("bbox")) and abs((block["bbox"][0] + block["bbox"][2]) / 2 - page_width / 2) < page_width * 0.14
        return len(compact) <= 420 and ("math" in fonts or math_chars >= 2 or (centered and bool(re.search(r"\([0-9]+\)$", compact)) and "=" in compact))

    def _pdf_tables(self, path: Path, captions: list[dict] | None = None) -> list[dict[str, Any]]:
        try:
            import pdfplumber
        except Exception:
            return []
        tables = []
        with pdfplumber.open(str(path)) as pdf:
            for page_number, page in enumerate(pdf.pages, 1):
                try:
                    found = page.find_tables() or []
                except Exception:
                    found = []
                for index, table in enumerate(found, 1):
                    extracted = table.extract() or []
                    rows = [[_compact(cell) for cell in row] for row in extracted]
                    header = rows[0] if rows else []
                    cells = []
                    for row_index, row in enumerate(rows):
                        for column_index, value in enumerate(row):
                            cells.append({"row": row_index, "column": column_index, "text": value,
                                          "header_refs": [f"c{column_index}"] if row_index > 0 and column_index < len(header) else []})
                    tables.append({
                        "id": _node_id("table", page_number, index), "type": "table", "page": page_number,
                        "bbox": _bbox(getattr(table, "bbox", [])), "rows": rows, "header_rows": 1 if rows else 0,
                        "headers": header, "cells": cells, "text": "\n".join(" | ".join(row) for row in rows),
                        "locator": f"page={page_number}&table={index}",
                    })
        if captions:
            import fitz
            from .pdf_table_structure import RuledTableRecovery
            with fitz.open(str(path)) as document:
                for page in document:
                    page_captions = [c for c in captions if c.get("page") == page.number + 1]
                    if not page_captions:
                        continue
                    for recovered in RuledTableRecovery().extract(page, page_captions):
                        region = fitz.Rect(recovered["bbox"])
                        tables = [table for table in tables if table["page"] != recovered["page"] or
                                  (fitz.Rect(table["bbox"]) & region).get_area() / max(1, fitz.Rect(table["bbox"]).get_area()) < 0.8]
                        tables.append(recovered)
        for table in tables:
            table["source_filename"] = path.name
        return tables[:500]

    @staticmethod
    def _attach_table_structure(nodes: list[dict], relations: list[dict], tables: list[dict]) -> None:
        """Publish row evidence with its conditions; bare numeric cells are unsafe context."""
        for table in tables:
            if table.get("representation") not in {"ruled_region_glyph_grid", "raster_header_grid"}:
                continue
            x0, y0, x1, y1 = table["bbox"]
            for node in nodes:
                box = node.get("bbox", [])
                if node.get("type") in {"paragraph", "heading", "formula", "ocr_line"} and node.get("page") == table["page"] and len(box) == 4:
                    if x0 - 2 <= box[0] and box[2] <= x1 + 2 and y0 - 2 <= box[1] and box[3] <= y1 + 2:
                        node["superseded_by_table"] = table["id"]
            for group in table["row_groups"]:
                nodes.append({**group, "type": "table_row_group", "page": table["page"]})
                relations.append({"type": "contained_by", "source": group["id"], "target": table["id"], "confidence": 0.9})
            for cell in table["cells"]:
                nodes.append({**{k: v for k, v in cell.items() if k != "glyphs"}, "type": "table_cell", "page": table["page"]})
                relations.append({"type": "cell_of", "source": cell["id"], "target": table["id"], "confidence": 0.9})
                for word_index in cell.get("word_indices", []):
                    relations.append({"type": "word_in_cell", "source": _node_id("ocr_word",table["page"],word_index), "target": cell["id"]})
                for ref in cell.get("header_refs", []) + cell.get("group_refs", []):
                    relations.append({"type": "conditioned_by", "source": cell["id"], "target": ref, "confidence": 0.9})
            for index in range(1, len(table["rows"])):
                cells = [c for c in table["cells"] if c["row"] == index]
                first = cells[0]
                parts = [table.get("caption", ""), first.get("group_context", ""), first.get("row_context", "")]
                parts.extend(f"{c['column_header']} = {c['text']}" for c in cells)
                row_id = f"{table['id']}:row:{index}"
                boxes = [c["bbox"] for c in cells if c.get("bbox")]
                row_box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
                nodes.append({"id": row_id, "type": "table_row", "page": table["page"],
                              "text": " | ".join(p for p in parts if p), "bbox": row_box,
                              "cell_ids": [c["id"] for c in cells],
                              **({"confidence": min(c["confidence"] for c in cells), "review_required": any(c["review_required"] for c in cells),
                                  "recognition_source": "ocr"} if table.get("representation") == "raster_header_grid" else {}),
                              "locator": f"{table['locator']}&row={index}"})
                relations.append({"type": "row_of", "source": row_id, "target": table["id"], "confidence": 0.9})

    @staticmethod
    def _expand_pdf_references(nodes: list[dict[str, Any]], pages: list[dict[str, Any]], references: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Split multi-citation layout blocks and exclude running headers from references."""
        replacements: dict[str, list[dict[str, Any]]] = {}
        expanded: list[dict[str, Any]] = []
        for node in references:
            text = _compact(node.get("text"))
            if len(text) < 16 or (len(text) < 220 and re.search(r"(?i)(?:^UIST\s|Generative Agents UIST|Preprint\.$)", text)):
                replacements[str(node["id"])] = [{**node, "type": "page_header"}]
                continue
            starts = list(re.finditer(r"(?<!\S)\[\d{1,4}\]\s*", text))
            boundaries = [match.start() for match in starts]
            if len(boundaries) >= 2:
                if boundaries[0] > 0:
                    boundaries.insert(0, 0)
                boundaries.append(len(text))
                parts = [text[boundaries[index]:boundaries[index + 1]].strip() for index in range(len(boundaries) - 1)]
                parts = [part for part in parts if len(part) >= 16]
            else:
                parts = [text]
            rows = []
            for index, part in enumerate(parts, 1):
                row = {**node, "id": f"{node['id']}:citation:{index}", "text": part, "raw_text": part,
                       "locator": f"{node.get('locator', '')}&citation={index}"}
                rows.append(row)
                expanded.append(row)
            replacements[str(node["id"])] = rows
        if replacements:
            rebuilt = []
            for node in nodes:
                rebuilt.extend(replacements.get(str(node.get("id")), [node]))
            nodes[:] = rebuilt
            for page in pages:
                order = []
                for node_id in page.get("reading_order") or []:
                    if str(node_id) in replacements:
                        order.extend(item["id"] for item in replacements[str(node_id)])
                    else:
                        order.append(node_id)
                page["reading_order"] = order
        return expanded

    def _ocr_pdf_page(self, path: Path, page_number: int) -> dict[str, Any]:
        return self.ocr_service.recognize(path, page_number)

    @staticmethod
    def _parse_tesseract_tsv(value: str, scale: float = 1.0) -> list[dict[str, Any]]:
        from services.document_ocr_service import DocumentOCRService
        return DocumentOCRService.parse_tsv(value, scale)

    def _docx_styles(self, parts: dict[str, bytes]) -> dict[str, dict[str, Any]]:
        if "word/styles.xml" not in parts:
            return {}
        root = ET.fromstring(parts["word/styles.xml"])
        rows = {}
        for style in root.findall("w:style", NS):
            style_id = style.get(f"{{{W}}}styleId", "")
            name = style.find("w:name", NS)
            outline = style.find("w:pPr/w:outlineLvl", NS)
            size = style.find("w:rPr/w:sz", NS)
            bold = style.find("w:rPr/w:b", NS)
            rows[style_id] = {"name": name.get(f"{{{W}}}val", style_id) if name is not None else style_id,
                              "outline_level": int(outline.get(f"{{{W}}}val", "-1")) if outline is not None else -1,
                              "font_size_half_points": int(size.get(f"{{{W}}}val", "0")) if size is not None and size.get(f"{{{W}}}val", "").isdigit() else 0,
                              "bold": bold is not None and bold.get(f"{{{W}}}val", "1") not in {"0", "false", "off"}}
        return rows

    def _docx_comments(self, parts: dict[str, bytes]) -> dict[str, dict[str, Any]]:
        if "word/comments.xml" not in parts:
            return {}
        root = ET.fromstring(parts["word/comments.xml"])
        rows = {}
        for node in root.findall("w:comment", NS):
            comment_id = node.get(f"{{{W}}}id", "")
            rows[comment_id] = {"id": f"comment:{comment_id}", "comment_id": comment_id,
                                "author": node.get(f"{{{W}}}author", ""), "date": node.get(f"{{{W}}}date", ""),
                                "text": _compact("".join(node.itertext()))}
        return rows

    def _docx_notes(self, parts: dict[str, bytes]) -> dict[tuple[str, str], dict[str, Any]]:
        rows = {}
        for kind in ("footnote", "endnote"):
            name = f"word/{kind}s.xml"
            if name not in parts:
                continue
            root = ET.fromstring(parts[name])
            for node in root.findall(f"w:{kind}", NS):
                note_id = node.get(f"{{{W}}}id", "")
                if note_id.startswith("-") or note_id == "0":
                    continue
                rows[(kind, note_id)] = {"note_id": note_id, "kind": kind, "text": _compact("".join(node.itertext()))}
        return rows

    def _docx_relationships(self, parts: dict[str, bytes]) -> dict[str, dict[str, str]]:
        name = "word/_rels/document.xml.rels"
        if name not in parts:
            return {}
        root = ET.fromstring(parts[name])
        return {item.get("Id", ""): {"target": item.get("Target", ""), "type": item.get("Type", "")}
                for item in root.findall(f"{{{PKG_REL}}}Relationship")}

    def _docx_paragraph(self, paragraph: ET.Element, index: int, page: int, styles: dict[str, dict[str, Any]], relationships: dict[str, dict[str, str]]) -> dict[str, Any]:
        style_node = paragraph.find("w:pPr/w:pStyle", NS)
        style_id = style_node.get(f"{{{W}}}val", "") if style_node is not None else ""
        style = styles.get(style_id, {"name": style_id, "outline_level": -1, "font_size_half_points": 0, "bold": False})
        outline = int(style.get("outline_level", -1))
        if outline < 0 and re.match(r"(?i)^heading\s*([1-9])", str(style.get("name", ""))):
            outline = int(re.match(r"(?i)^heading\s*([1-9])", str(style.get("name", ""))).group(1)) - 1
        accepted, original = [], []
        revisions = []
        for child in paragraph.iter():
            if child.tag == f"{{{W}}}ins":
                text = _compact("".join(node.text or "" for node in child.iter(f"{{{W}}}t")))
                accepted.append(text)
                revisions.append({"id": f"revision:ins:{index}:{len(revisions)+1}", "type": "insertion", "new_text": text,
                                  "author": child.get(f"{{{W}}}author", ""), "date": child.get(f"{{{W}}}date", "")})
            elif child.tag == f"{{{W}}}del":
                text = _compact("".join(node.text or "" for node in child.iter(f"{{{W}}}delText")))
                original.append(text)
                revisions.append({"id": f"revision:del:{index}:{len(revisions)+1}", "type": "deletion", "old_text": text,
                                  "author": child.get(f"{{{W}}}author", ""), "date": child.get(f"{{{W}}}date", "")})
        normal = []
        for text_node in paragraph.iter(f"{{{W}}}t"):
            if not any(parent is not None and parent.tag == f"{{{W}}}ins" for parent in []):
                normal.append(text_node.text or "")
        # Avoid double counting insertion text collected above.
        insertion_texts = [item.get("new_text", "") for item in revisions if item["type"] == "insertion"]
        normal_text = "".join(normal)
        for value in insertion_texts:
            normal_text = normal_text.replace(value, "", 1)
        text = _compact(normal_text + " " + " ".join(accepted))
        original_text = _compact(normal_text + " " + " ".join(original))
        sizes = [
            int(node.get(f"{{{W}}}val", "0"))
            for node in paragraph.findall(".//w:sz", NS)
            if node.get(f"{{{W}}}val", "").isdigit()
        ]
        direct_size = max(sizes, default=int(style.get("font_size_half_points") or 0))
        direct_bold = bool(paragraph.findall(".//w:b", NS)) or bool(style.get("bold"))
        inferred_level, heading_reason = self._docx_heading_inference(text, outline, style, direct_size, direct_bold, index)
        if outline < 0 and inferred_level:
            outline = inferred_level - 1
        node_type = "heading" if outline >= 0 else "paragraph"
        if re.search(r"(?i)caption|题注", str(style.get("name", ""))):
            label_text = _compact("".join(node.text or "" for node in paragraph.iter(f"{{{W}}}t")))
            if re.match(r"(?i)^(fig(?:ure)?|图)\s*[A-Z]?\d+", label_text):
                node_type = "figure_caption"
            elif re.match(r"(?i)^(table|表)\s*[A-Z]?\d+", label_text):
                node_type = "table_caption"
        comment_ids = [item.get(f"{{{W}}}id", "") for item in paragraph.iter(f"{{{W}}}commentRangeStart")]
        comment_anchors = {item: text for item in comment_ids}
        footnote_refs = [item.get(f"{{{W}}}id", "") for item in paragraph.iter(f"{{{W}}}footnoteReference")]
        formulas = []
        for formula_index, math in enumerate(paragraph.findall(".//m:oMath", NS), 1):
            formula_text = _compact("".join(node.text or "" for node in math.iter(f"{{{M}}}t")))
            formulas.append({"id": _node_id("formula", page, index * 100 + formula_index), "type": "formula", "page": page,
                             "text": formula_text, "omml": ET.tostring(math, encoding="unicode"),
                             "representation": "omml", "locator": f"paragraph={index}&formula={formula_index}"})
        figures = []
        for drawing_index, drawing in enumerate(paragraph.findall(".//w:drawing", NS), 1):
            doc_pr = drawing.find(".//wp:docPr", NS)
            blip = drawing.find(".//a:blip", NS)
            rel_id = blip.get(f"{{{R}}}embed", "") if blip is not None else ""
            figures.append({"type": "figure", "page": page, "relationship_id": rel_id,
                            "target": relationships.get(rel_id, {}).get("target", ""),
                            "title": doc_pr.get("title", "") if doc_pr is not None else "",
                            "alt_text": doc_pr.get("descr", "") if doc_pr is not None else "",
                            "locator": f"paragraph={index}&figure={drawing_index}"})
        fields = [_compact(node.text) for node in paragraph.iter(f"{{{W}}}instrText") if _compact(node.text)]
        bookmarks = [node.get(f"{{{W}}}name", "") for node in paragraph.iter(f"{{{W}}}bookmarkStart")]
        breaks = sum(1 for node in paragraph.iter(f"{{{W}}}br") if node.get(f"{{{W}}}type", "") == "page")
        breaks += sum(1 for _ in paragraph.iter(f"{{{W}}}lastRenderedPageBreak"))
        return {
            "id": _node_id(node_type, page, index), "type": node_type, "page": page, "order": index,
            "text": text, "original_text": original_text, "style_id": style_id, "style_name": style.get("name", ""),
            "heading_level": outline + 1 if outline >= 0 else 0, "fields": fields,
            "heading_inference": heading_reason, "font_size_points": round(direct_size / 2.0, 2) if direct_size else 0.0,
            "bold": direct_bold,
            "bookmarks": bookmarks,
            "locator": f"paragraph={index}", "formulas": formulas, "figures": figures, "revisions": revisions,
            "comment_anchors": comment_anchors, "footnote_refs": footnote_refs, "page_breaks": breaks,
        }

    @staticmethod
    def _docx_heading_inference(text: str, outline: int, style: dict[str, Any], size: int, bold: bool, index: int) -> tuple[int, str]:
        clean = _compact(text)
        if outline >= 0:
            return min(6, outline + 1), "outline_level"
        style_name = str(style.get("name") or "")
        match = re.match(r"(?i)^heading\s*([1-9])", style_name)
        if match:
            return int(match.group(1)), "heading_style"
        decimal = re.match(r"^(\d+(?:\.\d+){1,5})\s*", clean)
        if decimal and len(clean) <= 180:
            return min(6, decimal.group(1).count(".") + 1), "decimal_numbering"
        if re.match(r"^[一二三四五六七八九十百]+[、.]\s*\S+", clean) and len(clean) <= 180:
            return 1, "chinese_numbering"
        if re.match(r"^(?:第[一二三四五六七八九十百\d]+章|Chapter\s+\d+)\b", clean, re.I) and len(clean) <= 180:
            return 1, "chapter_numbering"
        if index == 1 and len(clean) <= 180 and (size >= 28 or re.search(r"说明书|报告|计划书|白皮书|Report|Proposal", clean, re.I)):
            return 1, "document_title"
        metadata_label = re.match(
            r"^(?:项目名称|英文(?:名称)?|English(?:\s+title)?|作者|日期|版本|单位|联系人)\s*[:：]",
            clean,
            re.I,
        )
        if bold and size >= 24 and len(clean) <= 120 and not metadata_label and not re.match(r"[•·\-]", clean):
            return 2 if size < 28 else 1, "direct_formatting"
        return 0, ""

    @staticmethod
    def _recover_docx_rendered_pages(path: Path, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        soffice = Path("C:/Program Files/LibreOffice/program/soffice.com")
        executable = str(soffice) if soffice.is_file() else (shutil.which("soffice.exe") or shutil.which("soffice") or "")
        if not executable:
            return {"status": "engine_unavailable", "engine": "", "page_count": 1, "mapped_ratio": 0.0}
        try:
            import fitz
            with tempfile.TemporaryDirectory(prefix="clawos-docx-layout-") as td:
                root = Path(td); profile = root / "profile"
                result = subprocess.run([
                    executable, f"-env:UserInstallation={profile.as_uri()}", "--headless",
                    "--convert-to", "pdf", "--outdir", str(root), str(path),
                ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
                pdf = root / f"{path.stem}.pdf"
                if result.returncode != 0 or not pdf.is_file():
                    return {"status": "failed", "engine": "libreoffice", "page_count": 1,
                            "mapped_ratio": 0.0, "error": result.stderr[-500:]}
                with fitz.open(str(pdf)) as document:
                    page_texts = [re.sub(r"\s+", "", page.get_text("text")) for page in document]
                mapped = 0
                paragraph_pages: dict[str, int] = {}
                content_nodes = [node for node in nodes if node.get("text")]
                for node in content_nodes:
                    needle = re.sub(r"\s+", "", str(node.get("text") or ""))
                    probes = [needle[: min(48, len(needle))]]
                    if len(needle) > 48:
                        probes.append(needle[-32:])
                    matches = [
                        page_index for page_index, page_text in enumerate(page_texts, 1)
                        if any(len(probe) >= 6 and probe in page_text for probe in probes)
                    ]
                    if matches:
                        node["page"] = matches[0]; node["rendered_page_confidence"] = 1.0 if len(matches) == 1 else 0.7
                        mapped += 1
                        locator = str(node.get("locator") or "")
                        para_match = re.search(r"paragraph=(\d+)", locator)
                        if para_match:
                            paragraph_pages[para_match.group(1)] = matches[0]
                current_page = 1
                for node in nodes:
                    locator = str(node.get("locator") or "")
                    para_match = re.search(r"paragraph=(\d+)", locator)
                    if para_match and para_match.group(1) in paragraph_pages:
                        node["page"] = paragraph_pages[para_match.group(1)]
                    current_page = max(current_page, int(node.get("page") or current_page))
                    node["page"] = current_page
                return {"status": "completed", "engine": "libreoffice", "page_count": len(page_texts),
                        "mapped_nodes": mapped, "total_text_nodes": len(content_nodes),
                        "mapped_ratio": round(mapped / max(1, len(content_nodes)), 4)}
        except Exception as exc:
            return {"status": "failed", "engine": "libreoffice", "page_count": 1, "mapped_ratio": 0.0,
                    "error": f"{type(exc).__name__}: {exc}"}

    def _docx_table(self, table: ET.Element, index: int, page: int, section_stack: list[tuple[int, str]]) -> dict[str, Any]:
        rows, cells = [], []
        header_rows = 0
        for row_index, tr in enumerate(table.findall("w:tr", NS)):
            is_header = tr.find("w:trPr/w:tblHeader", NS) is not None
            header_rows += int(is_header and row_index == header_rows)
            values = []
            column = 0
            for tc in tr.findall("w:tc", NS):
                text = _compact("".join(node.text or "" for node in tc.iter(f"{{{W}}}t")))
                grid_span_node = tc.find("w:tcPr/w:gridSpan", NS)
                grid_span = int(grid_span_node.get(f"{{{W}}}val", "1")) if grid_span_node is not None else 1
                vmerge = tc.find("w:tcPr/w:vMerge", NS)
                merge = vmerge.get(f"{{{W}}}val", "continue") if vmerge is not None else ""
                values.append(text)
                cells.append({"row": row_index, "column": column, "text": text, "grid_span": grid_span,
                              "vertical_merge": merge, "is_header": is_header,
                              "header_refs": [f"r{h}c{column}" for h in range(header_rows)] if row_index >= header_rows else []})
                column += grid_span
            rows.append(values)
        return {"id": _node_id("table", page, index), "type": "table", "page": page,
                "rows": rows, "cells": cells, "header_rows": header_rows, "headers": rows[:header_rows],
                "text": "\n".join(" | ".join(row) for row in rows), "section_path": [item[1] for item in section_stack],
                "locator": f"table={index}"}

    @staticmethod
    def _docx_reference_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result, active = [], False
        for node in nodes:
            if node.get("type") == "heading" and re.search(r"(?i)references|bibliography|参考文献", node.get("text", "")):
                active = True
                continue
            if active and node.get("type") == "heading":
                active = False
            if active and node.get("type") == "paragraph" and len(node.get("text", "")) >= 16:
                result.append({**node, "type": "reference"})
        return result

    def _relations(self, nodes: list[dict[str, Any]], figures: list[dict[str, Any]], tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        relations = []
        labels: dict[str, str] = {}
        visual_nodes = figures + tables
        for node in nodes:
            if node.get("type") in {"figure_caption", "table_caption", "paragraph"}:
                label = _label(node.get("text", ""))
                if label and node.get("type") in {"figure_caption", "table_caption"}:
                    target_type = "figure" if node.get("type") == "figure_caption" else "table"
                    candidates = [item for item in visual_nodes if item.get("page") == node.get("page") and item.get("type") == target_type and not item.get("semantic_only")]
                    if not candidates:
                        target = {
                            "id": _node_id(f"inferred_{target_type}", int(node.get("page") or 1), len(visual_nodes) + 1),
                            "type": target_type, "page": node.get("page"), "bbox": [], "semantic_only": True,
                            "representation": "caption_inferred_region", "confidence": 0.65,
                            "locator": f"{node.get('locator', '')}&inferred_{target_type}=1",
                        }
                        nodes.append(target)
                        visual_nodes.append(target)
                        (figures if target_type == "figure" else tables).append(target)
                        candidates = [target]
                    if candidates:
                        target = min(candidates, key=lambda item: (item.get("caption_id") != node["id"], self._distance(node.get("bbox"), item.get("bbox"))))
                        confidence = 0.65 if target.get("semantic_only") else 0.9
                        relations.append({"type": "caption_of", "source": node["id"], "target": target["id"], "confidence": confidence})
                        labels[label] = target["id"]
        for node in nodes:
            if node.get("type") not in {"paragraph", "heading"}:
                continue
            for match in re.finditer(r"(?i)(?<![A-Za-z])(?:fig(?:ure)?\.?|table|图|表)\s*[A-Z]?\d+(?:[.-]\d+)*", node.get("text", "")):
                label = _label(match.group(0))
                if label in labels and labels[label] != node["id"]:
                    relations.append({"type": "references", "source": node["id"], "target": labels[label], "confidence": 0.95})
            for field in node.get("fields") or []:
                match = re.search(r"(?i)\bREF\s+([^\s]+)", field)
                if match:
                    relations.append({"type": "cross_reference", "source": node["id"], "target": f"bookmark:{match.group(1)}", "confidence": 1.0})
        return relations

    @staticmethod
    def _distance(left: Any, right: Any) -> float:
        if not left or not right:
            return 1e9
        return abs(float(left[1]) - float(right[3])) + abs(float(left[0]) - float(right[0])) * 0.1

    @staticmethod
    def _evidence_units(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        accepted = {"paragraph", "heading", "table", "table_row", "formula", "footnote", "reference", "ocr_line", "figure_caption", "table_caption", "page_notice"}
        return [{"id": node["id"], "type": node["type"], "text": node.get("text", ""),
                 "page": int(node.get("page") or 0), "bbox": node.get("bbox") or [],
                 **({"recognition_confidence": node["confidence"], "review_required": node.get("review_required", False),
                     "word_ids": node.get("word_ids", []), "language": node.get("language", "")} if node["type"] == "ocr_line" or node.get("recognition_source") == "ocr" else {}),
                 "locator": node.get("locator", ""), "section_path": node.get("section_path") or []}
                for node in nodes if node.get("type") in accepted and node.get("text") and node.get("representation") not in {"ruled_region_glyph_grid", "raster_header_grid"} and not node.get("superseded_by_table")]

    @staticmethod
    def _quality(fmt: str, pages: list, nodes: list, tables: list, figures: list, formulas: list,
                 footnotes: list, references: list, ocr_pages: list) -> dict[str, Any]:
        references_expected = any(
            node.get("type") == "heading" and re.search(r"(?i)references|bibliography|参考文献", node.get("text", ""))
            for node in nodes
        )
        checks = {
            "reading_order": bool(pages) and all(page.get("reading_order") or fmt == "docx" for page in pages),
            "coordinates": fmt == "docx" or any(node.get("bbox") for node in nodes),
            "heading_hierarchy": any(node.get("type") == "heading" for node in nodes),
            "table_headers": not tables or all("header_rows" in item and "cells" in item for item in tables),
            "figure_relations_ready": not figures or all(item.get("locator") for item in figures),
            "formula_fidelity": not formulas or all(item.get("representation") in {"omml", "positioned_text", "pdf_region+positioned_text"} for item in formulas),
            "footnote_links": not footnotes or all(item.get("id") for item in footnotes),
            "references_identified": not references_expected or bool(references),
            "ocr_coordinates": not ocr_pages or all(item.get("status") == "completed" and item.get("words") for item in ocr_pages),
        }
        return {"checks": checks, "score": round(sum(bool(value) for value in checks.values()) / len(checks) * 100, 2),
                "measurement_scope": "structural_integrity_only", "semantic_accuracy_evaluated": False,
                "gate": "pass" if all(checks.values()) else "revision_required",
                "ocr_truth_boundary": "OCR coordinates require a configured Tesseract engine; unavailable pages remain explicitly blocked."}


def graph_json(graph: dict[str, Any]) -> str:
    return json.dumps(graph, ensure_ascii=False, sort_keys=True)
