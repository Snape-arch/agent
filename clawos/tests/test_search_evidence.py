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
        self.assertEqual(first["provider_health"]["providers"][0]["provider"], "mock")
        self.assertEqual(first["provider_health"]["providers"][0]["status"], "degraded")
        self.assertEqual(calls["mock"], 2)
        self.assertTrue(any(not attempt["ok"] for attempt in first["attempts"]))

    def test_provider_health_summary_and_live_acceptance_mock(self):
        from scripts.search_live_acceptance import run_live_suite
        from services.search_evidence import provider_health_summary

        health = provider_health_summary(
            [
                {"provider": "bing", "ok": True, "latency_ms": 100, "error_type": ""},
                {"provider": "duckduckgo", "ok": False, "latency_ms": 500, "error_type": "timeout"},
            ],
            ["bing", "duckduckgo", "tavily"],
        )

        with tempfile.TemporaryDirectory() as td:
            report = run_live_suite(Path(td), providers=["mock"], limit_cases=8, offline_mock=True)
            self.assertTrue(Path(report["report_path"]).exists())

        self.assertEqual(health["healthy_count"], 1)
        self.assertEqual(health["down_count"], 1)
        self.assertEqual(health["untested_count"], 1)
        self.assertEqual(report["mode"], "offline_mock")
        self.assertEqual(report["case_count"], 8)
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["citation_hit_rate"], 1.0)
        self.assertIn("provider_health", report)
        self.assertIn("by_scenario", report)

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
            tool_runner.input_data = {"offline_mock": True, "limit_cases": 6}
            tool_runner.handlers["web_search_live_benchmark"]()
        live_report = json.loads(output.getvalue())

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
        self.assertGreaterEqual(report["case_count"], 30)
        self.assertGreaterEqual(report["coverage"]["js_render_cases"], 5)
        self.assertTrue({
            "official_docs",
            "news_freshness",
            "papers",
            "policy",
            "product",
            "chinese_web",
            "js_page",
        }.issubset(set(report["by_category"].keys())))
        self.assertEqual(report["by_category"]["js_page"]["failed_count"], 0)
        self.assertIn("artifact", report)
        self.assertEqual(report["run_record"]["run_type"], "web_evidence")
        self.assertEqual(citation["status"], "pass")
        self.assertEqual(live_report["mode"], "offline_mock")
        self.assertEqual(live_report["failed_count"], 0)
        self.assertGreaterEqual(live_report["case_count"], 6)


if __name__ == "__main__":
    unittest.main()
