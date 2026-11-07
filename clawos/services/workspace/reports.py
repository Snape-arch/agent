"""Reports workflows and their domain dependencies."""
from __future__ import annotations
import json
import hashlib
import re
import uuid
from services.workspace.shared import WorkspaceValues


class ReportsWorkspace:
    """Workspace reports responsibilities."""

    def __init__(self, store, security, research, renderer):
        self.store = store
        self.security = security
        self.research = research
        self.renderer = renderer

    def generate_research_learning_analysis(
        self,
        document_id=None,
        file_path="",
        title="",
        output_dir="",
        formats=None,
        depth=5,
        question_count=50,
        report_style="journal",
    ):
        """Generate an editable self-questioning paper study report."""
        formats = formats or ["markdown", "pdf"]
        formats = [str(item).lower() for item in formats]
        if not formats or set(formats) - {'markdown','md','pdf','json'}:
            raise ValueError('report formats must be markdown, pdf or json')
        if not output_dir:
            raise ValueError("output_dir is required")
        out = self.security.resolve_path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        document = self._resolve_research_document(document_id, file_path, title)
        chunks = self._research_document_chunks(document["id"])
        if not chunks:
            raise ValueError("document has no extracted text chunks")
        pages = {}
        for chunk in chunks:
            pages.setdefault(int(chunk["page_number"]), []).append(chunk["content"])
        page_text = {page: "\n".join(parts) for page, parts in pages.items()}
        full_text = "\n".join(page_text[page] for page in sorted(page_text))
        max_depth = max(1, min(int(depth or 5), 5))
        max_questions = max(6, min(int(question_count or 50), 80))
        report_styles = {"journal", "learning_notes", "business_brief", "compact"}
        report_style = str(report_style or "journal").lower()
        if report_style not in report_styles:
            report_style = "journal"
        outline = self._paper_outline(full_text)
        topics = self._analysis_topics(outline, full_text, max(3, min(8, max_questions // max_depth)))
        questions = self._analysis_questions(topics, page_text, max_depth, max_questions)
        concepts = self._paper_concepts(full_text, limit=14)
        report = self._render_learning_analysis_markdown(document, outline, questions, concepts, max_depth, report_style)
        safe_name = WorkspaceValues._safe_filename(f"{document['title']}_learning_analysis")[:150] + '_' + uuid.uuid4().hex[:12]
        markdown_path = ""
        pdf_path = ""
        if "markdown" in formats or "md" in formats:
            markdown = out / f"{safe_name}.md"
            markdown.write_text(report, encoding="utf-8")
            markdown_path = str(markdown)
        if "pdf" in formats:
            pdf = out / f"{safe_name}.pdf"
            pdf_engine = self.renderer._write_learning_analysis_pdf(pdf, document["title"], report)
            pdf_path = str(pdf)
        else:
            pdf_engine = ""
        json_path = ''
        document_export=self._learning_report_document(document)
        if 'json' in formats:
            json_file = out / f'{safe_name}.json'
            from services.file_transactions import write_text
            write_text(json_file, json.dumps(dict(document=document_export,outline=outline,questions=questions,
                                                 concepts=concepts), ensure_ascii=False, indent=2))
            json_path = str(json_file)
        metadata = {
            "formats": formats,
            "source_file": document["file_path"],
            "page_count": document["page_count"],
            "outline_count": len(outline),
            "concept_count": len(concepts),
            "mode": "deterministic_evidence_based",
            "report_style": report_style,
            "pdf_engine": pdf_engine,
            "json_path": json_path,
        }
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO research_analysis_reports
                    (document_id, title, output_dir, markdown_path, pdf_path, question_count, depth, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(document["id"]), document["title"], str(out), markdown_path, pdf_path,
                    len(questions), max_depth, json.dumps(metadata, ensure_ascii=False),
                ),
            )
            row = c.execute(
                "SELECT * FROM research_analysis_reports WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
        item = dict(row)
        item["metadata"] = json.loads(item["metadata"] or "{}")
        item['json_path'] = json_path
        return {"report": item, "document": document_export, "preview": report[:1200]}


    @staticmethod
    def _learning_report_document(document,metadata_reference='research_documents.metadata'):
        # Full glyph/geometry metadata stays in its authoritative DB row. A
        # report references that snapshot instead of copying megabytes into JSON.
        metadata=document.get('metadata') or {}
        if isinstance(metadata,str):
            try:metadata=json.loads(metadata)
            except ValueError:pass
        encoded=json.dumps(metadata,ensure_ascii=False,sort_keys=True).encode('utf-8')
        value={k:v for k,v in document.items() if k!='metadata'}
        value['metadata']=dict(included=False,source_sha256=hashlib.sha256(encoded).hexdigest(),source_bytes=len(encoded),reference=metadata_reference)
        return value


    def _resolve_research_document(self, document_id=None, file_path="", title=""):
        with self.store._conn() as c:
            if document_id:
                row = c.execute(
                    "SELECT * FROM research_documents WHERE id=?",
                    (int(document_id),),
                ).fetchone()
                if not row:
                    raise ValueError("research document not found")
                return dict(row)
            if file_path:
                path = self.security.resolve_path(file_path)
                row = c.execute(
                    "SELECT * FROM research_documents WHERE file_path=?",
                    (str(path),),
                ).fetchone()
                if row:
                    return dict(row)
        if file_path:
            return self.research.import_research_pdf(file_path, title)
        raise ValueError("document_id or file_path is required")


    def _research_document_chunks(self, document_id):
        with self.store._conn() as c:
            return [dict(row) for row in c.execute(
                """
                SELECT page_number, chunk_index, content
                FROM research_chunks
                WHERE document_id=?
                ORDER BY page_number, chunk_index
                """,
                (int(document_id),),
            ).fetchall()]


    def _paper_outline(self, text):
        lines = [line.strip() for line in str(text).splitlines() if line.strip()]
        outline = []
        for line in lines:
            compact = re.sub(r"\s+", " ", line)
            if len(compact) > 90:
                continue
            if self._is_outline_noise(compact):
                continue
            if re.match(r"^(\d+(\.\d+)*|[一二三四五六七八九十]+[、.．]|第.+[章节部分]|[A-Z][A-Za-z ]{4,})", compact):
                outline.append(compact)
            if len(outline) >= 18:
                break
        return outline or [line[:80] for line in lines[:8]]


    def _analysis_topics(self, outline, text, target_count):
        topics = []
        for item in outline:
            clean = re.sub(r"^[\d.．、\s]+", "", item).strip()
            if clean and len(clean) <= 55 and not self._is_outline_noise(clean) and clean not in topics:
                topics.append(clean)
            if len(topics) >= target_count:
                break
        for concept in self._paper_concepts(text, limit=target_count * 2):
            if concept not in topics:
                topics.append(concept)
            if len(topics) >= target_count:
                break
        return topics or ["研究问题", "方法框架", "实验设计"]


    def _analysis_questions(self, topics, page_text, depth, question_count):
        pages = sorted(page_text)
        questions = []
        templates = [
            "这篇论文围绕“{topic}”到底想解决什么核心问题？",
            "作者为什么认为“{topic}”是必要的，而不是可选优化？",
            "论文中支撑“{topic}”的关键方法、系统模块或假设是什么？",
            "如果从实验和证据角度追问，“{topic}”的结论由哪些结果支撑？",
            "继续深挖，“{topic}”还有哪些局限、适用边界和可复现风险？",
        ]
        cursor = 0
        while len(questions) < question_count and topics:
            for topic_index, topic in enumerate(topics, 1):
                for level in range(1, depth + 1):
                    if len(questions) >= question_count:
                        break
                    page = pages[(len(questions) + cursor) % len(pages)]
                    evidence = self._best_evidence_for_topic(page_text, topic, page)
                    template = templates[min(level - 1, len(templates) - 1)]
                    questions.append({
                        "topic_index": topic_index,
                        "topic": topic,
                        "level": level,
                        "question": template.format(topic=topic),
                        "answer": self._evidence_answer(topic, evidence, level),
                        "evidence": evidence,
                        "page": evidence["page"],
                    })
                if len(questions) >= question_count:
                    break
            cursor += 1
        return questions


    @staticmethod
    def _is_outline_noise(text):
        compact = str(text or "").strip()
        if not compact:
            return True
        lowered = compact.lower()
        if lowered in {"contents", "references", "acknowledgements"}:
            return True
        if re.fullmatch(r"第[一二三四五六七八九十]+部分[·：:].*", compact):
            return True
        if compact in {"总览", "关键概念名词表", "局限性与可改进方向"}:
            return True
        if re.fullmatch(r"\d+", compact):
            return True
        if re.search(r"\.{4,}", compact):
            return True
        if len(compact) <= 2:
            return True
        return False


    def _best_evidence_for_topic(self, page_text, topic, fallback_page):
        topic_terms = [term.lower() for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", str(topic))[:4]]
        best = (0, fallback_page, page_text.get(fallback_page, ""))
        for page, text in page_text.items():
            lowered = text.lower()
            score = sum(lowered.count(term) for term in topic_terms)
            if score > best[0]:
                best = (score, page, text)
        sentences = re.split(r"(?<=[。！？.!?])\s+", best[2].strip())
        snippet = next((
            s.strip() for s in sentences
            if len(s.strip()) > 30
            and not self._is_outline_noise(s.strip())
            and not s.strip().lower().startswith("contents")
            and (not topic_terms or any(term in s.lower() for term in topic_terms))
        ), "")
        if not snippet:
            snippet = next((
                s.strip() for s in sentences
                if len(s.strip()) > 30
                and not self._is_outline_noise(s.strip())
                and not s.strip().lower().startswith("contents")
            ), best[2].strip()[:420])
        return {"page": best[1], "snippet": snippet[:520]}


    def _evidence_answer(self, topic, evidence, level):
        lead = [
            "先抓主线：",
            "继续追问动机：",
            "落到机制层：",
            "回到证据链：",
            "最后检查边界：",
        ][min(level - 1, 4)]
        return (
            f"{lead}围绕“{topic}”，报告应从论文原文证据出发解释其角色。"
            f"当前可引用第 {evidence['page']} 页片段：{evidence['snippet']}"
        )


    def _paper_concepts(self, text, limit=12):
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,8}", str(text))
        stop = {
            "the", "and", "with", "from", "this", "that", "contents",
            "研究", "论文", "方法", "系统", "结果", "总览", "主题", "解析报告",
        }
        counts = {}
        for word in words:
            key = word.strip()
            if key.lower() in stop or len(key) < 2:
                continue
            counts[key] = counts.get(key, 0) + 1
        return [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


    def _paper_quality_insights(self, document, outline, questions, concepts):
        chunks = self._research_document_chunks(document["id"])
        text = "\n".join(chunk["content"] for chunk in chunks)
        lowered = text.lower()
        signals = {
            "method": ["method", "approach", "framework", "algorithm", "model", "architecture", "pipeline"],
            "experiment": ["experiment", "evaluation", "benchmark", "dataset", "metric", "result", "ablation"],
            "reproducibility": ["code", "implementation", "parameter", "hyperparameter", "environment", "github", "appendix"],
            "limitation": ["limitation", "future work", "threat", "risk", "failure", "error"],
        }
        signal_rows = []
        for name, terms in signals.items():
            hits = sum(lowered.count(term) for term in terms)
            signal_rows.append((name, hits, "strong" if hits >= 3 else "partial" if hits else "missing"))
        cited_pages = sorted({q["page"] for q in questions})
        evidence_density = round(len(questions) / max(len(cited_pages), 1), 2)
        top_concepts = ", ".join(concepts[:8]) or "not enough terms"
        outline_preview = " / ".join(outline[:5]) or "no explicit outline"
        return [
            "",
            "## Paper Intelligence Addendum",
            "",
            "### Contribution Reading",
            f"- Claimed focus: {self._one_sentence_summary(questions)}",
            f"- Outline signal: {outline_preview}",
            f"- Key concept cluster: {top_concepts}",
            "",
            "### Method And Evidence Signals",
            *[f"- {name}: {status} ({hits} keyword hits)" for name, hits, status in signal_rows],
            f"- Evidence density: {len(questions)} question nodes over {max(len(cited_pages), 1)} cited pages, about {evidence_density} nodes/page.",
            "",
            "### Reproducibility Checklist",
            "- Problem statement: verify that the target task, inputs, and expected outputs are explicit.",
            "- Method mechanism: trace each module to a cited sentence, figure, table, or experiment.",
            "- Evaluation protocol: confirm dataset, metric, baseline, ablation, and failure case coverage.",
            "- Rebuild plan: convert the strongest L3-L5 questions into implementation tasks before coding.",
            "",
            "### Reading Verdict",
            "- Treat strong signal sections as the first pass for presentation slides.",
            "- Treat missing signal sections as follow-up questions for manual reading or model-assisted re-query.",
        ]


    def _render_learning_analysis_markdown(self, document, outline, questions, concepts, depth, report_style="journal"):
        if report_style != "journal":
            return self._render_styled_learning_analysis_markdown(document, outline, questions, concepts, depth, report_style)
        lines = [
            f"# 《{document['title']}》论文深度解析报告",
            "",
            f"本报告由 ClawOS 论文学习工作流生成：先抽取论文结构，再以自我提问方式逐层追问，共形成 {len(questions)} 个问答节点（深度至 L{depth}）。",
            "",
            "## 第一部分 · 总览",
            "",
            "### 1. 论文一句话概述",
            self._one_sentence_summary(questions),
            "",
            "### 2. 论文框架目录",
        ]
        lines.extend(f"- {item}" for item in outline[:18])
        lines.extend([
            "",
            "### 3. 学习时必须回答的核心问题",
            "- 论文解决的对象、痛点和应用场景是什么？",
            "- 方法框架由哪些模块组成，模块之间的数据流是什么？",
            "- 作者用哪些实验、指标或案例支撑结论？",
            "- 哪些结论是强证据，哪些只是合理推断？",
            "- 如果要复现或改进，最先卡住的依赖是什么？",
            "",
            "## 第二部分 · 主题深度解析（按追问分支逐层展开）",
        ])
        grouped = {}
        for question in questions:
            grouped.setdefault(question["topic"], []).append(question)
        for idx, (topic, items) in enumerate(grouped.items(), 1):
            lines.extend(["", f"### 主题 {idx}：{topic}"])
            for item in items:
                lines.extend([
                    "",
                    f"#### L{item['level']} 自问：{item['question']}",
                    "",
                    item["answer"],
                    "",
                    f"证据：第 {item['page']} 页。",
                ])
        lines.extend([
            "",
            "## 第三部分 · 概念表、局限与学习建议",
            "",
            "### 关键概念名词表",
        ])
        lines.extend(f"- **{concept}**：需要结合论文上下文解释定义、作用、输入输出和与其他概念的关系。" for concept in concepts)
        lines.extend([
            "",
            "### 局限性与可改进方向",
            "- 检查论文是否给出足够的消融实验、误差分析和失败案例。",
            "- 检查数据集、硬件环境、超参数和评价指标是否足以复现。",
            "- 区分论文明确声明、实验支持结论和本报告自动生成的学习性推断。",
            "",
            "### 系统性学习建议",
            "- 第一遍只读标题、摘要、图表和结论，建立问题地图。",
            "- 第二遍按本报告问题树逐项回到原文定位证据。",
            "- 第三遍把每个 L4/L5 问题改写成自己的复现任务或讨论题。",
            "- 最后输出一页纸复盘：贡献、证据、局限、可复现计划。",
        ])
        lines.extend(self._paper_quality_insights(document, outline, questions, concepts))
        return "\n".join(lines) + "\n"


    def _render_styled_learning_analysis_markdown(self, document, outline, questions, concepts, depth, report_style):
        title = document["title"]
        summary = self._one_sentence_summary(questions)
        topics = []
        seen = set()
        for question in questions:
            topic = str(question.get("topic") or "General")
            if topic not in seen:
                topics.append(topic)
                seen.add(topic)
        cited_pages = sorted({int(q.get("page") or 1) for q in questions})
        first_questions = questions[: min(len(questions), 8)]
        concept_line = ", ".join(concepts[:10]) or "No dominant concepts detected"
        style_titles = {
            "learning_notes": "Learning Notes",
            "business_brief": "Business Brief",
            "compact": "Compact Report",
        }
        lines = [
            f"# {title} - {style_titles.get(report_style, 'Learning Report')}",
            "",
            f"Source pages: {len(cited_pages)} cited pages. Depth: L{depth}. Question nodes: {len(questions)}.",
            "",
        ]
        if report_style == "learning_notes":
            lines.extend([
                "## Learning Map",
                summary,
                "",
                "## Core Concepts",
                *[f"- {concept}" for concept in concepts[:12]],
                "",
                "## Guided Notes",
            ])
            for topic in topics[:8]:
                related = [q for q in questions if q.get("topic") == topic][:3]
                lines.extend(["", f"### {topic}"])
                for item in related:
                    lines.extend([
                        f"- Q{item['level']}: {item['question']}",
                        f"  Evidence: page {item['page']}. {item['answer']}",
                    ])
            lines.extend([
                "",
                "## Self Check",
                *[f"- Explain {q['topic']} without looking at the source, then verify page {q['page']}." for q in first_questions[:6]],
                "",
                "## Next Study Actions",
                "- Turn weak concepts into flashcards.",
                "- Re-read the cited pages before summarizing from memory.",
                "- Save unresolved questions back into the knowledge base.",
            ])
        elif report_style == "business_brief":
            lines.extend([
                "## Decision Snapshot",
                f"- Main point: {summary}",
                f"- Evidence base: {len(questions)} extracted question/evidence nodes across {len(cited_pages)} pages.",
                f"- Concept cluster: {concept_line}",
                "",
                "## Value And Use Cases",
                *[f"- {topic}" for topic in topics[:6]],
                "",
                "## Evidence To Cite",
                *[f"- Page {q['page']}: {q['answer']}" for q in first_questions[:5]],
                "",
                "## Risks And Open Questions",
                "- Validate whether the paper's assumptions match the target user, market, or deployment context.",
                "- Separate experimentally supported claims from plausible but untested extensions.",
                "- Check reproducibility before using the result as a product or investment claim.",
                "",
                "## Recommended Next Moves",
                "- Convert the strongest claim into one slide or one product requirement.",
                "- Ask follow-up questions against the cited pages before external sharing.",
            ])
        else:
            lines.extend([
                "## One Page Summary",
                summary,
                "",
                "## Key Points",
                *[f"- {topic}" for topic in topics[:5]],
                "",
                "## Evidence",
                *[f"- Page {q['page']}: {q['question']}" for q in first_questions[:6]],
                "",
                "## Concepts",
                concept_line,
                "",
                "## Actions",
                "- Keep the Markdown report as the editable source.",
                "- Use the PDF for review or sharing.",
                "- Save this report back to the knowledge base for later Q&A.",
            ])
        return "\n".join(lines) + "\n"


    def _one_sentence_summary(self, questions):
        if not questions:
            return "本文围绕一个具体研究问题提出方法并通过实验验证。"
        first = questions[0]
        return f"本文围绕“{first['topic']}”展开，核心学习路径应从问题动机、方法机制、实验支撑与边界局限四层理解。"
