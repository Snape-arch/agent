"""Source-bound, optimistic-concurrency OCR review; never a model auto-approval."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from .document_semantic_graph_service import DocumentSemanticGraphService


class DocumentReviewService:
    def __init__(self, store, allowed_roots):
        self.store = store
        self.roots = [Path(p).resolve() for p in allowed_roots]

    def _source(self, document):
        path = Path(document.get("file_path") or "").resolve()
        if not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError("Review source is outside allowed roots")
        if not path.is_file():
            raise ValueError("Review source is unavailable")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        actual = digest.hexdigest()
        expected = str(document.get("file_hash") or "")
        if len(expected) == 64 and expected != actual:
            raise ValueError("Source changed since extraction; re-ingest before review")
        return path, actual

    @staticmethod
    def _revision(document, digest):
        payload = json.dumps([document["id"], document["metadata"], digest], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _targets(graph, chunk):
        nodes = {n["id"]: n for n in graph.get("nodes", [])}
        targets = {}
        for node_id in chunk["metadata"].get("node_ids", []):
            node = nodes.get(node_id)
            if not node:
                raise ValueError("Review evidence node is missing; re-ingest the source")
            if node["type"] == "table_row":
                for cell_id in node["cell_ids"]:
                    cell = nodes[cell_id]
                    targets[cell_id] = cell
                    for header_id in cell.get("header_refs", []):
                        targets[header_id] = nodes[header_id]
            else:
                targets[node_id] = node
        if not targets:
            raise ValueError("No positioned evidence to review; re-ingest the source")
        return targets

    def queue(self, document_id):
        document = self.store.get_document(document_id, include_review=True)
        if not document:
            raise ValueError("Document not found")
        _, digest = self._source(document)
        graph = document["metadata"].get("semantic_graph") or {}
        chunks = self.store.get_document_chunks(document_id, 10000, include_review=True)
        items = []
        for chunk in chunks:
            if not chunk["metadata"].get("review_required"):
                continue
            targets = self._targets(graph, chunk)
            items.append({"chunk_id": chunk["id"], "citation": chunk["citation"],
                          "state": chunk["metadata"].get("review_state", "pending"),
                          "cells": [{"id": key, "text": node.get("text", ""), "original_text": node.get("original_text", node.get("text", "")),
                                     "page": node.get("page"), "bbox": node.get("bbox"), "header": node.get("column_header", ""),
                                     "is_header": node.get("is_header", node.get("row") == 0),
                                     "verification": node.get("verification", {}), "reasons": node.get("review_reasons", []),
                                     "crop_url": f"/api/documents/{document_id}/review/crop?node_id={key}"}
                                    for key, node in targets.items()]})
        with self.store._conn() as c:
            history = [dict(row) for row in c.execute("SELECT id,actor,created_at,payload FROM document_review_events WHERE document_id=? ORDER BY id", (document_id,))]
        return {"document_id": document_id, "revision": self._revision(document, digest), "source_sha256": digest,
                "items": items, "history": history, "inspection_only": True}

    def crop(self, document_id, node_id):
        import fitz
        document = self.store.get_document(document_id, include_review=True)
        if not document:
            raise ValueError("Document not found")
        path, _ = self._source(document)
        node = next((n for n in document["metadata"].get("semantic_graph", {}).get("nodes", []) if n["id"] == node_id), None)
        if not node or len(node.get("bbox", [])) != 4 or not node.get("page") or path.suffix.lower() != ".pdf":
            raise ValueError("Positioned PDF evidence is unavailable")
        with fitz.open(path) as pdf:
            page = pdf[int(node["page"])-1]
            # Graph bounds use unrotated points. Transform before clipping a
            # rendered (potentially rotated) page.
            box = fitz.Rect(node["bbox"]) * page.rotation_matrix
            box = (box + (-3,-3,3,3)) & page.rect
            if box.is_empty:
                raise ValueError("Evidence crop is outside the page")
            return page.get_pixmap(matrix=fitz.Matrix(3,3), clip=box, alpha=False).tobytes("png")

    def submit(self, document_id, *, chunk_id, revision, values, confirmed=False, action="approve", actor="local-user"):
        if confirmed is not True:
            raise ValueError("Explicit source inspection confirmation is required")
        if action not in {"approve", "reject"} or not isinstance(values, dict):
            raise ValueError("Invalid review action or cell values")
        document = self.store.get_document(document_id, include_review=True)
        if not document:
            raise ValueError("Document not found")
        _, digest = self._source(document)
        if revision != self._revision(document, digest):
            raise ValueError("Stale review: source or evidence changed; reload")
        graph = deepcopy(document["metadata"].get("semantic_graph") or {})
        chunks = self.store.get_document_chunks(document_id, 10000, include_review=True)
        chunk = next((row for row in chunks if row["id"] == chunk_id), None)
        if not chunk or not chunk["metadata"].get("review_required"):
            raise ValueError("Chunk is not pending review")
        targets = self._targets(graph, chunk)
        if action == "approve" and (set(values) != set(targets) or any(not isinstance(v, str) or not v.strip() or len(v)>8000 for v in values.values())):
            raise ValueError("Confirm every cell and its headers; missing/extra/empty values are not accepted")
        changes = []
        if action == "approve":
            for node_id, node in targets.items():
                value = values[node_id].strip()
                # Shared headers already confirmed by another row cannot be
                # silently rewritten, which would invalidate published rows.
                if node.get("human_review") and node["text"] != value:
                    raise ValueError("Previously confirmed cell differs; re-ingest for a new review revision")
                changes.append({"node_id": node_id, "before": node["text"], "after": value, "bbox": node.get("bbox"), "page": node.get("page")})
                node.setdefault("original_text", node["text"])
                node.update(text=value, value_text=value, review_required=False,
                            human_review={"source_sha256": digest, "actor": actor, "revision": revision})
            by_id = {n["id"]: n for n in graph["nodes"]}
            for table in graph.get("tables", []):
                if table.get("representation") != "raster_header_grid":
                    continue
                for cell in table["cells"]:
                    updated = by_id[cell["id"]]
                    cell.update(updated)
                    table["rows"][cell["row"]][cell["column"]] = cell["text"]
                table["headers"] = list(table["rows"][0])
                for cell in table["cells"]:
                    cell["column_header"] = table["headers"][cell["column"]]
                    cell["row_label"] = table["rows"][cell["row"]][0]
                    by_id[cell["id"]].update(cell)
                for row in graph["nodes"]:
                    if row.get("type") != "table_row" or not row["id"].startswith(table["id"] + ":row:"):
                        continue
                    cells = [by_id[c] for c in row["cell_ids"]]
                    row["text"] = " | ".join(p for p in [table.get("caption", ""), *[f"{c['column_header']} = {c['text']}" for c in cells]] if p)
                    row["review_required"] = any(c.get("review_required") or any(by_id[h].get("review_required") for h in c.get("header_refs", [])) for c in cells)
                if table["id"] in by_id:
                    by_id[table["id"]].update(deepcopy(table))
            graph["evidence_units"] = DocumentSemanticGraphService._evidence_units(graph["nodes"])
            graph["plain_text"] = "\n".join(n["text"] for n in graph["evidence_units"])
        units = {n["id"]: n for n in graph.get("evidence_units", [])}
        for row in chunks:
            meta = row["metadata"]
            if row["id"] == chunk_id and action == "reject":
                meta["review_state"] = "rejected"
            if action == "approve" and meta.get("review_required"):
                refs = [units.get(i) for i in meta.get("node_ids", [])]
                if refs and all(ref is not None for ref in refs):
                    row["content"] = "\n".join(ref["text"] for ref in refs)
                    meta["review_required"] = any(ref.get("review_required") for ref in refs)
                    if not meta["review_required"]:
                        meta.update(review_state="approved", reviewed_source_sha256=digest)
        metadata = document["metadata"]
        metadata["semantic_graph"] = graph
        metadata["review_revision"] = revision
        metadata["ocr_review_pages"] = sorted({row["metadata"].get("page_number", 0) for row in chunks if row["metadata"].get("review_required")})
        if "structure" in metadata:
            metadata["structure"]["tables"] = graph.get("tables", [])
        withheld = [row for row in chunks if row["metadata"].get("review_required")]
        pending = [row for row in withheld if row["metadata"].get("review_state") != "rejected"]
        status = "needs_ocr" if metadata.get("ocr_required") else ("needs_review" if pending else ("ready_with_exclusions" if withheld else "ready"))
        # Compare and commit under one write transaction. Events survive OCR
        # re-ingestion; stale forms cannot approve a replacement extraction.
        with self.store._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            current = dict(c.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())
            current["metadata"] = json.loads(current["metadata"])
            if self._revision(current, digest) != revision or self._source(current)[1] != digest:
                raise ValueError("Stale review: source or evidence changed; reload")
            invalidated = []
            for row in chunks:
                previous = c.execute("SELECT content,metadata FROM document_chunks WHERE id=?", (row["id"],)).fetchone()
                if previous and (previous["content"] != row["content"] or json.loads(previous["metadata"]).get("review_required") != row["metadata"].get("review_required")):
                    # Retire old derived knowledge, including pre-gate leftovers.
                    # Preserve the full records in the immutable review event.
                    invalidated.extend(dict(k) for k in c.execute("SELECT * FROM knowledge WHERE source=?", (row["citation"],)))
                    c.execute("DELETE FROM knowledge WHERE source=?", (row["citation"],))
                    if c.execute("SELECT 1 FROM sqlite_master WHERE name='knowledge_sources_v2'").fetchone():
                        retired = list(c.execute("SELECT k.id,k.current_version FROM knowledge_records_v2 k JOIN knowledge_sources_v2 s ON s.knowledge_id=k.id WHERE s.source_ref=?", (row["citation"],)))
                        c.execute("UPDATE knowledge_records_v2 SET status='expired' WHERE id IN (SELECT knowledge_id FROM knowledge_sources_v2 WHERE source_ref=?)", (row["citation"],))
                        for record in retired:
                            c.execute("INSERT INTO knowledge_vector_outbox_v2(knowledge_id,operation,payload_version,created_at) VALUES(?,?,?,datetime('now'))", (record["id"],"delete",record["current_version"]))
                c.execute("UPDATE document_chunks SET content=?,metadata=? WHERE id=? AND document_id=?", (row["content"],json.dumps(row["metadata"],ensure_ascii=False),row["id"],document_id))
            c.execute("UPDATE documents SET metadata=?,status=?,updated_at=datetime('now') WHERE id=?", (json.dumps(metadata,ensure_ascii=False),status,document_id))
            c.execute("INSERT INTO document_review_events(document_id,source_sha256,revision,actor,payload) VALUES(?,?,?,?,?)",
                      (document_id,digest,revision,actor,json.dumps({"action":action,"chunk_id":chunk_id,"changes":changes,"invalidated_knowledge":invalidated},ensure_ascii=False)))
        # Approved chunks are immediately available through the gated retrieval
        # path. Publishing to the long-term knowledge index is explicit/retryable.
        return {"ok": True, "status": status, "remaining": len(pending), "withheld": len(withheld), "action": action,
                "publication": "ready_for_explicit_publish" if action == "approve" else "withheld"}

    def publish(self, document_id, *, confirmed=False):
        if confirmed is not True:
            raise ValueError("Explicit knowledge publication confirmation is required")
        document = self.store.get_document(document_id, include_review=True)
        if not document:
            raise ValueError("Document not found")
        _, digest = self._source(document)
        ids = []
        for chunk in self.store.get_document_chunks(document_id, 10000):
            if chunk["metadata"].get("review_state") != "approved":
                continue
            if chunk["metadata"].get("reviewed_source_sha256") != digest:
                raise ValueError("Source changed since review; re-ingest before publication")
            item = self.store.add_knowledge(title=f"{document['title']} #{chunk['chunk_index']}", content=chunk["content"],
                                           source=chunk["citation"], category=document["category"], tags=["document","source-reviewed"], confidence=.9,
                                           reviewed_chunk_id=chunk["id"])
            ids.append(item["id"])
        return {"ok": True, "knowledge_ids": ids, "count": len(ids)}
