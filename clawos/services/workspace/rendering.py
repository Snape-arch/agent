"""Rendering workflows and their domain dependencies."""
from __future__ import annotations
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


class ResearchReportRenderer:
    """Workspace rendering responsibilities."""

    def _write_learning_analysis_pdf(self, path, title, markdown):
        from services.pdf_math_renderer import PdfMathRenderer
        if not PdfMathRenderer.has_math(markdown) and self._write_learning_analysis_typst_pdf(path, title, markdown):
            return "typst"
        self._write_learning_analysis_reportlab_pdf(path, title, markdown)
        return "reportlab"


    def _write_learning_analysis_typst_pdf(self, path, title, markdown):
        typst = shutil.which("typst")
        if not typst:
            return False
        typ_path = Path(path).with_suffix(".typ")
        typ_body = self._markdown_to_typst(title, markdown)
        typ_path.write_text(typ_body, encoding="utf-8")
        try:
            proc = subprocess.run(
                [typst, "compile", str(typ_path), str(path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            return proc.returncode == 0 and Path(path).is_file() and Path(path).stat().st_size > 1000
        except Exception:
            return False


    @staticmethod
    def _markdown_to_typst(title, markdown):
        def esc_typ(value):
            return str(value).replace("\\", "\\\\").replace("#", "\\#").replace("$", "\\$").replace("[", "\\[").replace("]", "\\]")
        lines = [
            '#set document(title: "' + esc_typ(title) + '", author: "ClawOS")',
            "#set page(paper: \"a4\", margin: (x: 22mm, y: 22mm))",
            "#set text(font: (\"Noto Sans CJK SC\", \"Microsoft YaHei\", \"Arial\"), size: 10.5pt, fill: rgb(\"07111f\"))",
            "#set par(justify: true, leading: 0.62em)",
            "#show heading: it => { set text(fill: rgb(\"0b3344\")); it }",
            "#align(center)[",
            "#text(size: 9pt, fill: rgb(\"0b3344\"))[Journal-style paper reading dossier]",
            "#linebreak()",
            "#text(size: 22pt, weight: \"bold\")[" + esc_typ(title) + "]",
            "]",
            "#v(10pt)",
            "#line(length: 45%, stroke: rgb(\"0b3344\"))",
            "#v(16pt)",
        ]
        for raw in markdown.splitlines():
            line = raw.strip()
            if not line:
                lines.append("")
            elif line.startswith("# "):
                lines.append("= " + esc_typ(line[2:]))
            elif line.startswith("## "):
                lines.append("== " + esc_typ(line[3:]))
            elif line.startswith("### "):
                lines.append("=== " + esc_typ(line[4:]))
            elif line.startswith("#### "):
                lines.append("==== " + esc_typ(line[5:]))
            elif line.startswith("- "):
                lines.append("- " + esc_typ(line[2:]))
            else:
                lines.append(esc_typ(line))
        return "\n".join(lines) + "\n"


    def _write_learning_analysis_reportlab_pdf(self, path, title, markdown):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.pdfbase.ttfonts import TTFont
        except Exception as exc:  # pragma: no cover - depends on local optional package
            raise RuntimeError(f"reportlab is required to generate PDF: {exc}") from exc
        font_name = "STSong-Light"
        for font_path in (
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/msyhbd.ttc"),
            Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
            Path("C:/Windows/Fonts/simsunb.ttf"),
            Path("C:/Windows/Fonts/simhei.ttf"),
        ):
            if font_path.is_file():
                font_name = "ClawOSCJK"
                pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
                break
        else:
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        page_width, page_height = A4
        doc = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=24 * mm,
            bottomMargin=22 * mm,
            title=title,
            author="ClawOS",
        )
        sample = getSampleStyleSheet()
        palette = {
            "ink": colors.HexColor("#07111f"),
            "muted": colors.HexColor("#172033"),
            "rule": colors.HexColor("#7f8ea3"),
            "accent": colors.HexColor("#16765b"),
            "soft": colors.HexColor("#eff7f3"),
        }
        styles = {
            "Title": ParagraphStyle(
                "ClawOSTitle",
                parent=sample["Title"],
                fontName=font_name,
                fontSize=22,
                leading=29,
                textColor=palette["ink"],
                alignment=1,
                spaceAfter=12,
            ),
            "Kicker": ParagraphStyle(
                "ClawOSKicker",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=9,
                leading=13,
                textColor=palette["accent"],
                alignment=1,
                uppercase=True,
                spaceAfter=16,
            ),
            "Body": ParagraphStyle(
                "ClawOSBody",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=10.8,
                leading=17.2,
                firstLineIndent=12,
                textColor=palette["ink"],
                spaceAfter=5,
            ),
            "Lead": ParagraphStyle(
                "ClawOSLead",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=11.4,
                leading=18.4,
                textColor=palette["muted"],
                alignment=1,
                spaceAfter=16,
            ),
            "Heading1": ParagraphStyle(
                "ClawOSHeading1",
                parent=sample["Heading1"],
                fontName=font_name,
                fontSize=15.5,
                leading=21.5,
                textColor=palette["accent"],
                spaceBefore=14,
                spaceAfter=8,
                keepWithNext=True,
            ),
            "Heading2": ParagraphStyle(
                "ClawOSHeading2",
                parent=sample["Heading2"],
                fontName=font_name,
                fontSize=13,
                leading=18.5,
                textColor=palette["ink"],
                spaceBefore=10,
                spaceAfter=6,
                keepWithNext=True,
            ),
            "Heading3": ParagraphStyle(
                "ClawOSHeading3",
                parent=sample["Heading3"],
                fontName=font_name,
                fontSize=10.8,
                leading=16,
                textColor=palette["accent"],
                spaceBefore=8,
                spaceAfter=4,
                keepWithNext=True,
            ),
            "Bullet": ParagraphStyle(
                "ClawOSBullet",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=10.4,
                leading=16,
                leftIndent=13,
                firstLineIndent=-8,
                textColor=palette["ink"],
                bulletIndent=0,
                spaceAfter=4,
            ),
            "Evidence": ParagraphStyle(
                "ClawOSEvidence",
                parent=sample["BodyText"],
                fontName=font_name,
                fontSize=9.8,
                leading=14.6,
                leftIndent=10,
                rightIndent=10,
                borderColor=palette["rule"],
                borderWidth=0.9,
                borderPadding=6,
                backColor=palette["soft"],
                textColor=palette["ink"],
                spaceBefore=4,
                spaceAfter=8,
            ),
        }

        def header_footer(canvas, _doc):
            canvas.saveState()
            canvas.setStrokeColor(palette["rule"])
            canvas.setLineWidth(0.65)
            canvas.line(doc.leftMargin, page_height - 16 * mm, page_width - doc.rightMargin, page_height - 16 * mm)
            canvas.setFont(font_name, 8.8)
            canvas.setFillColor(palette["muted"])
            canvas.drawString(doc.leftMargin, page_height - 12 * mm, "ClawOS Research Learning Analysis")
            short_title = str(title)
            available = (page_width-doc.leftMargin-doc.rightMargin)*.48
            while pdfmetrics.stringWidth(short_title,font_name,8.8)>available and short_title:
                short_title=short_title[:-1]
            if short_title != str(title): short_title=short_title[:-1]+'…'
            canvas.drawRightString(page_width - doc.rightMargin, page_height - 12 * mm, short_title)
            canvas.line(doc.leftMargin, 14 * mm, page_width - doc.rightMargin, 14 * mm)
            canvas.drawString(doc.leftMargin, 9 * mm, datetime.now(timezone.utc).strftime("Generated %Y-%m-%d UTC"))
            canvas.drawRightString(page_width - doc.rightMargin, 9 * mm, f"Page {canvas.getPageNumber()}")
            canvas.restoreState()

        from services.pdf_math_renderer import PdfMathRenderer
        math_renderer = PdfMathRenderer(max_width=doc.width - 24)
        for style in styles.values():
            style.autoLeading = "max"

        def plain_inline(text):
            # Keep portable local source labels; only safe absolute web links
            # become PDF annotations. Escape content before ReportLab markup.
            text = re.sub(r'`([^`]+)`', r'\1', str(text))
            parts=[];start=0
            for match in re.finditer(r'\[([^\]]+)\]\(([^\s)]+)\)',text):
                parts.append(xml_escape(text[start:match.start()]))
                label,url=match.groups()
                parts.append(f'<a href="{xml_escape(url)}" color="#16765b">{xml_escape(label)}</a>'
                             if url.startswith(('https://','http://')) and '"' not in url
                             else xml_escape(label))
                start=match.end()
            parts.append(xml_escape(text[start:]))
            return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", ''.join(parts))

        def md_inline(text):
            return math_renderer.inline(str(text), plain_inline)

        compact_grounded = '## 引用核查与原文索引' in markdown and len(markdown)<18000
        story = []
        story.append(Spacer(1, 10))
        story.append(Paragraph("论文精读报告 · 来源 / 实验条件 / 适用边界" if compact_grounded else "Journal-style paper reading dossier", styles["Kicker"]))
        story.append(Paragraph(md_inline(title), styles["Title"]))
        story.append(HRFlowable(width="45%", thickness=1.0, color=palette["accent"], spaceBefore=2, spaceAfter=14, hAlign="CENTER"))
        story.append(Paragraph("依据上传原文整理，保留引用与核查入口。" if compact_grounded else "Structured parsing, self-questioning, evidence tracing, concepts, limits, and follow-up reading plan.", styles["Lead"]))
        if not compact_grounded:
            story.append(PageBreak())
        markdown_lines = math_renderer.markdown_lines(markdown)
        for line_index,raw in enumerate(markdown_lines):
            line = raw.strip()
            if not line:
                if not compact_grounded: story.append(Spacer(1, 5))
                continue
            if line.startswith("# "):
                if compact_grounded and line[2:].strip() == str(title).strip():
                    continue
                story.append(Paragraph(md_inline(line[2:]), styles["Heading1"]))
                story.append(HRFlowable(width="100%", thickness=0.6, color=palette["rule"], spaceBefore=0, spaceAfter=7))
            elif line.startswith("## "):
                story.append(Paragraph(md_inline(line[3:]), styles["Heading1"]))
            elif line.startswith("### "):
                story.append(Paragraph(md_inline(line[4:]), styles["Heading2"]))
            elif line.startswith("#### "):
                story.append(Paragraph(md_inline(line[5:]), styles["Heading3"]))
            elif line.startswith("- "):
                paragraph=Paragraph(md_inline(line[2:]), styles["Bullet"], bulletText="-")
                if line.startswith('- [doc:') and '](' in line: paragraph.keepWithNext=True
                if line_index+1<len(markdown_lines) and markdown_lines[line_index+1].strip().startswith('- 实验条件：'):
                    paragraph.keepWithNext=True
                story.append(paragraph)
            elif line.startswith('> '):
                story.append(Paragraph(md_inline(line[2:]), styles['Evidence']))
            elif line.startswith("璇佹嵁") or line.startswith("证据") or line.lower().startswith("evidence"):
                # Keep heading/paragraph grouping visible to the document's
                # pagination algorithm; a nested KeepTogether can orphan the
                # preceding keepWithNext heading at the end of a page.
                story.append(Paragraph(md_inline(line), styles["Evidence"]))
            else:
                story.append(Paragraph(md_inline(line), styles["Body"]))
        try:
            doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
        finally:
            math_renderer.close()
