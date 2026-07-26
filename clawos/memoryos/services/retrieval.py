"""RetrievalService - multi-strategy retrieval with BM25 and re-ranking."""
import os, re, math, threading
from pathlib import Path
from collections import Counter

class BM25Index:
    """Pure-Python BM25 text index for keyword search."""

    def __init__(self, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = []
        self.term_freqs = []
        self.doc_lengths = []
        self.avgdl = 0
        self.df = Counter()
        self.N = 0

    def add(self, doc_id, text):
        tokens = self._tokenize(text)
        tf = Counter(tokens)
        self.docs.append((doc_id, text))
        self.term_freqs.append(tf)
        self.doc_lengths.append(len(tokens))
        for term in tf:
            self.df[term] += 1
        self.N += 1
        self.avgdl = sum(self.doc_lengths) / self.N if self.N > 0 else 1

    def search(self, query, top_k=10):
        if self.N == 0:
            return []
        tokens = self._tokenize(query)
        scores = []
        for i, tf in enumerate(self.term_freqs):
            score = 0.0
            for t in tokens:
                if t not in self.df:
                    continue
                idf = math.log((self.N - self.df[t] + 0.5) / (self.df[t] + 0.5) + 1)
                f = tf.get(t, 0)
                score += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * self.doc_lengths[i] / self.avgdl))
            if score > 0:
                scores.append((i, score, self.docs[i][0], self.docs[i][1]))
        scores.sort(key=lambda x: x[1], reverse=True)
        return [{"doc_id": s[2], "text": s[3][:300], "score": s[1]} for s in scores[:top_k]]

    def _tokenize(self, text):
        return [t.lower() for t in re.findall(r"[\w\u4e00-\u9fff]{2,}", text)]


def _default_reranker_model_path():
    return str((Path(__file__).resolve().parents[3] / "tools" / "models" / "qwen3-reranker-0.6b").resolve())


class CrossEncoderReranker:
    """Lazy local sentence-transformers CrossEncoder reranker."""

    def __init__(self, model_path="", provider="qwen3", batch_size=8, device=""):
        self.provider = str(provider or "qwen3").strip().lower()
        self.model_path = str(Path(model_path or _default_reranker_model_path()).expanduser().resolve())
        self.batch_size = max(1, int(batch_size or 8))
        self.device = str(
            device
            or os.environ.get("CLAWOS_RERANKER_DEVICE")
            or os.environ.get("RERANKER_DEVICE")
            or "cpu"
        ).strip()
        self._model = None
        self._lock = threading.RLock()

    @property
    def enabled(self):
        return self.provider in {"qwen3", "qwen3-reranker", "cross_encoder", "cross-encoder", "local"}

    def _load(self):
        if not self.enabled:
            raise RuntimeError(f"Unsupported reranker provider: {self.provider}")
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import CrossEncoder  # type: ignore
                except Exception as exc:
                    raise RuntimeError(f"sentence-transformers is not installed: {exc}") from exc
                if not Path(self.model_path).exists():
                    raise RuntimeError(f"reranker model path not found: {self.model_path}")
                self._model = CrossEncoder(self.model_path, device=self.device, local_files_only=True)
            return self._model

    def rerank(self, query, candidates, top_k=5):
        if not candidates:
            return []
        model = self._load()
        pairs = []
        for item in candidates:
            citation = item.get("citation") or item.get("source_ref") or item.get("metadata", {}).get("source", "")
            candidate_text = "\n".join([
                f"Title: {item.get('title', '')}",
                f"Citation: {citation}",
                str(item.get("content") or item.get("text") or ""),
            ]).strip()
            pairs.append((query or "", candidate_text))
        scores = model.predict(pairs, batch_size=self.batch_size)
        ranked = []
        for score, item in zip(scores, candidates):
            row = dict(item)
            row["rerank_score"] = round(float(score), 4)
            row["strategy"] = "rerank"
            ranked.append(row)
        ranked.sort(key=lambda item: item.get("rerank_score", float("-inf")), reverse=True)
        return ranked[:max(1, int(top_k or 5))]


