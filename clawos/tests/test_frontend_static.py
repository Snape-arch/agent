from pathlib import Path
import unittest


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


class FrontendStaticTests(unittest.TestCase):
    def read_page(self, name: str) -> str:
        return (STATIC_DIR / name).read_text(encoding="utf-8")

    def test_frontend_is_split_into_layered_pages(self):
        home = self.read_page("index.html")
        product = self.read_page("product.html")
        console = self.read_page("console.html")

        self.assertIn('href="/product"', home)
        self.assertIn("magazine-backdrop", home)
        self.assertIn('href="/console"', product)
        self.assertIn("Evidence Grid", product)
        self.assertIn("Runtime Map", product)
        self.assertIn('class="console-page aether-console"', console)

    def test_pages_use_clawos_assets_and_motion(self):
        home = self.read_page("index.html")
        product = self.read_page("product.html")

        self.assertIn("d55c96717921508cafd61730a1623e08.jpg", home)
        self.assertIn("starfield", home)
        self.assertIn("layer", home)
        self.assertIn("evidence", product.lower())
        self.assertIn("runtime", product.lower())

    def test_console_has_chat_first_information_architecture(self):
        html = self.read_page("console.html")

        self.assertIn('href="/assets/site.css"', html)
        self.assertIn('href="/assets/console.css"', html)
        self.assertIn('data-view="chat"', html)
        self.assertIn('data-view="search"', html)
        self.assertIn('data-view="knowledge"', html)
        self.assertIn('data-view="projects"', html)
        self.assertIn("view-knowledge", html)
        self.assertIn("view-memory", html)
        self.assertIn("filePicker", html)
        self.assertIn("commandDrawer", html)

    def test_console_exposes_knowledge_library_as_user_rag_surface(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        for token in (
            "knowledgeTable",
            "knowledgeSearchTable",
            "knowledgeMap",
            "knowledgeEdges",
            "knowledgeFilePicker",
            "knowledgeSessionSelect",
            "knowledgeStatus",
            "attachmentTray",
            ):
            self.assertIn(token, html)

        for token in (
            "/api/knowledge",
            "handleKnowledgeFiles",
            "draftKnowledgeFromSelectedSession",
            "renderKnowledgeSessionSelect",
            "saveKnowledge",
            "searchKnowledge",
            "renderKnowledgeMap",
            "appendKnowledgeToPrompt",
            "deleteKnowledgeItem",
            "editingKnowledgeId",
        ):
            self.assertIn(token, js)

        self.assertIn(".knowledge-toolbar", css)
        self.assertIn(".import-drop", css)
        self.assertIn(".session-import", css)
        self.assertIn("Overflow safety layer", css)
        self.assertIn(".aether-console #view-knowledge .section-block", css)
        self.assertIn("max-height:min(42vh,420px)", css)
        self.assertIn("overflow-y:auto", css)
        self.assertIn("display:block", css)

    def test_chat_file_picker_uses_attachment_context_not_prompt_paste(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")
        css = self.read_page("assets/console.css")

        self.assertIn("attachmentTray", html)
        self.assertIn("Agent 会作为上下文自动阅读", html)
        self.assertIn("chatAttachments", js)
        self.assertIn("clawos_attachments", js)
        self.assertIn("/api/documents/upload", js)
        self.assertIn("new FormData", js)
        self.assertIn("document_id", js)
        self.assertIn("renderAttachmentTray", js)
        self.assertIn("attachment-chip", css)
        file_handler = js.split("async function handlePickedFiles", 1)[1].split("function setMemoryType", 1)[0]
        self.assertNotIn('prompt").value=($("prompt").value', file_handler)
        self.assertNotIn(".text()", file_handler)

    def test_pages_have_no_common_mojibake_fragments(self):
        combined = "\n".join(
            self.read_page(name)
            for name in ("console.html", "assets/console.js", "assets/console.css")
        )

        for fragment in ("闁", "闂", "鐎", "閿", "鏉", "鐠", "閹"):
            self.assertNotIn(fragment, combined)

    def test_console_exposes_tool_trace_and_confirmation_ui(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/tools/executions", js)
        self.assertIn("needs_confirmation", js)
        self.assertIn("confirmPending", html + js)
        self.assertIn("toolExecTable", html)

    def test_console_exposes_model_api_settings(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("cfgProvider", html)
        self.assertIn("cfgApiKey", html)
        self.assertIn("/api/config/model", js)
        self.assertIn("saveModelSettings", js)

    def test_console_exposes_unified_memory_governance(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/memory/items", js)
        self.assertIn("memType", html)
        self.assertIn("memKey", html)
        self.assertIn("memValue", html)
        self.assertIn("toggleMemory", js)
        self.assertIn("memoryTable", html)
        self.assertIn("memoryReviewTable", html)
        self.assertIn("/api/memory/reviews", js)
        self.assertIn("resolveMemoryReview", js)

    def test_console_exposes_memory_and_reflection_review_actions(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("reflectionReviewTable", html)
        self.assertIn("/api/reflection/improvements", js)
        self.assertIn("transitionReflection", js)
        self.assertIn("validateReflection", js)
        self.assertIn("publishReflection", js)
        self.assertIn("rollbackReflection", js)

    def test_console_exposes_task_trace_panel(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/tasks", js)
        self.assertIn("/api/tasks/stream", js)
        self.assertIn("/api/tasks/recover", js)
        self.assertIn("/api/tasks/queue", js)
        self.assertIn("/api/tasks/queue/claim", js)
        self.assertIn("/cancel", js)
        self.assertIn("/retry", js)
        self.assertIn("taskTable", html)
        self.assertIn("taskQueueTable", html)
        self.assertIn("taskStepTable", html)
        self.assertIn("taskEventTable", html)
        self.assertIn("claimTask", js)
        self.assertIn("loadTaskQueue", js)
        self.assertIn("loadTasks", js)
        self.assertIn("task_id", js)

    def test_console_exposes_benchmark_and_skill_review_inbox(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("benchmarkSuiteTable", html)
        self.assertIn("benchmarkRunTable", html)
        self.assertIn("/api/benchmarks/scenarios/run", js)
        self.assertIn("/api/skills/evolution/review-inbox", js)
        self.assertIn("promoteSkill", js)
        self.assertIn("reviewSkill", js)

    def test_console_exposes_scene_capability_check(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("capabilityTable", html)
        self.assertIn("sceneBoundaryTable", html)
        self.assertIn("modelHealthTable", html)
        self.assertIn("toolAccuracyTable", html)
        self.assertIn("routingPolicyTable", html)
        self.assertIn("/api/workspace/capabilities", js)
        self.assertIn("/api/model/health", js)
        self.assertIn("/api/tools/accuracy", js)
        self.assertIn("/api/routing/policy", js)
        self.assertIn("联网搜索/网页抓取", js)
        self.assertIn("web_fetch", self.read_page("../functions.jsonl"))
        self.assertIn("document_understanding", js)
        self.assertIn("office_artifacts", js)
        self.assertIn("meeting_audio", js)


if __name__ == "__main__":
    unittest.main()
