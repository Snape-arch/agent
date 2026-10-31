from __future__ import annotations

import json
import re
import hashlib
from typing import Any
from .paper_numeric_evidence import audit_numeric_support
from .research_claim_guard import audit_claim_boundaries


REPORT_SECTION_KEYS = ("methodology", "experiments", "findings", "limitations", "contributions")


def _clean_text(value: Any, limit: int = 1400) -> str:
    text = str(value or "").translate(str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}))
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _first_sentence(value: Any, limit: int = 420) -> str:
    text = _clean_text(value, limit * 3)
    match = re.match(r"(.+?[.!?。！？])(?:\s|$)", text)
    return _clean_text(match.group(1) if match else text, limit)


def _clip_words(value: str, limit: int) -> str:
    text = _clean_text(value, max(limit * 3, limit))
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (clipped or text[:limit]).rstrip() + "…"


def _best_sentence(value: Any, section: str = "", limit: int = 520) -> str:
    text = _clean_text(value, 5000)
    if section == "abstract" and re.search(r"\babstract\b", text, re.I):
        text = re.split(r"\babstract\b", text, maxsplit=1, flags=re.I)[-1].strip(" :-")
    candidates = [
        _clean_text(item, max(limit * 2, 1000))
        for item in re.split(r"(?<=[.!?。！？])\s+|\n+", text)
        if 45 <= len(_clean_text(item, limit)) <= max(limit, 90)
    ]
    if not candidates:
        return _first_sentence(text, limit)
    cues = {
        "methodology": ("we ", "method", "model", "algorithm", "attention", "network", "use "),
        "experiments": ("experiment", "evaluate", "dataset", "baseline", "metric", "result"),
        "findings": ("we find", "we show", "outperform", "improve", "result", "achieve"),
        "limitations": ("limit", "however", "future", "cannot", "lack", "challenge"),
        "abstract": ("we ", "paper", "propose", "present", "survey", "show"),
    }.get(section, ())

    def score(sentence: str) -> float:
        low = sentence.lower()
        value = min(len(sentence), 260) / 260
        value += sum(0.35 for cue in cues if cue in low)
        value -= 0.8 if "@" in sentence or "arxiv:" in low else 0
        value -= 0.5 if sentence.count("/") >= 3 else 0
        value -= 0.4 if sentence[0:1].islower() else 0
        value -= 0.7 if sentence[-1:] not in ".!?。！？" else 0
        return value

    return _clip_words(max(candidates, key=score), limit)


def _canonical_citation(citation: str, document_id: Any) -> str:
    value = str(citation or "").strip()
    if value.startswith("doc:"):
        match = re.fullmatch(r"doc:(\d+)#page=([1-9]\d*)&chunk=([1-9]\d*)", value)
        return value if match and str(int(match.group(1))) == str(document_id) else ""
    page = re.search(r"#page=(\d+)", value)
    chunk = re.search(r"(?:&|#)chunk=(\d+)", value)
    if page:
        return f"doc:{document_id}#page={page.group(1)}&chunk={chunk.group(1) if chunk else '1'}"
    return value


