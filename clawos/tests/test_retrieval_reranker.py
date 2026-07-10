import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RetrievalRerankerTests(unittest.TestCase):
    def test_local_retrieval_models_default_to_cpu_with_env_override(self):
        from memoryos.services.retrieval import CrossEncoderReranker
        from memoryos.services.vector_store import SentenceTransformerEncoder

        old_embedding = os.environ.pop("CLAWOS_EMBEDDING_DEVICE", None)
        old_reranker = os.environ.pop("CLAWOS_RERANKER_DEVICE", None)
        try:
            self.assertEqual(SentenceTransformerEncoder("embedding").device, "cpu")
            self.assertEqual(CrossEncoderReranker("reranker").device, "cpu")
            os.environ["CLAWOS_EMBEDDING_DEVICE"] = "cuda:0"
            os.environ["CLAWOS_RERANKER_DEVICE"] = "cuda:1"
            self.assertEqual(SentenceTransformerEncoder("embedding").device, "cuda:0")
            self.assertEqual(CrossEncoderReranker("reranker").device, "cuda:1")
        finally:
            if old_embedding is None:
                os.environ.pop("CLAWOS_EMBEDDING_DEVICE", None)
            else:
                os.environ["CLAWOS_EMBEDDING_DEVICE"] = old_embedding
            if old_reranker is None:
                os.environ.pop("CLAWOS_RERANKER_DEVICE", None)
            else:
                os.environ["CLAWOS_RERANKER_DEVICE"] = old_reranker

    def test_semantic_rerank_uses_vector_recall_then_reranks_top_k(self):
        from memoryos.services.retrieval import RetrievalService

        class FakeVector:
            def __init__(self):
                self.calls = []

            def search(self, query, top_k=10, min_score=0.15):
                self.calls.append({"query": query, "top_k": top_k, "min_score": min_score})
                return [
                    {"id": f"kw_{i}", "text": f"candidate {i}", "score": 1 / i, "metadata": {"title": f"Doc {i}"}}
                    for i in range(1, 31)
                ]

        class FakeReranker:
            def __init__(self):
                self.seen = 0

            def rerank(self, query, candidates, top_k=5):
                self.seen = len(candidates)
                ranked = list(reversed(candidates))
                return ranked[:top_k]

        vector = FakeVector()
        reranker = FakeReranker()
        service = RetrievalService(store=None, vector_store=vector, reranker=reranker)

        results = service.semantic_rerank("query", recall_k=30, top_k=5, min_score=0.0)

        self.assertEqual(vector.calls[0]["top_k"], 30)
        self.assertEqual(vector.calls[0]["min_score"], 0.0)
        self.assertEqual(reranker.seen, 30)
        self.assertEqual(len(results), 5)
        self.assertEqual(results[0]["id"], "kw_30")


if __name__ == "__main__":
    unittest.main()
