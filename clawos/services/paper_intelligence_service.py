from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import socket
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .search_evidence import FileRateLimiter, JsonFileCache


SECTION_ALIASES = {
    "abstract": ("abstract", "摘要"),
    "introduction": ("introduction", "background", "引言", "背景"),
    "methodology": ("method", "methodology", "approach", "materials and methods", "方法", "模型", "算法"),
    "experiments": ("experiment", "evaluation", "dataset", "setup", "实验", "评测", "数据集"),
    "findings": ("result", "finding", "discussion", "结果", "发现", "讨论"),
    "limitations": ("limitation", "threat", "future work", "局限", "限制", "不足", "未来工作"),
    "conclusion": ("conclusion", "concluding", "结论", "总结"),
    "references": ("references", "bibliography", "参考文献"),
}

CLAIM_CUES = (
    "we find", "we show", "we demonstrate", "results indicate", "outperform", "improve",
    "significant", "achieve", "suggest", "表明", "发现", "结果", "提升", "优于", "达到", "显著",
)
LIMITATION_CUES = ("limit", "threat", "future work", "however", "局限", "限制", "不足", "未来")
NEGATIVE_CUES = ("not", "no ", "without", "failed", "decrease", "lower", "worse", "无显著", "未", "不", "下降", "更差")
POSITIVE_CUES = ("increase", "improve", "higher", "better", "outperform", "significant", "提升", "增加", "更高", "优于", "显著")


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", str(text or ""))
        if token.lower() not in {"the", "and", "for", "with", "that", "this", "from", "using", "通过", "本文", "研究"}
    }


def _sentences(text: str, min_chars: int = 18) -> list[str]:
    rows = re.split(r"(?<=[.!?。！？；;])\s*|[\r\n]+", str(text or ""))
    return [re.sub(r"\s+", " ", row).strip() for row in rows if len(re.sub(r"\s+", " ", row).strip()) >= min_chars]


