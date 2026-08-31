from __future__ import annotations

import json
import re
from typing import Any


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
        return value
    page = re.search(r"#page=(\d+)", value)
    chunk = re.search(r"(?:&|#)chunk=(\d+)", value)
    if page:
        return f"doc:{document_id}#page={page.group(1)}&chunk={chunk.group(1) if chunk else '1'}"
    return value


class GroundedPaperReport:
    """Build and validate a model-assisted paper report against local citations."""

    @staticmethod
    def build_evidence_bundle(intelligence: dict[str, Any]) -> dict[str, Any]:
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
    def prompt(bundle: dict[str, Any], language: str = "zh-CN") -> list[dict[str, str]]:
        compact = {key: value for key, value in bundle.items() if key != "allowed_citations"}
        system = (
            "You are a rigorous research-paper analyst. Return one JSON object only. "
            "Every factual item must cite one or more citation strings that occur verbatim in the evidence bundle. "
            "Separate author-stated facts from your inference. Never invent datasets, metrics, baselines, limitations, or results. "
            "Retain dataset, sample, baseline, metric, parameter and other experimental conditions with every result. "
            "When one conclusion depends on evidence from multiple pages, cite every supporting page rather than only the result page. "
            "If evidence is missing, say so explicitly. Write concise professional Chinese."
        )
        schema = {
            "summary": "one-sentence paper summary",
            "research_problem": "problem and motivation",
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
        return cls.normalize(payload, bundle, mode="model_assisted")

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
            "research_problem": _best_sentence((introduction or abstract or [{}])[0].get("excerpt"), "abstract", 620),
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
                citations = [str(c) for c in citations if str(c) in allowed][:4]
                requested = str(item.get("status") or "supported")
                status = requested if requested in {"supported", "inference", "not_found"} else "supported"
                if status == "supported" and not citations:
                    status = "inference"
                rows.append({"text": text, "citations": citations, "status": status})
                if item.get("conditions"):
                    rows[-1]["conditions"] = [_clean_text(value, 500) for value in item.get("conditions") or [] if _clean_text(value, 500)]
            return rows

        normalized = {
            "schema": "clawos.grounded-paper-report.v1",
            "mode": mode,
            "title": bundle.get("document", {}).get("title") or "Untitled paper",
            "summary": _clean_text(payload.get("summary"), 700),
            "research_problem": _clean_text(payload.get("research_problem"), 1000),
            "contributions": normalize_rows(payload.get("contributions")),
            "methodology": normalize_rows(payload.get("methodology")),
            "experiments": normalize_rows(payload.get("experiments")),
            "findings": normalize_rows(payload.get("findings")),
            "limitations": normalize_rows(payload.get("limitations")),
            "open_questions": [_clean_text(item, 400) for item in list(payload.get("open_questions") or [])[:8] if _clean_text(item, 400)],
            "verdict": _clean_text(payload.get("verdict"), 900),
            "source_quality": bundle.get("quality") or {},
            "evidence_count": len(allowed),
        }
        if not normalized["summary"]:
            normalized["summary"] = "当前证据不足以形成可靠的一句话结论。"
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
            f"> 生成方式：{mode_label}。每条事实性结论仅保留当前证据包中的引用。",
            "",
            "## 一句话结论",
            "",
            str(report.get("summary") or ""),
            "",
            "## 研究问题",
            "",
            str(report.get("research_problem") or ""),
        ]
        for key, label in labels.items():
            lines.extend(["", f"## {label}", ""])
            rows = list(report.get(key) or [])
            if not rows:
                lines.append("- 当前解析证据未能稳定定位该部分。")
                continue
            for item in rows:
                status = {"supported": "原文支持", "inference": "分析推断", "not_found": "待核查"}.get(item.get("status"), "待核查")
                citations = " ".join(f"[{citation}]" for citation in item.get("citations") or [])
                lines.append(f"- **{status}**：{item.get('text', '')}{(' ' + citations) if citations else ''}")
        lines.extend(["", "## 仍需核查的问题", ""])
        lines.extend(f"- {item}" for item in report.get("open_questions") or ["无"])
        lines.extend(["", "## 综合判断", "", str(report.get("verdict") or ""), ""])
        return "\n".join(lines)
