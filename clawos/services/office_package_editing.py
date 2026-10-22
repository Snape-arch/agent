"""Bounded Office edits that preserve untouched OOXML parts and run properties."""
from __future__ import annotations

import math
import posixpath
import re
from typing import Any
from lxml import etree as ET

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML = "http://www.w3.org/XML/1998/namespace"


def parse_xml(raw: bytes):
    return ET.fromstring(raw, parser=ET.XMLParser(resolve_entities=False, no_network=True, load_dtd=False))


def serialize(root) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def replace_runs(root, old: str, new: str, namespace: str) -> int:
    """Match within paragraphs, never through tabs, fields, breaks or drawings.

    Replacement inherits the first affected run's formatting. Unmatched prefixes,
    suffixes and run properties remain in their original runs.
    """
    if not old:
        raise ValueError("replacement target must not be empty")
    count = 0
    for paragraph in root.iter(f"{{{namespace}}}p"):
        groups, group = [], []
        def visit(node):
            nonlocal group
            local = ET.QName(node).localname if isinstance(node.tag, str) else ""
            if node is not paragraph and local in {"p", "tab", "br", "cr", "fldChar", "instrText", "drawing", "del", "fld"}:
                if group:
                    groups.append(group)
                    group = []
                return
            if node.tag == f"{{{namespace}}}t":
                group.append(node)
            else:
                for child in node:
                    visit(child)
        visit(paragraph)
        if group:
            groups.append(group)
        for nodes in groups:
            text = "".join(node.text or "" for node in nodes)
            matches = list(re.finditer(re.escape(old), text))
            offsets, offset = [], 0
            for node in nodes:
                offsets.append(offset)
                offset += len(node.text or "")
            for match in reversed(matches):
                start, end = match.span()
                first = next(i for i, node in enumerate(nodes) if offsets[i] <= start < offsets[i] + len(node.text or ""))
                last = next(i for i, node in enumerate(nodes) if offsets[i] < end <= offsets[i] + len(node.text or ""))
                prefix = (nodes[first].text or "")[:start-offsets[first]]
                suffix = (nodes[last].text or "")[end-offsets[last]:]
                nodes[first].text = prefix + new + (suffix if first == last else "")
                for i in range(first+1, last):
                    nodes[i].text = ""
                if last != first:
                    nodes[last].text = suffix
                for node in nodes[first:last+1]:
                    node.set(f"{{{XML}}}space", "preserve")
                count += 1
    return count


def cell_position(address: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", address)
    if not match:
        raise ValueError(f"invalid cell reference: {address}")
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char)-64
    row = int(match[2])
    if row > 1048576 or column > 16384:
        raise ValueError(f"cell outside XLSX bounds: {address}")
    return row, column


