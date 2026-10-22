"""Conservative bitmap layout: header-grid anchored tables, no OCR text guesses."""
from __future__ import annotations

import re
import numpy as np


def runs(values):
    edges = np.flatnonzero(np.diff(np.r_[False, values, False].astype(np.int8)))
    return list(zip(edges[::2].tolist(), edges[1::2].tolist()))


class RasterDocumentLayout:
    def detect(self, image, scale: float) -> list[dict]:
        ink = np.asarray(image.convert("L")) < 150
        height, width = ink.shape
        horizontal = []
        for y in range(height):
            for x0, x1 in runs(ink[y]):
                if x1 - x0 >= max(90 * scale, width * .3):
                    if horizontal and y - horizontal[-1]["bottom"] <= 2 and abs(x0 - horizontal[-1]["x0"]) <= 3 and abs(x1 - horizontal[-1]["x1"]) <= 3:
                        horizontal[-1]["bottom"] = y
                    else:
                        horizontal.append({"top": y, "bottom": y, "x0": x0, "x1": x1})
        regions = []
        for i, top in enumerate(horizontal):
            if any(r["pixel_bbox"][1] <= top["top"] < r["pixel_bbox"][3] for r in regions):
                continue
            matches = [h for h in horizontal[i+1:] if abs(h["x0"] - top["x0"]) <= 4 and abs(h["x1"] - top["x1"]) <= 4]
            if len(matches) < 2:
                continue
            header, bottom = matches[:2]
            gap = header["top"] - top["bottom"]
            if not 7 * scale < gap < 36 * scale or bottom["top"] - header["bottom"] < 12 * scale or bottom["top"] - top["top"] > height * .55:
                continue
            x0, x1 = top["x0"], top["x1"]
            vertical = ink[top["bottom"]+2:header["top"]-1, x0:x1].mean(axis=0) > .92
            dividers = [round((a+b)/2) + x0 for a, b in runs(vertical) if b-a <= max(5, 2*scale)]
            inner = [x for x in dividers if x0+8*scale < x < x1-8*scale]
            edges = [x0, *inner, x1]
            if not 3 <= len(edges) <= 13 or min(np.diff(edges)) < 22 * scale:
                continue
            row_rules = [header, bottom]
            for following in matches[2:]:
                if following["top"]-top["top"] > height*.55:
                    break
                strip = ink[bottom["bottom"]+2:following["top"]-1]
                if not len(strip) or not all(strip[:,max(0,x-2):x+3].any(axis=1).mean() > .92 for x in inner):
                    break
                bottom = following
                row_rules.append(bottom)
            # Only accept regions with real body ink in every header-defined column.
            body = ink[header["bottom"]+3:bottom["top"]-2]
            if any(body[:, a+3:b-3].sum() < 15*scale for a,b in zip(edges, edges[1:])):
                continue
            body_dividers = [round((a+b)/2)+x0 for a,b in runs(body[:,x0:x1].mean(axis=0)>.92)]
            if any(x0+8*scale < x < x1-8*scale and all(abs(x-edge)>4 for edge in edges) for x in body_dividers):
                # A merged header needs an explicit spanning-header model.
                continue
            # Blank horizontal strips are row-separator candidates, not guarantees.
            occupied = body[:, x0+3:x1-3].sum(axis=1) > 2*scale
            bands = []
            for a, b in runs(occupied):
                if bands and a-bands[-1][1] <= 3*scale:
                    bands[-1][1] = b
                else:
                    bands.append([a,b])
            regions.append({"type": "table_candidate", "pixel_bbox": [x0, top["top"], x1, bottom["bottom"]+1],
                            "bbox": [v/scale for v in [x0,top["top"],x1,bottom["bottom"]+1]],
                            "pixel_columns": edges, "pixel_header_bottom": header["bottom"],
                            "pixel_row_rules": [h["bottom"] for h in row_rules] if len(row_rules)>2 else [],
                            "body_bands": [[a+header["bottom"]+3,b+header["bottom"]+3] for a,b in bands],
                            "method": "bitmap_header_grid", "structure_status": "candidate"})
        return regions

    def recover(self, image, scale: float, recognize, verify=None) -> tuple[list[dict], list[dict]]:
        """Recognize isolated columns, assign words to geometric rows (pixel callback)."""
        tables, regions = [], self.detect(image, scale)
        budget = 160
        for region in regions:
            edges = region["pixel_columns"]
            bands = region["body_bands"]
            row_count = len(region["pixel_row_rules"])-1 if region["pixel_row_rules"] else len(bands)
            if not 2 <= row_count <= 40 or (row_count+1)*(len(edges)-1) > budget:
                region["structure_status"] = "ambiguous_or_budget_exceeded"
                continue
            budget -= (row_count+1)*(len(edges)-1)
            x0,y0,x1,y1 = region["pixel_bbox"]
            header_end = region["pixel_header_bottom"]
            boundaries = [header_end+2, *[round((a[1]+b[0])/2) for a,b in zip(bands,bands[1:])], y1-2]
            row_spans = [(y0+3,header_end-2), *list(zip(boundaries,boundaries[1:]))]
            if region["pixel_row_rules"]:
                row_spans = [(y0+3,header_end-2), *[(a+3,b-2) for a,b in zip(region["pixel_row_rules"],region["pixel_row_rules"][1:])]]
            from PIL import ImageDraw
            columns = []
            for left,right in zip(edges,edges[1:]):
                crop_box = [left+3,y0+3,right-3,y1-3]
                crop = image.crop(crop_box)
                draw = ImageDraw.Draw(crop)
                for rule in [header_end,*region["pixel_row_rules"]]:
                    y = rule-crop_box[1]
                    draw.rectangle([0,y-3,crop.width,y+2],fill="white")
                result = recognize(crop)
                for word in result["words"]:
                    box = word["bbox"]
                    word["bbox"] = [(box[0]+crop_box[0])/scale,(box[1]+crop_box[1])/scale,
                                    (box[2]+crop_box[0])/scale,(box[3]+crop_box[1])/scale]
                columns.append(result)
            cells, rows = [], []
            for r,(a,b) in enumerate(row_spans):
                values = []
                for c,(left,right) in enumerate(zip(edges,edges[1:])):
                    result = columns[c]
                    words = [w for w in result["words"] if a <= (w["bbox"][1]+w["bbox"][3])*scale/2 < b]
                    from services.document_ocr_service import DocumentOCRService
                    lines = DocumentOCRService.lines(words)
                    text = " ".join(line["text"] for line in lines)
                    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
                    confidence = min((line["confidence"] for line in lines), default=0)
                    crosses = any(w["bbox"][1]*scale < a-3 or w["bbox"][3]*scale > b+3 for w in words)
                    numeric = bool(r and re.search(r"\d",text))
                    critical = numeric or bool(re.search(r"不|未|无|仅|至少|至多|[<>≤≥%]|\b(?:not|no|without|only)\b", text, re.I))
                    mixed_script_suspect = bool(
                        re.search(r"[\u3400-\u9fff]", text)
                        and re.search(r"(?:\b[A-Z][lI1]\b|\b[A-Z]{2,}\d\b|[A-Z][a-z]+[A-Z][a-z]+)", text)
                    )
                    uncertain = confidence < .9 or mixed_script_suspect
                    verification = {"status": "not_requested", "candidates": []}
                    if verify and (critical or uncertain):
                        # A separate cell segmentation view, not a corrected truth.
                        verification = verify(image.crop((left+3,a,right-3,b)), text, confidence)
                    original_text = text
                    selection = verification.get("selection") or {}
                    if selection.get("auto_applied"):
                        text = str(selection.get("selected_text") or text)
                    numeric = bool(r and re.search(r"\d",text))
                    critical = numeric or bool(re.search(r"不|未|无|仅|至少|至多|[<>≤≥%]|\b(?:not|no|without|only)\b", text, re.I))
                    cells.append({"row": r,"column": c,"text": text,"value_text": text,
                                  "bbox": [left/scale,a/scale,right/scale,b/scale],"words": words,
                                  "confidence": confidence, "review_required": True,
                                  "review_reasons": ["scanned_cell_requires_source_confirmation"] + (["critical_value"] if critical else []) + (["recognizer_disagreement"] if verification["status"] == "disagreement" else []) + (["ocr_candidate_selected"] if selection.get("auto_applied") else []),
                                  "verification": verification, "original_text": original_text,
                                  "numeric_verification_required": numeric, "crosses_row_boundary": crosses,
                                  "recognition_status": result["status"], "is_header": r == 0})
                    values.append(text)
                rows.append(values)
            # An empty crop/header or sparse body cannot establish a table schema.
            headers = rows[0]
            if any(not h or len(h)>100 for h in headers) or len(set(headers)) != len(headers) or any(not row[0] for row in rows[1:]):
                region["structure_status"] = "recognition_incomplete"
                region["recognition_preview"] = rows
                continue
            region["structure_status"] = "reconstructed"
            tables.append({"bbox": region["bbox"], "rows": rows, "headers": headers, "header_rows": 1,
                           "cells": cells, "row_groups": [], "representation": "raster_header_grid",
                           "recovery": {"status": "reconstructed", "method": region["method"], "semantic_accuracy_evaluated": False}})
        return tables, regions
