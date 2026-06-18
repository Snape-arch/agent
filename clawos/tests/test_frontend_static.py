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

        self.assertIn("让智能体开始工作", home)
        self.assertIn('href="/product"', home)
        self.assertIn("把 Agent 的每次行动", product)
        self.assertIn('href="/console"', product)
        self.assertIn("ClawOS 工作台", console)

    def test_pages_use_clawos_assets_and_motion(self):
        home = self.read_page("index.html")
        product = self.read_page("product.html")

        self.assertIn("magazine-backdrop", home)
        self.assertIn("d55c96717921508cafd61730a1623e08.jpg", home)
        self.assertIn("starfield", home)
        self.assertIn("layer", home)
        self.assertIn("Evidence Grid", product)
        self.assertIn("Runtime Map", product)
        self.assertIn("可追踪、可审计、可回滚", product)

    def test_console_has_polished_chinese_console_copy(self):
        html = self.read_page("console.html")

        self.assertIn("ClawOS 工作台", html)
        self.assertIn("状态总览", html)
        self.assertIn("资料库", html)
        self.assertIn("搜索聊天", html)
        self.assertIn("项目", html)
        self.assertIn("更多应用", html)
        self.assertIn("filePicker", html)
        self.assertIn("工具路由", html)
        self.assertIn("运行轨迹", html)
        self.assertIn("冻结基准", html)
        self.assertIn("场景工作流", html)
        self.assertIn("技能审查", html)

    def test_pages_have_no_common_mojibake_fragments(self):
        combined = "\n".join(
            self.read_page(name)
            for name in ("index.html", "product.html", "console.html", "assets/console.js")
        )

        for fragment in ("閺", "闁", "瀹", "閿", "锟", "杩", "璁", "鎺"):
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

    def test_console_exposes_unified_memory_management(self):
        html = self.read_page("console.html")
        js = self.read_page("assets/console.js")

        self.assertIn("/api/memory/items", js)
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
