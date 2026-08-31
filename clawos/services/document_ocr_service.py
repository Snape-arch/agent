"""Local OCR with explicit language coverage, positioned words and line evidence.

Recognition confidence is engine output, NOT a calibrated factual probability.
Raster tables require verified header/grid boundaries; equations and heading
semantics are not inferred from OCR words alone.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any


class DocumentOCRService:
    def __init__(self, *, language: str | None = None, tessdata_dir: str | Path | None = None):
        self.language = language or os.environ.get("TESSERACT_LANG", "auto")
        local = Path(__file__).resolve().parents[2] / "tools/ocr/tessdata"
        configured = tessdata_dir or os.environ.get("TESSDATA_PREFIX", "")
        self.explicit_tessdata = bool(configured)
        self.tessdata_dir = str(configured or (local if local.is_dir() else ""))
        known = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")
        self.executable = os.environ.get("TESSERACT_CMD", "").strip() or shutil.which("tesseract") or (str(known) if known.is_file() else "")

    def capability(self) -> dict[str, Any]:
        base = {"engine": "tesseract-tsv", "requested_language": self.language,
                "tessdata_dir": self.tessdata_dir, "available_languages": [], "warnings": []}
        if not self.executable:
            return {**base, "status": "engine_unavailable"}
        args = [self.executable]
        if self.tessdata_dir:
            args += ["--tessdata-dir", self.tessdata_dir]
        try:
            result = subprocess.run(args + ["--list-langs"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=15)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {**base, "status": "engine_unavailable", "error": type(exc).__name__}
        if result.returncode:
            return {**base, "status": "engine_unavailable", "error": result.stderr[:300]}
        available = {line.strip() for line in result.stdout.splitlines() if re.fullmatch(r"[\w/]+", line.strip())}
        base["available_languages"] = sorted(available)
        requested = self.language.split("+") if self.language != "auto" else [x for x in ("chi_sim", "eng") if x in available]
        if self.language == "auto" and "chi_sim" not in available:
            base["warnings"].append("simplified_chinese_model_unavailable")
        missing = [x for x in requested if x not in available]
        if not requested or missing:
            return {**base, "status": "language_unavailable", "missing_languages": missing or ["eng", "chi_sim"]}
        return {**base, "status": "ready", "language": "+".join(requested)}

    def recognize(self, path: Path, page_number: int) -> dict[str, Any]:
        capability = self.capability()
        base = {**capability, "page": page_number, "required": True, "words": [], "lines": [],
                "coordinate_space": "unrotated_page_points", "semantic_structure_recovered": False}
        if capability["status"] != "ready":
            return base
        try:
            import fitz
            with tempfile.TemporaryDirectory(prefix="clawos-ocr-") as td, fitz.open(str(path)) as document:
                page = document[page_number - 1]
                # 216 DPI; cap unusually large pages to bound bitmap allocation.
                scale = min(3.0, 6000 / max(page.rect.width, page.rect.height))
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image_path = Path(td) / "page.png"
                pix.save(str(image_path))
                args = [self.executable, str(image_path), "stdout"]
                if self.tessdata_dir:
                    args += ["--tessdata-dir", self.tessdata_dir]
                # Config variable rather than the optional external configs/tsv file.
                args += ["-l", capability["language"], "--oem", "1", "-c", "tessedit_create_tsv=1"]
                result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
                if result.returncode:
                    return {**base, "status": "failed", "error": result.stderr[:300]}
                words = self.parse_tsv(result.stdout, scale=1 / scale)
                from PIL import Image
                from services.raster_document_layout import RasterDocumentLayout
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                deadline = time.monotonic() + 90
                # Use the installed high-accuracy Chinese recognizer for CJK-heavy
                # regions only in the default local profile. Explicit config wins.
                region_language, region_data = capability["language"], self.tessdata_dir
                observed = "".join(w["text"] for w in words)
                chinese = len(re.findall(r"[\u3400-\u9fff]", observed))
                local_root = Path(__file__).resolve().parents[2] / "tools/ocr"
                best = local_root / "tessdata-best"
                if self.language == "auto" and not self.explicit_tessdata and Path(self.tessdata_dir) == local_root / "tessdata" and chinese >= 30 and chinese > len(observed)*.3 and (best/"chi_sim.traineddata").is_file():
                    region_language, region_data = "chi_sim", str(best)

                def recognize_crop(crop, psm=6):
                    if time.monotonic() >= deadline:
                        return {"status": "budget_exceeded", "words": []}
                    crop_path = Path(td) / "cell.png"
                    crop.save(crop_path)
                    crop_args = [self.executable, str(crop_path), "stdout"]
                    if region_data:
                        crop_args += ["--tessdata-dir", region_data]
                    crop_args += ["-l", region_language, "--oem", "1", "--psm", str(psm), "-c", "tessedit_create_tsv=1"]
                    try:
                        output = subprocess.run(crop_args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=min(15,max(.1,deadline-time.monotonic())))
                        found = self.parse_tsv(output.stdout)
                        return {"status": "completed" if output.returncode == 0 and found else "failed", "words": found if output.returncode == 0 else []}
                    except (OSError, subprocess.TimeoutExpired):
                        return {"status": "failed", "words": []}

                def verify_crop(crop, original):
                    import unicodedata
                    from PIL import ImageOps
                    candidates = []
                    # Different segmentation/scale exposes errors correlated with
                    # the column view. Agreement is NOT independent factual proof.
                    for mode in (6, 7):
                        view = ImageOps.expand(crop.resize((crop.width*2, crop.height*2)), border=24, fill="white")
                        response = recognize_crop(view, mode)
                        text = " ".join(line["text"] for line in self.lines(response["words"]))
                        candidates.append({"view": f"cell_2x_psm{mode}", "text": text, "status": response["status"]})
                    norm = lambda t: re.sub(r"\s+", "", unicodedata.normalize("NFKC", t))
                    complete = all(c["status"] == "completed" for c in candidates)
                    agreement = complete and all(norm(c["text"]) == norm(original) for c in candidates)
                    return {"status": "agreement_unverified" if agreement else ("disagreement" if complete else "incomplete"),
                            "candidates": candidates, "auto_accepted": False}

                tables, regions = RasterDocumentLayout().recover(image, scale, recognize_crop, verify_crop)
                def inside(word, table):
                    box, region = word["bbox"], table["bbox"]
                    return region[0] <= (box[0]+box[2])/2 <= region[2] and region[1] <= (box[1]+box[3])/2 <= region[3]
                words = [w for w in words if not any(inside(w,t) for t in tables)]
                block = max((w["block_num"] for w in words), default=0) + 1
                for index, table in enumerate(tables, 1):
                    table.update(id=f"ocr_table:p{page_number}:{index}", type="table", page=page_number,
                                 locator=f"page={page_number}&ocr_table={index}", source_filename=path.name)
                    header_review = any(c["review_required"] for c in table["cells"] if c["is_header"])
                    for cell in table["cells"]:
                        r,c = cell["row"],cell["column"]
                        cell.update(id=f"{table['id']}:r{r}c{c}", column_header=table["headers"][c],
                                    header_refs=[] if r == 0 else [f"{table['id']}:r0c{c}"],
                                    locator=f"{table['locator']}&row={r}&column={c}",
                                    row_label=table["rows"][r][0], review_required=cell["review_required"] or header_review)
                        cell["word_indices"] = list(range(len(words)+1,len(words)+1+len(cell["words"])))
                        for word in cell.pop("words"):
                            word["block_num"] = block
                            word["table_id"] = table["id"]
                            words.append(word)
                        block += 1
                bounds = page.rect * page.derotation_matrix
                kept, index_map = [], {}
                for old_index, word in enumerate(words,1):
                    box = (fitz.Rect(word["bbox"]) * page.derotation_matrix) & bounds
                    word["bbox"] = [round(v, 2) for v in box]
                    if word["bbox"][0] < word["bbox"][2] and word["bbox"][1] < word["bbox"][3]:
                        index_map[old_index] = len(kept)+1
                        kept.append(word)
                words = kept
                lines = self.lines(words)
                for table in tables:
                    table["bbox"] = list(fitz.Rect(table["bbox"]) * page.derotation_matrix)
                    for cell in table["cells"]:
                        cell["bbox"] = list(fitz.Rect(cell["bbox"]) * page.derotation_matrix)
                        cell["word_indices"] = [index_map[i] for i in cell["word_indices"] if i in index_map]
                for region in regions:
                    region["bbox"] = list(fitz.Rect(region["bbox"]) * page.derotation_matrix)
                text_blocks = {}
                for i, word in enumerate(words,1):
                    if word.get("table_id"):
                        continue
                    text_blocks.setdefault(word["block_num"],[]).append((i,word))
                for block_id, items in text_blocks.items():
                    boxes = [w["bbox"] for _,w in items]
                    regions.append({"id":f"ocr_region:p{page_number}:block{block_id}","type":"ocr_text_block",
                                    "bbox":[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)],
                                    "word_indices":[i for i,_ in items],"method":"tesseract_block_segmentation",
                                    "semantic_role":"unclassified","structure_status":"not_applicable"})
                reading = [(line["bbox"][1], line["bbox"][0], line["text"]) for line in lines
                           if not any(inside(line,t) for t in tables)]
                reading.extend((t["bbox"][1],t["bbox"][0],"\n".join(" | ".join(row) for row in t["rows"])) for t in tables)
                return {**base, "status": "completed" if words else "empty", "words": words, "lines": lines,
                        "tables": tables, "regions": regions, "reading_text": "\n".join(t for _,_,t in sorted(reading)),
                        "region_language": region_language, "region_tessdata_dir": region_data,
                        "semantic_structure_recovered": bool(tables),
                        "raster_dpi": round(scale * 72, 2), "page_bounds": list(bounds),
                        "review_required": any(line["review_required"] for line in lines) or any(c["review_required"] for t in tables for c in t["cells"]) or any(r["type"]=="table_candidate" and r["structure_status"] != "reconstructed" for r in regions)}
        except subprocess.TimeoutExpired:
            return {**base, "status": "timeout"}
        except (OSError, ValueError, RuntimeError) as exc:
            return {**base, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]}

    @staticmethod
    def parse_tsv(value: str, scale: float = 1.0) -> list[dict[str, Any]]:
        rows = []
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("scale must be finite and positive")
        for line in str(value or "").splitlines()[1:]:
            columns = line.split("\t", 11)
            if len(columns) != 12 or columns[0] != "5" or not columns[11].strip():
                continue
            try:
                left, top, width, height, confidence = map(float, columns[6:11])
                identity = [int(x) for x in columns[1:6]]
            except ValueError:
                continue
            if not all(math.isfinite(x) for x in (left, top, width, height, confidence)) or min(left, top) < 0 or min(width, height) <= 0 or not 0 <= confidence <= 100:
                continue
            rows.append({"text": columns[11].strip(), "confidence": round(confidence / 100, 4),
                         "block_num": identity[1], "paragraph_num": identity[2], "line_num": identity[3], "word_num": identity[4],
                         "bbox": [round(left * scale, 2), round(top * scale, 2),
                                  round((left + width) * scale, 2), round((top + height) * scale, 2)]})
        return rows

    @staticmethod
    def lines(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[tuple, list] = OrderedDict()
        for index, word in enumerate(words, 1):
            key = (word["block_num"], word["paragraph_num"], word["line_num"])
            groups.setdefault(key, []).append((index, word))
        result = []
        for key, items in groups.items():
            items.sort(key=lambda item: item[1]["word_num"])
            fragments = []
            ambiguous = False
            for index, (_, word) in enumerate(items):
                if index:
                    previous = items[index - 1][1]
                    # Large horizontal gaps may be table cells/columns. Keep a
                    # visible boundary but do not infer headers from mere spacing.
                    gap = word["bbox"][0] - previous["bbox"][2]
                    height = max(word["bbox"][3] - word["bbox"][1], previous["bbox"][3] - previous["bbox"][1])
                    is_boundary = gap > max(12, height * 2)
                    fragments.append(" | " if is_boundary else " ")
                    ambiguous |= is_boundary
                fragments.append(word["text"])
            raw = "".join(fragments)
            # Remove only artificial CJK word boundaries; preserve Latin spaces.
            text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff，。！？；：、）】])", "", raw)
            text = re.sub(r"(?<=[（【])\s+(?=[\u3400-\u9fff])", "", text)
            boxes = [w["bbox"] for _, w in items]
            weights = [len(w["text"]) for _, w in items]
            confidence = sum(w["confidence"] * n for (_, w), n in zip(items, weights)) / sum(weights)
            result.append({"text": text, "raw_text": raw, "confidence": round(confidence, 4),
                           "review_required": ambiguous or confidence < .75 or any(w["confidence"] < .4 for _, w in items),
                           "layout_ambiguous": ambiguous,
                           "word_indices": [i for i, _ in items], "block_num": key[0], "paragraph_num": key[1], "line_num": key[2],
                           "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]})
        return result
