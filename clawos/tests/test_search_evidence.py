import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class SearchEvidenceEngineTests(unittest.TestCase):
    def test_ranking_cache_retry_and_quality_summary(self):
        from services.search_evidence import SearchEvidenceEngine

        with tempfile.TemporaryDirectory() as td:
            engine = SearchEvidenceEngine(Path(td) / "cache.json", Path(td) / "rate.json")
            calls = {"mock": 0}

            def mock_provider(query, limit):
                calls["mock"] += 1
                if calls["mock"] == 1:
                    raise RuntimeError("temporary provider failure")
                return [
                    {
                        "title": "Official Python datetime docs",
                        "url": "https://docs.python.org/3/library/datetime.html",
                        "snippet": "Official Python documentation explains timezone aware datetime objects.",
                        "source": "mock",
                        "rank": 2,
                        "published_at": "2026-01-01",
                    },
                    {
                        "title": "Personal date blog",
                        "url": "https://example.com/date-blog",
                        "snippet": "Short personal note about dates.",
                        "source": "mock",
                        "rank": 1,
                        "published_at": "2018-01-01",
                    },
                ], ""

            first = engine.search(
                "Python datetime timezone official documentation",
                5,
                ["mock"],
                {"mock": mock_provider},
                retries=2,
            )
            second = engine.search(
                "Python datetime timezone official documentation",
                5,
                ["mock"],
                {"mock": mock_provider},
                retries=2,
            )

        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["results"][0]["domain"], "docs.python.org")
        self.assertEqual(first["results"][0]["credibility"], "high")
        self.assertGreaterEqual(first["quality_summary"]["high_credibility"], 1)
        self.assertEqual(calls["mock"], 2)
        self.assertTrue(any(not attempt["ok"] for attempt in first["attempts"]))

    def test_rate_limit_and_citation_consistency_gate(self):
        from services.search_evidence import FileRateLimiter, citation_consistency

        with tempfile.TemporaryDirectory() as td:
            limiter = FileRateLimiter(Path(td) / "rate.json", max_per_minute=1)
            first = limiter.check("web_search")
            second = limiter.check("web_search")

        check = citation_consistency(
            "Retrieval augmented generation requires citations and evidence grounding. Unsupported claim about unicorn metrics.",
            [{
                "title": "RAG citation paper",
                "url": "https://arxiv.org/abs/2401.00001",
                "snippet": "Retrieval augmented generation requires citations and evidence grounding.",
            }],
        )

        self.assertTrue(first["allowed"])
        self.assertFalse(second["allowed"])
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["anti_hallucination_gate"]["status"], "revision_required")
        self.assertGreaterEqual(check["unsupported_count"], 1)

    def test_tool_runner_search_benchmark_and_citation_tool(self):
        from scripts import tool_runner

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            tool_runner.input_data = {}
            tool_runner.handlers["web_search_benchmark"]()
        report = json.loads(output.getvalue())

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            tool_runner.input_data = {
                "answer": "Python documentation explains timezone aware datetime objects.",
                "sources": [{
                    "title": "Official Python datetime docs",
                    "url": "https://docs.python.org/3/library/datetime.html",
                    "snippet": "Official Python documentation explains timezone aware datetime objects.",
                }],
            }
            tool_runner.handlers["web_citation_check"]()
        citation = json.loads(output.getvalue())

        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["pass_rate"], 1.0)
        self.assertIn("artifact", report)
        self.assertEqual(report["run_record"]["run_type"], "web_evidence")
        self.assertEqual(citation["status"], "pass")


if __name__ == "__main__":
    unittest.main()
