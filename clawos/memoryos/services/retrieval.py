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
        # Chinese has no word separators: whole-sentence tokens never match a question.
        tokens = re.findall(r"[a-z0-9_]+", str(text).lower())
        for run in re.findall(r"[\u4e00-\u9fff]+", str(text)):
            tokens.extend(run[i:i+2] for i in range(len(run)-1))
            if len(run) == 1:
                tokens.append(run)
        return tokens


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

    def __init__(self, store, vector_store=None, reranker=None, *, allow_env_reranker=True):
        self._store = store
        self._vector_store = vector_store
        self._reranker = reranker or (self._build_env_reranker() if allow_env_reranker else None)
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
            if memory.get("owner_id", "default")!="default" or memory.get("workspace_id", "default")!="default":
                continue
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

    @staticmethod
    def _candidate_key(item):
        metadata = item.get("metadata") or {}
        knowledge_id = item.get("knowledge_id") or metadata.get("knowledge_id")
        if knowledge_id:
            return f"knowledge:{knowledge_id}"
        return f"{item.get('source')}:{item.get('id')}"

    def retrieve(
        self, query, top_k=10, strategy="hybrid",
        owner_id="default", workspace_id="default", recall_k=None,
    ):
        recall_k = max(int(recall_k or top_k), int(top_k))
        lanes = []
        v2_legacy_ids = set()

        # Evidence-first records are filtered for lifecycle state and carry
        # source-level citations. Legacy retrieval remains as a compatibility lane.
        try:
            evidence_lane = []
            for item in self._store.search_knowledge_v2(
                query, limit=recall_k, owner_id=owner_id, workspace_id=workspace_id,
            ):
                if item.get("legacy_knowledge_id"):
                    v2_legacy_ids.add(int(item["legacy_knowledge_id"]))
                sources = item.get("sources") or []
                evidence_lane.append({
                    "source": "knowledge_v2", "id": f"kv2_{item.get('id')}",
                    "knowledge_id": item.get("id"), "title": item.get("title", ""),
                    "content": item.get("statement", "")[:1200],
                    "citation": sources[0].get("citation", "") if sources else "",
                    "score": item.get("retrieval_score", item.get("confidence", 0.5)),
                    "strategy": "evidence_knowledge", "metadata": {
                        "status": item.get("status"), "source_count": item.get("source_count", len(sources)),
                    },
                })
            if evidence_lane:
                lanes.append(("evidence", 1.0, evidence_lane))
        except (AttributeError, ImportError, OSError, ValueError):
            pass

        # Keyword search (SQLite)
        legacy_scope = owner_id == "default" and workspace_id == "default"
        kw = self._store.search_knowledge(query, limit=recall_k) if legacy_scope else []
        keyword_lane = []
        for r in kw:
            if int(r.get("id") or 0) in v2_legacy_ids:
                continue
            keyword_lane.append({"source": "knowledge", "id": r.get("id"), "title": r.get("title"),
                                 "content": r.get("content", "")[:300], "score": r.get("confidence", 0.5), "strategy": "keyword"})
        if keyword_lane:
            lanes.append(("keyword", 0.55, keyword_lane))

        # BM25 search
        if legacy_scope:
            self._ensure_bm25()
        bm = self._bm25.search(query, recall_k) if legacy_scope else []
        bm25_lane = []
        for r in bm:
            try:
                if int(r["doc_id"]) in v2_legacy_ids:
                    continue
            except (TypeError, ValueError):
                pass
            bm25_lane.append({"source": "bm25", "id": r["doc_id"], "title": "", "content": r["text"],
                              "score": r["score"], "strategy": "bm25"})
        if bm25_lane:
            lanes.append(("bm25", 0.75, bm25_lane))

        # Vector search (semantic)
        if self._vector_store:
            filters = {"type": "knowledge_v2", "status": "active", "owner_id": owner_id, "workspace_id": workspace_id}
            try:
                vs = self._vector_store.search(query, recall_k, filters=filters)
            except TypeError:  # Backward-compatible test and external adapters.
                vs = self._vector_store.search(query, recall_k)
            vector_lane = []
            for r in vs:
                metadata = r.get("metadata", {})
                if metadata.get("owner_id", "default") != owner_id or metadata.get("workspace_id", "default") != workspace_id:
                    continue
                vector_lane.append({
                    "source": "vector", "id": r["id"], "knowledge_id": metadata.get("knowledge_id"),
                    "title": metadata.get("title", ""), "content": r["text"],
                    "citation": metadata.get("source", ""), "score": r["score"],
                    "strategy": "vector", "metadata": metadata,
                })
            if vector_lane:
                lanes.append(("vector", 1.0, vector_lane))

        # Reciprocal-rank fusion compares ranks instead of incompatible raw
        # BM25/cosine/confidence scales. Evidence rows win representation when
        # the same stable knowledge ID appears in multiple lanes.
        fused = {}
        for lane_name, weight, lane in lanes:
            for rank, item in enumerate(lane, 1):
                citation = item.get("citation") or (item.get("metadata") or {}).get("source", "")
                if hasattr(self._store, "document_source_usable") and not self._store.document_source_usable(citation, item.get("knowledge_id"), (item.get("metadata") or {}).get("version")):
                    continue
                key = self._candidate_key(item)
                entry = fused.setdefault(key, {
                    "item": dict(item), "fusion_score": 0.0, "channels": [], "lane_ranks": {},
                })
                entry["fusion_score"] += float(weight) / (60.0 + rank)
                entry["channels"].append(lane_name)
                entry["lane_ranks"][lane_name] = rank
                if item.get("source") == "knowledge_v2":
                    entry["item"] = dict(item)
        ranked = []
        for entry in fused.values():
            item = entry["item"]
            item["raw_score"] = item.get("score", 0.0)
            item["score"] = round(entry["fusion_score"], 6)
            item["fusion_score"] = item["score"]
            item["channels"] = sorted(set(entry["channels"]))
            item["lane_ranks"] = entry["lane_ranks"]
            item["strategy"] = "hybrid_rrf"
            ranked.append(item)
        ranked.sort(key=lambda item: item["fusion_score"], reverse=True)
        return ranked[:top_k]

    def semantic_rerank(
        self, query, recall_k=30, top_k=5, min_score=0.0,
        owner_id="default", workspace_id="default",
    ):
        """Run vector recall first, then local cross-encoder reranking."""
        if not self._vector_store:
            return []
        filters = {"type": "knowledge_v2", "status": "active", "owner_id": owner_id, "workspace_id": workspace_id}
        try:
            vector_hits = self._vector_store.search(
                query, top_k=max(recall_k, top_k), min_score=min_score, filters=filters,
            )
        except TypeError:
            vector_hits = self._vector_store.search(query, top_k=max(recall_k, top_k), min_score=min_score)
        candidates = [
            {
                "source": "vector",
                "id": item.get("id"),
                "knowledge_id": item.get("metadata", {}).get("knowledge_id"),
                "title": item.get("metadata", {}).get("title", ""),
                "content": item.get("text", ""),
                "citation": item.get("metadata", {}).get("source", ""),
                "score": item.get("score", 0),
                "strategy": "vector",
                "metadata": item.get("metadata", {}),
            }
            for item in vector_hits
            if not hasattr(self._store, "document_source_usable") or self._store.document_source_usable(item.get("metadata", {}).get("source", ""), item.get("metadata", {}).get("knowledge_id"), item.get("metadata", {}).get("version"))
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
        owner_id = str(policy.get("owner_id") or "default")
        workspace_id = str(policy.get("workspace_id") or "default")
        candidates = self.retrieve(
            query, top_k=recall_k if self._reranker else top_k,
            owner_id=owner_id, workspace_id=workspace_id, recall_k=recall_k,
        )
        results = self._reranker.rerank(query, candidates, top_k=rerank_top_k) if self._reranker else candidates
        if not results:
            return ""
        top = results[0]
        channels = set(top.get("channels") or [])
        evidence_sufficient = (
            len(channels) >= 2
            or (top.get("source") == "knowledge_v2" and float(top.get("raw_score") or 0) >= 0.55)
            or (top.get("source") == "vector" and float(top.get("raw_score") or top.get("score") or 0) >= 0.72)
            or (self._reranker is not None and float(top.get("rerank_score") or top.get("score") or 0) >= 0.6)
        )
        if policy.get("require_sufficient_evidence", True) and not evidence_sufficient:
            return ""
        knowledge_ids = [int(item["knowledge_id"]) for item in results if item.get("knowledge_id")]
        if knowledge_ids and hasattr(self._store, "record_knowledge_usage"):
            self._store.record_knowledge_usage(
                knowledge_ids,
                query=query,
                session_id=str(policy.get("session_id") or ""),
                task_id=str(policy.get("task_id") or ""),
                usage_type="context_injected",
                outcome="pending",
            )
        parts = ["Relevant knowledge from memory:"]
        used_chars = len(parts[0])
        max_chars = max(400, int(max_tokens) * 4)
        for r in results[:top_k]:
            citation = r.get("citation") or (r.get("metadata") or {}).get("source", "")
            prefix = f"[{citation}] " if policy.get("citation_aware") and citation else ""
            line = f"  [{r['source']}] {prefix}{r.get('title','')} {r.get('content','')[:200]}"
            if len(parts) > 1 and used_chars + len(line) > max_chars:
                break
            parts.append(line)
            used_chars += len(line)
        return "\n".join(parts)
