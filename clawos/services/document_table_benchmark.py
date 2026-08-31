"""Exact cell/condition checks on a versioned, visually transcribed PDF corpus."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .document_fidelity_benchmark import DocumentFidelityBenchmark
from .document_semantic_graph_service import DocumentSemanticGraphService

MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks/document_table_cells_v1.json"


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


class DocumentTableBenchmark:
    @staticmethod
    def evaluate_table(graph: dict, spec: dict) -> dict:
        candidates = [t for t in graph.get("tables", []) if t.get("page") == spec["page"]
                      and norm(spec["caption"]) in norm(t.get("caption", "")) and not t.get("semantic_only")]
        table = candidates[0] if len(candidates) == 1 else {}
        cells = {(c["row"], c["column"]): c for c in table.get("cells", [])}
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        checks = {key: [] for key in ("values", "headers", "annotations", "row_context", "evidence_conditions", "cell_coordinates", "graph_links", "table_geometry")}
        failures = []
        def record(metric: str, passed: bool, **detail):
            checks[metric].append(bool(passed))
            if not passed:
                failures.append({"metric": metric, **detail})
        actual_box = table.get("bbox", [])
        record("table_geometry", len(actual_box) == 4 and all(abs(a - b) <= 3 for a, b in zip(actual_box, spec["bbox"])), expected=spec["bbox"], actual=actual_box)
        record("table_geometry", len(table.get("rows", [])) == len(spec["rows"]) + 1 and len(table.get("headers", [])) == len(spec["headers"]), detail="exact row/column counts")
        for column, header in enumerate(spec["headers"]):
            actual = cells.get((0, column), {}).get("text", "")
            record("headers", norm(actual) == norm(header), column=column, expected=header, actual=actual)
        for r, expected_row in enumerate(spec["rows"], 1):
            first = cells.get((r, 0), {})
            group, parent = spec["group_by_row"][r-1], spec["parent_by_row"][r-1]
            record("row_context", norm(group) in norm(first.get("group_context", "")) and norm(parent) == norm(first.get("row_context", "")), row=r, expected_group=group, expected_parent=parent)
            row_node = nodes.get(f"{table.get('id')}:row:{r}", {})
            evidence = norm(row_node.get("text", ""))
            record("evidence_conditions", bool(evidence) and all(norm(c) in evidence for c in [*spec["conditions"], group, parent, *spec["headers"]]), row=r)
            for c, expected in enumerate(expected_row):
                cell = cells.get((r, c), {})
                actual = cell.get("value_text", "")
                record("values", norm(actual) == norm(expected), row=r, column=c, expected=expected, actual=actual)
                box = cell.get("bbox", [])
                record("cell_coordinates", len(box) == 4 and len(actual_box) == 4 and actual_box[0]-2 <= box[0] < box[2] <= actual_box[2]+2 and actual_box[1]-2 <= box[1] < box[3] <= actual_box[3]+2, row=r, column=c)
                refs = cell.get("header_refs", [])
                record("graph_links", bool(refs) and all(ref in nodes for ref in refs + cell.get("group_refs", [])) and cell.get("id") in row_node.get("cell_ids", []), row=r, column=c)
            for c, expected in zip(spec.get("annotation_columns", []), (spec.get("annotations") or [[] for _ in spec["rows"]])[r-1]):
                actual = [a["text"] for a in cells.get((r, c), {}).get("annotations", [])]
                record("annotations", actual == [expected], row=r, column=c, expected=expected, actual=actual)
        return {"caption": spec["caption"], "page": spec["page"], "checks": checks, "failures": failures}

    def evaluate(self, workspace_root: str | Path, manifest_path: str | Path = MANIFEST) -> dict:
        root, path = Path(workspace_root).resolve(), Path(manifest_path)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "clawos.document-table-cells.v1" or not manifest.get("documents"):
            raise ValueError("invalid table corpus")
        rows, identities = [], []
        for document in manifest["documents"]:
            source = (root / document["path"]).resolve()
            verified = root in source.parents and source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == document["sha256"]
            identities.append(verified)
            graph = DocumentSemanticGraphService().parse_pdf(source) if verified else {}
            rows.extend({"path": document["path"], **self.evaluate_table(graph, spec)} for spec in document["tables"])
        totals: dict[str, list] = {}
        for row in rows:
            for name, values in row.pop("checks").items():
                totals.setdefault(name, []).extend(values)
        metrics = {name: DocumentFidelityBenchmark._metric(values) for name, values in totals.items()}
        checks = {name: bool(values) and all(values) for name, values in totals.items()}
        checks["identities_verified"] = all(identities)
        return {"schema": "clawos.document-table-evaluation.v1", "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "tables": rows, "metrics": metrics, "acceptance": {"passed": all(checks.values()), "checks": checks},
                "evaluation_split": manifest["evaluation_split"], "review_status": manifest["review_status"],
                "release_claim_allowed": False, "truth_boundary": manifest["truth_boundary"],
                "interval_boundary": "Descriptive Wilson intervals over correlated cells in four development tables; not held-out generalization bounds."}
