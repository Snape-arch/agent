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
    def test_evidence_policy_covers_stable_fresh_local_high_risk_and_experience(self):
        from services.search_evidence import decide_search_need

        stable = decide_search_need("解释一下什么是强化学习")
        fresh = decide_search_need("当前 TypeScript 最新稳定版本是什么")
        sourced = decide_search_need("请联网查证这个结论并附上来源")
        local = decide_search_need(
            "分析这个项目的模块边界", local_context_sufficient=True
        )
        high_risk = decide_search_need("这份合同是否合规，有什么法律风险")
        attached_high_risk = decide_search_need(
            "判断附件合同当前是否合规", has_attachments=True
        )
        experience = decide_search_need("对比这些框架的真实使用经验和踩坑")

        self.assertFalse(stable["should_search"])
        self.assertTrue(fresh["should_search"])
        self.assertTrue(fresh["coverage"]["require_fresh"])
        self.assertTrue(sourced["should_search"])
        self.assertFalse(local["should_search"])
        self.assertTrue(high_risk["should_search"])
        self.assertTrue(high_risk["coverage"]["require_authoritative"])
        self.assertTrue(attached_high_risk["should_search"])
        self.assertTrue(experience["should_search"])
        self.assertTrue(experience["coverage"]["require_community"])

    def test_evidence_sufficiency_stops_only_after_required_lanes_exist(self):
        from services.search_evidence import decide_search_need, evidence_sufficiency

        decision = decide_search_need("对比 Python Web 框架的真实使用经验和踩坑")
        official = {
            "domain": "docs.python.org", "source_type": "official",
            "credibility": "high", "scores": {"relevance": 0.8, "freshness": 0.5},
        }
        independent = {
            "domain": "example.org", "source_type": "other",
            "credibility": "medium", "scores": {"relevance": 0.6, "freshness": 0.5},
        }
        incomplete = evidence_sufficiency([official, independent], decision)
        complete = evidence_sufficiency([
            official, independent,
            {
                "domain": "zhihu.com", "source_type": "community",
                "credibility": "medium", "scores": {"relevance": 0.7, "freshness": 0.5},
            },
        ], decision)

        self.assertFalse(incomplete["enough_to_stop_search"])
        self.assertIn("community_experience", incomplete["missing"])
        self.assertTrue(complete["enough_to_stop_search"])
        self.assertEqual(complete["reason"], "evidence_coverage_met")

    def test_query_plan_uses_policy_instead_of_always_expanding(self):
        from services.search_evidence import build_query_plan, decide_search_need

        stable = decide_search_need("解释 Python 装饰器")
        experience = decide_search_need("Python 异步编程有哪些实践经验和踩坑")
        fresh = decide_search_need("Python 当前最新版本")

        self.assertEqual(len(build_query_plan("解释 Python 装饰器", breadth="quick", decision=stable)), 1)
        self.assertTrue(any(
            item["facet"] == "community"
            for item in build_query_plan("Python 异步编程有哪些实践经验和踩坑", decision=experience)
        ))
        self.assertTrue(any(
            item["facet"] == "fresh_primary"
            for item in build_query_plan("Python 当前最新版本", decision=fresh)
        ))

    def test_search_need_is_conservative_and_respects_explicit_requests(self):
        from services.search_evidence import decide_search_need

        stable = decide_search_need("解释一下什么是强化学习", mode="auto")
        attached = decide_search_need("总结这篇论文", mode="auto", has_attachments=True)
        latest = decide_search_need("搜索一下最近的强化学习论文", mode="off")
        forced = decide_search_need("解释强化学习", mode="force")

        self.assertFalse(stable["should_search"])
        self.assertFalse(attached["should_search"])
        self.assertTrue(latest["should_search"])
        self.assertEqual(latest["reason"], "explicit_user_request")
        self.assertTrue(forced["should_search"])

    def test_chinese_query_plan_and_diversity_include_community_sources(self):
        from services.search_evidence import (
            SearchEvidenceEngine,
            build_query_plan,
            select_diverse_results,
        )

        plan = build_query_plan("Python 异步编程有哪些实践经验")
        self.assertEqual(plan[0]["facet"], "primary")
        self.assertTrue(any("site:zhihu.com" in item["query"] for item in plan))

        ranked = [
            SearchEvidenceEngine.score_source("Python 异步编程 实践经验", item)
            for item in [
                {"title": "Python docs 1", "url": "https://docs.python.org/a", "snippet": "Python 异步编程 实践经验", "rank": 1},
                {"title": "Python docs 2", "url": "https://docs.python.org/b", "snippet": "Python 异步编程", "rank": 2},
                {"title": "Python docs 3", "url": "https://docs.python.org/c", "snippet": "Python 异步编程", "rank": 3},
                {"title": "知乎实践", "url": "https://zhuanlan.zhihu.com/p/1", "snippet": "Python 异步编程 实践经验", "rank": 4},
            ]
        ]
        ranked.sort(key=lambda item: item["scores"]["source_score"], reverse=True)
        selected = select_diverse_results(ranked, 4)

        self.assertLessEqual(sum(1 for item in selected if item["domain"] == "docs.python.org"), 2)
        self.assertTrue(any(item["source_type"] == "community" for item in selected))

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
        self.assertIn(first["results"][0]["source_type"], {"official", "academic"})
        self.assertEqual(first["results"][0]["credibility"], "high")
        self.assertGreaterEqual(first["quality_summary"]["high_credibility"], 1)
        self.assertEqual(first["provider_health"]["providers"][0]["provider"], "mock")
        self.assertEqual(first["provider_health"]["providers"][0]["status"], "degraded")
        self.assertEqual(calls["mock"], 2)
        self.assertTrue(any(not attempt["ok"] for attempt in first["attempts"]))

    def test_search_skips_extra_facets_after_primary_evidence_is_sufficient(self):
        from services.search_evidence import SearchEvidenceEngine, decide_search_need

        with tempfile.TemporaryDirectory() as td:
            engine = SearchEvidenceEngine(Path(td) / "cache.json", Path(td) / "rate.json")
            calls = []

            def provider(query, limit):
                calls.append(query)
                return [
                    {
                        "title": "Official current release",
                        "url": "https://docs.example.gov/release",
                        "snippet": "Current release information",
                        "rank": 1, "published_at": "2026-08-01",
                    },
                    {
                        "title": "Independent current release notes",
                        "url": "https://example.org/release-notes",
                        "snippet": "Current release information",
                        "rank": 2, "published_at": "2026-08-02",
                    },
                ], ""

            decision = decide_search_need("current release information")
            result = engine.search(
                "current release information", 5, ["mock"], {"mock": provider},
                decision=decision, use_cache=False,
            )

        self.assertTrue(result["stop_search"])
        self.assertTrue(result["expansion_skipped"])
        self.assertEqual(len(calls), 1)

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

    def test_search_policy_corpus_metrics_and_simulation_truth_boundary(self):
        from services.search_provider_benchmark_service import (
            load_corpus,
            run_provider_benchmark,
            score_answer,
            wilson_interval,
        )

        corpus = load_corpus()
        self.assertGreaterEqual(len(corpus["cases"]), 20)
        self.assertTrue(any(not item["should_search"] for item in corpus["cases"]))
        self.assertTrue(any(item.get("require_community") for item in corpus["cases"]))
        interval = wilson_interval(9, 10)
        self.assertEqual(interval["rate"], 0.9)
        self.assertLess(interval["low"], interval["rate"])

        source = {
            "title": "Community practice", "url": "https://stackoverflow.com/questions/1",
            "domain": "stackoverflow.com", "source_type": "community",
            "snippet": "Python asyncio production pitfalls", "scores": {"source_score": 0.8},
        }
        scored = score_answer(
            {"expected_terms": ["Python", "asyncio"], "require_community": True,
             "community_domains": ["stackoverflow.com"]},
            "Python asyncio pitfalls. [Community practice](https://stackoverflow.com/questions/1)",
            [source],
        )
        self.assertTrue(scored["citation_hit"])
        self.assertTrue(scored["community_source_hit"])
        self.assertEqual(scored["quality_score"], 1.0)

        with tempfile.TemporaryDirectory() as td:
            report = run_provider_benchmark(
                td, providers=["mock"], provider_funcs={}, offline_mock=True, use_cache=False,
            )
            persisted = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))

        self.assertEqual(report["mode"], "simulation_only")
        self.assertFalse(report["real_provider_evaluated"])
        self.assertFalse(report["real_provider_usable"])
        self.assertFalse(report["acceptance"]["eligible"])
        self.assertFalse(report["acceptance"]["passed"])
        self.assertEqual(report["search_trigger"]["accuracy"]["total"], report["case_count"])
        self.assertEqual(persisted["name"], "clawos-search-evidence-policy-v1")

    def test_search_policy_benchmark_tool_uses_frozen_corpus(self):
        from scripts import tool_runner

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(output):
            tool_runner.input_data = {"offline_mock": True, "out": td}
            tool_runner.handlers["web_search_policy_benchmark"]()
        report = json.loads(output.getvalue())

        self.assertEqual(report["mode"], "simulation_only")
        self.assertIn("search_trigger", report)
        self.assertIn("community_source_coverage_rate", report)
        self.assertIn("evidence_ready_answer_quality_pass_rate", report)
        self.assertFalse(report["generated_answer_quality"]["evaluated"])
        self.assertFalse(report["acceptance"]["eligible"])

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
