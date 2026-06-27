"""Offline vector search backends for MemoryOS.

The default backend is a dependency-light character n-gram vector index. When
``chromadb`` is installed, ``MemoryVectorStore(provider="chroma")`` uses a local
persistent Chroma collection with the same deterministic local embeddings, so it
does not download models or call the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

import numpy as np


class VectorStore:
    """Pure-Python vector store using character n-gram embeddings."""

    def __init__(self, dim: int = 256, persist_path: str = ""):
        self.dim = dim
        self.persist_path = persist_path
        self._vectors: dict[str, np.ndarray] = {}
        self._texts: dict[str, str] = {}
        self._metadata: dict[str, dict] = {}
        self._lock = threading.RLock()

    def _embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim)
        text = (text or "").lower()
        for n in range(2, 5):
            for i in range(len(text) - n + 1):
                gram = text[i:i + n]
                digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(digest, "little") % self.dim
                vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def embed(self, text: str) -> list[float]:
        return self._embed(text).astype(float).tolist()

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        with self._lock:
            self._vectors[str(doc_id)] = self._embed(text)
            self._texts[str(doc_id)] = text or ""
            self._metadata[str(doc_id)] = metadata or {}

    def remove(self, doc_id: str) -> None:
        with self._lock:
            self._vectors.pop(str(doc_id), None)
            self._texts.pop(str(doc_id), None)
            self._metadata.pop(str(doc_id), None)

    def update(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        self.add(doc_id, text, metadata)

    def search(self, query: str, top_k: int = 10, min_score: float = 0.15) -> list[dict]:
        with self._lock:
            if not self._vectors:
                return []
            query_vec = self._embed(query)
            scores = []
            for doc_id, vec in self._vectors.items():
                sim = float(np.dot(query_vec, vec))
                if sim >= min_score:
                    scores.append((sim, doc_id))
            scores.sort(key=lambda x: x[0], reverse=True)
            return [
                {
                    "id": doc_id,
                    "text": self._texts[doc_id],
                    "score": round(score, 4),
                    "metadata": self._metadata.get(doc_id, {}),
                }
                for score, doc_id in scores[:top_k]
            ]

    def get(self, doc_id: str) -> dict | None:
        with self._lock:
            key = str(doc_id)
            if key not in self._vectors:
                return None
            return {"id": key, "text": self._texts.get(key, ""), "metadata": self._metadata.get(key, {})}

    def list_all(self) -> list[dict]:
        with self._lock:
            return [
                {"id": doc_id, "text": text[:200], "metadata": self._metadata.get(doc_id, {})}
                for doc_id, text in self._texts.items()
            ]

    def count(self) -> int:
        with self._lock:
            return len(self._vectors)

    def clear(self) -> None:
        with self._lock:
            self._vectors.clear()
            self._texts.clear()
            self._metadata.clear()


def _metadata_for_chroma(metadata: dict | None) -> dict:
    clean: dict[str, str | int | float | bool] = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean[str(key)] = value
        else:
            clean[str(key)] = json.dumps(value, ensure_ascii=False)
    return clean


class ChromaVectorStore:
    """Offline Chroma backend using deterministic local embeddings."""

    def __init__(self, persist_path: str, dim: int = 256, collection_name: str = "clawos_memory"):
        try:
            import chromadb  # type: ignore
        except Exception as exc:  # pragma: no cover - fallback path covers this in tests
            raise RuntimeError(f"chromadb is not installed: {exc}") from exc
        self.dim = dim
        self.persist_path = str(Path(persist_path).expanduser().resolve())
        self.collection_name = collection_name
        self._encoder = VectorStore(dim=dim)
        try:
            from chromadb.config import Settings  # type: ignore
            settings = Settings(anonymized_telemetry=False)
        except Exception:
            settings = None
        self._client = chromadb.PersistentClient(path=self.persist_path, settings=settings)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._lock = threading.RLock()

    def _embedding(self, text: str) -> list[float]:
        return self._encoder.embed(text or "")

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        with self._lock:
            self._collection.upsert(
                ids=[str(doc_id)],
                documents=[text or ""],
                metadatas=[_metadata_for_chroma(metadata)],
                embeddings=[self._embedding(text or "")],
            )

    def remove(self, doc_id: str) -> None:
        with self._lock:
            try:
                self._collection.delete(ids=[str(doc_id)])
            except Exception:
                return

    def update(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        self.add(doc_id, text, metadata)

    def search(self, query: str, top_k: int = 10, min_score: float = 0.15) -> list[dict]:
        with self._lock:
            if self.count() <= 0:
                return []
            result = self._collection.query(
                query_embeddings=[self._embedding(query or "")],
                n_results=max(1, int(top_k or 10)),
                include=["documents", "metadatas", "distances"],
            )
            ids = (result.get("ids") or [[]])[0]
            docs = (result.get("documents") or [[]])[0]
            metas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            rows = []
            for doc_id, text, metadata, distance in zip(ids, docs, metas, distances):
                score = max(0.0, 1.0 - float(distance or 0.0))
                if score >= min_score:
                    rows.append({
                        "id": str(doc_id),
                        "text": text or "",
                        "score": round(score, 4),
                        "metadata": metadata or {},
                    })
            return rows

    def get(self, doc_id: str) -> dict | None:
        with self._lock:
            result = self._collection.get(ids=[str(doc_id)], include=["documents", "metadatas"])
            ids = result.get("ids") or []
            if not ids:
                return None
            return {
                "id": ids[0],
                "text": (result.get("documents") or [""])[0] or "",
                "metadata": (result.get("metadatas") or [{}])[0] or {},
            }

    def list_all(self) -> list[dict]:
        with self._lock:
            result = self._collection.get(include=["documents", "metadatas"])
            ids = result.get("ids") or []
            docs = result.get("documents") or []
            metas = result.get("metadatas") or []
            return [
                {"id": doc_id, "text": (text or "")[:200], "metadata": metadata or {}}
                for doc_id, text, metadata in zip(ids, docs, metas)
            ]

    def count(self) -> int:
        try:
            return int(self._collection.count())
        except Exception:
            return 0

    def clear(self) -> None:
        with self._lock:
            try:
                self._client.delete_collection(self.collection_name)
            except Exception:
                pass
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

    def close(self) -> None:
        with self._lock:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()


class MemoryVectorStore:
    """High-level vector store integrated with MemoryOS SQLite."""

    def __init__(self, db_path: str, dim: int = 256, provider: str = "", persist_dir: str = ""):
        self.db_path = db_path
        self.dim = dim
        requested = (
            provider
            or os.environ.get("CLAWOS_VECTOR_PROVIDER")
            or os.environ.get("VECTOR_PROVIDER")
            or "lightweight"
        ).strip().lower()
        self.requested_provider = requested
        self.provider = "lightweight"
        self.fallback_reason = ""
        self.persist_dir = (
            persist_dir
            or os.environ.get("CLAWOS_CHROMA_DIR")
            or os.environ.get("CHROMA_DIR")
            or str(Path(db_path).with_name("chroma"))
        )
        if requested == "chroma":
            try:
                self._store: VectorStore | ChromaVectorStore = ChromaVectorStore(self.persist_dir, dim=dim)
                self.provider = "chroma"
            except Exception as exc:
                self._store = VectorStore(dim=dim)
                self.fallback_reason = str(exc)
        else:
            self._store = VectorStore(dim=dim)
        self._lock = threading.Lock()
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        with self._lock:
            self._load_from_db()
            self._loaded = True

    def _load_from_db(self):
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, task, lesson, context, solution, outcome FROM experiences ORDER BY id"
            ).fetchall()
            for row in rows:
                doc_id = f"exp_{row['id']}"
                text = f"{row['task']} {row['lesson']} {row['context']} {row['solution']}"
                self._store.add(doc_id, text, {
                    "type": "experience",
                    "outcome": row["outcome"],
                    "task": row["task"][:200],
                })
            rows = conn.execute(
                "SELECT id, title, content, category, source FROM knowledge ORDER BY id"
            ).fetchall()
            for row in rows:
                doc_id = f"kw_{row['id']}"
                text = f"{row['title']} {row['content']}"
                self._store.add(doc_id, text, {
                    "type": "knowledge",
                    "category": row["category"],
                    "source": row["source"],
                    "title": row["title"],
                })
            rows = conn.execute(
                """
                SELECT id, memory_type, category, key, value, source, confidence
                FROM memories
                WHERE enabled=1
                ORDER BY id
                """
            ).fetchall()
            for row in rows:
                doc_id = f"mem_{row['id']}"
                text = f"{row['memory_type']} {row['category']} {row['key']} {row['value']}"
                self._store.add(doc_id, text, {
                    "type": row["memory_type"],
                    "category": row["category"],
                    "source": row["source"],
                    "title": row["key"],
                    "confidence": row["confidence"],
                })
            conn.close()
        except sqlite3.Error:
            return

    def add_experience(self, exp_id: int, task: str, lesson: str = "",
                       context: str = "", solution: str = "", outcome: str = "partial"):
        self._ensure_loaded()
        doc_id = f"exp_{exp_id}"
        text = f"{task} {lesson} {context} {solution}"
        self._store.add(doc_id, text, {"type": "experience", "outcome": outcome, "task": task[:200]})

    def add_knowledge(self, kw_id: int, title: str, content: str,
                      category: str = "domain", source: str = ""):
        self._ensure_loaded()
        doc_id = f"kw_{kw_id}"
        text = f"{title} {content}"
        self._store.add(doc_id, text, {
            "type": "knowledge",
            "category": category,
            "source": source,
            "title": title,
        })

    def search(self, query: str, top_k: int = 10, min_score: float = 0.15) -> list[dict]:
        self._ensure_loaded()
        return self._store.search(query, top_k, min_score)

    def search_experiences(self, query: str, top_k: int = 5) -> list[dict]:
        results = self.search(query, top_k)
        return [r for r in results if r.get("metadata", {}).get("type") == "experience"]

    def search_knowledge(self, query: str, top_k: int = 5) -> list[dict]:
        results = self.search(query, top_k)
        return [r for r in results if r.get("metadata", {}).get("type") == "knowledge"]

    def refresh(self):
        self._store.clear()
        self._loaded = False

    def close(self) -> None:
        close = getattr(self._store, "close", None)
        if callable(close):
            close()

    def stats(self) -> dict:
        self._ensure_loaded()
        rows = self._store.list_all()
        return {
            "provider": self.provider,
            "requested_provider": self.requested_provider,
            "fallback_reason": self.fallback_reason,
            "persist_dir": self.persist_dir if self.provider == "chroma" else "",
            "vector_count": self._store.count(),
            "experiences": len([r for r in rows if r.get("metadata", {}).get("type") == "experience"]),
            "knowledge": len([r for r in rows if r.get("metadata", {}).get("type") == "knowledge"]),
            "memories": len([r for r in rows if r.get("id", "").startswith("mem_")]),
        }
