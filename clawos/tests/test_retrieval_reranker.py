import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class RetrievalRerankerTests(unittest.TestCase):
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