def _normalize_doi(value: str) -> str:
    text = urllib.parse.unquote(str(value or "")).strip().lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    match = re.search(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", text, re.I)
    return match.group(0).rstrip(".,;)") if match else ""


def _year(value: Any) -> int:
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else 0


class PaperIntelligenceService:
    """Structure-aware scholarly analysis grounded in stored document chunks."""

    def __init__(self, store: Any):
        self.store = store

    def analyze_document(self, document_id: int) -> dict[str, Any]:
        document = self.store.get_document(document_id)
        if not document:
            raise ValueError("Document not found")
        chunks = self.store.get_document_chunks(document_id, 10000)
        metadata = document.get("metadata") or {}
        structure = dict(metadata.get("structure") or {})
        semantic_graph = dict(metadata.get("semantic_graph") or {})
        section_rows = self._section_rows(chunks, structure)
        categorized = {name: [] for name in SECTION_ALIASES}
        for row in section_rows:
            categorized[row["section"]].append(row)
        tables = self._tables(chunks, structure)
        formulas = self._formulas(chunks, structure, int(document_id))
        references = self._references(chunks, structure)
        claims = self._claims(chunks, section_rows)
        aligned = self.align_claims([item["claim"] for item in claims], [int(document_id)])
        evidence_by_claim = {item["claim"]: item for item in aligned["alignments"]}
        for item in claims:
            item["alignment"] = evidence_by_claim.get(item["claim"], {})
        sections = {
            name: [
                {"citation": item["citation"], "heading": item.get("heading", ""), "excerpt": item["excerpt"][:1800]}
                for item in rows[:12]
            ]
            for name, rows in categorized.items()
        }
        checks = {
            "has_methodology": bool(sections["methodology"]),
            "has_experiments": bool(sections["experiments"]),
            "has_findings": bool(sections["findings"] or sections["conclusion"]),
            "has_limitations": bool(sections["limitations"]),
            "has_references": bool(references),
            "claims_grounded": aligned["metrics"]["supported_rate"] >= 0.9 if claims else False,
            "page_citations": all(
                "#page=" in str(chunk.get("citation") or "") and "&chunk=" in str(chunk.get("citation") or "")
                for chunk in chunks
            ) if chunks else False,
            # Legacy documents remain analyzable. Advanced semantic fidelity is
            # reported separately instead of lowering their established content score.
            "semantic_graph": not semantic_graph or semantic_graph.get("schema") == "clawos.document-semantic-graph.v1",
            "table_header_relations": not semantic_graph or not tables or all(
                "header_rows" in item and ("cells" in item or item.get("source") == "text-caption") for item in tables
            ),
            "formula_fidelity": not formulas or all(item.get("representation") for item in formulas),
            "review_semantics": document.get("filename", "").lower().endswith(".pdf") or (
                "comments" in structure and "revisions" in structure
            ),
        }
        score = round(sum(1 for value in checks.values() if value) / len(checks) * 100, 2)
        return {
            "schema": "clawos.paper-intelligence.v1",
            "document": document,
            "sections": sections,
            "claims": claims,
            "tables": tables,
            "formulas": formulas,
            "figures": list(structure.get("figures") or [])[:200],
            "footnotes": list(structure.get("footnotes") or [])[:300],
            "comments": list(structure.get("comments") or [])[:300],
            "revisions": list(structure.get("revisions") or [])[:300],
            "semantic_relations": list(structure.get("relations") or [])[:1000],
            "references": references,
            "quality": {
                "score": score,
                "checks": checks,
                "semantic_fidelity": {
                    "available": semantic_graph.get("schema") == "clawos.document-semantic-graph.v1",
                    "quality_gate": (semantic_graph.get("quality") or {}).get("quality_gate", "legacy_text_only"),
                },
                "claim_count": len(claims),
                "table_count": len(tables),
                "formula_count": len(formulas),
                "reference_count": len(references),
            },
        }

    def semantic_graph(self, document_id: int, compact: bool = False) -> dict[str, Any]:
        """Return the persisted graph, or rebuild it from the governed source file."""
        document = self.store.get_document(int(document_id))
        if not document:
            raise ValueError("Document not found")
        graph = dict((document.get("metadata") or {}).get("semantic_graph") or {})
        if not graph:
            source = Path(str(document.get("file_path") or "")).expanduser()
            if not source.is_file() or source.suffix.lower() not in {".pdf", ".docx"}:
                raise ValueError("Document has no PDF/DOCX source for semantic parsing")
            from .document_semantic_graph_service import DocumentSemanticGraphService
            graph = DocumentSemanticGraphService().parse(source)
        from .document_evidence_policy import safe_graph
        graph = safe_graph(graph)
        if not compact:
            return graph
        return {
            key: graph.get(key)
            for key in ("schema", "format", "source", "pages", "sections", "tables", "figures", "formulas",
                        "footnotes", "references", "comments", "revisions", "relations", "quality")
        }

    def align_claims(self, claims: list[Any], document_ids: list[int] | None = None, threshold: float = 0.34) -> dict[str, Any]:
        documents = [self.store.get_document(item) for item in (document_ids or [])]
        documents = [item for item in documents if item]
        if not documents:
            documents = self.store.list_documents("research") or self.store.list_documents("research_pdf") or self.store.list_documents()
        candidates = []
        for document in documents[:100]:
            for chunk in self.store.get_document_chunks(int(document["id"]), 10000):
                candidates.append({
                    **chunk,
                    "document_id": int(document["id"]),
                    "title": document.get("title", ""),
                    "citation": chunk.get("citation") or f"doc:{document['id']}#chunk={chunk.get('chunk_index')}",
                })
        alignments = []
        for raw in claims or []:
            claim = str(raw.get("claim") if isinstance(raw, dict) else raw).strip()
            required_conditions = list(raw.get("conditions") or []) if isinstance(raw, dict) else []
            ranked = []
            for chunk in candidates:
                score, signals = self._support_score(claim, str(chunk.get("content") or ""))
                condition_hits = [
                    condition for condition in required_conditions
                    if self._support_score(condition, str(chunk.get("content") or ""))[0] >= 0.30
                ]
                ranked.append({
                        "citation": chunk["citation"],
                        "document_id": chunk["document_id"],
                        "chunk_id": chunk.get("id"),
                        "title": chunk.get("title", ""),
                        "snippet": str(chunk.get("content") or "")[:520],
                        "support_score": score,
                        "signals": {**signals, "condition_hits": len(condition_hits),
                                    "condition_matches": condition_hits,
                                    "condition_total": len(required_conditions)},
                        "page": self._citation_page(chunk["citation"]),
                    })
            ranked.sort(key=lambda item: (-item["support_score"], item["document_id"], item["page"], item.get("chunk_id") or 0))
            best = ranked[0] if ranked else None
            score = float((best or {}).get("support_score") or 0)
            status = "supported" if score >= threshold else ("weak" if score >= threshold * 0.65 else "unsupported")
            evidence = []
            seen_pages = set()
            for item in ranked:
                if item["support_score"] < max(threshold, score * 0.72):
                    continue
                page_key = (item["document_id"], item["page"] or item["citation"])
                if page_key in seen_pages:
                    continue
                seen_pages.add(page_key)
                evidence.append(item)
                if len(evidence) >= 4:
                    break
            # Experimental conditions often live in methods pages rather than
            # the result sentence. Add the strongest page for each missing
            # condition instead of requiring it to resemble the claim itself.
            for condition in required_conditions:
                if any(condition in (item.get("signals", {}).get("condition_matches") or []) for item in evidence):
                    continue
                condition_ranked = sorted(
                    ranked,
                    key=lambda item: -self._support_score(condition, item.get("snippet", ""))[0],
                )
                for item in condition_ranked:
                    condition_score = self._support_score(condition, item.get("snippet", ""))[0]
                    page_key = (item["document_id"], item["page"] or item["citation"])
                    if condition_score >= 0.30 and page_key not in seen_pages:
                        evidence.append(item); seen_pages.add(page_key)
                        break
                if len(evidence) >= 4:
                    break
            condition_coverage = 1.0
            if required_conditions:
                covered = {
                    condition for item in evidence
                    for condition in (item.get("signals", {}).get("condition_matches") or [])
                }
                condition_coverage = len(covered) / len(required_conditions)
                if condition_coverage < 1.0 and status == "supported":
                    status = "condition_incomplete"
            alignments.append({
                "claim": claim, "status": status, "conditions": required_conditions,
                "condition_coverage": round(condition_coverage, 4), "evidence": evidence,
                "citations": [item["citation"] for item in evidence],
                **(best or {"support_score": 0.0, "signals": {}}),
            })
        supported = sum(1 for item in alignments if item["status"] == "supported")
        return {
            "alignments": alignments,
            "metrics": {
                "claim_count": len(alignments),
                "supported_count": supported,
                "weak_count": sum(1 for item in alignments if item["status"] == "weak"),
                "unsupported_count": sum(1 for item in alignments if item["status"] == "unsupported"),
                "condition_incomplete_count": sum(1 for item in alignments if item["status"] == "condition_incomplete"),
                "multi_page_evidence_count": sum(1 for item in alignments if len(item.get("evidence") or []) > 1),
                "supported_rate": round(supported / max(1, len(alignments)), 4),
                "threshold": threshold,
            },
            "gate": "pass" if alignments and supported / len(alignments) >= 0.9 else "revision_required",
        }

    def compare_documents(self, document_ids: list[int]) -> dict[str, Any]:
        analyses = [self.analyze_document(int(item)) for item in document_ids]
        claims = []
        for analysis in analyses:
            for item in analysis["claims"]:
                claims.append({
                    "document_id": int(analysis["document"]["id"]),
                    "title": analysis["document"].get("title", ""),
                    "claim": item["claim"],
                    "citation": item["citation"],
                    "polarity": self._polarity(item["claim"]),
                })
        contradictions = []
        agreements = []
        for index, left in enumerate(claims):
            for right in claims[index + 1:]:
                if left["document_id"] == right["document_id"]:
                    continue
                overlap = self._topic_overlap(left["claim"], right["claim"])
                if overlap < 0.22:
                    continue
                numeric_conflict = self._numeric_conflict(left["claim"], right["claim"])
                polarity_conflict = left["polarity"] * right["polarity"] < 0
                row = {"left": left, "right": right, "topic_overlap": overlap, "numeric_conflict": numeric_conflict}
                if polarity_conflict or numeric_conflict:
                    row["reason"] = "opposite_polarity" if polarity_conflict else "different_numeric_result"
                    row["severity"] = "high" if overlap >= 0.45 else "medium"
                    contradictions.append(row)
                elif left["polarity"] == right["polarity"] and left["polarity"] != 0:
                    agreements.append(row)
        section_coverage = {
            str(item["document"]["id"]): {
                name: bool(item["sections"].get(name))
                for name in ("methodology", "experiments", "findings", "limitations", "references")
            }
            for item in analyses
        }
        return {
            "schema": "clawos.cross-paper-comparison.v1",
            "documents": [{"id": item["document"]["id"], "title": item["document"].get("title", ""), "quality": item["quality"]} for item in analyses],
            "agreements": agreements[:100],
            "potential_contradictions": contradictions[:100],
            "section_coverage": section_coverage,
            "gate": "review_required" if contradictions else "pass",
            "note": "Contradictions are deterministic candidates and require scholarly review; they are not asserted as final scientific conclusions.",
        }

    def readiness(self, document_ids: list[int] | None = None) -> dict[str, Any]:
        ids = document_ids or [int(item["id"]) for item in self.store.list_documents("research")]
        analyses = [self.analyze_document(item) for item in ids[:50]]
        average = round(sum(item["quality"]["score"] for item in analyses) / max(1, len(analyses)), 2)
        checks = {
            "documents_analyzed": bool(analyses),
            "average_structure_score_90": average >= 90,
            "claim_gate_pass": bool(analyses) and all(item["quality"]["checks"]["claims_grounded"] for item in analyses),
            "references_extracted": bool(analyses) and all(item["quality"]["reference_count"] > 0 for item in analyses),
        }
        score = round(sum(1 for value in checks.values() if value) / len(checks) * 100, 2)
        return {"score": score, "average_document_score": average, "checks": checks, "documents": len(analyses), "ready": score >= 90}

    def _section_rows(self, chunks: list[dict[str, Any]], structure: dict[str, Any]) -> list[dict[str, Any]]:
        explicit = []
        for item in structure.get("sections", []) or []:
            heading = str(item.get("title") if isinstance(item, dict) else item).strip()
            if heading:
                explicit.append((int(item.get("page") or 0) if isinstance(item, dict) else 0, heading, self._section_name(heading)))
        rows = []
        current = "introduction"
        for chunk in chunks:
            text = str(chunk.get("content") or "")
            heading = next((line.strip() for line in text.splitlines()[:4] if 2 <= len(line.strip()) <= 120 and self._section_name(line.strip())), "")
            if heading:
                current = self._section_name(heading) or current
            elif explicit:
                citation_page = self._citation_page(chunk.get("citation", ""))
                choices = [item for item in explicit if item[0] <= citation_page and item[2]]
                if choices:
                    heading, current = choices[-1][1], choices[-1][2]
            rows.append({"section": current, "heading": heading, "citation": chunk.get("citation") or "", "excerpt": text, "chunk_id": chunk.get("id")})
        return rows

    @staticmethod
    def _section_name(heading: str) -> str:
        low = re.sub(r"^\s*\d+(?:\.\d+)*[.)]?\s*", "", str(heading or "").lower()).strip(" :：.-")
        for name, aliases in SECTION_ALIASES.items():
            if any(low == alias or low.startswith(alias + " ") or alias in low[:60] for alias in aliases):
                return name
        return ""

    def _claims(self, chunks: list[dict[str, Any]], section_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        section_by_id = {item.get("chunk_id"): item["section"] for item in section_rows}
        claims = []
        seen = set()
        context_candidates = []
        for chunk in chunks:
            section = section_by_id.get(chunk.get("id"), "")
            if section in {"methodology", "experiments"}:
                for sentence in _sentences(chunk.get("content", "")):
                    if self._condition_sentence(sentence) or re.search(r"(?i)dataset|sample|baseline|metric|parameter|epoch|batch|数据集|样本|基线|指标|参数", sentence):
                        context_candidates.append({"text": sentence, "citation": chunk.get("citation") or ""})
        for chunk in chunks:
            section = section_by_id.get(chunk.get("id"), "")
            for sentence in _sentences(chunk.get("content", "")):
                low = sentence.lower()
                if section not in {"findings", "conclusion", "limitations", "experiments"} and not any(cue in low for cue in CLAIM_CUES):
                    continue
                if sentence.lower() in seen:
                    continue
                seen.add(sentence.lower())
                topic = _tokens(sentence)
                ranked_context = sorted(
                    context_candidates,
                    key=lambda item: len(topic & _tokens(item["text"])) / max(1, len(topic)),
                    reverse=True,
                )
                conditions = [item for item in ranked_context if self._condition_sentence(item["text"]) or len(topic & _tokens(item["text"])) >= 2][:4]
                claims.append({
                    "claim": sentence[:1200],
                    "section": section,
                    "citation": chunk.get("citation") or "",
                    "evidence_citations": list(dict.fromkeys([chunk.get("citation") or ""] + [item["citation"] for item in conditions if item["citation"]])),
                    "conditions": [item["text"] for item in conditions],
                    "claim_type": "limitation" if any(cue in low for cue in LIMITATION_CUES) else "finding",
                })
        return claims[:80]

    def _tables(self, chunks: list[dict[str, Any]], structure: dict[str, Any]) -> list[dict[str, Any]]:
        tables = [dict(item) for item in (structure.get("tables") or []) if isinstance(item, dict)]
        for chunk in chunks:
            text = str(chunk.get("content") or "")
            for match in re.finditer(r"(?im)^\s*(table|表)\s*([\dIVX一二三四五六七八九十]+)[.:：]?\s*(.{0,180})$", text):
                tables.append({"label": f"{match.group(1)} {match.group(2)}", "caption": match.group(3).strip(), "citation": chunk.get("citation") or "", "source": "text-caption"})
        return tables[:200]

    def _formulas(self, chunks: list[dict[str, Any]], structure: dict[str, Any] | None = None, document_id: int = 0) -> list[dict[str, Any]]:
        rows = [dict(item) for item in ((structure or {}).get("formulas") or []) if isinstance(item, dict)]
        pattern = re.compile(r"(?m)^\s*((?:\$\$|\\\[).+?(?:\$\$|\\\])|(?:[A-Za-z][A-Za-z0-9_]*(?:\([^)]*\))?\s*=\s*[^\n]{3,160})(?:\s*\(\d+\))?)\s*$")
        for chunk in chunks:
            for match in pattern.finditer(str(chunk.get("content") or "")):
                formula = re.sub(r"\s+", " ", match.group(1)).strip()
                if formula and len(formula) <= 240:
                    rows.append({"formula": formula, "formula_text": formula, "citation": chunk.get("citation") or "",
                                 "representation": "plain_text_pattern"})
        for item in rows:
            if "formula" not in item:
                item["formula"] = item.get("formula_text") or item.get("text") or ""
            page = int(item.get("page") or 0)
            if not item.get("citation"):
                item["citation"] = f"doc:{document_id}#page={page}&chunk=1" if document_id and page else ""
            item.setdefault("representation", "positioned_text")
        unique = {(item.get("formula", ""), item.get("citation", ""), item.get("locator", "")): item for item in rows if item.get("formula")}
        return list(unique.values())[:200]

    @staticmethod
    def _condition_sentence(value: str) -> bool:
        return bool(re.search(
            r"(?i)(?:\b(?:if|when|under|using|given|provided|unless|dataset|sample size|baseline|metric)\b|"
            r"(?:当|若|如果|仅在|基于|使用|数据集|样本量|基线|指标|条件下))",
            str(value or ""),
        ))

    def _references(self, chunks: list[dict[str, Any]], structure: dict[str, Any]) -> list[dict[str, Any]]:
        raw_refs = []
        for item in structure.get("references") or []:
            value = str(item.get("text") or item.get("raw") or "") if isinstance(item, dict) else str(item)
            if value.strip():
                raw_refs.append(value)
        in_references = False
        for chunk in chunks:
            text = str(chunk.get("content") or "")
            if re.search(r"(?im)^\s*(references|bibliography|参考文献)\s*$", text):
                in_references = True
            if in_references:
                raw_refs.extend(line.strip() for line in text.splitlines() if len(line.strip()) >= 18)
        rows = []
        seen = set()
        for raw in raw_refs:
            clean = re.sub(r"^\s*\[?\d+\]?[.)]?\s*", "", re.sub(r"\s+", " ", raw)).strip()
            if not clean or clean.lower() in seen or self._section_name(clean) == "references":
                continue
            seen.add(clean.lower())
            arxiv = re.search(r"arxiv[:\s]+(\d{4}\.\d{4,5}(?:v\d+)?)", clean, re.I)
            rows.append({"raw": clean[:1400], "doi": _normalize_doi(clean), "arxiv_id": arxiv.group(1) if arxiv else "", "year": _year(clean)})
        return rows[:500]

    @staticmethod
    def _support_score(claim: str, evidence: str) -> tuple[float, dict[str, Any]]:
        claim_tokens = _tokens(claim)
        evidence_tokens = _tokens(evidence)
        lexical = len(claim_tokens & evidence_tokens) / max(1, len(claim_tokens))
        claim_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", claim))
        evidence_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", evidence))
        numeric = len(claim_numbers & evidence_numbers) / max(1, len(claim_numbers)) if claim_numbers else 0.5
        polarity_match = 1.0 if PaperIntelligenceService._polarity(claim) == PaperIntelligenceService._polarity(evidence) else 0.0
        phrase = 1.0 if len(claim) >= 24 and claim.lower() in evidence.lower() else 0.0
        score = min(1.0, lexical * 0.58 + numeric * 0.20 + polarity_match * 0.12 + phrase * 0.10)
        return round(score, 4), {"lexical": round(lexical, 4), "numeric": round(numeric, 4), "polarity_match": polarity_match, "exact_phrase": phrase}

    @staticmethod
    def _polarity(text: str) -> int:
        low = str(text or "").lower()
        positive = sum(1 for cue in POSITIVE_CUES if cue in low)
        negative = sum(1 for cue in NEGATIVE_CUES if cue in low)
        return 1 if positive > negative else (-1 if negative > positive else 0)

    @staticmethod
    def _topic_overlap(left: str, right: str) -> float:
        a, b = _tokens(left), _tokens(right)
        return round(len(a & b) / max(1, min(len(a), len(b))), 4)

    @staticmethod
    def _numeric_conflict(left: str, right: str) -> bool:
        a = {float(value) for value in re.findall(r"\b\d+(?:\.\d+)?\b", left)}
        b = {float(value) for value in re.findall(r"\b\d+(?:\.\d+)?\b", right)}
        if not a or not b or a & b:
            return False
        return min(abs(x - y) / max(abs(x), abs(y), 1.0) for x in a for y in b) >= 0.15

    @staticmethod
    def _citation_page(citation: str) -> int:
        match = re.search(r"#page=(\d+)", str(citation or ""))
        return int(match.group(1)) if match else 0


class ScholarlySearchService:
    """Multi-provider scholarly metadata search and verified open-access PDF download."""

    PROVIDERS = ("openalex", "crossref", "semantic_scholar")

    def __init__(
        self,
        cache_dir: Path,
        *,
        http_json: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
        http_binary: Callable[[str, dict[str, str], int], tuple[bytes, str, str]] | None = None,
        resolver: Callable[[str], list[str]] | None = None,
    ):
        self.cache = JsonFileCache(Path(cache_dir) / "scholarly_search_cache.json", ttl_seconds=21600)
        self.rate = FileRateLimiter(Path(cache_dir) / "scholarly_search_rate.json", max_per_minute=20)
        self.http_json = http_json or self._http_json
        self.http_binary = http_binary or self._http_binary
        self.resolver = resolver or self._resolve_host

    def search(self, query: str, limit: int = 10, providers: list[str] | None = None, year_from: int = 0, year_to: int = 0, open_access_only: bool = False) -> dict[str, Any]:
        query = str(query or "").strip()
        if len(query) < 3:
            raise ValueError("query must contain at least 3 characters")
        limit = max(1, min(int(limit or 10), 50))
        providers = [item for item in (providers or self.PROVIDERS) if item in self.PROVIDERS]
        if not providers:
            raise ValueError("at least one supported scholarly provider is required")
        if year_from and year_to and int(year_from) > int(year_to):
            raise ValueError("year_from cannot be greater than year_to")
        cache_key = hashlib.sha256(json.dumps([query, limit, providers, year_from, year_to, open_access_only], sort_keys=True).encode()).hexdigest()
        cached = self.cache.get(cache_key)
        if cached:
            return {**cached, "cache_hit": True}
        rate = self.rate.check("scholarly_search")
        if not rate["allowed"]:
            return {"query": query, "results": [], "error": "rate_limited", "rate_limit": rate}
        rows, attempts = [], []
        for provider in providers:
            started = time.perf_counter()
            try:
                found = getattr(self, f"_search_{provider}")(query, limit, year_from, year_to, open_access_only)
                rows.extend(found)
                attempts.append({"provider": provider, "ok": True, "count": len(found), "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
            except Exception as exc:
                attempts.append({"provider": provider, "ok": False, "error": type(exc).__name__, "detail": str(exc)[:200], "latency_ms": round((time.perf_counter() - started) * 1000, 2)})
        merged = self._deduplicate_and_rank(query, rows, limit, year_from, year_to, open_access_only)
        payload = {
            "query": query,
            "results": merged,
            "count": len(merged),
            "attempts": attempts,
            "quality": {
                "multi_source_count": sum(1 for item in merged if len(item.get("sources", [])) >= 2),
                "doi_count": sum(1 for item in merged if item.get("doi")),
                "open_access_count": sum(1 for item in merged if item.get("open_access_pdf_url")),
                "avg_relevance": round(sum(item.get("relevance_score", 0) for item in merged) / max(1, len(merged)), 4),
            },
            "rate_limit": rate,
            "cache_hit": False,
        }
        if merged:
            self.cache.set(cache_key, payload)
        return payload

    def resolve_open_access(self, doi: str, email: str = "") -> dict[str, Any]:
        doi = _normalize_doi(doi)
        email = str(email or os.environ.get("SCHOLARLY_CONTACT_EMAIL") or "").strip()
        if not doi:
            raise ValueError("valid DOI required")
        if not email or "@" not in email:
            raise ValueError("Unpaywall requires SCHOLARLY_CONTACT_EMAIL or an email argument")
        url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='')}?email={urllib.parse.quote(email)}"
        payload = self.http_json(url, self._headers())
        best = payload.get("best_oa_location") or {}
        return {
            "doi": doi,
            "is_open_access": bool(payload.get("is_oa")),
            "oa_status": payload.get("oa_status", ""),
            "pdf_url": best.get("url_for_pdf") or "",
            "landing_url": best.get("url") or "",
            "license": best.get("license") or "",
            "host_type": best.get("host_type") or "",
            "version": best.get("version") or "",
            "source": "unpaywall",
        }

    def download_open_access(self, paper: dict[str, Any], output_dir: Path, max_bytes: int = 50_000_000) -> dict[str, Any]:
        max_bytes = int(max_bytes or 0)
        if max_bytes < 1024 or max_bytes > 200_000_000:
            raise ValueError("max_bytes must be between 1024 and 200000000")
        url = str(paper.get("open_access_pdf_url") or paper.get("pdf_url") or "").strip()
        if not url:
            raise ValueError("paper has no verified open-access PDF URL")
        verified_by = str(paper.get("open_access_verified_by") or paper.get("source") or "").strip().lower()
        if verified_by not in {"openalex", "semantic_scholar", "unpaywall", "crossref_open_license"}:
            raise ValueError("open-access provenance is required before download")
        self._validate_public_url(url)
        data, content_type, final_url = self.http_binary(url, self._headers(accept="application/pdf"), max_bytes)
        self._validate_public_url(final_url)
        if len(data) > max_bytes:
            raise ValueError("PDF exceeds maximum allowed size")
        if not data.startswith(b"%PDF-"):
            raise ValueError("downloaded content is not a PDF")
        if "pdf" not in str(content_type).lower() and content_type:
            raise ValueError(f"unexpected content type: {content_type}")
        output_dir = Path(output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(paper.get("doi") or paper.get("title") or "paper")).strip("._")[:100] or "paper"
        target = output_dir / f"{stem}.pdf"
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix=f".{stem}.", suffix=".part", delete=False) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        temporary.replace(target)
        return {
            "downloaded": True,
            "path": str(target),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_url": url,
            "final_url": final_url,
            "content_type": content_type,
            "doi": _normalize_doi(str(paper.get("doi") or "")),
            "license": paper.get("license") or "",
            "open_access": True,
        }

    def _search_crossref(self, query: str, limit: int, year_from: int, year_to: int, open_access_only: bool) -> list[dict[str, Any]]:
        params = {"query.bibliographic": query, "rows": str(limit), "select": "DOI,title,author,published,container-title,abstract,is-referenced-by-count,URL,link,license,type"}
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}-01-01")
        if year_to:
            filters.append(f"until-pub-date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        url = "https://api.crossref.org/works?" + urllib.parse.urlencode(params)
        items = ((self.http_json(url, self._headers()).get("message") or {}).get("items") or [])
        rows = []
        for item in items:
            links = item.get("link") or []
            pdf = next((link.get("URL", "") for link in links if "pdf" in str(link.get("content-type", "")).lower()), "")
            licenses = item.get("license") or []
            license_url = licenses[0].get("URL") if licenses else ""
            open_license = bool(re.search(r"creativecommons\.org|publicdomain|open-access", str(license_url), re.I))
            rows.append({
                "title": ((item.get("title") or [""])[0]), "doi": _normalize_doi(item.get("DOI", "")),
                "authors": [" ".join([author.get("given", ""), author.get("family", "")]).strip() for author in item.get("author", [])],
                "year": _year(item.get("published")), "venue": ((item.get("container-title") or [""])[0]),
                "abstract": re.sub(r"<[^>]+>", " ", str(item.get("abstract") or "")),
                "citation_count": int(item.get("is-referenced-by-count") or 0), "url": item.get("URL") or "",
                "open_access_pdf_url": pdf if open_license else "", "license": license_url, "provider": "crossref",
                "open_access_verified_by": "crossref_open_license" if pdf and open_license else "",
            })
        return rows

    def _search_openalex(self, query: str, limit: int, year_from: int, year_to: int, open_access_only: bool) -> list[dict[str, Any]]:
        params = {"search": query, "per-page": str(limit), "select": "id,doi,title,publication_year,authorships,primary_location,best_oa_location,open_access,cited_by_count,type"}
        filters = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if open_access_only:
            filters.append("open_access.is_oa:true")
        if filters:
            params["filter"] = ",".join(filters)
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        items = self.http_json(url, self._headers()).get("results") or []
        rows = []
        for item in items:
            location = item.get("primary_location") or {}
            best_oa_location = item.get("best_oa_location") or {}
            source = location.get("source") or {}
            oa = item.get("open_access") or {}
            best_pdf = best_oa_location.get("pdf_url") or location.get("pdf_url") or ""
            rows.append({
                "title": item.get("title") or "", "doi": _normalize_doi(item.get("doi", "")),
                "authors": [((entry.get("author") or {}).get("display_name") or "") for entry in item.get("authorships", [])],
                "year": int(item.get("publication_year") or 0), "venue": source.get("display_name") or "",
                "abstract": "", "citation_count": int(item.get("cited_by_count") or 0), "url": item.get("id") or "",
                "open_access_pdf_url": best_pdf if oa.get("is_oa") else "", "license": "", "provider": "openalex",
                "open_access_verified_by": "openalex" if oa.get("is_oa") and best_pdf else "",
            })
        return rows

    def _search_semantic_scholar(self, query: str, limit: int, year_from: int, year_to: int, open_access_only: bool) -> list[dict[str, Any]]:
        fields = "paperId,title,abstract,year,authors,venue,citationCount,externalIds,url,openAccessPdf,publicationTypes"
        params = {"query": query, "limit": str(limit), "fields": fields}
        if year_from or year_to:
            params["year"] = f"{year_from or ''}-{year_to or ''}"
        url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urllib.parse.urlencode(params)
        items = self.http_json(url, self._headers(api_key=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""))).get("data") or []
        rows = []
        for item in items:
            pdf = (item.get("openAccessPdf") or {}).get("url") or ""
            if open_access_only and not pdf:
                continue
            rows.append({
                "title": item.get("title") or "", "doi": _normalize_doi((item.get("externalIds") or {}).get("DOI", "")),
                "authors": [author.get("name", "") for author in item.get("authors", [])], "year": int(item.get("year") or 0),
                "venue": item.get("venue") or "", "abstract": item.get("abstract") or "", "citation_count": int(item.get("citationCount") or 0),
                "url": item.get("url") or "", "open_access_pdf_url": pdf, "license": "", "provider": "semantic_scholar",
                "open_access_verified_by": "semantic_scholar" if pdf else "",
            })
        return rows

    def _deduplicate_and_rank(self, query: str, rows: list[dict[str, Any]], limit: int, year_from: int, year_to: int, open_access_only: bool) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for row in rows:
            title_key = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(row.get("title") or "").lower())
            key = f"doi:{row['doi']}" if row.get("doi") else f"title:{title_key[:180]}"
            if not title_key:
                continue
            existing = merged.get(key)
            if existing:
                existing["sources"] = sorted(set(existing.get("sources", [])) | {row["provider"]})
                for field in ("abstract", "open_access_pdf_url", "open_access_verified_by", "license", "url", "venue"):
                    if not existing.get(field) and row.get(field):
                        existing[field] = row[field]
                existing["citation_count"] = max(int(existing.get("citation_count") or 0), int(row.get("citation_count") or 0))
            else:
                merged[key] = {**row, "sources": [row["provider"]]}
        query_tokens = _tokens(query)
        current_year = datetime.now(timezone.utc).year
        ranked = []
        for item in merged.values():
            if open_access_only and not item.get("open_access_pdf_url"):
                continue
            year = int(item.get("year") or 0)
            if year_from and year and year < year_from:
                continue
            if year_to and year and year > year_to:
                continue
            text_tokens = _tokens(" ".join([str(item.get("title", "")), str(item.get("abstract", ""))]))
            relevance = len(query_tokens & text_tokens) / max(1, len(query_tokens))
            exact = 1.0 if query.lower() in str(item.get("title", "")).lower() else 0.0
            consensus = min(1.0, len(item.get("sources", [])) / 3)
            citation = min(1.0, math.log1p(int(item.get("citation_count") or 0)) / 8)
            freshness = max(0.0, 1.0 - max(0, current_year - year) / 15) if year else 0.2
            metadata = sum(bool(item.get(field)) for field in ("doi", "authors", "venue", "abstract")) / 4
            score = relevance * 0.46 + exact * 0.12 + consensus * 0.16 + citation * 0.10 + freshness * 0.08 + metadata * 0.08
            item["relevance_score"] = round(min(1.0, score), 4)
            item["rank_explanation"] = {"lexical": round(relevance, 4), "exact_title": exact, "provider_consensus": round(consensus, 4), "citation_prior": round(citation, 4), "freshness": round(freshness, 4), "metadata_completeness": round(metadata, 4)}
            ranked.append(item)
        ranked.sort(key=lambda item: (item["relevance_score"], len(item.get("sources", [])), int(item.get("citation_count") or 0)), reverse=True)
        return ranked[:limit]

    def _validate_public_url(self, url: str) -> None:
        parsed = urllib.parse.urlparse(str(url or ""))
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("only public HTTPS scholarly URLs are allowed")
        for value in self.resolver(parsed.hostname):
            ip = ipaddress.ip_address(value)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                raise ValueError("private or unsafe download host is not allowed")

    @staticmethod
    def _headers(accept: str = "application/json", api_key: str = "") -> dict[str, str]:
        email = os.environ.get("SCHOLARLY_CONTACT_EMAIL", "").strip()
        headers = {"Accept": accept, "User-Agent": f"ClawOS-Scholarly/1.0{f' (mailto:{email})' if email else ''}"}
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    @staticmethod
    def _http_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(5_000_000)
        return json.loads(raw.decode("utf-8"))

    def _http_binary(self, url: str, headers: dict[str, str], max_bytes: int) -> tuple[bytes, str, str]:
        service = self

        class PublicOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, response_headers, newurl):
                service._validate_public_url(newurl)
                return super().redirect_request(req, fp, code, msg, response_headers, newurl)

        request = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(PublicOnlyRedirectHandler())
        with opener.open(request, timeout=45) as response:
            data = response.read(max_bytes + 1)
            return data, response.headers.get("content-type", ""), response.geturl()

    @staticmethod
    def _resolve_host(host: str) -> list[str]:
        return sorted({item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
