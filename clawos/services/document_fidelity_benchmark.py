"""Fixed-corpus semantic fidelity evaluation for real PDF and DOCX files."""

from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from .document_semantic_graph_service import DocumentSemanticGraphService


DEFAULT_MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks" / "document_fidelity_corpus_v1.json"


def _normalize(value: Any) -> str:
    text = str(value or "").translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "�": ""}))
    return re.sub(r"\s+", " ", text).strip().casefold()


class DocumentFidelityBenchmark:
    """Measure labelled structure, page, relation and count fidelity without model grading."""

    SCHEMA = "clawos.document-fidelity-evaluation.v1"
    MANIFEST_SCHEMA = "clawos.document-fidelity-corpus.v1"

    def validate_manifest(self, manifest: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if manifest.get("schema") != self.MANIFEST_SCHEMA:
            errors.append("unsupported corpus schema")
        documents = manifest.get("documents") or []
        if len(documents) < 7:
            errors.append("fixed corpus requires at least seven real documents")
        seen: set[str] = set()
        for index, document in enumerate(documents):
            prefix = f"documents[{index}]"
            for key in ("id", "path", "format", "sha256", "assertions", "review"):
                if not document.get(key):
                    errors.append(f"{prefix}.{key} is required")
            if document.get("id") in seen:
                errors.append(f"{prefix}.id is duplicated")
            seen.add(str(document.get("id") or ""))
            if document.get("format") not in {"pdf", "docx"}:
                errors.append(f"{prefix}.format is invalid")
            digest = str(document.get("sha256") or "")
            if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
                errors.append(f"{prefix}.sha256 must be a full SHA-256 digest")
            review = document.get("review") or {}
            if not review.get("method") or not review.get("reviewed_at"):
                errors.append(f"{prefix}.review evidence is incomplete")
        return errors

    def evaluate(self, workspace_root: str | Path, manifest_path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
        root = Path(workspace_root).resolve()
        manifest_file = Path(manifest_path)
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        errors = self.validate_manifest(manifest)
        if errors:
            raise ValueError("; ".join(errors))
        parser = DocumentSemanticGraphService()
        rows: list[dict[str, Any]] = []
        assertion_values: list[bool] = []
        page_values: list[bool] = []
        relation_values: list[bool] = []
        count_values: list[bool] = []
        started = time.perf_counter()
        for document in manifest["documents"]:
            source = (root / document["path"]).resolve()
            within_root = source == root or root in source.parents
            if not within_root or not source.is_file():
                rows.append({"id": document["id"], "status": "unavailable", "path": str(source)})
                continue
            actual_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if actual_digest.casefold() != str(document["sha256"]).casefold():
                rows.append({"id": document["id"], "status": "digest_mismatch", "expected_sha256": document["sha256"], "actual_sha256": actual_digest})
                continue
            graph = parser.parse_docx(source, recover_rendered_pages=True) if source.suffix.lower() == ".docx" else parser.parse_pdf(source)
            assertions = [self._assertion(graph, item) for item in document.get("assertions") or []]
            relations = [self._relation(graph, item) for item in document.get("relations") or []]
            counts = [self._count(graph, key, spec) for key, spec in (document.get("counts") or {}).items()]
            assertion_values.extend(item["correct"] for item in assertions)
            page_values.extend(item["page_correct"] for item in assertions if item["page_evaluated"])
            relation_values.extend(item["correct"] for item in relations)
            count_values.extend(item["correct"] for item in counts)
            rows.append({
                "id": document["id"], "status": "evaluated", "path": str(source), "sha256": actual_digest,
                "format": graph["format"], "assertions": assertions, "relations": relations, "counts": counts,
                "parser_quality": graph.get("quality"), "layout_recovery": graph.get("layout_recovery"),
            })
        evaluated = [row for row in rows if row["status"] == "evaluated"]
        metrics = {
            "documents": {"expected": len(rows), "evaluated": len(evaluated)},
            "classification_accuracy": self._metric(assertion_values),
            "rendered_page_accuracy": self._metric(page_values),
            "relation_recall": self._metric(relation_values),
            "count_constraint_accuracy": self._metric(count_values),
        }
        gates = manifest.get("acceptance_gates") or {}
        checks = {
            "all_documents_identity_verified": len(evaluated) == len(rows),
            "minimum_labelled_assertions": len(assertion_values) >= int(gates.get("minimum_labelled_assertions", 30)),
            "classification_accuracy": metrics["classification_accuracy"]["rate"] >= float(gates.get("classification_accuracy", 0.85)),
            "rendered_page_accuracy": metrics["rendered_page_accuracy"]["rate"] >= float(gates.get("rendered_page_accuracy", 0.9)),
            "relation_recall": metrics["relation_recall"]["rate"] >= float(gates.get("relation_recall", 0.8)),
            "count_constraint_accuracy": metrics["count_constraint_accuracy"]["rate"] >= float(gates.get("count_constraint_accuracy", 0.9)),
        }
        return {
            "schema": self.SCHEMA, "corpus": manifest.get("name"), "version": manifest.get("version"),
            "manifest_digest": hashlib.sha256(manifest_file.read_bytes()).hexdigest(), "rows": rows,
            "metrics": metrics, "acceptance": {"passed": all(checks.values()), "checks": checks},
            "review_status": manifest.get("review_status"), "maintainer_signoff": bool(manifest.get("maintainer_signoff")),
            "release_claim_allowed": all(checks.values()) and bool(manifest.get("maintainer_signoff")),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "truth_boundary": manifest.get("truth_boundary"),
            "evaluation_split": "development_regression_not_held_out",
            "interval_boundary": "Wilson intervals describe these labelled assertions; labels within a document are correlated and were used during development, so these are not held-out population generalization bounds.",
        }

    def evaluate_ocr_sample(self, source_pdf: str | Path, *, page_number: int = 1) -> dict[str, Any]:
        """Rasterize a real text page, OCR the image-only PDF, and score words plus coordinates."""
        try:
            import fitz
        except Exception as exc:
            raise RuntimeError("PyMuPDF is required for OCR fidelity evaluation") from exc
        source = Path(source_pdf).resolve()
        if not source.is_file() or source.suffix.lower() != ".pdf":
            raise ValueError("source_pdf must be an existing PDF")
        with tempfile.TemporaryDirectory(prefix="clawos-ocr-benchmark-") as td, fitz.open(str(source)) as original:
            page = original[page_number - 1]
            expected_text = page.get_text("text") or ""
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
            scanned = fitz.open()
            scan_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
            scan_page.insert_image(scan_page.rect, pixmap=pixmap)
            scan_path = Path(td) / "image-only.pdf"
            scanned.save(str(scan_path))
            scanned.close()
            graph = DocumentSemanticGraphService().parse_pdf(scan_path)
        ocr_words = [word for item in graph.get("ocr_pages") or [] for word in item.get("words") or []]
        if not ocr_words:
            ocr_words = [
                {"text": node.get("text", ""), "bbox": node.get("bbox") or [], "confidence": node.get("confidence", 0.0)}
                for node in graph.get("nodes") or [] if node.get("type") == "ocr_word"
            ]
        expected = self._tokens(expected_text)
        actual = self._tokens(" ".join(str(word.get("text") or "") for word in ocr_words))
        expected_counter, actual_counter = Counter(expected), Counter(actual)
        matched = sum(min(count, actual_counter[token]) for token, count in expected_counter.items())
        word_recall = matched / max(1, sum(expected_counter.values()))
        bbox_valid = sum(
            len(word.get("bbox") or []) == 4
            and word["bbox"][0] < word["bbox"][2]
            and word["bbox"][1] < word["bbox"][3]
            for word in ocr_words
        ) / max(1, len(ocr_words))
        mean_confidence = sum(float(word.get("confidence") or 0) for word in ocr_words) / max(1, len(ocr_words))
        checks = {
            "ocr_completed": bool(ocr_words),
            "word_recall": word_recall >= 0.72,
            "bbox_validity": bbox_valid >= 0.99,
            "mean_confidence": mean_confidence >= 0.75,
        }
        return {
            "schema": "clawos.document-ocr-fidelity.v1", "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "page": page_number, "engine": "tesseract-tsv", "expected_tokens": len(expected), "ocr_words": len(ocr_words),
            "metrics": {"word_recall": round(word_recall, 6), "bbox_validity": round(bbox_valid, 6), "mean_confidence": round(mean_confidence, 6)},
            "acceptance": {"passed": all(checks.values()), "checks": checks},
            "truth_boundary": "A real born-digital English PDF page was rasterized into an image-only PDF. Text extracted before rasterization is the OCR reference; this does not measure handwriting or Chinese OCR.",
        }

    @staticmethod
    def _tokens(value: str) -> list[str]:
        return [token.casefold() for token in re.findall(r"[A-Za-z0-9]+", value or "") if len(token) >= 2]

    @staticmethod
    def _assertion(graph: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
        anchor = _normalize(spec.get("text"))
        candidates = [node for node in graph.get("nodes") or [] if anchor and anchor in _normalize(node.get("text"))]
        candidate = min(candidates, key=lambda node: len(_normalize(node.get("text")))) if candidates else None
        expected_types = spec.get("types") or [spec.get("type")]
        expected_types = [str(item) for item in expected_types if item]
        expected_page = spec.get("page")
        found_type = str(candidate.get("type") or "") if candidate else ""
        found_page = int(candidate.get("page") or 0) if candidate else 0
        return {
            "text": spec.get("text"), "expected_types": expected_types, "expected_page": expected_page,
            "found": candidate is not None, "found_type": found_type, "found_page": found_page,
            "correct": candidate is not None and found_type in expected_types,
            "page_evaluated": expected_page is not None,
            "page_correct": candidate is not None and (expected_page is None or found_page == int(expected_page)),
            "node_id": candidate.get("id") if candidate else None,
        }

    @staticmethod
    def _relation(graph: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
        source_anchor = _normalize(spec.get("source_text"))
        sources = [node for node in graph.get("nodes") or [] if source_anchor in _normalize(node.get("text"))]
        source_ids = {node.get("id") for node in sources}
        nodes_by_id = {node.get("id"): node for node in graph.get("nodes") or []}
        matched = []
        for relation in graph.get("relations") or []:
            if relation.get("source") not in source_ids or relation.get("type") != spec.get("type"):
                continue
            target = nodes_by_id.get(relation.get("target"), {})
            if target.get("semantic_only") and not spec.get("allow_inferred", False):
                continue
            if not spec.get("target_type") or target.get("type") == spec.get("target_type"):
                matched.append(relation)
        return {**spec, "correct": bool(matched), "matches": matched[:3]}

    @staticmethod
    def _count(graph: dict[str, Any], key: str, spec: Any) -> dict[str, Any]:
        if key == "pages":
            actual = len(graph.get("pages") or [])
        elif key == "headings":
            actual = sum(node.get("type") == "heading" for node in graph.get("nodes") or [])
        else:
            actual = sum(not item.get("semantic_only") for item in graph.get(key) or [])
        limits = spec if isinstance(spec, dict) else {"exact": int(spec)}
        correct = ("exact" not in limits or actual == int(limits["exact"])) and ("min" not in limits or actual >= int(limits["min"])) and ("max" not in limits or actual <= int(limits["max"]))
        return {"name": key, "actual": actual, "constraint": limits, "correct": correct}

    @classmethod
    def _metric(cls, values: list[bool]) -> dict[str, Any]:
        n, successes = len(values), sum(values)
        rate = successes / n if n else 0.0
        return {"successes": successes, "n": n, "rate": round(rate, 6), "wilson_95": cls._wilson(successes, n)}

    @staticmethod
    def _wilson(successes: int, n: int) -> list[float]:
        if not n:
            return [0.0, 0.0]
        z, p = 1.959963984540054, successes / n
        denominator = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denominator
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
        return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]
