from __future__ import annotations

import copy
import hashlib
import json
import os
import posixpath
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from lxml import etree as ET
from .office_package_editing import parse_xml, replace_runs, edit_cells


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML = "http://www.w3.org/XML/1998/namespace"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
for prefix, uri in (("w", W), ("r", R)):
    ET.register_namespace(prefix, uri)


class OfficeRoundtripService:
    """Part-scoped OOXML editing with auditable fidelity evidence."""

    def edit_docx(
        self, source: str | Path, output: str | Path, *,
        replacements: dict[str, Any] | None = None,
        comments: list[dict[str, Any]] | None = None,
        revisions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        source, output = Path(source), Path(output)
        parts = self._read(source)
        document = parse_xml(parts["word/document.xml"])
        changed = set()
        counts = {}
        for old, new in (replacements or {}).items():
            count = 0
            for name in list(parts):
                if name == "word/document.xml" or (name.startswith("word/") and name.endswith(".xml") and
                        (Path(name).name.startswith(("header", "footer")) or name in {"word/footnotes.xml", "word/endnotes.xml"})):
                    root = document if name == "word/document.xml" else parse_xml(parts[name])
                    found = replace_runs(root, str(old), str(new), W)
                    if found:
                        count += found
                        changed.add(name)
                        if name != "word/document.xml":
                            parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            if not count:
                raise ValueError(f"text target not found within an editable paragraph: {old}")
            counts[str(old)] = count
        if comments:
            self._add_comments(parts, document, comments)
        if revisions:
            self._add_revisions(parts, document, revisions)
        parts["word/document.xml"] = ET.tostring(document, encoding="utf-8", xml_declaration=True)
        allowed = changed | {"word/document.xml"}
        if comments:
            allowed |= {"word/comments.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"}
        if revisions:
            allowed |= {"word/settings.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"}
        return {**self._publish(source, output, parts, allowed), "replacement_counts": counts}

    def edit_xlsx(self, source: str | Path, output: str | Path, updates: list[dict[str, Any]]) -> dict[str, Any]:
        source, output = Path(source), Path(output)
        parts = self._read(source)
        allowed, count = edit_cells(parts, updates or [])
        return {**self._publish(source, output, parts, allowed), "updated_cells": count,
                "recalculation_required": bool(updates)}

    def edit_pptx(self, source: str | Path, output: str | Path, replacements: dict[str, Any]) -> dict[str, Any]:
        source, output = Path(source), Path(output)
        parts = self._read(source)
        changed, counts = set(), {}
        for old, new in (replacements or {}).items():
            count = 0
            for name, raw in list(parts.items()):
                if not name.startswith(("ppt/slides/", "ppt/notesSlides/")) or not name.endswith(".xml"):
                    continue
                root = parse_xml(raw)
                found = replace_runs(root, str(old), str(new), "http://schemas.openxmlformats.org/drawingml/2006/main")
                if found:
                    parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                    changed.add(name)
                    count += found
            if not count:
                raise ValueError(f"text target not found within an editable paragraph: {old}")
            counts[str(old)] = count
        return {**self._publish(source, output, parts, changed), "replacement_counts": counts}

    def recalculate_xlsx(self, source: str | Path, output: str | Path) -> dict[str, Any]:
        source, output = Path(source), Path(output)
        engine = shutil.which("soffice")
        if not engine:
            candidate = Path("C:/Program Files/LibreOffice/program/soffice.com")
            engine = str(candidate) if candidate.is_file() else ""
        if not engine:
            raise RuntimeError("LibreOffice is required for formula recalculation")
        with tempfile.TemporaryDirectory(prefix="clawos-office-recalc-") as td:
            root = Path(td)
            incoming, converted = root / source.name, root / "converted"
            profile = root / "profile"
            converted.mkdir()
            shutil.copy2(source, incoming)
            result = subprocess.run([
                engine, f"-env:UserInstallation={profile.as_uri()}", "--headless",
                "--convert-to", "xlsx", "--outdir", str(converted), str(incoming),
            ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            produced = converted / source.name
            if result.returncode != 0 or not produced.is_file():
                raise RuntimeError((result.stderr or result.stdout).strip() or "LibreOffice recalculation failed")
            formulas, cached = self._formula_counts(produced)
            source_formulas, _ = self._formula_counts(source)
            errors = self._formula_errors(produced)
            package_errors = self._package_errors(self._read(produced))
            if formulas != source_formulas or cached != formulas or errors or package_errors:
                raise RuntimeError(f"Formula recalculation gate failed: formulas={formulas}/{source_formulas}, cached={cached}, errors={errors}, package={package_errors}")
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(produced, output)
        formulas, cached = self._formula_counts(output)
        return {
            "engine": "libreoffice-calc", "formula_count": formulas,
            "cached_formula_values": cached,
            "recalculated": cached == formulas,
            "output_sha256": self._sha(output),
        }

    def audit(self, source: Path, output: Path, allowed_changed_parts: set[str]) -> dict[str, Any]:
        before, after = self._hashes(source), self._hashes(output)
        changed = sorted(name for name in before.keys() & after.keys() if before[name] != after[name])
        added, removed = sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())
        actual = set(changed + added + removed)
        styles = [name for name in before if name.endswith("styles.xml") or "/theme/" in name]
        style_preserved = all(before.get(name) == after.get(name) for name in styles)
        unexpected = sorted(actual - set(allowed_changed_parts))
        errors = self._package_errors(self._read(output))
        return {
            "schema": "clawos.office-roundtrip.v1", "package_valid": not errors,
            "package_errors": errors,
            "changed_parts": changed, "added_parts": added, "removed_parts": removed,
            "allowed_changed_parts": sorted(allowed_changed_parts),
            "unexpected_changed_parts": unexpected,
            "style_parts": styles, "style_preserved": style_preserved,
            "roundtrip_passed": not unexpected and style_preserved and not errors,
            "source_sha256": self._sha(source), "output_sha256": self._sha(output),
        }

    @classmethod
    def _formula_errors(cls, path: Path) -> list[str]:
        namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        errors = []
        for name, raw in cls._read(path).items():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                for cell in parse_xml(raw).iter(f"{{{namespace}}}c"):
                    if cell.find(f"{{{namespace}}}f") is not None and cell.get("t") == "e":
                        errors.append(f"{name}:{cell.get('r')}:{cell.findtext(f'{{{namespace}}}v')}")
        return errors

    def _publish(self, source: Path, output: Path, parts: dict, allowed: set) -> dict:
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".office-edit-", dir=output.parent) as td:
            candidate = Path(td) / output.name
            self._write(candidate, parts)
            result = self.audit(source, candidate, allowed)
            if not result["roundtrip_passed"]:
                raise ValueError(f"Office preservation gate failed: {result['package_errors']} {result['unexpected_changed_parts']}")
            os.replace(candidate, output)
        return result

    @staticmethod
    def _package_errors(parts: dict[str, bytes]) -> list[str]:
        errors = []
        if "[Content_Types].xml" not in parts or "_rels/.rels" not in parts:
            errors.append("missing_package_manifest")
        for name, raw in parts.items():
            if not name.endswith((".xml", ".rels")):
                continue
            try:
                root = parse_xml(raw)
            except ET.XMLSyntaxError:
                errors.append(f"invalid_xml:{name}")
                continue
            if name.endswith(".rels"):
                base = posixpath.dirname(posixpath.dirname(name))
                ids = set()
                for rel in root:
                    if rel.get("Id") in ids:
                        errors.append(f"duplicate_relationship:{name}:{rel.get('Id')}")
                    ids.add(rel.get("Id"))
                    if rel.get("TargetMode") == "External":
                        continue
                    from urllib.parse import unquote
                    target = unquote(rel.get("Target", "").split("#", 1)[0])
                    resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
                    if resolved not in parts:
                        errors.append(f"missing_relationship_target:{name}:{resolved}")
        return errors

    @staticmethod
    def _replace_text(root: ET.Element, old: str, new: str) -> None:
        if not replace_runs(root, old, new, W):
            raise ValueError(f"text target not found within an editable paragraph: {old}")

    def _add_comments(self, parts: dict[str, bytes], document: ET.Element, rows: list[dict[str, Any]]) -> None:
        comments = parse_xml(parts.get("word/comments.xml", f'<w:comments xmlns:w="{W}"/>'.encode()))
        ids = [int(item.get(f"{{{W}}}id", "-1")) for item in comments.findall(f"{{{W}}}comment")]
        next_id = max(ids, default=-1) + 1
        for row in rows:
            target = str(row.get("target") or "")
            if not target:
                raise ValueError("comment target is required")
            comment_id = next_id
            next_id += 1
            self._mark_comment(document, target, comment_id)
            node = ET.SubElement(comments, f"{{{W}}}comment", {
                f"{{{W}}}id": str(comment_id), f"{{{W}}}author": str(row.get("author") or "ClawOS"),
                f"{{{W}}}date": self._now(),
            })
            p, run = ET.SubElement(node, f"{{{W}}}p"), None
            run = ET.SubElement(p, f"{{{W}}}r")
            ET.SubElement(run, f"{{{W}}}t").text = str(row.get("text") or "")
        parts["word/comments.xml"] = ET.tostring(comments, encoding="utf-8", xml_declaration=True)
        self._ensure_part(parts, "/word/comments.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml", "comments", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments")

    def _mark_comment(self, document: ET.Element, target: str, comment_id: int) -> None:
        parent, start, end, before, selected, after = self._run_range(document, target)
        marker = ET.Element(f"{{{W}}}commentRangeStart", {f"{{{W}}}id": str(comment_id)})
        closing = ET.Element(f"{{{W}}}commentRangeEnd", {f"{{{W}}}id": str(comment_id)})
        ref = ET.Element(f"{{{W}}}r")
        ET.SubElement(ref, f"{{{W}}}commentReference", {f"{{{W}}}id": str(comment_id)})
        for node in list(parent)[start:end+1]:
            parent.remove(node)
        for offset, node in enumerate(before + [marker] + selected + [closing, ref] + after):
            parent.insert(start+offset, node)

    @classmethod
    def _run_range(cls, document, target):
        # Direct text runs only. Never move links, fields, existing review markers,
        # drawings or paragraph boundaries into a new review range.
        for paragraph in document.iter(f"{{{W}}}p"):
            group = []
            for index, run in enumerate(list(paragraph) + [None]):
                if (run is not None and run.tag == f"{{{W}}}r" and
                    all(child.tag in {f"{{{W}}}rPr", f"{{{W}}}t"} for child in run)):
                    group.append((index, run))
                    continue
                value = "".join("".join(node.text or "" for node in item.iter(f"{{{W}}}t")) for _, item in group)
                position = value.find(target)
                if position >= 0 and target:
                    stop = position + len(target)
                    before, selected, after = [], [], []
                    cursor = 0
                    for _, item in group:
                        text = "".join(node.text or "" for node in item.iter(f"{{{W}}}t"))
                        for left, right, bucket in ((0, max(0, min(len(text), position-cursor)), before),
                                (max(0, position-cursor), min(len(text), stop-cursor), selected),
                                (max(0, min(len(text), stop-cursor)), len(text), after)):
                            if left < right:
                                clone = ET.Element(f"{{{W}}}r", dict(item.attrib))
                                props = item.find(f"{{{W}}}rPr")
                                if props is not None:
                                    clone.append(copy.deepcopy(props))
                                cls._set_text(ET.SubElement(clone, f"{{{W}}}t"), text[left:right])
                                bucket.append(clone)
                        cursor += len(text)
                    return paragraph, group[0][0], group[-1][0], before, selected, after
                group = []
        raise ValueError(f"review target not found in contiguous text runs: {target}")

    def _add_revisions(self, parts: dict[str, bytes], document: ET.Element, rows: list[dict[str, Any]]) -> None:
        revision_id = max((int(node.get(f"{{{W}}}id", "0")) for node in document.iter()
                           if node.tag in {f"{{{W}}}ins", f"{{{W}}}del"}), default=0) + 1
        for row in rows:
            old, new = str(row.get("old") or ""), str(row.get("new") or "")
            if not old:
                raise ValueError("revision old text is required")
            self._mark_revision(document, old, new, revision_id, str(row.get("author") or "ClawOS"))
            revision_id += 2
        settings = parse_xml(parts.get("word/settings.xml", f'<w:settings xmlns:w="{W}"/>'.encode()))
        if settings.find(f"{{{W}}}trackRevisions") is None:
            settings.insert(0, ET.Element(f"{{{W}}}trackRevisions"))
        parts["word/settings.xml"] = ET.tostring(settings, encoding="utf-8", xml_declaration=True)
        self._ensure_part(parts, "/word/settings.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml", "settings", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings")

    def _mark_revision(self, document: ET.Element, old: str, new: str, revision_id: int, author: str) -> None:
        parent, start, end, before, selected, after = self._run_range(document, old)
        attrs = {f"{{{W}}}id": str(revision_id), f"{{{W}}}author": author, f"{{{W}}}date": self._now()}
        deletion = ET.Element(f"{{{W}}}del", attrs)
        template = copy.deepcopy(selected[0])
        for run in selected:
            for text in run.iter(f"{{{W}}}t"):
                text.tag = f"{{{W}}}delText"
            deletion.append(run)
        addition = ET.Element(f"{{{W}}}ins", {**attrs, f"{{{W}}}id": str(revision_id + 1)})
        self._set_text(next(template.iter(f"{{{W}}}t")), new)
        addition.append(template)
        for node in list(parent)[start:end+1]:
            parent.remove(node)
        for offset, node in enumerate(before + [deletion, addition] + after):
            parent.insert(start+offset, node)

    @staticmethod
    def _set_text(node: ET.Element, value: str) -> None:
        node.text = value
        if value.startswith(" ") or value.endswith(" "):
            node.set(f"{{{XML}}}space", "preserve")
        else:
            node.attrib.pop(f"{{{XML}}}space", None)

    @staticmethod
    def _ensure_part(parts: dict[str, bytes], part_name: str, content_type: str, rel_name: str, rel_type: str) -> None:
        types = parse_xml(parts["[Content_Types].xml"])
        if not any(item.get("PartName") == part_name for item in types):
            ET.SubElement(types, f"{{{CT}}}Override", {"PartName": part_name, "ContentType": content_type})
            ET.register_namespace("ct", CT)
            parts["[Content_Types].xml"] = ET.tostring(types, encoding="utf-8", xml_declaration=True)
            ET.register_namespace("w", W); ET.register_namespace("r", R)
        rel_path = "word/_rels/document.xml.rels"
        rels = parse_xml(parts.get(rel_path, f'<Relationships xmlns="{PKG_REL}"/>'.encode()))
        if not any(item.get("Type") == rel_type for item in rels):
            ids = {item.get("Id") for item in rels}
            index = 1
            while f"rId{index}" in ids: index += 1
            ET.SubElement(rels, f"{{{PKG_REL}}}Relationship", {"Id": f"rId{index}", "Type": rel_type, "Target": f"{rel_name}.xml"})
            ET.register_namespace("pr", PKG_REL)
            parts[rel_path] = ET.tostring(rels, encoding="utf-8", xml_declaration=True)
            ET.register_namespace("w", W); ET.register_namespace("r", R)

    @staticmethod
    def _formula_counts(path: Path) -> tuple[int, int]:
        formulas = cached = 0
        namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        for name, raw in OfficeRoundtripService._read(path).items():
            if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                continue
            for cell in parse_xml(raw).iter(f"{{{namespace}}}c"):
                if cell.find(f"{{{namespace}}}f") is not None:
                    formulas += 1
                    value = cell.find(f"{{{namespace}}}v")
                    if value is not None and (value.text not in {None, ""} or cell.get("t") == "str"):
                        cached += 1
        return formulas, cached

    @staticmethod
    def _read(path: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(path) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError("Office package contains duplicate parts")
            return {name: archive.read(name) for name in archive.namelist()}

    @staticmethod
    def _write(path: Path, parts: dict[str, bytes]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, raw in parts.items(): archive.writestr(name, raw)
        os.replace(temporary, path)

    @classmethod
    def _hashes(cls, path: Path) -> dict[str, str]:
        return {name: hashlib.sha256(raw).hexdigest() for name, raw in cls._read(path).items()}

    @staticmethod
    def _sha(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
