"""Conservative reconstruction of captioned, horizontally ruled PDF tables.

No whole-page text grid: require a bounded ruled region, separated headers and
repeated numeric rows. Keep glyph evidence and small-type annotations distinct.
"""
from __future__ import annotations

import bisect
import re
import statistics
from typing import Any


def bounds(items: list[dict]) -> list[float]:
    return [round(v, 3) for v in (
        min(i["bbox"][0] for i in items), min(i["bbox"][1] for i in items),
        max(i["bbox"][2] for i in items), max(i["bbox"][3] for i in items))] if items else []


def glyph_text(items: list[dict]) -> str:
    # Ligature-expanded glyphs can share an origin with tiny float differences.
    # Stable, quantized ordering preserves PDF character order for these ties.
    ordered = sorted(items, key=lambda i: round(i.get("origin_x", i["bbox"][0]), 3))
    result, previous = "", None
    for item in ordered:
        if previous and item["bbox"][0] - previous["bbox"][2] > max(1.0, item["size"] * 0.22):
            result += " "
        result += item["text"]
        previous = item
    return re.sub(r"\s+", " ", result).strip()


class RuledTableRecovery:
    def extract(self, page: Any, captions: list[dict]) -> list[dict]:
        groups: list[dict] = []
        for drawing in page.get_drawings():
            for item in drawing["items"]:
                if item[0] != "l":
                    continue
                a, b = item[1:3]
                x0, x1 = sorted((a.x, b.x))
                if abs(a.y - b.y) > 0.8 or x1 - x0 < 90:
                    continue
                group = next((g for g in groups if abs(g["x0"] - x0) < 2 and abs(g["x1"] - x1) < 2), None)
                if group is None:
                    group = {"x0": x0, "x1": x1, "ys": []}
                    groups.append(group)
                if all(abs(y - a.y) > 1 for y in group["ys"]):
                    group["ys"].append(a.y)
        glyphs = []
        for block in page.get_text("rawdict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line["spans"]:
                    for char in span["chars"]:
                        glyphs.append({"text": char["c"], "bbox": list(char["bbox"]),
                                       "origin_x": char["origin"][0], "baseline": char["origin"][1], "size": span["size"]})
        # Two same-width tables on one page must not become one giant region.
        split_groups = []
        for group in groups:
            current = []
            for y in sorted(group["ys"]):
                if current and any(c.get("bbox") and current[-1] < c["bbox"][1] < y
                                   and max(group["x0"], c["bbox"][0]) < min(group["x1"], c["bbox"][2]) for c in captions):
                    split_groups.append({**group, "ys": current})
                    current = []
                current.append(y)
            if current:
                split_groups.append({**group, "ys": current})
        groups = split_groups
        recovered = []
        for group in sorted(groups, key=lambda g: (min(g["ys"]), g["x0"])):
            ys = sorted(group["ys"])
            if len(ys) < 3 or not 20 < ys[-1] - ys[0] < page.rect.height * 0.7:
                continue
            region = [group["x0"], ys[0], group["x1"], ys[-1]]
            candidates = [c for c in captions if self._caption_distance(c.get("bbox", []), region) < 120]
            if not candidates:
                continue
            caption = min(candidates, key=lambda c: self._caption_distance(c["bbox"], region))
            contained = [g for g in glyphs if region[0] - 1 <= (g["bbox"][0] + g["bbox"][2]) / 2 <= region[2] + 1
                         and region[1] <= g["baseline"] <= region[3]]
            table = self._reconstruct(contained, region, ys[1], page.number + 1, caption)
            if table:
                recovered.append(table)
        return recovered

    @staticmethod
    def _caption_distance(box: list, region: list) -> float:
        if len(box) != 4:
            return float("inf")
        overlap = max(0, min(box[2], region[2]) - max(box[0], region[0]))
        if overlap < min(box[2] - box[0], region[2] - region[0]) * 0.6:
            return float("inf")
        if box[3] <= region[1] + 2:
            return region[1] - box[3]
        if box[1] >= region[3] - 2:
            return box[1] - region[3]
        return float("inf")

    @staticmethod
    def _lines(glyphs: list[dict], size: float) -> list[list[dict]]:
        anchors: list[float] = []
        for glyph in sorted(glyphs, key=lambda g: g["baseline"]):
            if glyph["size"] >= size * 0.78 and glyph["text"].strip():
                if not anchors or abs(anchors[-1] - glyph["baseline"]) > size * 0.28:
                    anchors.append(glyph["baseline"])
        lines: list[list[dict]] = [[] for _ in anchors]
        for glyph in glyphs:
            if anchors:
                index = min(range(len(anchors)), key=lambda i: abs(anchors[i] - glyph["baseline"]))
                lines[index].append(glyph)
        return [line for line in lines if glyph_text(line)]

    def _reconstruct(self, glyphs: list[dict], region: list, header_bottom: float, page: int, caption: dict) -> dict | None:
        header_glyphs = [g for g in glyphs if g["baseline"] < header_bottom]
        body_glyphs = [g for g in glyphs if g["baseline"] >= header_bottom]
        if not header_glyphs or not body_glyphs:
            return None
        header_sizes = [g["size"] for g in header_glyphs if g["text"].strip()]
        if not header_sizes:
            return None
        size = statistics.median(header_sizes)
        # Vertical whitespace through the full header combines multi-line header
        # components, while leaving true inter-column gaps.
        occupied: list[list[float]] = []
        for g in sorted((g for g in header_glyphs if g["text"].strip()), key=lambda g: g["bbox"][0]):
            left, right = g["bbox"][0], g["bbox"][2]
            if occupied and left - occupied[-1][1] < size * 0.55:
                occupied[-1][1] = max(occupied[-1][1], right)
            else:
                occupied.append([left, right])
        if not 2 <= len(occupied) <= 20:
            return None
        body_lines = self._lines(body_glyphs, size)
        # Exclude centred, spanning group labels from boundary voting.
        voting = [g for line in body_lines if any(g["bbox"][0] < occupied[1][0] for g in line)
                  for g in line if g["text"].strip()]
        separators = []
        for left, right in zip(occupied, occupied[1:]):
            lo, hi = left[1], right[0]
            candidates = [lo + (hi - lo) * i / 80 for i in range(1, 80)]
            # Prefer genuine whitespace shared across rows; midpoint breaks ties.
            def cost(x: float) -> tuple:
                hits = sum(g["bbox"][0] - 0.5 < x < g["bbox"][2] + 0.5 for g in voting)
                clearance = min((min(abs(x - g["bbox"][0]), abs(x - g["bbox"][2])) for g in voting), default=0)
                return hits, -min(clearance, 3), abs(x - (lo + hi) / 2)
            separators.append(min(candidates, key=cost))
        edges = [region[0], *separators, region[2]]
        columns = len(edges) - 1
        def split(line: list[dict]) -> list[list[dict]]:
            cells: list[list[dict]] = [[] for _ in range(columns)]
            for g in line:
                cells[bisect.bisect_right(separators, (g["bbox"][0] + g["bbox"][2]) / 2)].append(g)
            return cells
        headers = ["" for _ in range(columns)]
        for line in self._lines(header_glyphs, size):
            for c, content in enumerate(split(line)):
                headers[c] = (headers[c] + " " + glyph_text(content)).strip()
        if any(not h or len(h) > 80 for h in headers):
            return None
        table_id = f"ruled_table:p{page}:{round(region[0])}:{round(region[1])}"
        cells, rows, row_groups = [], [headers], []
        context = ""
        parent_label = ""
        for line in body_lines:
            buckets = split(line)
            texts = [glyph_text(content) for content in buckets]
            if not texts[0] and not any(re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", t) for t in texts if t):
                context = glyph_text(line)
                row_groups.append({"id": f"{table_id}:group:{len(row_groups)}", "text": context, "bbox": bounds(line)})
                continue
            if not texts[0] or sum(bool(t) for t in texts) < max(2, columns * 0.6):
                return None  # Ambiguous multi-line/sparse body: do not invent rows.
            row = len(rows)
            row_context = parent_label if texts[0].startswith("+") else ""
            if not row_context:
                parent_label = texts[0]
            for c, content in enumerate(buckets):
                main = [g for g in content if g["size"] >= size * 0.75]
                small = [g for g in content if g["size"] < size * 0.75]
                primary = glyph_text(main)
                # Small glyphs in fractions remain part of the literal cell.
                separate = bool(small) and bool(re.fullmatch(r"[+-]?\d+(?:\.\d+)?%?", primary))
                annotation = glyph_text(small) if separate else ""
                display = f"{primary} [small-type: {annotation}]" if annotation else texts[c]
                texts[c] = display
                cells.append({"id": f"{table_id}:r{row}c{c}", "row": row, "column": c, "text": display,
                              "raw_text": glyph_text(content), "value_text": primary if separate else display,
                              "annotations": [{"text": annotation, "kind": "small_type", "meaning": "not_inferred"}] if annotation else [],
                              "header_refs": [f"{table_id}:r0c{c}"], "column_header": headers[c],
                              "row_label": texts[0], "row_context": row_context, "group_context": context,
                              "group_refs": [row_groups[-1]["id"]] if context else [], "bbox": bounds(content),
                              "glyphs": content, "locator": f"page={page}&table={table_id}&row={row}&column={c}"})
            rows.append(texts)
        numeric = sum(bool(re.search(r"\d", cell["value_text"])) for cell in cells if cell["column"] > 0)
        if len(rows) < 3 or numeric < 2:
            return None
        header_cells = [{"id": f"{table_id}:r0c{c}", "row": 0, "column": c, "text": value,
                         "header_refs": [], "bbox": bounds(split(header_glyphs)[c])} for c, value in enumerate(headers)]
        return {"id": table_id, "type": "table", "page": page, "bbox": [round(x, 3) for x in region],
                "rows": rows, "headers": headers, "header_rows": 1, "cells": header_cells + cells,
                "row_groups": row_groups, "column_edges": edges, "caption": caption.get("text", ""),
                "caption_id": caption["id"], "text": "\n".join(" | ".join(row) for row in rows),
                "locator": f"page={page}&table={table_id}", "representation": "ruled_region_glyph_grid",
                "recovery": {"engine": "ruled-glyph-v1", "status": "reconstructed", "semantic_accuracy_evaluated": False}}