class RetrievalService:
    """Multi-strategy retrieval: keyword (SQLite FTS) + BM25 + re-rank."""

    def __init__(self, store, vector_store=None, reranker=None):
        self._store = store
        self._vector_store = vector_store
        self._reranker = reranker or self._build_env_reranker()
        self._bm25 = BM25Index()
        self._bm25_populated = False

    def set_vector_store(self, vector_store):
        self._vector_store = vector_store

    def _build_env_reranker(self):
        provider = (
            os.environ.get("CLAWOS_RERANKER_PROVIDER")
            or os.environ.get("RERANKER_PROVIDER")
            or "none"
        ).strip().lower()
        if provider in {"", "none", "off", "false", "0"}:
            return None
        model_path = os.environ.get("CLAWOS_RERANKER_MODEL_PATH") or os.environ.get("RERANKER_MODEL_PATH") or ""
        batch_size = int(os.environ.get("CLAWOS_RERANKER_BATCH_SIZE") or os.environ.get("RERANKER_BATCH_SIZE") or 8)
        return CrossEncoderReranker(model_path=model_path, provider=provider, batch_size=batch_size)

    def _ensure_bm25(self):
        self._bm25 = BM25Index()
        items = self._store.list_knowledge()
        for item in items:
            self._bm25.add(item.get("id", ""), item.get("title", "") + " " + item.get("content", ""))
        exps = self._store.get_recent_experiences(50)
        for exp in exps:
            self._bm25.add(f"exp_{exp.get('id','')}", exp.get("task", "") + " " + exp.get("lesson", ""))
        memories = self._store.list_memories(include_disabled=False, limit=500)
        for memory in memories:
            self._bm25.add(
                f"mem_{memory.get('id', '')}",
                " ".join([
                    memory.get("memory_type", ""),
                    memory.get("category", ""),
                    memory.get("key", ""),
                    memory.get("value", ""),
                ]),
            )
        self._bm25_populated = True

    def retrieve(self, query, top_k=10, strategy="hybrid"):
        results = []

        # Keyword search (SQLite)
        kw = self._store.search_knowledge(query, limit=top_k)
        for r in kw:
            results.append({"source": "knowledge", "id": r.get("id"), "title": r.get("title"),
                          "content": r.get("content", "")[:300], "score": r.get("confidence", 0.5), "strategy": "keyword"})

        # BM25 search
        self._ensure_bm25()
        bm = self._bm25.search(query, top_k)
        for r in bm:
            results.append({"source": "bm25", "id": r["doc_id"], "title": "", "content": r["text"],
                          "score": r["score"], "strategy": "bm25"})

        # Vector search (semantic)
        if self._vector_store:
            vs = self._vector_store.search(query, top_k)
            for r in vs:
                results.append({"source": "vector", "id": r["id"], "title": r.get("metadata", {}).get("title", ""),
                              "content": r["text"], "score": r["score"], "strategy": "vector"})

        # Re-rank: deduplicate and normalize scores
        seen = set()
        ranked = []
        for r in sorted(results, key=lambda x: x["score"], reverse=True):
            key = str(r.get("id")) + r.get("title", "")[:50]
            if key not in seen:
                seen.add(key)
                ranked.append(r)
        return ranked[:top_k]

    def semantic_rerank(self, query, recall_k=30, top_k=5, min_score=0.0):
        """Run vector recall first, then local cross-encoder reranking."""
        if not self._vector_store:
            return []
        vector_hits = self._vector_store.search(query, top_k=max(recall_k, top_k), min_score=min_score)
        candidates = [
            {
                "source": "vector",
                "id": item.get("id"),
                "title": item.get("metadata", {}).get("title", ""),
                "content": item.get("text", ""),
                "citation": item.get("metadata", {}).get("source", ""),
                "score": item.get("score", 0),
                "strategy": "vector",
                "metadata": item.get("metadata", {}),
            }
            for item in vector_hits
        ]
        if not self._reranker:
            return candidates[:top_k]
        return self._reranker.rerank(query, candidates, top_k=top_k)

    def retrieve_for_context(self, query, max_tokens=1500, policy=None):
        """Retrieve and format results as context string for LLM."""
        policy = dict(policy or {})
        top_k = max(1, min(int(policy.get("top_k") or 5), 50))
        recall_k = max(top_k, min(int(
            policy.get("recall_top_k") or policy.get("top_k") or 30
        ), 200))
        rerank_top_k = max(1, min(int(policy.get("rerank_top_k") or top_k), 50))
        results = (
            self.semantic_rerank(query, recall_k=recall_k, top_k=rerank_top_k)
            if self._reranker
            else self.retrieve(query, top_k=top_k)
        )
        if not results:
            return ""
        parts = ["Relevant knowledge from memory:"]
        for r in results[:top_k]:
            citation = r.get("citation") or (r.get("metadata") or {}).get("source", "")
            prefix = f"[{citation}] " if policy.get("citation_aware") and citation else ""
            parts.append(
                f"  [{r['source']}] {prefix}{r.get('title','')} {r.get('content','')[:200]}"
            )
        return "\n".join(parts)
