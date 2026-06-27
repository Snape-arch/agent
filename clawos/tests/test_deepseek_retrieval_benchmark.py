import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class DeepSeekRetrievalBenchmarkTests(unittest.TestCase):
    def test_parse_json_object_handles_fenced_json(self):
        from scripts.deepseek_retrieval_benchmark import parse_json_object

        parsed = parse_json_object('```json\n{"selected_ids":["kw_1"],"confidence":0.9}\n```')

        self.assertEqual(parsed["selected_ids"], ["kw_1"])
        self.assertEqual(parsed["confidence"], 0.9)

    def test_normalize_id_maps_keyword_and_vector_ids(self):
        from scripts.deepseek_retrieval_benchmark import normalize_id

        self.assertEqual(normalize_id("kw_42"), {"kw_42", "42"})
        self.assertEqual(normalize_id("42"), {"42", "kw_42"})

    def test_retrieval_metrics_scores_recall_mrr_and_judge_hits(self):
        from scripts.deepseek_retrieval_benchmark import retrieval_metrics

        metrics = retrieval_metrics([
            {
                "expected_ids": ["kw_2"],
                "retrieved_ids": ["kw_1", "2", "kw_3"],
                "judge": {"selected_ids": ["kw_2"]},
            },
            {
                "expected_ids": ["kw_5"],
                "retrieved_ids": ["kw_5", "kw_4"],
                "judge": {"selected_ids": ["5"]},
            },
        ], top_k=5)

        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["hit_rate"], 1.0)
        self.assertEqual(metrics["judge_hit_rate"], 1.0)
        self.assertEqual(metrics["mrr"], 0.75)


if __name__ == "__main__":
    unittest.main()
