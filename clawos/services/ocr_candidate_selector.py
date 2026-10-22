"""Conservative OCR candidate ranking for table cells.

The selector uses recognizer evidence, document-local recurrence and generic
format constraints. It never receives benchmark labels or a document-specific
replacement dictionary. Selection confidence is operational, not factual.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Any


def compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).strip("|[]‘’“”\"")


def _cjk_ngrams(value: str) -> list[str]:
    runs = re.findall(r"[\u3400-\u9fff]+", compact(value))
    return [run[index:index + 2] for run in runs for index in range(max(0, len(run) - 1))]


class OCRCandidateSelector:
    UNITS = {"倍", "秒", "分", "分钟", "小时", "天", "个", "项", "次", "人", "元", "年", "月", "日"}

    @classmethod
    def select(
        cls,
        original: str,
        candidates: list[dict[str, Any]],
        *,
        context_text: str = "",
        original_confidence: float = 0.0,
    ) -> dict[str, Any]:
        original = str(original or "").strip()
        rows = [{"text": original, "view": "column", "confidence": original_confidence}]
        rows.extend(dict(item) for item in candidates if compact(item.get("text", "")))
        rows.extend(cls._consensus_repairs(original, rows[1:]))
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(compact(row["text"]).casefold(), []).append(row)
        context_counts = Counter(_cjk_ngrams(context_text))
        scored = []
        for key, group in grouped.items():
            representative = max(group, key=lambda item: float(item.get("confidence") or 0.0))
            text = str(representative["text"]).strip()
            score, reasons = cls._score(
                text, original, context_counts,
                confidence=max(float(item.get("confidence") or 0.0) for item in group),
                view_count=len({str(item.get("view") or "") for item in group}),
            )
            scored.append({"text": text, "normalized": key, "score": round(score, 6),
                           "view_count": len(group), "reasons": reasons,
                           "similarity": round(SequenceMatcher(None, key, compact(original).casefold()).ratio(), 6),
                           "introduced_ascii_noise": cls._introduced_ascii_noise(text, original)})
        eligible = [item for item in scored if not item["introduced_ascii_noise"]] or scored
        ranked = sorted(eligible, key=lambda item: (item["score"], item["view_count"]), reverse=True)
        current = next(item for item in scored if item["normalized"] == compact(original).casefold())
        best = ranked[0]
        improvement = best["score"] - current["score"]
        strong = set(best["reasons"]) & {
            "bounded_percentage", "recognized_unit", "identifier_shape",
            "document_recurrence", "multi_view_consensus",
        }
        identifier_only = strong == {"identifier_shape"}
        identifier_safe = not identifier_only or cls._identifier_skeleton(best["text"]) == cls._identifier_skeleton(original)
        repeated_high_similarity = best["view_count"] >= 2 and best["similarity"] >= 0.92 and improvement >= 0.02
        locally_repeated = (
            "document_recurrence" in strong
            and (best["similarity"] >= 0.94 or (best["view_count"] >= 2 and best["similarity"] >= 0.9))
            and improvement >= 0.005 and original_confidence < 0.9
        )
        consensus_supported = (
            "multi_view_consensus" in strong and best["similarity"] >= 0.92
            and improvement >= 0.08
        )
        acronym_supported = (
            identifier_only and identifier_safe and best["similarity"] >= 0.9
            and improvement >= 0.22
        )
        auto_applied = (
            best["normalized"] != current["normalized"]
            and bool(strong)
            and identifier_safe
            and not best["introduced_ascii_noise"]
            and (
                improvement >= 0.28
                or repeated_high_similarity
                or locally_repeated
                or consensus_supported
                or acronym_supported
                or "bounded_percentage" in strong
            )
        )
        return {
            "selected_text": best["text"] if auto_applied else original,
            "auto_applied": auto_applied,
            "reason": "candidate_quality_margin" if auto_applied else "human_review_required",
            "score_margin": round(improvement, 6),
            "selected_reasons": best["reasons"],
            "ranked": ranked[:8],
            "truth_boundary": "Correlated OCR views and local-format evidence; not independently verified truth.",
        }

    @classmethod
    def _consensus_repairs(cls, original: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        repairs = []
        unit_votes: Counter[tuple[str, str]] = Counter()
        for item in candidates:
            for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([\u3400-\u9fff]{1,2})", compact(item.get("text", ""))):
                if unit in cls.UNITS:
                    unit_votes[(number, unit)] += 1
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*([\u3400-\u9fff]{1,2})", original):
            number, current = match.groups()
            choices = [(count, unit) for (found, unit), count in unit_votes.items() if found == number and unit != current]
            if not choices:
                continue
            count, unit = max(choices)
            if count < 2:
                continue
            repaired = original[:match.start(2)] + unit + original[match.end(2):]
            for index in range(count):
                repairs.append({"text": repaired, "view": f"unit_consensus_{index}", "confidence": 0.82})
        return repairs

    @classmethod
    def _score(
        cls, text: str, original: str, context_counts: Counter,
        *, confidence: float, view_count: int,
    ) -> tuple[float, list[str]]:
        value, base = compact(text), compact(original)
        similarity = SequenceMatcher(None, value.casefold(), base.casefold()).ratio()
        length_ratio = min(len(value), len(base)) / max(1, max(len(value), len(base)))
        score = similarity * 0.62 + length_ratio * 0.18 + max(0.0, min(confidence, 1.0)) * 0.12
        score += min(0.12, math.log2(max(1, view_count)) * 0.06)
        reasons = []

        # Three or more agreeing preprocessing/segmentation views are still
        # correlated evidence, but are useful for correcting a near-identical
        # baseline transcription. The final source-review gate remains intact.
        if view_count >= 3 and similarity >= 0.92 and cls._only_identifier_change(text, original):
            score += min(0.16, (view_count - 2) * 0.04)
            reasons.append("multi_view_consensus")

        novel_ngrams = set(_cjk_ngrams(value)) - set(_cjk_ngrams(original))
        context_hits = sum(context_counts[item] for item in novel_ngrams)
        if context_hits >= 1:
            score += min(0.4, context_hits * 0.12)
            reasons.append("document_recurrence")

        percentages = [float(item) for item in re.findall(r"(\d+(?:\.\d+)?)\s*%", value)]
        rate_context = bool(re.search(r"(?:率|比例|占比|准确|precision|recall|rate|percent)", value, re.I))
        if percentages and rate_context:
            if all(0 <= item <= 100 for item in percentages):
                score += 0.65
                reasons.append("bounded_percentage")
            else:
                score -= 1.0

        if any(re.search(rf"\d+(?:\.\d+)?{re.escape(unit)}", value) for unit in cls.UNITS):
            score += 0.22
            reasons.append("recognized_unit")

        identifier_text = unicodedata.normalize("NFKC", str(text or ""))
        identifiers = re.findall(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]{1,15}(?![A-Za-z0-9])", identifier_text)
        identifier_score = 0.0
        for token in identifiers:
            if token.isupper() and token.isalpha() and 2 <= len(token) <= 6:
                identifier_score += 0.24
            elif re.fullmatch(r"[A-Z][a-z]+[A-Z]{2,}", token):
                identifier_score += 0.28
            elif re.search(r"[A-Za-z]\d$", token) and not re.search(r"\d", base.replace(token, "")):
                identifier_score -= 0.3
            elif token.endswith("l") and len(token) == 2:
                identifier_score -= 0.2
        if identifier_score > 0:
            reasons.append("identifier_shape")
        score += identifier_score

        replacement = len(value) - int(round(similarity * len(value)))
        if replacement > max(3, len(base) // 4):
            score -= 0.35
        if cls._introduced_ascii_noise(value, base):
            score -= 0.45
        unusual = re.findall(r"[^A-Za-z0-9\u3400-\u9fff,，.。:：;；!?！？%+<>=≤≥()（）\[\]【】\-_/\s]", value)
        if unusual:
            score -= min(0.35, len(unusual) * 0.12)
        return score, reasons

    @staticmethod
    def _identifier_skeleton(value: str) -> str:
        return re.sub(r"[A-Za-z][A-Za-z0-9]{1,15}", "<id>", compact(value)).casefold()

    @classmethod
    def _only_identifier_change(cls, value: str, original: str) -> bool:
        return compact(value).casefold() != compact(original).casefold() and cls._identifier_skeleton(value) == cls._identifier_skeleton(original)

    @staticmethod
    def _introduced_ascii_noise(value: str, original: str) -> bool:
        current = re.findall(r"[A-Za-z]{2,}", value)
        baseline = re.findall(r"[A-Za-z]{2,}", original)
        for token in current:
            if not any(SequenceMatcher(None, token.casefold(), old.casefold()).ratio() >= 0.45 for old in baseline):
                return True
        return False
