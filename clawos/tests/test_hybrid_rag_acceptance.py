import tempfile
import unittest
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class HybridRagAcceptanceTests(unittest.TestCase):
    def test_parse_json_object_handles_fenced_json(self):
        from scripts.hybrid_rag_acceptance import parse_json_object

        parsed = parse_json_object('```json\n{"ok": true, "ids": ["kw_1"]}\n```')

        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["ids"], ["kw_1"])

    def test_normalize_id_supports_raw_and_prefixed_ids(self):
        from scripts.hybrid_rag_acceptance import normalize_id

        self.assertEqual(normalize_id("kw_42"), {"kw_42", "42"})
        self.assertEqual(normalize_id("42"), {"42", "kw_42"})

    def test_model_file_report_marks_embedding_pooling_requirement(self):
        from scripts.hybrid_rag_acceptance import model_file_report

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "modules.json", "config_sentence_transformers.json"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            incomplete = model_file_report(root, "embedding")
            (root / "1_Pooling").mkdir()
            (root / "1_Pooling" / "config.json").write_text("{}", encoding="utf-8")
            complete = model_file_report(root, "embedding")

        self.assertFalse(incomplete["complete"])
        self.assertTrue(complete["complete"])

    def test_aggregate_reports_full_chain_metrics(self):
        from scripts.hybrid_rag_acceptance import aggregate

        metrics = aggregate([
            {
                "vector_rank": 2,
                "rerank_rank": 1,
                "citation_hit": True,
                "judge": {"grounded": True, "cites_expected": True},
                "latency_ms": 120,
            },
            {
                "vector_rank": 1,
                "rerank_rank": 2,
                "citation_hit": True,
                "judge": {"grounded": True, "cites_expected": False},
                "latency_ms": 240,
            },
        ], recall_k=30, top_k=5)

        self.assertEqual(metrics["vector_recall_at_30"], 1.0)
        self.assertEqual(metrics["rerank_recall_at_5"], 1.0)
        self.assertEqual(metrics["citation_hit_rate"], 1.0)
        self.assertEqual(metrics["judge_grounded_rate"], 1.0)
        self.assertEqual(metrics["judge_expected_citation_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
