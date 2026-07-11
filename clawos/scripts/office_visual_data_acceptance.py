#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from services.office_productivity_service import OfficeProductivityService
from services.autonomous_subagent_service import AutonomousSubagentService


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="clawos-office-visual-") as td:
        root=Path(td); service=OfficeProductivityService(allowed_roots=[root])
        long_table=[["序号 No.","区域 Region","收入 Revenue","状态 Status"], *[[i, "华东 East" if i%2 else "华西 West", i*1250, "已复核 Reviewed"] for i in range(1,81)]]
        sections=[{"heading":"执行摘要 Executive Summary","paragraphs":["本报告验证中英文混排、长表分页、可搜索文本和专业层级。 This report validates mixed-language layout and pagination."],"table":long_table}]
        docx=service.create(root/"quality.docx",title="经营分析 Business Review",sections=sections,metadata={"subtitle":"Visual quality acceptance","footer":"ClawOS • 2026"},confirmed=True)
        pdf=service.create(root/"quality.pdf",title="经营分析 Business Review",sections=sections,confirmed=True)
        pptx=service.create(root/"quality.pptx",title="Business Review",data=[{"title":"Revenue quality is measurable","bullets":["Auditable formulas and filters","Visual gates before release","Independent reviewer rejects unsupported claims"]}],confirmed=True)
        rows=[{"region":"East","revenue":120.0,"cost":70.0},{"region":"East","revenue":180.0,"cost":90.0},{"region":"West","revenue":100.0,"cost":65.0}]
        analysis=service.analyze_data(rows,root/"analysis.xlsx",title="Revenue Analysis",group_by="region",metrics=["revenue","cost"],confirmed=True)
        from reportlab.pdfgen import canvas
        image_only=root/"ocr_required.pdf"; c=canvas.Canvas(str(image_only)); c.rect(72,500,400,180,stroke=1,fill=0); c.showPage(); c.save()
        audits={
            "docx":service.quality_audit(docx["path"]),
            "docx_template":service.quality_audit(docx["path"],template_path=docx["path"]),
            "pdf":service.quality_audit(pdf["path"],strict_visual=True),
            "pptx":service.quality_audit(pptx["path"]),
            "xlsx":service.quality_audit(analysis["workbook"]),
            "ocr_detection":service.quality_audit(image_only),
        }
        roles=AutonomousSubagentService.advanced_data_team("Analyze revenue",source_description="regional sales table")
        checks={
            "docx_structure":audits["docx"]["quality_gate"]=="pass",
            "template_fidelity":audits["docx_template"]["quality_gate"]=="pass",
            "pdf_rendered":audits["pdf"]["quality_gate"]=="pass" and audits["pdf"]["render"]["pages"]>=1,
            "pptx_no_overflow":audits["pptx"]["quality_gate"]=="pass",
            "xlsx_analysis":audits["xlsx"]["quality_gate"]=="pass" and analysis["grouped"]["East"]["revenue"]==300 and next(item for item in audits["xlsx"]["checks"] if item["name"]=="formula_integrity")["detail"]["formulas"]>=8,
            "ocr_pdf_rejected":audits["ocr_detection"]["quality_gate"]=="revision_required" and "searchable_or_ocr_required" in audits["ocr_detection"]["hard_failures"],
            "advanced_data_team":len(roles)==4 and roles[-1].hard_gate,
        }
        return {"schema":"clawos.office-visual-data-acceptance.v1","ok":all(checks.values()),"checks":checks,"audits":audits,"analysis":{"rows":analysis["rows"],"summary":analysis["summary"],"grouped":analysis["grouped"],"correlations":analysis["correlations"]},"subagent_roles":[item.role_id for item in roles]}


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--out",default=""); args=parser.parse_args(); result=run(); text=json.dumps(result,ensure_ascii=False,indent=2); print(text)
    if args.out: Path(args.out).write_text(text+"\n",encoding="utf-8")
    return 0 if result["ok"] else 1

if __name__=="__main__": raise SystemExit(main())