def edit_cells(parts: dict[str, bytes], updates: list[dict[str, Any]]) -> tuple[set[str], int]:
    workbook = parse_xml(parts["xl/workbook.xml"])
    rels = parse_xml(parts["xl/_rels/workbook.xml.rels"])
    targets = {rel.get("Id"): posixpath.normpath(posixpath.join("xl", rel.get("Target", "")))
               if not rel.get("Target", "").startswith("/") else rel.get("Target").lstrip("/")
               for rel in rels if rel.get("TargetMode") != "External"}
    sheets = {sheet.get("name"): targets.get(sheet.get(f"{{{R}}}id")) for sheet in workbook.iter(f"{{{S}}}sheet")}
    roots, changed = {}, set()
    for update in updates:
        sheet = str(update.get("sheet") or "")
        if not sheet and len(sheets) == 1:
            sheet = next(iter(sheets))
        path = sheets.get(sheet)
        if not path or path not in parts:
            raise ValueError(f"worksheet not found: {sheet}")
        address = str(update.get("cell") or "").upper()
        row_number, column = cell_position(address)
        root = roots.setdefault(path, parse_xml(parts[path]))
        for merged in root.iter(f"{{{S}}}mergeCell"):
            bounds = merged.get("ref", "").split(":")
            first, last = cell_position(bounds[0]), cell_position(bounds[-1])
            if first[0] <= row_number <= last[0] and first[1] <= column <= last[1] and address != bounds[0]:
                raise ValueError(f"write the merged cell anchor {bounds[0]}, not {address}")
        data = root.find(f"{{{S}}}sheetData")
        if data is None:
            raise ValueError("worksheet has no sheetData")
        row = next((item for item in data if int(item.get("r", 0)) == row_number), None)
        if row is None:
            row = ET.Element(f"{{{S}}}row", r=str(row_number))
            index = next((i for i, item in enumerate(data) if int(item.get("r", 0)) > row_number), len(data))
            data.insert(index, row)
        cell = next((item for item in row if item.get("r") == address), None)
        if cell is None:
            cell = ET.Element(f"{{{S}}}c", r=address)
            index = next((i for i, item in enumerate(row) if cell_position(item.get("r"))[1] > column), len(row))
            row.insert(index, cell)
        formula = cell.find(f"{{{S}}}f")
        if formula is not None and formula.get("t") in {"shared", "array", "dataTable"}:
            raise ValueError("editing shared/array/data-table formula cells requires an Office calculation engine")
        for candidate in root.iter(f"{{{S}}}f"):
            ref = candidate.get("ref")
            if ref:
                bounds = ref.split(":")
                first, last = cell_position(bounds[0]), cell_position(bounds[-1])
                if first[0] <= row_number <= last[0] and first[1] <= column <= last[1]:
                    raise ValueError("cell belongs to a shared/array formula range")
        value = update.get("value")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("cell numeric values must be finite")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError("cell value must be text, number, boolean or null")
        for child in list(cell):
            if child.tag in {f"{{{S}}}f", f"{{{S}}}v", f"{{{S}}}is"}:
                cell.remove(child)
        cell.attrib.pop("t", None)  # Preserve style, metadata, and extension attributes.
        if isinstance(value, str) and value.startswith("=") and update.get("type") != "text":
            if len(value) < 2:
                raise ValueError("formula must not be empty")
            ET.SubElement(cell, f"{{{S}}}f").text = value[1:]
        elif isinstance(value, str):
            cell.set("t", "inlineStr")
            text = ET.SubElement(ET.SubElement(cell, f"{{{S}}}is"), f"{{{S}}}t")
            text.text = value
            text.set(f"{{{XML}}}space", "preserve")
        elif value is not None:
            if isinstance(value, bool):
                cell.set("t", "b")
            ET.SubElement(cell, f"{{{S}}}v").text = str(int(value)) if isinstance(value, bool) else str(value)
        dimension = root.find(f"{{{S}}}dimension")
        if dimension is not None:
            # Let consumers infer used range, avoiding stale dimensions hiding new cells.
            root.remove(dimension)
        changed.add(path)
    if updates:
        # Any input edit can invalidate dependencies on other worksheets.
        for path in set(sheets.values()):
            root = roots.get(path)
            if root is None:
                root = parse_xml(parts[path])
            invalidated = False
            for cell in root.iter(f"{{{S}}}c"):
                if cell.find(f"{{{S}}}f") is not None:
                    for cached in list(cell.findall(f"{{{S}}}v")):
                        cell.remove(cached)
                        invalidated = True
            if invalidated or path in changed:
                parts[path] = serialize(root)
                changed.add(path)
        calc = workbook.find(f"{{{S}}}calcPr")
        if calc is None:
            calc = ET.SubElement(workbook, f"{{{S}}}calcPr")
        calc.set("fullCalcOnLoad", "1")
        calc.set("forceFullCalc", "1")
        calc.set("calcMode", "auto")
        parts["xl/workbook.xml"] = serialize(workbook)
        changed.add("xl/workbook.xml")
        # Old calculation chains cannot describe changed formulas reliably.
        for rel in list(rels):
            if rel.get("Type", "").endswith("/calcChain"):
                target = targets[rel.get("Id")]
                parts.pop(target, None)
                changed.add(target)
                rels.remove(rel)
                types = parse_xml(parts["[Content_Types].xml"])
                for entry in list(types):
                    if entry.get("PartName", "").lstrip("/") == target:
                        types.remove(entry)
                parts["[Content_Types].xml"] = serialize(types)
                parts["xl/_rels/workbook.xml.rels"] = serialize(rels)
                changed.update({"[Content_Types].xml", "xl/_rels/workbook.xml.rels"})
    return changed, len(updates)
