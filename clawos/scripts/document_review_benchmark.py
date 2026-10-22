"""Replay real OCR captures through source review; gold edits simulate a reviewer.

This is a workflow acceptance test, NOT a measurement of autonomous OCR accuracy
or independent human review. Uses an isolated database and no paid APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from memoryos.memory_store import MemoryStore
from services.document_review_service import DocumentReviewService
from services.knowledge_service import KnowledgeService
from services.office_productivity_service import OfficeProductivityService
from services.scanned_table_benchmark import MANIFEST, iou, score_graphs, normalized


def evaluate(raw: Path, output: Path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    captured = json.loads((raw/"table-report.json").read_text(encoding="utf-8"))
    if captured["manifest_sha256"] != hashlib.sha256(MANIFEST.read_bytes()).hexdigest() or captured["source_sha256"] != manifest["source_sha256"]:
        raise ValueError("Captured OCR does not match the frozen corpus")
    output.mkdir(parents=True, exist_ok=True)
    before, after, documents, controls = {}, {}, [], []
    disagreements, erroneous_critical, fixed_candidates = 0, 0, 0
    with tempfile.TemporaryDirectory(prefix="clawos-review-benchmark-") as td:
        store = MemoryStore(str(Path(td)/"review.db"))
        review = DocumentReviewService(store,[raw])
        for page in sorted({t["page"] for t in manifest["tables"]}):
            source = (raw/f"scan-p{page}.pdf").resolve()
            graph = json.loads((raw/f"graph-p{page}.json").read_text(encoding="utf-8"))
            before[page] = json.loads(json.dumps(graph))
            record = store.add_document(f"Captured page {page}",filename=source.name,file_path=str(source),
                        file_hash=hashlib.sha256(source.read_bytes()).hexdigest(),status="needs_ocr",metadata={"ocr_required":True})
            meta = {"semantic_graph":graph,"structure":{"tables":graph["tables"]},"ocr_review_pages":[1],"ocr_required":False}
            # Replay captured recognizer output through the actual console service.
            with patch("memoryos.document_ingestion.extract_pdf_text_enhanced",return_value=(graph["plain_text"],meta)):
                KnowledgeService(store,Path(td)).run_ocr(record["id"])
            expected = {}
            for spec in [s for s in manifest["tables"] if s["page"] == page]:
                table = max(graph["tables"],key=lambda t:iou(t["bbox"],spec["bbox"]))
                if iou(table["bbox"],spec["bbox"]) < .95:
                    raise ValueError("Required table missing; cannot simulate review")
                for cell in table["cells"]:
                    expected[cell["id"]] = spec["rows"][cell["row"]][cell["column"]]
                for anchor in spec.get("critical",[]):
                    cell = next(c for c in table["cells"] if c["row"] == anchor["row"] and c["column"] == anchor["column"])
                    if normalized(anchor["contains"]) not in normalized(cell["text"]):
                        erroneous_critical += 1
                        verification = cell.get("verification",{})
                        disagreements += verification.get("status") == "disagreement"
                        fixed_candidates += any(normalized(anchor["contains"]) in normalized(c["text"]) for c in verification.get("candidates",[]))
                        (output/f"source-p{page}-r{cell['row']}c{cell['column']}.png").write_bytes(review.crop(record["id"],cell["id"]))
            controls.append(not any("table_row" in c["metadata"].get("evidence_types",[]) for c in store.get_document_chunks(record["id"],10000)))
            controls.append(review.publish(record["id"],confirmed=True)["count"] == 0)
            reviewed = 0
            while True:
                queue = review.queue(record["id"])
                item = next((i for i in queue["items"] if i["cells"] and all(c["id"] in expected for c in i["cells"])), None)
                if not item:
                    break
                review.submit(record["id"],chunk_id=item["chunk_id"],revision=queue["revision"],
                              values={c["id"]:expected[c["id"]] for c in item["cells"]},confirmed=True,actor="benchmark_simulated_reviewer")
                reviewed += 1
            first = review.publish(record["id"],confirmed=True)
            controls.append(first == review.publish(record["id"],confirmed=True))
            after[page] = store.get_document(record["id"],include_review=True)["metadata"]["semantic_graph"]
            safe = store.get_document(record["id"])["metadata"]["semantic_graph"]
            OfficeProductivityService(store,allowed_roots=[output]).create(output/f"reviewed-p{page}.md",title=f"Reviewed page {page}",
                sections=[{"heading":"Source-reviewed table","table":table} for table in safe["tables"]],confirmed=True)
            exported = normalized((output/f"reviewed-p{page}.md").read_text(encoding="utf-8"))
            controls.append(all(normalized(value) in exported for value in expected.values()))
            answer = KnowledgeService(store,Path(td)).citation_answer(document_id=record["id"],limit=12)
            controls.append(not any(bad in json.dumps(answer,ensure_ascii=False) for bad in ("959%", "7 信")))
            documents.append({"source_page":page,"reviewed_rows":reviewed,"published_rows":first["count"],
                              "remaining_non_table_review":len(review.queue(record["id"])["items"]),
                              "audit_events":len(review.queue(record["id"])["history"])})
            (output/f"reviewed-graph-p{page}.json").write_text(json.dumps(safe,ensure_ascii=False,indent=2),encoding="utf-8")
        raw_result, corrected = score_graphs(before,manifest), score_graphs(after,manifest)
        controls.extend(corrected["metrics"][key]["rate"] == 1 for key in ("cell_text_exact","critical_exact","cell_coordinates","header_links"))
        return {"schema":"clawos.document-review-workflow.v1","workflow_passed":all(controls),
                "checks_passed":sum(controls),"checks_total":len(controls),"raw_metrics":raw_result["metrics"],
                "post_simulated_review_metrics":{k:v for k,v in corrected["metrics"].items() if k != "critical_review"},
                "erroneous_critical_anchors":erroneous_critical,"disagreement_detected":disagreements,
                "correct_anchor_in_candidates":fixed_candidates,"documents":documents,
                "release_claim_allowed":False,"independent_human_review":False,
                "truth_boundary":"Frozen gold edits simulate user confirmation on real captured OCR in a temporary DB. Post-review accuracy is by construction, not autonomous recognition or production human accuracy."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    report = evaluate(args.raw.resolve(),args.out.resolve())
    (args.out/"review-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report["workflow_passed"] else 1)
