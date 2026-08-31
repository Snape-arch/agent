"""Fixed raster table geometry, text, conditions, and negative-region checks."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from services.document_fidelity_benchmark import DocumentFidelityBenchmark
from services.document_ocr_benchmark import evaluate as evaluate_ocr

MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks/scanned_table_regions_v1.json"


def normalized(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).casefold()


def iou(a,b):
    area = max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return area/max(1,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def score_graphs(graphs, manifest):
    checks = {k: [] for k in ("regions", "shape", "cell_text_exact", "cell_coordinates", "header_links", "critical_exact", "critical_review", "negative_regions")}
    failures = []
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
                correct = normalized(actual.get("text","")) == normalized(expected)
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
            checks["critical_exact"].append(normalized(critical["contains"]) in normalized(cell.get("text","")))
            if critical["kind"] == "numeric":
                checks["critical_review"].append(bool(cell.get("numeric_verification_required") and cell.get("review_required")))
    for negative in manifest["negative_regions"]:
        checks["negative_regions"].append(not any(iou(t["bbox"],negative["bbox"])>.1 for t in graphs.get(negative["page"],{}).get("tables",[])))
    metrics = {k:DocumentFidelityBenchmark._metric(v) for k,v in checks.items()}
    gates = {k: m["n"]>0 and m["rate"]>=manifest["gates"].get(k,1.0) for k,m in metrics.items()}
    return {"metrics":metrics,"failures":failures,"acceptance":{"passed":all(gates.values()),"checks":gates}}


def evaluate(workspace: Path, output: Path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source = (workspace/manifest["source"]).resolve()
    if not source.is_relative_to(workspace.resolve()) or hashlib.sha256(source.read_bytes()).hexdigest()!=manifest["source_sha256"]:
        raise ValueError("Fixed source identity mismatch")
    ocr = evaluate_ocr(source,sorted({s["page"] for s in manifest["tables"]}),output)
    graphs = {r["page"]:json.loads((output/f"graph-p{r['page']}.json").read_text(encoding="utf-8")) for r in ocr["rows"]}
    result = score_graphs(graphs,manifest)
    return {**result,"schema":"clawos.scanned-table-quality.v1","ocr":ocr,
            "manifest_sha256":hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),"source_sha256":manifest["source_sha256"],
            "release_claim_allowed":False,"truth_boundary":"Four tables in two rasterized pages of one real document; agent visual transcription, not independent human/held-out truth. Correlated cell Wilson intervals are descriptive only."}
