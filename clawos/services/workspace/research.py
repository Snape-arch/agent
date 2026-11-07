"""Research workflows and their domain dependencies."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from services.workspace.shared import WorkspaceValues


class ResearchWorkspace:
    """Workspace research responsibilities."""

    def __init__(self, store, security):
        self.store = store
        self.security = security

    def import_research_pdf(self, file_path, title=""):
        path = self.security.resolve_path(file_path)
        if path.suffix.lower() != ".pdf" or not path.is_file():
            raise ValueError("a readable PDF file is required")
        text, extraction_meta = self._extract_pdf_text(path)
        pages = text.split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        digest = WorkspaceValues._file_hash(path)
        ocr_pages = [
            index for index, page in enumerate(pages, 1)
            if len(page.strip()) < 20
        ]
        ocr_status = "ocr_required" if ocr_pages else "text_extracted"
        knowledge_entries = []
        with self.store._conn() as c:
            existing = c.execute(
                "SELECT id FROM research_documents WHERE file_path=?", (str(path),)
            ).fetchone()
            if existing:
                c.execute("DELETE FROM research_chunks WHERE document_id=?", (int(existing["id"]),))
                document_id = int(existing["id"])
                c.execute(
                    """
                    UPDATE research_documents
                    SET title=?, file_hash=?, page_count=?, metadata=?
                    WHERE id=?
                    """,
                    (
                        title or path.stem, digest, len(pages),
                        json.dumps({
                            **extraction_meta,
                            "ocr_status": ocr_status,
                            "ocr_pages": ocr_pages,
                        }, ensure_ascii=False),
                        document_id,
                    ),
                )
            else:
                cursor = c.execute(
                    """
                    INSERT INTO research_documents
                        (title, file_path, file_hash, page_count, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        title or path.stem, str(path), digest, len(pages),
                        json.dumps({
                            **extraction_meta,
                            "ocr_status": ocr_status,
                            "ocr_pages": ocr_pages,
                        }, ensure_ascii=False),
                    ),
                )
                document_id = int(cursor.lastrowid)
            chunk_count = 0
            for page_number, page in enumerate(pages, 1):
                for chunk_index, chunk in enumerate(self._chunk_text(page), 1):
                    c.execute(
                        """
                        INSERT INTO research_chunks
                            (document_id, page_number, chunk_index, content)
                        VALUES (?, ?, ?, ?)
                        """,
                        (document_id, page_number, chunk_index, chunk),
                    )
                    chunk_count += 1
                    knowledge_entries.append((page_number, chunk_index, chunk))
            document = dict(c.execute(
                "SELECT * FROM research_documents WHERE id=?", (document_id,)
            ).fetchone())
            document["chunk_count"] = chunk_count
            document["metadata"] = json.loads(document.get("metadata") or "{}")
        for page_number, chunk_index, chunk in knowledge_entries:
            self.store.add_knowledge(
                title=f"{title or path.stem} p.{page_number} #{chunk_index}",
                content=chunk,
                category="research_pdf",
                source=f"{path}#page={page_number}",
                confidence=0.9,
            )
        return document


    def validate_citations(self, citations):
        results = []
        with self.store._conn() as c:
            docs = {
                row["file_path"]: dict(row)
                for row in c.execute("SELECT * FROM research_documents").fetchall()
            }
            for citation in citations or []:
                raw = citation.get("source_ref") if isinstance(citation, dict) else str(citation)
                match = re.search(r"(.+?)#page=(\d+)", str(raw))
                valid = False
                reason = "citation must include #page=N"
                if match:
                    file_path, page = match.group(1), int(match.group(2))
                    doc = docs.get(str(Path(file_path).resolve(strict=False))) or docs.get(file_path)
                    if not doc:
                        reason = "document not imported"
                    elif page < 1 or page > int(doc["page_count"] or 0):
                        reason = "page out of range"
                    else:
                        valid, reason = True, "ok"
                results.append({"citation": raw, "valid": valid, "reason": reason})
        return {"valid": all(item["valid"] for item in results), "results": results}


    def research_compare_matrix(self, document_ids=None, query_terms=None):
        terms = [str(term).strip() for term in (query_terms or []) if str(term).strip()]
        with self.store._conn() as c:
            params = []
            where = ""
            if document_ids:
                ids = [int(item) for item in document_ids]
                where = "WHERE rd.id IN ({})".format(",".join("?" for _ in ids))
                params.extend(ids)
            docs = c.execute(f"SELECT * FROM research_documents rd {where} ORDER BY rd.id", params).fetchall()
            matrix = []
            for doc in docs:
                chunks = c.execute(
                    "SELECT content FROM research_chunks WHERE document_id=?",
                    (int(doc["id"]),),
                ).fetchall()
                text = "\n".join(row["content"] for row in chunks).lower()
                if not terms:
                    terms = sorted(set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", text)))[:8]
                matrix.append({
                    "document_id": int(doc["id"]),
                    "title": doc["title"],
                    "coverage": {term: text.count(term.lower()) for term in terms},
                })
        return {"terms": terms, "matrix": matrix}


    def create_repro_workflow(self, title, question="", steps=None, output_path=""):
        steps = steps or [
            "Record data provenance",
            "Run deterministic preprocessing",
            "Execute experiment script",
            "Export metrics and figures",
        ]
        manifest = {
            "title": str(title),
            "question": str(question or ""),
            "steps": steps,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": ["README.md", "experiment_plan.json", "notebooks/README.md"],
        }
        resolved_output = ""
        if output_path:
            out = self.security.resolve_path(output_path)
            if out.exists():
                raise ValueError("output_path already exists")
            out.mkdir(parents=True)
            (out / "notebooks").mkdir()
            (out / "README.md").write_text(
                f"# {title}\n\n## Question\n{question}\n\n## Reproduce\n" +
                "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps)) + "\n",
                encoding="utf-8",
            )
            (out / "experiment_plan.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (out / "notebooks" / "README.md").write_text("Place reproducible notebooks here.\n", encoding="utf-8")
            resolved_output = str(out)
        with self.store._conn() as c:
            cursor = c.execute(
                """
                INSERT INTO research_repro_workflows
                    (title, question, output_path, manifest)
                VALUES (?, ?, ?, ?)
                """,
                (str(title), str(question or ""), resolved_output, json.dumps(manifest, ensure_ascii=False)),
            )
            row = c.execute(
                "SELECT * FROM research_repro_workflows WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
            item = dict(row)
            item["manifest"] = json.loads(item["manifest"])
            return item


    def search_research(self, query, limit=10):
        terms = [term for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", str(query))][:6]
        if not terms:
            return []
        with self.store._conn() as c:
            clauses = " OR ".join("rc.content LIKE ?" for _ in terms)
            rows = c.execute(
                f"""
                SELECT rc.*, rd.title, rd.file_path
                FROM research_chunks rc
                JOIN research_documents rd ON rd.id=rc.document_id
                WHERE {clauses}
                ORDER BY rc.document_id DESC, rc.page_number, rc.chunk_index
                LIMIT ?
                """,
                [*(f"%{term}%" for term in terms), max(1, min(int(limit), 50))],
            ).fetchall()
            return [{
                **dict(row),
                "citation": f"{row['title']} (p.{row['page_number']})",
                "source_ref": f"{row['file_path']}#page={row['page_number']}",
            } for row in rows]


    @staticmethod
    def _chunk_text(text, size=1200, overlap=150):
        clean = "\n".join(line.rstrip() for line in str(text).splitlines()).strip()
        if not clean:
            return []
        chunks = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + size)
            chunks.append(clean[start:end])
            if end == len(clean):
                break
            start = max(start + 1, end - overlap)
        return chunks


    @staticmethod
    def _extract_pdf_text(path):
        try:
            from memoryos.document_ingestion import extract_pdf_text
            text, meta = extract_pdf_text(path)
            return text, meta
        except Exception:
            pass
        executable = shutil.which("pdftotext")
        if executable:
            proc = subprocess.run(
                [executable, "-layout", str(path), "-"],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.decode("utf-8", errors="replace")[:500])
            return proc.stdout.decode("utf-8", errors="replace"), {"extractor": "pdftotext"}
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("pdftotext or pypdf is required for local PDF extraction") from exc
        reader = PdfReader(str(path))
        return "\f".join((page.extract_text() or "") for page in reader.pages), {"extractor": "pypdf"}
