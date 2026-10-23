"""Offline vector search backends for MemoryOS.

The default backend is a dependency-light character n-gram vector index. When
``chromadb`` is installed, ``MemoryVectorStore(provider="chroma")`` uses a local
persistent Chroma collection. Embeddings default to deterministic local hash
vectors, and can be upgraded to a local sentence-transformers model such as
Qwen3-Embedding-0.6B without changing the MemoryVectorStore contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
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

    def add_many(self, rows: list[dict]) -> None:
        for row in rows:
            self.add(row["id"], row.get("text", ""), row.get("metadata") or {})

    def remove(self, doc_id: str) -> None:
        with self._lock:
            self._vectors.pop(str(doc_id), None)
            self._texts.pop(str(doc_id), None)
            self._metadata.pop(str(doc_id), None)

    def update(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        self.add(doc_id, text, metadata)

    def search(
        self, query: str, top_k: int = 10, min_score: float = 0.15,
        filters: dict | None = None,
    ) -> list[dict]:
        with self._lock:
            if not self._vectors:
                return []
            query_vec = self._embed(query)
            scores = []
            for doc_id, vec in self._vectors.items():
                metadata = self._metadata.get(doc_id, {})
                if filters and any(metadata.get(key) != value for key, value in filters.items()):
                    continue
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


class SentenceTransformerEncoder:
    """Lazy local sentence-transformers encoder."""

    def __init__(self, model_path: str, dim: int = 1024, device: str = ""):
        self.model_path = str(Path(model_path).expanduser().resolve())
        self.dim = int(dim or 1024)
        self.device = str(
            device
            or os.environ.get("CLAWOS_EMBEDDING_DEVICE")
            or os.environ.get("EMBEDDING_DEVICE")
            or "cpu"
        ).strip()
        self._model = None
        self._lock = threading.RLock()

    def _load(self):
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer  # type: ignore
                except Exception as exc:
                    raise RuntimeError(f"sentence-transformers is not installed: {exc}") from exc
                if not Path(self.model_path).exists():
                    raise RuntimeError(f"embedding model path not found: {self.model_path}")
                self._model = SentenceTransformer(self.model_path, device=self.device, local_files_only=True)
            return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load()
        vector = model.encode([text or ""], normalize_embeddings=True, show_progress_bar=False)[0]
        return np.asarray(vector, dtype=float).tolist()

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode([text or "" for text in texts], normalize_embeddings=True, batch_size=16, show_progress_bar=False)
        return np.asarray(vectors, dtype=float).tolist()


def _embedding_provider_name(provider: str = "") -> str:
    return (
        provider
        or os.environ.get("CLAWOS_EMBEDDING_PROVIDER")
        or os.environ.get("EMBEDDING_PROVIDER")
        or "hash"
    ).strip().lower()


def _default_embedding_model_path() -> str:
    return str((Path(__file__).resolve().parents[3] / "tools" / "models" / "qwen3-embedding-0.6b").resolve())


def _create_encoder(provider: str, dim: int):
    return _create_encoder_with_model(provider, dim, "")


def _create_encoder_with_model(provider: str, dim: int, model_path: str = ""):
    if provider in {"hash", "local_hash", "ngram", ""}:
        return VectorStore(dim=dim), dim, ""
    if provider in {"qwen3", "qwen3-embedding", "sentence_transformers", "sentence-transformers", "local"}:
        model_path = model_path or (
            os.environ.get("CLAWOS_EMBEDDING_MODEL_PATH")
            or os.environ.get("EMBEDDING_MODEL_PATH")
            or _default_embedding_model_path()
        )
        target_dim = int(os.environ.get("CLAWOS_EMBEDDING_DIM") or os.environ.get("EMBEDDING_DIM") or dim or 1024)
        return SentenceTransformerEncoder(model_path, target_dim), target_dim, model_path
    raise RuntimeError(f"Unsupported embedding provider: {provider}")


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
    """Offline Chroma backend using a local embedding encoder."""

    def __init__(self, persist_path: str, dim: int = 256, collection_name: str = "clawos_memory", encoder=None):
        try:
            import chromadb  # type: ignore
        except Exception as exc:  # pragma: no cover - fallback path covers this in tests
            raise RuntimeError(f"chromadb is not installed: {exc}") from exc
        self.dim = dim
        self.persist_path = str(Path(persist_path).expanduser().resolve())
        self.collection_name = collection_name
        self._encoder = encoder or VectorStore(dim=dim)
        try:
            from chromadb.config import Settings  # type: ignore
            settings = Settings(anonymized_telemetry=False)
        except Exception:
            settings = None
        self._client = chromadb.PersistentClient(path=self.persist_path, settings=settings)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine", "embedding_dim": int(dim)},
        )
        self._lock = threading.RLock()

    def _embedding(self, text: str) -> list[float]:
        return self._encoder.embed(text or "")

    def _embeddings(self, texts: list[str]) -> list[list[float]]:
        embed_many = getattr(self._encoder, "embed_many", None)
        if callable(embed_many):
            return embed_many([text or "" for text in texts])
        return [self._embedding(text or "") for text in texts]

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        with self._lock:
            self._collection.upsert(
                ids=[str(doc_id)],
                documents=[text or ""],
                metadatas=[_metadata_for_chroma(metadata)],
                embeddings=[self._embedding(text or "")],
            )

    def add_many(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self._lock:
            ids = [str(row["id"]) for row in rows]
            docs = [row.get("text", "") or "" for row in rows]
            metas = [_metadata_for_chroma(row.get("metadata") or {}) for row in rows]
            self._collection.upsert(
                ids=ids,
                documents=docs,
                metadatas=metas,
                embeddings=self._embeddings(docs),
            )

    def remove(self, doc_id: str) -> None:
        with self._lock:
            # A failed delete must remain pending in the durable outbox.
            self._collection.delete(ids=[str(doc_id)])

    def update(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        self.add(doc_id, text, metadata)

    def search(
        self, query: str, top_k: int = 10, min_score: float = 0.15,
        filters: dict | None = None,
    ) -> list[dict]:
        with self._lock:
            if self.count() <= 0:
                return []
            query_args = {
                "query_embeddings": [self._embedding(query or "")],
                "n_results": max(1, int(top_k or 10)),
                "include": ["documents", "metadatas", "distances"],
            }
            if filters:
                clauses = [{str(key): {"$eq": value}} for key, value in filters.items()]
                query_args["where"] = clauses[0] if len(clauses) == 1 else {"$and": clauses}
            result = self._collection.query(
                **query_args,
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
                metadata={"hnsw:space": "cosine", "embedding_dim": int(self.dim)},
            )

    def close(self) -> None:
        with self._lock:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()


class MemoryVectorStore:
    """High-level vector store integrated with MemoryOS SQLite."""

    def __init__(
        self,
        db_path: str,
        dim: int = 256,
        provider: str = "",
        persist_dir: str = "",
        embedding_provider: str = "",
        embedding_model_path: str = "",
        embedding_dim: int = 0,
    ):
        self.db_path = db_path
        self.embedding_provider = _embedding_provider_name(embedding_provider)
        if self.embedding_provider not in {"hash", "local_hash", "ngram", ""}:
            dim = int(embedding_dim or os.environ.get("CLAWOS_EMBEDDING_DIM") or os.environ.get("EMBEDDING_DIM") or 1024)
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
        self.embedding_model_path = ""
        self.index_schema_version = 2
        self.index_name = ""
        self.embedding_fingerprint = ""
        if requested == "chroma":
            try:
                encoder, self.dim, self.embedding_model_path = _create_encoder_with_model(
                    self.embedding_provider,
                    self.dim,
                    embedding_model_path,
                )
                self.embedding_fingerprint = self._fingerprint()
                collection_name = (
                    f"clawos_knowledge_v2_{self.embedding_provider.replace('-', '_')}_{self.dim}_"
                    f"{self.embedding_fingerprint[:10]}"
                )
                self.index_name = collection_name
                self._store: VectorStore | ChromaVectorStore = ChromaVectorStore(
                    self.persist_dir,
                    dim=self.dim,
                    collection_name=collection_name,
                    encoder=encoder,
                )
                self.provider = "chroma"
            except Exception as exc:
                self._store = VectorStore(dim=dim)
                self.fallback_reason = str(exc)
        else:
            self._store = VectorStore(dim=dim)
            self.embedding_fingerprint = self._fingerprint()
            self.index_name = f"clawos_knowledge_v2_lightweight_{self.dim}_{self.embedding_fingerprint[:10]}"
        self._lock = threading.RLock()
        self._loaded = False

    def _fingerprint(self) -> str:
        model = Path(self.embedding_model_path) if self.embedding_model_path else None
        model_marker = ""
        if model and model.exists():
            markers = []
            for name in ("config.json", "modules.json", "model.safetensors", "tokenizer.json"):
                candidate = model / name
                if candidate.exists():
                    stat = candidate.stat()
                    markers.append(f"{name}:{stat.st_size}:{stat.st_mtime_ns}")
            model_marker = "|".join(markers)
        raw = f"knowledge-v2|{self.embedding_provider}|{self.dim}|{model_marker}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _ensure_loaded(self, sync_limit=1000):
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            with self._projection_lock():
                if self._store.count() <= 0 or not self._index_state_matches():
                    self._load_from_db()
                else:
                    self._sync_outbox_locked(sync_limit)
                self._loaded = True

    def _projection_lock(self):
        from services.file_transactions import _file_lock
        database = Path(self.db_path).resolve()
        return _file_lock(database, timeout=120, lock_dir=database.parent / '.clawos-vector-locks')

    def _index_state_matches(self) -> bool:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            row = conn.execute(
                "SELECT schema_version,embedding_fingerprint FROM knowledge_vector_index_state_v2 WHERE index_name=?",
                (self.index_name,),
            ).fetchone()
            return bool(row and int(row[0]) == self.index_schema_version and row[1] == self.embedding_fingerprint)
        except sqlite3.Error:
            return False
        finally:
            if conn is not None:
                conn.close()

    def _load_from_db(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            # Writes arriving while embeddings are computed must remain pending.
            # Reading this before projections is conservative and replay is idempotent.
            has_outbox = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_vector_outbox_v2'").fetchone()
            outbox_watermark = self._max_outbox_id(conn) if has_outbox else 0
            indexed_rows = []
            rows = conn.execute(
                "SELECT id, task, lesson, context, solution, outcome FROM experiences ORDER BY id"
            ).fetchall()
            for row in rows:
                doc_id = f"exp_{row['id']}"
                text = f"{row['task']} {row['lesson']} {row['context']} {row['solution']}"
                indexed_rows.append({"id": doc_id, "text": text, "metadata": {
                    "type": "experience",
                    "outcome": row["outcome"],
                    "task": row["task"][:200],
                }})
            has_v2 = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='knowledge_records_v2'"
            ).fetchone()
            if has_v2:
                rows = conn.execute(
                    "SELECT id FROM knowledge_records_v2 WHERE status='active' AND (valid_until='' OR valid_until>?) ORDER BY id",
                    (datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),),
                ).fetchall()
                for row in rows:
                    projection = self._knowledge_projection(conn, int(row["id"]))
                    if projection:
                        indexed_rows.append(projection)
            else:
                rows = conn.execute(
                    "SELECT id, title, content, category, source FROM knowledge ORDER BY id"
                ).fetchall()
                for row in rows:
                    doc_id = f"kw_{row['id']}"
                    text = f"{row['title']} {row['content']}"
                    indexed_rows.append({"id": doc_id, "text": text, "metadata": {
                        "type": "knowledge", "category": row["category"],
                        "source": row["source"], "title": row["title"],
                    }})
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
                indexed_rows.append({"id": doc_id, "text": text, "metadata": {
                    "type": row["memory_type"],
                    "category": row["category"],
                    "source": row["source"],
                    "title": row["key"],
                    "confidence": row["confidence"],
                }})
            add_many = getattr(self._store, "add_many", None)
            if callable(add_many):
                add_many(indexed_rows)
            else:
                for item in indexed_rows:
                    self._store.add(item["id"], item.get("text", ""), item.get("metadata") or {})
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            conn.execute(
                "UPDATE knowledge_vector_outbox_v2 SET processed_at=?,error='' WHERE processed_at='' AND id<=?",
                (now, outbox_watermark),
            ) if has_v2 else None
            if has_v2:
                conn.execute(
                    """INSERT INTO knowledge_vector_index_state_v2
                       (index_name,schema_version,embedding_fingerprint,last_outbox_id,indexed_records,
                        last_full_sync_at,last_incremental_sync_at,last_error,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(index_name) DO UPDATE SET schema_version=excluded.schema_version,
                        embedding_fingerprint=excluded.embedding_fingerprint,last_outbox_id=excluded.last_outbox_id,
                        indexed_records=excluded.indexed_records,last_full_sync_at=excluded.last_full_sync_at,
                        last_incremental_sync_at=excluded.last_incremental_sync_at,last_error='',updated_at=excluded.updated_at""",
                    (self.index_name, self.index_schema_version, self.embedding_fingerprint,
                     outbox_watermark, self._knowledge_vector_count(), now, now, "", now),
                )
            conn.commit()
            conn.close()
            conn = None
        except sqlite3.Error:
            return
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _max_outbox_id(conn) -> int:
        row = conn.execute("SELECT COALESCE(MAX(id),0) FROM knowledge_vector_outbox_v2").fetchone()
        return int(row[0] if row else 0)

    def _knowledge_vector_count(self) -> int:
        return len([
            row for row in self._store.list_all()
            if (row.get("metadata") or {}).get("type") == "knowledge_v2"
        ])

    def _knowledge_projection(self, conn, knowledge_id: int) -> dict | None:
        row = conn.execute(
            """SELECT k.*,
               (SELECT COUNT(*) FROM knowledge_sources_v2 s WHERE s.knowledge_id=k.id) source_count,
               (SELECT MAX(authority) FROM knowledge_sources_v2 s WHERE s.knowledge_id=k.id) max_authority,
               (SELECT source_ref FROM knowledge_sources_v2 s WHERE s.knowledge_id=k.id ORDER BY authority DESC,id LIMIT 1) source_ref,
               (SELECT locator FROM knowledge_sources_v2 s WHERE s.knowledge_id=k.id ORDER BY authority DESC,id LIMIT 1) locator,
               (SELECT COALESCE(AVG(CASE WHEN outcome IN ('success','accepted','helpful','delivered') THEN 1.0
                    WHEN outcome IN ('failed','rejected','harmful') THEN -1.0 ELSE 0.0 END),0.0)
                    FROM knowledge_usage_v2 u WHERE u.knowledge_id=k.id) utility
               FROM knowledge_records_v2 k WHERE k.id=?""",
            (int(knowledge_id),),
        ).fetchone()
        if not row or row["status"] != "active":
            return None
        valid_until = str(row["valid_until"] or "")
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if valid_until and valid_until <= now:
            return None
        source_ref, locator = str(row["source_ref"] or ""), str(row["locator"] or "")
        from services.document_evidence_policy import source_usable
        if not source_usable(conn, source_ref):
            return None
        citation = source_ref if not locator or "#" in source_ref else f"{source_ref}#{locator}"
        return {
            "id": f"kv2_{row['id']}",
            "text": f"{row['title']}\n{row['statement']}",
            "metadata": {
                "type": "knowledge_v2", "knowledge_id": int(row["id"]),
                "category": row["category"], "title": row["title"], "source": citation,
                "status": row["status"], "owner_id": row["owner_id"], "workspace_id": row["workspace_id"],
                "confidence": float(row["confidence"]), "authority": float(row["max_authority"] or 0.5),
                "utility": float(row["utility"] or 0.0), "source_count": int(row["source_count"] or 0),
                "version": int(row["current_version"]), "valid_until": valid_until,
                "updated_at": row["updated_at"], "schema_version": self.index_schema_version,
                "embedding_fingerprint": self.embedding_fingerprint[:16],
            },
        }

    def _sync_outbox(self, limit: int = 1000) -> dict:
        with self._lock, self._projection_lock():
            return self._sync_outbox_locked(limit)

    def _sync_outbox_locked(self, limit: int) -> dict:
        processed = failed = 0
        last_id = 0
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM knowledge_vector_outbox_v2 WHERE processed_at='' ORDER BY id LIMIT ?", (int(limit),),
            ).fetchall()
            last_id = max((int(event['id']) for event in rows), default=0)
            # Every event for a record projects its current authoritative version.
            # Coalesce only the fetched window; later events remain durable/pending.
            groups = {}
            for event in rows:
                groups.setdefault(int(event['knowledge_id']), []).append(event)

            receipts = []
            def receipt(events, error=''):
                nonlocal processed, failed
                now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
                receipts.extend((now if not error else '', error, int(event['id'])) for event in events)
                if error: failed += len(events)
                else: processed += len(events)

            pending = []
            for knowledge_id, events in groups.items():
                try:
                    projection = self._knowledge_projection(conn, knowledge_id)
                    if events[-1]['operation'] == 'delete' or not projection:
                        self._store.remove(f'kv2_{knowledge_id}')
                        receipt(events)
                    else:
                        pending.append((projection, events))
                except Exception as exc:
                    receipt(events, f'{type(exc).__name__}: {exc}'[:500])
            for offset in range(0, len(pending), 32):
                batch = pending[offset:offset+32]
                events = [event for _, group in batch for event in group]
                try:
                    add_many = getattr(self._store, 'add_many', None)
                    if callable(add_many):
                        add_many([projection for projection, _ in batch])
                    else:
                        for projection, _ in batch:
                            self._store.add(projection['id'], projection['text'], projection['metadata'])
                    receipt(events)
                except Exception as exc:
                    # Partial backend writes are safe to replay by stable ID; none
                    # of this batch's events are acknowledged until it succeeds.
                    receipt(events, f'{type(exc).__name__}: {exc}'[:500])
            # Never hold a SQLite write transaction while running the encoder.
            conn.executemany(
                "UPDATE knowledge_vector_outbox_v2 SET processed_at=?,attempts=attempts+1,error=? WHERE id=?",
                receipts,
            )
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            conn.execute(
                """INSERT INTO knowledge_vector_index_state_v2
                   (index_name,schema_version,embedding_fingerprint,last_outbox_id,indexed_records,
                    last_full_sync_at,last_incremental_sync_at,last_error,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(index_name) DO UPDATE SET
                    last_outbox_id=MAX(last_outbox_id,excluded.last_outbox_id),
                    indexed_records=excluded.indexed_records,
                    last_incremental_sync_at=excluded.last_incremental_sync_at,
                    last_error=excluded.last_error,updated_at=excluded.updated_at""",
                (self.index_name,self.index_schema_version,self.embedding_fingerprint,last_id,
                 self._knowledge_vector_count(),"",now,"" if not failed else f"{failed} projection events failed",now),
            )
            conn.commit()
            conn.close()
            conn = None
        except sqlite3.Error as exc:
            return {"processed": processed, "failed": failed + 1, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            if conn is not None:
                conn.close()
        return {"processed": processed, "failed": failed, "last_outbox_id": last_id}

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

    def _sync_personal_memories(self):
        """Re-embed changed canonical memories without rebuilding knowledge vectors."""
        from contextlib import closing
        with self._lock, closing(sqlite3.connect(self.db_path,timeout=5)) as connection:
            connection.row_factory=sqlite3.Row
            for row in connection.execute('SELECT * FROM memories'):
                doc_id=f"mem_{row['id']}"
                if not row['enabled']:
                    self._store.remove(doc_id)
                    continue
                previous=self._store.get(doc_id)
                text=f"{row['memory_type']} {row['category']} {row['key']} {row['value']}"
                if previous and previous.get('text')==text and (previous.get('metadata') or {}).get('version')==row['current_version']:
                    continue
                self._store.add(doc_id,text,dict(type=row['memory_type'],category=row['category'],source=row['source'],
                    title=row['key'],confidence=row['confidence'],owner_id=row['owner_id'],workspace_id=row['workspace_id'],version=row['current_version']))

    def search(
        self, query: str, top_k: int = 10, min_score: float = 0.15,
        filters: dict | None = None,
    ) -> list[dict]:
        self._ensure_loaded()
        self._sync_outbox()
        self._sync_personal_memories()
        candidates = self._store.search(query, max(top_k*4,20), min_score, filters=filters)
        safe = []
        # The public vector-search API also crosses the review boundary. Never
        # trust a stale collection's active flag/version after a source correction.
        try:
            from contextlib import closing
            with closing(sqlite3.connect(self.db_path, timeout=5)) as connection:
                connection.row_factory = sqlite3.Row
                from services.document_evidence_policy import source_usable
                for item in candidates:
                    meta = item.get("metadata") or {}
                    item_id=str(item.get("id") or "")
                    if item_id.startswith("mem_"):
                        memory=connection.execute("SELECT * FROM memories WHERE id=?",(int(item_id[4:]),)).fetchone()
                        if not memory or not memory['enabled']:
                            continue
                        expected=f"{memory['memory_type']} {memory['category']} {memory['key']} {memory['value']}"
                        if item.get('text') != expected:
                            continue
                        if filters and (filters.get('owner_id',memory['owner_id'])!=memory['owner_id'] or filters.get('workspace_id',memory['workspace_id'])!=memory['workspace_id']):
                            continue
                    elif item_id.startswith("exp_"):
                        memory=connection.execute("SELECT enabled FROM memories WHERE memory_type='experience' AND key=?",('reflection:'+item_id[4:],)).fetchone()
                        if memory and not memory['enabled']:
                            continue
                    if not source_usable(connection, meta.get("source", "")):
                        continue
                    if meta.get("type") == "knowledge_v2":
                        projection = self._knowledge_projection(connection, int(meta.get("knowledge_id") or 0))
                        if not projection or projection["metadata"]["version"] != meta.get("version"):
                            continue
                    safe.append(item)
        except sqlite3.DatabaseError:
            # Without authoritative state, document knowledge must stay withheld.
            safe = [item for item in candidates if not str((item.get("metadata") or {}).get("source", "")).startswith("doc:")
                    and (item.get("metadata") or {}).get("type") != "knowledge_v2"
                    and not str(item.get("id", "")).startswith(("mem_", "exp_"))]
        return safe[:top_k]

    def search_experiences(self, query: str, top_k: int = 5) -> list[dict]:
        return self.search(query, top_k, filters={"type": "experience"})

    def search_knowledge(
        self, query: str, top_k: int = 5, owner_id: str = "default", workspace_id: str = "default",
    ) -> list[dict]:
        return self.search(query, top_k, filters={
            "type": "knowledge_v2", "status": "active",
            "owner_id": owner_id, "workspace_id": workspace_id,
        })

    def refresh(self, limit: int = 1000):
        self._ensure_loaded(sync_limit=0)
        return self._sync_outbox(limit)

    def rebuild(self):
        """Explicit full rebuild. Normal writes use the durable outbox instead."""
        self._store.clear()
        self._loaded = False
        self._ensure_loaded()
        return self.stats()

    def close(self) -> None:
        close = getattr(self._store, "close", None)
        if callable(close):
            close()

    def stats(self) -> dict:
        self._ensure_loaded()
        rows = self._store.list_all()
        index_state = {}
        pending = failed_events = expected_v2 = 0
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM knowledge_vector_index_state_v2 WHERE index_name=?", (self.index_name,),
            ).fetchone()
            index_state = dict(row) if row else {}
            pending = int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_vector_outbox_v2 WHERE processed_at=''"
            ).fetchone()[0])
            failed_events = int(conn.execute(
                "SELECT COUNT(*) FROM knowledge_vector_outbox_v2 WHERE processed_at='' AND error<>''"
            ).fetchone()[0])
            expected_v2 = int(conn.execute(
                """SELECT COUNT(*) FROM knowledge_records_v2
                   WHERE status='active' AND (valid_until='' OR valid_until>?)""",
                (datetime.now(timezone.utc).isoformat(),),
            ).fetchone()[0])
        except sqlite3.Error:
            pass
        finally:
            if conn is not None:
                conn.close()
        return {
            "provider": self.provider,
            "requested_provider": self.requested_provider,
            "fallback_reason": self.fallback_reason,
            "embedding_provider": self.embedding_provider,
            "embedding_model_path": self.embedding_model_path if self.embedding_provider not in {"hash", "local_hash", "ngram", ""} else "",
            "embedding_dim": self.dim,
            "index_schema_version": self.index_schema_version,
            "index_name": self.index_name,
            "embedding_fingerprint": self.embedding_fingerprint,
            "persist_dir": self.persist_dir if self.provider == "chroma" else "",
            "vector_count": self._store.count(),
            "experiences": len([r for r in rows if r.get("metadata", {}).get("type") == "experience"]),
            "knowledge": len([r for r in rows if r.get("metadata", {}).get("type") in {"knowledge", "knowledge_v2"}]),
            "knowledge_v2": len([r for r in rows if r.get("metadata", {}).get("type") == "knowledge_v2"]),
            "expected_knowledge_v2": expected_v2,
            "memories": len([r for r in rows if r.get("id", "").startswith("mem_")]),
            "outbox_pending": pending,
            "outbox_failed": failed_events,
            "last_full_sync_at": index_state.get("last_full_sync_at", ""),
            "last_incremental_sync_at": index_state.get("last_incremental_sync_at", ""),
            "last_index_error": index_state.get("last_error", ""),
            "consistent": (
                pending == 0
                and failed_events == 0
                and len([r for r in rows if r.get("metadata", {}).get("type") == "knowledge_v2"]) == expected_v2
            ),
        }
