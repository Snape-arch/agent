from pathlib import Path
import unittest


class FrontendStaticTests(unittest.TestCase):
    def test_workspace_has_polished_chinese_console_copy(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("ClawOS 工作台", html)
        self.assertIn("状态总览", html)
        self.assertIn("记忆中枢", html)
        self.assertIn("工具路由", html)
        self.assertIn("运行轨迹", html)

    def test_workspace_has_no_common_mojibake_fragments(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

        for fragment in ("鏉", "閺", "閿", "閵", "閳", "宸", "鏅", "锛", "�"):
            self.assertNotIn(fragment, html)

    def test_workspace_exposes_tool_trace_and_confirmation_ui(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("/api/tools/executions", html)
        self.assertIn("needs_confirmation", html)
        self.assertIn("confirmPending", html)
        self.assertIn("toolExecTable", html)

    def test_workspace_exposes_unified_memory_management(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("/api/memory/items", html)
        self.assertIn("Project", html)
        self.assertIn("Experience", html)
        self.assertIn("Skill", html)
        self.assertIn("toggleMemory", html)
        self.assertIn("memoryTable", html)

    def test_workspace_exposes_task_trace_panel(self):
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn("/api/tasks", html)
        self.assertIn("taskTable", html)
        self.assertIn("loadTasks", html)
        self.assertIn("task_id", html)


if __name__ == "__main__":
    unittest.main()
