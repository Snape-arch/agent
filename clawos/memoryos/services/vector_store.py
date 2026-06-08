"""VectorStore — lightweight embedding-based semantic search (no external Chroma needed).

Generates fixed-dimension embeddings from text using character n-grams.
This is a pure-Python vector store that provides semantic search capability
without requiring any external ML models or network downloads.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import numpy as np


class VectorStore:
    """Pure-Python vector store using character n-gram embeddings.

    The embedding technique uses character n-grams (bigrams, trigrams, 4-grams)
    hashed into a fixed-dimension vector space, then normalized for cosine similarity.
    This provides reasonable semantic search without external ML dependencies.

    For a competition/production version, swap this for ChromaDB + sentence-transformers.
    """

    def __init__(self, dim: int = 256, persist_path: str = ""):
        self.dim = dim
        self._vectors: dict[str, np.ndarray] = {}
        self._texts: dict[str, str] = {}
        self._metadata: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _embed(self, text: str) -> np.ndarray:
        """Generate embedding vector from text using character n-grams.

        Uses counts of overlapping character n-grams (n=2,3,4) hashed into
        a fixed-dimension vector, then L2-normalized.
        """
        vec = np.zeros(self.dim)
        text = text.lower()
        for n in range(2, 5):
            for i in range(len(text) - n + 1):
                gram = text[i:i + n]
                idx = abs(hash(gram)) % self.dim
                vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        """Add a document with its embedding to the store."""
        with self._lock:
            self._vectors[doc_id] = self._embed(text)
            self._texts[doc_id] = text
            self._metadata[doc_id] = metadata or {}

    def remove(self, doc_id: str) -> None:
        """Remove a document by ID."""
        with self._lock:
            self._vectors.pop(doc_id, None)
            self._texts.pop(doc_id, None)
            self._metadata.pop(doc_id, None)

    def update(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        """Update a document's text and embedding."""
        self.add(doc_id, text, metadata)

    def search(self, query: str, top_k: int = 10, min_score: float = 0.15) -> list[dict]:
        """Search for semantically similar documents using cosine similarity.

        Returns sorted list of {id, text, score, metadata} dicts.
        """
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
        """Get a document by ID."""
        with self._lock:
            if doc_id not in self._vectors:
                return None
            return {
                "id": doc_id,
                "text": self._texts.get(doc_id, ""),
                "metadata": self._metadata.get(doc_id, {}),
            }

    def list_all(self) -> list[dict]:
        """List all documents in the store."""
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


class MemoryVectorStore:
    """High-level vector store integrated with MemoryOS SQLite.

    Automatically syncs experiences and knowledge entries between
    SQLite and the in-memory vector index for semantic search.
    """

    def __init__(self, db_path: str, dim: int = 256):
        self.db_path = db_path
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
        """Load existing experiences and knowledge from SQLite into vector index."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            # Load experiences
            rows = conn.execute(
                "SELECT id, task, lesson, context, solution, outcome FROM experiences ORDER BY id"
            ).fetchall()
            for row in rows:
                doc_id = f"exp_{row['id']}"
                text = f"{row['task']} {row['lesson']} {row.get('context', '')} {row.get('solution', '')}"
                self._store.add(doc_id, text, {
                    "type": "experience",
                    "outcome": row["outcome"],
                    "task": row["task"][:200],
                })
            # Load knowledge
            rows = conn.execute(
                "SELECT id, title, content, category, source FROM knowledge ORDER BY id"
            ).fetchall()
            for row in rows:
                doc_id = f"kw_{row['id']}"
                text = f"{row['title']} {row['content']}"
                self._store.add(doc_id, text, {
                    "type": "knowledge",
                    "category": row["category"],
                    "source": row.get("source", ""),
                    "title": row["title"],
                })
            conn.close()
        except Exception:
            pass

    def add_experience(self, exp_id: int, task: str, lesson: str = "",
                       context: str = "", solution: str = "", outcome: str = "partial"):
        """Add an experience to the vector index."""
        self._ensure_loaded()
        doc_id = f"exp_{exp_id}"
        text = f"{task} {lesson} {context} {solution}"
        self._store.add(doc_id, text, {
            "type": "experience",
            "outcome": outcome,
            "task": task[:200],
        })

    def add_knowledge(self, kw_id: int, title: str, content: str,
                      category: str = "domain", source: str = ""):
        """Add a knowledge entry to the vector index."""
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
        """Semantic search across all memories."""
        self._ensure_loaded()
        return self._store.search(query, top_k, min_score)

    def search_experiences(self, query: str, top_k: int = 5) -> list[dict]:
        """Search only experience memories."""
        results = self.search(query, top_k)
        return [r for r in results if r.get("metadata", {}).get("type") == "experience"]

    def search_knowledge(self, query: str, top_k: int = 5) -> list[dict]:
        """Search only knowledge entries."""
        results = self.search(query, top_k)
        return [r for r in results if r.get("metadata", {}).get("type") == "knowledge"]

    def refresh(self):
        """Reload all data from SQLite."""
        self._store.clear()
        self._loaded = False

    def stats(self) -> dict:
        self._ensure_loaded()
        return {
            "vector_count": self._store.count(),
            "experiences": len([r for r in self._store.list_all()
                                if r.get("metadata", {}).get("type") == "experience"]),
            "knowledge": len([r for r in self._store.list_all()
                              if r.get("metadata", {}).get("type") == "knowledge"]),
        }