class GroundedPaperReport:
    """Build and validate a model-assisted paper report against local citations."""

    @staticmethod
    def build_evidence_bundle(intelligence: dict[str, Any], source_chunks=None) -> dict[str, Any]:
        document = dict(intelligence.get("document") or {})
        sections = dict(intelligence.get("sections") or {})
        selected: dict[str, list[dict[str, str]]] = {}
        allowed: dict[str, str] = {}
        for key in ("abstract", "introduction", "methodology", "experiments", "findings", "limitations", "conclusion"):
            rows = []
            for item in list(sections.get(key) or [])[:6]:
                citation = _canonical_citation(str(item.get("citation") or ""), document.get("id"))
                excerpt = _clean_text(item.get("excerpt"), 1100)
                if not citation or not excerpt:
                    continue
                rows.append({"citation": citation, "heading": _clean_text(item.get("heading"), 160), "excerpt": excerpt})
                allowed[citation] = excerpt
            selected[key] = rows
        claims = []
        for item in list(intelligence.get("claims") or [])[:36]:
            citation = _canonical_citation(str(item.get("citation") or ""), document.get("id"))
            claim = _clean_text(item.get("claim"), 800)
            if not citation or not claim:
                continue
            alignment = item.get("alignment") or {}
            citations = [citation]
            citations.extend(
                _canonical_citation(str(value), document.get("id"))
                for value in (item.get("evidence_citations") or alignment.get("citations") or [])
            )
            citations = list(dict.fromkeys(value for value in citations if value))[:4]
            for evidence in alignment.get("evidence") or []:
                evidence_citation = _canonical_citation(str(evidence.get("citation") or ""), document.get("id"))
                if evidence_citation:
                    allowed[evidence_citation] = _clean_text(evidence.get("snippet"), 1100)
            claims.append({
                "claim": claim,
                "section": str(item.get("section") or ""),
                "claim_type": str(item.get("claim_type") or "finding"),
                "citation": citation,
                "citations": citations,
                "conditions": [_clean_text(value, 500) for value in item.get("conditions") or [] if _clean_text(value, 500)],
            })
            for value in citations:
                allowed[value] = allowed.get(value) or claim
        # Use actual evidence-ready chunks rather than a shorter extracted claim
        # as the authoritative cited text. Geometry never enters the model input.
        for chunk in list(source_chunks or [])[:1000]:
            citation=_canonical_citation(chunk.get('citation',''),document.get('id'))
            if citation and chunk.get('content'):
                allowed[citation]=_clean_text(chunk['content'],1800)
        return {
            "schema": "clawos.paper-evidence-bundle.v1",
            "document": {
                "id": document.get("id"),
                "title": document.get("title") or document.get("filename") or "Untitled paper",
                "page_count": (document.get("metadata") or {}).get("page_count", 0),
                "extractor": document.get("extractor") or "",
            },
            "sections": selected,
            "claims": claims,
            "tables": list(intelligence.get("tables") or [])[:16],
            "figures": list(intelligence.get("figures") or [])[:16],
            "formulas": list(intelligence.get("formulas") or [])[:16],
            "footnotes": list(intelligence.get("footnotes") or [])[:24],
            "quality": dict(intelligence.get("quality") or {}),
            "allowed_citations": allowed,
        }

    @staticmethod
    def model_evidence(bundle):
        allowed=bundle.get('allowed_citations') or {}
        rows=[dict(citation=c,excerpt=text) for c,text in allowed.items() if len(text.strip())>=18]
        cues=('achiev','score','accuracy','bleu','f1','times','reduc','improv','结果','准确','显存')
        def score(row):
            text=row['excerpt'].lower();page=re.search(r'#page=(\d+)',row['citation'])
            return sum(cue in text for cue in cues)*2 + (3 if page and int(page[1])<=2 else 0)
        rows.sort(key=score,reverse=True)
        # Reserve room for a mechanism and a boundary as well as headline results.
        preferred=rows[:2]
        for cues in (('we propose','we introduce','architecture','rank decomposition','pre-train'),('limitation','however','future work','cannot','does not')):
            candidate=next((r for r in rows if r not in preferred and any(cue in r['excerpt'].lower() for cue in cues)),None)
            if candidate:preferred.append(candidate)
        ordered=preferred+[r for r in rows if r not in preferred]
        compact=dict(document={k:_clean_text(v,200) if isinstance(v,str) else v for k,v in bundle.get('document',{}).items()},evidence=[])
        for row in ordered:
            candidate=dict(row,excerpt=_clip_words(row['excerpt'],1800))
            trial=dict(compact,evidence=compact['evidence']+[candidate])
            if len(json.dumps(trial,ensure_ascii=False).encode('utf-8'))<=7000:
                compact['evidence'].append(candidate)
        compact['selection']=dict(algorithm='budgeted_source_excerpts_v1',available=len(allowed),included=len(compact['evidence']),full_paper_coverage=False)
        return compact

    @classmethod
    def prompt(cls,bundle: dict[str, Any], language: str = "zh-CN") -> list[dict[str, str]]:
        compact = cls.model_evidence(bundle)
        system = (
            "You are a rigorous research-paper analyst. Return one JSON object only. "
            "Every factual item must cite one or more citation strings that occur verbatim in the evidence bundle. "
            "Separate author-stated facts from your inference. Never invent datasets, metrics, baselines, limitations, or results. "
            "Retain dataset, sample, baseline, metric, parameter and other experimental conditions with every result. "
            "When one conclusion depends on evidence from multiple pages, cite every supporting page rather than only the result page. "
            "The excerpts are budget-selected, not the full paper. If evidence is missing, say so explicitly. "
            "Report the principal results with their metric and experimental setting when present. Write concise professional Chinese."
        )
        schema = {
            "summary": "one-sentence paper summary",
            "summary_citations": ["doc:..."],
            "research_problem": "problem and motivation",
            "research_problem_citations": ["doc:..."],
            "contributions": [{"text": "contribution", "citations": ["doc:..."], "status": "supported|inference|not_found"}],
            "methodology": [{"text": "mechanism or method", "citations": ["doc:..."], "status": "supported|inference|not_found"}],
            "experiments": [{"text": "setup, baseline, metric, or result", "citations": ["doc:..."], "status": "supported|inference|not_found"}],
            "findings": [{"text": "finding", "citations": ["doc:..."], "status": "supported|inference|not_found"}],
            "limitations": [{"text": "stated limitation or clearly marked inference", "citations": ["doc:..."], "status": "supported|inference|not_found"}],
            "open_questions": ["question for verification or reproduction"],
            "verdict": "balanced assessment of evidence strength and boundary",
        }
        user = (
            f"Language: {language}\nRequired JSON shape:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Evidence bundle:\n{json.dumps(compact, ensure_ascii=False)}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    @classmethod
    def parse_model_output(cls, raw: str, bundle: dict[str, Any]) -> dict[str, Any] | None:
        text = str(raw or "").strip()
        if not text:
            return None
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
        candidate = fenced.group(1).strip() if fenced else text
        if not candidate.startswith("{"):
            match = re.search(r"\{[\s\S]*\}", candidate)
            candidate = match.group(0) if match else ""
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if not all(isinstance(payload.get(key),str) and payload[key].strip() for key in ('summary','research_problem')):
            return None
        if not all(isinstance(payload.get(key),list) for key in REPORT_SECTION_KEYS):
            return None
        rows=[row for key in REPORT_SECTION_KEYS for row in payload[key]]
        if not rows or any(not isinstance(row,dict) or not isinstance(row.get('text'),str) or not row['text'].strip() for row in rows):
            return None
        selected=cls.model_evidence(bundle)
        bound=dict(bundle,allowed_citations={r['citation']:r['excerpt'] for r in selected['evidence']})
        report=cls.normalize(payload,bound,mode="model_assisted")
        report['evidence_selection']=selected['selection']
        return report

    @classmethod
    def fallback(cls, bundle: dict[str, Any]) -> dict[str, Any]:
        sections = bundle.get("sections") or {}
        claims = bundle.get("claims") or []

        def rows_from(section: str, *, limit: int = 4) -> list[dict[str, Any]]:
            rows = []
            for item in list(sections.get(section) or [])[:limit]:
                rows.append({"text": _best_sentence(item.get("excerpt"), section, 520), "citations": [item.get("citation")], "status": "supported"})
            return [item for item in rows if item["text"] and item["citations"][0]]

        abstract = list(sections.get("abstract") or [])
        introduction = list(sections.get("introduction") or [])
        summary_source = (abstract or introduction or list(sections.get("conclusion") or []))
        summary = _best_sentence(summary_source[0].get("excerpt"), "abstract", 520) if summary_source else "未能从当前解析结果中稳定定位摘要。"
        finding_rows = [
            {"text": item["claim"], "citations": item.get("citations") or [item["citation"]], "status": "supported",
             "conditions": item.get("conditions") or []}
            for item in claims
            if item.get("section") in {"findings", "conclusion", "experiments"}
        ][:6]
        limitation_rows = [
            {"text": item["claim"], "citations": [item["citation"]], "status": "supported"}
            for item in claims
            if item.get("claim_type") == "limitation"
        ][:5] or rows_from("limitations", limit=5)
        if not limitation_rows:
            limitation_rows = [{"text": "当前解析证据中未定位到明确的局限性段落，需要回到原文人工核查。", "citations": [], "status": "not_found"}]
        payload = {
            "summary": summary,
            "summary_citations": [summary_source[0]['citation']] if summary_source else [],
            "research_problem": _best_sentence((introduction or abstract or [{}])[0].get("excerpt"), "abstract", 620),
            "research_problem_citations": [(introduction or abstract)[0]['citation']] if introduction or abstract else [],
            "contributions": rows_from("abstract", limit=3) or finding_rows[:3],
            "methodology": rows_from("methodology", limit=6),
            "experiments": rows_from("experiments", limit=6),
            "findings": finding_rows or rows_from("findings", limit=6) or rows_from("conclusion", limit=4),
            "limitations": limitation_rows,
            "open_questions": [
                "核心结论是否有独立消融实验支持？",
                "数据集、评价指标与基线是否足以复现主要结果？",
                "作者明确声明的适用边界和失败条件是什么？",
            ],
            "verdict": "这是基于论文结构与原文片段生成的证据回退版本；未被引用支持的内容不应当作论文结论。",
        }
        return cls.normalize(payload, bundle, mode="evidence_fallback")

    @classmethod
    def normalize(cls, payload: dict[str, Any], bundle: dict[str, Any], *, mode: str) -> dict[str, Any]:
        allowed = dict(bundle.get("allowed_citations") or {})

        def valid_citations(value):
            values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
            return list(dict.fromkeys(str(c) for c in values if str(c) in allowed))[:4]

        def audit_statement(text,citations,*,inference=False):
            fragments=[allowed[c] for c in citations]
            audit=audit_numeric_support(text,fragments)
            boundary=None if inference else audit_claim_boundaries(text,fragments)
            audit['boundary_audit']=boundary
            audit['review_required']=audit['review_required'] or bool(boundary and boundary['review_required'])
            return audit

        def normalize_rows(value: Any) -> list[dict[str, Any]]:
            if not isinstance(value, list):
                value = [value] if value else []
            rows = []
            for raw in value[:10]:
                item = raw if isinstance(raw, dict) else {"text": raw}
                text = _clean_text(item.get("text") or item.get("claim"), 900)
                if not text:
                    continue
                citations = item.get("citations") or ([item.get("citation")] if item.get("citation") else [])
                citations = valid_citations(citations)
                requested = str(item.get("status") or "supported")
                status = requested if requested in {"supported", "inference", "not_found", "review_required"} else "supported"
                if status == "supported" and not citations:
                    status = "review_required"
                rows.append({"text": text, "citations": citations, "status": status})
                if item.get("conditions"):
                    values = item['conditions'] if isinstance(item['conditions'], list) else [item['conditions']]
                    rows[-1]["conditions"] = [_clean_text(value, 500) for value in values[:12] if _clean_text(value, 500)]
                audit=audit_statement(text+' '+' '.join(rows[-1].get('conditions',[])),citations,inference=status=='inference')
                audit['missing_citation']=not bool(citations) and requested=='supported'
                audit['review_required']=audit['review_required'] or audit['missing_citation']
                rows[-1]['evidence_audit']=audit
                if audit['review_required'] and status!='not_found':rows[-1]['status']='review_required'
            return rows

        normalized = {
            "schema": "clawos.grounded-paper-report.v1",
            "mode": mode,
            "title": bundle.get("document", {}).get("title") or "Untitled paper",
            "summary": _clean_text(payload.get("summary"), 700),
            "summary_citations": valid_citations(payload.get("summary_citations")),
            "research_problem": _clean_text(payload.get("research_problem"), 1000),
            "research_problem_citations": valid_citations(payload.get("research_problem_citations")),
            "contributions": normalize_rows(payload.get("contributions")),
            "methodology": normalize_rows(payload.get("methodology")),
            "experiments": normalize_rows(payload.get("experiments")),
            "findings": normalize_rows(payload.get("findings")),
            "limitations": normalize_rows(payload.get("limitations")),
            "open_questions": [_clean_text(item, 400) for item in (payload.get("open_questions") if isinstance(payload.get("open_questions"), list) else [payload.get("open_questions")] if payload.get("open_questions") else [])[:8] if _clean_text(item, 400)],
            "verdict": _clean_text(payload.get("verdict"), 900),
            "source_quality": bundle.get("quality") or {},
            "evidence_count": len(allowed),
        }
        if not normalized["summary"]:
            normalized["summary"] = "当前证据不足以形成可靠的一句话结论。"
        rows = [item for key in REPORT_SECTION_KEYS for item in normalized[key]]
        cited = list(dict.fromkeys(normalized['summary_citations'] + normalized['research_problem_citations']
                                 + [citation for item in rows for citation in item['citations']]))
        normalized['document_id'] = bundle.get('document', {}).get('id')
        normalized['source_digest'] = hashlib.sha256(json.dumps(allowed, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        normalized['source_index'] = [dict(citation=c, excerpt=allowed[c]) for c in cited]
        for key in ('summary','research_problem'):
            citations=normalized[key+'_citations']
            audit=audit_statement(normalized[key],citations)
            audit['missing_citation']=not bool(citations)
            audit['review_required']=audit['review_required'] or audit['missing_citation']
            normalized[key+'_audit']=audit
        normalized['verdict_audit']=audit_statement(normalized['verdict'],cited)
        normalized['citation_audit'] = dict(cited_items=sum(bool(r['citations']) for r in rows),
                                           total_items=len(rows), missing_sections=[k for k in REPORT_SECTION_KEYS if not normalized[k]],
                                           review_required_items=sum(r['status']=='review_required' for r in rows),
                                           numeric_literal_scope='cited_fragments_only',
                                           semantic_entailment_verified=False)
        return normalized

    @staticmethod
    def render_markdown(report: dict[str, Any]) -> str:
        labels = {
            "contributions": "主要贡献",
            "methodology": "方法与机制",
            "experiments": "实验设计与结果",
            "findings": "核心发现",
            "limitations": "局限与适用边界",
        }
        mode_label = "模型辅助、引用约束" if report.get("mode") == "model_assisted" else "结构化证据回退"
        lines = [
            f"# {report.get('title') or '论文精读报告'}",
            "",
            f"> 生成方式：{mode_label}。引用已校验属于当前论文；引用存在不代表结论已经过语义核验。",
            "",
            "## 一句话结论",
            "",
            ('**待核查**：' if report.get('summary_audit',{}).get('review_required') else '')+str(report.get("summary") or ""),
            "",
            "## 研究问题",
            "",
            ('**待核查**：' if report.get('research_problem_audit',{}).get('review_required') else '')+str(report.get("research_problem") or ""),
        ]
        if report.get('evidence_selection'):
            lines.insert(4,'> 本报告使用了有预算限制的原文片段；未覆盖部分需回到全文核查。')
        for key, label in labels.items():
            lines.extend(["", f"## {label}", ""])
            rows = list(report.get(key) or [])
            if not rows:
                lines.append("- 当前解析证据未能稳定定位该部分。")
                continue
            for item in rows:
                status = {"supported": "原文支持", "inference": "分析推断", "not_found": "待核查", "review_required":"待核查"}.get(item.get("status"), "待核查")
                citations = " ".join(f"[{citation}]" for citation in item.get("citations") or [])
                lines.append(f"- **{status}**：{item.get('text', '')}{(' ' + citations) if citations else ''}")
                if item.get('conditions'):
                    lines.append("  - 实验条件：" + "；".join(item['conditions']))
                audit=item.get('evidence_audit') or {}
                if audit.get('unsupported_quantities'):
                    lines.append('  - 核查提示：所引片段未覆盖这些数字或单位：'+'、'.join(audit['unsupported_quantities'][:12])+'。')
                elif audit.get('missing_citation'):
                    lines.append('  - 核查提示：缺少可核对的原文引用。')
        lines.extend(["", "## 仍需核查的问题", ""])
        lines.extend(f"- {item}" for item in report.get("open_questions") or ["无"])
        lines.extend(["", "## 综合判断", "", ('**待核查**：' if report.get('verdict_audit',{}).get('review_required') else '')+str(report.get("verdict") or ""), ""])
        lines.extend(["## 引用核查与原文索引", "",
                      f"证据快照 SHA-256：`{report.get('source_digest', '')}`", "",
                      "模型概述和研究问题也需回原文核查；缺少证据的部分不得作为已验证结论。", ""])
        for item in report.get('source_index') or []:
            citation = item['citation']
            page = re.search(r'#page=(\d+)', citation)
            if page and report.get('document_id'):
                lines.append(f"- [{citation}](/academy/paper?document={report['document_id']}&page={page.group(1)}&reader=window)")
            else:
                lines.append(f"- {citation}")
            lines.append("  > " + item['excerpt'])
        lines.append("")
        return "\n".join(lines)
