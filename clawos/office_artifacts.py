"""Self-contained XLSX and PPTX helpers based on OpenXML zip packages.

These helpers intentionally avoid openpyxl/python-pptx so ClawOS can generate
and lightly edit Office artifacts on a fresh Python install.
"""

from __future__ import annotations

import html
import re
import zipfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
PML_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
AML_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)
ET.register_namespace("p", PML_NS)
ET.register_namespace("a", AML_NS)


def _xml_header(text):
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + text


def _col_name(index):
    index = int(index)
    name = ""
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell_ref(row_index, col_index):
    return f"{_col_name(col_index)}{int(row_index)}"


def _cell_kind(value):
    if isinstance(value, bool):
        return "b", "1" if value else "0"
    if isinstance(value, (int, float)):
        return "n", str(value)
    return "inlineStr", str(value)


def create_xlsx(path, sheets):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheets = sheets or [{"name": "Sheet1", "rows": []}]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _xlsx_content_types(len(sheets)))
        z.writestr("_rels/.rels", _rels({
            "rId1": ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "xl/workbook.xml"),
            "rId2": ("http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
            "rId3": ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties", "docProps/app.xml"),
        }))
        z.writestr("docProps/core.xml", _core_props())
        z.writestr("docProps/app.xml", _app_props())
        z.writestr("xl/workbook.xml", _workbook_xml(sheets))
        z.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        z.writestr("xl/styles.xml", _xlsx_styles())
        for index, sheet in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{index}.xml", _worksheet_xml(sheet.get("rows", [])))
    return str(path)


def edit_xlsx(path, updates, output_path=None):
    path = Path(path)
    output = Path(output_path) if output_path else path
    files = _read_zip(path)
    sheet_map = _xlsx_sheet_map(files)
    for item in updates or []:
        sheet_key = str(item.get("sheet") or "Sheet1")
        sheet_file = sheet_map.get(sheet_key) or sheet_map.get("1") or "xl/worksheets/sheet1.xml"
        files[sheet_file] = _update_worksheet(files[sheet_file], item.get("cell", "A1"), item.get("value", ""))
    _write_zip(output, files)
    return str(output)


def create_pptx(path, title="", slides=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    slides = slides or [{"title": title or "ClawOS Deck", "bullets": []}]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _pptx_content_types(len(slides)))
        z.writestr("_rels/.rels", _rels({
            "rId1": ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "ppt/presentation.xml"),
            "rId2": ("http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"),
            "rId3": ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties", "docProps/app.xml"),
        }))
        z.writestr("docProps/core.xml", _core_props())
        z.writestr("docProps/app.xml", _app_props())
        z.writestr("ppt/presentation.xml", _presentation_xml(len(slides)))
        z.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(len(slides)))
        z.writestr("ppt/slideMasters/slideMaster1.xml", _blank_part("p:sldMaster"))
        z.writestr("ppt/slideLayouts/slideLayout1.xml", _blank_part("p:sldLayout"))
        z.writestr("ppt/theme/theme1.xml", _theme_xml())
        for index, slide in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{index}.xml", _slide_xml(slide, index))
            z.writestr(f"ppt/slides/_rels/slide{index}.xml.rels", _rels({}))
    return str(path)


def replace_pptx_text(path, replacements, output_path=None):
    path = Path(path)
    output = Path(output_path) if output_path else path
    files = _read_zip(path)
    for name, content in list(files.items()):
        if not re.match(r"ppt/slides/slide\d+\.xml$", name):
            continue
        text = content.decode("utf-8")
        for old, new in (replacements or {}).items():
            text = text.replace(html.escape(str(old)), html.escape(str(new)))
            text = text.replace(str(old), html.escape(str(new)))
        files[name] = text.encode("utf-8")
    _write_zip(output, files)
    return str(output)


def _read_zip(path):
    with zipfile.ZipFile(path, "r") as z:
        return {name: z.read(name) for name in z.namelist()}


def _write_zip(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)


def _xlsx_sheet_map(files):
    root = ET.fromstring(files["xl/workbook.xml"])
    mapping = {}
    for index, sheet in enumerate(root.findall(f".//{{{MAIN_NS}}}sheet"), 1):
        name = sheet.attrib.get("name", f"Sheet{index}")
        mapping[name] = f"xl/worksheets/sheet{index}.xml"
        mapping[str(index)] = f"xl/worksheets/sheet{index}.xml"
    return mapping


def _update_worksheet(content, cell, value):
    root = ET.fromstring(content)
    sheet_data = root.find(f"{{{MAIN_NS}}}sheetData")
    if sheet_data is None:
        sheet_data = ET.SubElement(root, f"{{{MAIN_NS}}}sheetData")
    match = re.match(r"([A-Z]+)(\d+)$", str(cell).upper())
    if not match:
        raise ValueError(f"invalid cell reference: {cell}")
    row_number = int(match.group(2))
    row = None
    for candidate in sheet_data.findall(f"{{{MAIN_NS}}}row"):
        if int(candidate.attrib.get("r", 0)) == row_number:
            row = candidate
            break
    if row is None:
        row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": str(row_number)})
    target = None
    for candidate in row.findall(f"{{{MAIN_NS}}}c"):
        if candidate.attrib.get("r") == str(cell).upper():
            target = candidate
            break
    if target is None:
        target = ET.SubElement(row, f"{{{MAIN_NS}}}c", {"r": str(cell).upper()})
    target.clear()
    target.attrib["r"] = str(cell).upper()
    kind, serial = _cell_kind(value)
    if kind == "inlineStr":
        target.attrib["t"] = "inlineStr"
        inline = ET.SubElement(target, f"{{{MAIN_NS}}}is")
        ET.SubElement(inline, f"{{{MAIN_NS}}}t").text = serial
    else:
        if kind == "b":
            target.attrib["t"] = "b"
        ET.SubElement(target, f"{{{MAIN_NS}}}v").text = serial
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _rels(items):
    rows = [
        f'<Relationship Id="{rid}" Type="{rel_type}" Target="{target}"/>'
        for rid, (rel_type, target) in items.items()
    ]
    return _xml_header(
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(rows) + "</Relationships>"
    )


