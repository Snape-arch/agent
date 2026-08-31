from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _tokens(value: Any) -> set[str]:
    text = _normalized(value)
    stop = {
        "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "are",
        "was", "were", "this", "that", "with", "from", "by", "it", "as", "be",
        "的", "了", "是", "在", "和", "与", "或", "请", "一个", "这个", "如何",
    }
    result = {item for item in re.findall(r"[a-z0-9][a-z0-9_.%+/-]*", text) if item not in stop}
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(segment[index:index + 2] for index in range(max(0, len(segment) - 1)))
    return {item for item in result if item and item not in stop}


def wilson_interval(successes: int, total: int, z: float = 1.959964) -> dict[str, float | int]:
    if total <= 0:
        return {"successes": 0, "total": 0, "rate": 0.0, "lower": 0.0, "upper": 0.0}
    rate = successes / total
    denominator = 1 + z * z / total
    centre = rate + z * z / (2 * total)
    margin = z * math.sqrt((rate * (1 - rate) + z * z / (4 * total)) / total)
    return {
        "successes": int(successes), "total": int(total), "rate": round(rate, 6),
        "lower": round(max(0.0, (centre - margin) / denominator), 6),
        "upper": round(min(1.0, (centre + margin) / denominator), 6),
    }


class ClaimEvidenceAnswerValidator:
    """Auditable lexical verifier; never presented as an unrestricted NLI model."""

    REFUSAL_MARKERS = (
        "没有足够证据", "没有找到", "无法根据", "不能根据", "证据不足",
        "insufficient evidence", "cannot determine", "not enough evidence",
    )
    NEGATION_MARKERS = (" not ", " no ", "never", "cannot", "不", "未", "无", "不能")

    @classmethod
    def validate(
        cls,
        *,
        query: str,
        answer: str,
        evidence: list[dict[str, Any]],
        expected_answer: str = "",
        must_refuse: bool = False,
        claims: list[dict[str, Any] | str] | None = None,
    ) -> dict[str, Any]:
        answer = str(answer or "").strip()
        refusal = any(marker in answer.lower() for marker in cls.REFUSAL_MARKERS)
        evidence_map: dict[str, list[dict[str, Any]]] = {}
        for item in evidence or []:
            row = dict(item or {})
            for key in (row.get("id"), row.get("citation"), row.get("source_ref")):
                if key:
                    bucket = evidence_map.setdefault(str(key).strip(), [])
                    if row not in bucket:
                        bucket.append(row)

        claim_rows = cls._claims(answer, claims)
        validations = [cls._validate_claim(item, evidence_map) for item in claim_rows]
        supported = sum(bool(item["supported"]) for item in validations)
        cited = sum(bool(item["citations"]) for item in validations)
        resolved_citations = sum(len(item["resolved_citations"]) for item in validations)
        citation_count = sum(len(item["citations"]) for item in validations)
        condition_ok = sum(not item["condition_omission"] for item in validations)
        expected_similarity = cls._similarity(answer, expected_answer) if expected_answer else None

        if must_refuse:
            valid = refusal and not claim_rows
            decision = "correct_refusal" if valid else "refusal_required"
        else:
            valid = bool(claim_rows) and not refusal and all(
                item["supported"] and item["citations"] and not item["condition_omission"]
                for item in validations
            )
            if valid and expected_similarity is not None and expected_similarity < 0.55:
                valid = False
            decision = "supported" if valid else "unsupported_or_misattributed"

        issue_counts = {
            "unsupported_expansion": sum(item["unsupported_expansion"] for item in validations),
            "citation_mismatch": sum(item["citation_mismatch"] for item in validations),
            "missing_citation": sum(not bool(item["citations"]) for item in validations),
            "condition_omission": sum(item["condition_omission"] for item in validations),
            "wrong_refusal": int(not must_refuse and refusal),
            "missing_refusal": int(must_refuse and not refusal),
        }
        return {
            "schema": "clawos.claim-evidence-answer-validation.v1",
            "valid": bool(valid), "decision": decision, "must_refuse": bool(must_refuse),
            "refusal_detected": refusal, "claim_count": len(validations),
            "supported_claim_rate": round(supported / len(validations), 6) if validations else 0.0,
            "citation_resolution_rate": round(resolved_citations / citation_count, 6) if citation_count else 0.0,
            "citation_coverage": round(cited / len(validations), 6) if validations else 0.0,
            "condition_retention_rate": round(condition_ok / len(validations), 6) if validations else 1.0,
            "expected_answer_similarity": round(expected_similarity, 6) if expected_similarity is not None else None,
            "issues": issue_counts, "claims": validations,
            "truth_boundary": "Deterministic citation, numeric, polarity, condition and lexical-overlap verifier; not a semantic entailment model.",
        }

    @classmethod
    def _claims(cls, answer: str, claims: list[dict[str, Any] | str] | None) -> list[dict[str, Any]]:
        if claims is not None:
            rows = []
            for raw in claims:
                item = {"text": raw} if isinstance(raw, str) else dict(raw or {})
                text = str(item.get("text") or "").strip()
                if text:
                    item["text"] = text
                    rows.append(item)
            return rows
        if any(marker in answer.lower() for marker in cls.REFUSAL_MARKERS):
            return []
        parts = []
        for line in re.split(r"[\r\n]+", answer):
            line = line.strip(" -•*")
            if not line:
                continue
            # A citation at the end of a sentence belongs to that sentence. Do
            # not split it into a synthetic citation-only claim.
            if re.search(r"\[[^\[\]]+\]\s*$", line):
                parts.append(line)
            else:
                parts.extend(re.split(r"(?<=[.!?。！？])\s+", line))
        return [{"text": item.strip(" -•*")} for item in parts if len(item.strip(" -•*")) >= 8]

    @classmethod
    def _validate_claim(cls, claim: dict[str, Any], evidence_map: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        text = str(claim.get("text") or "").strip()
        citations = [str(item) for item in claim.get("citations") or re.findall(r"\[([^\[\]]+)\]", text)]
        clean = re.sub(r"\[[^\[\]]+\]", "", text).strip()
        resolved = []
        for citation in citations:
            for evidence in evidence_map.get(citation, []):
                if evidence not in resolved:
                    resolved.append(evidence)
        scores = [cls._support_score(clean, str(item.get("text") or item.get("excerpt") or "")) for item in resolved]
        best = max(scores) if scores else 0.0
        best_evidence = resolved[scores.index(best)] if scores else None
        condition_omission = bool(best_evidence) and cls._has_condition(
            str(best_evidence.get("text") or best_evidence.get("excerpt") or "")
        ) and not cls._has_condition(clean)
        supported = bool(resolved) and best >= 0.62 and not condition_omission
        return {
            "text": clean, "citations": citations,
            "resolved_citations": [str(item.get("citation") or item.get("id") or "") for item in resolved],
            "support_score": round(best, 6), "supported": supported,
            "unsupported_expansion": int(not supported),
            "citation_mismatch": int(bool(citations) and not supported),
            "condition_omission": int(condition_omission),
        }

    @classmethod
    def _support_score(cls, claim: str, evidence: str) -> float:
        claim_tokens, evidence_tokens = _tokens(claim), _tokens(evidence)
        if not claim_tokens or not evidence_tokens:
            return 0.0
        overlap = len(claim_tokens & evidence_tokens) / len(claim_tokens)
        claim_numbers = set(re.findall(r"[-+]?\d+(?:\.\d+)?%?", claim))
        evidence_numbers = set(re.findall(r"[-+]?\d+(?:\.\d+)?%?", evidence))
        if not claim_numbers.issubset(evidence_numbers):
            return 0.0
        claim_negative = any(item in f" {claim.lower()} " for item in cls.NEGATION_MARKERS)
        evidence_negative = any(item in f" {evidence.lower()} " for item in cls.NEGATION_MARKERS)
        if claim_negative != evidence_negative:
            return 0.0
        return overlap

    @classmethod
    def _has_condition(cls, value: str) -> bool:
        padded = f" {_normalized(value)} "
        if any(marker in padded for marker in (" if ", " when ", " unless ", " only when ", " provided that ")):
            return True
        return bool(re.search(r"(?:仅当|只有在|如果|当且仅当|在以下条件|前提是|当.{1,48}(?:时|后|前))", padded))

    @classmethod
    def _similarity(cls, left: str, right: str) -> float:
        left_tokens, right_tokens = _tokens(left), _tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        precision = len(left_tokens & right_tokens) / len(left_tokens)
        recall = len(left_tokens & right_tokens) / len(right_tokens)
        return 2 * precision * recall / max(0.000001, precision + recall)


class AnswerQualityService:
    ORIGINS = {"consented_user", "benchmark_proxy", "codex_evaluator", "automated_test"}
    SPLITS = {"train", "dev", "test", "production"}

    def __init__(self, store):
        self.store = store
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.store._conn() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS answer_quality_feedback_v1 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    expected_answer TEXT NOT NULL DEFAULT '',
                    must_refuse INTEGER NOT NULL DEFAULT 0,
                    evidence TEXT NOT NULL DEFAULT '[]',
                    expected_relations TEXT NOT NULL DEFAULT '{}',
                    validation TEXT NOT NULL DEFAULT '{}',
                    origin TEXT NOT NULL,
                    consented INTEGER NOT NULL DEFAULT 0,
                    dataset_split TEXT NOT NULL DEFAULT 'production',
                    frozen INTEGER NOT NULL DEFAULT 0,
                    corpus_version TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT 'default',
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_answer_quality_origin_split_v1
                    ON answer_quality_feedback_v1(origin,dataset_split,frozen,id);
                CREATE TABLE IF NOT EXISTS answer_quality_runs_v1 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    corpus_version TEXT NOT NULL,
                    corpus_digest TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    confidence_intervals TEXT NOT NULL,
                    passed INTEGER NOT NULL DEFAULT 0,
                    truth_boundary TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def record(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        answer = str(payload.get("answer") or "").strip()
        if not query or not answer:
            raise ValueError("query and answer are required")
        origin = str(payload.get("origin") or "consented_user").strip().lower()
        if origin not in self.ORIGINS:
            raise ValueError(f"origin must be one of {sorted(self.ORIGINS)}")
        consented = bool(payload.get("consented"))
        if origin == "consented_user" and not consented:
            raise ValueError("consented_user feedback requires consented=true")
        if origin != "consented_user" and consented:
            raise ValueError("only consented_user rows may set consented=true")
        split = str(payload.get("dataset_split") or ("production" if origin == "consented_user" else "test"))
        if split not in self.SPLITS:
            raise ValueError(f"dataset_split must be one of {sorted(self.SPLITS)}")
        evidence = [dict(item or {}) for item in payload.get("evidence") or []]
        validation = ClaimEvidenceAnswerValidator.validate(
            query=query, answer=answer, evidence=evidence,
            expected_answer=str(payload.get("expected_answer") or ""),
            must_refuse=bool(payload.get("must_refuse")), claims=payload.get("claims"),
        )
        digest_payload = {
            "query": query, "answer": answer, "evidence": evidence, "origin": origin,
            "split": split, "version": str(payload.get("corpus_version") or ""),
        }
        content_hash = hashlib.sha256(_json(digest_payload).encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.store._conn() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO answer_quality_feedback_v1
                   (query,answer,expected_answer,must_refuse,evidence,expected_relations,validation,
                    origin,consented,dataset_split,frozen,corpus_version,task_id,owner_id,workspace_id,
                    metadata,content_hash,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (query, answer, str(payload.get("expected_answer") or ""), int(bool(payload.get("must_refuse"))),
                 _json(evidence), _json(payload.get("expected_relations") or {}), _json(validation),
                 origin, int(consented), split, int(bool(payload.get("frozen"))),
                 str(payload.get("corpus_version") or ""), str(payload.get("task_id") or ""),
                 str(payload.get("owner_id") or "default"), str(payload.get("workspace_id") or "default"),
                 _json(payload.get("metadata") or {}), content_hash, now),
            )
            row = connection.execute(
                "SELECT * FROM answer_quality_feedback_v1 WHERE content_hash=?", (content_hash,),
            ).fetchone()
        return self._row(dict(row))

    def list(self, *, origin: str = "", split: str = "", limit: int = 500) -> list[dict[str, Any]]:
        clauses, params = [], []
        if origin:
            clauses.append("origin=?")
            params.append(origin)
        if split:
            clauses.append("dataset_split=?")
            params.append(split)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self.store._conn() as connection:
            rows = connection.execute(
                f"SELECT * FROM answer_quality_feedback_v1{where} ORDER BY id DESC LIMIT ?", params,
            ).fetchall()
        return [self._row(dict(row)) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.store._conn() as connection:
            rows = connection.execute(
                "SELECT origin,dataset_split,consented,validation FROM answer_quality_feedback_v1"
            ).fetchall()
        origin_counts, split_counts = {}, {}
        valid = 0
        human = 0
        for row in rows:
            origin_counts[row["origin"]] = origin_counts.get(row["origin"], 0) + 1
            split_counts[row["dataset_split"]] = split_counts.get(row["dataset_split"], 0) + 1
            valid += int(bool(_loads(row["validation"], {}).get("valid")))
            human += int(row["origin"] == "consented_user" and bool(row["consented"]))
        return {
            "count": len(rows), "origin_counts": origin_counts, "split_counts": split_counts,
            "consented_user_count": human, "proxy_count": len(rows) - human,
            "validity": wilson_interval(valid, len(rows)),
            "truth_boundary": "Proxy/evaluator rows are never counted as independent human feedback.",
        }

    def save_run(self, report: dict[str, Any]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.store._conn() as connection:
            cursor = connection.execute(
                """INSERT INTO answer_quality_runs_v1
                   (corpus_version,corpus_digest,metrics,confidence_intervals,passed,truth_boundary,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (str(report.get("version") or ""), str(report.get("corpus_digest") or ""),
                 _json(report.get("metrics") or {}), _json(report.get("confidence_intervals") or {}),
                 int(bool(report.get("passed"))), str(report.get("truth_boundary") or ""), now),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _row(item: dict[str, Any]) -> dict[str, Any]:
        for key, fallback in (("evidence", []), ("expected_relations", {}), ("validation", {}), ("metadata", {})):
            item[key] = _loads(item.get(key), fallback)
        item["must_refuse"] = bool(item.get("must_refuse"))
        item["consented"] = bool(item.get("consented"))
        item["frozen"] = bool(item.get("frozen"))
        return item
