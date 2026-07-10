import json
import tempfile
import unittest
from pathlib import Path

from memoryos.memory_store import MemoryStore
from services.paper_intelligence_service import PaperIntelligenceService, ScholarlySearchService
from security.policy import ToolSecurityPolicy


class PaperIntelligenceTests(unittest.TestCase):
    def _paper(self, store, title, result_sentence):
        doc = store.add_document(
            title=title,
            filename=f"{title}.pdf",
            file_hash=title,
            category="research",
            metadata={"structure": {"references": ["Smith et al. Evidence RAG. 2024. doi:10.1234/example"]}},
        )
        chunks = [
            "Abstract\nWe evaluate retrieval augmented generation for scholarly evidence.",
            "Methodology\nWe use a blinded evaluation with 200 claims and three annotators.",
            "Experiments\nTable 1: Citation accuracy by method\naccuracy = supported_claims / all_claims (1)",
            f"Results\n{result_sentence}",
            "Limitations\nHowever, the study is limited to English computer-science papers.",
            "References\n[1] Smith et al. Evidence RAG. 2024. doi:10.1234/example",
        ]
        for index, content in enumerate(chunks, 1):
            store.add_document_chunk(doc["id"], index, content, f"doc:{doc['id']}#page={index}&chunk=1")
        return doc

    def test_structure_claim_citations_and_cross_paper_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(str(Path(td) / "memory.db"))
            left = self._paper(store, "Positive study", "We find the reranker improves citation accuracy by 20 percent.")
            right = self._paper(store, "Negative study", "We find the reranker does not improve citation accuracy and lowers it by 10 percent.")
            service = PaperIntelligenceService(store)

            analysis = service.analyze_document(left["id"])
            self.assertGreaterEqual(analysis["quality"]["score"], 90)
            self.assertTrue(analysis["sections"]["methodology"])
            self.assertTrue(analysis["sections"]["limitations"])
            self.assertTrue(analysis["tables"])
            self.assertTrue(analysis["formulas"])
            self.assertEqual(analysis["references"][0]["doi"], "10.1234/example")
            self.assertTrue(all(item["citation"].startswith(f"doc:{left['id']}#page=") for item in analysis["claims"]))

            aligned = service.align_claims(
                ["The reranker improves citation accuracy by 20 percent."],
                [left["id"]],
            )
            self.assertEqual(aligned["gate"], "pass")
            self.assertEqual(aligned["alignments"][0]["citation"], f"doc:{left['id']}#page=4&chunk=1")

            comparison = service.compare_documents([left["id"], right["id"]])
            self.assertTrue(comparison["potential_contradictions"])
            self.assertEqual(comparison["gate"], "review_required")

    def test_search_deduplicates_and_ranks_provider_consensus(self):
        def fake_json(url, _headers):
            if "crossref" in url:
                return {"message": {"items": [{"DOI": "10.1/a", "title": ["Grounded scholarly RAG"], "published": {"date-parts": [[2025]]}, "is-referenced-by-count": 12}]}}
            if "openalex" in url:
                return {"results": [{"doi": "https://doi.org/10.1/a", "title": "Grounded scholarly RAG", "publication_year": 2025, "cited_by_count": 12, "open_access": {"is_oa": True}, "best_oa_location": {"pdf_url": "https://papers.example/a.pdf"}}]}
            return {"data": []}

        with tempfile.TemporaryDirectory() as td:
            service = ScholarlySearchService(Path(td), http_json=fake_json)
            result = service.search("grounded scholarly RAG", providers=["crossref", "openalex"])
            self.assertEqual(result["count"], 1)
            self.assertEqual(set(result["results"][0]["sources"]), {"crossref", "openalex"})
            self.assertEqual(result["quality"]["multi_source_count"], 1)

    def test_download_validates_pdf_and_writes_atomically(self):
        pdf = b"%PDF-1.7\nminimal-test-payload"

        def fake_binary(url, _headers, _max_bytes):
            return pdf, "application/pdf", url

        with tempfile.TemporaryDirectory() as td:
            service = ScholarlySearchService(
                Path(td) / "cache",
                http_binary=fake_binary,
                resolver=lambda _host: ["8.8.8.8"],
            )
            result = service.download_open_access(
                {"title": "Paper", "doi": "10.1234/paper", "open_access_pdf_url": "https://papers.example/paper.pdf", "open_access_verified_by": "openalex"},
                Path(td) / "papers",
            )
            self.assertTrue(Path(result["path"]).is_file())
            self.assertEqual(Path(result["path"]).read_bytes(), pdf)
            self.assertEqual(len(list((Path(td) / "papers").glob("*.part"))), 0)

    def test_download_rejects_private_address(self):
        with tempfile.TemporaryDirectory() as td:
            service = ScholarlySearchService(Path(td), resolver=lambda _host: ["127.0.0.1"])
            with self.assertRaises(ValueError):
                service.download_open_access(
                    {"open_access_pdf_url": "https://localhost/paper.pdf", "open_access_verified_by": "openalex"},
                    Path(td) / "papers",
                )

    def test_download_rejects_unproven_open_access_url(self):
        with tempfile.TemporaryDirectory() as td:
            service = ScholarlySearchService(Path(td), resolver=lambda _host: ["8.8.8.8"])
            with self.assertRaisesRegex(ValueError, "provenance"):
                service.download_open_access(
                    {"open_access_pdf_url": "https://papers.example/paper.pdf"},
                    Path(td) / "papers",
                )

    def test_network_and_download_tools_are_confirmation_gated(self):
        policy = ToolSecurityPolicy()
        search = policy.evaluate("scholarly_search", {"query": "citation fidelity"})
        download = policy.evaluate("scholarly_download", {"output_dir": tempfile.gettempdir()})
        self.assertTrue(search["allowed"])
        self.assertEqual(search["decision"], "confirm")
        self.assertTrue(download["allowed"])
        self.assertEqual(download["decision"], "confirm")
        self.assertEqual(download["risk_level"], "high")


if __name__ == "__main__":
    unittest.main()
