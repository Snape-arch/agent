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
        self.assertIn("ClawOS 工作台", console)

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
        self.assertIn("知识库", html)
        self.assertIn("记忆治理", html)
        self.assertIn("更多应用", html)
        self.assertIn("filePicker", html)
        self.assertIn("commandDrawer", html)

    def test_console_exposes_knowledge_library_as_user_rag_surface(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("knowledgeTable", html)
        self.assertIn("knowledgeSearchTable", html)
        self.assertIn("knowledgeMap", html)
        self.assertIn("保存到知识库", html)
        self.assertIn("从当前对话凝练", html)
        self.assertIn("/api/knowledge", js)
        self.assertIn("saveKnowledge", js)
        self.assertIn("searchKnowledge", js)
        self.assertIn("renderKnowledgeMap", js)

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

        self.assertIn("模型 API 配置", html)
        self.assertIn("cfgProvider", html)
        self.assertIn("cfgApiKey", html)
        self.assertIn("/api/config/model", js)
        self.assertIn("saveModelSettings", js)

    def test_console_exposes_unified_memory_governance(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/memory/items", js)
        self.assertIn("用户画像", html)
        self.assertIn("偏好记忆", html)
        self.assertIn("项目记忆", html)
        self.assertIn("经验记忆", html)
        self.assertIn("技能记忆", html)
        self.assertIn("toggleMemory", js)
        self.assertIn("memoryTable", html)
        self.assertIn("memoryReviewTable", html)
        self.assertIn("/api/memory/reviews", js)
        self.assertIn("resolveMemoryReview", js)

    def test_console_exposes_memory_and_reflection_review_actions(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("记忆审查", html)
        self.assertIn("改进审查", html)
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
        self.assertIn("/api/workspace/capabilities", js)
        self.assertIn("结构化文件生成", js)
        self.assertIn("论文学习解析文件", js)
        self.assertIn("自带 XLSX 表格", js)
        self.assertIn("自带 PPTX 演示文稿", js)
        self.assertIn("PDF 文本识别", js)
        self.assertIn("音频会议", js)


if __name__ == "__main__":
    unittest.main()