def _core_props():
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return _xml_header(
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:creator>ClawOS</dc:creator><cp:lastModifiedBy>ClawOS</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _app_props():
    return _xml_header(
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>ClawOS</Application></Properties>"
    )


def _xlsx_content_types(sheet_count):
    sheet_parts = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, sheet_count + 1)
    )
    return _xml_header(
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        + sheet_parts + "</Types>"
    )


def _workbook_xml(sheets):
    rows = "".join(
        f'<sheet name="{html.escape(str(sheet.get("name") or f"Sheet{i}"))}" sheetId="{i}" r:id="rId{i}"/>'
        for i, sheet in enumerate(sheets, 1)
    )
    return _xml_header(
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>{rows}</sheets></workbook>'
    )


def _workbook_rels(sheet_count):
    items = {
        f"rId{i}": (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
            f"worksheets/sheet{i}.xml",
        )
        for i in range(1, sheet_count + 1)
    }
    items[f"rId{sheet_count + 1}"] = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
        "styles.xml",
    )
    return _rels(items)


def _xlsx_styles():
    return _xml_header(
        f'<styleSheet xmlns="{MAIN_NS}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>'
    )


def _worksheet_xml(rows):
    row_xml = []
    for row_index, row in enumerate(rows or [], 1):
        cells = []
        for col_index, value in enumerate(row or [], 1):
            ref = _cell_ref(row_index, col_index)
            kind, serial = _cell_kind(value)
            if kind == "inlineStr":
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(serial)}</t></is></c>')
            elif kind == "b":
                cells.append(f'<c r="{ref}" t="b"><v>{serial}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{serial}</v></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return _xml_header(f'<worksheet xmlns="{MAIN_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>')


def _pptx_content_types(slide_count):
    slide_parts = "".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    return _xml_header(
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        + slide_parts + "</Types>"
    )


def _presentation_xml(slide_count):
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i}"/>' for i in range(1, slide_count + 1))
    return _xml_header(
        f'<p:presentation xmlns:p="{PML_NS}" xmlns:a="{AML_NS}" xmlns:r="{REL_NS}">'
        f"<p:sldIdLst>{ids}</p:sldIdLst><p:sldSz cx=\"12192000\" cy=\"6858000\" type=\"wide\"/>"
        "</p:presentation>"
    )


def _presentation_rels(slide_count):
    items = {
        f"rId{i}": (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            f"slides/slide{i}.xml",
        )
        for i in range(1, slide_count + 1)
    }
    items[f"rId{slide_count + 1}"] = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
        "slideMasters/slideMaster1.xml",
    )
    items[f"rId{slide_count + 2}"] = (
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
        "theme/theme1.xml",
    )
    return _rels(items)


def _blank_part(tag):
    return _xml_header(
        f'<{tag} xmlns:p="{PML_NS}" xmlns:a="{AML_NS}" xmlns:r="{REL_NS}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        '<p:grpSpPr/></p:spTree></p:cSld></' + tag + ">"
    )


def _theme_xml():
    return _xml_header(
        f'<a:theme xmlns:a="{AML_NS}" name="ClawOS"><a:themeElements><a:clrScheme name="ClawOS">'
        '<a:dk1><a:srgbClr val="111827"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
        '<a:accent1><a:srgbClr val="2563EB"/></a:accent1></a:clrScheme>'
        '<a:fontScheme name="ClawOS"><a:majorFont><a:latin typeface="Arial"/></a:majorFont>'
        '<a:minorFont><a:latin typeface="Arial"/></a:minorFont></a:fontScheme>'
        '<a:fmtScheme name="ClawOS"/></a:themeElements></a:theme>'
    )


def _slide_xml(slide, index):
    title = html.escape(str(slide.get("title") or f"Slide {index}"))
    bullets = [html.escape(str(item)) for item in (slide.get("bullets") or [])]
    notes = html.escape(str(slide.get("notes") or ""))
    bullet_xml = "".join(
        f'<a:p><a:r><a:rPr lang="zh-CN" sz="2200"/><a:t>{item}</a:t></a:r></a:p>'
        for item in bullets
    )
    if notes:
        bullet_xml += f'<a:p><a:r><a:rPr lang="zh-CN" sz="1600"/><a:t>{notes}</a:t></a:r></a:p>'
    return _xml_header(
        f'<p:sld xmlns:p="{PML_NS}" xmlns:a="{AML_NS}" xmlns:r="{REL_NS}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
        f'{_text_box(2, "Title", 700000, 450000, 10800000, 900000, title, 3400, True)}'
        f'{_text_box(3, "Body", 900000, 1550000, 10400000, 4300000, bullet_xml, 2200, False)}'
        '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
    )


def _text_box(shape_id, name, x, y, cx, cy, text, font_size, is_plain_text):
    if is_plain_text:
        body = f'<a:p><a:r><a:rPr lang="zh-CN" sz="{font_size}"/><a:t>{text}</a:t></a:r></a:p>'
    else:
        body = text or '<a:p><a:r><a:t></a:t></a:r></a:p>'
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>{body}</p:txBody></p:sp>'
    )
