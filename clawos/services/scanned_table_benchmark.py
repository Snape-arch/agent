"""Fixed raster table geometry, text, conditions, and negative-region checks."""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path

from services.document_fidelity_benchmark import DocumentFidelityBenchmark
from services.document_ocr_benchmark import edit_distance, evaluate as evaluate_ocr

MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks/scanned_table_regions_v1.json"


def normalized(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).casefold()


def iou(a,b):
    area = max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def score_graphs(graphs, manifest):
    checks = {k: [] for k in ("regions", "shape", "cell_text_exact", "cell_coordinates", "header_links", "critical_exact", "critical_review", "negative_regions")}
    failures = []
    effort = {
        "baseline_manual_cell_edits": 0, "manual_cell_edits_required": 0,
        "baseline_character_edits": 0, "character_edits_required": 0,
        "baseline_critical_edits": 0, "critical_edits_required": 0,
        "auto_changed_cells": 0, "auto_changes_improved": 0,
        "auto_changes_worsened": 0, "verification_cells": 0,
        "verification_elapsed_ms": 0.0,
    }
    for spec in manifest["tables"]:
        graph = graphs.get(spec["page"], {})
        candidates = graph.get("tables", [])
        table = max(candidates,key=lambda t:iou(t["bbox"],spec["bbox"]),default={})
        found = bool(table) and iou(table["bbox"],spec["bbox"]) >= manifest["gates"]["region_iou"]
        if not found:
            table = {}
        checks["regions"].append(found)
        checks["shape"].append(len(table.get("rows",[])) == len(spec["rows"]) and all(len(r)==len(spec["rows"][0]) for r in table.get("rows",[])))
        cells = {(c["row"],c["column"]): c for c in table.get("cells",[])}
        for r, row in enumerate(spec["rows"]):
            for c, expected in enumerate(row):
                actual = cells.get((r,c),{})
                original = actual.get("original_text", actual.get("text", ""))
                correct = normalized(actual.get("text","")) == normalized(expected)
                baseline_correct = normalized(original) == normalized(expected)
                baseline_distance = edit_distance(normalized(original), normalized(expected))
                final_distance = edit_distance(normalized(actual.get("text", "")), normalized(expected))
                effort["baseline_manual_cell_edits"] += int(not baseline_correct)
                effort["manual_cell_edits_required"] += int(not correct)
                effort["baseline_character_edits"] += baseline_distance
                effort["character_edits_required"] += final_distance
                verification = actual.get("verification") or {}
                if verification and verification.get("status") != "not_requested":
                    effort["verification_cells"] += 1
                    effort["verification_elapsed_ms"] += float(verification.get("elapsed_ms") or 0.0)
                selection = verification.get("selection") or {}
                if selection.get("auto_applied") and normalized(original) != normalized(actual.get("text", "")):
                    effort["auto_changed_cells"] += 1
                    effort["auto_changes_improved"] += int(final_distance < baseline_distance)
                    effort["auto_changes_worsened"] += int(final_distance > baseline_distance)
                checks["cell_text_exact"].append(correct)
                if not correct:
                    failures.append({"page":spec["page"],"table_bbox":spec["bbox"],"row":r,"column":c,"expected":expected,"actual":actual.get("text", "")})
                box = actual.get("bbox",[])
                region = table.get("bbox",[])
                checks["cell_coordinates"].append(len(box)==4 and bool(region) and region[0] <= box[0] < box[2] <= region[2] and region[1] <= box[1] < box[3] <= region[3])
                if r:
                    header_id = cells.get((0,c),{}).get("id")
                    checks["header_links"].append(bool(header_id) and header_id in actual.get("header_refs",[]) and any(e["type"]=="conditioned_by" and e["source"]==actual.get("id") and e["target"]==header_id for e in graph.get("relations",[])))
        for critical in spec.get("critical",[]):
            cell = cells.get((critical["row"],critical["column"]),{})
            original = cell.get("original_text", cell.get("text", ""))
            effort["baseline_critical_edits"] += int(normalized(critical["contains"]) not in normalized(original))
            effort["critical_edits_required"] += int(normalized(critical["contains"]) not in normalized(cell.get("text", "")))
            checks["critical_exact"].append(normalized(critical["contains"]) in normalized(cell.get("text","")))
            if critical["kind"] == "numeric":
                checks["critical_review"].append(bool(cell.get("numeric_verification_required") and cell.get("review_required")))
    for negative in manifest["negative_regions"]:
        checks["negative_regions"].append(not any(iou(t["bbox"],negative["bbox"])>.1 for t in graphs.get(negative["page"],{}).get("tables",[])))
    metrics = {k:DocumentFidelityBenchmark._metric(v) for k,v in checks.items()}
    gates = {k: m["n"]>0 and m["rate"]>=manifest["gates"].get(k,1.0) for k,m in metrics.items()}
    baseline = effort["baseline_manual_cell_edits"]
    changed = effort["auto_changed_cells"]
    effort.update({
        "manual_cell_edits_saved": baseline - effort["manual_cell_edits_required"],
        "manual_cell_edit_reduction": (baseline - effort["manual_cell_edits_required"]) / max(1, baseline),
        "auto_change_improvement_rate": effort["auto_changes_improved"] / max(1, changed),
        "verification_elapsed_seconds": round(effort.pop("verification_elapsed_ms") / 1000, 3),
        "timing_scope": "machine OCR verification time; human review time is recorded only by real review submissions",
    })
    effort_gates = {
        "manual_cell_edit_reduction": effort["manual_cell_edit_reduction"] >= manifest["gates"].get("manual_cell_edit_reduction", 0.0),
        "critical_edits_required": effort["critical_edits_required"] <= manifest["gates"].get("critical_edits_required", 0),
        "auto_changes_worsened": effort["auto_changes_worsened"] <= manifest["gates"].get("auto_changes_worsened", 0),
        "verification_time_budget": effort["verification_elapsed_seconds"] <= manifest["gates"].get("verification_elapsed_seconds", float("inf")),
    }
    gates.update(effort_gates)
    return {"metrics":metrics,"review_effort":effort,"failures":failures,
            "acceptance":{"passed":all(gates.values()),"checks":gates}}


def evaluate(workspace: Path, output: Path):
    started = time.monotonic()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source = (workspace/manifest["source"]).resolve()
    if not source.is_relative_to(workspace.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest()!=manifest["source_sha256"]:
        raise ValueError("Fixed source identity mismatch")
    ocr = evaluate_ocr(source,sorted({s["page"] for s in manifest["tables"]}),output)
    graphs = {r["page"]:json.loads((output/f"graph-p{r['page']}.json").read_text(encoding="utf-8")) for r in ocr["rows"]}
    result = score_graphs(graphs,manifest)
    result["review_effort"]["processing_elapsed_seconds"] = round(time.monotonic() - started, 3)
    return {**result,"schema":"clawos.scanned-table-quality.v1","ocr":ocr,
            "manifest_sha256":hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),"source_sha256":manifest["source_sha256"],
            "release_claim_allowed":False,"truth_boundary":"Four tables in two rasterized pages of one real document; agent visual transcription, not independent human/held-out truth. Correlated cell Wilson intervals are descriptive only."}
