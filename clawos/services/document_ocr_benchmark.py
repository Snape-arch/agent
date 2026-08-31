"""Position-aware, CJK-sensitive development evaluation of real rasterized pages."""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from services.document_semantic_graph_service import DocumentSemanticGraphService


def characters(text: str) -> str:
    return "".join(re.findall(r"[a-z0-9\u3400-\u9fff]", text.casefold()))


def edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def score(reference: str, actual: str, source_words: list, words: list, bounds: list) -> dict:
    expected, found = characters(reference), characters(actual)
    cjk_expected = Counter(re.findall(r"[\u3400-\u9fff]", expected))
    cjk_actual = Counter(re.findall(r"[\u3400-\u9fff]", found))
    cjk_match = sum((cjk_expected & cjk_actual).values())
    matched = sum((Counter(expected) & Counter(found)).values())
    positioned, valid, position_evaluated = 0, 0, 0
    for word in words:
        box = word["bbox"]
        valid += int(bounds[0] <= box[0] < box[2] <= bounds[2] and bounds[1] <= box[1] < box[3] <= bounds[3])
        # A box must overlap matching source text, not merely lie on the page.
        matching = "".join(str(s[4]) for s in source_words
                           if min(box[2], s[2]) > max(box[0], s[0]) and min(box[3], s[3]) > max(box[1], s[1]))
        token = characters(word["text"])
        if token:
            position_evaluated += 1
            positioned += int(token in characters(matching))
    return {
        "reference_characters": len(expected), "actual_characters": len(found),
        "character_recall": matched / max(1, len(expected)), "character_precision": matched / max(1, len(found)),
        "character_error_rate": edit_distance(expected, found) / max(1, len(expected)),
        "cjk_reference_characters": sum(cjk_expected.values()),
        "cjk_recall": cjk_match / sum(cjk_expected.values()) if cjk_expected else None,
        "cjk_precision": cjk_match / max(1, sum(cjk_actual.values())) if cjk_expected else None,
        "coordinate_validity": valid / max(1, len(words)),
        "text_position_hit_rate": positioned / max(1, position_evaluated),
        "positioned_hits": positioned, "position_evaluated_words": position_evaluated, "ocr_words": len(words),
    }


def evaluate(source: Path, pages: list[int], output: Path, *, language: str = "auto") -> dict:
    import fitz
    if not pages or len(set(pages)) != len(pages):
        raise ValueError("pages must be nonempty and unique")
    source = source.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    parser = DocumentSemanticGraphService(ocr_language=language)
    with fitz.open(source) as original:
        for number in pages:
            if not 1 <= number <= len(original):
                raise ValueError("page out of range")
            page = original[number - 1]
            reference = page.get_text()
            if len(characters(reference)) < 20:
                raise ValueError("Reference page needs native text; image-only reference cannot score itself")
            raster = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            scan_path = output / f"scan-p{number}.pdf"
            with fitz.open() as scan:
                p = scan.new_page(width=page.rect.width, height=page.rect.height)
                p.insert_image(p.rect, pixmap=raster)
                scan.save(scan_path)
            graph = parser.parse_pdf(scan_path)
            ocr = graph["ocr_pages"][0]
            # Source words are unrotated; rasterized page itself has no rotation.
            source_words = []
            for w in page.get_text("words"):
                source_words.append([*(fitz.Rect(w[:4]) * page.rotation_matrix), w[4]])
            # Semantic row evidence repeats headers deliberately; compare raw
            # recognition order, not the expanded evidence representation.
            metrics = score(reference, graph.get("recognition_text") or graph["plain_text"], source_words, ocr["words"], list(page.rect))
            checks = {"ocr_completed": ocr["status"] == "completed",
                      "character_recall": metrics["character_recall"] >= .9,
                      "character_precision": metrics["character_precision"] >= .9,
                      "reading_order_cer": metrics["character_error_rate"] <= .15,
                      "cjk_recall": metrics["cjk_recall"] is None or metrics["cjk_recall"] >= .9,
                      "coordinate_validity": metrics["coordinate_validity"] >= .99,
                      "text_position_hit_rate": metrics["text_position_hit_rate"] >= .85}
            # QA overlay, original raster unchanged. Boxes can be visually checked.
            with fitz.open(scan_path) as overlay:
                for word in ocr["words"]:
                    overlay[0].draw_rect(fitz.Rect(word["bbox"]), color=(0, .55, 0), width=.35)
                for table in graph.get("tables", []):
                    overlay[0].draw_rect(fitz.Rect(table["bbox"]),color=(0,.2,1),width=1)
                    for cell in table.get("cells",[]):
                        overlay[0].draw_rect(fitz.Rect(cell["bbox"]),color=(.9,0,0) if cell.get("review_required") else (.9,.5,0),width=.5)
                overlay[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(output / f"boxes-p{number}.png")
            import json
            (output / f"graph-p{number}.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
            rows.append({"page": number, "metrics": metrics, "checks": checks, "passed": all(checks.values()),
                         "language": ocr.get("language"), "status": ocr["status"],
                         "review_lines": sum(line["review_required"] for line in ocr.get("lines", [])),
                         "lines": len(ocr.get("lines", []))})
    return {"schema": "clawos.document-ocr-fidelity.v2", "source": str(source),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "rows": rows,
            "acceptance": {"passed": all(row["passed"] for row in rows)}, "release_claim_allowed": False,
            "truth_boundary": "Born-digital real pages rasterized at 216 DPI; native text and positions are references, not independent human labels. Character metrics ignore punctuation/case/spacing; CER also penalizes order differences. Not physical-scanner, handwriting, table-semantics or WPS parity evidence."}
