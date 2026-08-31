"""Re-run the fixed real corpus; opt in to local desktop Office automation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.document_fidelity_benchmark import DocumentFidelityBenchmark
from services.office_cross_application_service import OfficeCrossApplicationService
from services.document_table_benchmark import DocumentTableBenchmark


def build_fixture(root: Path) -> Path:
    from PIL import Image, ImageDraw
    from services.office_productivity_service import OfficeProductivityService

    root.mkdir(parents=True, exist_ok=True)
    chart = root / "fixture-chart.png"
    image = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(image)
    for x, y, color in ((100, 40, "#2E74B5"), (480, 110, "#70AD47"), (860, 170, "#D9A441")):
        draw.rectangle((x, y, x + 230, 350), fill=color)
    image.save(chart)
    sections = [
        {"heading": "1 Methods", "paragraphs": [
            "The blinded evaluation used 240 verified records[[FN:protocol]].",
            "See [[REF:figure_1]] for the fixture chart; the bars are synthetic test data.",
        ], "formulas": [{"text": "fidelity = supported / required", "label": "1"}],
         "figures": [{"path": str(chart), "label": "Figure 1", "caption": "Synthetic rendering fixture",
                      "bookmark": "figure_1", "alt_text": "Three synthetic bars used only to test rendering"}]},
        {"heading": "2 Pagination", "page_break": True, "table": {
            "rows": [["Case", "Condition", "Expected behavior"], *[
                [f"R{i:02d}", "A deliberately verbose condition that wraps within the fixed-width cell.",
                 "Header repeats and no cell content is clipped."] for i in range(1, 25)
            ]], "header_rows": 1, "column_widths": [1, 3, 2.5], "label": "Table 1",
            "caption": "Pagination stress matrix", "bookmark": "table_1",
        }},
        {"heading": "3 References", "page_break": True, "paragraphs": [
            "[1] ECMA International. Office Open XML File Formats. ECMA-376.",
        ]},
    ]
    path = root / "cross-app-fidelity.docx"
    result = OfficeProductivityService(allowed_roots=[root], preview_root=root / "previews").create(
        path, title="Office Semantic Fidelity Benchmark", sections=sections, confirmed=True,
        metadata={
            "footnotes": [{"marker": "protocol", "text": "The fixture is deterministic and contains no user-sensitive data."}],
            "comments": [{"target": "240 verified records", "text": "Verify the sample count", "author": "QA"}],
            "revisions": [{"old": "blinded", "new": "double-blinded", "author": "QA"}],
        },
    )
    (root / "generation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=ROOT.parent)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cross-office", action="store_true", help="Explicitly launch installed Word/WPS applications in hidden mode")
    parser.add_argument("--table-cells", action="store_true", help="Also check fixed cell values, annotations and experimental contexts")
    args = parser.parse_args()
    args.out = args.out.resolve(); args.out.mkdir(parents=True, exist_ok=True)
    benchmark = DocumentFidelityBenchmark()
    reports = {"semantic": benchmark.evaluate(args.workspace_root),
               "ocr": benchmark.evaluate_ocr_sample(args.workspace_root / "参考文献/2305.16291v2.pdf")}
    if args.table_cells:
        reports["table_cells"] = DocumentTableBenchmark().evaluate(args.workspace_root)
    if args.cross_office:
        fixture = build_fixture(args.out / "fixture")
        reports["cross_office"] = OfficeCrossApplicationService().evaluate(fixture, args.out / "renders")
        if args.table_cells:
            from services.document_semantic_graph_service import DocumentSemanticGraphService
            from services.office_productivity_service import OfficeProductivityService
            graph = DocumentSemanticGraphService().parse_pdf(args.workspace_root / "参考文献/2310.08560v2.pdf")
            table = next(t for t in graph["tables"] if t.get("page") == 5 and t.get("caption", "").startswith("Table 2."))
            table["column_widths"] = [3, 1.5, 2]
            recovered_path = args.out / "recovered-table.docx"
            result = OfficeProductivityService(allowed_roots=[args.out], preview_root=args.out / "previews").create(
                recovered_path, title="Recovered research table", confirmed=True,
                sections=[{"heading": "MemGPT: deep memory retrieval", "table": table}],
            )
            (args.out / "recovered_generation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            reports["recovered_cross_office"] = OfficeCrossApplicationService().evaluate(recovered_path, args.out / "recovered-renders")
    for name, report in reports.items():
        (args.out / f"{name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {name: report["acceptance"] for name, report in reports.items()}
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if all(report["passed"] for report in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
