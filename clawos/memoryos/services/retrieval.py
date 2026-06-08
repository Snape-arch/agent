"""RetrievalService - multi-strategy retrieval with BM25 and re-ranking."""
import re, math
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


class RetrievalService:
    """Multi-strategy retrieval: keyword (SQLite FTS) + BM25 + re-rank."""

    def __init__(self, store, vector_store=None):
        self._store = store
        self._vector_store = vector_store
        self._bm25 = BM25Index()
        self._bm25_populated = False

    def set_vector_store(self, vector_store):
        self._vector_store = vector_store

    def _ensure_bm25(self):
        if self._bm25_populated:
            return
        items = self._store.list_knowledge()
        for item in items:
            self._bm25.add(item.get("id", ""), item.get("title", "") + " " + item.get("content", ""))
        exps = self._store.get_recent_experiences(50)
        for exp in exps:
            self._bm25.add(f"exp_{exp.get('id','')}", exp.get("task", "") + " " + exp.get("lesson", ""))
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
                results.append({"source": "vector", "id": r["id"], "title": "",
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

    def retrieve_for_context(self, query, max_tokens=1500):
        """Retrieve and format results as context string for LLM."""
        results = self.retrieve(query, top_k=5)
        if not results:
            return ""
        parts = ["Relevant knowledge from memory:"]
        for r in results[:3]:
            parts.append(f"  [{r['source']}] {r.get('title','')} {r.get('content','')[:200]}")
        return "\n".join(parts)
