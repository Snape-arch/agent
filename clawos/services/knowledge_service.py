from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from memoryos.document_ingestion import chunk_text


class KnowledgeService:
    """Document/RAG/OCR operations kept outside the FastAPI route file."""

    def __init__(self, store: Any, upload_dir: Path, vector_refresh: Callable[[], None] | None = None):
        self.store = store
        self.upload_dir = Path(upload_dir)
        self.vector_refresh = vector_refresh

    def list_ocr_queue(self, category: str = "") -> list[dict[str, Any]]:
        docs = self.store.list_documents(category)
        pending = []
        for doc in docs:
            meta = doc.get("metadata") or {}
            status = str(doc.get("status") or "").lower()
            if meta.get("ocr_required") or status in {"ocr_required", "needs_ocr"}:
                pending.append({
                    **doc,
                    "ocr_pages": meta.get("ocr_pages", []),
                    "ocr_reason": meta.get("ocr_reason") or "low_extractable_text",
                })
        return pending

    def citation_answer(self, q: str = "", category: str = "", document_id: int = 0, limit: int = 5) -> dict[str, Any]:
        top_k = max(1, min(int(limit or 5), 12))
        if document_id:
            document = self.store.get_document(document_id)
            if not document:
                raise ValueError("Document not found")
            chunks = self.store.get_document_chunks(document_id, top_k)
            for chunk in chunks:
                chunk.setdefault("title", document.get("title", ""))
                chunk.setdefault("filename", document.get("filename", ""))
                chunk.setdefault("category", document.get("category", ""))
        elif q:
            chunks = self.store.search_document_chunks(q, category, top_k)
        else:
            chunks = []

        citations = []
        lines = []
        for index, chunk in enumerate(chunks, 1):
            content = str(chunk.get("content") or "").strip()
            citation = chunk.get("citation") or f"doc:{chunk.get('document_id')}#chunk={chunk.get('chunk_index')}"
            citations.append({
                "rank": index,
                "citation": citation,
                "document_id": chunk.get("document_id"),
                "chunk_id": chunk.get("id"),
                "title": chunk.get("title") or chunk.get("filename") or "",
                "snippet": content[:360],
            })
            if content:
                lines.append(f"[{index}] {content[:420]}")
        answer = "No indexed evidence matched the query."
        if lines:
            answer = "基于已入库资料的可引用答案草稿：\n" + "\n\n".join(lines)
        return {"answer": answer, "citations": citations, "count": len(citations), "query": q, "category": category}

    def knowledge_graph(self, category: str = "", limit: int = 80) -> dict[str, Any]:
        max_nodes = max(12, min(int(limit or 80), 160))
        docs = self.store.list_documents(category)
        knowledge = self.store.list_knowledge(category)
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        def add_node(node_id: str, label: str, node_type: str, weight: int = 1, meta: dict[str, Any] | None = None):
            if node_id not in nodes:
                nodes[node_id] = {"id": node_id, "label": label, "type": node_type, "weight": weight, "meta": meta or {}}
            else:
                nodes[node_id]["weight"] = max(int(nodes[node_id].get("weight") or 1), int(weight or 1))

        root = f"category:{category or 'all'}"
        add_node(root, category or "all", "category", max(len(docs) + len(knowledge), 1))
        for doc in docs[: max_nodes // 2]:
            doc_id = f"doc:{doc.get('id')}"
            add_node(
                doc_id,
                doc.get("title") or doc.get("filename") or doc_id,
                "document",
                int(doc.get("chunk_count") or 1),
                {"status": doc.get("status"), "ocr_required": bool((doc.get("metadata") or {}).get("ocr_required"))},
            )
            edges.append({"source": root, "target": doc_id, "type": "contains"})
            for chunk in self.store.get_document_chunks(int(doc.get("id")), 3):
                chunk_id = f"chunk:{chunk.get('id')}"
                add_node(chunk_id, f"chunk {chunk.get('chunk_index')}", "chunk", 1, {"citation": chunk.get("citation", "")})
                edges.append({"source": doc_id, "target": chunk_id, "type": "cites"})
                for concept in self._extract_concepts(chunk.get("content", ""), limit=3):
                    concept_id = f"concept:{concept.lower()}"
                    add_node(concept_id, concept, "concept", 1)
                    edges.append({"source": chunk_id, "target": concept_id, "type": "mentions"})
        for item in knowledge[: max_nodes // 2]:
            item_id = f"knowledge:{item.get('id')}"
            add_node(item_id, item.get("title") or item_id, "knowledge", int(item.get("access_count") or 1), {"source": item.get("source", ""), "tags": item.get("tags", "")})
            edges.append({"source": root, "target": item_id, "type": "contains"})
            for tag in self._normalize_tags(item.get("tags"))[:6]:
                tag_id = f"tag:{tag.lower()}"
                add_node(tag_id, f"#{tag}", "tag", 1)
                edges.append({"source": item_id, "target": tag_id, "type": "tagged"})
            source = str(item.get("source") or "").strip()
            if source:
                source_key = source.split("#", 1)[0][:80]
                source_id = f"source:{source_key}"
                add_node(source_id, source_key, "source", 1, {"source": source})
                edges.append({"source": item_id, "target": source_id, "type": "sourced_from"})
            for link in self._extract_wikilinks(str(item.get("content") or ""))[:8]:
                link_id = f"wikilink:{link.lower()}"
                add_node(link_id, link, "wikilink", 1)
                edges.append({"source": item_id, "target": link_id, "type": "links_to"})
            for concept in self._extract_concepts(f"{item.get('title', '')} {item.get('content', '')}", limit=4):
                concept_id = f"concept:{concept.lower()}"
                add_node(concept_id, concept, "concept", 1)
                edges.append({"source": item_id, "target": concept_id, "type": "mentions"})
        title_to_id = {str(item.get("title") or ""): f"knowledge:{item.get('id')}" for item in knowledge if item.get("title")}
        for item in knowledge[: max_nodes // 2]:
            item_id = f"knowledge:{item.get('id')}"
            for link in self._extract_wikilinks(str(item.get("content") or "")):
                target_id = title_to_id.get(link)
                if target_id and target_id != item_id:
                    edges.append({"source": item_id, "target": target_id, "type": "backlink"})
        limited_nodes = list(nodes.values())[:max_nodes]
        allowed = {node["id"] for node in limited_nodes}
        limited_edges = [edge for edge in edges if edge["source"] in allowed and edge["target"] in allowed][: max_nodes * 2]
        return {"nodes": limited_nodes, "edges": limited_edges, "count": len(limited_nodes), "category": category or "all"}

    def obsidian_check(self, category: str = "", limit: int = 120) -> dict[str, Any]:
        """Validate whether the indexed knowledge can form a useful Obsidian-style vault."""
        items = self.store.list_knowledge(category)[: max(1, min(int(limit or 120), 500))]
        docs = self.store.list_documents(category)
        notes = [self._obsidian_note_payload(item, items) for item in items]
        wikilinks = sorted({link for note in notes for link in note["wikilinks"]})
        backlinks = sum(len(note["backlinks"]) for note in notes)
        tagged = sum(1 for note in notes if note["tags"])
        with_source = sum(1 for note in notes if note["source"])
        graph = self.knowledge_graph(category, limit=max(24, min(int(limit or 120), 160)))
        checks = [
            {"name": "frontmatter", "passed": all(note["frontmatter_ok"] for note in notes) if notes else True, "detail": "title/category/source/tags/confidence are renderable"},
            {"name": "wikilinks", "passed": bool(wikilinks) or len(notes) <= 1, "detail": f"{len(wikilinks)} wiki links detected"},
            {"name": "backlinks", "passed": backlinks > 0 or len(notes) <= 1, "detail": f"{backlinks} backlink edges detected"},
            {"name": "tags", "passed": tagged == len(notes) if notes else True, "detail": f"{tagged}/{len(notes)} notes have tags"},
            {"name": "sources", "passed": with_source == len(notes) if notes else True, "detail": f"{with_source}/{len(notes)} notes have source references"},
            {"name": "graph", "passed": bool(graph["nodes"]) and (bool(graph["edges"]) or len(notes) + len(docs) <= 1), "detail": f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges"},
        ]
        passed = sum(1 for check in checks if check["passed"])
        score = round(passed / len(checks), 4) if checks else 1.0
        return {
            "ok": score >= 0.84,
            "score": score,
            "category": category or "all",
            "note_count": len(notes),
            "document_count": len(docs),
            "wikilink_count": len(wikilinks),
            "backlink_count": backlinks,
            "checks": checks,
            "sample_notes": notes[:5],
            "graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
            "standard": "obsidian-frontmatter-tags-wikilinks-backlinks-graph",
        }

    def export_obsidian_vault(self, output_dir: Path, category: str = "", limit: int = 300) -> dict[str, Any]:
        items = self.store.list_knowledge(category)[: max(1, min(int(limit or 300), 1000))]
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        notes_dir = output_dir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        index_lines = [
            "---",
            "title: ClawOS Knowledge Vault",
            f"category: {self._yaml_scalar(category or 'all')}",
            f"generated_at: {self._yaml_scalar(datetime.now(timezone.utc).isoformat())}",
            "tags:",
            "  - clawos",
            "  - knowledge-vault",
            "---",
            "",
            "# ClawOS Knowledge Vault",
            "",
        ]
        notes = [self._obsidian_note_payload(item, items) for item in items]
        written = []
        for note in notes:
            filename = f"{self._safe_note_filename(note['title'])}.md"
            target = notes_dir / filename
            target.write_text(note["markdown"], encoding="utf-8")
            written.append(str(target))
            index_lines.append(f"- [[notes/{target.stem}|{note['title']}]]")
        (output_dir / "index.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
        report = self.obsidian_check(category, limit=limit)
        report.update({
            "exported": True,
            "output_dir": str(output_dir),
            "files": [str(output_dir / "index.md"), *written],
            "file_count": len(written) + 1,
        })
        return report

    def run_ocr(self, document_id: int, *, sidecar_text: str = "", force: bool = False) -> dict[str, Any]:
        document = self.store.get_document(document_id)
        if not document:
            raise ValueError("Document not found")
        meta = dict(document.get("metadata") or {})
        if not force and not (meta.get("ocr_required") or str(document.get("status") or "").lower() in {"ocr_required", "needs_ocr"}):
            return {"ok": True, "status": "skipped", "reason": "document does not require OCR", "document": document, "chunk_count": document.get("chunk_count", 0)}

        text, engine, reason = self._load_ocr_text(document, sidecar_text=sidecar_text)
        if not text.strip():
            meta.update({"ocr_attempted": True, "ocr_engine": engine, "ocr_error": reason})
            updated = self.store.add_document(
                title=document.get("title") or document.get("filename") or f"doc-{document_id}",
                filename=document.get("filename") or "",
                file_path=document.get("file_path") or "",
                file_hash=document.get("file_hash") or f"document-{document_id}",
                mime_type=document.get("mime_type") or "",
                category=document.get("category") or "domain",
                extractor=document.get("extractor") or "",
                status="ocr_unavailable",
                metadata=meta,
            )
            return {"ok": False, "status": "ocr_unavailable", "reason": reason, "document": updated, "chunk_count": 0}

        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("OCR produced no indexable text")
        meta.update({
            "ocr_required": False,
            "ocr_completed": True,
            "ocr_attempted": True,
            "ocr_engine": engine,
            "ocr_text_chars": len(text),
        })
        updated = self.store.add_document(
            title=document.get("title") or document.get("filename") or f"doc-{document_id}",
            filename=document.get("filename") or "",
            file_path=document.get("file_path") or "",
            file_hash=document.get("file_hash") or f"document-{document_id}",
            mime_type=document.get("mime_type") or "",
            category=document.get("category") or "domain",
            extractor=f"{document.get('extractor') or 'document'}+ocr",
            status="ready",
            metadata=meta,
        )
        if hasattr(self.store, "delete_knowledge_by_source_prefix"):
            self.store.delete_knowledge_by_source_prefix(f"doc:{updated['id']}#")
        knowledge_ids = []
        for index, chunk in enumerate(chunks, 1):
            citation = f"doc:{updated['id']}#chunk={index}"
            self.store.add_document_chunk(updated["id"], index, chunk, citation)
            item = self.store.add_knowledge(
                title=f"{updated['title']} #{index}",
                content=f"{chunk}\n\nSource: {citation}",
                category=updated.get("category") or "domain",
                source=citation,
                tags=["document", "ocr"],
                confidence=0.82,
            )
            knowledge_ids.append(int(item["id"]))
        if self.vector_refresh:
            self.vector_refresh()
        updated["chunk_count"] = len(chunks)
        updated["knowledge_ids"] = knowledge_ids
        return {"ok": True, "status": "ready", "reason": "ocr indexed", "document": updated, "chunk_count": len(chunks), "engine": engine}

    def _load_ocr_text(self, document: dict[str, Any], *, sidecar_text: str = "") -> tuple[str, str, str]:
        if sidecar_text.strip():
            return sidecar_text, "manual-sidecar", "sidecar text supplied by user"
        file_path = Path(str(document.get("file_path") or ""))
        for candidate in self._sidecar_candidates(file_path):
            if candidate.exists():
                if candidate.suffix.lower() == ".json":
                    data = json.loads(candidate.read_text(encoding="utf-8-sig"))
                    text = data.get("text") or "\n\n".join(str(p.get("text") or "") for p in data.get("pages", []))
                else:
                    text = candidate.read_text(encoding="utf-8-sig", errors="replace")
                return text, f"sidecar:{candidate.name}", "sidecar OCR text loaded"
        if file_path.exists() and file_path.suffix.lower() == ".pdf":
            text = self._try_local_pdf_ocr(file_path)
            if text.strip():
                return text, "tesseract", "local OCR completed"
        return "", "unavailable", "no sidecar OCR text or local tesseract/pdftoppm engine"

    @staticmethod
    def _sidecar_candidates(file_path: Path) -> list[Path]:
        if not str(file_path):
            return []
        return [
            Path(str(file_path) + ".ocr.txt"),
            file_path.with_suffix(file_path.suffix + ".ocr.txt"),
            file_path.with_suffix(".ocr.txt"),
            Path(str(file_path) + ".ocr.json"),
            file_path.with_suffix(".ocr.json"),
        ]

    @staticmethod
    def _try_local_pdf_ocr(file_path: Path) -> str:
        pdftoppm = shutil.which("pdftoppm")
        tesseract = shutil.which("tesseract")
        if not pdftoppm or not tesseract:
            return ""
        chunks: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            prefix = str(Path(td) / "page")
            subprocess.run([pdftoppm, "-png", "-r", "200", str(file_path), prefix], check=True, capture_output=True, timeout=180)
            for image_path in sorted(Path(td).glob("page-*.png")):
                out_prefix = str(image_path.with_suffix(""))
                subprocess.run([tesseract, str(image_path), out_prefix, "-l", "eng+chi_sim"], check=True, capture_output=True, timeout=180)
                text_path = image_path.with_suffix(".txt")
                if text_path.exists():
                    chunks.append(text_path.read_text(encoding="utf-8", errors="replace"))
        return "\n\n".join(chunks)

    def _obsidian_note_payload(self, item: dict[str, Any], all_items: list[dict[str, Any]]) -> dict[str, Any]:
        title = str(item.get("title") or f"Knowledge {item.get('id')}")
        content = str(item.get("content") or "").strip()
        source = str(item.get("source") or "").strip()
        tags = self._normalize_tags(item.get("tags"))
        if not tags:
            tags = [str(item.get("category") or "domain")]
        wikilinks = self._extract_wikilinks(content)
        titles = {str(other.get("title") or ""): other for other in all_items if other.get("id") != item.get("id")}
        backlinks = []
        for other in all_items:
            if other.get("id") == item.get("id"):
                continue
            other_content = str(other.get("content") or "")
            other_links = self._extract_wikilinks(other_content)
            if title in other_links or f"[[{title}]]" in other_content:
                backlinks.append({"id": other.get("id"), "title": other.get("title") or f"Knowledge {other.get('id')}"})
        inferred_links = [name for name in titles if name and name in content and name not in wikilinks]
        links = sorted(set(wikilinks + inferred_links))
        frontmatter = [
            "---",
            f"title: {self._yaml_scalar(title)}",
            f"category: {self._yaml_scalar(item.get('category') or 'domain')}",
            f"source: {self._yaml_scalar(source or 'manual')}",
            f"confidence: {float(item.get('confidence') or 0):.3f}",
            "tags:",
            *[f"  - {self._yaml_scalar(tag)}" for tag in tags],
            "---",
            "",
        ]
        body = [f"# {title}", "", content or "_No content captured._", ""]
        if source:
            body.extend(["## Source", "", source, ""])
        body.extend(["## Links", ""])
        body.extend([f"- [[{link}]]" for link in links] or ["- No wiki links detected"])
        body.extend(["", "## Backlinks", ""])
        body.extend([f"- [[{entry['title']}]]" for entry in backlinks] or ["- No backlinks detected"])
        return {
            "id": item.get("id"),
            "title": title,
            "source": source,
            "tags": tags,
            "wikilinks": links,
            "backlinks": backlinks,
            "frontmatter_ok": bool(title and tags and (source or item.get("source") == "")),
            "markdown": "\n".join(frontmatter + body) + "\n",
        }

    @staticmethod
    def _normalize_tags(raw: Any) -> list[str]:
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = [part.strip() for part in raw.split(",")]
        else:
            parsed = raw or []
        tags = []
        for tag in parsed if isinstance(parsed, list) else []:
            clean = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff/]+", "-", str(tag).strip()).strip("-")
            if clean and clean not in tags:
                tags.append(clean)
        return tags

    @staticmethod
    def _extract_wikilinks(content: str) -> list[str]:
        links = []
        for match in re.findall(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", str(content)):
            link = match.strip()
            if link and link not in links:
                links.append(link)
        return links

    @staticmethod
    def _extract_concepts(content: str, limit: int = 6) -> list[str]:
        stop = {
            "the", "and", "for", "with", "from", "this", "that", "into", "should", "about",
            "source", "manual", "document", "chunk", "answers", "generated",
        }
        counts: dict[str, int] = {}
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}|[\u4e00-\u9fff]{2,8}", str(content or "")):
            key = raw.strip()
            lowered = key.lower()
            if lowered in stop or len(key) < 2:
                continue
            counts[key] = counts.get(key, 0) + 1
        return [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[: max(1, int(limit or 6))]]

    @staticmethod
    def _safe_note_filename(title: str) -> str:
        safe = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(title)).strip("._")
        return safe[:90] or "knowledge_note"

    @staticmethod
    def _yaml_scalar(value: Any) -> str:
        text = str(value if value is not None else "").replace('"', '\\"')
        return f'"{text}"'
